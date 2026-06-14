#!/usr/bin/env python3
"""
Parametric Bridge Model Generator
Reads bridge_params.json and creates a 3D FreeCAD model with:
- Deck slab
- Piers
- Abutments
- Road surface layer
- TechDraw 3-view output

Usage:
    freecadcmd freecad_bridge.py --params bridge_params.json --output bridge.FCStd
"""

import sys
import json
import argparse
from pathlib import Path

# FreeCAD imports (available when run via freecadcmd)
FREECAD = None
try:
    import FreeCAD
    import Part
    import Mesh
    import TechDraw
    import Draft
    import Sketcher
    FREECAD = True
except ImportError:
    FREECAD = False


def parse_args():
    # Arguments are passed via a small JSON config file (freecad_config.json)
    # or via command-line with --pass (which FreeCAD might mishandle)
    # Default: look for freecad_config.json, then fallback to defaults
    config_path = Path("freecad_config.json")
    config = {}
    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)

    parser = argparse.ArgumentParser(description="Generate parametric bridge model in FreeCAD")
    parser.add_argument("--params", "-p", default=config.get("params", "bridge_params.json"),
                        help="Path to bridge_params.json")
    parser.add_argument("--output", "-o", default=config.get("output", "bridge.FCStd"),
                        help="Output FreeCAD file path")
    parser.add_argument("--drawing", "-d", default=config.get("drawing", None),
                        help="Output drawing SVG path (optional)")
    parser.add_argument("--analyze", action="store_true",
                        default=config.get("analyze", False),
                        help="Run simple structural analysis (placeholder)")

    # Try to parse; if running under freecadcmd with --pass, args may be mangled
    try:
        return parser.parse_args()
    except SystemExit:
        # Fallback to config-only mode
        return argparse.Namespace(
            params=config.get("params", "bridge_params.json"),
            output=config.get("output", "bridge.FCStd"),
            drawing=config.get("drawing", None),
            analyze=config.get("analyze", False),
        )


def load_params(params_path):
    """Load bridge parameters from JSON."""
    with open(params_path, 'r') as f:
        return json.load(f)


