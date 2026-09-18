"""
Testes do fluxo do codigo (OTP) com dubles de pagina.

Cada teste descreve uma tela que o portal ja' pode mostrar -- caixa unica,
seis caixas, campo dentro de iframe, componente que ignora `fill`, botao que
nasce desabilitado, codigo recusado -- e cobra do fluxo a resposta certa.

Nenhum teste abre navegador ou toca no portal.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import otp_flow  # noqa: E402


# ---------------------------------------------------------------- dubles ---
class CampoFalso:
    """Um <input>. `aceita_teclado`/`aceita_fill` dizem a que ele reage."""

    def __init__(self, dono, indice, limite=1, visivel=True, editavel=True,
                 aceita_teclado=True, aceita_fill=True):
        self.dono = dono
        self.indice = indice
        self.limite = limite
        self.valor = ""
        self.visivel = visivel
        self.editavel = editavel
        self.aceita_teclado = aceita_teclado
        self.aceita_fill = aceita_fill
        self.cliques = 0

    # --- API que o otp_flow usa ---
    def is_visible(self):
        return self.visivel

    def is_editable(self):
        return self.editavel

    def is_enabled(self):
        return True

    def click(self, timeout=None):
        self.cliques += 1
        self.dono.foco = self.indice

    def focus(self):
        self.dono.foco = self.indice

    def fill(self, texto):
        if texto == "":
            self.valor = ""
            return
        if not self.aceita_fill:
            return                      # componente ignora escrita sem eventos
        self.valor = texto[:self.limite]

    def type(self, texto, delay=None):
        self.press_sequentially(texto, delay)

    def press_sequentially(self, texto, delay=None):
        if not self.aceita_teclado:
            return
        for ch in texto:
            self.valor = (self.valor + ch)[:self.limite]

    def input_value(self):
        return self.valor


class LocatorFalso:
    def __init__(self, campos):
        self.campos = campos

    def count(self):
        return len(self.campos)

    def nth(self, i):
        return self.campos[i]

    @property
    def first(self):
        return self.campos[0]

    def is_visible(self):
        return bool(self.campos) and self.campos[0].is_visible()

    def is_enabled(self):
        return bool(self.campos) and self.campos[0].is_enabled()

    def click(self, timeout=None):
        self.campos[0].click()


class BotaoFalso:
    def __init__(self, texto, visivel=True, habilitado=True):
        self.texto = texto
        self.visivel = visivel
        self.habilitado = habilitado
        self.cliques = 0

    def is_visible(self):
        return self.visivel

    def is_enabled(self):
        return self.habilitado

    def click(self, timeout=None):
        self.cliques += 1


class TecladoFalso:
    """Digita na caixa focada e avanca sozinho, como um componente de PIN."""

    def __init__(self, frame):
        self.frame = frame
        self.teclas = []

    def type(self, texto, delay=None):
        for ch in texto:
            campos = self.frame.campos_de_teclado()
            if not campos:
                return
            i = min(self.frame.foco, len(campos) - 1)
            campo = campos[i]
            if not campo.aceita_teclado:
                return
            campo.valor = (campo.valor + ch)[:campo.limite]
            if len(campo.valor) >= campo.limite:
                self.frame.foco = min(i + 1, len(campos) - 1)

    def press(self, tecla):
        self.teclas.append(tecla)


class FrameFalso:
    def __init__(self, mapa=None, texto_body="", botoes=None):
        self.mapa = mapa or {}          # seletor -> LocatorFalso
        self.texto_body = texto_body
        self.botoes = botoes or {}      # rotulo -> BotaoFalso
        self.foco = 0
        self.js_chamado = []

    def campos_de_teclado(self):
        for loc in self.mapa.values():
            if loc.campos:
                return loc.campos
        return []

    def locator(self, seletor):
        # `:visible` é o filtro que o Playwright aplica de verdade; o dublê
        # precisa respeitá-lo, senão o teste não vê o campo escondido.
        if seletor.endswith(":visible"):
            base = self.mapa.get(seletor[:-len(":visible")])
            if base is not None:
                return LocatorFalso([c for c in base.campos if c.visivel])
            return LocatorFalso([])
        if seletor in self.mapa:
            return self.mapa[seletor]
        for rotulo, botao in self.botoes.items():
            if f'"{rotulo}"' in seletor and seletor.startswith("button"):
                return LocatorBotao(botao)
        return LocatorFalso([])

    def evaluate(self, js, args=None):
        self.js_chamado.append((js, args))
        if "activeElement" in js:
            return "INPUT"
        # setter JS: escreve mesmo em componente que ignora fill/teclado
        if args:
            _seletor, codigo, por_caixa = args
            campos = self.campos_de_teclado()
            if not campos:
                return False
            if por_caixa:
                for i, campo in enumerate(campos):
                    campo.valor = codigo[i] if i < len(codigo) else ""
            else:
                campos[0].valor = codigo
            return True
        return None

    def inner_text(self, _seletor):
        return self.texto_body


class LocatorBotao:
    def __init__(self, botao):
        self.botao = botao

    @property
    def first(self):
        return self.botao

    def is_visible(self):
        return self.botao.is_visible()


class PaginaFalsa:
    def __init__(self, frame_principal, outros_frames=(), fechada=False):
        self.principal = frame_principal
        self.frames = [frame_principal, *outros_frames]
        self.keyboard = TecladoFalso(frame_principal)
        self.fechada = fechada
        self.screenshots = 0
        self.conteudo = "<html>portal</html>"

    def is_closed(self):
        return self.fechada

    def locator(self, seletor):
        return self.principal.locator(seletor)

    def evaluate(self, js, args=None):
        return self.principal.evaluate(js, args)

    def inner_text(self, seletor):
        return self.principal.inner_text(seletor)

    def content(self):
        return self.conteudo

    def screenshot(self, path=None, full_page=False):
        self.screenshots += 1
        Path(path).write_bytes(b"png")


class ContextoFalso:
    def __init__(self, paginas):
        self.pages = list(paginas)


# ------------------------------------------------------------- fabricas ---
def tela_de_caixas(quantidade=6, **kw):
    frame = FrameFalso(botoes={"Continuar": BotaoFalso("Continuar")})
    campos = [CampoFalso(frame, i, limite=1, **kw) for i in range(quantidade)]
    frame.mapa['san-otp-pin-input input'] = LocatorFalso(campos)
    return frame, campos


def tela_campo_unico(**kw):
    frame = FrameFalso(botoes={"Continuar": BotaoFalso("Continuar")})
    campo = CampoFalso(frame, 0, limite=6, **kw)
    frame.mapa['input[autocomplete="one-time-code"]'] = LocatorFalso([campo])
    return frame, campo


class RadioFalso:
    def __init__(self, texto_da_linha):
        self.texto = texto_da_linha
        self.marcado = False

    def evaluate(self, _js):
        return self.texto

    def check(self, timeout=None):
        self.marcado = True

    def click(self, timeout=None, force=False):
        self.marcado = True

    def is_visible(self):
        return True

    def is_enabled(self):
        return True


def tela_de_canal(com_email=True):
    """A tela real: 'Escolha sua forma de receber o código de validação'."""
    frame = FrameFalso(texto_body="Autenticação Parceiro Santander. "
                                  "Escolha sua forma de receber o código de validação",
                       botoes={"Enviar": BotaoFalso("Enviar")})
    celular = RadioFalso("(62) *****-2835")
    email = RadioFalso("Ryan***@gmail.com")
    opcoes = [celular, email] if com_email else [celular]
    frame.mapa['input[type="radio"]'] = LocatorFalso(opcoes)
    return frame, celular, email


# ============================================ 0. ESCOLHER COMO RECEBER =====
class TestEscolhaDoCanal:
    def test_reconhece_a_tela_de_escolha(self):
        frame, _, _ = tela_de_canal()
        assert otp_flow.tela_de_escolha_de_canal(ContextoFalso([PaginaFalsa(frame)])) is not None

    def test_tela_comum_nao_e_confundida(self):
        frame = FrameFalso(texto_body="Bem-vindo ao Parceiro Santander")
        assert otp_flow.tela_de_escolha_de_canal(ContextoFalso([PaginaFalsa(frame)])) is None

    def test_escolhe_o_email_e_clica_em_enviar(self):
        """E-mail é o único canal que o bot consegue ler sozinho."""
        frame, celular, email = tela_de_canal()
        assert otp_flow.escolher_canal(ContextoFalso([PaginaFalsa(frame)])) is True
        assert email.marcado is True and celular.marcado is False
        assert frame.botoes["Enviar"].cliques == 1

    def test_sem_email_usa_o_que_existe(self):
        frame, celular, _ = tela_de_canal(com_email=False)
        assert otp_flow.escolher_canal(ContextoFalso([PaginaFalsa(frame)])) is True
        assert celular.marcado is True

    def test_sem_a_tela_nao_faz_nada(self):
        frame = FrameFalso(texto_body="outra coisa")
        assert otp_flow.escolher_canal(ContextoFalso([PaginaFalsa(frame)])) is False


# =================================================== 1. LOCALIZAR O CAMPO ===
class TestLocalizarCampo:
    def test_acha_as_seis_caixas_do_componente_do_portal(self):
        frame, _ = tela_de_caixas()
        alvo = otp_flow.localizar_campo(ContextoFalso([PaginaFalsa(frame)]))
        assert alvo is not None
        assert alvo.tipo == "caixas" and alvo.quantidade == 6
        assert alvo.seletor == 'san-otp-pin-input input'

    def test_acha_campo_unico(self):
        frame, _ = tela_campo_unico()
        alvo = otp_flow.localizar_campo(ContextoFalso([PaginaFalsa(frame)]))
        assert alvo is not None and alvo.tipo == "unico"

    def test_acha_o_campo_unico_com_rotulo_do_portal(self):
        """Tela real: um input "Código de validação", sem maxlength."""
        frame = FrameFalso(botoes={"Continuar": BotaoFalso("Continuar")})
        campo = CampoFalso(frame, 0, limite=6)
        frame.mapa['input[aria-label*="digo" i]'] = LocatorFalso([campo])
        alvo = otp_flow.localizar_campo(ContextoFalso([PaginaFalsa(frame)]))
        assert alvo is not None and alvo.tipo == "unico"

    def test_acha_campo_dentro_de_iframe(self):
        """Regressao: o fluxo antigo so' olhava o frame principal."""
        dentro, _ = tela_de_caixas()
        pagina = PaginaFalsa(FrameFalso(), outros_frames=[dentro])
        alvo = otp_flow.localizar_campo(ContextoFalso([pagina]))
        assert alvo is not None and alvo.frame is dentro

    def test_tela_sem_campo_devolve_none(self):
        pagina = PaginaFalsa(FrameFalso(texto_body="bem-vindo"))
        assert otp_flow.localizar_campo(ContextoFalso([pagina])) is None

    def test_ignora_campos_invisiveis_do_passo_anterior(self):
        frame, campos = tela_de_caixas(visivel=False)
        assert otp_flow.localizar_campo(ContextoFalso([PaginaFalsa(frame)])) is None

    def test_recusa_quando_a_quantidade_nao_bate(self):
        """7 inputs de 1 caractere nao sao um OTP de 6 digitos."""
        frame, _ = tela_de_caixas(quantidade=7)
        assert otp_flow.localizar_campo(ContextoFalso([PaginaFalsa(frame)])) is None

    def test_ignora_o_componente_escondido_do_passo_anterior(self):
        """Regressão: contar visíveis e escrever em nth() do locator cheio
        endereçava as caixas ESCONDIDAS, e a leitura de volta lia as mesmas —
        a prova fechava sozinha."""
        frame = FrameFalso(botoes={"Continuar": BotaoFalso("Continuar")})
        escondidos = [CampoFalso(frame, i, limite=1, visivel=False) for i in range(6)]
        visiveis = [CampoFalso(frame, 6 + i, limite=1) for i in range(6)]
        frame.mapa['san-otp-pin-input input'] = LocatorFalso(escondidos + visiveis)
        alvo = otp_flow.localizar_campo(ContextoFalso([PaginaFalsa(frame)]))
        assert alvo is not None and alvo.quantidade == 6
        otp_flow.inserir(alvo, "123456")
        assert "".join(c.valor for c in visiveis) == "123456"
        assert all(c.valor == "" for c in escondidos)

    def test_pagina_fechada_e_pulada(self):
        frame, _ = tela_de_caixas()
        viva = PaginaFalsa(frame)
        morta = PaginaFalsa(FrameFalso(), fechada=True)
        alvo = otp_flow.localizar_campo(ContextoFalso([morta, viva]))
        assert alvo is not None and alvo.pagina is viva


