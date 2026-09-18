"""
gmail_otp.py — Lê automaticamente o código OTP do Santander no Gmail.

Fluxo:
  1. Na primeira execução abre o navegador para autorizar (OAuth2).
  2. Salva o token em token_gmail.json — nas próximas execuções roda silencioso.
  3. Monitora e-mails de santander@santander.com.br com chegada recente,
     extrai o código de 6 dígitos e retorna.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import time
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# -- Dependências opcionais (Gmail API) ----------------------------------------
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    _GMAIL_DISPONIVEL = True
except ImportError:
    _GMAIL_DISPONIVEL = False
    logger.warning(
        "gmail_otp: bibliotecas nao instaladas. "
        "Rode: pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client"
    )

# -- Configuracoes -------------------------------------------------------------
SCOPES            = ["https://www.googleapis.com/auth/gmail.modify"]

# Caminho ABSOLUTO (pasta deste arquivo). Com caminho relativo, abrir o
# programa de outra pasta fazia o `credentials.json` "sumir" e a autenticacao
# falhar em silencio.
_PASTA            = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE  = os.path.join(_PASTA, "credentials.json")
TOKEN_FILE        = os.path.join(_PASTA, "token_gmail.json")

REMETENTE         = "santander@santander.com.br"

# O codigo vem perto de uma palavra que o anuncia. Pegar "os primeiros 6
# digitos do e-mail" trazia protocolo, data ou numero de contrato.
_RE_COM_CONTEXTO  = re.compile(
    r"(?:c[oó]digo|token|otp|verifica[cç][aã]o|seguran[cç]a|acesso)"
    r"[^0-9]{0,40}(\d{6})", re.IGNORECASE | re.DOTALL)
_RE_ISOLADO       = re.compile(r"(?<![0-9])(\d{6})(?![0-9])")
# Numeros que parecem codigo mas nao sao (ano/mes, CEP com 6, sequencias).
_RE_DATA          = re.compile(r"20\d{4}")

# Janela de busca: so considera e-mails chegados nos ultimos N minutos. Um
# codigo de 15 minutos atras ja' expirou no portal.
JANELA_MINUTOS    = 5


# -- Autenticacao --------------------------------------------------------------

def _get_service():
    """Retorna um objeto autenticado da Gmail API. Abre o navegador na 1a vez."""
    if not _GMAIL_DISPONIVEL:
        raise RuntimeError("Bibliotecas da Gmail API nao instaladas.")

    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(
            f"Arquivo '{CREDENTIALS_FILE}' nao encontrado. "
            "Baixe-o do Google Cloud Console (OAuth 2.0 Client ID -> Desktop app)."
        )

    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w", encoding="utf-8") as fh:
            fh.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


# -- Extracao do codigo --------------------------------------------------------

def _mascarar(codigo: str) -> str:
    """O codigo e' credencial de uso unico: no log vai mascarado."""
    codigo = str(codigo or "")
    return codigo[:2] + "*" * (len(codigo) - 2) if len(codigo) > 2 else "*" * len(codigo)


def _extrair_codigo(texto: str):
    """O codigo de 6 digitos do texto, ou None.

    Primeiro procura perto de uma palavra que anuncia o codigo ("codigo",
    "token", "verificacao"...). So' se nao achar nada assim e' que aceita um
    numero isolado de 6 digitos -- e ainda descarta o que parece data.
    """
    texto = texto or ""
    m = _RE_COM_CONTEXTO.search(texto)
    if m:
        return m.group(1)
    for achado in _RE_ISOLADO.finditer(texto):
        numero = achado.group(1)
        if _RE_DATA.fullmatch(numero):
            continue
        return numero
    return None


def _decodificar_parte(parte: dict) -> str:
    """Decodifica base64url de uma parte do e-mail."""
    data = parte.get("body", {}).get("data", "")
    if data:
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
    return ""


def _extrair_texto_email(msg_payload: dict) -> str:
    """Extrai o texto plano (ou HTML) de um payload de mensagem Gmail."""
    mime = msg_payload.get("mimeType", "")

    if mime in ("text/plain", "text/html"):
        return _decodificar_parte(msg_payload)

    partes = msg_payload.get("parts", [])
    for parte in partes:
        sub_mime = parte.get("mimeType", "")
        if sub_mime == "text/plain":
            return _decodificar_parte(parte)
        if sub_mime in ("text/html", "multipart/alternative"):
            texto = _extrair_texto_email(parte)
            if texto:
                return texto
    return ""