def create_bridge_model(params):
    """Create the full bridge 3D model in FreeCAD.

    Returns:
        doc: FreeCAD document
        objects: dict of created objects {'deck': ..., 'piers': [...], 'abutments': [...]}
    """
    doc = FreeCAD.newDocument("Bridge")
    objects = {'deck': None, 'piers': [], 'abutments': [], 'road': None}

    dims = params['dimensions']
    centerline = params['centerline']
    piers_data = params.get('pier_positions', [])
    abutments_data = params.get('abutment_positions', [])

    # Key dimensions
    span = dims['span_length']
    width = dims['deck_width']
    deck_elev = dims['deck_elevation']
    ground_elev = dims.get('ground_elevation', 0.0)
    deck_thickness = 0.5  # meters

    # Get bridge axis direction from centerline
    if centerline:
        axis_dir = centerline['axis_direction']
        perp_dir = centerline['perpendicular_direction']
        center = centerline['center']
    else:
        axis_dir = [1, 0]
        perp_dir = [0, 1]
        center = [0, 0, deck_elev]

    print(f"Creating bridge model:")
    print(f"  Span: {span}m, Width: {width}m")
    print(f"  Deck elevation: {deck_elev}m, Ground: {ground_elev}m")
    print(f"  Piers: {len(piers_data)}, Abutments: {len(abutments_data)}")

    # --- 1. Deck Slab ---
    print("\n[1/5] Creating deck slab...")
    deck = doc.addObject('Part::Box', 'Deck')
    deck.Length = span * 1000  # FreeCAD uses mm internally
    deck.Width = width * 1000
    deck.Height = deck_thickness * 1000

    # Position deck centered at origin in X-Y, at deck elevation in Z
    deck_x = -span / 2 * 1000
    deck_y = -width / 2 * 1000
    deck_z = (deck_elev - deck_thickness / 2) * 1000
    deck.Placement.Base = FreeCAD.Vector(deck_x, deck_y, deck_z)
    objects['deck'] = deck
    print(f"  Deck: {span}x{width}x{deck_thickness}m at z={deck_elev}m")

    # --- 2. Piers ---
    print(f"\n[2/5] Creating {len(piers_data)} piers...")
    pier_length = 2.0  # Along bridge axis
    pier_width = 1.0   # Across bridge axis

    for i, p in enumerate(piers_data):
        pier_x = p['x'] * 1000
        pier_y = p['y'] * 1000
        pier_h = p['height'] * 1000
        pier_z_min = p['z_min'] * 1000

        pier = doc.addObject('Part::Box', f'Pier_{i+1}')
        pier.Length = pier_length * 1000
        pier.Width = pier_width * 1000
        pier.Height = pier_h

        pier.Placement.Base = FreeCAD.Vector(
            pier_x - pier_length * 1000 / 2,
            pier_y - pier_width * 1000 / 2,
            pier_z_min
        )
        objects['piers'].append(pier)
        print(f"  Pier {i+1}: ({p['x']:.1f}, {p['y']:.1f}), h={p['height']:.2f}m")

    # --- 3. Abutments ---
    print(f"\n[3/5] Creating {len(abutments_data)} abutments...")

    for i, a in enumerate(abutments_data):
        abut_x = a['x'] * 1000
        abut_y = a['y'] * 1000
        abut_h = a['height'] * 1000
        abut_z_min = a['z_min'] * 1000
        abut_w = a.get('width', 1.5) * 1000

        abutment = doc.addObject('Part::Box', f'Abutment_{i+1}')
        abutment.Length = 2.0 * 1000  # Along bridge axis
        abutment.Width = width * 1000  # Full bridge width
        abutment.Height = abut_h

        abutment.Placement.Base = FreeCAD.Vector(
            abut_x - 1000,
            abut_y - width * 1000 / 2,
            abut_z_min
        )
        objects['abutments'].append(abutment)
        print(f"  Abutment {i+1}: ({a['x']:.1f}, {a['y']:.1f}), h={a['height']:.2f}m, w={a.get('width', 1.5):.2f}m")

    # --- 4. Road Surface ---
    print(f"\n[4/5] Creating road surface...")
    road = doc.addObject('Part::Box', 'RoadSurface')
    road.Length = span * 1000
    road.Width = (width - 1.0) * 1000  # Slightly narrower (curbs)
    road.Height = 0.1 * 1000  # 10cm asphalt layer

    road_x = -span / 2 * 1000
    road_y = -(width - 1.0) / 2 * 1000
    road_z = (deck_elev + deck_thickness / 2) * 1000
    road.Placement.Base = FreeCAD.Vector(road_x, road_y, road_z)
    objects['road'] = road

    # Set road color via view object
    road_view = road.ViewObject
    if road_view:
        try:
            road_view.ShapeColor = (0.2, 0.2, 0.2, 1.0)  # Dark grey
        except:
            pass

    # --- 5. Fuse all parts into a single bridge shape ---
    print(f"\n[5/5] Fusing bridge components...")
    all_parts = [objects['deck']] + objects['piers'] + objects['abutments']
    if objects['road']:
        all_parts.append(objects['road'])

    # Create a compound of all parts
    compound = doc.addObject('Part::Compound', 'BridgeCompound')
    compound.Links = all_parts

    # Also create a boolean fusion for a cleaner model
    fusion = doc.addObject('Part::MultiFuse', 'Bridge')
    fusion.Shapes = all_parts

    doc.recompute()
    print("  Model built successfully!")

    return doc, objects


