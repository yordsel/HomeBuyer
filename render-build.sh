#!/usr/bin/env bash
set -euo pipefail

echo "=== Installing Python dependencies ==="
pip install --upgrade pip
pip install .

echo "=== Building frontend ==="
cd ui
npm ci
npm run build
cd ..

echo "=== Build complete ==="
