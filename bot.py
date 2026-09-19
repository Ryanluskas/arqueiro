"""
bot.py â€” Parceiro Santander | SimulaÃ§Ã£o de CrÃ©dito Consignado
"""

import os
import re
import time
import random
import logging
import threading
import configparser
import queue as _queue_mod
from datetime import datetime

try:
    import winsound as _winsound
    _WINSOUND = True
except ImportError:
    _WINSOUND = False

import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

try:
    from playwright_stealth import stealth_sync
    _STEALTH_LIB = True
except ImportError:
    _STEALTH_LIB = False

import otp_flow

try:
    import gmail_otp as _gmail_otp
    _GMAIL_OTP = True
except ImportError:
    _GMAIL_OTP = False

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
ARQUIVO_ENTRADA = "clientes.csv"
RESULTADO_XLSX  = "resultado_filtrado.xlsx"
COM_REFIN_XLSX  = "com_refinanciamento.xlsx"
PROGRESSO_XLSX  = "_progresso.xlsx"   # estado completo p/ retomar (uso interno â€” nÃ£o abrir)
DEBUG_MARGEM    = True   # salva _debug_margem.html quando nÃ£o conseguir ler a margem
URL_FORMULARIO  = "https://www.parceirosantander.com.br/spa-base/logged-area/recommendation/"
URL_LANDING     = "https://www.parceirosantander.com.br/spa-base/landing-page"
PASTA_DO_BOT    = os.path.dirname(os.path.abspath(__file__))
CONFIG_INI      = os.path.join(PASTA_DO_BOT, "config.ini")
CREDENCIAIS_INI = os.path.join(PASTA_DO_BOT, "credenciais.ini")

# Caminhos padrao desta maquina. Em outro PC eles nao existem -- por isso o
# config.ini (escrito pela aba Configuracoes da GUI) tem a ultima palavra.
PERFIL_DIR      = r"C:\Users\Ryyan\AppData\Local\BraveSoftware\Brave-Browser\User Data"
BRAVE_EXE       = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"


def carregar_config() -> tuple[str, str]:
    """Le config.ini e aplica navegador/perfil desta instalacao.

    Devolve (executavel, perfil) ja' aplicados nas globais, para a GUI mostrar
    o que vai ser usado de fato.
    """
    global PERFIL_DIR, BRAVE_EXE
    cfg = configparser.ConfigParser(interpolation=None)
    try:
        if cfg.read(CONFIG_INI, encoding="utf-8") and cfg.has_section("navegador"):
            exe    = cfg.get("navegador", "executavel", fallback="").strip()
            perfil = cfg.get("navegador", "perfil",     fallback="").strip()
            if exe:
                BRAVE_EXE = exe
            if perfil:
                PERFIL_DIR = perfil
    except Exception as e:
        logging.getLogger(__name__).warning(f"Falha ao ler config.ini: {e}")
    return BRAVE_EXE, PERFIL_DIR
TIMEOUT         = 25_000


def _carregar_credenciais() -> tuple[str, str]:
    """LÃª CPF/senha de variÃ¡vel de ambiente ou de credenciais.ini (fora do cÃ³digo).

    O caminho Ã© absoluto (pasta do bot): quando a GUI Ã© aberta de outro
    diretÃ³rio, o arquivo relativo nÃ£o era encontrado e o bot seguia sem
    credencial, em silÃªncio.
    """
    cpf   = os.environ.get("SANTANDER_CPF", "").strip()
    senha = os.environ.get("SANTANDER_SENHA", "").strip()
    if not (cpf and senha):
        cfg = configparser.ConfigParser(interpolation=None)
        try:
            if cfg.read(CREDENCIAIS_INI, encoding="utf-8") and cfg.has_section("acesso"):
                cpf   = cpf   or cfg.get("acesso", "cpf",   fallback="").strip()
                senha = senha or cfg.get("acesso", "senha", fallback="").strip()
        except Exception as e:
            logging.getLogger(__name__).warning(f"Falha ao ler credenciais.ini: {e}")
    if not (cpf and senha):
        print("[AVISO] Credenciais nÃ£o configuradas. Defina SANTANDER_CPF/SANTANDER_SENHA "
              "ou crie credenciais.ini (veja credenciais.ini.exemplo).")
    return cpf, senha


CPF_ACESSO, SENHA_ACESSO = _carregar_credenciais()


def recarregar_credenciais() -> bool:
    """RelÃª credenciais.ini sem reiniciar o programa.

    A GUI grava o arquivo e chama isto; antes, as credenciais eram lidas uma
    Ãºnica vez na importaÃ§Ã£o e sÃ³ valiam na prÃ³xima abertura.
    """
    global CPF_ACESSO, SENHA_ACESSO
    CPF_ACESSO, SENHA_ACESSO = _carregar_credenciais()
    return bool(CPF_ACESSO and SENHA_ACESSO)


def recarregar_config() -> tuple[str, str]:
    """Idem para o config.ini (navegador e perfil)."""
    return carregar_config()


carregar_config()

BURST_MIN    = 8    # timing conservador (revertido da v13 â€” evita bloqueio do site)
BURST_MAX    = 12
DESCANSO_MIN = 45
DESCANSO_MAX = 70

COEFICIENTE  = 0.02100   # coeficiente para calcular valor liberado no refinanciamento

STEALTH_JS = """
try { Object.defineProperty(navigator, 'webdriver', {get: () => undefined, configurable: true}); } catch(e) {}
if (!window.chrome) window.chrome = {};
if (!window.chrome.runtime) window.chrome.runtime = {};
const _rt = window.chrome.runtime;
if (!_rt.connect)     _rt.connect     = function(){return {onDisconnect:{addListener:function(){}},postMessage:function(){}}};
if (!_rt.sendMessage) _rt.sendMessage = function(){};
if (!_rt.getManifest) _rt.getManifest = function(){return {}};
if (!_rt.onConnect)   _rt.onConnect   = {addListener:function(){}};
if (!_rt.onMessage)   _rt.onMessage   = {addListener:function(){}};
if (!window.chrome.loadTimes) window.chrome.loadTimes = function(){return null};
if (!window.chrome.csi) window.chrome.csi = function(){return {startE:Date.now(),onloadT:Date.now(),pageT:1,tran:15}};
if (!window.chrome.app) window.chrome.app = {isInstalled:false,getDetails:function(){return null},getIsInstalled:function(){return false}};
try { ['cdc_adoQpoasnfa76pfcZLmcfl_Array','cdc_adoQpoasnfa76pfcZLmcfl_Promise',
       '__playwright','__pw_manual','domAutomation','domAutomationController'].forEach(k=>{try{delete window[k]}catch(e){}});
} catch(e) {}
try {
    const _origPQ = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.__proto__.query = (p) =>
        p.name === 'notifications'
            ? Promise.resolve({state: Notification.permission, onchange: null})
            : _origPQ(p);
} catch(e) {}
const _def = (obj, prop, val) => { try { Object.defineProperty(obj, prop, {get: ()=>val, configurable:true}); } catch(e) {} };
_def(navigator, 'languages',          ['pt-BR','pt','en-US','en']);
_def(navigator, 'hardwareConcurrency', 8);
_def(navigator, 'platform',           'Win32');
_def(navigator, 'deviceMemory',       8);
_def(navigator, 'maxTouchPoints',     0);
_def(navigator, 'vendor',            'Google Inc.');
"""

# ---------------------------------------------------------------------------
# CANAIS GUI
# ---------------------------------------------------------------------------
python_stop_event = threading.Event()   # GUI seta para parar
_start_event      = threading.Event()   # reservado
_otp_queue        = _queue_mod.Queue()  # GUI envia OTP
_status_queue     = _queue_mod.Queue()  # Bot envia status para GUI
_pause_event      = threading.Event()   # GUI seta para pausar
_aguardando_otp   = threading.Event()   # segura o fechador de abas na tela do codigo
_parar_gmail      = threading.Event()   # avisa o watcher que nao precisa mais
_gmail_thread     = None                # watcher do Gmail (um por vez)

_ultimo_keepalive = 0.0

logging.basicConfig(
    filename="bot_log.txt",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    encoding="utf-8",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# STEALTH
# ---------------------------------------------------------------------------
def _aplicar_stealth(page):
    try:
        if _STEALTH_LIB:
            stealth_sync(page)
    except Exception:
        pass
    try:
        page.add_init_script(STEALTH_JS)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def _pausa(a=0.4, b=0.9):
    time.sleep(random.uniform(a, b))

def _mover_mouse(page):
    try:
        page.mouse.move(random.randint(180, 1050), random.randint(120, 660))
    except Exception:
        pass

def _keepalive(page):
    global _ultimo_keepalive
    agora = time.time()
    if agora - _ultimo_keepalive > 90:
        try:
            page.evaluate("fetch(window.location.href, {method:'HEAD'}).catch(()=>{})")
        except Exception:
            pass
        _ultimo_keepalive = agora

def _digitar(locator, texto: str):
    try:
        locator.click(force=True)
        locator.fill("")
        locator.fill(texto)
        try:
            locator.evaluate("el => { Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(el, arguments[0]); ['input','change','blur'].forEach(e => el.dispatchEvent(new Event(e, {bubbles:true}))); }", texto)
        except:
            pass
    except Exception:
        pass

def _url_real(page) -> str:
    try:
        return page.evaluate("window.location.href")
    except Exception:
        return page.url

def sessao_expirada(page) -> bool:
    # PÃ¡gina fechada devolve URL do cache e passava por "sessÃ£o viva": toda
    # aÃ§Ã£o seguinte estourava sem ninguÃ©m tentar relogar.
    try:
        if page.is_closed():
            return True
    except Exception:
        pass
    url = _url_real(page).lower()
    return "landing-page" in url or "/login" in url or "logout" in url


def _paginas_logadas(ctx) -> list:
    """Todas as abas que parecem estar dentro do portal, agora."""
    dentro = []
    for p in ctx.pages:
        try:
            if p.is_closed():
                continue
            url = _url_real(p).lower()
            if "logged-area" in url and "landing" not in url and "/login" not in url:
                dentro.append(p)
        except Exception:
            continue
    return dentro


def _pagina_logada(ctx):
    """Alguma aba jÃ¡ estÃ¡ DENTRO do portal (qualquer tela logada).

    `_encontrar_pagina_formulario` exige a rota do formulÃ¡rio; o portal, depois
    do login, para em `/logged-area/home`. Usar aquela funÃ§Ã£o como prova de
    login fazia o bot concluir "ainda expirado" estando logado, e girar horas
    no laÃ§o de relogin (hÃ¡ 39h de silÃªncio no bot_log.txt por causa disso).
    """
    dentro = _paginas_logadas(ctx)
    return dentro[0] if dentro else None

def _encontrar_pagina_formulario(ctx):
    for p in ctx.pages:
        try:
            url = _url_real(p).lower()
            if "recommendation" in url and "landing" not in url and "login" not in url:
                return p
        except Exception:
            continue
    return None

def _achar_pagina_login(ctx):
    for p in ctx.pages:
        try:
            url = p.url.lower()
            if any(k in url for k in ["openid", "/login", "corp/protocol", "keycloak", "/auth?"]):
                return p
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# AUTO-LOGIN
# ---------------------------------------------------------------------------
def _clicar_acessar_portal(page) -> bool:
    for sel in ['button:has-text("Acessar o Portal")', 'a:has-text("Acessar o Portal")',
                ':has-text("Acessar o Portal")']:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=3000):
                loc.click()
                return True
        except Exception:
            pass
    return False

# ---------------------------------------------------------------------------
# CODIGO DE VERIFICACAO (OTP) â€” apoio
# ---------------------------------------------------------------------------
def marcar_tela_de_codigo(momento: float = None) -> None:
    """Registra QUANDO a tela do cÃ³digo apareceu.

    CÃ³digo enfileirado bem antes disso Ã© de outra tentativa (e o portal jÃ¡ nÃ£o
    aceita); cÃ³digo digitado segundos antes da tela continua valendo.
    """
    global _marco_da_tela
    _marco_da_tela = momento if momento is not None else time.time()


def _drenar_fila_otp() -> int:
    """Joga fora codigo que sobrou de uma tentativa anterior.

    OTP vale poucos minutos. A fila so' era limpa no botao Iniciar da GUI,
    entao um codigo velho era digitado numa tela nova e o log dizia "sucesso".
    """
    descartados = 0
    while True:
        try:
            _otp_queue.get_nowait()
            descartados += 1
        except _queue_mod.Empty:
            break
    if descartados:
        otp_flow.etapa("drain_queue", "descartar", "ok", codigos=descartados)
    return descartados


# Um cÃ³digo do Santander vale poucos minutos; depois disso nÃ£o adianta tentar.
IDADE_MAXIMA_CODIGO = 120.0
# Folga para o operador que digita ANTES de a tela aparecer (acontece sempre:
# o e-mail chega antes de o portal renderizar a tela).
GRACA_ANTES_DA_TELA = 60.0
_marco_da_tela = 0.0


