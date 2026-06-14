#!/usr/bin/env bash
# ============================================================================
# Bridge Skill v0.3 — UAV Survey → Constructable Bridge Engineering Drawings
# ============================================================================
# Usage:
#   ./run_bridge_skill.sh <pointcloud.las> [output_dir]
#   ./run_bridge_skill.sh --generate-synthetic [--span 30] [--width 8]
#   ./run_bridge_skill.sh --generate-synthetic --bridge-type arch
#
# Pipeline steps:
#   1. (Optional) Generate synthetic / realistic point cloud
#   2. Point cloud processing → bridge_params.json (enhanced with terrain, veg filter)
#   3. Engineering design → detailed_design.json (structural calculations, rebar, BOM)
#   4. FreeCAD parametric 3D modeling → bridge.FCStd, .step, .stl
#   5. Professional drawing generation → GA, Superstructure, Substructure, BOM sheets
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
╔══════════════════════════════════════════════════════════════════╗
║  Bridge Skill v0.3 — UAV Survey → Constructable Drawings        ║
╠══════════════════════════════════════════════════════════════════╣
║  Pipeline:                                                      ║
║    Point Cloud → Params → Engineering Design → 3D Model → Drawings
╚══════════════════════════════════════════════════════════════════╝

Usage:
  $0 <pointcloud.las> [output_dir]
  $0 --generate-synthetic [options]

Options:
  --generate-synthetic     Generate synthetic bridge point cloud
  --realistic              Generate realistic UAV-simulated point cloud
  --span N                 Bridge span in meters (default: 30)
  --width N                Deck width in meters (default: 8)
  --pier-height N          Pier height in meters (default: 5)
  --bridge-type TYPE       beam | arch | auto (default: auto)
  --design-code CODE       AASHTO | CHN (default: AASHTO)
  --live-load MODEL        HL93 | CL1 (default: HL93)
  --output-dir DIR         Output directory (default: ./bridge_output)
  --analyze                Run structural analysis
  --no-class-filter        Disable classification-based veg filtering
  --help                   Show this help

Output:
  bridge_output/
  ├── bridge.las                  Point cloud (if synthetic)
  ├── bridge_params.json          Extracted structural parameters
  ├── detailed_design.json        Engineering design with rebar, BOM
  ├── bridge.FCStd                FreeCAD 3D model
  ├── bridge.step                 STEP exchange format
  ├── bridge.stl                  STL mesh
  └── drawings/
      ├── GA_drawing.svg          General Arrangement
      ├── Superstructure_drawing.svg  Girder & deck details
      ├── Substructure_drawing.svg    Pier & abutment details
      └── BOM_table.svg           Bill of Materials

Examples:
  # Quick demo with synthetic data:
  $0 --generate-synthetic

  # Realistic UAV simulation:
  $0 --generate-synthetic --realistic

  # Arch bridge:
  $0 --generate-synthetic --bridge-type arch --span 40

  # Process real UAV point cloud:
  $0 survey_data.las ./my_bridge

  # With structural analysis:
  $0 --generate-synthetic --analyze

  # Chinese design code:
  $0 --generate-synthetic --design-code CHN --live-load CL1
EOF
    exit 0
}

# ── Argument parsing ──────────────────────────────────────────────────
GENERATE_SYNTHETIC=false
REALISTIC=false
SPAN=30
WIDTH=8
PIER_HEIGHT=5
BRIDGE_TYPE="auto"
DESIGN_CODE="AASHTO"
LIVE_LOAD="HL93"
OUTPUT_DIR=""
DO_ANALYZE=false
INPUT_LAS=""
NO_CLASS_FILTER=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --generate-synthetic) GENERATE_SYNTHETIC=true; shift ;;
        --realistic) REALISTIC=true; shift ;;
        --span) SPAN="$2"; shift 2 ;;
        --width) WIDTH="$2"; shift 2 ;;
        --pier-height) PIER_HEIGHT="$2"; shift 2 ;;
        --bridge-type) BRIDGE_TYPE="$2"; shift 2 ;;
        --design-code) DESIGN_CODE="$2"; shift 2 ;;
        --live-load) LIVE_LOAD="$2"; shift 2 ;;
        --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
        --analyze) DO_ANALYZE=true; shift ;;
        --no-class-filter) NO_CLASS_FILTER="--no-class-filter"; shift ;;
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

