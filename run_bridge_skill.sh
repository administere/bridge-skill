#!/usr/bin/env bash
# ============================================================================
# Bridge Skill — UAV Survey → Bridge Construction Drawing Pipeline
# ============================================================================
# Usage:
#   ./run_bridge_skill.sh <pointcloud.las> [output_dir] [--type beam|arch]
#   ./run_bridge_skill.sh --generate-synthetic [--span 30] [--width 8]
#
# Pipeline steps:
#   1. (Optional) Generate synthetic point cloud
#   2. Process point cloud → bridge_params.json
#   3. FreeCAD parametric modeling → bridge.FCStd, bridge_drawing.svg
#   4. STEP + STL exports
#
# Requires: conda environment 'bridge_skill' with open3d, laspy, freecad
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONDA_ENV="bridge_skill"
FREECAD_CMD="$HOME/miniconda3/envs/${CONDA_ENV}/bin/freecadcmd"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[bridge-skill]${NC} $*"; }
ok()   { echo -e "${GREEN}[✓]${NC} $*"; }
err()  { echo -e "${RED}[✗]${NC} $*"; exit 1; }

usage() {
    cat <<EOF
╔══════════════════════════════════════════════════════════════╗
║     Bridge Skill — UAV Survey → Construction Drawing        ║
╚══════════════════════════════════════════════════════════════╝

Usage:
  $0 <pointcloud.las> [output_dir]
  $0 --generate-synthetic [--span 30] [--width 8]

Options:
  --generate-synthetic   Generate synthetic bridge point cloud
  --span N               Bridge span in meters (default: 30)
  --width N              Deck width in meters (default: 8)
  --pier-height N        Pier height in meters (default: 5)
  --bridge-type TYPE     beam | arch | auto (default: auto)
  --output-dir DIR       Output directory (default: ./bridge_output)
  --analyze              Run structural analysis placeholder
  --help                 Show this help

Output:
  bridge_output/
  ├── bridge.las                Point cloud (if synthetic)
  ├── bridge_params.json        Extracted parameters
  ├── bridge.FCStd              FreeCAD 3D model
  ├── bridge.step               STEP exchange format
  ├── bridge.stl                STL mesh
  └── bridge_drawing.svg        Dimensioned 3-view drawing

Examples:
  # Process real UAV point cloud:
  $0 survey_data.las ./my_bridge

  # Quick demo with synthetic data:
  $0 --generate-synthetic

  # Generate + analyze:
  $0 --generate-synthetic --analyze
EOF
    exit 0
}

# ── Argument parsing ──────────────────────────────────────────────
GENERATE_SYNTHETIC=false
SPAN=30
WIDTH=8
PIER_HEIGHT=5
BRIDGE_TYPE="auto"
OUTPUT_DIR=""
DO_ANALYZE=false
INPUT_LAS=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --generate-synthetic) GENERATE_SYNTHETIC=true; shift ;;
        --span) SPAN="$2"; shift 2 ;;
        --width) WIDTH="$2"; shift 2 ;;
        --pier-height) PIER_HEIGHT="$2"; shift 2 ;;
        --bridge-type) BRIDGE_TYPE="$2"; shift 2 ;;
        --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
        --analyze) DO_ANALYZE=true; shift ;;
        --help|-h) usage ;;
        -*)
            echo "Unknown option: $1"
            usage
            ;;
        *)
            INPUT_LAS="$1"
            shift
            ;;
    esac
done

# ── Validate ──────────────────────────────────────────────────────
if ! command -v conda &>/dev/null; then
    err "conda not found. Please install Miniconda first."
fi

if ! conda env list | grep -q "$CONDA_ENV"; then
    err "Conda env '$CONDA_ENV' not found. Run: conda create -n bridge_skill python=3.10"
fi

# ── Setup output directory ────────────────────────────────────────
if [[ -z "$OUTPUT_DIR" ]]; then
    if [[ -n "$INPUT_LAS" ]]; then
        BASENAME=$(basename "$INPUT_LAS" .las)
        OUTPUT_DIR="./${BASENAME}_output"
    else
        OUTPUT_DIR="./bridge_output"
    fi
