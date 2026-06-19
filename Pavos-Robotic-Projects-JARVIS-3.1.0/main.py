from __future__ import annotations

import sys
from pathlib import Path

from prp.app import PRPApplication


def main() -> int:
    base_dir = Path(__file__).resolve().parent
    app = PRPApplication(base_dir)
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
