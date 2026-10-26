#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
.venv/bin/python -m pip check
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m pytest -q --junitxml=generated/verification.xml
