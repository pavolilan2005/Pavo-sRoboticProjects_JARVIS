from .models import ActionResult, Capability, RiskLevel

__all__ = ["MarkPlatform", "ActionResult", "Capability", "RiskLevel"]


def __getattr__(name):
    if name == "MarkPlatform":
        from .controller import MarkPlatform
        return MarkPlatform
    raise AttributeError(name)
