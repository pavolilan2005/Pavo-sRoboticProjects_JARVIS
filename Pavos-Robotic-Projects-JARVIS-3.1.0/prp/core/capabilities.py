from __future__ import annotations

import concurrent.futures
import threading
from typing import Any, Callable

from .event_bus import EventBus
from .models import ActionResult, Capability, RiskLevel


class CapabilityError(RuntimeError):
    pass


class CapabilityRegistry:
    def __init__(
        self,
        event_bus: EventBus,
        confirmer: Callable[[str, str], bool] | None = None,
    ):
        self.event_bus = event_bus
        self.confirmer = confirmer or (lambda _title, _message: False)
        self._items: dict[str, Capability] = {}
        self._lock = threading.RLock()
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=8, thread_name_prefix="JarvisCapability"
        )

    def register(self, capability: Capability, replace: bool = False) -> None:
        with self._lock:
            if capability.name in self._items and not replace:
                raise CapabilityError(f"Capability already registered: {capability.name}")
            self._items[capability.name] = capability
        self.event_bus.publish(
            "capability.registered", {"capability": capability.public_dict()}, "core"
        )

    def register_handler(
        self,
        name: str,
        description: str,
        handler,
        *,
        risk: RiskLevel = RiskLevel.LOW,
        requires_confirmation: bool = False,
        timeout_seconds: float = 30.0,
        tags: tuple[str, ...] = (),
        schema: dict[str, Any] | None = None,
        replace: bool = False,
    ) -> None:
        self.register(
            Capability(
                name=name,
                description=description,
                handler=handler,
                risk=risk,
                requires_confirmation=requires_confirmation,
                timeout_seconds=timeout_seconds,
                tags=tags,
                schema=schema or {},
            ),
            replace=replace,
        )

    def get(self, name: str) -> Capability | None:
        with self._lock:
            return self._items.get(name)

    def list(self, tag: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            values = list(self._items.values())
        if tag:
            values = [c for c in values if tag in c.tags]
        return sorted((c.public_dict() for c in values), key=lambda c: c["name"])

    def execute(
        self,
        name: str,
        params: dict[str, Any] | None = None,
        *,
        confirmed: bool = False,
        timeout: float | None = None,
    ) -> ActionResult:
        capability = self.get(name)
        if not capability:
            return ActionResult.failure(
                f"La capacidad '{name}' no está registrada.", error="capability_not_found"
            )
        params = dict(params or {})

        if capability.requires_confirmation and not confirmed:
            allowed = self.confirmer(
                capability.name,
                f"JARVIS quiere ejecutar una acción de riesgo {capability.risk.value}: {capability.description}",
            )
            if not allowed:
                return ActionResult.failure(
                    "La acción fue cancelada porque requiere confirmación.",
                    error="confirmation_required",
                )

        self.event_bus.publish(
            "capability.started", {"name": name, "params": params}, "capability_registry"
        )
        future = self._executor.submit(capability.handler, params)
        try:
            raw = future.result(timeout=timeout or capability.timeout_seconds)
            result = self._normalize(raw)
            if capability.verifier and result.ok:
                try:
                    if not capability.verifier(params, result):
                        result = ActionResult.failure(
                            f"La acción '{name}' se ejecutó, pero no pudo verificarse.",
                            error="verification_failed",
                            original=result.to_dict(),
                        )
                except Exception as exc:
                    result.warnings.append(f"No se pudo verificar: {exc}")
        except concurrent.futures.TimeoutError:
            future.cancel()
            result = ActionResult.failure(
                f"La acción '{name}' excedió el tiempo límite.", error="timeout"
            )
        except Exception as exc:
            result = ActionResult.failure(
                f"Falló la acción '{name}': {exc}", error=type(exc).__name__
            )

        self.event_bus.publish(
            "capability.finished",
            {"name": name, "params": params, "result": result.to_dict()},
            "capability_registry",
        )
        return result

    @staticmethod
    def _normalize(raw: Any) -> ActionResult:
        if isinstance(raw, ActionResult):
            return raw.finish()
        if isinstance(raw, dict):
            if "ok" in raw:
                return ActionResult(
                    bool(raw.get("ok")),
                    str(raw.get("message", "Acción completada.")),
                    data=dict(raw.get("data") or {}),
                    warnings=list(raw.get("warnings") or []),
                    error=str(raw.get("error") or ""),
                ).finish()
            return ActionResult.success("Acción completada.", result=raw)
        if isinstance(raw, bool):
            return ActionResult.success("Acción completada.") if raw else ActionResult.failure("La acción no pudo completarse.")
        if raw is None:
            return ActionResult.success("Acción completada.")
        return ActionResult.success(str(raw))
