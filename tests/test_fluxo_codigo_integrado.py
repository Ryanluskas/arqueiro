"""
Integração: o laço que espera o código e conclui o login
(`bot.aguardar_codigo_e_entrar`), com telas de mentira.

Percorre o caminho inteiro — recebe código → acha a tela → acha o campo →
foca → insere → confere o que entrou → confirma → confere o desfecho — e os
desvios que antes faziam o código evaporar sem aviso.
"""
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bot                                   # noqa: E402
import otp_flow                              # noqa: E402
from test_otp_flow import (ContextoFalso, PaginaFalsa, FrameFalso,   # noqa: E402
                           tela_de_caixas)


@pytest.fixture(autouse=True)
def _sem_espera(monkeypatch):
    """Os `sleep` do laço não interessam ao teste; o relógio real, sim."""
    monkeypatch.setattr(bot.time, "sleep", lambda _s: None)
    # A espera antes de interpretar a tela como recusa é testada à parte.
    monkeypatch.setattr(otp_flow, "_ESPERA_ANTES_DE_RECUSAR", 0.0)
    monkeypatch.setattr(bot, "_marco_da_tela", 0.0)
    monkeypatch.setattr(otp_flow.time, "sleep", lambda _s: None)
    monkeypatch.setattr(bot, "_GMAIL_OTP", False)      # sem thread de Gmail
    monkeypatch.setattr(bot, "_WINSOUND", False)       # sem beep
    bot.python_stop_event.clear()
    bot._drenar_fila_otp()
    _drenar_status()
    yield
    bot.python_stop_event.clear()
    bot._drenar_fila_otp()
    _drenar_status()


def _drenar_status():
    tipos = []
    while True:
        try:
            tipos.append(bot._status_queue.get_nowait())
        except Exception:
            return tipos


def _tipos(mensagens):
    return [m.get("type") for m in mensagens]


class CtxComTelaDeCodigo(ContextoFalso):
    """Contexto cuja 'aba logada' só aparece depois que o código é aceito."""

    def __init__(self, frame, campos, codigo_certo="123456"):
        super().__init__([PaginaFalsa(frame)])
        self.frame = frame
        self.campos = campos
        self.codigo_certo = codigo_certo
        self.aba_logada = object()

    def logado(self):
        digitado = "".join(c.valor for c in self.campos)
        return (digitado == self.codigo_certo
                and self.frame.botoes["Continuar"].cliques > 0)

    def logadas(self):
        """O que `bot._paginas_logadas` enxergaria neste contexto."""
        return [self.aba_logada] if self.logado() else []


def _com_tela():
    frame, campos = tela_de_caixas()
    return CtxComTelaDeCodigo(frame, campos)


# ==================================================== CAMINHO COMPLETO =====
class TestCaminhoCompleto:
    def test_codigo_da_gui_entra_e_o_login_conclui(self, monkeypatch):
        ctx = _com_tela()
        monkeypatch.setattr(bot, "_paginas_logadas", lambda _c: ctx.logadas())
        bot.enfileirar_codigo("123456")

        assert bot.aguardar_codigo_e_entrar(ctx, prazo_segundos=5) is True
        assert "".join(c.valor for c in ctx.campos) == "123456"
        assert ctx.frame.botoes["Continuar"].cliques == 1
        assert "login_ok" in _tipos(_drenar_status())

    def test_avisa_a_interface_quando_a_tela_aparece(self, monkeypatch):
        ctx = _com_tela()
        monkeypatch.setattr(bot, "_paginas_logadas", lambda _c: ctx.logadas())
        bot.enfileirar_codigo("123456")
        bot.aguardar_codigo_e_entrar(ctx, prazo_segundos=5)
        assert "otp_needed" in _tipos(_drenar_status())

    def test_login_que_se_resolve_sozinho_nao_pede_codigo(self, monkeypatch):
        """SSO concluiu enquanto esperávamos: não há código a digitar."""
        nova = {"aba": None}
        monkeypatch.setattr(bot, "_paginas_logadas",
                            lambda _c: [nova["aba"]] if nova["aba"] else [])
        ctx = ContextoFalso([PaginaFalsa(FrameFalso())])

        def aparece(_s):
            nova["aba"] = object()

        monkeypatch.setattr(bot.time, "sleep", aparece)
        assert bot.aguardar_codigo_e_entrar(ctx, prazo_segundos=5) is True
        assert "otp_needed" not in _tipos(_drenar_status())

    def test_aba_velha_ja_logada_nao_conta_como_sucesso(self, monkeypatch):
        """Uma aba esquecida em /logged-area/ fazia o bot dizer "logado" no
        primeiro segundo e seguir sem nunca digitar o código."""
        velha = object()
        monkeypatch.setattr(bot, "_paginas_logadas", lambda _c: [velha])
        ctx = _com_tela()
        assert bot.aguardar_codigo_e_entrar(ctx, prazo_segundos=0.4) is False


