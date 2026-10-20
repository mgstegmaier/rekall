#!/usr/bin/env python3
"""Lookup order for rekall_config.get_secret: environment, then keyring, then .env. No real Keychain.
Run directly: python3 scripts/test_secrets.py"""
import os
import sys
import tempfile
import types
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
(TMP / "rekall.toml").write_text(f'[user]\nname = "T"\ntimezone = "UTC"\n[vault]\npath = "{TMP}/v"\n[data]\npath = "{TMP}/d"\n')
os.environ["REKALL_CONFIG"] = str(TMP / "rekall.toml")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

store = {}
fake = types.ModuleType("keyring")
fake.get_password = lambda svc, name: store.get((svc, name))
fake.set_password = lambda svc, name, v: store.__setitem__((svc, name), v)
sys.modules["keyring"] = fake

import rekall_config as rc  # noqa: E402

rc.ENV_FILE = TMP / ".env"
rc.ENV_FILE.write_text("K=from-file\nBLANK=\n")
os.environ.pop("K", None)
assert rc.get_secret("K") == "from-file"
rc.set_secret("K", "from-keyring")
assert store[("rekall", "K")] == "from-keyring" and rc.get_secret("K") == "from-keyring"
os.environ["K"] = "from-env"
assert rc.get_secret("K") == "from-env"
os.environ.pop("K")

assert rc.find_secret("BLANK") is None
try:
    rc.get_secret("BLANK")
    raise AssertionError("missing key must raise")
except KeyError as e:
    assert "BLANK" in str(e) and "keyring" in str(e) and ".env" in str(e)

def boom(*a):
    raise RuntimeError("backend down")
fake.get_password = boom
assert rc.get_secret("K") == "from-file", "a broken keyring falls through to .env"
sys.modules["keyring"] = None  # import raises ImportError
assert rc.get_secret("K") == "from-file", "a missing package falls through to .env"
print("ok")
