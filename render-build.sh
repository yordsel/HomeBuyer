#!/usr/bin/env bash
set -euo pipefail

echo "=== Installing Python dependencies ==="
pip install --upgrade pip
pip install .

echo "=== Build complete ==="