fi
mkdir -p "$OUTPUT_DIR"
log "Output directory: $OUTPUT_DIR"

# ── Step 1: Generate synthetic data (optional) ────────────────────
if $GENERATE_SYNTHETIC; then
    log "Step 1/4: Generating synthetic bridge point cloud..."
    INPUT_LAS="$OUTPUT_DIR/bridge.las"
    conda run -n "$CONDA_ENV" python "$SCRIPT_DIR/generate_synthetic_data.py" \
        --span "$SPAN" --width "$WIDTH" --pier-height "$PIER_HEIGHT" \
        --output "$INPUT_LAS"
    ok "Synthetic point cloud: $INPUT_LAS"
else
    if [[ -z "$INPUT_LAS" ]]; then
        err "No input point cloud specified. Use --generate-synthetic or provide a .las file."
    fi
    log "Step 1/4: Using input: $INPUT_LAS"
fi

# ── Step 2: Point cloud processing ────────────────────────────────
log "Step 2/4: Processing point cloud → bridge_params.json..."
PARAMS_JSON="$OUTPUT_DIR/bridge_params.json"
conda run -n "$CONDA_ENV" python "$SCRIPT_DIR/bridge_pipeline.py" \
    "$INPUT_LAS" --output "$PARAMS_JSON" --bridge-type "$BRIDGE_TYPE"
ok "Parameters extracted: $PARAMS_JSON"

# Display key results
conda run -n "$CONDA_ENV" python -c "
import json
with open('$PARAMS_JSON') as f:
    p = json.load(f)
d = p['dimensions']
print(f'  Span: {d[\"span_length\"]}m | Width: {d[\"deck_width\"]}m | '
      f'Clearance: {d[\"clearance_under_bridge\"]}m | Piers: {d[\"num_piers\"]}')
"

# ── Step 3: FreeCAD parametric modeling ───────────────────────────
log "Step 3/4: Building FreeCAD 3D model..."
FREECAD_CONFIG="$OUTPUT_DIR/freecad_config.json"
cat > "$FREECAD_CONFIG" <<JSONEOF
{
  "params": "$PARAMS_JSON",
  "output": "$OUTPUT_DIR/bridge.FCStd",
  "drawing": "$OUTPUT_DIR/bridge_drawing.svg",
  "analyze": $DO_ANALYZE
}
JSONEOF

# Copy freecad_bridge.py to output dir for proper relative paths
cp "$SCRIPT_DIR/freecad_bridge.py" "$OUTPUT_DIR/freecad_bridge.py"
(cd "$OUTPUT_DIR" && echo '
import sys
sys.path.insert(0, ".")
import json
from pathlib import Path

with open("freecad_config.json") as f:
    config = json.load(f)

exec(open("freecad_bridge.py").read())
' | "$FREECAD_CMD" -c 2>&1) | grep -E '^\[' || true

if [[ -f "$OUTPUT_DIR/bridge.FCStd" ]]; then
    ok "FreeCAD model: $OUTPUT_DIR/bridge.FCStd"
    ok "STEP export: $OUTPUT_DIR/bridge.step"
    ok "STL mesh: $OUTPUT_DIR/bridge.stl"
    ok "Drawing: $OUTPUT_DIR/bridge_drawing.svg"
else
    err "FreeCAD model generation failed!"
fi

# ── Step 4: Summary ───────────────────────────────────────────────
log "Step 4/4: Pipeline complete!"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              Bridge Skill — Pipeline Complete               ║"
echo "╠══════════════════════════════════════════════════════════════╣"
printf "║  %-56s ║\n" "Output: $OUTPUT_DIR"
printf "║  %-56s ║\n" "  bridge_params.json  — Extracted parameters"
printf "║  %-56s ║\n" "  bridge.FCStd        — FreeCAD 3D model"
printf "║  %-56s ║\n" "  bridge.step         — STEP exchange"
printf "║  %-56s ║\n" "  bridge.stl          — 3D mesh"
printf "║  %-56s ║\n" "  bridge_drawing.svg  — 3-view drawing"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "To view the 3D model: freecad $OUTPUT_DIR/bridge.FCStd"
echo "To view the drawing:  xdg-open $OUTPUT_DIR/bridge_drawing.svg"
