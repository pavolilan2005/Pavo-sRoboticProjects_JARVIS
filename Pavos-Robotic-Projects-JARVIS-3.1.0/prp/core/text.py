from __future__ import annotations

import re
import unicodedata


def normalize_voice_text(text: str) -> str:
    value = unicodedata.normalize("NFKD", (text or "").lower())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-z0-9ñ ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()
