from __future__ import annotations

import concurrent.futures
import copy
import operator
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .capabilities import CapabilityRegistry
from .event_bus import EventBus
from .models import ActionResult
from .storage import JsonStore


@dataclass
class RoutineRun:
    run_id: str
    routine_id: str
    status: str = "pending"
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str = ""
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)

    def public(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "routine_id": self.routine_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "steps": self.steps,
            "warnings": self.warnings,
            "error": self.error,
        }


DEFAULT_ROUTINES = {
    "version": 1,
    "routines": [
        {
            "id": "modo_stream",
            "name": "Modo Stream",
            "aliases": ["modo stream", "prepara el directo", "vamos a transmitir"],
            "description": "Prepara aplicaciones, música, OBS e iluminación para transmitir.",
            "steps": [
                {
                    "parallel": [
                        {"capability": "apps.open", "params": {"app_name": "OBS Studio"}, "critical": True},
                        {"capability": "apps.open", "params": {"app_name": "Spotify"}, "critical": False},
                        {
                            "capability": "browser.open",
                            "params": {"url": "https://dashboard.twitch.tv/"},
                            "critical": False,
                        },
                    ]
                },
                {"wait": 3},
                {
                    "capability": "obs.set_scene",
                    "params": {"scene": "Starting Soon"},
                    "critical": False,
                    "retries": 1,
                },
                {
                    "capability": "spotify.play_playlist",
                    "params": {"playlist": "Stream"},
                    "critical": False,
                },
                {
                    "capability": "spotify.set_volume",
                    "params": {"volume": 22},
                    "critical": False,
                },
                {
                    "capability": "domotics.activate_scene",
                    "params": {"scene": "stream"},
                    "critical": False,
                },
                {"capability": "pc.status", "params": {}, "critical": False},
            ],
        },
        {
            "id": "terminar_stream",
            "name": "Terminar Stream",
            "aliases": ["termina el stream", "cierra el directo"],
            "description": "Cierra el entorno de streaming de forma segura.",
            "steps": [
                {"capability": "obs.stop_recording", "params": {}, "critical": False},
                {
                    "capability": "spotify.pause",
                    "params": {},
                    "critical": False,
                },
                {
                    "capability": "domotics.activate_scene",
                    "params": {"scene": "normal"},
                    "critical": False,
                },
            ],
        },
        {
            "id": "modo_estudio",
            "name": "Modo Estudio",
            "aliases": ["modo estudio", "vamos a estudiar"],
            "description": "Prepara un entorno de concentración.",
            "steps": [
                {
                    "parallel": [
                        {"capability": "apps.open", "params": {"app_name": "Visual Studio Code"}, "critical": False},
                        {"capability": "apps.open", "params": {"app_name": "Spotify"}, "critical": False},
                    ]
                },
                {"capability": "spotify.play_playlist", "params": {"playlist": "Focus"}, "critical": False},
                {"capability": "spotify.set_volume", "params": {"volume": 18}, "critical": False},
                {"capability": "domotics.activate_scene", "params": {"scene": "estudio"}, "critical": False},
            ],
        },
    ],
}


