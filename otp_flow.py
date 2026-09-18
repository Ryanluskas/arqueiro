"""
otp_flow.py — o caminho do codigo de verificacao (OTP), em etapas verificaveis.

Por que este modulo existe: o fluxo antigo vivia dentro de
`tentar_login_automatico` e declarava sucesso sem prova. Ele achava a tela por
`input[maxlength="1"]`, escrevia com `fill()`, e a "verificacao" devolvia True
se o campo tivesse QUALQUER coisa -- inclusive um digito so'. O log dizia
"OTP processado com sucesso" sem que o portal tivesse aceitado nada.

Aqui cada etapa responde uma pergunta e devolve resposta conferivel:

    localizar_campo()      -> em que pagina/frame esta' o campo, e de que tipo
    focar()                -> o foco pegou? (le document.activeElement)
    limpar()               -> o campo ficou vazio?
    inserir()              -> escreveu; qual tecnica funcionou
    verificar_inserido()   -> o que esta' no campo e' EXATAMENTE o codigo
    confirmar()            -> o botao existia, estava habilitado e foi clicado
    verificar_resultado()  -> o portal aceitou, recusou, ou nao deu para saber

Nada aqui importa Playwright: as funcoes recebem os objetos de pagina e usam
so' o que a API expoe (`locator`, `evaluate`, `keyboard`, ...). E' o que
permite testar o fluxo inteiro com dubles, sem navegador e sem portal.

O codigo nunca aparece inteiro no log -- `_mascarar("123456")` vira "12****".
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

DIGITOS_PADRAO = 6
TIMEOUT_CURTO = 3_000      # ms: acoes na tela de OTP nao podem travar 30s
PAUSA_TECLA = 0.08         # s entre digitos, quando digitamos tecla a tecla

# Recusa de verdade. A lista anterior tinha "tente novamente" e "expirou", que
# aparecem no texto NORMAL da tela ("Nao recebeu? Tente novamente em 60s",
# "o codigo expira em 5 minutos") -- e um codigo valido era dado como queimado.
# Agora sao frases, nao palavras soltas, e a busca comeca pelos elementos de
# erro da propria tela.
_MARCAS_DE_RECUSA = (
    "codigo invalido", "código inválido", "codigo incorreto", "código incorreto",
    "codigo expirado", "código expirado", "codigo nao confere", "código não confere",
    "codigo errado", "código errado", "codigo ja utilizado", "código já utilizado",
)
_SELETORES_DE_ERRO = ('[role="alert"]', '[class*="error"]', '[class*="erro"]',
                      '[class*="invalid"]', '[class*="feedback"]')
# Depois de confirmar, o portal leva um instante para responder: procurar
# recusa no primeiro instante le' a tela antiga.
_ESPERA_ANTES_DE_RECUSAR = 2.0

# Ordem importa: do seletor mais especifico (declara que e' OTP) ao mais geral.
_SELETORES = (
    ("unico",  'input[autocomplete="one-time-code"]'),
    ("caixas", 'san-otp-pin-input input'),
    ("caixas", '[class*="otp"] input'),
    ("caixas", '[class*="pin"] input'),
    ("caixas", 'input[maxlength="1"]'),
    ("unico",  'input[maxlength="6"]'),
    ("unico",  'input[inputmode="numeric"]'),
    ("unico",  'input[type="tel"]'),
    # A tela real do Santander (Keycloak) traz UM campo com rotulo
    # "Código de validação" -- sem maxlength e sem inputmode.
    ("unico",  'input[id*="code" i]'),
    ("unico",  'input[id*="codigo" i]'),
    ("unico",  'input[name*="code" i]'),
    ("unico",  'input[name*="otp" i]'),
    ("unico",  'input[name*="token" i]'),
    ("unico",  'input[aria-label*="digo" i]'),
    ("unico",  'input[placeholder*="digo" i]'),
)

# Rotulos do botao que confirma o codigo, do mais provavel ao menos.
_BOTOES = ("Continuar", "Confirmar", "Validar", "Avançar", "Avancar",
           "Verificar", "Entrar", "Acessar", "submit")


def _mascarar(codigo: str) -> str:
    """Nunca registrar o codigo inteiro: ele e' credencial de uso unico."""
    codigo = str(codigo or "")
    if len(codigo) <= 2:
        return "*" * len(codigo)
    return codigo[:2] + "*" * (len(codigo) - 2)


