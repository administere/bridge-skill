# CAD Project — Bridge Skill

## Bridge Skill: UAV Survey → Construction Drawing Pipeline

When the user asks to process drone/UAV survey data for bridges, generate bridge models,
or create bridge construction drawings from point clouds, use the bridge skill pipeline.

### Quick Start

```bash
# Full demo with synthetic data:
~/bridge_skill/run_bridge_skill.sh --generate-synthetic

# Process real point cloud:
~/bridge_skill/run_bridge_skill.sh <pointcloud.las> <output_dir>

# With structural analysis:
~/bridge_skill/run_bridge_skill.sh --generate-synthetic --analyze
```

### Pipeline Steps (can run individually)

1. **Generate synthetic data**: `conda run -n bridge_skill python ~/bridge_skill/generate_synthetic_data.py`
2. **Process point cloud**: `conda run -n bridge_skill python ~/bridge_skill/bridge_pipeline.py <input.las> -o bridge_params.json`
3. **FreeCAD modeling**: Uses `freecadcmd` from bridge_skill conda env, reads `bridge_params.json`
4. **Output**: `.FCStd` (3D model), `.step`, `.stl`, `.svg` (3-view drawing)

### Key Files

| File | Purpose |
|------|---------|
| `~/bridge_skill/run_bridge_skill.sh` | Main entry point |
| `~/bridge_skill/generate_synthetic_data.py` | Synthetic bridge point cloud |
| `~/bridge_skill/bridge_pipeline.py` | Point cloud → bridge_params.json |
| `~/bridge_skill/freecad_bridge.py` | bridge_params.json → 3D model + drawings |
| `~/bridge_skill/README.md` | Full documentation |

### Environment

- Conda env: `bridge_skill` (Python 3.10, open3d, laspy, freecad=0.21.2)
- FreeCAD headless: `/home/wayne/miniconda3/envs/bridge_skill/bin/freecadcmd`
