from __future__ import annotations
import subprocess, os
from prp.core.models import ActionResult

class NotificationService:
    def show(self, title: str, message: str) -> ActionResult:
        try:
            if os.name == "nt":
                safe_title=title.replace("'","''"); safe_message=message.replace("'","''")
                script=f"Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('{safe_message}','{safe_title}') | Out-Null"
                subprocess.Popen(["powershell","-NoProfile","-Command",script],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            return ActionResult.success(f"Notificación: {title}")
        except Exception as exc: return ActionResult.failure("No pude mostrar la notificación",str(exc))
