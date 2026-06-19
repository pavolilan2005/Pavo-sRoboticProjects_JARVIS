"""JARVIS process-wide startup compatibility fixes.

Python imports this module automatically during normal startup because it lives
beside main.py. Keeping this tiny also protects standalone action scripts.
"""
try:
    from core.subprocess_compat import install_subprocess_text_compat
    install_subprocess_text_compat()
except Exception:
    # Startup must never fail because an optional compatibility patch failed.
    pass
