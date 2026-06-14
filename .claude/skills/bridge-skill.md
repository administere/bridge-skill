# Bridge Skill

UAV drone survey to bridge construction drawing automated pipeline.

## Trigger

When the user asks to:
- Process UAV/drone survey data for bridge analysis
- Generate bridge 3D models or construction drawings from point clouds
- Create parametric bridge models from survey data
- Convert point cloud (.las/.laz) to bridge structural parameters
- "process this bridge point cloud", "generate bridge drawings", "bridge from survey"

## Usage

### Full pipeline (recommended)

```bash
# Demo with synthetic data:
~/bridge_skill/run_bridge_skill.sh --generate-synthetic --output-dir <output_dir>

# Real point cloud:
~/bridge_skill/run_bridge_skill.sh <pointcloud.las> <output_dir>

# With options:
~/bridge_skill/run_bridge_skill.sh <pointcloud.las> <output_dir> --bridge-type arch --analyze
```

### Individual steps

**Generate synthetic test data:**
```bash
conda run -n bridge_skill python ~/bridge_skill/generate_synthetic_data.py \
    --span 30 --width 8 --pier-height 5 --output bridge.las
```

**Process point cloud to extract parameters:**
```bash
conda run -n bridge_skill python ~/bridge_skill/bridge_pipeline.py \
    <input.las> --output bridge_params.json --bridge-type beam
```

**Generate FreeCAD 3D model and drawings:**
The freecad_bridge.py script must be run via freecadcmd (not regular Python).
Create a freecad_config.json with params/output/drawing paths, then:
```bash
cd <output_dir> && /home/wayne/miniconda3/envs/bridge_skill/bin/freecadcmd -c <<'EOF'
import sys, json
sys.path.insert(0, ".")
with open("freecad_config.json") as f: config = json.load(f)
exec(open("freecad_bridge.py").read())
EOF
```

Note: freecad_bridge.py must be copied to the output directory first (or run from ~/bridge_skill/).

## Environment

- **Conda env**: `bridge_skill` (Python 3.10)
- **Key packages**: open3d, laspy, numpy, scipy, freecad=0.21.2
- **FreeCAD**: `/home/wayne/miniconda3/envs/bridge_skill/bin/freecadcmd`

## Output Files

| File | Description |
|------|-------------|
| `bridge.las` | Point cloud (if synthetic) |
| `bridge_params.json` | Extracted bridge parameters |
| `bridge.FCStd` | FreeCAD 3D model |
| `bridge.step` | STEP exchange format |
| `bridge.stl` | 3D mesh for printing/viewing |
| `bridge_drawing.svg` | 3-view dimensioned drawing |

## bridge_params.json Structure

Key fields for downstream use:
- `dimensions.span_length` — bridge span (m)
- `dimensions.deck_width` — deck width (m)
- `dimensions.clearance_under_bridge` — clearance height (m)
- `dimensions.pier_spacings` — array of pier-to-pier distances (m)
- `centerline.start/end` — 3D bridge axis endpoints
- `pier_positions[]` — array of {x, y, z, height} for each pier
- `abutment_positions[]` — array of {x, y, z, height} for each abutment

## Important Notes

- FreeCAD scripts MUST run via `freecadcmd`, not regular Python
- The point cloud pipeline expects LAS 1.2+ format with X, Y, Z, classification fields
- For real UAV data, use OpenDroneMap (Docker: `opendronemap/odm`) to generate the point cloud first
- The synthetic generator creates a beam bridge by default; modify `--span`/`--width` for different dimensions
