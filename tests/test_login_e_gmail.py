"""
Testes das peças do login e da leitura do código no Gmail.

Foco no que quebrava calado: o bot achar que não está logado estando,
consumir código velho da fila, fechar a aba do código, e o Gmail devolver um
número qualquer de seis dígitos como se fosse o código.

Nenhum teste abre navegador, portal ou Gmail.
"""
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import bot            # noqa: E402
import gmail_otp      # noqa: E402


class PaginaFalsa:
    def __init__(self, url, fechada=False):
        self._url = url
        self.fechada = fechada

    def is_closed(self):
        return self.fechada

    def evaluate(self, _js):
        if self.fechada:
            raise RuntimeError("Target page, context or browser has been closed")
        return self._url

    @property
    def url(self):
        return self._url


class CtxFalso:
    def __init__(self, *paginas):
        self.pages = list(paginas)


# ===================================================== 1. ESTOU LOGADO? ====
class TestPaginaLogada:
    def test_home_conta_como_logado(self):
        """O portal para em /logged-area/home depois do login.

        Regressão: o critério antigo exigia `recommendation` na URL, então o
        bot concluía "ainda expirado" estando dentro — e girava horas.
        """
        ctx = CtxFalso(PaginaFalsa("https://www.parceirosantander.com.br/spa-base/logged-area/home"))
        assert bot._pagina_logada(ctx) is not None

    def test_formulario_tambem_conta(self):
        ctx = CtxFalso(PaginaFalsa(
            "https://www.parceirosantander.com.br/spa-base/logged-area/recommendation/"))
        assert bot._pagina_logada(ctx) is not None

    def test_landing_nao_conta(self):
        ctx = CtxFalso(PaginaFalsa(
            "https://www.parceirosantander.com.br/spa-base/landing-page"))
        assert bot._pagina_logada(ctx) is None

    def test_tela_de_login_nao_conta(self):
        ctx = CtxFalso(PaginaFalsa("https://id.santander.com.br/login?x=1"))
        assert bot._pagina_logada(ctx) is None

    def test_pagina_fechada_e_ignorada(self):
        ctx = CtxFalso(PaginaFalsa("https://x/spa-base/logged-area/home", fechada=True))
        assert bot._pagina_logada(ctx) is None


class TestSessaoExpirada:
    def test_pagina_fechada_conta_como_expirada(self):
        """Antes, page fechada devolvia a URL do cache e passava por viva."""
        assert bot.sessao_expirada(PaginaFalsa("https://x/logged-area/home", fechada=True)) is True

    def test_landing_e_expirada(self):
        assert bot.sessao_expirada(PaginaFalsa("https://x/spa-base/landing-page")) is True

    def test_dentro_do_portal_nao_e_expirada(self):
        assert bot.sessao_expirada(PaginaFalsa("https://x/spa-base/logged-area/home")) is False


# ====================================================== 2. ABAS ============
class TestAbasProtegidas:
    @pytest.mark.parametrize("url", [
        "https://id.santander.com.br/oauth/authorize",   # domínio do login
        "https://sso.santander.com.br/verificacao",      # tela do código
        "https://x/openid/connect",
    ])
    def test_tela_de_login_nunca_fecha(self, url):
        assert bot._aba_protegida(url) is True
        assert bot._aba_protegida(url, esperando_codigo=True) is True

    @pytest.mark.parametrize("url", [
        "about:blank",
        "",
        "https://www.parceirosantander.com.br/spa-base/logged-area/home",
        "https://www.google.com",
    ])
    def test_enquanto_espera_o_codigo_nada_fecha(self, url):
        assert bot._aba_protegida(url, esperando_codigo=True) is True

    @pytest.mark.parametrize("url", [
        "about:blank",                                   # aba em branco vazando
        "https://www.parceirosantander.com.br/spa-base/logged-area/home",  # duplicata
        "https://www.google.com",
    ])
    def test_fora_da_espera_a_faxina_volta_ao_normal(self, url):
        """Proteger o portal inteiro deixava aba velha em /logged-area/ —
        justamente a que fazia o bot achar que já estava logado."""
        assert bot._aba_protegida(url) is False


