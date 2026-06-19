from __future__ import annotations
import base64
from pathlib import Path
from prp.core.config import ConfigStore
from prp.core.models import ActionResult

SCOPES=["https://www.googleapis.com/auth/gmail.readonly","https://www.googleapis.com/auth/gmail.modify"]

class GmailService:
    def __init__(self, config: ConfigStore): self.config=config; self._service=None
    def _client(self):
        if self._service: return self._service
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        token=self.config.path("gmail_token.json"); credentials_path=self.config.secrets().get("gmail_credentials_path","")
        creds=None
        if token.exists(): creds=Credentials.from_authorized_user_file(str(token),SCOPES)
        if creds and creds.expired and creds.refresh_token: creds.refresh(Request())
        if not creds or not creds.valid:
            if not credentials_path or not Path(credentials_path).exists(): raise RuntimeError("Configura gmail_credentials_path en secrets.json")
            creds=InstalledAppFlow.from_client_secrets_file(credentials_path,SCOPES).run_local_server(port=0)
            token.write_text(creds.to_json(),encoding="utf-8")
        self._service=build("gmail","v1",credentials=creds,cache_discovery=False)
        return self._service
    def unread(self, limit: int=10) -> ActionResult:
        try:
            service=self._client(); rows=service.users().messages().list(userId="me",q="is:unread",maxResults=max(1,min(25,int(limit)))).execute().get("messages",[])
            items=[]
            for row in rows:
                msg=service.users().messages().get(userId="me",id=row["id"],format="metadata",metadataHeaders=["From","Subject","Date"]).execute()
                headers={h["name"].lower():h["value"] for h in msg.get("payload",{}).get("headers",[])}
                items.append({"id":row["id"],"from":headers.get("from",""),"subject":headers.get("subject","(sin asunto)"),"date":headers.get("date","")})
            return ActionResult.success(f"Tienes {len(items)} correos no leídos",emails=items)
        except Exception as exc: return ActionResult.failure("No pude consultar Gmail",str(exc))
