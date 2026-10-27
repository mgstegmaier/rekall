"""pytest from the repo root. rekall_config sys.exits without a rekall.toml, so when
REKALL_CONFIG is unset this writes a scratch one (rekall.example.toml with the vault, data and
state under a temp dir, vault-template/ copied in) before any test imports rekall_config.
A set REKALL_CONFIG is left alone, so `REKALL_CONFIG=rekall.toml pytest` runs against your install."""

import atexit
import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

if not os.environ.get("REKALL_CONFIG"):
    tmp = Path(tempfile.mkdtemp(prefix="rekall-pytest-"))
    atexit.register(shutil.rmtree, tmp, ignore_errors=True)
    shutil.copytree(ROOT / "vault-template", tmp / "vault")
    toml = (ROOT / "rekall.example.toml").read_text(encoding="utf-8")
    toml = toml.replace('path = "~/rekall/vault"', f'path = "{(tmp / "vault").as_posix()}"')
    toml = toml.replace('path = "~/rekall/data"',
                        f'path = "{(tmp / "data").as_posix()}"\nstate = "{(tmp / "state").as_posix()}"')
    assert str(tmp) in toml, "rekall.example.toml paths changed; update conftest.py"
    (tmp / "rekall.toml").write_text(toml, encoding="utf-8")
    os.environ["REKALL_CONFIG"] = str(tmp / "rekall.toml")