# ================================================== 3. FILA DE CÓDIGOS =====
class TestFilaDeCodigos:
    def setup_method(self):
        bot._drenar_fila_otp()

    def teardown_method(self):
        bot._drenar_fila_otp()

    def test_drenar_descarta_tudo(self):
        bot.enfileirar_codigo("111111")
        bot.enfileirar_codigo("222222")
        assert bot._drenar_fila_otp() == 2
        assert bot._proximo_codigo() is None

    def test_proximo_codigo_devolve_o_que_chegou(self):
        bot.enfileirar_codigo(" 123456 ")
        assert bot._proximo_codigo() == "123456"
        assert bot._proximo_codigo() is None

    def test_codigo_velho_e_descartado_sozinho(self):
        """Sobra de uma tentativa anterior: o portal já não aceita."""
        import time
        bot._otp_queue.put(("999999", time.time() - 600))
        bot.enfileirar_codigo("123456")
        assert bot._proximo_codigo() == "123456"

    def test_codigo_recem_digitado_nao_e_jogado_fora(self):
        """O operador digita enquanto o bot ainda está na tela de senha."""
        bot.enfileirar_codigo("123456")
        assert bot._proximo_codigo() == "123456"

    def test_formato_antigo_continua_aceito(self):
        bot._otp_queue.put("123456")
        assert bot._proximo_codigo() == "123456"


class TestMarcoDaTela:
    def setup_method(self):
        bot._drenar_fila_otp()
        bot.marcar_tela_de_codigo(0.0)

    def teardown_method(self):
        bot._drenar_fila_otp()
        bot.marcar_tela_de_codigo(0.0)

    def test_codigo_anterior_a_tela_e_descartado(self):
        import time
        agora = time.time()
        bot._otp_queue.put(("999999", agora - 200))
        bot.marcar_tela_de_codigo(agora)
        assert bot._proximo_codigo() is None

    def test_codigo_pouco_antes_da_tela_sobrevive(self):
        import time
        agora = time.time()
        bot._otp_queue.put(("123456", agora - 10))
        bot.marcar_tela_de_codigo(agora)
        assert bot._proximo_codigo() == "123456"


class TestWatcherDoGmail:
    def test_nao_cria_duas_threads(self, monkeypatch):
        """Cada tentativa de login criava outra thread; as duas competiam pela
        mesma caixa e a segunda dizia 'não encontrei'."""
        criadas = []

        class ThreadFalsa:
            def __init__(self, *a, **k):
                criadas.append(self)
                self.viva = True

            def start(self):
                pass

            def is_alive(self):
                return self.viva

        monkeypatch.setattr(bot, "_GMAIL_OTP", True)
        monkeypatch.setattr(bot.threading, "Thread", ThreadFalsa)
        monkeypatch.setattr(bot, "_gmail_thread", None)
        bot._iniciar_watcher_gmail()
        bot._iniciar_watcher_gmail()
        assert len(criadas) == 1
        criadas[0].viva = False
        bot._iniciar_watcher_gmail()
        assert len(criadas) == 2


# ============================================ 3b. PREENCHER CPF E SENHA ====
class CampoComMascara:
    """O campo do CPF do portal: formata sozinho o que for digitado."""

    def __init__(self, mascara=True):
        self.valor = ""
        self.mascara = mascara
        self.visivel = True

    def click(self, force=False, timeout=None):
        pass

    def fill(self, texto):
        if texto == "":
            self.valor = ""
            return
        # `fill` joga o texto inteiro: com máscara, texto já pontuado vira lixo
        self.valor = self._formatar(texto) if self.mascara else texto

    def type(self, texto, delay=None):
        for ch in texto:
            self.valor = self._formatar(
                "".join(c for c in self.valor + ch if c.isdigit()))

    def input_value(self):
        return self.valor

    def _formatar(self, texto):
        if not self.mascara:
            return texto
        d = "".join(c for c in texto if c.isdigit())[:11]
        if len(d) <= 3:
            return d
        if len(d) <= 6:
            return f"{d[:3]}.{d[3:]}"
        if len(d) <= 9:
            return f"{d[:3]}.{d[3:6]}.{d[6:]}"
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