def enfileirar_codigo(codigo: str) -> None:
    """PÃµe o cÃ³digo na fila com a hora de chegada.

    O carimbo Ã© o que permite distinguir "o operador acabou de digitar" de
    "sobrou da tentativa anterior" â€” antes o laÃ§o drenava a fila inteira no
    inÃ­cio e engolia o cÃ³digo recÃ©m-digitado.
    """
    _otp_queue.put((str(codigo or "").strip(), time.time()))


def _proximo_codigo():
    """PrÃ³ximo cÃ³digo ainda vÃ¡lido; descarta em silÃªncio os que expiraram."""
    while True:
        try:
            item = _otp_queue.get_nowait()
        except _queue_mod.Empty:
            return None
        if isinstance(item, (tuple, list)) and len(item) == 2:
            codigo, carimbo = item
        else:                       # formato antigo: assume que chegou agora
            codigo, carimbo = item, time.time()
        codigo = str(codigo or "").strip()
        if not codigo:
            continue
        carimbo = float(carimbo or 0)
        idade = time.time() - carimbo
        if idade > IDADE_MAXIMA_CODIGO:
            otp_flow.etapa("queue", "descartar_velho", "expired",
                           idade=f"{int(idade)}s")
            continue
        # CÃ³digo que jÃ¡ existia antes desta tela Ã© de outra tentativa.
        if _marco_da_tela and carimbo < _marco_da_tela - GRACA_ANTES_DA_TELA:
            otp_flow.etapa("queue", "descartar_de_outra_tela", "stale",
                           idade=f"{int(idade)}s")
            continue
        return codigo


def _iniciar_watcher_gmail() -> None:
    """Uma thread de leitura do Gmail por vez.

    As flags eram locais da funcao: cada nova tentativa de login criava outra
    thread, e as duas competiam pela mesma caixa (a primeira marca o e-mail
    como lido e a segunda reporta "nao encontrei").
    """
    global _gmail_thread
    if not _GMAIL_OTP:
        return
    if _gmail_thread is not None and _gmail_thread.is_alive():
        return

    _parar_gmail.clear()
    inicio = time.time()

    def _ler():
        try:
            otp_flow.etapa("gmail", "iniciar", "ok")
            _status_queue.put({"type": "log", "msg": "ðŸ” Buscando o cÃ³digo no Gmail..."})
            codigo = _gmail_otp.aguardar_otp(timeout=85, intervalo=5,
                                             desde=inicio, parar=_parar_gmail)
            if codigo:
                enfileirar_codigo(codigo)
                otp_flow.etapa("gmail", "encontrado", "ok",
                               codigo=otp_flow._mascarar(codigo))
                _status_queue.put({"type": "log", "msg": "âœ“ CÃ³digo encontrado no Gmail."})
            else:
                otp_flow.etapa("gmail", "busca", "not_found")
                _status_queue.put({"type": "log",
                                   "msg": "âš  NÃ£o achei o cÃ³digo no Gmail â€” digite Ã  mÃ£o."})
        except Exception as ex:
            otp_flow.etapa("gmail", "erro", "error", erro=str(ex)[:120])
            _status_queue.put({"type": "log", "msg": f"âš  Erro ao ler o Gmail: {ex}"})

    _gmail_thread = threading.Thread(target=_ler, daemon=True, name="gmail-otp-watcher")
    _gmail_thread.start()


def _avisar_que_precisa_de_codigo() -> None:
    _status_queue.put({"type": "otp_needed"})
    if _WINSOUND:
        try:
            for _ in range(3):
                _winsound.Beep(1000, 400)
                time.sleep(0.1)
        except Exception:
            pass


def aguardar_codigo_e_entrar(ctx, prazo_segundos: int = 90) -> bool:
    """Espera o portal pedir o cÃ³digo, usa o cÃ³digo que chegar, e conclui.

    Cada volta faz trÃªs perguntas, nesta ordem: jÃ¡ entrei? a tela do cÃ³digo
    apareceu? chegou cÃ³digo novo? SÃ³ entÃ£o tenta preencher â€” e o cÃ³digo sÃ³ sai
    da fila quando existe uma tela para usÃ¡-lo, em vez de ser consumido e
    perdido em qualquer desvio, como acontecia antes.

    Devolve True sÃ³ quando o portal aceitou o cÃ³digo (ou o login se resolveu
    sozinho). Nada aqui declara sucesso por ter clicado num botÃ£o.
    """
    _aguardando_otp.clear()
    otp_avisado = False
    canal_escolhido = False
    pendente = None
    tentativas_do_codigo = 0
    prazo = time.time() + prazo_segundos

    # Foto das abas que JA' estavam logadas: uma aba velha esquecida em
    # /logged-area/ fazia o bot declarar "logado" no primeiro segundo, sem
    # nunca ter digitado o cÃ³digo.
    ja_logadas = {id(p) for p in _paginas_logadas(ctx)}

    def _entrou_agora():
        for p in _paginas_logadas(ctx):
            if id(p) not in ja_logadas:
                return p
        return None

    try:
        while time.time() < prazo:
            if python_stop_event.is_set():
                otp_flow.etapa("wait_code", "parar", "stop_event")
                return False
            time.sleep(1)

            if _entrou_agora() is not None:
                logger.info("Auto-login: CPF+senha OK")
                otp_flow.etapa("login", "pos_credenciais", "ok")
                _status_queue.put({"type": "login_ok"})
                return True

            # Tela "Escolha sua forma de receber o cÃ³digo": sem passar por
            # ela, nenhum cÃ³digo Ã© enviado e a tela do cÃ³digo nunca aparece.
            if not canal_escolhido and otp_flow.tela_de_escolha_de_canal(ctx):
                canal_escolhido = otp_flow.escolher_canal(ctx, preferir_email=True)
                if canal_escolhido:
                    _status_queue.put({"type": "log",
                                       "msg": "ðŸ“§ Pedi o cÃ³digo por e-mail."})
                    marcar_tela_de_codigo()
                    _iniciar_watcher_gmail()
                continue

            alvo = otp_flow.localizar_campo(ctx)
            if alvo is not None and not otp_avisado:
                otp_avisado = True
                _aguardando_otp.set()       # segura o fechador de abas
                marcar_tela_de_codigo()     # corta cÃ³digos de tentativas anteriores
                otp_flow.etapa("detect_screen", alvo.seletor, "ok",
                               tipo=alvo.tipo, campos=alvo.quantidade)
                _status_queue.put({"type": "log",
                                   "msg": "ðŸ” O portal pediu o cÃ³digo de verificaÃ§Ã£o."})
                _avisar_que_precisa_de_codigo()
                _iniciar_watcher_gmail()

            novo = _proximo_codigo()
            if novo:
                pendente, tentativas_do_codigo = novo, 0
            if not pendente:
                continue
            if alvo is None:
                continue                    # guarda o cÃ³digo atÃ© a tela existir

            tentativas_do_codigo += 1
            resultado = otp_flow.preencher_otp(
                ctx, pendente,
                esta_logado=lambda: _entrou_agora() is not None,
                tentativas=2)

            if resultado.ok:
                logger.info("Auto-login: cÃ³digo aceito")
                _status_queue.put({"type": "log", "msg": "âœ“ CÃ³digo aceito."})
                _status_queue.put({"type": "login_ok"})
                return True

            # NÃ£o deu: o cÃ³digo sÃ³ volta a ser tentado se ainda servir.
            if resultado.reutilizavel and tentativas_do_codigo < 2:
                _status_queue.put({"type": "log",
                                   "msg": f"âš  NÃ£o consegui usar o cÃ³digo ({resultado.desfecho}); tentando de novo."})
                time.sleep(3)
                continue

            pendente = None
            motivo = ("o portal recusou o cÃ³digo"
                      if resultado.desfecho == "recusado"
                      else f"falhei em {resultado.desfecho}")
            _status_queue.put({"type": "log",
                               "msg": f"âœ— {motivo}. Digite o cÃ³digo novamente."})
            if resultado.diagnostico:
                _status_queue.put({"type": "log",
                                   "msg": f"ðŸ›ˆ DiagnÃ³stico salvo: {os.path.basename(resultado.diagnostico)}"})
            _avisar_que_precisa_de_codigo()
    finally:
        _aguardando_otp.clear()
        _parar_gmail.set()       # o watcher nao precisa mais ler a caixa

    otp_flow.etapa("wait_code", "prazo", "timeout")
    _status_queue.put({"type": "log",
                       "msg": "â° O prazo do cÃ³digo acabou sem concluir o login."})
    return False


def _so_digitos(texto: str) -> str:
    return "".join(ch for ch in str(texto or "") if ch.isdigit())


def _esperar_visivel(pagina, seletor: str, ms: int = 8000):
    """Espera o campo aparecer DE VERDADE.

    `is_visible(timeout=...)` ignora o timeout e responde na hora: numa pÃ¡gina
    que ainda estava renderizando, os trÃªs seletores davam False e o login
    desistia em silÃªncio.
    """
    try:
        pagina.wait_for_selector(seletor, state="visible", timeout=ms)
        return pagina.locator(seletor).first
    except Exception:
        return None


def _preencher_campo_login(pagina, seletores, valor: str, nome: str,
                           so_digitos: bool = False) -> bool:
    """Escreve e CONFERE. Devolve False sem inventar sucesso.

    O campo do CPF tem mÃ¡scara: mandar "709.589.331-46" pronto faz a mÃ¡scara
    formatar por cima e o valor sair invÃ¡lido -- o botÃ£o Entrar fica cinza e
    nada acontece. Por isso digitamos sÃ³ os dÃ­gitos, tecla a tecla, e
    comparamos ignorando a pontuaÃ§Ã£o que a prÃ³pria mÃ¡scara coloca.
    """
    if not valor:
        otp_flow.etapa("login", f"{nome}", "sem_credencial")
        _status_queue.put({"type": "log",
                           "msg": f"âœ— {nome.upper()} nÃ£o configurado â€” aba ConfiguraÃ§Ãµes."})
        return False

    escrever = _so_digitos(valor) if so_digitos else valor

    def confere(campo) -> bool:
        try:
            lido = campo.input_value() or ""
        except Exception:
            return False
        if so_digitos:
            return _so_digitos(lido) == _so_digitos(valor)
        return lido == valor

    for seletor in seletores:
        campo = _esperar_visivel(pagina, seletor, 8000 if seletor is seletores[0] else 2000)
        if campo is None:
            continue
        for tecnica in ("teclado", "fill"):
            try:
                campo.click(force=True, timeout=3000)
                campo.fill("")
                if tecnica == "teclado":
                    campo.type(escrever, delay=60)
                else:
                    campo.fill(escrever)
            except Exception as e:
                otp_flow.etapa("login", f"{nome}:{tecnica}", "error", erro=str(e)[:80])
                continue
            if confere(campo):
                otp_flow.etapa("login", f"{nome}:{tecnica}", "ok", seletor=seletor)
                return True
            otp_flow.etapa("login", f"{nome}:{tecnica}", "verification_failed",
                           seletor=seletor)
    return False