# ======================================================== O CÓDIGO NÃO SOME =
class TestCodigoNaoEvapora:
    def test_codigo_que_chega_antes_da_tela_e_guardado(self, monkeypatch):
        """Antes: `get_nowait` consumia e o `continue` seguinte descartava."""
        frame, campos = tela_de_caixas()
        vazia = PaginaFalsa(FrameFalso())
        cheia = PaginaFalsa(frame)
        estado = {"voltas": 0}

        class CtxQueDemora:
            @property
            def pages(self):
                estado["voltas"] += 1
                return [vazia] if estado["voltas"] < 4 else [cheia]

        ctx = CtxQueDemora()
        pronto = {"ok": False}
        monkeypatch.setattr(bot, "_paginas_logadas",
                            lambda _c: [object()] if pronto["ok"] else [])

        def confirmou(*_a, **_k):
            pronto["ok"] = "".join(c.valor for c in campos) == "123456"
            return pronto["ok"]

        monkeypatch.setattr(otp_flow, "confirmar", lambda alvo, tentativa=1: confirmou())
        bot.enfileirar_codigo("123456")          # chega ANTES da tela existir

        assert bot.aguardar_codigo_e_entrar(ctx, prazo_segundos=5) is True
        assert "".join(c.valor for c in campos) == "123456"

    def test_codigo_velho_na_fila_e_descartado(self, monkeypatch):
        """Código de uma tentativa anterior já expirou no portal."""
        ctx = _com_tela()
        monkeypatch.setattr(bot, "_paginas_logadas", lambda _c: [])
        import time as _t
        bot._otp_queue.put(("999999", _t.time() - 600))   # sobra de horas atrás
        bot.aguardar_codigo_e_entrar(ctx, prazo_segundos=0.3)
        assert "".join(c.valor for c in ctx.campos) == ""   # não foi digitado

    def test_codigo_digitado_pouco_antes_da_tela_ainda_vale(self, monkeypatch):
        """O operador vê o e-mail e digita antes de o portal renderizar."""
        ctx = _com_tela()
        monkeypatch.setattr(bot, "_paginas_logadas", lambda _c: ctx.logadas())
        import time as _t
        bot._otp_queue.put(("123456", _t.time() - 10))     # 10s antes da tela
        assert bot.aguardar_codigo_e_entrar(ctx, prazo_segundos=5) is True
        assert "".join(c.valor for c in ctx.campos) == "123456"

    def test_codigo_de_tentativa_anterior_nao_e_usado_na_tela_nova(self, monkeypatch):
        """Relogin rápido: o código de 3 minutos atrás não serve nesta tela."""
        ctx = _com_tela()
        monkeypatch.setattr(bot, "_paginas_logadas", lambda _c: ctx.logadas())
        import time as _t
        bot._otp_queue.put(("999999", _t.time() - 100))    # antes desta tela
        bot.aguardar_codigo_e_entrar(ctx, prazo_segundos=0.4)
        assert "".join(c.valor for c in ctx.campos) == ""


# ========================================================== RECUPERAÇÃO ====
class TestRecuperacao:
    def test_portal_recusa_o_codigo_e_a_interface_pede_outro(self, monkeypatch):
        ctx = _com_tela()
        ctx.frame.texto_body = "Código inválido"
        monkeypatch.setattr(bot, "_paginas_logadas", lambda _c: [])
        bot.enfileirar_codigo("123456")

        assert bot.aguardar_codigo_e_entrar(ctx, prazo_segundos=1) is False
        tipos = _tipos(_drenar_status())
        # pediu de novo: uma vez ao abrir a tela, outra depois da recusa
        assert tipos.count("otp_needed") >= 2

    def test_nao_insiste_com_codigo_recusado(self, monkeypatch):
        ctx = _com_tela()
        ctx.frame.texto_body = "Código expirado"
        monkeypatch.setattr(bot, "_paginas_logadas", lambda _c: [])
        chamadas = {"n": 0}
        original = otp_flow.preencher_otp

        def contando(*a, **k):
            chamadas["n"] += 1
            return original(*a, **k)

        monkeypatch.setattr(otp_flow, "preencher_otp", contando)
        bot.enfileirar_codigo("123456")
        bot.aguardar_codigo_e_entrar(ctx, prazo_segundos=1)
        assert chamadas["n"] == 1

    def test_tela_some_no_meio_nao_derruba_o_bot(self, monkeypatch):
        """A tela do código desaparece antes de digitarmos."""
        monkeypatch.setattr(bot, "_paginas_logadas", lambda _c: [])
        monkeypatch.setattr(otp_flow, "diagnosticar", lambda *a, **k: "")
        ctx = ContextoFalso([PaginaFalsa(FrameFalso())])
        bot.enfileirar_codigo("123456")
        assert bot.aguardar_codigo_e_entrar(ctx, prazo_segundos=0.3) is False

    def test_botao_parar_interrompe(self, monkeypatch):
        """O laço antigo ignorava o Parar por até 90s."""
        ctx = _com_tela()
        monkeypatch.setattr(bot, "_paginas_logadas", lambda _c: [])
        bot.python_stop_event.set()
        assert bot.aguardar_codigo_e_entrar(ctx, prazo_segundos=60) is False

    def test_prazo_acaba_sem_codigo(self, monkeypatch):
        ctx = _com_tela()
        monkeypatch.setattr(bot, "_paginas_logadas", lambda _c: [])
        assert bot.aguardar_codigo_e_entrar(ctx, prazo_segundos=0.3) is False


# ============================================================ ABAS =========
class TestAbasDuranteOCodigo:
    def test_nenhuma_aba_e_fechada_enquanto_o_codigo_e_esperado(self, monkeypatch):
        """A tela do código costuma vir em popup; fechá-la matava o fluxo."""
        fechadas = []

        class AbaFalsa:
            def __init__(self, url):
                self._url = url

            def is_closed(self):
                return False

            def evaluate(self, _js):
                return self._url

            @property
            def url(self):
                return self._url

            def close(self):
                fechadas.append(self._url)

        principal = AbaFalsa("https://x/spa-base/logged-area/home")
        intrusa = AbaFalsa("https://propaganda.example.com")

        class Ctx:
            pages = [principal, intrusa]

        bot._aguardando_otp.set()
        try:
            bot._fechar_abas_extras(Ctx(), principal)
            assert fechadas == []
        finally:
            bot._aguardando_otp.clear()

        bot._fechar_abas_extras(Ctx(), principal)
        assert fechadas == ["https://propaganda.example.com"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