# -- Busca de OTP --------------------------------------------------------------

def _timestamp_unix_minutos_atras(minutos: int) -> int:
    """Retorna timestamp Unix de N minutos atras (para query do Gmail)."""
    t = datetime.now(tz=timezone.utc) - timedelta(minutes=minutos)
    return int(t.timestamp())


_IDS_CONSUMIDOS: set = set()


def checar_otp_agora(service, desde_ts: float = 0.0):
    """Codigo de 6 digitos de um e-mail do Santander AINDA NAO usado.

    `desde_ts` (epoch) descarta e-mail que chegou antes desta espera: num
    relogin rapido, a busca devolvia o e-mail da tentativa anterior -- codigo
    ja' queimado -- e o bot o digitava como se fosse novo.
    """
    try:
        after_ts = _timestamp_unix_minutos_atras(JANELA_MINUTOS)
        # Sem `is:unread`: se o e-mail foi aberto no celular (ou marcado como
        # lido por um filtro), o codigo continua valido e o bot precisa achar.
        query = f"from:{REMETENTE} after:{after_ts}"

        resultado = service.users().messages().list(
            userId="me", q=query, maxResults=5
        ).execute()

        mensagens = resultado.get("messages", [])
        if not mensagens:
            return None

        for ref in mensagens:
            msg_id = ref["id"]
            if msg_id in _IDS_CONSUMIDOS:
                continue                      # este e-mail ja' foi usado
            msg = service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()

            # internalDate vem em milissegundos desde a epoca.
            try:
                chegou = float(msg.get("internalDate", 0)) / 1000.0
            except (TypeError, ValueError):
                chegou = 0.0
            if desde_ts and chegou and chegou < desde_ts:
                continue

            # Tenta extrair do assunto primeiro (mais rapido)
            headers = msg.get("payload", {}).get("headers", [])
            assunto = next(
                (h["value"] for h in headers if h["name"].lower() == "subject"),
                ""
            )
            codigo = _extrair_codigo(assunto)

            # Se nao achou no assunto, tenta no corpo
            if not codigo:
                corpo = _extrair_texto_email(msg.get("payload", {}))
                codigo = _extrair_codigo(corpo)

            if codigo:
                _IDS_CONSUMIDOS.add(msg_id)
                # Marca como lido para nao reutilizar
                try:
                    service.users().messages().modify(
                        userId="me",
                        id=msg_id,
                        body={"removeLabelIds": ["UNREAD"]}
                    ).execute()
                except Exception as e:
                    logger.warning(f"gmail_otp: erro ao marcar como lido: {e}")

                logger.info(f"gmail_otp: codigo encontrado -> {_mascarar(codigo)}")
                return codigo

    except Exception as e:
        logger.warning(f"gmail_otp: erro na busca: {e}")

    return None


def aguardar_otp(timeout: int = 90, intervalo: int = 5, desde: float = None,
                 parar=None):
    """
    Fica verificando o Gmail a cada `intervalo` segundos por ate `timeout` segundos.
    Retorna o codigo OTP encontrado, ou None se esgotar o tempo.

    Args:
        timeout:   Tempo maximo de espera em segundos (padrao 90s).
        intervalo: Intervalo entre verificacoes em segundos (padrao 5s).
    """
    if not _GMAIL_DISPONIVEL:
        logger.warning("gmail_otp: bibliotecas indisponiveis — modo manual ativado.")
        return None

    try:
        service = _get_service()
    except Exception as e:
        logger.warning(f"gmail_otp: falha na autenticacao: {e}")
        return None

    logger.info(f"gmail_otp: aguardando OTP por ate {timeout}s...")
    fim = time.time() + timeout
    # Uma folga para tras: o e-mail costuma sair no instante em que a tela do
    # codigo aparece, as vezes um pouco antes de comecarmos a olhar.
    desde_ts = (desde if desde is not None else time.time()) - 60

    while time.time() < fim:
        if parar is not None and parar.is_set():
            logger.info("gmail_otp: leitura cancelada (login concluido).")
            return None
        codigo = checar_otp_agora(service, desde_ts)
        if codigo:
            return codigo
        time.sleep(intervalo)

    logger.info("gmail_otp: timeout — OTP nao encontrado no Gmail.")
    return None