def tentar_login_automatico(page) -> bool:
    ctx = page.context

    # Fase 1: SSO silencioso
    try:
        for t in ["Continuar", "Fechar", "Ok", "Entendi", "Aceitar"]:
            try:
                b = page.locator(f'button:has-text("{t}")')
                if b.count() > 0 and b.first.is_visible(timeout=200):
                    b.first.click()
            except Exception:
                pass

        _clicar_acessar_portal(page)

        for _ in range(16):
            time.sleep(0.5)
            if _encontrar_pagina_formulario(ctx) is not None:
                logger.info("Auto-login: SSO OK")
                _status_queue.put({"type": "login_ok"})
                return True
    except Exception as e:
        logger.warning(f"Auto-login SSO: {e}")

    # Fase 2: CPF + senha
    try:
        lp = _achar_pagina_login(ctx) or page
        _aplicar_stealth(lp)

        try:
            lp.wait_for_selector('input', timeout=8000)
        except Exception:
            return False
        time.sleep(0.8)

        # CPF (o campo tem mÃ¡scara: sÃ³ os dÃ­gitos entram)
        cpf_ok = _preencher_campo_login(
            lp, ['input#inputUser', 'input[id="inputUser"]',
                 'input[name*="user" i]', 'input[type="text"]'],
            CPF_ACESSO, "cpf", so_digitos=True)

        if not cpf_ok:
            try:
                cpf_ok = bool(lp.evaluate(f"""
                    (function() {{
                        function findInShadow(root, id) {{
                            const el = root.querySelector && root.querySelector('#' + id);
                            if (el) return el;
                            for (const node of (root.querySelectorAll && root.querySelectorAll('*')) || []) {{
                                if (node.shadowRoot) {{ const f = findInShadow(node.shadowRoot, id); if (f) return f; }}
                            }}
                            return null;
                        }}
                        const el = findInShadow(document, 'inputUser');
                        if (!el) return false;
                        el.focus();
                        Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set.call(el,{repr(CPF_ACESSO)});
                        el.dispatchEvent(new Event('input',{{bubbles:true}}));
                        el.dispatchEvent(new Event('change',{{bubbles:true}}));
                        return true;
                    }})()
                """))
            except Exception:
                pass

        if not cpf_ok:
            otp_flow.etapa("login", "cpf", "falhou")
            _status_queue.put({"type": "log",
                               "msg": "âœ— NÃ£o consegui preencher o CPF na tela de login."})
            return False

        time.sleep(0.5)

        # Senha
        senha_ok = _preencher_campo_login(
            lp, ['input#inputPassword', 'input[type="password"]',
                 'input[id*="senha" i]', 'input[name*="senha" i]',
                 'input[formcontrolname*="senha" i]',
                 'input[formcontrolname*="password" i]'],
            SENHA_ACESSO, "senha")

        if not senha_ok:
            try:
                senha_ok = bool(lp.evaluate(f"""
                    (function() {{
                        function findInShadow(root, type) {{
                            const el = root.querySelector && root.querySelector('input[type="'+type+'"]');
                            if (el) return el;
                            for (const node of (root.querySelectorAll && root.querySelectorAll('*')) || []) {{
                                if (node.shadowRoot) {{ const f = findInShadow(node.shadowRoot, type); if (f) return f; }}
                            }}
                            return null;
                        }}
                        const el = findInShadow(document, 'password');
                        if (!el) return false;
                        el.focus();
                        Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set.call(el,{repr(SENHA_ACESSO)});
                        el.dispatchEvent(new Event('input',{{bubbles:true}}));
                        el.dispatchEvent(new Event('change',{{bubbles:true}}));
                        return true;
                    }})()
                """))
            except Exception:
                pass

        if not senha_ok:
            otp_flow.etapa("login", "senha", "falhou")
            _status_queue.put({"type": "log",
                               "msg": "âœ— NÃ£o consegui preencher a senha na tela de login."})
            return False

        time.sleep(0.5)

        # O "Entrar" nasce desabilitado e sÃ³ habilita quando a mÃ¡scara aceita
        # os dois campos: clicar antes disso trava 30s no auto-wait e volta.
        enviou = False
        for sel in ['button:has-text("Entrar")', 'button[type="submit"]',
                    'button:has-text("Acessar")', 'input[type="submit"]']:
            b = _esperar_visivel(lp, sel, 3000)
            if b is None:
                continue
            fim_espera = time.time() + 5
            while time.time() < fim_espera:
                try:
                    if b.is_enabled():
                        break
                except Exception:
                    break
                time.sleep(0.25)
            try:
                b.click(timeout=3000)
                enviou = True
                otp_flow.etapa("login", f"entrar:{sel}", "ok")
                break
            except Exception as e:
                otp_flow.etapa("login", f"entrar:{sel}", "error", erro=str(e)[:80])
        if not enviou:
            otp_flow.etapa("login", "entrar", "not_clicked")
            _status_queue.put({"type": "log",
                               "msg": "âš  Preenchi os campos, mas nÃ£o consegui clicar em Entrar."})

        # O portal pode pedir o cÃ³digo de verificaÃ§Ã£o agora.
        if aguardar_codigo_e_entrar(ctx):
            return True
        return False
    except Exception as e:
        logger.warning(f"Auto-login CPF: {e}")
        return False


def aguardar_relogin(page):
    ctx = page.context
    found = _encontrar_pagina_formulario(ctx)
    if found is not None:
        return found

    logger.warning(f"SessÃ£o expirada. URL: {_url_real(page)}")
    _status_queue.put({"type": "sessao_expirada"})

    # RecuperaÃ§Ã£o suave: "landing-page" muitas vezes Ã© sÃ³ um bounce transitÃ³rio e a
    # sessÃ£o AINDA Ã© vÃ¡lida. Tenta reentrar direto no formulÃ¡rio antes do login completo
    # (evita pedir OTP/senha Ã  toa).
    for _ in range(2):
        try:
            page.goto(URL_FORMULARIO, wait_until="domcontentloaded", timeout=15_000)
            time.sleep(2.5)
            found = _encontrar_pagina_formulario(ctx)
            if found is not None:
                logger.info("SessÃ£o recuperada sem login (reentrada no formulÃ¡rio)")
                _status_queue.put({"type": "login_ok"})
                return found
            if sessao_expirada(page):
                break   # caiu de novo p/ landing/login â†’ precisa logar mesmo
        except Exception:
            pass

    try:
        if "landing" not in _url_real(page).lower():
            page.goto(URL_LANDING, wait_until="domcontentloaded", timeout=15_000)
            time.sleep(2)
    except Exception:
        pass

    if tentar_login_automatico(page):
        found = _formulario_apos_login(ctx)
        if found is not None:
            return found

    for segundo in range(7200):
        if python_stop_event.is_set():
            logger.info("Relogin interrompido pelo botÃ£o Parar.")
            return None
        if segundo % 5 == 0:
            found = _formulario_apos_login(ctx, navegar=False)
            if found is not None:
                logger.info("SessÃ£o recuperada (o portal voltou sozinho).")
                _status_queue.put({"type": "login_ok"})
                return found
        if segundo > 0 and segundo % 300 == 0:
            # Sem esta linha, o log ficava horas em silÃªncio e nÃ£o dava para
            # saber se o bot estava vivo (hÃ¡ 39h assim no bot_log.txt).
            logger.info(f"Relogin: ainda tentando ({segundo // 60} min).")
            try:
                if page.is_closed():
                    page = ctx.new_page()
                    _aplicar_stealth(page)
                page.goto(URL_LANDING, wait_until="domcontentloaded", timeout=15_000)
                time.sleep(2)
                if tentar_login_automatico(page):
                    found = _formulario_apos_login(ctx)
                    if found is not None:
                        return found
                found = _formulario_apos_login(ctx)   # logado? leva ao formulÃ¡rio
                if found is not None:
                    return found
            except Exception as e:
                logger.warning(f"Relogin: falha ao voltar para a landing: {e}")
        time.sleep(1)

    return None


def _formulario_apos_login(ctx, navegar: bool = True):
    """A pÃ¡gina do formulÃ¡rio, aceitando que o portal pare na home.

    Depois do login o portal fica em `/logged-area/home`; o critÃ©rio antigo
    (URL com `recommendation`) dizia "nÃ£o logou" e o bot girava no laÃ§o de 2h
    estando logado. Com `navegar=False` a funÃ§Ã£o sÃ³ CONSULTA â€” importante no
    laÃ§o de 5 em 5 segundos, que senÃ£o martelaria o site com um goto por volta.
    """
    found = _encontrar_pagina_formulario(ctx)
    if found is not None:
        return found
    logada = _pagina_logada(ctx)
    if logada is None or not navegar:
        return None
    try:
        logada.goto(URL_FORMULARIO, wait_until="domcontentloaded", timeout=15_000)
        time.sleep(2)
    except Exception as e:
        logger.warning(f"Relogin: logado, mas falhei ao abrir o formulÃ¡rio: {e}")
    return _encontrar_pagina_formulario(ctx)


# ---------------------------------------------------------------------------
# SALVAR EXCEL ORGANIZADO
# ---------------------------------------------------------------------------
# Colunas mostradas no Excel (na ordem certa)
_COLUNAS_FIXAS  = ["Nome", "CPF", "DDD", "Celular", "Telefone",
                   "Margem_Livre", "Soma_Parcelas", "Total_Parcelas",
                   "Saldo_Devedor_Total", "Reducao_Total"]
# Colunas internas (controle do bot) e colunas de detalhe omitidas do output
_COLUNAS_OCULTAS = {"Tem_Emprestimo"}
_PREFIXOS_OCULTOS = ("Saldo",)   # Saldo_devedor_N nÃ£o aparece no Excel

def _to_excel_atomico(df: pd.DataFrame, caminho: str):
    """Grava num temporÃ¡rio e substitui. Se o destino estiver aberto/bloqueado
    (ex.: aberto no Excel no Windows), tenta de novo e avisa â€” sem perder dados."""
    tmp = caminho + ".tmp.xlsx"   # mantÃ©m extensÃ£o .xlsx para o engine aceitar
    df.to_excel(tmp, index=False)
    for tentativa in range(3):
        try:
            os.replace(tmp, caminho)
            return
        except PermissionError:
            time.sleep(0.6)
    # ainda bloqueado: mantÃ©m o tmp (dados preservados) e avisa para fechar o arquivo
    msg = (f"[AVISO] NÃ£o consegui salvar '{caminho}' â€” provavelmente estÃ¡ aberto no "
           f"Excel. FECHE o arquivo. Dados preservados em '{tmp}'.")
    print(msg)
    try:
        _status_queue.put({"type": "log", "msg": msg})
    except Exception:
        pass


def _salvar_excel(df: pd.DataFrame):
    """Salva o estado completo (progresso) + os arquivos finais limpos."""
    # Estado completo p/ retomar (todas as colunas, inclusive controle e saldo)
    _to_excel_atomico(df, PROGRESSO_XLSX)

    # Arquivo final organizado (esconde colunas internas/saldo)
    cols_fixas_presentes = [c for c in _COLUNAS_FIXAS if c in df.columns]
    cols_extra = sorted(
        c for c in df.columns
        if c not in _COLUNAS_FIXAS
        and c not in _COLUNAS_OCULTAS
        and not any(c.startswith(p) for p in _PREFIXOS_OCULTOS)
    )
    ordem = cols_fixas_presentes + cols_extra
    df_out = df[ordem]
    _to_excel_atomico(df_out, RESULTADO_XLSX)

    df_com = df[df["Tem_Emprestimo"] == "Sim"]
    if not df_com.empty:
        _to_excel_atomico(df_com[ordem], COM_REFIN_XLSX)


# ---------------------------------------------------------------------------
# DADOS
# ---------------------------------------------------------------------------
_COLUNAS_CONTROLE = ("Telefone", "Tem_Emprestimo", "Margem_Livre",
                     "Soma_Parcelas", "Total_Parcelas", "Saldo_Devedor_Total",
                     "Reducao_Total")


def _garantir_colunas_controle(df: pd.DataFrame) -> pd.DataFrame:
    """Garante que as colunas de controle existam. ReconstrÃ³i Tem_Emprestimo
    quando o arquivo veio 'limpo' (sem a coluna interna), pelo que dÃ¡ pra inferir."""
    for col in _COLUNAS_CONTROLE:
        if col not in df.columns:
            df[col] = ""
    df = df.fillna("")
    vazio    = df["Tem_Emprestimo"].astype(str).str.strip() == ""
    tem_red  = df["Reducao_Total"].astype(str).str.strip() != ""
    tem_soma = df["Soma_Parcelas"].astype(str).str.strip() != ""
    # liberou -> Sim ; tinha contrato mas nÃ£o liberou -> NÃ£o ; resto fica p/ processar
    df.loc[vazio & tem_red, "Tem_Emprestimo"] = "Sim"
    df.loc[vazio & ~tem_red & tem_soma, "Tem_Emprestimo"] = "NÃ£o"
    return df


def carregar_dados() -> pd.DataFrame:
    # 1) Retoma do progresso interno (estado completo, todas as colunas)
    if os.path.exists(PROGRESSO_XLSX):
        return _garantir_colunas_controle(pd.read_excel(PROGRESSO_XLSX, dtype=str))

    # 2) Compatibilidade: retoma de um resultado antigo, recriando o que faltar
    if os.path.exists(RESULTADO_XLSX):
        return _garantir_colunas_controle(pd.read_excel(RESULTADO_XLSX, dtype=str))

    # 3) Primeira execuÃ§Ã£o: lÃª o CSV de entrada
    df = pd.read_csv(ARQUIVO_ENTRADA, sep=None, engine="python",
                     dtype=str, encoding="utf-8-sig")
    df.columns = [c.strip() for c in df.columns]

    rename = {}
    for c in df.columns:
        lc = c.lower()
        if "nome" in lc:                                    rename[c] = "Nome"
        elif "cpf" in lc or "cnpj" in lc:                  rename[c] = "CPF"
        elif lc == "ddd":                                   rename[c] = "DDD"
        elif "celular" in lc or "fone" in lc or "tel" in lc: rename[c] = "Celular"
    df = df.rename(columns=rename)
    for col in ("Nome", "CPF", "DDD", "Celular"):
        if col not in df.columns:
            df[col] = ""

    df["Telefone"]        = ""
    df["Tem_Emprestimo"]  = ""   # controle interno â€” nÃ£o aparece no Excel final
    df["Margem_Livre"]    = ""
    df["Soma_Parcelas"]   = ""
    df["Total_Parcelas"]  = ""
    df["Reducao_Total"]   = ""
    return df


# ---------------------------------------------------------------------------
# FORMULÃRIO
# ---------------------------------------------------------------------------
def _tem_campo_nome(page) -> bool:
    """True quando o formulÃ¡rio de consulta (campo Nome) estÃ¡ realmente na tela."""
    try:
        if page.get_by_label("Nome PF ou SÃ³cio").count() > 0:
            return True
    except Exception:
        pass
    try:
        return page.locator('label').filter(has_text="Nome").count() > 0
    except Exception:
        return False