class PaginaDeLogin:
    def __init__(self, campos):
        self.campos = campos            # seletor -> campo

    def wait_for_selector(self, seletor, state=None, timeout=None):
        if seletor in self.campos:
            return self.campos[seletor]
        raise RuntimeError("timeout")

    def locator(self, seletor):
        class _L:
            first = self.campos.get(seletor)
        return _L()


class TestPreencherLogin:
    def test_cpf_formatado_entra_certo_no_campo_com_mascara(self):
        """Regressão: o CPF salvo vem com pontos; mandar assim pela `fill`
        fazia a máscara formatar por cima e o valor sair inválido."""
        campo = CampoComMascara()
        pagina = PaginaDeLogin({"input#inputUser": campo})
        ok = bot._preencher_campo_login(pagina, ["input#inputUser"],
                                        "529.982.247-25", "cpf", so_digitos=True)
        assert ok is True
        assert campo.valor == "529.982.247-25"

    def test_senha_vai_literal(self):
        campo = CampoComMascara(mascara=False)
        pagina = PaginaDeLogin({"input#inputPassword": campo})
        assert bot._preencher_campo_login(pagina, ["input#inputPassword"],
                                          "s3nh@!123", "senha") is True
        assert campo.valor == "s3nh@!123"

    def test_sem_credencial_avisa_e_para(self):
        pagina = PaginaDeLogin({"input#inputUser": CampoComMascara()})
        assert bot._preencher_campo_login(pagina, ["input#inputUser"],
                                          "", "cpf", so_digitos=True) is False

    def test_campo_que_nao_aparece_nao_vira_sucesso(self):
        pagina = PaginaDeLogin({})
        assert bot._preencher_campo_login(pagina, ["input#inputUser"],
                                          "52998224725", "cpf", so_digitos=True) is False

    def test_campo_que_ignora_escrita_e_reportado(self):
        class Teimoso(CampoComMascara):
            def type(self, texto, delay=None):
                pass

            def fill(self, texto):
                self.valor = ""

        pagina = PaginaDeLogin({"input#inputUser": Teimoso()})
        assert bot._preencher_campo_login(pagina, ["input#inputUser"],
                                          "52998224725", "cpf", so_digitos=True) is False


# ================================================ 4. CREDENCIAIS E CONFIG ==
class TestCredenciaisEConfig:
    def test_recarrega_sem_reiniciar(self, tmp_path, monkeypatch):
        """A GUI grava o arquivo e o bot precisa enxergar na hora."""
        arquivo = tmp_path / "credenciais.ini"
        arquivo.write_text("[acesso]\ncpf = 52998224725\nsenha = trocada\n", encoding="utf-8")
        monkeypatch.setattr(bot, "CREDENCIAIS_INI", str(arquivo))
        monkeypatch.delenv("SANTANDER_CPF", raising=False)
        monkeypatch.delenv("SANTANDER_SENHA", raising=False)
        assert bot.recarregar_credenciais() is True
        assert bot.CPF_ACESSO == "52998224725"
        assert bot.SENHA_ACESSO == "trocada"

    def test_senha_com_porcento_nao_quebra(self, tmp_path, monkeypatch):
        """ConfigParser padrão trata % como interpolação e estoura na leitura."""
        arquivo = tmp_path / "credenciais.ini"
        arquivo.write_text("[acesso]\ncpf = 52998224725\nsenha = a%b%c\n", encoding="utf-8")
        monkeypatch.setattr(bot, "CREDENCIAIS_INI", str(arquivo))
        monkeypatch.delenv("SANTANDER_CPF", raising=False)
        monkeypatch.delenv("SANTANDER_SENHA", raising=False)
        assert bot.recarregar_credenciais() is True
        assert bot.SENHA_ACESSO == "a%b%c"

    def test_navegador_vem_do_config_ini(self, tmp_path, monkeypatch):
        """Em outro PC, o caminho fixo do Brave não existe."""
        arquivo = tmp_path / "config.ini"
        arquivo.write_text(
            "[navegador]\nexecutavel = D:\\Chrome\\chrome.exe\nperfil = D:\\perfil\n",
            encoding="utf-8")
        monkeypatch.setattr(bot, "CONFIG_INI", str(arquivo))
        exe, perfil = bot.carregar_config()
        assert exe.endswith("chrome.exe") and perfil.endswith("perfil")