class RoutineEngine:
    OPERATORS = {
        "==": operator.eq,
        "!=": operator.ne,
        ">": operator.gt,
        ">=": operator.ge,
        "<": operator.lt,
        "<=": operator.le,
        "contains": lambda a, b: b in a,
        "truthy": lambda a, _b: bool(a),
    }

    def __init__(self, registry: CapabilityRegistry, event_bus: EventBus, path):
        self.registry = registry
        self.event_bus = event_bus
        self.store = JsonStore(path, DEFAULT_ROUTINES)
        self._runs: dict[str, RoutineRun] = {}
        self._lock = threading.RLock()
        self._workers = concurrent.futures.ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="JarvisRoutine"
        )
        self._ensure_defaults()

    def _ensure_defaults(self) -> None:
        data = self.store.load()
        if not isinstance(data, dict) or not isinstance(data.get("routines"), list):
            self.store.save(DEFAULT_ROUTINES)

    def list(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.store.load().get("routines", []))

    def get(self, routine_id_or_alias: str) -> dict[str, Any] | None:
        needle = self._norm(routine_id_or_alias)
        for routine in self.list():
            candidates = [routine.get("id", ""), routine.get("name", ""), *(routine.get("aliases") or [])]
            if needle in {self._norm(x) for x in candidates}:
                return routine
        return None

    def save(self, routine: dict[str, Any]) -> dict[str, Any]:
        if not routine.get("id"):
            routine["id"] = self._slug(routine.get("name", "rutina"))
        routine.setdefault("name", routine["id"])
        routine.setdefault("aliases", [])
        routine.setdefault("steps", [])
        self.validate(routine)
        data = self.store.load()
        items = data.setdefault("routines", [])
        for index, existing in enumerate(items):
            if existing.get("id") == routine["id"]:
                items[index] = copy.deepcopy(routine)
                break
        else:
            items.append(copy.deepcopy(routine))
        self.store.save(data)
        self.event_bus.publish("routine.saved", {"routine": routine}, "routine_engine")
        return routine

    def delete(self, routine_id: str) -> bool:
        data = self.store.load()
        before = len(data.get("routines", []))
        data["routines"] = [r for r in data.get("routines", []) if r.get("id") != routine_id]
        self.store.save(data)
        deleted = len(data["routines"]) < before
        if deleted:
            self.event_bus.publish("routine.deleted", {"routine_id": routine_id}, "routine_engine")
        return deleted

    def validate(self, routine: dict[str, Any]) -> None:
        if not isinstance(routine.get("steps"), list):
            raise ValueError("La rutina necesita una lista de pasos.")
        for index, step in enumerate(routine["steps"], 1):
            if not isinstance(step, dict):
                raise ValueError(f"El paso {index} debe ser un objeto.")
            if not any(k in step for k in ("capability", "parallel", "wait", "if")):
                raise ValueError(f"El paso {index} no tiene capability, parallel, wait o if.")
            if "capability" in step and not isinstance(step.get("params", {}), dict):
                raise ValueError(f"Los parámetros del paso {index} deben ser un objeto.")

    def run(self, routine_id_or_alias: str, variables: dict[str, Any] | None = None, asynchronous: bool = False) -> ActionResult:
        routine = self.get(routine_id_or_alias)
        if not routine:
            return ActionResult.failure(
                f"No encontré la rutina '{routine_id_or_alias}'.", error="routine_not_found"
            )
        run = RoutineRun(run_id=str(uuid.uuid4())[:8], routine_id=routine["id"])
        with self._lock:
            self._runs[run.run_id] = run
        if asynchronous:
            self._workers.submit(self._execute, run, routine, variables or {})
            return ActionResult.success(
                f"Rutina '{routine['name']}' iniciada.", run_id=run.run_id, status="running"
            )
        return self._execute(run, routine, variables or {})

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            run = self._runs.get(run_id)
        if not run or run.status not in {"pending", "running"}:
            return False
        run.cancel_event.set()
        self.event_bus.publish("routine.cancel_requested", {"run_id": run_id}, "routine_engine")
        return True

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            run = self._runs.get(run_id)
        return run.public() if run else None

    def _execute(self, run: RoutineRun, routine: dict[str, Any], variables: dict[str, Any]) -> ActionResult:
        run.status = "running"
        context = {"variables": variables, "results": {}, "routine": routine}
        self.event_bus.publish(
            "routine.started", {"run_id": run.run_id, "routine": routine}, "routine_engine"
        )
        completed_with_rollbacks: list[dict[str, Any]] = []
        try:
            for index, step in enumerate(routine.get("steps", []), 1):
                if run.cancel_event.is_set():
                    run.status = "cancelled"
                    run.error = "cancelled"
                    break
                record = self._execute_step(step, context, run, index)
                run.steps.append(record)
                context["results"][str(index)] = record
                if record.get("ok") and step.get("rollback"):
                    completed_with_rollbacks.append(step)
                if not record.get("ok"):
                    if step.get("critical", True):
                        run.status = "failed"
                        run.error = record.get("message", "Paso crítico fallido")
                        self._rollback(completed_with_rollbacks, context, run)
                        break
                    run.warnings.append(record.get("message", "Paso no crítico fallido"))
            else:
                run.status = "completed_with_warnings" if run.warnings else "completed"
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            self._rollback(completed_with_rollbacks, context, run)
        run.finished_at = time.time()
        payload = run.public()
        self.event_bus.publish(f"routine.{run.status}", payload, "routine_engine")
        if run.status in {"completed", "completed_with_warnings"}:
            message = f"Rutina '{routine['name']}' completada."
            if run.warnings:
                message += f" Advertencias: {len(run.warnings)}."
            result = ActionResult.success(message, run=payload)
            result.warnings.extend(run.warnings)
            return result
        if run.status == "cancelled":
            return ActionResult.failure(f"Rutina '{routine['name']}' cancelada.", error="cancelled", run=payload)
        return ActionResult.failure(
            f"La rutina '{routine['name']}' falló: {run.error}", error=run.error, run=payload
        )

    def _execute_step(self, step: dict[str, Any], context: dict[str, Any], run: RoutineRun, index: int) -> dict[str, Any]:
        started = time.time()
        if "wait" in step:
            seconds = max(0.0, float(step.get("wait", 0)))
            run.cancel_event.wait(seconds)
            return {"index": index, "type": "wait", "ok": not run.cancel_event.is_set(), "seconds": seconds, "duration": time.time() - started}

        if "parallel" in step:
            children = list(step.get("parallel") or [])
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(8, len(children)))) as pool:
                futures = [pool.submit(self._execute_step, child, context, run, index) for child in children]
                records = [f.result() for f in futures]
            ok = all(r.get("ok") or not children[i].get("critical", True) for i, r in enumerate(records))
            return {"index": index, "type": "parallel", "ok": ok, "children": records, "duration": time.time() - started, "message": "Bloque paralelo completado." if ok else "Falló un paso crítico del bloque paralelo."}

        if "if" in step:
            condition = step.get("if") or {}
            passed, condition_record = self._evaluate_condition(condition, context)
            branch = step.get("then", []) if passed else step.get("else", [])
            records = [self._execute_step(child, context, run, index) for child in branch]
            ok = all(r.get("ok") for r in records) if records else True
            return {"index": index, "type": "condition", "ok": ok, "condition": condition_record, "branch": "then" if passed else "else", "children": records, "duration": time.time() - started}

        capability = str(step.get("capability", ""))
        params = self._resolve(copy.deepcopy(step.get("params") or {}), context)
        retries = max(0, int(step.get("retries", 0)))
        confirmed = bool(step.get("confirmed", False))
        result = None
        for attempt in range(retries + 1):
            if run.cancel_event.is_set():
                return {"index": index, "type": "capability", "capability": capability, "ok": False, "message": "Rutina cancelada.", "error": "cancelled", "attempt": attempt + 1}
            result = self.registry.execute(capability, params, confirmed=confirmed, timeout=step.get("timeout"))
            if result.ok:
                break
            if attempt < retries:
                time.sleep(float(step.get("retry_delay", 1.0)))
        assert result is not None
        delay = float(step.get("delay_after", 0) or 0)
        if delay > 0:
            run.cancel_event.wait(delay)
        return {
            "index": index,
            "type": "capability",
            "capability": capability,
            "params": params,
            "ok": result.ok,
            "message": result.message,
            "error": result.error,
            "data": result.data,
            "warnings": result.warnings,
            "duration": time.time() - started,
        }

    def _evaluate_condition(self, condition: dict[str, Any], context: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        capability = condition.get("capability")
        if capability:
            result = self.registry.execute(str(capability), self._resolve(condition.get("params", {}), context))
            actual = result.data.get(condition.get("field", "result"), result.ok)
            record = result.to_dict()
        else:
            actual = self._resolve(condition.get("value"), context)
            record = {"actual": actual}
        op_name = str(condition.get("operator", "truthy"))
        expected = self._resolve(condition.get("equals"), context)
        op = self.OPERATORS.get(op_name)
        if not op:
            raise ValueError(f"Operador de condición desconocido: {op_name}")
        try:
            passed = bool(op(actual, expected))
        except Exception:
            passed = False
        record.update({"operator": op_name, "expected": expected, "passed": passed})
        return passed, record

    def _rollback(self, steps: list[dict[str, Any]], context: dict[str, Any], run: RoutineRun) -> None:
        for step in reversed(steps):
            rollback = step.get("rollback")
            if not isinstance(rollback, dict):
                continue
            result = self.registry.execute(
                str(rollback.get("capability", "")),
                self._resolve(rollback.get("params", {}), context),
                confirmed=True,
            )
            run.steps.append({"type": "rollback", "capability": rollback.get("capability"), "ok": result.ok, "message": result.message})

    def _resolve(self, value: Any, context: dict[str, Any]) -> Any:
        if isinstance(value, dict):
            return {k: self._resolve(v, context) for k, v in value.items()}
        if isinstance(value, list):
            return [self._resolve(v, context) for v in value]
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            path = value[2:-1].split(".")
            current: Any = context
            for part in path:
                if not isinstance(current, dict):
                    return value
                current = current.get(part)
            return current
        return value

    def shutdown(self) -> None:
        """Stop accepting background routine work during application shutdown."""
        with self._lock:
            for run in self._runs.values():
                if run.status in {"pending", "running"}:
                    run.cancel_event.set()
        self._workers.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _norm(value: str) -> str:
        return " ".join(str(value or "").strip().lower().split())

    @staticmethod
    def _slug(value: str) -> str:
        raw = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value))
        return "_".join(part for part in raw.split("_") if part) or "rutina"