# ============================================================ 2. FOCO ======
class TestFoco:
    def test_foco_clica_na_primeira_caixa(self):
        frame, campos = tela_de_caixas()
        alvo = otp_flow.localizar_campo(ContextoFalso([PaginaFalsa(frame)]))
        assert otp_flow.focar(alvo) is True
        assert campos[0].cliques == 1 and frame.foco == 0

    def test_foco_falha_quando_o_clique_estoura(self):
        frame, campos = tela_de_caixas()
        alvo = otp_flow.localizar_campo(ContextoFalso([PaginaFalsa(frame)]))

        def explode(timeout=None):
            raise RuntimeError("element is not visible")

        campos[0].click = explode
        campos[0].focus = explode
        assert otp_flow.focar(alvo) is False


# ======================================================== 3. INSERCAO ======
class TestInsercao:
    def _alvo(self, frame):
        return otp_flow.localizar_campo(ContextoFalso([PaginaFalsa(frame)]))

    def test_teclado_resolve_no_componente_de_pin(self):
        frame, campos = tela_de_caixas()
        alvo = self._alvo(frame)
        assert otp_flow.inserir(alvo, "123456") == "teclado"
        assert "".join(c.valor for c in campos) == "123456"

    def test_cai_para_fill_quando_o_componente_ignora_teclado(self):
        frame, campos = tela_de_caixas(aceita_teclado=False)
        alvo = self._alvo(frame)
        assert otp_flow.inserir(alvo, "123456") == "fill"
        assert "".join(c.valor for c in campos) == "123456"

    def test_cai_para_js_quando_ignora_teclado_e_fill(self):
        """Componente que so' reage a eventos disparados na mao."""
        frame, campos = tela_de_caixas(aceita_teclado=False, aceita_fill=False)
        alvo = self._alvo(frame)
        assert otp_flow.inserir(alvo, "123456") == "js"
        assert "".join(c.valor for c in campos) == "123456"

    def test_campo_unico_recebe_o_codigo_inteiro(self):
        frame, campo = tela_campo_unico()
        alvo = self._alvo(frame)
        assert otp_flow.inserir(alvo, "987654") in ("teclado", "sequencial", "fill", "js")
        assert campo.valor == "987654"

    def test_limpa_residuo_antes_de_escrever(self):
        frame, campos = tela_de_caixas()
        campos[0].valor = "9"
        alvo = self._alvo(frame)
        otp_flow.limpar(alvo)
        assert all(c.valor == "" for c in campos)