def etapa(nome: str, acao: str, resultado: str, tentativa: int = 1, **extra) -> None:
    """Uma linha por etapa, sempre no mesmo formato, sempre grepavel.

    [CODE_FLOW] stage=insert_code action=teclado result=ok attempt=1 ...
    """
    partes = [f"stage={nome}", f"action={acao}", f"result={resultado}",
              f"attempt={tentativa}"]
    partes += [f"{k}={v}" for k, v in extra.items() if v not in (None, "")]
    logger.info("[CODE_FLOW] " + " ".join(partes))



# ---------------------------------------------------------------------------
# 0. ESCOLHER COMO RECEBER O CODIGO
# ---------------------------------------------------------------------------
# Antes da tela do codigo, o portal mostra "Escolha sua forma de receber o
# codigo de validacao" com duas opcoes (celular e e-mail) e um botao Enviar.
# O bot parava aqui: nenhum codigo era enviado, e a tela do codigo nunca
# chegava a existir.
_MARCAS_DE_CANAL = ("forma de receber", "receber o código", "receber o codigo",
                    "escolha sua forma")
_BOTOES_DE_ENVIO = ("Enviar", "Continuar", "Avançar", "Avancar")


def tela_de_escolha_de_canal(ctx):
    """A pagina/frame que esta' pedindo para escolher o canal, ou None."""
    for pagina in _paginas(ctx):
        for frame in _frames(pagina):
            try:
                texto = " ".join((frame.inner_text("body") or "").lower().split())
            except Exception:
                continue
            if any(marca in texto for marca in _MARCAS_DE_CANAL):
                return pagina, frame
    return None


def escolher_canal(ctx, preferir_email: bool = True) -> bool:
    """Marca o canal (e-mail, por padrao) e clica em Enviar.

    O e-mail e' o preferido porque e' o unico que o bot consegue ler sozinho
    (ver gmail_otp.py); o SMS depende de alguem olhar o celular.
    """
    achado = tela_de_escolha_de_canal(ctx)
    if achado is None:
        return False
    pagina, frame = achado

    escolhida = _marcar_opcao(frame, preferir_email)
    if not escolhida:
        etapa("choose_channel", "opcao", "not_found")
        return False

    for rotulo in _BOTOES_DE_ENVIO:
        botao = _botao_por_texto(Alvo(pagina, frame, "unico", None, 0), rotulo)
        if botao is None:
            continue
        if not _esperar_habilitado(botao):
            continue
        try:
            botao.click(timeout=TIMEOUT_CURTO)
            etapa("choose_channel", f"enviar:{rotulo}", "ok", canal=escolhida)
            return True
        except Exception as exc:
            etapa("choose_channel", f"enviar:{rotulo}", "error", erro=_curto(exc))
    etapa("choose_channel", "enviar", "not_found", canal=escolhida)
    return False


def _marcar_opcao(frame, preferir_email: bool):
    """Clica na opcao desejada. Devolve "email", "sms" ou "" se nao achou."""
    try:
        radios = frame.locator('input[type="radio"]')
        total = radios.count()
    except Exception:
        total = 0

    melhor = None
    melhor_tipo = ""
    for i in range(total):
        radio = radios.nth(i)
        texto = _texto_da_linha(radio)
        eh_email = "@" in texto
        tipo = "email" if eh_email else "sms"
        if (preferir_email and eh_email) or (not preferir_email and not eh_email):
            melhor, melhor_tipo = radio, tipo
            break
        if melhor is None:
            melhor, melhor_tipo = radio, tipo

    if melhor is None:
        return ""
    for tentar in (lambda: melhor.check(timeout=TIMEOUT_CURTO),
                   lambda: melhor.click(timeout=TIMEOUT_CURTO),
                   lambda: melhor.click(timeout=TIMEOUT_CURTO, force=True)):
        try:
            tentar()
            return melhor_tipo
        except TypeError:
            try:
                melhor.click()
                return melhor_tipo
            except Exception:
                continue
        except Exception:
            continue
    return ""


