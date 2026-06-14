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
    """Load bridge parameters from JSON. Supports both bridge_params.json
    and detailed_design.json formats."""
    with open(params_path, 'r') as f:
        params = json.load(f)

    # Detect format: detailed_design.json has 'superstructure' key
    if 'superstructure' in params:
        return params  # detailed_design.json format

    # Wrap legacy bridge_params.json into a compatible structure
    dims = params.get('dimensions', {})
    return {
        'bridge_type': params.get('bridge_type', 'beam'),
        'design_code': 'N/A',
        'dimensions': dims,
        'centerline': params.get('centerline', {}),
        'pier_positions': params.get('pier_positions', []),
        'abutment_positions': params.get('abutment_positions', []),
        'superstructure': {
            'girder_type': 'solid_box',  # Legacy fallback
            'num_girders': 1,
            'girder_depth': 0.5,
            'girder_spacing': dims.get('deck_width', 8.0),
            'deck_thickness': 0.5,
            'flange_width': 0,
            'flange_thickness': 0,
            'web_thickness': 0,
            'curb_width': 0,
            'curb_height': 0,
        },
        'substructure': {
            'piers': [{'height': p.get('height', 5.0), 'section': '1.0x2.0m',
                        'x_pos': p.get('x', 0), 'y_pos': p.get('y', 0),
                        'cap_width': 2.6, 'cap_depth': 0.6,
                        'foundation': 'spread_footing_3x3x0.8m'}
                      for p in params.get('pier_positions', [])],
            'abutments': [{'height': a.get('height', 5.0), 'width': dims.get('deck_width', 8.0),
                           'x_pos': a.get('x', 0), 'y_pos': a.get('y', 0)}
                          for a in params.get('abutment_positions', [])],
            'bearing_type': 'elastomeric_pad',
            'bearings_count': len(params.get('pier_positions', [])) * 4,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# Helper: Create I-beam profile shape
# ═══════════════════════════════════════════════════════════════════════════

def make_i_beam_profile(depth_m, flange_w_m, flange_t_m, web_t_m):
    """Create an I-beam cross-section wire for extrusion.

    Returns a FreeCAD Part.Wire in the YZ plane (vertical),
    centered at origin, ready for extrusion along X axis.
    """
    d = depth_m * 1000  # mm
    fw = flange_w_m * 1000
    ft = flange_t_m * 1000
    wt = web_t_m * 1000

    half_fw = fw / 2
    half_wt = wt / 2

    # Points in YZ plane: Y=horizontal (flange width), Z=vertical (depth)
    # Start from bottom-left of bottom flange, go clockwise
    y0 = -half_fw  # Left edge
    y1 = half_fw   # Right edge
    z_bot = -d / 2
    z_top = d / 2
    z_bot_inner = z_bot + ft
    z_top_inner = z_top - ft

    pts = [
        FreeCAD.Vector(0, y0, z_bot),          # Bottom-left
        FreeCAD.Vector(0, y1, z_bot),          # Bottom-right
        FreeCAD.Vector(0, y1, z_bot_inner),    # Bottom flange top-right
        FreeCAD.Vector(0, half_wt, z_bot_inner),  # Web bottom-right
        FreeCAD.Vector(0, half_wt, z_top_inner),  # Web top-right
        FreeCAD.Vector(0, y1, z_top_inner),    # Top flange bottom-right
        FreeCAD.Vector(0, y1, z_top),          # Top-right
        FreeCAD.Vector(0, y0, z_top),          # Top-left
        FreeCAD.Vector(0, y0, z_top_inner),    # Top flange bottom-left
        FreeCAD.Vector(0, -half_wt, z_top_inner),  # Web top-left
        FreeCAD.Vector(0, -half_wt, z_bot_inner),  # Web bottom-left
        FreeCAD.Vector(0, y0, z_bot_inner),    # Bottom flange top-left
        FreeCAD.Vector(0, y0, z_bot),          # Close
    ]

    wire = Part.makePolygon(pts)
    face = Part.Face(wire)
    return face


# ═══════════════════════════════════════════════════════════════════════════
# Detailed Beam Bridge Model
# ═══════════════════════════════════════════════════════════════════════════

def create_beam_bridge_detailed(doc, params):
    """Create a detailed beam bridge with I-beam girders, pier caps, railings."""
    super_s = params.get('superstructure', {})
    sub = params.get('substructure', {})
    dims = params.get('dimensions', {})
    centerline = params.get('centerline', {})

    objects = {'deck': None, 'girders': [], 'piers': [], 'abutments': [],
               'railings': [], 'bearings': [], 'road': None}

    # Dimensions
    span = dims.get('span_length', 30)
    width = dims.get('deck_width', 8)
    deck_elev = dims.get('deck_elevation', 5.0)
    ground_elev = dims.get('ground_elevation', 0.0)

    girder_type = super_s.get('girder_type', 'I-beam')
    num_girders = super_s.get('num_girders', 3)
    girder_depth = super_s.get('girder_depth', 1.7)
    girder_spacing = super_s.get('girder_spacing', 2.7)
    deck_thickness = super_s.get('deck_thickness', 0.225)
    flange_w = super_s.get('flange_width', 0.85)
    flange_t = super_s.get('flange_thickness', 0.21)
    web_t = super_s.get('web_thickness', 0.14)
    curb_w = super_s.get('curb_width', 0.5)
    curb_h = super_s.get('curb_height', 0.3)

    deck_bot_z = deck_elev - deck_thickness

    print(f"Building detailed beam bridge model:")
    print(f"  {girder_type}, {num_girders} girders @ {girder_spacing}m spacing")
    print(f"  Girder depth: {girder_depth}m, Deck: {deck_thickness*1000:.0f}mm")

    # ── 1. Girders ──
    print(f"\n[1/6] Creating {num_girders} I-beam girders...")
    if girder_type in ('I-beam', 'T-beam'):
        profile_face = make_i_beam_profile(girder_depth, flange_w, flange_t, web_t)
    else:
        # Solid rectangular profile as fallback
        profile_face = Part.Face(Part.makePolygon([
            FreeCAD.Vector(0, -girder_depth*500, -0.25*1000),
            FreeCAD.Vector(0, girder_depth*500, -0.25*1000),
            FreeCAD.Vector(0, girder_depth*500, 0.25*1000),
            FreeCAD.Vector(0, -girder_depth*500, 0.25*1000),
            FreeCAD.Vector(0, -girder_depth*500, -0.25*1000),
        ]))

    girder_objects = []
    for i in range(num_girders):
        y_offset = -width/2 + curb_w + girder_spacing/2 + i * girder_spacing
        # Extrude profile along bridge X-axis
        extrude_vec = FreeCAD.Vector(span * 1000, 0, 0)
        girder_shape = profile_face.extrude(extrude_vec)

        girder_obj = doc.addObject('Part::Feature', f'Girder_{i+1}')
        girder_obj.Shape = girder_shape
        girder_obj.Placement.Base = FreeCAD.Vector(
            -span/2 * 1000,
            y_offset * 1000,
            (deck_bot_z - girder_depth) * 1000
        )

        # Set color
        if hasattr(girder_obj, 'ViewObject') and girder_obj.ViewObject:
            try:
                girder_obj.ViewObject.ShapeColor = (0.65, 0.65, 0.70, 1.0)
            except:
                pass

        girder_objects.append(girder_obj)
        objects['girders'].append(girder_obj)

    print(f"  Created {len(girder_objects)} girder extrusions")

    # ── 2. Deck Slab ──
    print(f"\n[2/6] Creating deck slab...")
    deck = doc.addObject('Part::Box', 'DeckSlab')
    deck.Length = span * 1000
    deck.Width = width * 1000
    deck.Height = deck_thickness * 1000
    deck.Placement.Base = FreeCAD.Vector(
        -span/2 * 1000, -width/2 * 1000,
        deck_bot_z * 1000
    )
    if hasattr(deck, 'ViewObject') and deck.ViewObject:
        try:
            deck.ViewObject.ShapeColor = (0.75, 0.72, 0.68, 1.0)
        except:
            pass
    objects['deck'] = deck

    # ── 3. Curbs ──
    print(f"\n[3/6] Creating curbs and railings...")
    if curb_w > 0 and curb_h > 0:
        for side, sign in [('Left', -1), ('Right', 1)]:
            curb = doc.addObject('Part::Box', f'Curb_{side}')
            curb.Length = span * 1000
            curb.Width = curb_w * 1000
            curb.Height = curb_h * 1000
            curb.Placement.Base = FreeCAD.Vector(
                -span/2 * 1000,
                sign * width/2 * 1000 - (curb_w if sign > 0 else 0) * 1000,
                deck_elev * 1000
            )
            if hasattr(curb, 'ViewObject') and curb.ViewObject:
                try:
                    curb.ViewObject.ShapeColor = (0.55, 0.55, 0.55, 1.0)
                except:
                    pass
            objects['railings'].append(curb)

    # ── 4. Railings / Barriers ──
    railing_height = 1.1
    post_spacing = 2.0
    n_posts = int(span / post_spacing) + 1

    for side, sign in [('L', -1), ('R', 1)]:
        edge_y = sign * (width/2 - curb_w/2) * 1000
        for j in range(n_posts):
            post_x = (-span/2 + j * post_spacing) * 1000
            post = doc.addObject('Part::Cylinder', f'RailingPost_{side}_{j+1}')
            post.Radius = 0.05 * 1000
            post.Height = railing_height * 1000
            post.Placement.Base = FreeCAD.Vector(
                post_x, edge_y, (deck_elev + curb_h) * 1000
            )
            objects['railings'].append(post)

        # Top rail (horizontal bar)
        rail = doc.addObject('Part::Cylinder', f'TopRail_{side}')
        rail.Radius = 0.04 * 1000
        rail.Height = span * 1000
        # Rotate to horizontal (along X axis) — use Placement.Rotation
        from FreeCAD import Rotation
        rail.Placement = FreeCAD.Placement(
            FreeCAD.Vector(-span/2 * 1000, edge_y,
                          (deck_elev + curb_h + railing_height) * 1000),
            Rotation(FreeCAD.Vector(0, 1, 0), 90)
        )
        objects['railings'].append(rail)

    print(f"  Created railings: {n_posts*2} posts, 2 top rails")

    # ── 5. Piers with caps ──
    print(f"\n[4/6] Creating piers with caps...")
    piers_data = sub.get('piers', params.get('pier_positions', []))

    for i, p in enumerate(piers_data):
        pier_h = p.get('height', 5.0)
        section = p.get('section', '1.0x2.0m')
        px = p.get('x_pos', p.get('x', 0))
        py = p.get('y_pos', p.get('y', 0))
        cap_w = p.get('cap_width', 2.6)
        cap_d = p.get('cap_depth', 0.6)

        # Parse section dimensions
        try:
            sec_parts = section.replace('m', '').split('x')
            col_w, col_l = float(sec_parts[0]), float(sec_parts[1])
        except:
            col_w, col_l = 1.0, 2.0

        # Column
        column = doc.addObject('Part::Box', f'PierColumn_{i+1}')
        column.Length = col_l * 1000
        column.Width = col_w * 1000
        column.Height = pier_h * 1000
        column.Placement.Base = FreeCAD.Vector(
            px * 1000 - col_l * 1000 / 2,
            py * 1000 - col_w * 1000 / 2,
            0
        )
        if hasattr(column, 'ViewObject') and column.ViewObject:
            try:
                column.ViewObject.ShapeColor = (0.70, 0.70, 0.75, 1.0)
            except:
                pass
        objects['piers'].append(column)

        # Pier cap
        cap = doc.addObject('Part::Box', f'PierCap_{i+1}')
        cap.Length = cap_w * 1000
        cap.Width = width * 0.8 * 1000
        cap.Height = cap_d * 1000
        cap.Placement.Base = FreeCAD.Vector(
            px * 1000 - cap_w * 1000 / 2,
            -width * 0.4 * 1000,
            pier_h * 1000
        )
        if hasattr(cap, 'ViewObject') and cap.ViewObject:
            try:
                cap.ViewObject.ShapeColor = (0.70, 0.70, 0.75, 1.0)
            except:
                pass
        objects['piers'].append(cap)

        # Bearing pads (small blocks on cap)
        for bj, bx_offset in enumerate([-0.8, 0.8]):
            bearing = doc.addObject('Part::Box', f'Bearing_P{i+1}_{bj+1}')
            bearing.Length = 0.4 * 1000
            bearing.Width = 0.4 * 1000
            bearing.Height = 0.08 * 1000
            bearing.Placement.Base = FreeCAD.Vector(
                (px + bx_offset) * 1000 - 0.2 * 1000,
                -0.2 * 1000,
                (pier_h + cap_d) * 1000
            )
            if hasattr(bearing, 'ViewObject') and bearing.ViewObject:
                try:
                    bearing.ViewObject.ShapeColor = (0.9, 0.2, 0.2, 1.0)
                except:
                    pass
            objects['bearings'].append(bearing)

    print(f"  Created {len(piers_data)} pier(s) with caps and bearings")

    # ── 6. Abutments ──
    print(f"\n[5/6] Creating abutments...")
    abutments_data = sub.get('abutments', params.get('abutment_positions', []))

    for i, a in enumerate(abutments_data):
        ah = a.get('height', 5.0)
        aw = a.get('width', width + 1)
        ax = a.get('x_pos', a.get('x', 0))
        ay = a.get('y_pos', a.get('y', 0))

        # Main abutment body
        abutment = doc.addObject('Part::Box', f'Abutment_{i+1}')
        abutment.Length = 2.0 * 1000
        abutment.Width = aw * 1000
        abutment.Height = ah * 1000
        abutment.Placement.Base = FreeCAD.Vector(
            ax * 1000 - 1.0 * 1000,
            -aw / 2 * 1000,
            0
        )
        if hasattr(abutment, 'ViewObject') and abutment.ViewObject:
            try:
                abutment.ViewObject.ShapeColor = (0.68, 0.68, 0.72, 1.0)
            except:
                pass
        objects['abutments'].append(abutment)

        # Backwall
        backwall = doc.addObject('Part::Box', f'Backwall_{i+1}')
        backwall.Length = 0.4 * 1000
        backwall.Width = aw * 1000
        backwall.Height = 1.5 * 1000
        # Backwall sits on top of abutment, on the earth side
        bw_x = ax * 1000 + (1.0 if ax < 0 else -1.4) * 1000
        backwall.Placement.Base = FreeCAD.Vector(
            bw_x, -aw / 2 * 1000, ah * 1000
        )
        if hasattr(backwall, 'ViewObject') and backwall.ViewObject:
            try:
                backwall.ViewObject.ShapeColor = (0.68, 0.68, 0.72, 1.0)
            except:
                pass
        objects['abutments'].append(backwall)

    # ── 7. Road Surface ──
    print(f"\n[6/6] Creating road surface...")
    road = doc.addObject('Part::Box', 'RoadSurface')
    road.Length = span * 1000
    road.Width = (width - 2 * curb_w) * 1000
    road.Height = 0.075 * 1000  # 75mm asphalt
    road.Placement.Base = FreeCAD.Vector(
        -span/2 * 1000,
        -(width - 2 * curb_w) / 2 * 1000,
        deck_elev * 1000
    )
    if hasattr(road, 'ViewObject') and road.ViewObject:
        try:
            road.ViewObject.ShapeColor = (0.15, 0.15, 0.15, 1.0)
        except:
            pass
    objects['road'] = road

    # ── Fuse all components ──
    print(f"\n  Fusing bridge components...")
    all_parts = [objects['deck']] + objects['girders'] + objects['piers'] + \
                objects['abutments'] + objects['bearings']
    if objects['road']:
        all_parts.append(objects['road'])
    # Include railings if they exist
    for r in objects['railings']:
        all_parts.append(r)

    # Create compound and fusion
    compound = doc.addObject('Part::Compound', 'BridgeCompound')
    compound.Links = all_parts

    fusion = doc.addObject('Part::MultiFuse', 'Bridge')
    fusion.Shapes = all_parts

    doc.recompute()
    print("  Detailed beam bridge model built successfully!")

    return doc, objects


# ═══════════════════════════════════════════════════════════════════════════
# Arch Bridge Model
# ═══════════════════════════════════════════════════════════════════════════

def create_arch_bridge_model(doc, params):
    """Create an arch bridge with parabolic ribs and spandrel columns."""
    super_s = params.get('superstructure', {})
    sub = params.get('substructure', {})
    dims = params.get('dimensions', {})

    objects = {'deck': None, 'arch_ribs': [], 'spandrels': [], 'piers': [],
               'abutments': [], 'road': None}

    span = super_s.get('span', dims.get('span_length', 30))
    width = dims.get('deck_width', 8)
    deck_elev = dims.get('deck_elevation', 5.0)
    rise = super_s.get('rise', span * 0.2)
    num_ribs = super_s.get('num_ribs', 2)
    rib_width = super_s.get('rib_width', 1.2)
    rib_depth = super_s.get('rib_depth', 0.6)
    num_spandrels = super_s.get('num_spandrels', 6)
    deck_thickness = super_s.get('deck_thickness', 0.25)
    curb_w = super_s.get('curb_width', 0.5)
    curb_h = super_s.get('curb_height', 0.3)

    print(f"Building arch bridge model:")
    print(f"  Span: {span}m, Rise: {rise}m (rise/span={rise/span:.2f})")
    print(f"  {num_ribs} ribs, {num_spandrels} spandrel columns")

    # ── 1. Arch Ribs ──
    print(f"\n[1/5] Creating arch ribs...")

    # Parabolic arch: z = rise * (1 - (2x/L)^2) = 4*rise*(x/L)*(1-x/L)
    n_curve_pts = 100
    for r in range(num_ribs):
        rib_y = (-width/2 + 0.5 + r * (width - 1)/(num_ribs - 1)) * 1000 \
                if num_ribs > 1 else 0

        # Build arch curve points
        curve_pts = []
        for j in range(n_curve_pts + 1):
            x = -span/2 + j * span / n_curve_pts
            t = (x + span/2) / span  # 0 to 1
            z = 4 * rise * t * (1 - t)  # Parabola: max at t=0.5
            curve_pts.append(FreeCAD.Vector(x * 1000, rib_y, z * 1000))

        # Create BSpline through points
        curve = Part.BSplineCurve()
        curve.interpolate(curve_pts)
        curve_wire = Part.Wire(curve.toShape())

        # Create rib cross-section and sweep
        rib_profile = Part.Face(Part.makePolygon([
            FreeCAD.Vector(0, -rib_width*500, -rib_depth*500),
            FreeCAD.Vector(0, rib_width*500, -rib_depth*500),
            FreeCAD.Vector(0, rib_width*500, rib_depth*500),
            FreeCAD.Vector(0, -rib_width*500, rib_depth*500),
            FreeCAD.Vector(0, -rib_width*500, -rib_depth*500),
        ]))

        rib_shape = curve_wire.makePipe(rib_profile)
        rib_obj = doc.addObject('Part::Feature', f'ArchRib_{r+1}')
        rib_obj.Shape = rib_shape
        if hasattr(rib_obj, 'ViewObject') and rib_obj.ViewObject:
            try:
                rib_obj.ViewObject.ShapeColor = (0.65, 0.60, 0.70, 1.0)
            except:
                pass
        objects['arch_ribs'].append(rib_obj)

    print(f"  Created {num_ribs} parabolic arch ribs")

    # ── 2. Spandrel Columns ──
    print(f"\n[2/5] Creating spandrel columns...")
    for i in range(num_spandrels):
        x = -span/2 + (i + 0.5) * span / num_spandrels
        t = (x + span/2) / span
        arch_z = 4 * rise * t * (1 - t)  # Z on arch curve

        col_h = deck_elev - arch_z - deck_thickness  # Column height
        if col_h < 0.2:
            continue

        for r in range(num_ribs):
            rib_y = (-width/2 + 0.5 + r * (width - 1)/(num_ribs - 1)) \
                    if num_ribs > 1 else 0

            col = doc.addObject('Part::Box', f'Spandrel_{i+1}_{r+1}')
            col.Length = 0.5 * 1000
            col.Width = 0.5 * 1000
            col.Height = col_h * 1000
            col.Placement.Base = FreeCAD.Vector(
                x * 1000 - 0.25 * 1000,
                rib_y - 0.25 * 1000,
                (arch_z + rib_depth) * 1000
            )
            if hasattr(col, 'ViewObject') and col.ViewObject:
                try:
                    col.ViewObject.ShapeColor = (0.72, 0.72, 0.76, 1.0)
                except:
                    pass
            objects['spandrels'].append(col)

    print(f"  Created {len(objects['spandrels'])} spandrel columns")

    # ── 3. Deck ──
    print(f"\n[3/5] Creating deck...")
    deck = doc.addObject('Part::Box', 'DeckSlab')
    deck.Length = span * 1000
    deck.Width = width * 1000
    deck.Height = deck_thickness * 1000
    deck.Placement.Base = FreeCAD.Vector(
        -span/2 * 1000, -width/2 * 1000,
        (deck_elev - deck_thickness) * 1000
    )
    if hasattr(deck, 'ViewObject') and deck.ViewObject:
        try:
            deck.ViewObject.ShapeColor = (0.75, 0.72, 0.68, 1.0)
        except:
            pass
    objects['deck'] = deck

    # Curbs
    if curb_w > 0:
        for side, sign in [('Left', -1), ('Right', 1)]:
            curb = doc.addObject('Part::Box', f'Curb_{side}')
            curb.Length = span * 1000
            curb.Width = curb_w * 1000
            curb.Height = curb_h * 1000
            curb.Placement.Base = FreeCAD.Vector(
                -span/2 * 1000,
                (sign * width/2 - (curb_w if sign > 0 else 0)) * 1000,
                deck_elev * 1000
            )
            objects['railings'] = objects.get('railings', []) + [curb]

    # ── 4. Abutments (arch springing points) ──
    print(f"\n[4/5] Creating arch springing abutments...")
    for side, sign in [('Left', -1), ('Right', 1)]:
        abut_x = sign * span/2
        abutment = doc.addObject('Part::Box', f'Abutment_{side}')
        abutment.Length = 3.0 * 1000
        abutment.Width = (width + 1) * 1000
        abutment.Height = rise * 0.6 * 1000  # Abutment visible height
        abutment.Placement.Base = FreeCAD.Vector(
            (abut_x - 1.5 * sign) * 1000 if sign < 0 else (abut_x - 1.5) * 1000,
            -(width + 1) / 2 * 1000,
            0
        )
        if hasattr(abutment, 'ViewObject') and abutment.ViewObject:
            try:
                abutment.ViewObject.ShapeColor = (0.68, 0.68, 0.72, 1.0)
            except:
                pass
        objects['abutments'].append(abutment)

    # ── 5. Road surface ──
    print(f"\n[5/5] Creating road surface...")
    road = doc.addObject('Part::Box', 'RoadSurface')
    road.Length = span * 1000
    road.Width = (width - 2 * curb_w) * 1000
    road.Height = 0.075 * 1000
    road.Placement.Base = FreeCAD.Vector(
        -span/2 * 1000,
        -(width - 2 * curb_w) / 2 * 1000,
        deck_elev * 1000
    )
    if hasattr(road, 'ViewObject') and road.ViewObject:
        try:
            road.ViewObject.ShapeColor = (0.15, 0.15, 0.15, 1.0)
        except:
            pass
    objects['road'] = road

    # Fuse
    all_parts = [objects['deck']] + objects['arch_ribs'] + objects['spandrels'] + \
                objects['abutments']
    if objects['road']:
        all_parts.append(objects['road'])
    for r in objects.get('railings', []):
        all_parts.append(r)

    compound = doc.addObject('Part::Compound', 'BridgeCompound')
    compound.Links = all_parts

    fusion = doc.addObject('Part::MultiFuse', 'Bridge')
    fusion.Shapes = all_parts

    doc.recompute()
    print("  Arch bridge model built successfully!")

    return doc, objects


# ═══════════════════════════════════════════════════════════════════════════
# Main Model Dispatcher
# ═══════════════════════════════════════════════════════════════════════════

def create_bridge_model(params):
    """Create the full bridge 3D model in FreeCAD.
    Dispatches to type-specific builders based on bridge_type and format.

    Returns:
        doc: FreeCAD document
        objects: dict of created objects
    """
    doc = FreeCAD.newDocument("Bridge")

    bridge_type = params.get('bridge_type', 'beam')
    super_s = params.get('superstructure', {})
    girder_type = super_s.get('girder_type', '')

    # Use detailed builder if we have superstructure data and it's not legacy solid_box
    if super_s and girder_type not in ('solid_box', '') and bridge_type in ('beam', None):
        print(f"Using detailed beam bridge builder ({girder_type})")
        return create_beam_bridge_detailed(doc, params)

    if bridge_type == 'arch':
        print("Using arch bridge builder")
        return create_arch_bridge_model(doc, params)

    # ── Legacy fallback: simple box model ──
    print("Using legacy box-model builder")
    objects = {'deck': None, 'piers': [], 'abutments': [], 'road': None}

    dims = params['dimensions']
    piers_data = params.get('pier_positions', [])
    abutments_data = params.get('abutment_positions', [])

    span = dims['span_length']
    width = dims['deck_width']
    deck_elev = dims['deck_elevation']
    ground_elev = dims.get('ground_elevation', 0.0)
    deck_thickness = 0.5

    # Deck
    deck = doc.addObject('Part::Box', 'Deck')
    deck.Length = span * 1000
    deck.Width = width * 1000
    deck.Height = deck_thickness * 1000
    deck.Placement.Base = FreeCAD.Vector(
        -span/2 * 1000, -width/2 * 1000,
        (deck_elev - deck_thickness/2) * 1000
    )
    objects['deck'] = deck

    # Piers (simple boxes)
    for i, p in enumerate(piers_data):
        pier = doc.addObject('Part::Box', f'Pier_{i+1}')
        pier.Length = 2.0 * 1000
        pier.Width = 1.0 * 1000
        pier.Height = p['height'] * 1000
        pier.Placement.Base = FreeCAD.Vector(
            p['x'] * 1000 - 1.0 * 1000,
            p['y'] * 1000 - 0.5 * 1000,
            p['z_min'] * 1000
        )
        objects['piers'].append(pier)

    # Abutments
    for i, a in enumerate(abutments_data):
        abutment = doc.addObject('Part::Box', f'Abutment_{i+1}')
        abutment.Length = 2.0 * 1000
        abutment.Width = width * 1000
        abutment.Height = a['height'] * 1000
        abutment.Placement.Base = FreeCAD.Vector(
            a['x'] * 1000 - 1.0 * 1000,
            -width/2 * 1000,
            a['z_min'] * 1000
        )
        objects['abutments'].append(abutment)

    # Road surface
    road = doc.addObject('Part::Box', 'RoadSurface')
    road.Length = span * 1000
    road.Width = (width - 1.0) * 1000
    road.Height = 0.1 * 1000
    road.Placement.Base = FreeCAD.Vector(
        -span/2 * 1000,
        -(width - 1.0)/2 * 1000,
        (deck_elev + deck_thickness/2) * 1000
    )
    objects['road'] = road

    # Fuse
    all_parts = [objects['deck']] + objects['piers'] + objects['abutments'] + [objects['road']]
    compound = doc.addObject('Part::Compound', 'BridgeCompound')
    compound.Links = all_parts
    fusion = doc.addObject('Part::MultiFuse', 'Bridge')
    fusion.Shapes = all_parts

    doc.recompute()
    print("  Legacy model built successfully!")

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
    """Structural analysis summary.

    For detailed_design.json format: reads pre-computed analysis.
    For legacy format: computes simple beam estimates.
    """
    print(f"\n[Structural Analysis]")

    # Check if analysis was already performed by bridge_designer.py
    if 'analysis' in params:
        analysis = params['analysis']
        loads = params.get('loads', {})
        dims = params.get('dimensions', {})

        print(f"  Design code: {params.get('design_code', 'N/A')}")
        print(f"  Dead load: {loads.get('dead_load_kN_per_m', 'N/A')} kN/m")
        print(f"  Live load moment: {loads.get('live_load_moment_kNm', 'N/A')} kN·m")
        if 'Mu_per_girder_kNm' in analysis:
            print(f"  Factored moment (per girder): {analysis['Mu_per_girder_kNm']:.0f} kN·m")
            print(f"  Max deflection: {analysis.get('max_deflection_mm', 'N/A')} mm")
            print(f"  Deflection OK: {analysis.get('deflection_ok', 'N/A')}")
        elif 'compressive_stress_kPa' in analysis:
            print(f"  Compressive stress: {analysis['compressive_stress_kPa']:.0f} kPa")
            print(f"  Compression OK: {analysis.get('compression_ok', 'N/A')}")
        return analysis

    # Legacy fallback
    print(f"\n[Structural Analysis - Simplified Estimate]")
    dims = params['dimensions']
    span = dims['span_length']
    width = dims['deck_width']

    deck_area = span * width
    dead_load = deck_area * 0.5 * 25
    live_load = deck_area * 5.0

    w = (dead_load + live_load) / span
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

    # Load parameters (handles both legacy and detailed_design.json formats)
    print("=" * 60)
    print("Parametric Bridge Model Generator v0.3")
    print("=" * 60)
    params = load_params(args.params)
    print(f"Loaded parameters from: {args.params}")

    bridge_type = params.get('bridge_type', 'beam')
    super_s = params.get('superstructure', {})

    print(f"  Bridge type: {bridge_type}")
    print(f"  Format: {'detailed_design' if super_s else 'legacy bridge_params'}")

    if super_s:
        print(f"  Girder type: {super_s.get('girder_type', 'N/A')}")
        girder_depth = super_s.get('girder_depth', super_s.get('rib_depth', 'N/A'))
        print(f"  Section depth: {girder_depth}m")
    print(f"  Span: {params['dimensions']['span_length']}m")
    print(f"  Width: {params['dimensions']['deck_width']}m")

    # Create 3D model (dispatches to appropriate builder)
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

    # Export to STEP
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
