from .models import ActionResult, Capability, RiskLevel

__all__ = ["PRPPlatform", "ActionResult", "Capability", "RiskLevel"]


def __getattr__(name):
    if name == "PRPPlatform":
        from .controller import PRPPlatform
        return PRPPlatform
    raise AttributeError(name)