def _texto_da_linha(radio) -> str:
    """O texto ao lado do radio (para saber se aquela opcao e' o e-mail)."""
    try:
        return radio.evaluate(
            "el => (el.closest('label,li,tr,div') || el.parentElement || {}).innerText || ''")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# 1. LOCALIZAR
# ---------------------------------------------------------------------------
@dataclass
class Alvo:
    """Onde o codigo vai ser digitado, e o que sabemos sobre esse lugar."""

    pagina: object                 # a page (para screenshot, teclado, dump)
    frame: object                  # onde os inputs realmente estao
    tipo: str                      # "caixas" (uma por digito) ou "unico"
    locator: object                # os inputs
    quantidade: int                # quantos inputs visiveis
    seletor: str = ""              # qual seletor achou (vai para o log)

    @property
    def primeiro(self):
        return self.locator.first if self.quantidade else self.locator


def _paginas(ctx):
    for p in getattr(ctx, "pages", []) or []:
        try:
            if callable(getattr(p, "is_closed", None)) and p.is_closed():
                continue
        except Exception:
            continue
        yield p


def _frames(pagina):
    """A pagina e, depois, cada frame dela.

    Locator do Playwright atravessa shadow DOM aberto, mas NAO atravessa
    iframe -- e tela de login de banco costuma vir em iframe. O resto do
    projeto ja' varre `page.frames` (ver `_fill_css` no bot.py); o fluxo de
    OTP era o unico lugar que nao varria.
    """
    vistos = [pagina]
    yield pagina
    try:
        for fr in getattr(pagina, "frames", []) or []:
            if fr not in vistos:
                yield fr
    except Exception:
        return


def _visiveis(locator) -> int:
    """Quantos inputs REALMENTE aparecem. `count()` sozinho conta ate' o que
    esta' escondido -- e Angular guarda no DOM o componente do passo anterior."""
    try:
        total = locator.count()
    except Exception:
        return 0
    visiveis = 0
    for i in range(min(total, 12)):
        try:
            if locator.nth(i).is_visible():
                visiveis += 1
        except Exception:
            continue
    return visiveis


def _locator_so_visiveis(frame, seletor):
    """(locator, quantidade) endereçando SO' os campos visíveis.

    Contar visíveis e depois escrever em `nth(i)` do locator não filtrado é
    escrever no componente escondido do passo anterior -- e a leitura de volta
    lê os mesmos campos errados, então a "prova" fechava sozinha.
    """
    try:
        filtrado = frame.locator(seletor + ":visible")
        quantos = filtrado.count()
        if quantos:
            return filtrado, quantos
    except Exception:
        pass
    try:
        bruto = frame.locator(seletor)
        total = bruto.count()
    except Exception:
        return None, 0
    if total and _visiveis(bruto) == total:
        return bruto, total          # todos visíveis: nth() endereça certo
    return None, 0                   # mistura: não dá para endereçar com segurança


def localizar_campo(ctx, digitos: int = DIGITOS_PADRAO, tentativa: int = 1):
    """Procura o campo do codigo em toda pagina e todo frame do contexto."""
    for pagina in _paginas(ctx):
        for frame in _frames(pagina):
            for tipo, seletor in _SELETORES:
                loc, visiveis = _locator_so_visiveis(frame, seletor)
                if not visiveis:
                    continue
                # "caixas" so' vale se houver uma caixa por digito; caso
                # contrario o seletor pegou outra coisa (checkbox estilizado,
                # campo de dia/mes) e distribuir digitos ali embaralha tudo.
                if tipo == "caixas" and visiveis != digitos:
                    if visiveis == 1:
                        tipo = "unico"
                    else:
                        continue
                if not _editavel(loc):
                    continue
                alvo = Alvo(pagina=pagina, frame=frame, tipo=tipo, locator=loc,
                            quantidade=visiveis, seletor=seletor)
                etapa("find_field", seletor, "ok", tentativa,
                      tipo=tipo, campos=visiveis)
                return alvo
    etapa("find_field", "varredura", "not_found", tentativa)
    return None


def _editavel(locator) -> bool:
    try:
        return bool(locator.first.is_editable())
    except Exception:
        # Dublê simples ou API sem is_editable: nao e' motivo para recusar.
        return True