# ====================================================== 4. VERIFICACAO =====
class TestVerificacaoDoQueFoiDigitado:
    def _alvo(self, frame):
        return otp_flow.localizar_campo(ContextoFalso([PaginaFalsa(frame)]))

    def test_codigo_completo_confere(self):
        frame, campos = tela_de_caixas()
        for c, ch in zip(campos, "123456"):
            c.valor = ch
        assert otp_flow.verificar_inserido(self._alvo(frame), "123456") is True

    def test_um_digito_so_nao_e_sucesso(self):
        """Regressao do defeito mais grave: qualquer conteudo passava."""
        frame, campos = tela_de_caixas()
        campos[0].valor = "1"
        assert otp_flow.verificar_inserido(self._alvo(frame), "123456") is False

    def test_codigo_trocado_nao_passa(self):
        frame, campos = tela_de_caixas()
        for c, ch in zip(campos, "654321"):
            c.valor = ch
        assert otp_flow.verificar_inserido(self._alvo(frame), "123456") is False

    def test_campo_vazio_nao_passa(self):
        frame, _ = tela_de_caixas()
        assert otp_flow.verificar_inserido(self._alvo(frame), "123456") is False


# ======================================================= 5. CONFIRMACAO ====
class TestConfirmacao:
    def _alvo(self, frame):
        return otp_flow.localizar_campo(ContextoFalso([PaginaFalsa(frame)]))

    def test_clica_no_botao_continuar(self):
        frame, _ = tela_de_caixas()
        assert otp_flow.confirmar(self._alvo(frame)) is True
        assert frame.botoes["Continuar"].cliques == 1

    def test_espera_o_botao_habilitar(self, monkeypatch):
        frame, _ = tela_de_caixas()
        botao = frame.botoes["Continuar"]
        botao.habilitado = False
        chamadas = {"n": 0}

        def habilita_depois():
            chamadas["n"] += 1
            if chamadas["n"] > 2:
                botao.habilitado = True
            return botao.habilitado

        botao.is_enabled = habilita_depois
        monkeypatch.setattr(otp_flow.time, "sleep", lambda _s: None)
        assert otp_flow.confirmar(self._alvo(frame)) is True
        assert botao.cliques == 1

    def test_sem_botao_usa_enter(self, monkeypatch):
        frame, _ = tela_de_caixas()
        frame.botoes.clear()
        pagina = PaginaFalsa(frame)
        alvo = otp_flow.localizar_campo(ContextoFalso([pagina]))
        assert otp_flow.confirmar(alvo) is True
        assert pagina.keyboard.teclas == ["Enter"]

    def test_botao_que_nunca_habilita_nao_e_clicado(self, monkeypatch):
        frame, _ = tela_de_caixas()
        frame.botoes["Continuar"].habilitado = False
        pagina = PaginaFalsa(frame)
        alvo = otp_flow.localizar_campo(ContextoFalso([pagina]))
        monkeypatch.setattr(otp_flow.time, "sleep", lambda _s: None)
        assert otp_flow.confirmar(alvo) is True          # cai para o Enter
        assert frame.botoes["Continuar"].cliques == 0


