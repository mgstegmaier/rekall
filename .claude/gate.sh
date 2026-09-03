#!/usr/bin/env bash
# Deterministic gate — enforced by the Stop hook (verification-gate.py) and /code-check.
# Keep under 2 minutes. Plan: familiar/docs/plans/2026-09-01-siloed-verification-hook-enforcement.md
set -e
cd "$(dirname "$0")/.."
python3 -m compileall -q -x "\.venv|node_modules" graph-memory scripts