# ---------------------------------------------------------------------------
# 2. FOCAR  /  3. LIMPAR
# ---------------------------------------------------------------------------
def focar(alvo: Alvo, tentativa: int = 1) -> bool:
    """Clica na primeira caixa (clique de verdade, nao `focus()`) e confere.

    Componente de PIN move o foco sozinho no `input`; por isso focamos so' a
    PRIMEIRA caixa e deixamos o componente conduzir o resto.
    """
    alvo_focado = alvo.primeiro
    try:
        alvo_focado.click(timeout=TIMEOUT_CURTO)
    except Exception as exc:
        try:
            alvo_focado.focus()
        except Exception:
            etapa("focus_field", "click+focus", "error", tentativa, erro=_curto(exc))
            return False
    ativo = _elemento_ativo(alvo)
    ok = ativo is None or ativo.lower() == "input"
    etapa("focus_field", "click", "ok" if ok else "sem_foco", tentativa, ativo=ativo)
    return ok


def _elemento_ativo(alvo: Alvo):
    """Quem esta' com o foco agora. `None` quando nao da' para saber."""
    try:
        return alvo.frame.evaluate(
            "() => document.activeElement && document.activeElement.tagName")
    except Exception:
        return None


def limpar(alvo: Alvo, tentativa: int = 1) -> None:
    """Campo com residuo concatena com o codigo novo e nunca confere."""
    try:
        if alvo.tipo == "caixas":
            for i in range(alvo.quantidade):
                _fill(alvo.locator.nth(i), "")
        else:
            _fill(alvo.primeiro, "")
        etapa("clear_field", "fill_vazio", "ok", tentativa)
    except Exception as exc:
        etapa("clear_field", "fill_vazio", "error", tentativa, erro=_curto(exc))


# ---------------------------------------------------------------------------
# 4. INSERIR
# ---------------------------------------------------------------------------
def inserir(alvo: Alvo, codigo: str, tentativa: int = 1) -> str:
    """Escreve o codigo. Devolve o nome da tecnica que conseguiu, ou "".

    A ordem nao e' gosto: comeca pelo teclado porque componente de PIN faz o
    auto-avanco em `keydown`/`keyup`, eventos que `fill()` nao dispara. `fill`
    e o setter JS ficam como rede, porque sao o que funciona quando o campo e'
    um `<input>` comum.
    """
    for nome, tecnica in (("teclado", _inserir_teclado),
                          ("sequencial", _inserir_sequencial),
                          ("fill", _inserir_fill),
                          ("js", _inserir_js)):
        try:
            tecnica(alvo, codigo)
        except Exception as exc:
            etapa("insert_code", nome, "error", tentativa, erro=_curto(exc))
            continue
        if verificar_inserido(alvo, codigo, tentativa, silencioso=True):
            etapa("insert_code", nome, "ok", tentativa, codigo=_mascarar(codigo))
            return nome
        etapa("insert_code", nome, "verification_failed", tentativa,
              lido=_mascarar(ler_codigo(alvo)))
        limpar(alvo, tentativa)
    return ""


def _inserir_teclado(alvo: Alvo, codigo: str) -> None:
    alvo.primeiro.click(timeout=TIMEOUT_CURTO)
    teclado = getattr(alvo.pagina, "keyboard", None)
    if teclado is None:
        raise RuntimeError("pagina sem teclado")
    teclado.type(codigo, delay=int(PAUSA_TECLA * 1000))


def _inserir_sequencial(alvo: Alvo, codigo: str) -> None:
    if alvo.tipo == "caixas":
        for i, ch in enumerate(codigo[:alvo.quantidade]):
            campo = alvo.locator.nth(i)
            _escrever_devagar(campo, ch)
    else:
        _escrever_devagar(alvo.primeiro, codigo)


def _escrever_devagar(campo, texto: str) -> None:
    escrever = getattr(campo, "press_sequentially", None)
    if callable(escrever):
        escrever(texto, delay=int(PAUSA_TECLA * 1000))
    else:                                   # Playwright < 1.38
        campo.type(texto, delay=int(PAUSA_TECLA * 1000))


def _fill(campo, texto: str) -> None:
    """`fill` com prazo curto: o padrao do Playwright e' 30s por chamada, e
    seis caixas numa tela ruim viravam tres minutos de espera."""
    try:
        campo.fill(texto, timeout=TIMEOUT_CURTO)
    except TypeError:          # dublê (ou API antiga) sem o parâmetro
        campo.fill(texto)