def _clicar_ver_produtos_home(page) -> bool:
    """Na HOME, clica o card 'Ver produtos' (O produto ideal estÃ¡ aqui) que abre o
    formulÃ¡rio de consulta. SÃ³ deve ser chamado quando o campo Nome NÃƒO estÃ¡ visÃ­vel â€”
    aÃ­ o Ãºnico 'Ver produtos' da tela Ã© o da home, nÃ£o o botÃ£o de envio do formulÃ¡rio."""
    for sel in ['a:has-text("Ver produtos")',
                'button:has-text("Ver produtos")',
                ':has-text("Ver produtos")']:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                loc.click()
                logger.info("  Clicou 'Ver produtos' (home) para abrir o formulÃ¡rio")
                return True
        except Exception:
            pass
    return False


def aguardar_formulario(page):
    for tentativa in range(3):
        try:
            page.wait_for_selector('label, button, a', timeout=12_000)
            # 1) JÃ¡ estamos no formulÃ¡rio (campo Nome presente)?
            if _tem_campo_nome(page):
                return
            # 2) Estamos na HOME com o card "Ver produtos" â†’ clica para abrir o form
            if _clicar_ver_produtos_home(page):
                for _ in range(24):   # espera o formulÃ¡rio (campo Nome) renderizar
                    if _tem_campo_nome(page):
                        return
                    time.sleep(0.5)
            time.sleep(2)
            if _tem_campo_nome(page):
                return
        except PlaywrightTimeoutError:
            pass
        if tentativa < 2:
            time.sleep(3)
    raise PlaywrightTimeoutError("FormulÃ¡rio nÃ£o encontrado apÃ³s 3 tentativas")


def preencher_formulario(page, nome: str, cpf: str, ddd: str, celular: str) -> tuple[str, bool]:
    """Preenche o formulÃ¡rio. Retorna (telefone_usado, telefone_valido).

    telefone_valido=False quando foi necessÃ¡rio usar um nÃºmero-placeholder sÃ³ para
    conseguir avanÃ§ar no portal â€” nesse caso o telefone NÃƒO deve ser salvo como real.
    """
    aguardar_formulario(page)
    _pausa()
    _mover_mouse(page)
    ddd_digits = "".join(ch for ch in ddd if ch.isdigit())[:2].zfill(2)
    cel_digits = "".join(ch for ch in celular if ch.isdigit())
    telefone_raw = ddd_digits + cel_digits

    # Valida antes de preencher: precisa ter 11 dÃ­gitos e comeÃ§ar com 9 (celular)
    telefone_valido = len(telefone_raw) == 11 and telefone_raw[2] == "9"
    if telefone_valido:
        telefone = telefone_raw
    else:
        telefone = ddd_digits + "999999999"
        logger.info(f"  Celular invÃ¡lido na origem: {cel_digits!r} â†’ placeholder {telefone}")
        print(f"  [AVISO] Celular fixo/invÃ¡lido {cel_digits!r} â†’ placeholder {telefone}")

    _digitar(page.get_by_label("Nome PF ou SÃ³cio"), nome)
    _pausa()
    _mover_mouse(page)
    _digitar(page.get_by_label("CPF ou CNPJ"), cpf)
    _pausa()
    _mover_mouse(page)
    _digitar(page.get_by_label("DDD + Celular"), telefone)
    _pausa()
    page.locator('button:has-text("Ver produtos")').click()
    _pausa(1.0, 1.5)

    # Segunda linha de defesa: se o form ainda mostrar erro de celular
    erros_cel = ['text=Celular invÃ¡lido', 'text=DDD invÃ¡lido',
                 'text=Telefone invÃ¡lido', 'text=nÃºmero invÃ¡lido']
    if any(page.locator(s).count() > 0 for s in erros_cel):
        tel_fallback = ddd_digits + "999999999"
        logger.warning(f"  Erro de celular: {telefone} â†’ placeholder {tel_fallback}")
        print(f"  [AVISO] Erro celular {telefone} â†’ placeholder {tel_fallback}")
        telefone = tel_fallback
        telefone_valido = False
        _digitar(page.get_by_label("DDD + Celular"), tel_fallback)
        _pausa(0.5, 0.8)
        page.locator('button:has-text("Ver produtos")').click()

    return telefone, telefone_valido


# ---------------------------------------------------------------------------
# AUTOMAÃ‡ÃƒO
# ---------------------------------------------------------------------------
def clicar_simular_consignado(page):
    page.wait_for_selector('text=Vitrine de produtos', timeout=TIMEOUT)
    _mover_mouse(page)
    _pausa()

    if page.locator('text=Produto nÃ£o disponÃ­vel').count() > 0:
        # Cliente sem produto: clica "Cancelar" e confirma "Sim" no modal
        # "Deseja mesmo cancelar sua oferta?" para VOLTAR Ã  tela de simulaÃ§Ã£o.
        # Usa cliques robustos (role + JS shadow) pois os botÃµes sÃ£o Web Components.
        _clicar_botao_texto(page, "Cancelar")
        time.sleep(1.0)
        confirmou = _confirmar_cancelamento(page)   # espera o modal e clica "Sim"
        logger.info(f"  Produto nÃ£o disponÃ­vel â€” cancelado (confirmou Sim={confirmou})")
        time.sleep(1.0)
        raise Exception("nÃ£o disponÃ­vel")

    clicou = False
    try:
        card = page.locator(':has-text("Consignado")').last
        btn  = card.locator('button:has-text("Simular")')
        if btn.count() > 0:
            btn.first.click()
            clicou = True
    except Exception:
        pass

    if not clicou:
        page.locator('button:has-text("Simular")').first.click()

    _pausa()
    time.sleep(1)

    # Fechava TODAS as outras abas sem olhar a URL â€” inclusive uma aba de
    # login/cÃ³digo aberta pelo portal nesse instante.
    _fechar_abas_extras(page.context, page)

    if "consorcio" in page.url.lower():
        page.go_back()
        raise Exception("consÃ³rcio â€” pulando")


def fechar_modais(page):
    try:
        if page.locator('text=cancelar sua oferta').count() > 0:
            sim = page.locator('button:has-text("Sim")')
            if sim.count() > 0 and sim.first.is_visible():
                sim.first.click(timeout=2000)
                _pausa(0.4, 0.7)
                return
    except Exception:
        pass
    for texto in ["Continuar sem consultar", "Continuar", "Fechar", "Ok", "OK", "Entendi"]:
        try:
            btn = page.locator(f'button:has-text("{texto}")')
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click(timeout=2000)
                _pausa(0.4, 0.7)
                return
        except Exception:
            pass




def _preencher_dados_empregador(page):
    hoje = datetime.now().strftime("%d/%m/%Y")

    def _tentar(variantes: list[str], valor: str) -> bool:
        """Preenche um campo por label/placeholder/contexto. Atravessa Shadow DOM."""
        # 1) Locators do Playwright (atravessam shadow DOM aberto)
        for v in variantes:
            for getter in (
                lambda v=v: page.get_by_label(v, exact=False).first,
                lambda v=v: page.get_by_placeholder(v, exact=False).first,
                lambda v=v: page.locator(f'input[placeholder*="{v}"]').first,
                lambda v=v: page.locator(f'mat-form-field:has-text("{v}") input').first,
            ):
                try:
                    loc = getter()
                    if loc.count() > 0 and loc.is_editable():
                        loc.click(force=True)
                        loc.fill("")
                        loc.type(valor, delay=random.randint(55, 90))
                        loc.evaluate("el => ['input','change','blur'].forEach("
                                     "e => el.dispatchEvent(new Event(e,{bubbles:true})))")
                        _pausa(0.3, 0.6)
                        return True
                except Exception:
                    pass

        # 2) JS percorrendo TODO o DOM, inclusive Shadow DOM, casando por contexto
        try:
            ok = page.evaluate("""([termos, valor]) => {
                function* allInputs(root){
                  for (const i of root.querySelectorAll('input,textarea')) yield i;
                  for (const el of root.querySelectorAll('*')) if (el.shadowRoot) yield* allInputs(el.shadowRoot);
                }
                function ctx(inp){
                  let t=(inp.getAttribute('placeholder')||'')+' '+(inp.getAttribute('aria-label')||'')+' '
                       +(inp.getAttribute('formcontrolname')||'')+' '+(inp.id||'')+' '+(inp.name||'');
                  let p=inp.closest('mat-form-field')||inp.parentElement;
                  for(let k=0;k<6&&p;k++){t+=' '+(p.textContent||'');p=p.parentElement||(p.getRootNode&&p.getRootNode().host);}
                  return t.toLowerCase();
                }
                const terms=termos.map(s=>s.toLowerCase());
                for(const inp of allInputs(document)){
                  if(inp.disabled||inp.readOnly||inp.type==='hidden') continue;
                  if(inp.offsetParent===null && inp.getClientRects().length===0) continue;
                  if(terms.some(t=>ctx(inp).includes(t))){
                    inp.focus();
                    const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
                    s.call(inp, valor);
                    ['input','change','blur'].forEach(e=>inp.dispatchEvent(new Event(e,{bubbles:true})));
                    return true;
                  }
                }
                return false;
            }""", [variantes, valor])
            if ok:
                _pausa(0.3, 0.6)
                return True
        except Exception:
            pass

        return False

    def _fill_css(seletores: list[str], valor: str) -> bool:
        """Preenche por id/formcontrolname em qualquer frame, confere e forÃ§a via JS se preciso."""
        for fr in page.frames:
            for sel in seletores:
                try:
                    loc = fr.locator(sel).first
                    if loc.count() == 0 or not loc.is_editable():
                        continue
                    # digita tecla por tecla (a mÃ¡scara dssinputnumber processa cada dÃ­gito)
                    loc.click()
                    try:
                        loc.press("Control+a"); loc.press("Delete")
                    except Exception:
                        pass
                    loc.type(valor, delay=random.randint(70, 110))
                    _pausa(0.2, 0.4)
                    # confere se entrou
                    try:
                        atual = (loc.input_value() or "").strip()
                    except Exception:
                        atual = ""
                    if not any(c.isdigit() for c in atual):
                        # forÃ§a via JS (native setter + eventos que o Angular escuta)
                        loc.evaluate(
                            """(el, v) => {
                                const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
                                el.focus(); s.call(el, v);
                                ['keydown','keyup','input','change','blur'].forEach(
                                    e=>el.dispatchEvent(new Event(e,{bubbles:true})));
                            }""", valor)
                        _pausa(0.2, 0.4)
                        try:
                            atual = (loc.input_value() or "").strip()
                        except Exception:
                            atual = ""
                    if any(c.isdigit() for c in atual):
                        return True
                except Exception:
                    pass
        return False

    # --- Preenche cada campo ---
    # Campos reais do portal: id/formcontrolname fixos (sem placeholder/label).
    # MÃ¡scara numÃ©rica empurra da direita: "500000" -> R$ 5.000,00
    bruto_ok = (_fill_css(['#input-salary', 'input[formcontrolname="salary"]'], "500000")
                or _tentar(["SalÃ¡rio Bruto", "Bruto", "Sal rio Bruto"], "5000,00"))
    liquido_ok = (_fill_css(['#input-netSalary', 'input[formcontrolname="netSalary"]'], "400000")
                  or _tentar(["SalÃ¡rio Liquido", "SalÃ¡rio LÃ­quido", "Liquido", "LÃ­quido", "quido"], "4000,00"))
    _tentar(["Descontos compulsÃ³rios", "Descontos compulsorios", "compuls"], "6,56")
    _tentar(["Descontos variÃ¡veis", "Descontos variaveis", "variÃ¡veis", "variaveis", "vari"], "65,56")

    # --- Fallback de posiÃ§Ã£o: sÃ³ ativa se AMBOS os salÃ¡rios falharam ---
    if not bruto_ok and not liquido_ok:
        try:
            n_filled = page.evaluate("""([v1, v2]) => {
                function* allInputs(root){
                  for (const i of root.querySelectorAll('input')) yield i;
                  for (const el of root.querySelectorAll('*')) if (el.shadowRoot) yield* allInputs(el.shadowRoot);
                }
                const inputs=[...allInputs(document)].filter(i =>
                    i.type!=='hidden' && !i.readOnly && !i.disabled &&
                    (i.offsetParent!==null || i.getClientRects().length>0) && !i.value);
                const vals=[v1,v2];
                const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
                inputs.slice(0,2).forEach((inp,i)=>{
                    inp.focus(); setter.call(inp, vals[i]);
                    ['input','change','blur'].forEach(e=>inp.dispatchEvent(new Event(e,{bubbles:true})));
                });
                return inputs.slice(0,2).length;
            }""", ["5000,00", "900,00"])
            if n_filled:
                logger.info(f"  Fallback posiÃ§Ã£o (shadow): {n_filled} input(s) preenchido(s)")
                _pausa(0.5, 0.8)
            else:
                _dump_form_debug(page)   # nÃ£o achou os salÃ¡rios: salva o HTML p/ diagnÃ³stico
        except Exception:
            pass

    # --- Data de admissÃ£o ---
    def _preencher_data(loc):
        loc.click(force=True)
        time.sleep(0.2)
        loc.press("Control+a")
        loc.press("Delete")
        loc.type(hoje, delay=50)
        loc.press("Tab")
        time.sleep(0.3)

    data_ok = False
    seletores_data = [
        # DeterminÃ­stico: id real do portal
        '#admissionDate',
        'input[id="admissionDate"]',
        # EspecÃ­fico para mat-datepicker
        'mat-form-field:has(mat-datepicker-toggle) input',
        # Por placeholder brasileiro
        'input[placeholder="DD/MM/AAAA"]',
        'input[placeholder="dd/mm/yyyy"]',
        'input[placeholder="dd/MM/yyyy"]',
        # Por texto do mat-form-field
        'mat-form-field:has-text("dmiss") input',
        'mat-form-field:has-text("Data de adm") input',
        'mat-form-field:has-text("admissÃ£o") input',
        'mat-form-field:has-text("admissao") input',
    ]
    for sel in seletores_data:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                _preencher_data(loc)
                data_ok = True
                break
        except Exception:
            pass

    # Fallback via get_by_label
    if not data_ok:
        for v in ["Data de admissÃ£o", "Data de admissao", "Data admissÃ£o", "admissÃ£o"]:
            try:
                loc = page.get_by_label(v, exact=False).first
                if loc.count() > 0:
                    _preencher_data(loc)
                    data_ok = True
                    break
            except Exception:
                pass

    # Fallback JS
    if not data_ok:
        try:
            page.evaluate("""(val) => {
                // Tenta achar datepicker pelo placeholder
                let inp = document.querySelector('input[placeholder*="AA"], input[placeholder*="yy"]');
                if (!inp) {
                    // Tenta qualquer mat-form-field com texto de data
                    const ffs = document.querySelectorAll('mat-form-field');
                    for (const ff of ffs) {
                        const txt = ff.textContent.toLowerCase();
                        if (txt.includes('dmiss') || txt.includes('admis')) {
                            inp = ff.querySelector('input'); break;
                        }
                    }
                }
                if (!inp) return;
                inp.focus();
                const proto = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
                if (proto && proto.set) proto.set.call(inp, val); else inp.value = val;
                ['input','change'].forEach(e => inp.dispatchEvent(new Event(e, {bubbles:true})));
            }""", hoje)
        except Exception:
            pass