def create_techdraw_views(doc, params, output_svg=None):
    """Create TechDraw page with plan, front, and side views."""
    print(f"\n[6/6] Creating TechDraw views...")

    dims = params['dimensions']
    span = dims['span_length']
    width = dims['deck_width']

    try:
        # Get the bridge fusion object
        bridge = doc.getObject('Bridge')
        if not bridge:
            bridge = doc.getObject('BridgeCompound')

        if not bridge:
            print("  Warning: Bridge object not found for TechDraw")
            return None

        # Create a page using A3 template (landscape is good for bridges)
        template_path = FreeCAD.getResourceDir() + 'Mod/TechDraw/Templates/A3_LandscapeTD.svg'
        page = doc.addObject('TechDraw::DrawPage', 'BridgeDrawing')
        template = doc.addObject('TechDraw::DrawSVGTemplate', 'Template')
        template.Template = template_path
        page.Template = template

        # Set page scale based on bridge size
        scale = max(span, width) * 1000 / 350  # Fit in ~350mm view

        # Plan view (top)
        view_plan = doc.addObject('TechDraw::DrawViewPart', 'PlanView')
        view_plan.Source = [bridge]
        view_plan.Direction = FreeCAD.Vector(0, 0, 1)
        view_plan.XDirection = FreeCAD.Vector(1, 0, 0)
        view_plan.Scale = scale
        view_plan.X = 120
        view_plan.Y = 80
        page.addView(view_plan)

        # Front elevation (looking along Y axis)
        view_front = doc.addObject('TechDraw::DrawViewPart', 'FrontView')
        view_front.Source = [bridge]
        view_front.Direction = FreeCAD.Vector(0, -1, 0)
        view_front.XDirection = FreeCAD.Vector(1, 0, 0)
        view_front.Scale = scale
        view_front.X = 120
        view_front.Y = 180
        page.addView(view_front)

        # Side elevation (looking along X axis)
        view_side = doc.addObject('TechDraw::DrawViewPart', 'SideView')
        view_side.Source = [bridge]
        view_side.Direction = FreeCAD.Vector(-1, 0, 0)
        view_side.XDirection = FreeCAD.Vector(0, 1, 0)
        view_side.Scale = scale
        view_side.X = 120
        view_side.Y = 280
        page.addView(view_side)

        doc.recompute()
        print("  TechDraw views created: plan, front, side")

        # Export to SVG if requested
        if output_svg:
            try:
                TechDraw.writeDXF(page, output_svg.replace('.svg', '.dxf'))
                print(f"  Exported DXF: {output_svg.replace('.svg', '.dxf')}")
            except:
                pass

            # Alternative: export page to SVG
            try:
                page.exportSvg(output_svg)
                print(f"  Exported SVG: {output_svg}")
            except Exception as e:
                print(f"  SVG export failed: {e}")
                # Fallback: generate simple dimensioned SVG
                generate_simple_svg(params, output_svg)

        return page
    except Exception as e:
        print(f"  TechDraw error: {e}")
        if output_svg:
            generate_simple_svg(params, output_svg)
        return None