def _inserir_fill(alvo: Alvo, codigo: str) -> None:
    if alvo.tipo == "caixas":
        for i, ch in enumerate(codigo[:alvo.quantidade]):
            _fill(alvo.locator.nth(i), ch)
    else:
        _fill(alvo.primeiro, codigo)


_JS_SETTER = """
(args) => {
  const [seletor, codigo, porCaixa] = args;
  const campos = Array.from(document.querySelectorAll(seletor))
                      .filter(el => el.offsetParent !== null && !el.disabled);
  if (!campos.length) return false;
  const setar = (el, valor) => {
    const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value').set;
    setter.call(el, valor);
    for (const tipo of ['keydown', 'keyup', 'input', 'change', 'blur']) {
      el.dispatchEvent(new Event(tipo, {bubbles: true}));
    }
  };
  if (porCaixa) {
    campos.forEach((el, i) => setar(el, codigo[i] || ''));
  } else {
    setar(campos[0], codigo);
  }
  return true;
}
"""


def _inserir_js(alvo: Alvo, codigo: str) -> None:
    """Ultima linha: setter nativo + eventos, a tecnica que ja' se provou
    neste portal nos campos de CPF e senha (ver `_fill_css` no bot.py)."""
    alvo.frame.evaluate(_JS_SETTER,
                        [alvo.seletor, codigo, alvo.tipo == "caixas"])


# ---------------------------------------------------------------------------
# 5. VERIFICAR O QUE ENTROU
# ---------------------------------------------------------------------------
def ler_codigo(alvo: Alvo) -> str:
    """O que esta' escrito no campo, agora. "" quando nao da' para ler."""
    try:
        if alvo.tipo == "caixas":
            partes = []
            for i in range(alvo.quantidade):
                partes.append((_ler(alvo.locator.nth(i)) or "").strip())
            return "".join(partes)
        return (_ler(alvo.primeiro) or "").strip()
    except Exception as exc:
        # Falha de leitura nao e' campo vazio: sem esta linha, o diagnostico
        # apontava para o lugar errado.
        etapa("read_field", "input_value", "error", erro=_curto(exc))
        return ""


def _ler(campo) -> str:
    try:
        return campo.input_value(timeout=TIMEOUT_CURTO)
    except TypeError:
        return campo.input_value()


def verificar_inserido(alvo: Alvo, codigo: str, tentativa: int = 1,
                       silencioso: bool = False) -> bool:
    """IGUAL ao codigo esperado -- nao "tem alguma coisa".

    A versao antiga aceitava qualquer conteudo nao-vazio, entao um digito so'
    passava como sucesso e o bot confirmava um codigo incompleto.
    """
    lido = ler_codigo(alvo)
    ok = lido == codigo
    if not silencioso:
        etapa("verify_typed", "comparacao", "ok" if ok else "mismatch", tentativa,
              esperado=_mascarar(codigo), lido=_mascarar(lido),
              tamanho=f"{len(lido)}/{len(codigo)}")
    return ok


# ---------------------------------------------------------------------------
# 6. CONFIRMAR
# ---------------------------------------------------------------------------
def confirmar(alvo: Alvo, tentativa: int = 1) -> bool:
    """Clica no botao que valida o codigo; se nao houver, tenta Enter.

    Botao de OTP costuma nascer desabilitado ate' o ultimo digito -- por isso
    esperamos ele habilitar em vez de clicar e travar 30s no auto-wait.
    """
    for rotulo in _BOTOES:
        botao = _botao_por_texto(alvo, rotulo)
        if botao is None:
            continue
        if not _esperar_habilitado(botao):
            etapa("confirm_code", f"botao:{rotulo}", "disabled", tentativa)
            continue
        try:
            botao.click(timeout=TIMEOUT_CURTO)
            etapa("confirm_code", f"botao:{rotulo}", "ok", tentativa)
            return True
        except Exception as exc:
            etapa("confirm_code", f"botao:{rotulo}", "error", tentativa,
                  erro=_curto(exc))
    try:
        teclado = getattr(alvo.pagina, "keyboard", None)
        if teclado is not None:
            teclado.press("Enter")
            etapa("confirm_code", "enter", "ok", tentativa)
            return True
    except Exception as exc:
        etapa("confirm_code", "enter", "error", tentativa, erro=_curto(exc))
    etapa("confirm_code", "nenhum", "not_found", tentativa)
    return False


