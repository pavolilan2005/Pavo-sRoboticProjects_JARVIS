import asyncio, json, tempfile
from pathlib import Path
from prp.core.capabilities import CapabilityRegistry
from prp.core.config import ConfigStore
from prp.core.events import EventBus
from prp.core.models import ActionResult, Capability
from prp.core.routines import RoutineEngine

def test_no_duplicate_capabilities():
    registry=CapabilityRegistry(); registry.register(Capability("x","x",lambda: ActionResult.success("ok")))
    try: registry.register(Capability("x","x",lambda: None)); assert False
    except ValueError: pass

def test_routine():
    with tempfile.TemporaryDirectory() as d:
        root=Path(d); (root/"config").mkdir(); (root/"config"/"routines.json").write_text(json.dumps({"routines":[{"id":"a","steps":[{"capability":"ok","args":{}}]}]}))
        reg=CapabilityRegistry(); reg.register(Capability("ok","",lambda: ActionResult.success("ok")))
        result=asyncio.run(RoutineEngine(ConfigStore(root),reg,EventBus()).run("a")); assert result.ok