# ======================================================= 5. GMAIL / OTP ====
class TestExtracaoDoCodigo:
    def test_pega_o_codigo_anunciado_e_nao_o_protocolo(self):
        texto = ("Protocolo 998877 - Santander\n"
                 "Seu código de verificação é 123456. Válido por 5 minutos.")
        assert gmail_otp._extrair_codigo(texto) == "123456"

    def test_aceita_token_e_acesso_como_anuncio(self):
        assert gmail_otp._extrair_codigo("Token de acesso: 445566") == "445566"

    def test_ignora_ano_mes_quando_isolado(self):
        assert gmail_otp._extrair_codigo("Atualizado em 202609 pelo sistema") is None

    def test_numero_isolado_serve_quando_nao_ha_anuncio(self):
        assert gmail_otp._extrair_codigo("Use 778899 para entrar") == "778899"

    def test_nao_confunde_numero_maior(self):
        assert gmail_otp._extrair_codigo("Contrato 1234567890") is None

    def test_texto_vazio(self):
        assert gmail_otp._extrair_codigo("") is None

    def test_codigo_nunca_vai_inteiro_para_o_log(self):
        assert gmail_otp._mascarar("123456") == "12****"

    def test_caminhos_sao_absolutos(self):
        """Abrir o programa de outra pasta fazia o credentials.json sumir."""
        assert Path(gmail_otp.CREDENTIALS_FILE).is_absolute()
        assert Path(gmail_otp.TOKEN_FILE).is_absolute()
        assert Path(gmail_otp.CREDENTIALS_FILE).parent == RAIZ

    def test_nao_devolve_duas_vezes_o_mesmo_email(self):
        """Num relogin rápido, a busca devolvia o e-mail da tentativa anterior
        — código já queimado — e o bot o digitava como se fosse novo."""
        import time as _t

        agora = _t.time()

        class ServicoFalso:
            def __init__(self):
                self.mensagens = {"m1": {
                    "internalDate": str(int(agora * 1000)),
                    "payload": {"headers": [{"name": "Subject",
                                             "value": "Seu código é 123456"}]},
                }}

            def users(self):
                return self

            def messages(self):
                return self

            def list(self, **_kw):
                return _Exec({"messages": [{"id": "m1"}]})

            def get(self, id=None, **_kw):
                return _Exec(self.mensagens[id])

            def modify(self, **_kw):
                return _Exec({})

        class _Exec:
            def __init__(self, valor):
                self.valor = valor

            def execute(self):
                return self.valor

        gmail_otp._IDS_CONSUMIDOS.clear()
        servico = ServicoFalso()
        assert gmail_otp.checar_otp_agora(servico, agora - 60) == "123456"
        assert gmail_otp.checar_otp_agora(servico, agora - 60) is None

    def test_email_anterior_a_espera_e_ignorado(self):
        """O e-mail chegou ANTES desta tela: é o código da tentativa passada."""
        import time as _t

        agora = _t.time()

        class _Exec:
            def __init__(self, valor):
                self.valor = valor

            def execute(self):
                return self.valor

        class ServicoVelho:
            def users(self):
                return self

            def messages(self):
                return self

            def list(self, **_kw):
                return _Exec({"messages": [{"id": "velho"}]})

            def get(self, **_kw):
                return _Exec({
                    "internalDate": str(int((agora - 900) * 1000)),
                    "payload": {"headers": [{"name": "Subject",
                                             "value": "Seu código é 999999"}]},
                })

            def modify(self, **_kw):
                return _Exec({})

        gmail_otp._IDS_CONSUMIDOS.clear()
        assert gmail_otp.checar_otp_agora(ServicoVelho(), agora - 60) is None

    def test_janela_curta(self):
        """15 minutos aceitava código já expirado."""
        assert gmail_otp.JANELA_MINUTOS <= 10


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