def _botao_por_texto(alvo: Alvo, rotulo: str):
    if rotulo == "submit":
        seletores = ('button[type="submit"]', 'input[type="submit"]')
        for seletor in seletores:
            try:
                botao = alvo.frame.locator(seletor).first
                if botao.is_visible():
                    return botao
            except Exception:
                continue
        return None
    for seletor in (f'button:has-text("{rotulo}")',
                    f'[role="button"]:has-text("{rotulo}")'):
        try:
            botao = alvo.frame.locator(seletor).first
            if botao.is_visible():
                return botao
        except Exception:
            continue
    return None


def _esperar_habilitado(botao, limite: float = 5.0) -> bool:
    fim = time.time() + limite
    while True:
        try:
            if botao.is_enabled():
                return True
        except Exception:
            return True          # sem is_enabled (dublê): deixa tentar
        if time.time() >= fim:
            return False
        time.sleep(0.25)


# ---------------------------------------------------------------------------
# 7. VERIFICAR O RESULTADO
# ---------------------------------------------------------------------------
def verificar_resultado(alvo: Alvo, esta_logado=None, limite: float = 20.0,
                        tentativa: int = 1) -> str:
    """Devolve "aceito", "recusado" ou "indefinido".

    "Cliquei no botao" nao e' resultado. Aqui esperamos por um dos tres
    desfechos observaveis: a tela de destino apareceu, o portal reclamou do
    codigo, ou o tempo acabou sem nenhum dos dois -- e nesse caso dizemos
    "indefinido" em vez de inventar sucesso.
    """
    fim = time.time() + limite
    inicio = time.time()
    erro_logado = False
    while time.time() < fim:
        if esta_logado is not None:
            try:
                if esta_logado():
                    etapa("verify_result", "logado", "aceito", tentativa)
                    return "aceito"
            except Exception as exc:
                if not erro_logado:      # uma vez, para nao encher o log
                    erro_logado = True
                    etapa("verify_result", "esta_logado", "error", tentativa,
                          erro=_curto(exc))
        # Dar tempo do portal responder antes de interpretar a tela como recusa.
        motivo = (_mensagem_de_recusa(alvo)
                  if time.time() - inicio >= _ESPERA_ANTES_DE_RECUSAR else None)
        if motivo:
            etapa("verify_result", "mensagem", "recusado", tentativa, motivo=motivo)
            return "recusado"
        time.sleep(0.5)
    etapa("verify_result", "timeout", "indefinido", tentativa)
    return "indefinido"


def _mensagem_de_recusa(alvo: Alvo):
    """Recusa explicita do portal, ou None.

    Procura primeiro nos elementos de erro; so' cai no corpo inteiro se nao
    houver nenhum. As marcas sao frases completas, para nao confundir com o
    texto de ajuda da propria tela.
    """
    for seletor in _SELETORES_DE_ERRO:
        try:
            caixa = alvo.frame.locator(seletor).first
            if not caixa.is_visible():
                continue
            texto = (caixa.inner_text() or "").lower()
        except Exception:
            continue
        achada = _marca_em(texto)
        if achada:
            return achada
    try:
        corpo = (alvo.frame.inner_text("body") or "").lower()
    except Exception:
        return None
    return _marca_em(corpo)


def _marca_em(texto: str):
    texto = " ".join((texto or "").split())
    for marca in _MARCAS_DE_RECUSA:
        if marca in texto:
            return marca
    return None


# ---------------------------------------------------------------------------
# DIAGNOSTICO
# ---------------------------------------------------------------------------
def diagnosticar(alvo_ou_pagina, motivo: str, pasta: str = "") -> str:
    """Salva HTML e screenshot da tela quando o fluxo quebra.

    Sem isso, mexer em seletor e' chute: o projeto nao tinha NENHUM screenshot
    e nenhum dump da tela de codigo.
    """
    pagina = getattr(alvo_ou_pagina, "pagina", alvo_ou_pagina)
    pasta = pasta or os.path.dirname(os.path.abspath(__file__))
    carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = os.path.join(pasta, f"_debug_otp_{motivo}_{carimbo}")
    salvos = []
    try:
        with open(base + ".html", "w", encoding="utf-8") as fh:
            fh.write(pagina.content())
        salvos.append(base + ".html")
    except Exception as exc:
        logger.warning(f"[CODE_FLOW] dump html falhou: {_curto(exc)}")
    try:
        pagina.screenshot(path=base + ".png", full_page=True)
        salvos.append(base + ".png")
    except Exception as exc:
        logger.warning(f"[CODE_FLOW] screenshot falhou: {_curto(exc)}")
    if salvos:
        etapa("diagnostic", motivo, "saved", arquivos=len(salvos))
    return salvos[0] if salvos else ""