# ── Validate ──────────────────────────────────────────────────────────
if ! command -v conda &>/dev/null; then
    err "conda not found. Please install Miniconda first."
fi

if ! conda env list | grep -q "$CONDA_ENV"; then
    err "Conda env '$CONDA_ENV' not found. Run: conda create -n bridge_skill python=3.10"
fi

# ── Setup output directory ────────────────────────────────────────────
if [[ -z "$OUTPUT_DIR" ]]; then
    if [[ -n "$INPUT_LAS" ]]; then
        BASENAME=$(basename "$INPUT_LAS" .las)
        OUTPUT_DIR="./${BASENAME}_output"
    else
        OUTPUT_DIR="./bridge_output"
    fi
fi
mkdir -p "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR/drawings"
log "Output directory: $OUTPUT_DIR"

# ═══════════════════════════════════════════════════════════════════════
# Step 1: Generate synthetic data (optional)
# ═══════════════════════════════════════════════════════════════════════
if $GENERATE_SYNTHETIC; then
    INPUT_LAS="$OUTPUT_DIR/bridge.las"

    if $REALISTIC; then
        log "Step 1/5: Generating realistic UAV-simulated point cloud..."
        INPUT_LAS="$OUTPUT_DIR/bridge_realistic.las"
        conda run -n "$CONDA_ENV" python "$SCRIPT_DIR/generate_realistic_data.py" \
            --span "$SPAN" --width "$WIDTH" --pier-height "$PIER_HEIGHT" \
            --output "$INPUT_LAS" --density medium
    else
        log "Step 1/5: Generating synthetic bridge point cloud..."
        conda run -n "$CONDA_ENV" python "$SCRIPT_DIR/generate_synthetic_data.py" \
            --span "$SPAN" --width "$WIDTH" --pier-height "$PIER_HEIGHT" \
            --output "$INPUT_LAS"
    fi
    ok "Point cloud: $INPUT_LAS"
else
    if [[ -z "$INPUT_LAS" ]]; then
        err "No input point cloud specified. Use --generate-synthetic or provide a .las file."
    fi
    log "Step 1/5: Using input point cloud: $INPUT_LAS"
fi

# ═══════════════════════════════════════════════════════════════════════
# Step 2: Point cloud processing → bridge_params.json
# ═══════════════════════════════════════════════════════════════════════
log "Step 2/5: Processing point cloud → bridge_params.json..."

PARAMS_JSON="$OUTPUT_DIR/bridge_params.json"
conda run -n "$CONDA_ENV" python "$SCRIPT_DIR/bridge_pipeline.py" \
    "$INPUT_LAS" --output "$PARAMS_JSON" --bridge-type "$BRIDGE_TYPE" \
    $NO_CLASS_FILTER
ok "Parameters extracted: $PARAMS_JSON"

# Display key results
conda run -n "$CONDA_ENV" python -c "
import json
with open('$PARAMS_JSON') as f:
    p = json.load(f)
d = p['dimensions']
t = p.get('terrain_profile', [])
ss = p.get('span_segments', [])
print(f'  Type: {p[\"bridge_type\"]} | Span: {d[\"span_length\"]}m | Width: {d[\"deck_width\"]}m')
print(f'  Clearance: {d[\"clearance_under_bridge\"]}m | Piers: {d[\"num_piers\"]} | Spans: {d.get(\"num_spans\", 1)}')
if t:
    print(f'  Terrain profile: {len(t)} samples, Z range: [{min(p[\"z\"] for p in t):.2f}, {max(p[\"z\"] for p in t):.2f}]m')
if ss:
    print(f'  Span segments: {ss}')
"

# ═══════════════════════════════════════════════════════════════════════
# Step 3: Engineering Design → detailed_design.json
# ═══════════════════════════════════════════════════════════════════════
log "Step 3/5: Engineering structural design → detailed_design.json..."

DESIGN_JSON="$OUTPUT_DIR/detailed_design.json"
conda run -n "$CONDA_ENV" python "$SCRIPT_DIR/bridge_designer.py" \
    "$PARAMS_JSON" --output "$DESIGN_JSON" \
    --design-code "$DESIGN_CODE" --live-load "$LIVE_LOAD"
ok "Engineering design: $DESIGN_JSON"

# Display design summary
conda run -n "$CONDA_ENV" python -c "
import json
with open('$DESIGN_JSON') as f:
    d = json.load(f)
