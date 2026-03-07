#!/usr/bin/env bash
# Download AiZynthFinder pre-trained models and stock files.
# Run this once before starting the worker — or bake into a Docker build step.
#
# Downloads to ./data/ (mounted into the container at /app/data/):
#   data/models/uspto_model.onnx       — expansion policy network
#   data/models/uspto_templates.hdf5   — reaction template library
#   data/models/filter_model.onnx      — feasibility filter network
#   data/stocks/zinc_stock.hdf5        — ZINC building blocks stock file
#
# Usage:
#   ./scripts/download_models.sh               # downloads to ./data/
#   ./scripts/download_models.sh /custom/path  # downloads to /custom/path/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DOWNLOAD_DIR="${1:-$REPO_ROOT/data}"

MODEL_DIR="$DOWNLOAD_DIR/models"
STOCK_DIR="$DOWNLOAD_DIR/stocks"

mkdir -p "$MODEL_DIR" "$STOCK_DIR"

echo "==> Downloading AiZynthFinder public models to: $DOWNLOAD_DIR"

# AiZynthFinder provides a built-in download tool that fetches the
# official pre-trained USPTO models and ZINC stock from its release assets.
python -m aizynthfinder.tools.download_public_data "$DOWNLOAD_DIR"

# Move only the zinc stock file into stocks/ subdirectory.
# All model files stay flat in $DOWNLOAD_DIR — matching config/aizynthfinder.yml paths.
echo "==> Organising downloaded files..."

for f in zinc_stock.hdf5; do
    if [[ -f "$DOWNLOAD_DIR/$f" ]]; then
        mv "$DOWNLOAD_DIR/$f" "$STOCK_DIR/$f"
        echo "    stocks/$f"
    fi
done

echo ""
echo "==> Done. Verify files:"
echo "    models/  : $(ls "$MODEL_DIR" | tr '\n' ' ')"
echo "    stocks/  : $(ls "$STOCK_DIR" | tr '\n' ' ')"
echo ""
echo "==> Start the worker: docker compose up worker"