def _parse_br_float(s: str) -> float:
    """'3.411,50' â†’ 3411.5  |  '3.411' â†’ 3411.0  |  '0,00' â†’ 0.0"""
    s = s.strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        if re.search(r"\.\d{3}$", s):
            s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _calcular_reducao(contratos: list[dict]) -> float:
    """
    Valor liberado no refinanciamento (fÃ³rmula Ãºnica):

        soma_parcelas / COEFICIENTE - soma_saldo_devedor

    Positivo  -> libera esse valor.
    Negativo  -> nÃ£o libera.
    """
    soma_parcelas = 0.0
    soma_saldo    = 0.0
    for c in contratos:
        vp = c.get("valor_parcela", "")
        sd = c.get("saldo_devedor", "")
        if vp:
            soma_parcelas += _parse_br_float(vp.replace("R$", "").strip())
        if sd:
            soma_saldo    += _parse_br_float(sd.replace("R$", "").strip())
    if soma_parcelas == 0.0:
        return 0.0
    return (soma_parcelas / COEFICIENTE) - soma_saldo


def _capturar_contratos_cards(page) -> list[dict]:
    """
    LÃª os cards da tela 'Selecione os contratos que deseja refinanciar'.
    EstratÃ©gia: tenta seletores de card, depois fallback no body completo.
    Regex flexÃ­vel: aceita \n, espaÃ§os ou ausÃªncia entre label e valor.
    """

    def _extrair_card(texto: str) -> dict:
        """Extrai todos os campos de um bloco de texto de card."""
        c: dict = {}
        # NÃºmero do contrato (ex: 9*****97, 7******86)
        m = re.search(r'(\d+\*+\d+)', texto)
        if m:
            c['contrato'] = m.group(1)
        # Parcelas totais â€” evita capturar "Parcelas pagas"
        m = re.search(r'(?<!pagas\s)Parcelas[\s\n]+(\d+)', texto, re.IGNORECASE)
        if not m:
            m = re.search(r'Parcelas\s*[:\n\r\s]+?(\d+)(?!\s*pagas)', texto, re.IGNORECASE)
        if m:
            c['parcelas'] = m.group(1)
        # Valor da parcela â€” tolerante: pula "R$"/espaÃ§o/quebra (\D) e pega o valor BR (1.234,56)
        m = re.search(r'Valor\s*da\s*parcela\D{0,20}?([\d.]+,\d{2})', texto, re.IGNORECASE)
        if m:
            c['valor_parcela'] = f"R$ {m.group(1)}"
        # Taxa
        m = re.search(r'Taxa[\s\S]{0,10}?([\d,]+%?\s*a\.?\s*m\.?)', texto, re.IGNORECASE)
        if m:
            c['taxa'] = m.group(1).strip()
        # Parcelas pagas
        m = re.search(r'Parcelas pagas[\s\S]{0,10}?(\d+)', texto, re.IGNORECASE)
        if m:
            c['parcelas_pagas'] = m.group(1)
        # Saldo devedor â€” tolerante: pula "R$"/espaÃ§o/quebra (\D) e pega o valor BR (1.234,56)
        m = re.search(r'Saldo\s*devedor\D{0,20}?([\d.]+,\d{2})', texto, re.IGNORECASE)
        if m:
            c['saldo_devedor'] = f"R$ {m.group(1)}"
        return c

    def _deep_text() -> str:
        """Texto de toda a pÃ¡gina INCLUSIVE Shadow DOM (innerText comum nÃ£o pega)."""
        try:
            return page.evaluate(r"""() => {
                function walk(root){
                  let t = '';
                  for (const node of root.childNodes){
                    if (node.nodeType === 3) t += node.textContent + ' ';
                    else if (node.nodeType === 1){
                      if (node.shadowRoot) t += walk(node.shadowRoot);
                      t += walk(node);
                    }
                  }
                  return t + '\n';
                }
                return walk(document.body || document.documentElement);
            }""") or ""
        except Exception:
            return ""

    contratos = []

    # â”€â”€ Tentativa 0 (preferida): texto profundo (Shadow DOM) + espera estabilizar â”€â”€
    # Espera os cards terminarem de carregar: lÃª o nÂº de contratos atÃ© parar de crescer.
    ultimo_n = -1
    texto_deep = ""
    for _ in range(12):   # ~12s no mÃ¡ximo
        texto_deep = _deep_text()
        n_agora = len(re.findall(r'\d+\*+\d+', texto_deep))
        if 'Saldo devedor' in texto_deep and n_agora > 0 and n_agora == ultimo_n:
            break   # estabilizou
        ultimo_n = n_agora
        time.sleep(1.0)

    # DEBUG â€” salva texto deep uma vez por execuÃ§Ã£o p/ diagnosticar regex
    if texto_deep and re.findall(r'\d+\*+\d+', texto_deep):
        if not getattr(_capturar_contratos_cards, '_debug_feito', False):
            try:
                with open('_debug_texto_deep.txt', 'w', encoding='utf-8') as f:
                    f.write(texto_deep[:30000])
                _capturar_contratos_cards._debug_feito = True
                print('  [DEBUG] _debug_texto_deep.txt salvo')
            except Exception as _e:
                print(f'  [DEBUG] erro ao salvar: {_e}')
    if texto_deep and 'Saldo devedor' in texto_deep:
        partes = re.split(r'(?=\d+\*+\d+)', texto_deep)
        for parte in partes:
            if not re.search(r'\d+\*+\d+', parte):
                continue
            if 'Saldo devedor' not in parte and 'Valor da parcela' not in parte:
                continue
            c = _extrair_card(parte)
            if c.get('contrato') or c.get('saldo_devedor'):
                contratos.append(c)

    # Se leu contratos mas faltou saldo/parcela (conta sairia errada), salva HTML real.
    if contratos and any(not (c.get('saldo_devedor') and c.get('valor_parcela'))
                         for c in contratos):
        _dump_contratos_debug(page)

    # â”€â”€ Tentativa 1: seletores de card â”€â”€
    if not contratos:
        for sel in ['mat-card', '[class*="card"]', '[class*="contract"]', 'li', 'article', 'div']:
            locs = page.locator(sel)
            n = locs.count()
            if n == 0:
                continue
            candidatos = []
            for j in range(n):
                try:
                    t = locs.nth(j).inner_text().strip()
                    # Card vÃ¡lido: tem nÃºmero mascarado OU tem saldo devedor E valor de parcela
                    if (re.search(r'\d+\*+\d+', t) or
                            ('Saldo devedor' in t and 'Valor da parcela' in t)):
                        candidatos.append(t)
                except Exception:
                    continue
            if candidatos:
                for texto in candidatos:
                    c = _extrair_card(texto)
                    if c.get('contrato') or c.get('saldo_devedor'):
                        contratos.append(c)
                if contratos:
                    break

    # â”€â”€ Tentativa 2: body completo, quebra por nÃºmero de contrato â”€â”€
    if not contratos:
        try:
            corpo = page.inner_text("body")
            # Divide nos pontos onde comeÃ§a um novo nÃºmero de contrato mascarado
            partes = re.split(r'(?=\d+\*+\d+)', corpo)
            for parte in partes:
                if not re.search(r'\d+\*+\d+', parte):
                    continue
                if 'Saldo devedor' not in parte and 'Valor da parcela' not in parte:
                    continue
                c = _extrair_card(parte)
                if c.get('contrato') or c.get('saldo_devedor'):
                    contratos.append(c)
        except Exception as e:
            logger.debug(f"  captura contratos (tentativa 2): {e}")

    # â”€â”€ Tentativa 3: body completo, quebra por blocos de linha â”€â”€
    if not contratos:
        try:
            corpo = page.inner_text("body")
            blocos = re.split(r'\n{2,}', corpo)
            for bloco in blocos:
                if 'Saldo devedor' not in bloco:
                    continue
                c = _extrair_card(bloco)
                if c.get('saldo_devedor'):
                    contratos.append(c)
        except Exception as e:
            logger.debug(f"  captura contratos (tentativa 3): {e}")

    return contratos


def _eh_valor_moeda(v: str) -> bool:
    """True sÃ³ se o texto tem cara de dinheiro (centavos, ex.: '-R$ 188,76', 'R$ 0,04').
    Serve para NÃƒO confundir a margem com a MatrÃ­cula (inteiro puro, ex.: '909801')."""
    return bool(re.search(r'\d,\d{2}', v or ""))


def _capturar_margem(page) -> str:
    """LÃª a 'Margem livre' percorrendo o DOM inclusive Shadow DOM. '' se nÃ£o achar."""
    # 0-A) TEXTO PROFUNDO (childNodes, atravessa Shadow DOM) â€” mesma tÃ©cnica que fez
    #      os contratos funcionarem. Pega "Margem livre" seguido do valor (R$ 1.838,40
    #      ou -R$ 244,84). Ã‰ a leitura mais confiÃ¡vel neste portal.
    try:
        deep = page.evaluate(r"""() => {
            function walk(root){
              let t='';
              for (const node of root.childNodes){
                if (node.nodeType===3) t += node.textContent + ' ';
                else if (node.nodeType===1){
                  if (node.shadowRoot) t += walk(node.shadowRoot);
                  t += walk(node);
                }
              }
              return t + ' ';
            }
            return walk(document.body || document.documentElement);
        }""") or ""
        m = re.search(r'Margem\s*livre[\s\S]{0,25}?(-?\s?R\$\s?[\d.]+,\d{2})',
                      deep, re.IGNORECASE)
        if m:
            return re.sub(r'\s+', ' ', m.group(1)).strip()
    except Exception as e:
        logger.debug(f"  captura margem (deep text): {e}")

    # 0-B) Campo real da "Margem livre": formcontrolname="benefitMargin".
    #      (HÃ¡ DOIS #input-margin na tela; o outro Ã© o cÃ³digo de consulta, vazio.)
    #      O valor fica no .value do input e Ã© preenchido de forma assÃ­ncrona.
    try:
        v = page.evaluate(r"""() => {
            function find(root){
              const el = root.querySelector && root.querySelector('input[formcontrolname="benefitMargin"]');
              if (el) return el;
              for (const n of (root.querySelectorAll ? root.querySelectorAll('*') : [])){
                if (n.shadowRoot){ const f = find(n.shadowRoot); if (f) return f; }
              }
              return null;
            }
            const el = find(document);
            if (!el) return '';
            return (el.value || el.getAttribute('value') || '').trim();
        }""") or ""
        if _eh_valor_moeda(v):
            return v.strip()
    except Exception as e:
        logger.debug(f"  captura margem (benefitMargin): {e}")

    # 0) DeterminÃ­stico: id/formcontrolname reais do portal (campo desabilitado)
    for fr in page.frames:
        for sel in ('#input-margin', 'input[formcontrolname="benefitMargin"]', 'input[id*="margin"]'):
            try:
                loc = fr.locator(sel).first
                if loc.count() > 0:
                    for cand in (loc.input_value() or "",
                                 loc.get_attribute("value") or "",
                                 loc.get_attribute("placeholder") or ""):
                        cand = cand.strip()
                        if _eh_valor_moeda(cand):
                            return cand
            except Exception:
                pass
    js = r"""
    () => {
      function* allInputs(root){
        for (const inp of root.querySelectorAll('input')) yield inp;
        for (const el of root.querySelectorAll('*')) if (el.shadowRoot) yield* allInputs(el.shadowRoot);
      }
      function ctx(inp){
        let t = (inp.getAttribute('placeholder')||'')+' '+(inp.getAttribute('aria-label')||'');
        let p = inp.closest('mat-form-field') || inp.parentElement;
        for (let i=0;i<6 && p;i++){ t += ' ' + (p.textContent||'');
          p = p.parentElement || (p.getRootNode && p.getRootNode().host); }
        return t;
      }
      for (const inp of allInputs(document)){
        if (/margem/i.test(ctx(inp))){
          const v = (inp.value || inp.getAttribute('value') || inp.getAttribute('placeholder') || '').trim();
          // exige centavos (\d,\d\d) p/ nÃ£o pegar a MatrÃ­cula (inteiro puro) por engano
          if (/\d,\d{2}/.test(v)) return v;
        }
      }
      function allText(root){
        let t = root.innerText || root.textContent || '';
        for (const el of root.querySelectorAll('*')) if (el.shadowRoot) t += ' ' + allText(el.shadowRoot);
        return t;
      }
      const txt = allText(document.body || document.documentElement);
      const m = txt.match(/Margem\s+(?:livre|dispon[iÃ­]vel)[\s:]*(-?\s*R\$\s*[\d.,]+)/i);
      if (m) return m[1].replace(/\s+/g,' ').trim();
      return '';
    }
    """
    try:
        v = page.evaluate(js)
        if _eh_valor_moeda(v):
            return v.strip()
    except Exception as e:
        logger.debug(f"  captura margem (js): {e}")

    # Fallback CSS (Playwright jÃ¡ atravessa shadow DOM aberto)
    for sel in ('mat-form-field:has-text("Margem livre") input',
                'mat-form-field:has-text("Margem") input',
                'input[placeholder*="argem"]'):
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            for cand in (loc.input_value() or "",
                         loc.get_attribute("value") or "",
                         loc.get_attribute("placeholder") or ""):
                cand = cand.strip()
                if cand and any(ch.isdigit() for ch in cand):
                    return cand
        except Exception:
            pass

    _dump_margem_debug(page)   # nÃ£o achou: salva o HTML do campo p/ diagnÃ³stico
    return ""


