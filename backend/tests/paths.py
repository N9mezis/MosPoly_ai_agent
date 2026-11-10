from __future__ import annotations

import os
from pathlib import Path

# В контейнере репозиторий смонтирован в /repo; локально — на уровень выше backend/.
REPO_ROOT = Path(os.environ.get("REPO_ROOT", Path(__file__).resolve().parents[2]))
TMP_DIR = Path(__file__).resolve().parent / ".tmp"
TMP_DIR.mkdir(exist_ok=True)