def generate_simple_svg(params, output_path):
    """Generate a simple dimensioned SVG drawing from parameters.
    Fallback when TechDraw is unavailable.
    """
    dims = params['dimensions']
    span = dims['span_length']
    width = dims['deck_width']
    clearance = dims.get('clearance_under_bridge', 0)
    num_piers = dims.get('num_piers', 0)
    pier_spacings = dims.get('pier_spacings', [])

    scale = 15  # pixels per meter
    margin = 80

    svg_width = span * scale + margin * 2
    svg_height = max(width, clearance) * scale + margin * 3 + 200

    pier_height = clearance
    deck_thickness = 0.5

    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{svg_width}" height="{svg_height}"
     viewBox="0 0 {svg_width} {svg_height}">
  <style>
    text {{ font-family: Arial, sans-serif; font-size: 12px; }}
    .title {{ font-size: 16px; font-weight: bold; }}
    .dim {{ font-size: 10px; fill: #d00; }}
    .label {{ font-size: 11px; fill: #333; }}
  </style>
  <rect width="{svg_width}" height="{svg_height}" fill="white"/>

  <!-- Title -->
  <text x="{svg_width/2}" y="25" text-anchor="middle" class="title">
    Bridge Construction Drawing
  </text>
  <text x="{svg_width/2}" y="45" text-anchor="middle" class="label">
    Span: {span}m × Width: {width}m | Clearance: {clearance}m | Piers: {num_piers}
  </text>

  <!-- ===== PLAN VIEW (top) ===== -->
  <g transform="translate({margin}, 60)">
    <text x="0" y="-10" class="label" font-weight="bold">Plan View</text>

    <!-- Deck outline -->
    <rect x="0" y="0" width="{span*scale}" height="{width*scale}"
          fill="#e8e8e8" stroke="#333" stroke-width="2"/>

    <!-- Centerline -->
    <line x1="0" y1="{width*scale/2}" x2="{span*scale}" y2="{width*scale/2}"
          stroke="#d00" stroke-width="1" stroke-dasharray="8,4"/>

    <!-- Dimension: span -->
    <line x1="0" y1="{width*scale + 15}" x2="{span*scale}" y2="{width*scale + 15}"
          stroke="#d00" stroke-width="1"/>
    <text x="{span*scale/2}" y="{width*scale + 30}" text-anchor="middle" class="dim">
      {span} m
    </text>

    <!-- Dimension: width -->
    <line x1="-20" y1="0" x2="-20" y2="{width*scale}"
          stroke="#d00" stroke-width="1"/>
    <text x="-25" y="{width*scale/2}" text-anchor="end" class="dim">
      {width} m
    </text>
  </g>

  <!-- ===== FRONT ELEVATION ===== -->
  <g transform="translate({margin}, {60 + width*scale + 60})">
    <text x="0" y="-10" class="label" font-weight="bold">Front Elevation</text>

    <!-- Deck -->
    <rect x="0" y="{clearance*scale}" width="{span*scale}" height="{deck_thickness*scale}"
          fill="#ccc" stroke="#333" stroke-width="2"/>

    <!-- Ground line -->
    <line x1="-10" y1="{(clearance + deck_thickness)*scale}" x2="{span*scale + 10}"
          y2="{(clearance + deck_thickness)*scale}"
          stroke="#693" stroke-width="1"/>
'''

    # Add piers
    if num_piers >= 2 and pier_spacings:
        # Calculate pier positions
        total_span = sum(pier_spacings)
        first_pier = (span - total_span) / 2
        pier_x = first_pier
        for i, spacing in enumerate(pier_spacings):
            px = pier_x * scale
            pw = 1.0 * scale  # pier width in plan
            ph = clearance * scale
            py = (clearance + deck_thickness) * scale - ph
            svg += f'''
    <!-- Pier {i+1} -->
    <rect x="{px - pw/2}" y="{py}" width="{pw}" height="{ph}"
          fill="#aab" stroke="#333" stroke-width="1"/>'''
            pier_x += spacing
        # Last pier
        px = pier_x * scale
        svg += f'''
    <!-- Pier {num_piers} -->
    <rect x="{px - pw/2}" y="{py}" width="{pw}" height="{ph}"
          fill="#aab" stroke="#333" stroke-width="1"/>'''

    # Clearance dimension
    svg += f'''
    <line x1="{span*scale + 20}" y1="{clearance*scale + deck_thickness*scale}"
          x2="{span*scale + 20}" y2="{deck_thickness*scale}"
          stroke="#d00" stroke-width="1"/>
    <text x="{span*scale + 25}" y="{(clearance/2 + deck_thickness)*scale}"
          class="dim">{clearance}m clearance</text>
  </g>
'''

    # ===== SIDE ELEVATION =====
    svg += f'''
  <!-- Side Elevation -->
  <g transform="translate({margin}, {60 + width*scale + 60 + clearance*scale + 80})">
    <text x="0" y="-10" class="label" font-weight="bold">Side Elevation</text>

    <!-- Deck cross-section -->
    <rect x="0" y="{clearance*scale}" width="{width*scale}" height="{deck_thickness*scale}"
          fill="#ccc" stroke="#333" stroke-width="2"/>

    <!-- Ground -->
    <line x1="-10" y1="{(clearance + deck_thickness)*scale}" x2="{width*scale + 10}"
          y2="{(clearance + deck_thickness)*scale}"
          stroke="#693" stroke-width="1"/>

    <!-- Pier cross-section -->
    <rect x="{width*scale/2 - 0.5*scale}" y="{clearance*scale}"
          width="{1.0*scale}" height="{clearance*scale}"
          fill="#aab" stroke="#333" stroke-width="1"/>

    <!-- Dimension: width -->
    <line x1="0" y1="{(clearance + deck_thickness)*scale + 20}"
          x2="{width*scale}" y2="{(clearance + deck_thickness)*scale + 20}"
          stroke="#d00" stroke-width="1"/>
    <text x="{width*scale/2}" y="{(clearance + deck_thickness)*scale + 35}"
          text-anchor="middle" class="dim">{width} m</text>
  </g>

  <!-- Specification Table -->
  <g transform="translate({margin}, {svg_height - 150})">
    <text x="0" y="0" class="label" font-weight="bold">Specifications</text>
    <text x="0" y="18" class="label">Bridge Type: {params.get('bridge_type', 'beam')}</text>
    <text x="0" y="34" class="label">Span Length: {span} m</text>
    <text x="0" y="50" class="label">Deck Width: {width} m</text>
    <text x="0" y="66" class="label">Clearance: {clearance} m</text>
    <text x="0" y="82" class="label">Number of Piers: {num_piers}</text>
  </g>
</svg>'''

    with open(output_path, 'w') as f:
        f.write(svg)

    print(f"  Simple SVG drawing saved to: {output_path}")


def structural_analysis_placeholder(params):
    """Placeholder for structural analysis.

    In a full implementation, this would:
    1. Export model to OpenSees or use FreeCAD FEM
    2. Compute bending moments
    3. Annotate max moment locations on drawings
    """
    print(f"\n[Structural Analysis - Placeholder]")
    dims = params['dimensions']
    span = dims['span_length']
    width = dims['deck_width']

    # Simple uniform load estimation
    deck_area = span * width
    dead_load = deck_area * 0.5 * 25  # 0.5m concrete @ 25 kN/m3
    live_load = deck_area * 5.0  # 5 kN/m2 traffic load

    # For simple beam: M_max = wL^2/8
    w = (dead_load + live_load) / span  # kN/m
    M_max = w * span**2 / 8

    print(f"  Dead load: {dead_load:.0f} kN")
    print(f"  Live load: {live_load:.0f} kN")
    print(f"  Max bending moment: {M_max:.0f} kN·m")
    print(f"  (Simple beam model, uniform load)")

    return {
        'dead_load_kN': round(dead_load, 0),
        'live_load_kN': round(live_load, 0),
        'max_moment_kNm': round(M_max, 0),
        'span_m': span,
        'width_m': width,
    }


def main():
    if not FREECAD:
        print("Error: This script must be run with freecadcmd, not regular Python.")
        print("Usage: freecadcmd freecad_bridge.py --params bridge_params.json")
        sys.exit(1)

    args = parse_args()

    # Load parameters
    print("=" * 60)
    print("Parametric Bridge Model Generator")
    print("=" * 60)
    params = load_params(args.params)
    print(f"Loaded parameters from: {args.params}")
    print(f"  Bridge type: {params.get('bridge_type', 'unknown')}")
    print(f"  Span: {params['dimensions']['span_length']}m")
    print(f"  Width: {params['dimensions']['deck_width']}m")

    # Create 3D model
    doc, objects = create_bridge_model(params)

    # Generate drawings
    drawing_output = args.drawing or args.output.replace('.FCStd', '_drawing.svg')
    create_techdraw_views(doc, params, drawing_output)

    # Optional structural analysis
    if args.analyze:
        analysis = structural_analysis_placeholder(params)

    # Save FreeCAD document
    output_path = Path(args.output)
    doc.saveAs(str(output_path.absolute()))
    print(f"\nFreeCAD model saved to: {output_path.absolute()}")

    # Export to STEP for interoperability
    step_path = output_path.with_suffix('.step')
    try:
        bridge = doc.getObject('Bridge')
        if bridge:
            Part.export([bridge], str(step_path.absolute()))
            print(f"STEP export saved to: {step_path.absolute()}")
    except Exception as e:
        print(f"STEP export skipped: {e}")

    # Export mesh
    mesh_path = output_path.with_suffix('.stl')
    try:
        bridge = doc.getObject('Bridge')
        if bridge:
            mesh = doc.addObject('Mesh::Feature', 'BridgeMesh')
            mesh.Mesh = Mesh.Mesh(bridge.Shape.tessellate(1.0))
            mesh.Mesh.write(str(mesh_path.absolute()))
            print(f"STL mesh saved to: {mesh_path.absolute()}")
    except Exception as e:
        print(f"STL export skipped: {e}")

    print(f"\n{'=' * 60}")
    print("Bridge model generation complete!")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