def _dump_margem_debug(page):
    """Se a margem estÃ¡ na tela mas nÃ£o foi lida, salva o HTML do campo (1x por execuÃ§Ã£o)."""
    if not DEBUG_MARGEM:
        return
    js = r"""
    () => {
      const out = [];
      function walk(root){
        for (const el of root.querySelectorAll('*')){
          const t = el.textContent || '';
          if (/margem/i.test(t) && el.children.length <= 4) out.push(el.outerHTML);
          if (el.shadowRoot) walk(el.shadowRoot);
        }
      }
      walk(document);
      return out.slice(0,12).join('\n\n<!-- ---- -->\n\n');
    }
    """
    try:
        html = page.evaluate(js)
        if html and "margem" in html.lower():
            with open("_debug_margem.html", "w", encoding="utf-8") as f:
                f.write(html)
            msg = "[DEBUG] Margem nÃ£o lida â€” HTML do campo salvo em '_debug_margem.html'. Envie esse arquivo."
            print(msg)
            try:
                _status_queue.put({"type": "log", "msg": msg})
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"  dump margem: {e}")


def _dump_form_debug(page):
    """Salva o HTML dos campos de SalÃ¡rio/Margem (1x por execuÃ§Ã£o) p/ diagnÃ³stico."""
    if not DEBUG_MARGEM:
        return
    js = r"""
    () => {
      const out = [];
      function walk(root){
        for (const el of root.querySelectorAll('*')){
          const t  = el.textContent || '';
          const ph = el.getAttribute ? (el.getAttribute('placeholder')||'') : '';
          if ((/sal[aÃ¡]rio|margem|matr[iÃ­]cula|admiss/i.test(t) || /sal[aÃ¡]rio|margem/i.test(ph))
              && el.children.length <= 4) out.push(el.outerHTML);
          if (el.shadowRoot) walk(el.shadowRoot);
        }
      }
      walk(document);
      return [...new Set(out)].slice(0,20).join('\n\n<!-- ---- -->\n\n');
    }
    """
    try:
        html = page.evaluate(js)
        if html:
            with open("_debug_form.html", "w", encoding="utf-8") as f:
                f.write(html)
            msg = ("[DEBUG] SalÃ¡rio/Margem nÃ£o preenchidos â€” HTML salvo em "
                   "'_debug_form.html'. Envie esse arquivo.")
            print(msg)
            try:
                _status_queue.put({"type": "log", "msg": msg})
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"  dump form: {e}")


def _dump_contratos_debug(page):
    """Salva o HTML real dos cards de contrato (1x/execuÃ§Ã£o) p/ validar a conta."""
    if getattr(_dump_contratos_debug, "_feito", False):
        return
    js = r"""
    () => {
      const out = [];
      function walk(root){
        for (const el of root.querySelectorAll('*')){
          const t = el.textContent || '';
          if ((/saldo devedor|valor da parcela/i.test(t)) && el.children.length <= 8)
            out.push(el.outerHTML);
          if (el.shadowRoot) walk(el.shadowRoot);
        }
      }
      walk(document);
      return [...new Set(out)].slice(0,30).join('\n\n<!-- ---- -->\n\n');
    }
    """
    try:
        html = page.evaluate(js)
        if html:
            with open("_debug_contratos.html", "w", encoding="utf-8") as f:
                f.write(html)
            _dump_contratos_debug._feito = True
            msg = ("[DEBUG] Contrato com saldo/parcela faltando â€” HTML salvo em "
                   "'_debug_contratos.html'. Envie esse arquivo.")
            print(msg)
            logger.warning(msg)
            try:
                _status_queue.put({"type": "log", "msg": msg})
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"  dump contratos: {e}")


def _form_empregador_presente(page) -> bool:
    """True se a tela 'Dados do empregador' jÃ¡ renderizou (varre Shadow DOM)."""
    js = r"""
    () => {
      function deep(root, fn){
        for (const el of root.querySelectorAll('*')){
          if (fn(el)) return true;
          if (el.shadowRoot && deep(el.shadowRoot, fn)) return true;
        }
        return false;
      }
      // 1) input de SalÃ¡rio pelo id/formcontrolname (mesmo padrÃ£o de #input-margin)
      const temSalInput = deep(document, el => {
        if (el.tagName !== 'INPUT') return false;
        const id = (el.id || '').toLowerCase();
        const fc = (el.getAttribute && (el.getAttribute('formcontrolname') || '')).toLowerCase();
        return id.includes('salary') || fc.includes('salary');
      });
      if (temSalInput) return true;
      // 2) texto de instruÃ§Ã£o / tÃ­tulo (atravessa shadow)
      function allText(root){
        let t = root.textContent || '';
        for (const el of root.querySelectorAll('*')) if (el.shadowRoot) t += ' ' + allText(el.shadowRoot);
        return t;
      }
      return /preencha os campos|dados do empregador|sal[aÃ¡]rio bruto/i
              .test(allText(document.body || document.documentElement));
    }
    """
    try:
        return bool(page.evaluate(js))
    except Exception:
        return False


def _dump_stepper_debug(page):
    """Salva o HTML completo da tela 'Dados do empregador' (1x/execuÃ§Ã£o) p/ achar seletores."""
    if getattr(_dump_stepper_debug, "_feito", False):
        return
    js = r"""
    () => {
      function serialize(root){
        let html = '';
        for (const el of root.children){
          html += el.outerHTML || '';
          // anexa o conteÃºdo de cada shadowRoot logo apÃ³s o host, marcado
          const hosts = el.querySelectorAll ? el.querySelectorAll('*') : [];
          for (const h of hosts){
            if (h.shadowRoot){
              html += '\n<!-- shadow of <' + h.tagName.toLowerCase() + '> -->\n'
                   + serialize(h.shadowRoot);
            }
          }
        }
        return html;
      }
      return serialize(document.body || document.documentElement);
    }
    """
    try:
        html = page.evaluate(js)
        if html:
            with open("_debug_stepper.html", "w", encoding="utf-8") as f:
                f.write(html)
            _dump_stepper_debug._feito = True
            msg = ("[DEBUG] Form nÃ£o detectado â€” HTML da tela salvo em "
                   "'_debug_stepper.html'. Envie esse arquivo.")
            print(msg)
            logger.warning(msg)
            try:
                _status_queue.put({"type": "log", "msg": msg})
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"  dump stepper: {e}")


def _clicar_calcular_margem(page) -> str:
    """Clica em 'Calcular margem' se o botÃ£o existir e estiver habilitado
    (tela de convÃªnio sem consulta online/base de margem). Retorna a margem
    capturada apÃ³s o clique, ou '' se nÃ£o achou/nÃ£o clicou."""
    btn_calc = page.locator(
        'button:has-text("Calcular margem"), '
        'button:has-text("Calcular Margem")'
    )
    if btn_calc.count() == 0:
        return ""
    for _ in range(10):
        try:
            if btn_calc.first.is_enabled():
                break
        except Exception:
            pass
        time.sleep(0.5)
    try:
        if not btn_calc.first.is_enabled():
            return ""
    except Exception:
        return ""
    btn_calc.first.click()
    _pausa(5.0, 8.0)   # aguarda o servidor calcular a margem (timing seguro original)
    return _capturar_margem(page)


