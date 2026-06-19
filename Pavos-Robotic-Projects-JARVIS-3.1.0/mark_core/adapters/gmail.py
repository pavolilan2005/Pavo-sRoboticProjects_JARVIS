from __future__ import annotations

import base64
from email.header import decode_header
from pathlib import Path
from typing import Any

from mark_core.models import ActionResult


GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


class GmailAdapter:
    def __init__(self, registry, event_bus, config_getter, base_dir: Path):
        self.registry = registry
        self.event_bus = event_bus
        self.config_getter = config_getter
        self.base_dir = base_dir

    def register(self) -> None:
        r = self.registry.register_handler
        r("gmail.unread", "Lista los correos no leídos más recientes.", self.unread, tags=("gmail", "email"))
        r("gmail.search", "Busca correos con la sintaxis de Gmail.", self.search, tags=("gmail", "email"))
        r("gmail.read", "Lee el contenido de un correo por ID.", self.read, tags=("gmail", "email"))
        r("gmail.mark_read", "Marca un correo como leído.", self.mark_read, tags=("gmail", "email"))
        r("gmail.status", "Comprueba la autorización de Gmail.", self.status, tags=("gmail", "email"))

    def _config(self) -> dict[str, Any]:
        return dict(self.config_getter().get("gmail") or {})

    def _service(self):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError("Faltan las dependencias de Gmail. Ejecuta INSTALAR_JARVIS.bat.") from exc

        cfg = self._config()
        credentials_path = Path(str(cfg.get("credentials_path") or self.base_dir / "config" / "gmail_credentials.json"))
        token_path = Path(str(cfg.get("token_path") or self.base_dir / "config" / "gmail_token.json"))
        if not credentials_path.exists():
            raise RuntimeError(f"No existe {credentials_path.name}. Descarga credenciales OAuth Desktop y configúralas en el Centro de Control.")
        creds = None
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), GMAIL_SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), GMAIL_SCOPES)
                creds = flow.run_local_server(port=0)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json(), encoding="utf-8")
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def status(self, _params: dict[str, Any]) -> ActionResult:
        try:
            profile = self._service().users().getProfile(userId="me").execute()
            return ActionResult.success(f"Gmail conectado como {profile.get('emailAddress', '')}.", profile=profile)
        except Exception as exc:
            return ActionResult.failure(f"Gmail no está listo: {exc}", error=str(exc))

    def unread(self, params: dict[str, Any]) -> ActionResult:
        params = dict(params)
        params.setdefault("query", "is:unread")
        return self.search(params)

    def search(self, params: dict[str, Any]) -> ActionResult:
        query = str(params.get("query", "is:unread")).strip()
        limit = max(1, min(50, int(params.get("limit", 10))))
        try:
            service = self._service()
            response = service.users().messages().list(userId="me", q=query, maxResults=limit).execute()
            items = []
            for ref in response.get("messages", []):
                msg = service.users().messages().get(userId="me", id=ref["id"], format="metadata", metadataHeaders=["From", "Subject", "Date"]).execute()
                headers = self._headers(msg)
                items.append({"id": msg["id"], "thread_id": msg.get("threadId"), "from": headers.get("from", ""), "subject": headers.get("subject", "(sin asunto)"), "date": headers.get("date", ""), "snippet": msg.get("snippet", "")})
            if not items:
                return ActionResult.success("No encontré correos que coincidan.", emails=[])
            summary = "; ".join(f"{m['from']}: {m['subject']}" for m in items[:5])
            return ActionResult.success(f"Encontré {len(items)} correos. {summary}", emails=items, query=query)
        except Exception as exc:
            return ActionResult.failure(f"No pude consultar Gmail: {exc}", error=str(exc))

    def read(self, params: dict[str, Any]) -> ActionResult:
        message_id = str(params.get("message_id", "")).strip()
        if not message_id:
            return ActionResult.failure("Falta message_id.")
        try:
            msg = self._service().users().messages().get(userId="me", id=message_id, format="full").execute()
            headers = self._headers(msg)
            body = self._body(msg.get("payload") or {})
            return ActionResult.success(f"Correo de {headers.get('from', '')}: {headers.get('subject', '')}. {body[:500]}", email={"id": message_id, "headers": headers, "body": body, "snippet": msg.get("snippet", "")})
        except Exception as exc:
            return ActionResult.failure(f"No pude leer el correo: {exc}", error=str(exc))

    def mark_read(self, params: dict[str, Any]) -> ActionResult:
        message_id = str(params.get("message_id", "")).strip()
        if not message_id:
            return ActionResult.failure("Falta message_id.")
        try:
            self._service().users().messages().modify(userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}).execute()
            return ActionResult.success("Correo marcado como leído.", message_id=message_id)
        except Exception as exc:
            return ActionResult.failure(f"No pude marcar el correo: {exc}")

    @staticmethod
    def _headers(msg: dict[str, Any]) -> dict[str, str]:
        result = {}
        for header in (msg.get("payload") or {}).get("headers", []):
            name = str(header.get("name", "")).lower()
            value = str(header.get("value", ""))
            if name == "subject":
                try:
                    decoded = decode_header(value)
                    value = "".join(part.decode(enc or "utf-8", errors="replace") if isinstance(part, bytes) else part for part, enc in decoded)
                except Exception:
                    pass
            result[name] = value
        return result

    @classmethod
    def _body(cls, payload: dict[str, Any]) -> str:
        mime = str(payload.get("mimeType", ""))
        data = (payload.get("body") or {}).get("data")
        if data and mime in {"text/plain", "text/html", ""}:
            try:
                text = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")
                if mime == "text/html":
                    try:
                        from bs4 import BeautifulSoup
                        return BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
                    except Exception:
                        return text
                return text
            except Exception:
                pass
        for part in payload.get("parts", []) or []:
            text = cls._body(part)
            if text:
                return text
        return ""