# ========================================================= 6. RESULTADO ====
class TestResultado:
    def _alvo(self, frame):
        return otp_flow.localizar_campo(ContextoFalso([PaginaFalsa(frame)]))

    def test_aceito_quando_o_portal_deixa_entrar(self):
        frame, _ = tela_de_caixas()
        assert otp_flow.verificar_resultado(self._alvo(frame),
                                            esta_logado=lambda: True) == "aceito"

    def test_recusado_quando_a_tela_reclama(self, monkeypatch):
        frame, _ = tela_de_caixas()
        frame.texto_body = "Código inválido. Tente novamente."
        monkeypatch.setattr(otp_flow.time, "sleep", lambda _s: None)
        assert otp_flow.verificar_resultado(self._alvo(frame),
                                            esta_logado=lambda: False) == "recusado"

    def test_texto_normal_da_tela_nao_e_recusa(self, monkeypatch):
        """A tela do código diz "Não recebeu? Tente novamente em 60 segundos"
        e "o código expira em 5 minutos" — nada disso é recusa."""
        frame, _ = tela_de_caixas()
        frame.texto_body = ("Digite o código enviado por e-mail. "
                            "O código expira em 5 minutos. "
                            "Não recebeu? Tente novamente em 60 segundos.")
        monkeypatch.setattr(otp_flow.time, "sleep", lambda _s: None)
        assert otp_flow.verificar_resultado(self._alvo(frame),
                                            esta_logado=lambda: False,
                                            limite=0.01) == "indefinido"

    def test_nao_declara_recusa_no_primeiro_instante(self, monkeypatch):
        """O portal leva um instante para responder; olhar a tela na hora do
        clique é ler a tela anterior."""
        frame, _ = tela_de_caixas()
        frame.texto_body = "Código inválido"
        monkeypatch.setattr(otp_flow.time, "sleep", lambda _s: None)
        assert otp_flow.verificar_resultado(self._alvo(frame),
                                            esta_logado=lambda: False,
                                            limite=0.05) == "indefinido"

    def test_recusa_na_caixa_de_erro_vale_mesmo_com_corpo_limpo(self, monkeypatch):
        """A mensagem certa vem num elemento de erro, não no corpo inteiro."""
        frame, _ = tela_de_caixas()
        frame.texto_body = "Digite o código enviado por e-mail."

        class CaixaDeErro:
            def is_visible(self):
                return True

            def inner_text(self):
                return "Código incorreto. Confira e tente novamente."

        class LocatorErro:
            first = CaixaDeErro()

        original = frame.locator

        def com_erro(seletor):
            if seletor == '[role="alert"]':
                return LocatorErro()
            return original(seletor)

        frame.locator = com_erro
        monkeypatch.setattr(otp_flow.time, "sleep", lambda _s: None)
        assert otp_flow.verificar_resultado(self._alvo(frame),
                                            esta_logado=lambda: False) == "recusado"

    def test_indefinido_quando_nada_acontece(self, monkeypatch):
        frame, _ = tela_de_caixas()
        monkeypatch.setattr(otp_flow.time, "sleep", lambda _s: None)
        assert otp_flow.verificar_resultado(self._alvo(frame),
                                            esta_logado=lambda: False,
                                            limite=0.01) == "indefinido"