def _curto(exc) -> str:
    texto = str(exc).replace("\n", " ")
    return texto[:120]


# ---------------------------------------------------------------------------
# ORQUESTRACAO
# ---------------------------------------------------------------------------
@dataclass
class Resultado:
    ok: bool
    desfecho: str                 # aceito | recusado | campo_nao_encontrado | ...
    tecnica: str = ""
    tentativas: int = 0
    diagnostico: str = ""
    detalhes: dict = field(default_factory=dict)

    @property
    def reutilizavel(self) -> bool:
        """O codigo ainda serve para outra tentativa?

        Recusado pelo portal = queimado (errado ou expirado): insistir com o
        mesmo codigo so' gasta tentativa. Falha nossa (campo, foco, clique) =
        o codigo continua valido e pode ser reaproveitado.
        """
        return self.desfecho not in ("aceito", "recusado")


def preencher_otp(ctx, codigo: str, esta_logado=None, tentativas: int = 2,
                  digitos: int = DIGITOS_PADRAO, diagnostico: bool = True) -> Resultado:
    """Fluxo completo: achar -> focar -> limpar -> inserir -> conferir ->
    confirmar -> conferir o desfecho. Tentativas sao LIMITADAS."""
    codigo = (codigo or "").strip()
    if not codigo.isdigit() or len(codigo) != digitos:
        etapa("receive_code", "validacao", "invalid_format", 1,
              tamanho=len(codigo))
        return Resultado(False, "codigo_invalido")

    etapa("receive_code", "fila", "ok", 1, codigo=_mascarar(codigo))
    ultimo = Resultado(False, "nao_tentado")

    for numero in range(1, max(1, tentativas) + 1):
        alvo = localizar_campo(ctx, digitos, numero)
        if alvo is None:
            caminho = ""
            if diagnostico:
                pagina = next(iter(_paginas(ctx)), None)
                if pagina is not None:
                    caminho = diagnosticar(pagina, "campo_nao_encontrado")
            ultimo = Resultado(False, "campo_nao_encontrado", tentativas=numero,
                               diagnostico=caminho)
            continue

        if not focar(alvo, numero):
            ultimo = Resultado(False, "sem_foco", tentativas=numero)
            continue

        limpar(alvo, numero)
        tecnica = inserir(alvo, codigo, numero)
        if not tecnica or not verificar_inserido(alvo, codigo, numero):
            caminho = diagnosticar(alvo, "nao_inseriu") if diagnostico else ""
            ultimo = Resultado(False, "nao_inseriu", tentativas=numero,
                               diagnostico=caminho,
                               detalhes={"lido": _mascarar(ler_codigo(alvo))})
            continue

        if not confirmar(alvo, numero):
            caminho = diagnosticar(alvo, "sem_confirmacao") if diagnostico else ""
            ultimo = Resultado(False, "sem_confirmacao", tecnica=tecnica,
                               tentativas=numero, diagnostico=caminho)
            continue

        desfecho = verificar_resultado(alvo, esta_logado, tentativa=numero)
        if desfecho == "aceito":
            return Resultado(True, "aceito", tecnica=tecnica, tentativas=numero)
        if desfecho == "recusado":
            # Codigo queimado: nao adianta repetir com o mesmo.
            return Resultado(False, "recusado", tecnica=tecnica, tentativas=numero)
        caminho = diagnosticar(alvo, "indefinido") if diagnostico else ""
        ultimo = Resultado(False, "indefinido", tecnica=tecnica,
                           tentativas=numero, diagnostico=caminho)

    etapa("finish", ultimo.desfecho, "falhou", ultimo.tentativas or tentativas)
    return ultimo