def verificar_refinanciamento(page) -> tuple[str, float, list[dict], str]:
    """
    Fluxo completo por cliente.
    Retorna ("Sim", reducao_total, contratos, margem_livre) ou ("NÃ£o", 0.0, [], "").
    A presenÃ§a da tela 'Selecione os contratos' = "Sim".
    """
    try:
        page.wait_for_selector(
            'text=SimulaÃ§Ã£o de emprÃ©stimo consignado', timeout=TIMEOUT
        )
    except PlaywrightTimeoutError:
        pass

    _mover_mouse(page)
    _pausa(1.5, 2.5)
    sim_url = page.url

    # Captura a margem livre jÃ¡ na tela de simulaÃ§Ã£o â€” vale para todo cliente,
    # tenha ele refinanciamento ou nÃ£o.
    margem_inicial = _capturar_margem(page)
    if margem_inicial:
        logger.info(f"  Margem livre (tela simulaÃ§Ã£o): {margem_inicial}")
        print(f"  Margem livre: {margem_inicial}")

    # DetecÃ§Ã£o tolerante: case-insensitive, em botÃ£o/link/role, com a frase completa
    sel_refin = ('button:has-text("Simular Refinanciamento"), '
                 'a:has-text("Simular Refinanciamento"), '
                 '[role="button"]:has-text("Simular Refinanciamento")')
    n_links = 0
    for tentativa_refin in range(2):
        try:
            page.wait_for_selector(sel_refin, timeout=15_000)
        except PlaywrightTimeoutError:
            pass
        n_links = page.locator(sel_refin).count()
        if n_links > 0:
            break
        # Ã s vezes os cards sÃ³ renderizam ao rolar / dar mais tempo
        try:
            page.mouse.wheel(0, 1400)
            time.sleep(2.0)
        except Exception:
            pass
    if n_links == 0:
        logger.info("  Sem 'Simular Refinanciamento' visÃ­vel -> NÃ£o")
        return "NÃ£o", 0.0, [], margem_inicial

    logger.info(f"  {n_links} convÃªnio(s) com refinanciamento")
    achou_contrato  = False
    todos_contratos: list[dict] = []
    contratos_vistos: set = set()
    margem_capturada = ""

    for i in range(n_links):
        if python_stop_event.is_set():
            break
        try:
            # Volta para a tela de simulaÃ§Ã£o entre convÃªnios
            cur = _url_real(page)
            if sim_url not in cur:
                page.goto(sim_url, wait_until="domcontentloaded", timeout=15_000)
                page.wait_for_selector(sel_refin, timeout=10_000)
                _pausa()

            links = page.locator(sel_refin)
            if links.count() <= i:
                continue

            links.nth(i).click()
            page.wait_for_load_state("domcontentloaded", timeout=15_000)
            _pausa(2.5, 4.0)

            # Captura Margem livre se disponÃ­vel nesta pÃ¡gina
            m_val = _capturar_margem(page)
            if m_val and not margem_capturada:
                margem_capturada = m_val
                logger.info(f"  Margem livre capturada: {m_val}")
                print(f"  Margem livre: {m_val}")

            # O formulÃ¡rio "Dados do empregador" Ã© um micro-frontend injetado
            # dinamicamente (lento) e seus campos ficam em Web Components (Shadow DOM).
            # Em vez de um teste Ãºnico, espera ATIVAMENTE atÃ© ~25s, varrendo o shadow.
            form_visivel = False
            for _ in range(25):
                if python_stop_event.is_set():
                    break
                if _form_empregador_presente(page):
                    form_visivel = True
                    break
                time.sleep(1.0)

            if form_visivel:
                logger.info("  Form 'Dados do empregador' detectado â€” preenchendo")
                # A margem livre fica NESTE form (ex.: "R$ 1.838,40" / "-R$ 244,84"),
                # no input formcontrolname="benefitMargin", preenchido de forma
                # ASSÃNCRONA. Espera atÃ© ~10s o valor aparecer antes de desistir.
                if not margem_capturada:
                    for _ in range(10):
                        m_val = _capturar_margem(page)
                        if m_val:
                            margem_capturada = m_val
                            logger.info(f"  Margem livre (form empregador): {m_val}")
                            print(f"  Margem livre: {m_val}")
                            break
                        time.sleep(1.0)
                _pausa(1.0, 1.5)
                _preencher_dados_empregador(page)
                _pausa(1.5, 2.5)
                # Alguns convÃªnios (sem consulta online/base de margem) exigem
                # clicar "Calcular margem" antes do stepper liberar "Continuar".
                m_val = _clicar_calcular_margem(page)
                if m_val and not margem_capturada:
                    margem_capturada = m_val
                    logger.info(f"  Margem livre pÃ³s-cÃ¡lculo: {m_val}")
                    print(f"  Margem livre (pÃ³s-cÃ¡lculo): {m_val}")
            else:
                logger.warning("  Form 'Dados do empregador' NÃƒO detectado apÃ³s 25s")
                _dump_stepper_debug(page)   # salva HTML real p/ acertar seletores

                m_val = _clicar_calcular_margem(page)
                if m_val and not margem_capturada:
                    margem_capturada = m_val
                    logger.info(f"  Margem livre pÃ³s-cÃ¡lculo: {m_val}")
                    print(f"  Margem livre (pÃ³s-cÃ¡lculo): {m_val}")

            # Garante dropdown = Refinanciamento
            for sel_dd in ['mat-select', 'select']:
                dd = page.locator(sel_dd).first
                if dd.count() == 0:
                    continue
                txt = (dd.inner_text() or "").strip().lower()
                if "refinanciamento" not in txt:
                    dd.click()
                    _pausa(0.3, 0.5)
                    opt = page.locator(
                        'mat-option:has-text("Refinanciamento"),'
                        'option:has-text("Refinanciamento")'
                    ).first
                    if opt.count() > 0:
                        opt.click()
                        _pausa(0.3, 0.5)
                break

            # AvanÃ§a o stepper atÃ© a tela de contratos (pode ter passo intermediÃ¡rio)
            _sels_contr_chk = ['text=Selecione os contratos', 'text=deseja refinanciar',
                               'text=contratos que deseja']
            for _passo in range(4):
                if any(page.locator(s).count() > 0 for s in _sels_contr_chk):
                    break
                btn_cont = page.locator(
                    'button:has-text("Continuar"), button:has-text("AvanÃ§ar"), '
                    'button:has-text("PrÃ³ximo"), button:has-text("Simular")')
                # espera habilitar (atÃ© 15s)
                habilitou = False
                for _ in range(30):
                    try:
                        if btn_cont.count() > 0 and btn_cont.first.is_enabled():
                            habilitou = True
                            break
                    except Exception:
                        pass
                    time.sleep(0.5)
                if not habilitou:
                    break
                try:
                    btn_cont.first.click()
                    page.wait_for_load_state("domcontentloaded", timeout=15_000)
                    _pausa(2.5, 4.0)
                except Exception:
                    break

            # Tela "Selecione os contratos" â†’ captura contratos
            _sels_contratos = [
                'text=Selecione os contratos',
                'text=deseja refinanciar',
                'text=contratos que deseja',
                ':has-text("Selecione os contratos")',
            ]
            na_tela_contratos = any(
                page.locator(s).count() > 0 for s in _sels_contratos
            )
            cur_url_pos = _url_real(page)
            logger.info(f"  ConvÃªnio {i+1}: tela_contratos={na_tela_contratos} url={cur_url_pos[:60]}")
            print(f"  ConvÃªnio {i+1}: tela_contratos={na_tela_contratos}")
            if na_tela_contratos:
                # Ãšltima chance de pegar a margem (Ã s vezes sÃ³ aparece aqui)
                if not margem_capturada:
                    m_val = _capturar_margem(page)
                    if m_val:
                        margem_capturada = m_val
                        logger.info(f"  Margem livre (tela contratos): {m_val}")
                        print(f"  Margem livre (contratos): {m_val}")
                # --- DEBUG TEMPORÃRIO: salva o texto real da tela de contratos ---
                try:
                    corpo = page.inner_text("body")
                except Exception:
                    corpo = "(inner_text falhou)"
                try:
                    corpo_deep = page.evaluate(r"""() => {
                        function walk(root){
                          let t='';
                          for (const node of root.childNodes){
                            if (node.nodeType===3) t += node.textContent + ' ';
                            else if (node.nodeType===1){
                              if (node.shadowRoot) t += walk(node.shadowRoot);
                              t += walk(node);
                            }
                          }
                          return t + '\n';
                        }
                        return walk(document.body || document.documentElement);
                    }""") or ""
                except Exception:
                    corpo_deep = "(deep text falhou)"
                try:
                    with open("debug_cards.txt", "w", encoding="utf-8") as f:
                        f.write("===== inner_text('body') =====\n")
                        f.write(corpo)
                        f.write("\n\n===== TEXTO PROFUNDO (Shadow DOM) =====\n")
                        f.write(corpo_deep)
                    logger.info("  [DEBUG] debug_cards.txt salvo")
                    print("  [DEBUG] debug_cards.txt salvo")
                except Exception as e:
                    logger.debug(f"  debug_cards: {e}")
                # --- FIM DEBUG TEMPORÃRIO ---

                contratos_conv = _capturar_contratos_cards(page)
                logger.info(f"  [DEBUG] contratos capturados: {contratos_conv}")
                print(f"  [DEBUG] contratos capturados: {contratos_conv}")
                novos = 0
                for c in contratos_conv:
                    chave = c.get("contrato", "") or c.get("saldo_devedor", "")
                    if chave and chave in contratos_vistos:
                        continue
                    if chave:
                        contratos_vistos.add(chave)
                    todos_contratos.append(c)
                    novos += 1
                if novos > 0:
                    achou_contrato = True  # presenÃ§a de contrato refinanciÃ¡vel
                logger.info(f"  ConvÃªnio {i+1}: {novos} contrato(s) novos (ignorados {len(contratos_conv)-novos} duplicados)")
                print(f"  ConvÃªnio {i+1}: {novos} contrato(s) âœ“")

            # Volta para a pÃ¡gina de simulaÃ§Ã£o
            try:
                page.goto(sim_url, wait_until="domcontentloaded", timeout=15_000)
                _pausa(0.5, 1.0)
            except Exception:
                pass

        except Exception as e:
            logger.warning(f"  Erro convÃªnio {i+1}: {e}")
            try:
                page.goto(sim_url, wait_until="domcontentloaded", timeout=15_000)
            except Exception:
                pass

    # Valor liberado considerando TODOS os contratos (fÃ³rmula Ãºnica)
    reducao_total = _calcular_reducao(todos_contratos)
    status = "Sim" if achou_contrato else "NÃ£o"
    return status, reducao_total, todos_contratos, (margem_capturada or margem_inicial)


def _clicar_botao_texto(page, texto: str) -> bool:
    """Clica um botÃ£o pelo texto, robusto p/ Web Components (DSS) do Santander.
    Tenta role de acessibilidade, CSS e, por fim, JS atravessando Shadow DOM."""
    # 1) role de acessibilidade (funciona p/ button e [role=button])
    try:
        loc = page.get_by_role("button", name=texto, exact=True)
        if loc.count() > 0 and loc.first.is_visible():
            loc.first.click(timeout=2000)
            return True
    except Exception:
        pass
    # 2) CSS abrangente
    for sel in (f'button:has-text("{texto}")',
                f'[role="button"]:has-text("{texto}")',
                f'dss-button:has-text("{texto}")',
                f'a:has-text("{texto}")'):
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.first.is_visible():
                loc.click(timeout=2000)
                return True
        except Exception:
            pass
    # 3) JS: acha elemento clicÃ¡vel com texto EXATO, atravessando Shadow DOM
    try:
        ok = page.evaluate(r"""(txt) => {
            const alvo = txt.trim().toLowerCase();
            function* all(root){
              for (const el of root.querySelectorAll('*')){
                yield el;
                if (el.shadowRoot) yield* all(el.shadowRoot);
              }
            }
            let cand = null;
            for (const el of all(document)){
              if ((el.textContent||'').trim().toLowerCase() !== alvo) continue;
              const tag = el.tagName.toLowerCase();
              const clicavel = tag==='button' || tag==='a' || tag.includes('button')
                    || el.getAttribute('role')==='button';
              if (clicavel){ cand = el; break; }
              if (!cand) cand = el;   // guarda fallback
            }
            if (cand){ cand.click(); return true; }
            return false;
        }""", texto)
        if ok:
            return True
    except Exception:
        pass
    return False


def _confirmar_cancelamento(page) -> bool:
    """Se o modal 'Deseja mesmo cancelar sua oferta?' estiver aberto, clica 'Sim'.
    Espera o modal aparecer (atÃ© ~5s) e retorna True se confirmou."""
    for _ in range(10):
        try:
            if page.locator('text=cancelar sua oferta').count() > 0:
                if _clicar_botao_texto(page, "Sim"):
                    time.sleep(0.8)
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _no_formulario(page) -> bool:
    # "No formulÃ¡rio" = campo Nome visÃ­vel. (Antes checava 'Ver produtos', que tambÃ©m
    # existe no card da HOME, fazendo o bot achar que jÃ¡ estava no form e nÃ£o comeÃ§ar.)
    return _tem_campo_nome(page)


def voltar_ao_formulario(page):
    _confirmar_cancelamento(page)
    if _no_formulario(page):
        return
    for _ in range(4):
        try:
            page.go_back(wait_until="domcontentloaded", timeout=5000)
            time.sleep(0.8)
            _confirmar_cancelamento(page)
            if _no_formulario(page):
                return
        except Exception:
            break
    if not _no_formulario(page):
        try:
            page.goto(URL_FORMULARIO, wait_until="domcontentloaded", timeout=15_000)
            time.sleep(1.5)
            _confirmar_cancelamento(page)
            aguardar_formulario(page)   # confirma que o formulÃ¡rio realmente carregou
        except Exception:
            pass


# Aba que pode ser do portal/login. Estava escrita em dois lugares com listas
# diferentes; qualquer domÃ­nio do Santander (id., sso., ...) agora conta, e
# `about:blank` tambÃ©m â€” popup recÃ©m-aberto ainda nÃ£o navegou, e fechÃ¡-lo era
# fechar a prÃ³pria tela do cÃ³digo.
_ABAS_DE_LOGIN = ("openid", "/login", "corp/protocol", "keycloak", "/auth?",
                  "id.santander", "sso.santander", "verific")


def _aba_protegida(url: str, esperando_codigo: bool = False) -> bool:
    """Aba que nÃ£o pode ser fechada.

    Tela de login/cÃ³digo nunca fecha. `about:blank` e duplicata do portal sÃ³
    sÃ£o poupadas enquanto o cÃ³digo Ã© esperado â€” fora disso elas voltam a ser
    recolhidas, como antes, para nÃ£o acumular aba ao longo de centenas de
    clientes (e para nÃ£o sobrar aba velha em /logged-area/).
    """
    url = (url or "").lower().strip()
    if any(k in url for k in _ABAS_DE_LOGIN):
        return True
    if esperando_codigo:
        return True          # na dÃºvida, durante o cÃ³digo nÃ£o se fecha nada
    return False


def _fechar_abas_extras(ctx, page_principal):
    # Enquanto o portal espera o cÃ³digo, nenhuma aba Ã© fechada: a tela do
    # cÃ³digo costuma vir em popup e era morta antes de ser usada.
    esperando = _aguardando_otp.is_set()
    if esperando:
        return
    for p in list(ctx.pages):
        if p is page_principal:
            continue
        try:
            if _aba_protegida(_url_real(p), esperando):
                continue
            p.close()
        except Exception as e:
            logger.debug(f"nao consegui fechar aba extra: {e}")