# ====================================================== 7. FLUXO INTEIRO ===
class TestFluxoCompleto:
    def test_caminho_feliz(self):
        frame, campos = tela_de_caixas()
        r = otp_flow.preencher_otp(ContextoFalso([PaginaFalsa(frame)]), "123456",
                                   esta_logado=lambda: True)
        assert r.ok and r.desfecho == "aceito" and r.tentativas == 1
        assert "".join(c.valor for c in campos) == "123456"
        assert frame.botoes["Continuar"].cliques == 1

    def test_codigo_com_menos_de_seis_digitos_nem_toca_na_tela(self):
        frame, campos = tela_de_caixas()
        r = otp_flow.preencher_otp(ContextoFalso([PaginaFalsa(frame)]), "123")
        assert not r.ok and r.desfecho == "codigo_invalido"
        assert all(c.valor == "" for c in campos)

    def test_tela_errada_gera_diagnostico(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(otp_flow, "diagnosticar",
                            lambda *a, **k: str(tmp_path / "_debug_otp.html"))
        pagina = PaginaFalsa(FrameFalso(texto_body="home"))
        r = otp_flow.preencher_otp(ContextoFalso([pagina]), "123456", tentativas=1)
        assert not r.ok and r.desfecho == "campo_nao_encontrado"
        assert r.diagnostico.endswith(".html")

    def test_recusa_do_portal_nao_repete_o_mesmo_codigo(self, monkeypatch):
        frame, _ = tela_de_caixas()
        frame.texto_body = "Código expirado"
        monkeypatch.setattr(otp_flow.time, "sleep", lambda _s: None)
        r = otp_flow.preencher_otp(ContextoFalso([PaginaFalsa(frame)]), "123456",
                                   esta_logado=lambda: False, tentativas=3)
        assert not r.ok and r.desfecho == "recusado"
        assert r.tentativas == 1              # nao insistiu com codigo queimado
        assert r.reutilizavel is False

    def test_falha_nossa_devolve_codigo_para_nova_tentativa(self, monkeypatch):
        monkeypatch.setattr(otp_flow, "diagnosticar", lambda *a, **k: "")
        pagina = PaginaFalsa(FrameFalso())
        r = otp_flow.preencher_otp(ContextoFalso([pagina]), "123456", tentativas=2)
        assert not r.ok and r.reutilizavel is True

    def test_limite_de_tentativas_e_respeitado(self, monkeypatch):
        """Campo existe, mas nada entra: tem que parar, nao girar para sempre."""
        frame, campos = tela_de_caixas(aceita_teclado=False, aceita_fill=False)
        frame.evaluate = lambda js, args=None: "INPUT" if "activeElement" in js else False
        monkeypatch.setattr(otp_flow, "diagnosticar", lambda *a, **k: "")
        chamadas = {"n": 0}
        original = otp_flow.localizar_campo

        def contando(*a, **k):
            chamadas["n"] += 1
            return original(*a, **k)

        monkeypatch.setattr(otp_flow, "localizar_campo", contando)
        r = otp_flow.preencher_otp(ContextoFalso([PaginaFalsa(frame)]), "123456",
                                   tentativas=2)
        assert not r.ok and r.desfecho == "nao_inseriu"
        assert chamadas["n"] == 2

    def test_recupera_na_segunda_tentativa(self, monkeypatch):
        """Primeira passada nao acha o campo; a tela carrega e a segunda vai."""
        frame, campos = tela_de_caixas()
        vazia = PaginaFalsa(FrameFalso())
        cheia = PaginaFalsa(frame)
        estado = {"n": 0}
        monkeypatch.setattr(otp_flow, "diagnosticar", lambda *a, **k: "")

        class CtxQueCarrega:
            @property
            def pages(self):
                estado["n"] += 1
                return [vazia] if estado["n"] == 1 else [cheia]

        r = otp_flow.preencher_otp(CtxQueCarrega(), "123456",
                                   esta_logado=lambda: True, tentativas=2)
        assert r.ok and r.tentativas == 2
        assert "".join(c.valor for c in campos) == "123456"


# =========================================================== 8. SEGREDO ====
class TestSegredoNoLog:
    def test_codigo_nunca_aparece_inteiro(self, caplog):
        frame, _ = tela_de_caixas()
        with caplog.at_level("INFO"):
            otp_flow.preencher_otp(ContextoFalso([PaginaFalsa(frame)]), "123456",
                                   esta_logado=lambda: True)
        texto = "\n".join(r.getMessage() for r in caplog.records)
        assert "123456" not in texto
        assert "12****" in texto

    def test_mascara(self):
        assert otp_flow._mascarar("123456") == "12****"
        assert otp_flow._mascarar("12") == "**"
        assert otp_flow._mascarar("") == ""


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
