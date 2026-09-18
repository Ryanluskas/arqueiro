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
CREDENTIALS_FILE  = "credentials.json"    # baixado do Google Cloud Console
TOKEN_FILE        = "token_gmail.json"    # gerado automaticamente apos 1a autorizacao

REMETENTE         = "santander@santander.com.br"
# Regex: captura exatamente 6 digitos consecutivos (mais flexível)
_RE_CODIGO        = re.compile(r"(\d{6})")
# Janela de busca: so considera e-mails chegados nos ultimos N minutos
JANELA_MINUTOS    = 15


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

def _extrair_codigo(texto: str):
    """Retorna o 1o codigo de 6 digitos encontrado no texto, ou None."""
    m = _RE_CODIGO.search(texto)
    return m.group(1) if m else None


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


def checar_otp_agora(service):
    """
    Verifica se ha e-mail OTP do Santander nao lido na janela recente.
    Retorna o codigo de 6 digitos ou None.
    """
    try:
        after_ts = _timestamp_unix_minutos_atras(JANELA_MINUTOS)
        query = f"from:{REMETENTE} is:unread after:{after_ts}"

        resultado = service.users().messages().list(
            userId="me", q=query, maxResults=5
        ).execute()

        mensagens = resultado.get("messages", [])
        if not mensagens:
            return None

        for ref in mensagens:
            msg_id = ref["id"]
            msg = service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()

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
                # Marca como lido para nao reutilizar
                try:
                    service.users().messages().modify(
                        userId="me",
                        id=msg_id,
                        body={"removeLabelIds": ["UNREAD"]}
                    ).execute()
                except Exception as e:
                    logger.warning(f"gmail_otp: erro ao marcar como lido: {e}")

                logger.info(f"gmail_otp: codigo encontrado -> {codigo} (assunto: {assunto[:60]})")
                return codigo

    except Exception as e:
        logger.warning(f"gmail_otp: erro na busca: {e}")

    return None


def aguardar_otp(timeout: int = 90, intervalo: int = 5):
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

    while time.time() < fim:
        codigo = checar_otp_agora(service)
        if codigo:
            return codigo
        time.sleep(intervalo)

    logger.info("gmail_otp: timeout — OTP nao encontrado no Gmail.")
    return None
