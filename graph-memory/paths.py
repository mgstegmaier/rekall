"""Where graph-memory keeps its data.

The code here is version controlled; its data is not. The index and the
distillates carry meeting and company content, and the model is 64MB of
regenerable download, so all of it sits beside the vault instead of in the
repo. The location comes from rekall.toml ([data].path).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rekall_config import DATA, SESSIONS, WIKI  # noqa: E402,F401

DB = DATA / "rag.db"
MODEL_DIR = DATA / "model"
DISTILLED_DIR = DATA / "distilled"
DIGEST_PENDING = DATA / "digest" / "pending"
DIGEST_LOG = DATA / "digest" / "log"