sup = d.get('superstructure', {})
qty = d.get('quantities', {})
ana = d.get('analysis', {})
print(f'  Design code: {d.get(\"design_code\", \"N/A\")}')
print(f'  Girder: {sup.get(\"girder_type\", \"N/A\")} | {sup.get(\"num_girders\", \"?\")} girders @ {sup.get(\"girder_spacing\", \"?\")}m')
print(f'  Deck: {sup.get(\"deck_thickness\", 0)*1000:.0f}mm + {sup.get(\"wearing_surface\", 0)*1000:.0f}mm asphalt')
reinf = d.get('reinforcement', {}).get('girder', {})
if reinf:
    print(f'  Main rebar: {reinf.get(\"main_bars\", \"N/A\")} | Stirrups: {reinf.get(\"stirrups\", \"N/A\")}')
print(f'  Total concrete: {qty.get(\"total_concrete_m3\", \"N/A\")} m³ | Rebar: {qty.get(\"total_rebar_kg\", 0)/1000:.1f} tonnes')
if 'deflection_ok' in ana:
    print(f'  Deflection: {ana.get(\"max_deflection_mm\", \"?\")}mm (OK: {ana.get(\"deflection_ok\", \"?\")})')
"

# ═══════════════════════════════════════════════════════════════════════
# Step 4: FreeCAD 3D Modeling
# ═══════════════════════════════════════════════════════════════════════
log "Step 4/5: Building FreeCAD 3D model..."

FREECAD_CONFIG="$OUTPUT_DIR/freecad_config.json"
cat > "$FREECAD_CONFIG" <<JSONEOF
{
  "params": "$DESIGN_JSON",
  "output": "$OUTPUT_DIR/bridge.FCStd",
  "drawing": "$OUTPUT_DIR/drawings/FreeCAD_drawing.svg",
  "analyze": $DO_ANALYZE
}
JSONEOF

# Copy freecad_bridge.py to output dir and run
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
else
    log "FreeCAD model generation skipped or incomplete (headless limitation)"
    log "Run manually: freecad $OUTPUT_DIR/bridge.FCStd"
fi

# ═══════════════════════════════════════════════════════════════════════
# Step 5: Professional Drawing Generation
# ═══════════════════════════════════════════════════════════════════════
log "Step 5/5: Generating professional construction drawings..."

DRAWINGS_DIR="$OUTPUT_DIR/drawings"
conda run -n "$CONDA_ENV" python "$SCRIPT_DIR/bridge_drawing.py" \
    "$DESIGN_JSON" --output-dir "$DRAWINGS_DIR" --all

# Count generated files
DRAWING_COUNT=$(ls -1 "$DRAWINGS_DIR"/*.svg 2>/dev/null | wc -l)
if [[ $DRAWING_COUNT -gt 0 ]]; then
    ok "$DRAWING_COUNT drawing sheets generated:"
    for f in "$DRAWINGS_DIR"/*.svg; do
        echo "       $(basename "$f")"
    done
else
    err "Drawing generation failed!"
fi

# ═══════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════

echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║        Bridge Skill v0.3 — Pipeline Complete                    ║"
echo "╠══════════════════════════════════════════════════════════════════╣"
printf "║  %-60s ║\n" "Output: $OUTPUT_DIR"
printf "║  %-60s ║\n" "  📊 bridge_params.json      — Extracted parameters"
printf "║  %-60s ║\n" "  🔧 detailed_design.json    — Engineering design + BOM"
printf "║  %-60s ║\n" "  🏗️  bridge.FCStd            — FreeCAD 3D model"
printf "║  %-60s ║\n" "  📐 bridge.step / .stl      — CAD exchange formats"
printf "║  %-60s ║\n" "  📄 drawings/               — Professional drawings:"
printf "║  %-60s ║\n" "      GA_drawing.svg          — General Arrangement"
printf "║  %-60s ║\n" "      Superstructure_drawing  — Girder & Deck details"
printf "║  %-60s ║\n" "      Substructure_drawing    — Pier & Abutment details"
printf "║  %-60s ║\n" "      BOM_table.svg           — Bill of Materials"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""
echo "To view drawings: xdg-open $DRAWINGS_DIR/GA_drawing.svg"
echo "To view 3D model: freecad $OUTPUT_DIR/bridge.FCStd"
echo "To view all outputs: ls -lh $OUTPUT_DIR/"
