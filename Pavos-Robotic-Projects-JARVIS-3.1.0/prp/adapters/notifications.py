from __future__ import annotations

from typing import Any

from prp.core.models import ActionResult


class NotificationsAdapter:
    def __init__(self, registry, event_bus, ui=None):
        self.registry = registry
        self.event_bus = event_bus
        self.ui = ui
        self._items: list[dict[str, Any]] = []
        self.event_bus.subscribe("notification.*", self._capture)

    def register(self) -> None:
        self.registry.register_handler("notifications.emit", "Crea una notificación interna y visual.", self.emit, tags=("notifications",))
        self.registry.register_handler("notifications.list", "Lista notificaciones recientes de JARVIS.", self.list_items, tags=("notifications",))
        self.registry.register_handler("notifications.read", "Devuelve notificaciones recientes para lectura por voz.", self.list_items, tags=("notifications",))
        self.registry.register_handler("notifications.windows", "Consulta notificaciones de Windows si el adaptador WinRT está disponible.", self.windows_notifications, tags=("notifications", "windows"))

    def _capture(self, event) -> None:
        item = {"topic": event.topic, "timestamp": event.timestamp, **event.payload}
        self._items.append(item)
        self._items[:] = self._items[-300:]

    def emit(self, params: dict[str, Any]) -> ActionResult:
        title = str(params.get("title", "JARVIS"))
        message = str(params.get("message", ""))
        priority = str(params.get("priority", "normal"))
        self.event_bus.publish("notification.created", {"title": title, "message": message, "priority": priority}, "notifications")
        if self.ui:
            try:
                self.ui.write_log(f"NOTIFY [{priority.upper()}] {title}: {message}")
            except Exception:
                pass
        try:
            from win10toast import ToastNotifier
            ToastNotifier().show_toast(title, message, duration=4, threaded=True)
        except Exception:
            pass
        return ActionResult.success(f"Notificación: {message}", title=title, message=message, priority=priority)

    def list_items(self, params: dict[str, Any]) -> ActionResult:
        limit = max(1, min(100, int(params.get("limit", 10))))
        items = self._items[-limit:]
        if not items:
            return ActionResult.success("No hay notificaciones recientes.", notifications=[])
        summary = "; ".join(str(i.get("message") or i.get("title") or i.get("topic")) for i in items[-5:])
        return ActionResult.success(f"Hay {len(items)} notificaciones recientes: {summary}", notifications=items)

    def windows_notifications(self, params: dict[str, Any]) -> ActionResult:
        # WinRT notification access requires explicit user permission and optional
        # Windows Runtime packages. Keep it isolated so the core remains portable.
        try:
            import asyncio
            from winrt.windows.ui.notifications.management import UserNotificationListener
            from winrt.windows.ui.notifications import NotificationKinds, KnownNotificationBindings

            async def collect():
                listener = UserNotificationListener.current
                access = await listener.request_access_async()
                if "allowed" not in str(access).lower():
                    return [], str(access)
                notifications = await listener.get_notifications_async(NotificationKinds.TOAST)
                results = []
                for note in list(notifications)[: int(params.get("limit", 20))]:
                    try:
                        binding = note.notification.visual.get_binding(KnownNotificationBindings.toast_generic)
                        texts = [str(t.text) for t in binding.get_text_elements()] if binding else []
                        results.append({"app": str(note.app_info.display_info.display_name), "text": texts, "id": int(note.id)})
                    except Exception:
                        pass
                return results, str(access)

            try:
                asyncio.get_running_loop()
                return ActionResult.failure("La consulta WinRT debe ejecutarse fuera del bucle Live.")
            except RuntimeError:
                items, access = asyncio.run(collect())
            return ActionResult.success(f"Windows reportó {len(items)} notificaciones.", notifications=items, access=access)
        except ImportError:
            return ActionResult.failure(
                "El lector de notificaciones de Windows es opcional. Instala requirements-optional-windows.txt y concede permiso en Windows.",
                error="winrt_not_installed",
            )
        except Exception as exc:
            return ActionResult.failure(f"No pude leer las notificaciones de Windows: {exc}", error=str(exc))