# ---------------------------------------------------------------------------
# LOOP PRINCIPAL
# ---------------------------------------------------------------------------
def processar_clientes(page, df: pd.DataFrame) -> pd.DataFrame:
    total = len(df)
    processados_no_burst = 0
    proximo_descanso = random.randint(BURST_MIN, BURST_MAX)

    for pos, (idx, linha) in enumerate(df.iterrows(), 1):
        if python_stop_event.is_set():
            break

        # Resume: pula sÃ³ os jÃ¡ finalizados. "Erro"/"CPF InvÃ¡lido" sÃ£o reprocessados.
        ja_feito = str(df.at[idx, "Tem_Emprestimo"]).strip()
        if ja_feito in ("Sim", "NÃ£o"):
            continue

        nome    = str(linha.get("Nome",    "Lead")).strip() or "Lead"
        cpf     = str(linha.get("CPF",     "")).strip()
        ddd     = str(linha.get("DDD",     "")).strip()
        celular = str(linha.get("Celular", "")).strip()

        cpf_digits = "".join(ch for ch in cpf if ch.isdigit())
        # CPF vindo de planilha perde ZEROS Ã€ ESQUERDA quando Ã© salvo como nÃºmero
        # (ex.: 000.000.000-00 -> 629627100). Recupera repondo os zeros Ã  esquerda.
        # (Comprovado: zfill valida 100% dos CPFs curtos da base; pad Ã  direita geraria
        #  o CPF de OUTRA pessoa.)
        if len(cpf_digits) > 11:
            cpf_digits = cpf_digits.lstrip("0")   # tira zeros Ã  esquerda sobrando
        if 0 < len(cpf_digits) < 11:
            cpf_digits = cpf_digits.zfill(11)      # repÃµe zeros Ã  esquerda perdidos
        if len(cpf_digits) != 11:
            df.at[idx, "Tem_Emprestimo"] = "CPF InvÃ¡lido"
            _salvar_excel(df)
            _status_queue.put({"type": "log", "msg": f"CPF invÃ¡lido: {nome}"})
            print(f"  [SKIP] CPF invÃ¡lido: {nome} ({cpf})")
            continue

        sim_n   = int((df["Tem_Emprestimo"] == "Sim").sum())
        nao_n   = int((df["Tem_Emprestimo"] == "NÃ£o").sum())
        erros_n = int(df["Tem_Emprestimo"].isin(["Erro", "CPF InvÃ¡lido"]).sum())

        _status_queue.put({
            "type": "progress", "idx": pos, "total": total,
            "nome": nome, "cpf": cpf, "status": "Processando...", "reducao": 0.0,
            "sim": sim_n, "nao": nao_n, "erros": erros_n,
        })

        logger.info(f"[{pos}/{total}] {nome} CPF:{cpf_digits}")
        print(f"[{pos}/{total}] Processando: {nome} CPF:{cpf_digits}")
        _keepalive(page)
        _fechar_abas_extras(page.context, page)

        if sessao_expirada(page):
            nova = aguardar_relogin(page)
            if nova is None:
                break
            page = nova
            processados_no_burst = 0
            proximo_descanso = random.randint(BURST_MIN, BURST_MAX)

        time.sleep(random.uniform(6.0, 10.0))   # throttle entre clientes (timing seguro original)

        status    = "Erro"
        reducao   = 0.0
        contratos: list[dict] = []
        margem    = ""
        tel_usado = ""
        tel_valido = False
        for tentativa in range(2):
            try:
                voltar_ao_formulario(page)   # garante a tela do formulÃ¡rio (CPF/nome/celular) antes de preencher
                tel_usado, tel_valido = preencher_formulario(page, nome, cpf_digits, ddd, celular)
                clicar_simular_consignado(page)
                fechar_modais(page)
                status, reducao, contratos, margem = verificar_refinanciamento(page)
                logger.info(f"  -> {status} | margem={margem or '-'} | {len(contratos)} contrato(s)")
                print(f"  -> {status} | margem={margem or '-'} | {len(contratos)} contrato(s)")
                break
            except PlaywrightTimeoutError as e:
                logger.warning(f"  TIMEOUT t{tentativa+1}: {str(e)[:60]}")
                if tentativa == 0:
                    if sessao_expirada(page):
                        nova = aguardar_relogin(page)
                        if nova:
                            page = nova
                    else:
                        time.sleep(2)
                else:
                    status = "Erro"
            except Exception as e:
                msg = str(e)
                logger.warning(f"  ERRO t{tentativa+1}: {msg}")
                if "nÃ£o disponÃ­vel" in msg.lower() or "consÃ³rcio" in msg.lower():
                    status = "NÃ£o"
                    break
                if tentativa == 0:
                    if sessao_expirada(page):
                        nova = aguardar_relogin(page)
                        if nova:
                            page = nova
                    else:
                        time.sleep(2)
                else:
                    status = "Erro"

        # Valor liberado: soma_parcelas / 0,021 - saldo_devedor_total
        reducao_valor = _calcular_reducao(contratos) if contratos else 0.0
        # LOG DEBUG â€” ver o que tem nos contratos antes de salvar
        for _i, _c in enumerate(contratos, 1):
            logger.info(f"  [SALVAR] Contrato {_i}: {_c}")

        # Status final: sÃ³ "Sim" quando realmente libera valor positivo
        if status == "Sim" and reducao_valor <= 0:
            status = "NÃ£o"

        # Soma das parcelas mensais
        soma_parc = sum(
            _parse_br_float(c.get("valor_parcela", "0").replace("R$", "").strip())
            for c in contratos if c.get("valor_parcela")
        )

        # Total de parcelas (em quantas vezes estÃ£o os emprÃ©stimos)
        total_parc = sum(
            int(c["parcelas"]) for c in contratos
            if c.get("parcelas", "").isdigit()
        )

        # Soma dos saldos devedores de TODOS os contratos (Ã© o "saldo devedor" da planilha)
        soma_saldo = sum(
            _parse_br_float(c.get("saldo_devedor", "0").replace("R$", "").strip())
            for c in contratos if c.get("saldo_devedor")
        )

        # Salva resultado â€” telefone sÃ³ Ã© gravado se for um celular real (nÃ£o placeholder)
        df.at[idx, "Telefone"]       = str(tel_usado) if tel_valido else ""
        df.at[idx, "Tem_Emprestimo"] = str(status)   # controle interno
        df.at[idx, "Margem_Livre"]   = str(margem)
        df.at[idx, "Soma_Parcelas"]  = f"{soma_parc:.2f}" if soma_parc > 0 else ""
        df.at[idx, "Total_Parcelas"] = str(total_parc) if total_parc > 0 else ""
        df.at[idx, "Reducao_Total"]  = f"{reducao_valor:.2f}" if reducao_valor > 0 else ""
        df.at[idx, "Saldo_Devedor_Total"] = f"{soma_saldo:.2f}" if soma_saldo > 0 else ""
        _MAP_CAMPO = {
            'contrato':      'Contrato',
            'parcelas':      'Parcelas',
            'valor_parcela': 'Valor_Parcela',
            'taxa':          'Taxa',
            'parcelas_pagas':'Parcelas_Pagas',
            'saldo_devedor': 'Saldo_Devedor',
        }
        for n_c, c in enumerate(contratos, 1):
            # Garante que todos os campos do mapa sÃ£o salvos, mesmo os vazios
            todos_campos = {**{k: "" for k in _MAP_CAMPO}, **c}
            for campo, val in todos_campos.items():
                col = f"{_MAP_CAMPO.get(campo, campo.capitalize())}_{n_c}"
                if col not in df.columns:
                    df[col] = ""
                if val:  # sÃ³ sobrescreve se tiver valor
                    df.at[idx, col] = val
            # Log debug dos saldos
            logger.info(f'  Contrato {n_c}: {c.get(chr(99)+chr(111)+chr(110)+chr(116)+chr(114)+chr(97)+chr(116)+chr(111),"?")} | parcela={c.get("valor_parcela","")} | saldo={c.get("saldo_devedor","")}'
            )
        _salvar_excel(df)

        sim_n   = int((df["Tem_Emprestimo"] == "Sim").sum())
        nao_n   = int((df["Tem_Emprestimo"] == "NÃ£o").sum())
        erros_n = int(df["Tem_Emprestimo"].isin(["Erro", "CPF InvÃ¡lido"]).sum())

        _status_queue.put({
            "type": "progress", "idx": pos, "total": total,
            "nome": nome, "cpf": cpf, "status": status, "reducao": reducao_valor,
            "sim": sim_n, "nao": nao_n, "erros": erros_n,
        })

        voltar_ao_formulario(page)
        processados_no_burst += 1

        while _pause_event.is_set() and not python_stop_event.is_set():
            time.sleep(0.5)

        if processados_no_burst >= proximo_descanso:
            duracao = random.uniform(DESCANSO_MIN, DESCANSO_MAX)
            _status_queue.put({"type": "log", "msg": f"Micro-pausa {duracao:.0f}s"})
            logger.info(f"Micro-pausa {duracao:.0f}s")
            time.sleep(duracao)
            processados_no_burst = 0
            proximo_descanso = random.randint(BURST_MIN, BURST_MAX)

    return df


# ---------------------------------------------------------------------------
# MAIN GUI
# ---------------------------------------------------------------------------
def main_gui():
    print(">>> bot versao SALARIO-FILL-v16 (clique Sim robusto: role+JS shadow) <<<")
    logger.info("bot versao SALARIO-FILL-v16")
    df = carregar_dados()

    sim0    = int((df["Tem_Emprestimo"] == "Sim").sum())
    nao0    = int((df["Tem_Emprestimo"] == "NÃ£o").sum())
    erros0  = int(df["Tem_Emprestimo"].isin(["Erro", "CPF InvÃ¡lido"]).sum())
    feitos0 = sim0 + nao0 + erros0

    _status_queue.put({
        "type": "init_stats", "total": len(df), "feitos": feitos0,
        "sim": sim0, "nao": nao0, "erros": erros0,
    })
    _status_queue.put({"type": "log", "msg": "Abrindo Brave..."})

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=PERFIL_DIR,
            executable_path=BRAVE_EXE,
            headless=False,
            ignore_default_args=["--enable-automation"],
            args=["--no-first-run", "--lang=pt-BR",
                  "--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 800},
            locale="pt-BR",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/136.0.0.0 Safari/537.36 Brave/136"
            ),
        )
        try:
            ctx.grant_permissions(["geolocation"],
                                   origin="https://www.parceirosantander.com.br")
        except Exception as e:
            logger.warning(f"Falha ao conceder geolocation: {e}")
        ctx.add_init_script(STEALTH_JS)
        ctx.on("page", lambda p: _aplicar_stealth(p))

        def _auto_fechar_aba(nova_aba):
            _aplicar_stealth(nova_aba)

            def _checar():
                # Espera a aba PARAR de ser about:blank antes de julgar. Com
                # um sleep Ãºnico de 1,5s, uma aba legÃ­tima que ainda estava
                # navegando era fechada â€” inclusive a do cÃ³digo.
                for _ in range(16):          # atÃ© ~8s
                    time.sleep(0.5)
                    if _aguardando_otp.is_set():
                        return
                    try:
                        if nova_aba.is_closed():
                            return
                        url = (nova_aba.url or "").lower()
                    except Exception:
                        return
                    if url and url != "about:blank":
                        if _aba_protegida(url, _aguardando_otp.is_set()):
                            return
                        try:
                            nova_aba.close()
                        except Exception as e:
                            logger.debug(f"nao consegui fechar aba nova: {e}")
                        return

            threading.Thread(target=_checar, daemon=True).start()

        ctx.on("page", _auto_fechar_aba)

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        _aplicar_stealth(page)

        try:
            page.goto(URL_LANDING, wait_until="domcontentloaded", timeout=15_000)
        except Exception:
            pass

        _status_queue.put({"type": "aguardando_login"})

        if not python_stop_event.is_set():
            tentar_login_automatico(page)

        while not python_stop_event.is_set():
            found = _encontrar_pagina_formulario(ctx)
            if found is not None:
                page = found
                break
            time.sleep(2)

        if python_stop_event.is_set():
            # MantÃ©m o Brave aberto mesmo ao parar
            while not python_stop_event.wait(timeout=1):
                pass
            return

        _status_queue.put({"type": "rodando"})
        try:
            df = processar_clientes(page, df)
        except Exception as _exc:
            logger.error(f"Erro crÃ­tico no loop principal: {_exc}", exc_info=True)
            print(f"[ERRO CRÃTICO] {_exc}")
            _status_queue.put({"type": "log", "msg": f"Erro crÃ­tico: {_exc}"})

        sim   = int((df["Tem_Emprestimo"] == "Sim").sum())
        nao   = int((df["Tem_Emprestimo"] == "NÃ£o").sum())
        erros = int(df["Tem_Emprestimo"].isin(["Erro", "CPF InvÃ¡lido"]).sum())
        _status_queue.put({"type": "log", "msg": f"ConcluÃ­do! Sim={sim} | NÃ£o={nao} | Erros={erros}"})
        _status_queue.put({"type": "stopped"})

        # MantÃ©m o Brave aberto â€” aguarda o usuÃ¡rio fechar pelo botÃ£o Parar
        while not python_stop_event.is_set():
            time.sleep(1)


# ---------------------------------------------------------------------------
# MAIN (terminal)
# ---------------------------------------------------------------------------
def main():
    _start_event.set()
    df = carregar_dados()

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=PERFIL_DIR,
            executable_path=BRAVE_EXE,
            headless=False,
            ignore_default_args=["--enable-automation"],
            args=["--no-first-run", "--lang=pt-BR",
                  "--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 800},
            locale="pt-BR",
        )
        try:
            ctx.grant_permissions(["geolocation"],
                                   origin="https://www.parceirosantander.com.br")
        except Exception as e:
            logger.warning(f"Falha ao conceder geolocation: {e}")
        ctx.add_init_script(STEALTH_JS)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(URL_FORMULARIO)

        print("FaÃ§a login no Brave e pressione ENTER quando estiver no formulÃ¡rio.")
        input()

        found = _encontrar_pagina_formulario(ctx)
        if found:
            page = found

        df = processar_clientes(page, df)
        ctx.close()

    _salvar_excel(df)
    print(f"ConcluÃ­do! Salvo em '{RESULTADO_XLSX}'.")


if __name__ == "__main__":
    main()
