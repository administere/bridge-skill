#!/usr/bin/env python3
"""
Professional Bridge Construction Drawing Generator
Generates engineering-grade SVG drawings from detailed_design.json.

Drawings produced:
  1. GA_drawing.svg       — General Arrangement (plan + elevation + cross-section)
  2. Superstructure.svg   — Girder cross-section, rebar layout, deck details
  3. Substructure.svg     — Pier elevation, abutment details
  4. BOM_table.svg        — Bill of Materials & Specifications

Usage:
    python bridge_drawing.py detailed_design.json -o ./drawings/
    python bridge_drawing.py detailed_design.json --all
    python bridge_drawing.py detailed_design.json --sheets GA,Super
"""

import json
import math
import argparse
from pathlib import Path
from datetime import datetime


# ============================================================================
# SVG Drawing Engine
# ============================================================================

class DrawingEngine:
    """Base SVG drawing engine with coordinate system, dimension lines, etc."""

    def __init__(self, width_mm=841, height_mm=594, scale=1.0, title="Bridge Drawing"):
        """Initialize A1 landscape drawing by default."""
        self.width_mm = width_mm
        self.height_mm = height_mm
        self.scale = scale
        self.title = title
        self.elements = []
        self._defs = []

        # Drawing coordinate system: origin at bottom-left of drawing area
        self.margin = 25  # mm margin
        self.title_block_h = 45  # mm for title block

        # Drawing area
        self.dx = self.margin
        self.dy = self.margin
        self.dw = width_mm - 2 * self.margin
        self.dh = height_mm - 2 * self.margin - self.title_block_h

    def add_def(self, svg_def):
        self._defs.append(svg_def)

    def rect(self, x, y, w, h, fill="none", stroke="#333", stroke_width=0.35, cls=""):
        cls_attr = f' class="{cls}"' if cls else ""
        self.elements.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"{cls_attr}/>'
        )

    def line(self, x1, y1, x2, y2, stroke="#333", stroke_width=0.35, dash=None, cls=""):
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        cls_attr = f' class="{cls}"' if cls else ""
        self.elements.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{stroke}" stroke-width="{stroke_width}"{dash_attr}{cls_attr}/>'
        )

    def text(self, x, y, content, font_size=2.5, fill="#333", anchor="start",
             bold=False, cls=""):
        weight = ' font-weight="bold"' if bold else ""
        cls_attr = f' class="{cls}"' if cls else ""
        self.elements.append(
            f'<text x="{x}" y="{y}" font-family="Arial,SimHei,sans-serif" '
            f'font-size="{font_size}" fill="{fill}" text-anchor="{anchor}"{weight}{cls_attr}>{content}</text>'
        )

    def dimension(self, x1, y1, x2, y2, label, offset=8, direction="h"):
        """Draw a dimension line with arrows and label."""
        # Extension lines
        if direction == "h":
            self.line(x1, y1, x1, y1 + offset, stroke="#d00", stroke_width=0.18)
            self.line(x2, y2, x2, y2 + offset, stroke="#d00", stroke_width=0.18)
            # Dimension line
            self.line(x1, y1 + offset * 0.7, x2, y2 + offset * 0.7, stroke="#d00", stroke_width=0.18)
            # Arrows (small triangles at ends)
            arrow_sz = 1.5
            mx = (x1 + x2) / 2
            my = y1 + offset * 0.7
            self.line(x1, my, x1 + arrow_sz, my - arrow_sz/2, stroke="#d00", stroke_width=0.18)
            self.line(x1, my, x1 + arrow_sz, my + arrow_sz/2, stroke="#d00", stroke_width=0.18)
            self.line(x2, my, x2 - arrow_sz, my - arrow_sz/2, stroke="#d00", stroke_width=0.18)
            self.line(x2, my, x2 - arrow_sz, my + arrow_sz/2, stroke="#d00", stroke_width=0.18)
            self.text(mx, my - 1.5, label, font_size=2.2, fill="#d00", anchor="middle")
        else:
            self.line(x1 - offset, y1, x1, y1, stroke="#d00", stroke_width=0.18)
            self.line(x2 - offset, y2, x2, y2, stroke="#d00", stroke_width=0.18)
            self.line(x1 - offset * 0.7, y1, x2 - offset * 0.7, y2, stroke="#d00", stroke_width=0.18)
            my = (y1 + y2) / 2
            self.text(x1 - offset - 1, my, label, font_size=2.2, fill="#d00", anchor="end")

    def circle(self, cx, cy, r, fill="none", stroke="#333", stroke_width=0.35):
        self.elements.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{stroke_width}"/>'
        )

    def polygon(self, points, fill="#ccc", stroke="#333", stroke_width=0.35):
        pts_str = " ".join(f"{x},{y}" for x, y in points)
        self.elements.append(
            f'<polygon points="{pts_str}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{stroke_width}"/>'
        )

    def hatch_rect(self, x, y, w, h, pattern="concrete"):
        """Filled rectangle with hatch pattern."""
        if pattern == "concrete":
            self.rect(x, y, w, h, fill="#e8e0d8", stroke="#333", stroke_width=0.3)
            # Concrete dot pattern
            step = 3
            for xi in range(int(x), int(x + w), step):
                for yi in range(int(y), int(y + h), step):
                    self.circle(xi + step/2, yi + step/2, 0.3, fill="#999", stroke="none")
        elif pattern == "steel":
            self.rect(x, y, w, h, fill="#e0e5f0", stroke="#333", stroke_width=0.3)
            # Diagonal lines for steel
            for i in range(-int(h), int(w + h), 4):
                self.line(x + i, y, x + i + h, y + h, stroke="#aab", stroke_width=0.15)
        elif pattern == "asphalt":
            self.rect(x, y, w, h, fill="#3a3a3a", stroke="#333", stroke_width=0.3)
        else:
            self.rect(x, y, w, h, fill="#eee", stroke="#333", stroke_width=0.3)

    def title_block(self, drawing_number="GA-01", revision="A"):
        """Standard engineering title block at bottom of sheet."""
        tb_y = self.height_mm - self.margin - self.title_block_h
        tb_w = self.width_mm - 2 * self.margin

        # Title block border
        self.rect(self.margin, tb_y, tb_w, self.title_block_h,
                  fill="#fff", stroke="#333", stroke_width=0.5)

        # Horizontal dividers
        self.line(self.margin, tb_y + 8, self.margin + tb_w, tb_y + 8, stroke="#333", stroke_width=0.25)
        self.line(self.margin, tb_y + 16, self.margin + tb_w, tb_y + 16, stroke="#333", stroke_width=0.25)
        self.line(self.margin, tb_y + 24, self.margin + tb_w, tb_y + 24, stroke="#333", stroke_width=0.25)
        self.line(self.margin, tb_y + 32, self.margin + tb_w, tb_y + 32, stroke="#333", stroke_width=0.25)

        # Vertical dividers
        x_divs = [tb_w * 0.35, tb_w * 0.55, tb_w * 0.70, tb_w * 0.82]
        for xd in x_divs:
            self.line(self.margin + xd, tb_y, self.margin + xd, tb_y + self.title_block_h,
                      stroke="#333", stroke_width=0.25)

        # Title block content
        self.text(self.margin + 3, tb_y + 6, self.title, font_size=3.5, bold=True)
        self.text(self.margin + 3, tb_y + 13, "Bridge Construction Drawing", font_size=2.2)

        # Project info
        self.text(self.margin + tb_w * 0.35 + 3, tb_y + 6, "Drawing:", font_size=2.2)
        self.text(self.margin + tb_w * 0.35 + 3, tb_y + 13, drawing_number, font_size=2.5, bold=True)

        self.text(self.margin + tb_w * 0.55 + 3, tb_y + 6, "Revision:", font_size=2.2)
        self.text(self.margin + tb_w * 0.55 + 3, tb_y + 13, revision, font_size=2.5, bold=True)

        self.text(self.margin + tb_w * 0.70 + 3, tb_y + 6, "Scale:", font_size=2.2)
        self.text(self.margin + tb_w * 0.70 + 3, tb_y + 13, f"1:{int(self.scale)}", font_size=2.5, bold=True)

        self.text(self.margin + tb_w * 0.82 + 3, tb_y + 6, "Date:", font_size=2.2)
        self.text(self.margin + tb_w * 0.82 + 3, tb_y + 13,
                  datetime.now().strftime("%Y-%m-%d"), font_size=2.2)

        # Bottom row: units, design code
        self.text(self.margin + 3, tb_y + 21, "All dimensions in mm unless noted", font_size=2.0)
        self.text(self.margin + 3, tb_y + 29, "Design Code: AASHTO LRFD Bridge Design Specs", font_size=2.0)

        self.text(self.margin + tb_w * 0.35 + 3, tb_y + 29,
                  "Generated by Bridge Skill Pipeline", font_size=2.0, fill="#888")

    def render(self, output_path):
        """Render all elements to SVG file."""
        svg_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     width="{self.width_mm}mm" height="{self.height_mm}mm"
     viewBox="0 0 {self.width_mm} {self.height_mm}">
  <defs>
    <style>
      text {{ font-family: 'Arial', 'SimHei', sans-serif; }}
      .cut-line {{ stroke: #1a1a1a; stroke-width: 0.5; }}
      .thin-line {{ stroke: #666; stroke-width: 0.18; }}
      .dim-line {{ stroke: #d00; stroke-width: 0.18; }}
      .center-line {{ stroke: #d00; stroke-width: 0.25; stroke-dasharray: 8,3,2,3; }}
      .hidden-line {{ stroke: #999; stroke-width: 0.18; stroke-dasharray: 3,3; }}
      .title {{ font-size: 4.5mm; font-weight: bold; fill: #1a1a1a; }}
      .subtitle {{ font-size: 3mm; font-weight: bold; fill: #333; }}
      .label {{ font-size: 2.5mm; fill: #333; }}
      .dim-label {{ font-size: 2.2mm; fill: #d00; }}
    </style>
    {"".join(self._defs)}
  </defs>
  <!-- Background -->
  <rect width="{self.width_mm}" height="{self.height_mm}" fill="white"/>

  <!-- Sheet border -->
  <rect x="5" y="5" width="{self.width_mm - 10}" height="{self.height_mm - 10}"
        fill="none" stroke="#333" stroke-width="0.5"/>

  <!-- Content -->
  {"".join(self.elements)}
</svg>'''

        with open(output_path, "w") as f:
            f.write(svg_content)
        print(f"  Saved: {output_path}")


# ============================================================================
# Drawing Generators
# ============================================================================

def draw_general_arrangement(design, output_dir):
    """Generate General Arrangement drawing — Plan + Elevation + Cross-section."""
    dims_super = design["superstructure"]
    dims_sub = design["substructure"]

    span = dims_super.get("girder_depth", 1.7)  # will be calculated properly
    width = dims_super.get("girder_spacing", 2.7) * dims_super.get("num_girders", 3)

    # Get dimensions from design
    bridge_type = design.get("bridge_type", "beam")
    girder_depth = dims_super.get("girder_depth", 1.7)
    num_girders = dims_super.get("num_girders", 3)
    girder_spacing = dims_super.get("girder_spacing", 2.7)
    deck_thickness = dims_super.get("deck_thickness", 0.225)
    curb_w = dims_super.get("curb_width", 0.5)
    curb_h = dims_super.get("curb_height", 0.3)

    # Estimate overall dimensions
    # If we have original params, span and width are there
    # Otherwise compute from superstructure
    if bridge_type == "arch":
        span = dims_super.get("span", 30)
        width = dims_super.get("num_ribs", 2) * 4.0 + 2 * curb_w
        rise = dims_super.get("rise", 6)
        deck_elev = rise + 1.0
    else:
        span = 30  # Default, should come from original params
        width = num_girders * girder_spacing + 2 * curb_w
        deck_elev = 5.0

    # Get pier heights from substructure
    piers = dims_sub.get("piers", [])
    pier_height = piers[0]["height"] if piers else 5.0
    clearance = pier_height - girder_depth - deck_thickness

    # Scale: fit span + margins in drawing width
    draw_w = 841 - 2 * 25  # usable width (A1 landscape)
    scale = span * 1000 / (draw_w * 0.45)  # 45% for plan, 45% for elevation
    scale = max(scale, 10)  # minimum 1:10

    engine = DrawingEngine(841, 594, scale, f"Bridge General Arrangement — {bridge_type.upper()}")

    # Layout: plan view top-left, elevation bottom-left, cross-section right
    plan_x0 = 30
    plan_y0 = 40

    elev_x0 = 30
    elev_y0 = plan_y0 + (width * 1000 / scale) + 40

    sect_x0 = 30 + span * 1000 / scale + 40
    sect_y0 = plan_y0

    # ── Title ──
    engine.text(30, 18, f"BRIDGE GENERAL ARRANGEMENT", font_size=4.5, bold=True)
    engine.text(30, 26, f"Type: {bridge_type.upper()} Bridge | Span: {span:.1f}m | Width: {width:.1f}m", font_size=2.8)

    # ═══ PLAN VIEW ═══
    engine.text(plan_x0, plan_y0 - 5, "PLAN VIEW", font_size=3, bold=True)

    px = plan_x0
    py = plan_y0
    pw = span * 1000 / scale
    ph = width * 1000 / scale

    # Deck outline
    engine.rect(px, py, pw, ph, fill="#e8e8e8", stroke="#333", stroke_width=0.4)

    # Girder lines (dashed)
    for i in range(1, num_girders):
        gy = py + (curb_w + i * girder_spacing) * 1000 / scale
        engine.line(px, gy, px + pw, gy, stroke="#999", stroke_width=0.2, dash="6,4")

    # Centerline
    cl_y = py + ph / 2
    engine.line(px, cl_y, px + pw, cl_y, stroke="#d00", stroke_width=0.3, dash="10,4,3,4",
                cls="center-line")

    # Pier locations
    for pier in piers:
        pier_x_px = px + (span * 0.5 + pier.get("x_pos", 0)) * 1000 / scale
        section_str = pier.get("section", "1.0x2.0m")
        pw_dim, pl_dim = [float(x.replace("m", "")) for x in section_str.split("x")]
        engine.rect(pier_x_px - pl_dim * 1000 / scale / 2,
                    py + ph * 0.5 - pw_dim * 1000 / scale / 2,
                    pl_dim * 1000 / scale, pw_dim * 1000 / scale,
                    fill="#c0c0d0", stroke="#333", stroke_width=0.3)

    # Dimensions
    engine.dimension(px, py + ph + 2, px + pw, py + ph + 2,
                     f"{span:.1f}m", offset=10, direction="h")
    engine.dimension(px - 8, py, px - 8, py + ph,
                     f"{width:.1f}m", offset=10, direction="v")

    # North arrow
    nx = px + pw + 10
    ny = py + 10
    engine.polygon([(nx, ny - 6), (nx - 3, ny + 2), (nx, ny), (nx + 3, ny + 2)],
                   fill="#d00", stroke="#d00")
    engine.text(nx, ny + 5, "N", font_size=3, fill="#d00", anchor="middle", bold=True)

    # ═══ ELEVATION VIEW ═══
    engine.text(elev_x0, elev_y0 - 5, "LONGITUDINAL ELEVATION", font_size=3, bold=True)

    ex = elev_x0
    ey = elev_y0
    ew = span * 1000 / scale

    deck_top_y = ey + clearance * 1000 / scale
    deck_bot_y = deck_top_y + (girder_depth + deck_thickness) * 1000 / scale

    # Ground line
    ground_y = deck_bot_y + clearance * 1000 / scale
    engine.line(ex - 5, ground_y, ex + ew + 5, ground_y, stroke="#693", stroke_width=0.3)
    # Ground hatch
    for gx in range(int(ex), int(ex + ew), 8):
        engine.line(gx, ground_y, gx - 5, ground_y + 8, stroke="#693", stroke_width=0.15)

    # Deck
    engine.rect(ex, deck_top_y, ew, (girder_depth + deck_thickness) * 1000 / scale,
                fill="#ccc", stroke="#333", stroke_width=0.4)

    # Girders (side view — just show depth)
    engine.rect(ex, deck_top_y + deck_thickness * 1000 / scale,
                ew, girder_depth * 1000 / scale,
                fill="#d8d8d8", stroke="#333", stroke_width=0.3)

    # Curbs
    engine.rect(ex, deck_top_y - curb_h * 1000 / scale,
                ew, curb_h * 1000 / scale,
                fill="#bbb", stroke="#333", stroke_width=0.2)

    # Piers
    for pier in piers:
        pier_x_px = ex + (span * 0.5 + pier.get("x_pos", 0)) * 1000 / scale
        pier_w_px = 1.0 * 1000 / scale
        pier_top = deck_bot_y
        pier_bot = ground_y
        engine.rect(pier_x_px - pier_w_px / 2, pier_top,
                    pier_w_px, pier_bot - pier_top,
                    fill="#c0c0d0", stroke="#333", stroke_width=0.3)

    # Dimensions
    engine.dimension(ex, deck_bot_y + 8, ex + ew, deck_bot_y + 8,
                     f"Span = {span:.1f}m", offset=10, direction="h")
    engine.dimension(ex + ew + 5, deck_top_y, ex + ew + 5, ground_y,
                     f"{pier_height:.1f}m", offset=10, direction="v")

    # ═══ CROSS-SECTION ═══
    engine.text(sect_x0, sect_y0 - 5, "CROSS-SECTION A-A", font_size=3, bold=True)

    sx = sect_x0
    sy = sect_y0
    sw = width * 1000 / scale * 1.5  # Slightly wider for detail
    sh = (pier_height + 3) * 1000 / scale

    # Deck cross-section
    deck_bot_sy = sy + 2 * 1000 / scale
    engine.rect(sx, deck_bot_sy, sw, (girder_depth + deck_thickness + curb_h) * 1000 / scale,
                fill="#ccc", stroke="#333", stroke_width=0.4)

    # Girders in cross-section (I-beam profile simplified)
    girder_w_px = (girder_depth * 0.5) * 1000 / scale  # flange width
    for i in range(num_girders):
        gx = sx + (curb_w + i * girder_spacing) * 1000 / scale - girder_w_px / 2
        # I-beam profile
        flange_t_px = (girder_depth * 0.12) * 1000 / scale
        web_t_px = (girder_depth * 0.08) * 1000 / scale
        engine.rect(gx, deck_bot_sy + deck_thickness * 1000 / scale,
                    girder_w_px, flange_t_px,  # Top flange
                    fill="#d8d8d8", stroke="#333", stroke_width=0.25)
        engine.rect(gx + girder_w_px/2 - web_t_px/2,
                    deck_bot_sy + (deck_thickness + flange_t_px) * 1000 / scale,
                    web_t_px, (girder_depth - 2 * flange_t_px) * 1000 / scale,  # Web
                    fill="#d8d8d8", stroke="#333", stroke_width=0.25)
        engine.rect(gx, deck_bot_sy + (deck_thickness + girder_depth - flange_t_px) * 1000 / scale,
                    girder_w_px, flange_t_px,  # Bottom flange
                    fill="#d8d8d8", stroke="#333", stroke_width=0.25)

    # Curbs
    engine.rect(sx, deck_bot_sy - curb_h * 1000 / scale,
                curb_w * 1000 / scale, curb_h * 1000 / scale,
                fill="#aaa", stroke="#333", stroke_width=0.2)
    engine.rect(sx + sw - curb_w * 1000 / scale, deck_bot_sy - curb_h * 1000 / scale,
                curb_w * 1000 / scale, curb_h * 1000 / scale,
                fill="#aaa", stroke="#333", stroke_width=0.2)

    # Dimensions
    engine.dimension(sx, deck_bot_sy + (girder_depth + deck_thickness) * 1000 / scale + 5,
                     sx + sw, deck_bot_sy + (girder_depth + deck_thickness) * 1000 / scale + 5,
                     f"{width:.1f}m", offset=10, direction="h")

    # Title block
    engine.title_block("GA-01", "A")

    output_path = Path(output_dir) / "GA_drawing.svg"
    engine.render(str(output_path))
    return output_path


def draw_superstructure_details(design, output_dir):
    """Generate superstructure detail drawing — girder cross-section + rebar layout."""
    super_s = design["superstructure"]
    rebar = design.get("reinforcement", {})

    girder_type = super_s.get("girder_type", "I-beam")
    girder_depth = super_s.get("girder_depth", 1.7)
    num_girders = super_s.get("num_girders", 3)
    girder_spacing = super_s.get("girder_spacing", 2.7)
    deck_thickness = super_s.get("deck_thickness", 0.225)
    flange_w = super_s.get("flange_width", 0.85)
    flange_t = super_s.get("flange_thickness", 0.21)
    web_t = super_s.get("web_thickness", 0.14)
    curb_w = super_s.get("curb_width", 0.5)
    curb_h = super_s.get("curb_height", 0.3)
    # Estimate span and width from superstructure or quantities
    span = super_s.get("span", 30)
    width = num_girders * girder_spacing + 2 * curb_w

    girder_rebar = rebar.get("girder", {})
    deck_rebar = rebar.get("deck", {})

    # Scale for 1:20 detail
    scale = 20
    engine = DrawingEngine(841, 594, scale, f"Superstructure Details — {girder_type}")

    # ═══ Title ═══
    engine.text(30, 18, "SUPERSTRUCTURE DETAILS", font_size=4.5, bold=True)
    engine.text(30, 26, f"{girder_type} Girder Section | Deck: {deck_thickness*1000:.0f}mm | "
                        f"Rebar: {girder_rebar.get('main_bars', 'N/A')}",
                font_size=2.5)

    # ═══ GIRDER CROSS-SECTION (1:20) ═══
    gx0 = 40
    gy0 = 50
    gd_px = girder_depth * 1000 / scale

    engine.text(gx0, gy0 - 5, f"GIRDER CROSS-SECTION (Scale 1:{scale})", font_size=3, bold=True)

    # I-beam profile
    gx = gx0 + 30
    gy = gy0
    fw_px = flange_w * 1000 / scale
    ft_px = flange_t * 1000 / scale
    wt_px = web_t * 1000 / scale
    gd_px = girder_depth * 1000 / scale

    # Top flange
    engine.hatch_rect(gx - fw_px/2, gy, fw_px, ft_px, "concrete")
    # Web
    engine.hatch_rect(gx - wt_px/2, gy + ft_px, wt_px, gd_px - 2*ft_px, "concrete")
    # Bottom flange
    engine.hatch_rect(gx - fw_px/2, gy + gd_px - ft_px, fw_px, ft_px, "concrete")

    # Rebar positions in girder
    cover = 50 / scale  # 50mm cover
    # Top bars
    for bx in [gx - fw_px/2 + cover * 2, gx + fw_px/2 - cover * 2]:
        engine.circle(bx, gy + ft_px/2, 3, fill="#d00", stroke="#a00")
    # Bottom bars (main reinforcement)
    n_bars = girder_rebar.get("num_bars", 8)
    bar_dia = girder_rebar.get("bar_diameter", 32)
    bar_r = bar_dia / 2 / scale
    bot_y = gy + gd_px - ft_px/2
    bar_spacing = (fw_px - 2 * cover) / (n_bars - 1) if n_bars > 1 else 0
    for i in range(n_bars):
        bx = gx - fw_px/2 + cover + i * bar_spacing
        engine.circle(bx, bot_y, bar_r, fill="#d00", stroke="#a00")

    # Stirrup outline
    stirrup_margin = cover * 0.6
    engine.rect(gx - fw_px/2 + stirrup_margin, gy + stirrup_margin,
                fw_px - 2*stirrup_margin, gd_px - 2*stirrup_margin,
                fill="none", stroke="#d00", stroke_width=0.35)

    # Girder dimensions
    engine.dimension(gx - fw_px/2, gy + gd_px + 5,
                     gx + fw_px/2, gy + gd_px + 5,
                     f"{flange_w*1000:.0f}mm", offset=10, direction="h")
    engine.dimension(gx + fw_px/2 + 5, gy, gx + fw_px/2 + 5, gy + gd_px,
                     f"{girder_depth*1000:.0f}mm", offset=10, direction="v")

    # Labels
    engine.text(gx - fw_px/2 - 15, gy + ft_px/2, f"Top flange\n{flange_t*1000:.0f}mm",
                font_size=2.2, anchor="end")
    engine.text(gx + fw_px/2 + 8, gy + gd_px/2, f"Web\n{web_t*1000:.0f}mm",
                font_size=2.2)
    engine.text(gx - fw_px/2 - 15, gy + gd_px - ft_px/2, f"Bottom flange\n{flange_t*1000:.0f}mm",
                font_size=2.2, anchor="end")

    # ═══ DECK SECTION ═══
    dx0 = gx + fw_px/2 + 40
    dy0 = gy0

    engine.text(dx0, dy0 - 5, "DECK SECTION (1:20)", font_size=3, bold=True)

    ds_width = girder_spacing * 1000 / scale * 0.8
    ds_thick = deck_thickness * 1000 / scale

    dx = dx0 + 20
    dy = dy0 + 30

    # Deck slab
    engine.hatch_rect(dx, dy, ds_width, ds_thick, "concrete")

    # Top rebar
    top_rebar_y = dy + cover
    for bx in range(int(dx + cover), int(dx + ds_width - cover), 25):
        engine.circle(bx, top_rebar_y, 1.6, fill="#d00", stroke="#a00")

    # Bottom rebar
    bot_rebar_y = dy + ds_thick - cover
    for bx in range(int(dx + cover), int(dx + ds_width - cover), 25):
        engine.circle(bx, bot_rebar_y, 1.6, fill="#d00", stroke="#a00")

    # Wearing surface
    ws_thick = 75 / scale
    engine.hatch_rect(dx, dy - ws_thick, ds_width, ws_thick, "asphalt")

    # Dimensions
    engine.dimension(dx, dy + ds_thick + 5, dx + ds_width, dy + ds_thick + 5,
                     f"{girder_spacing*1000:.0f}mm", offset=10, direction="h")
    engine.dimension(dx + ds_width + 5, dy, dx + ds_width + 5, dy + ds_thick,
                     f"{deck_thickness*1000:.0f}mm", offset=8, direction="v")

    # ═══ REINFORCEMENT SCHEDULE ═══
    sched_x = 35
    sched_y = gy + gd_px + 45
    engine.text(sched_x, sched_y, "REINFORCEMENT SCHEDULE", font_size=3.5, bold=True)

    # Table header
    col_w = [30, 100, 60, 60, 60, 60]
    col_headers = ["Mark", "Location", "Type", "Size", "Spacing", "Length"]
    row_h = 6
    table_x = sched_x
    table_y = sched_y + 5

    # Header
    x_cursor = table_x
    for i, (header, w) in enumerate(zip(col_headers, col_w)):
        engine.rect(x_cursor, table_y, w, row_h, fill="#333", stroke="none")
        engine.text(x_cursor + w/2, table_y + 4.5, header, font_size=2.2,
                    fill="#fff", anchor="middle", bold=True)
        x_cursor += w

    # Data rows
    rebar_data = [
        ["A1", "Girder Main", "HRB500", girder_rebar.get("main_bars", "N/A"), "—", f"{span:.1f}m"],
        ["A2", "Girder Stirrups", "HRB400", girder_rebar.get("stirrups", "N/A"), "—", "Per detail"],
        ["A3", "Deck Top Transverse", "HRB400", deck_rebar.get("top_transverse", "N/A"), "—", f"{width:.1f}m"],
        ["A4", "Deck Bottom Transverse", "HRB400", deck_rebar.get("bottom_transverse", "N/A"), "—", f"{width:.1f}m"],
        ["A5", "Deck Longitudinal", "HRB400", deck_rebar.get("bottom_longitudinal", "N/A"), "—", f"{span:.1f}m"],
    ]

    for i, row in enumerate(rebar_data):
        ry = table_y + row_h + i * row_h
        bg = "#fafafa" if i % 2 == 0 else "#fff"
        engine.rect(table_x, ry, sum(col_w), row_h, fill=bg, stroke="#ddd", stroke_width=0.15)
        x_cursor = table_x
        for j, (cell, w) in enumerate(zip(row, col_w)):
            engine.text(x_cursor + 2, ry + 4.5, cell, font_size=2)
            x_cursor += w

    # ═══ NOTES ═══
    notes_y = table_y + row_h + len(rebar_data) * row_h + 15
    engine.text(sched_x, notes_y, "NOTES:", font_size=2.5, bold=True)
    notes = [
        "1. All dimensions in mm unless noted otherwise.",
        "2. Concrete: C40/50 (f'c = 40 MPa), minimum cover 50mm.",
        "3. Reinforcement: HRB500 (fy = 500 MPa) for main bars, HRB400 for stirrups.",
        "4. Rebar laps: 40× bar diameter minimum. Stagger laps.",
        "5. Concrete placed monolithically; construction joints per engineer approval.",
    ]
    for i, note in enumerate(notes):
        engine.text(sched_x + 3, notes_y + 5 + i * 4, note, font_size=1.8, fill="#555")

    engine.title_block("SS-01", "A")
    output_path = Path(output_dir) / "Superstructure_drawing.svg"
    engine.render(str(output_path))
    return output_path


def draw_substructure_details(design, output_dir):
    """Generate substructure detail drawing — pier + abutment."""
    sub = design.get("substructure", {})
    piers = sub.get("piers", [])
    abutments = sub.get("abutments", [])

    scale = 25
    engine = DrawingEngine(841, 594, scale, "Substructure Details — Pier & Abutment")

    engine.text(30, 18, "SUBSTRUCTURE DETAILS", font_size=4.5, bold=True)
    engine.text(30, 26, f"Piers: {len(piers)} | Abutments: {len(abutments)} | "
                        f"Bearing: {sub.get('bearing_type', 'elastomeric')}",
                font_size=2.5)

    # ═══ PIER ELEVATION ═══
    px0 = 35
    py0 = 50
    engine.text(px0, py0 - 5, "TYPICAL PIER ELEVATION (1:25)", font_size=3, bold=True)

    if piers:
        pier = piers[0]
        ph = pier.get("height", 5.0) * 1000 / scale
        pw = 1.0 * 1000 / scale
        pl = 2.0 * 1000 / scale
        cap_w = pier.get("cap_width", 2.6) * 1000 / scale
        cap_d = pier.get("cap_depth", 0.6) * 1000 / scale

        px = px0 + 40
        py = py0 + 40

        # Ground
        engine.line(px - 20, py + ph, px + pl + 20, py + ph, stroke="#693", stroke_width=0.3)

        # Column
        engine.hatch_rect(px, py + cap_d, pl, ph - cap_d, "concrete")

        # Pier cap
        engine.hatch_rect(px - (cap_w - pl)/2, py, cap_w, cap_d, "concrete")

        # Bearing seats
        bearing_w = 0.4 * 1000 / scale
        engine.rect(px - (cap_w - pl)/2 + 5, py - 3, bearing_w, 3,
                    fill="#e44", stroke="#a33", stroke_width=0.3)
        engine.rect(px + pl - (cap_w - pl)/2 - 5 - bearing_w, py - 3, bearing_w, 3,
                    fill="#e44", stroke="#a33", stroke_width=0.3)

        # Foundation
        foundation_str = pier.get("foundation", "")
        fd_w = 3.0 * 1000 / scale
        fd_h = 0.8 * 1000 / scale
        engine.hatch_rect(px + pl/2 - fd_w/2, py + ph, fd_w, fd_h, "concrete")
        engine.line(px - 20, py + ph + fd_h, px + pl + 20, py + ph + fd_h,
                    stroke="#693", stroke_width=0.2, dash="4,2")

        # Column reinforcement hints
        for ry in range(int(py + cap_d + 5), int(py + ph), 12):
            engine.line(px + 4, ry, px + 4, ry + 5, stroke="#d00", stroke_width=0.3)
            engine.line(px + pl - 4, ry, px + pl - 4, ry + 5, stroke="#d00", stroke_width=0.3)

        # Dimensions
        engine.dimension(px - 10, py + cap_d, px - 10, py + ph,
                         f"{pier['height']:.1f}m", offset=12, direction="v")
        engine.dimension(px, py + ph + fd_h + 5,
                         px + pl, py + ph + fd_h + 5,
                         f"{2.0:.1f}m", offset=8, direction="h")

        # Pier cross-section callout
        sect_x = px + pl + 40
        sect_y = py0 + 40
        engine.text(sect_x, sect_y - 5, "SECTION B-B", font_size=2.5, bold=True)
        engine.hatch_rect(sect_x + 10, sect_y, pl * 0.8, pw * 0.8, "concrete")
        # Rebar in section
        for cx, cy in [(sect_x + 10 + 4, sect_y + 4),
                       (sect_x + 10 + pl * 0.8 - 4, sect_y + 4),
                       (sect_x + 10 + 4, sect_y + pw * 0.8 - 4),
                       (sect_x + 10 + pl * 0.8 - 4, sect_y + pw * 0.8 - 4)]:
            engine.circle(cx, cy, 2, fill="#d00", stroke="#a00")

        engine.dimension(sect_x + 10, sect_y + pw * 0.8 + 5,
                         sect_x + 10 + pl * 0.8, sect_y + pw * 0.8 + 5,
                         f"{2.0:.1f}m", offset=8, direction="h")

    # ═══ ABUTMENT ═══
    ax0 = px if piers else 60
    ay0 = py0 + max(ph + fd_h, 100) + 30 if piers else py0
    engine.text(ax0, ay0 - 5, "TYPICAL ABUTMENT (1:25)", font_size=3, bold=True)

    if abutments:
        abut = abutments[0]
        ah = abut.get("height", 5.0) * 1000 / scale
        aw = abut.get("width", 8.5) * 1000 / scale * 0.3  # Scale to fit

        ax = ax0 + 40
        ay = ay0 + 30

        # Backwall
        backwall_w = aw
        backwall_h = 1.5 * 1000 / scale
        engine.hatch_rect(ax, ay, backwall_w, backwall_h, "concrete")

        # Bearing seat
        seat_w = 0.6 * 1000 / scale
        engine.hatch_rect(ax + backwall_w/2 - seat_w/2, ay + backwall_h,
                          seat_w, 0.4 * 1000 / scale, "concrete")

        # Abutment body
        body_h = ah * 0.6
        engine.hatch_rect(ax, ay + backwall_h + 0.4 * 1000 / scale,
                          backwall_w, body_h, "concrete")

        # Foundation
        fd_w = backwall_w * 0.8
        fd_h = 0.8 * 1000 / scale
        engine.hatch_rect(ax + backwall_w/2 - fd_w/2,
                          ay + backwall_h + 0.4 * 1000 / scale + body_h,
                          fd_w, fd_h, "concrete")

        # Ground
        body_bot = ay + backwall_h + 0.4 * 1000 / scale + body_h
        engine.line(ax - 10, body_bot + fd_h, ax + backwall_w + 10, body_bot + fd_h,
                    stroke="#693", stroke_width=0.25)

        engine.dimension(ax + backwall_w + 5, ay,
                         ax + backwall_w + 5, ay + backwall_h,
                         f"1.5m", offset=8, direction="v")
        engine.dimension(ax + backwall_w + 12, ay + backwall_h,
                         ax + backwall_w + 12, body_bot + fd_h,
                         f"{ah:.1f}m", offset=8, direction="v")

    engine.title_block("SS-02", "A")
    output_path = Path(output_dir) / "Substructure_drawing.svg"
    engine.render(str(output_path))
    return output_path


def draw_bill_of_materials(design, output_dir):
    """Generate Bill of Materials and Specifications table."""
    quantities = design.get("quantities", {})
    super_s = design.get("superstructure", {})
    sub = design.get("substructure", {})

    concrete = quantities.get("concrete_m3", {})
    rebar_kg = quantities.get("rebar_kg", {})

    engine = DrawingEngine(841, 594, 1, "Bill of Materials & Specifications")

    engine.text(30, 18, "BILL OF MATERIALS & SPECIFICATIONS", font_size=5, bold=True)
    engine.text(30, 28, f"Bridge Type: {design.get('bridge_type', 'N/A').upper()} | "
                        f"Design Code: {design.get('design_code', 'N/A')}",
                font_size=2.8)

    # ═══ CONCRETE QUANTITIES TABLE ═══
    table_x = 30
    table_y = 40
    row_h = 9

    engine.text(table_x, table_y - 5, "CONCRETE QUANTITIES", font_size=3.5, bold=True)
    col_w = [140, 80, 100, 120]
    headers = ["Component", "Volume (m³)", "Grade", "Remarks"]

    # Draw table
    x_cursor = table_x
    for header, w in zip(headers, col_w):
        engine.rect(x_cursor, table_y, w, row_h, fill="#2a2a3a", stroke="none")
        engine.text(x_cursor + w/2, table_y + 6.5, header, font_size=2.5,
                    fill="#fff", anchor="middle", bold=True)
        x_cursor += w

    concrete_remarks = {
        "deck_slab": "C40, 225mm thick",
        "girders": f"{super_s.get('girder_type', 'N/A')}, C40",
        "curbs": "C30, cast-in-place",
        "piers": "C40, cast-in-place",
        "abutments": "C35, cast-in-place",
        "arch_ribs": "C50, cast-in-place",
        "spandrel_columns": "C40, cast-in-place",
    }

    for i, (comp, vol) in enumerate(concrete.items()):
        ry = table_y + row_h + i * row_h
        bg = "#f5f5f5" if i % 2 == 0 else "#fff"
        engine.rect(table_x, ry, sum(col_w), row_h, fill=bg, stroke="#ddd", stroke_width=0.15)

        remark = concrete_remarks.get(comp, "C40")
        row_data = [comp.replace("_", " ").title(), f"{vol:.1f}", "C40", remark]
        x_cursor = table_x
        for j, (cell, w) in enumerate(zip(row_data, col_w)):
            engine.text(x_cursor + 3, ry + 6.5, cell, font_size=2.2)
            x_cursor += w

    # Total row
    total_row_y = table_y + row_h + len(concrete) * row_h
    engine.rect(table_x, total_row_y, sum(col_w), row_h, fill="#dde", stroke="#333", stroke_width=0.3)
    total_conc = quantities.get("total_concrete_m3", sum(concrete.values()))
    engine.text(table_x + 3, total_row_y + 6.5, "TOTAL CONCRETE", font_size=2.5, bold=True)
    engine.text(table_x + col_w[0] + 3, total_row_y + 6.5, f"{total_conc:.1f} m³",
                font_size=2.5, bold=True)

    # ═══ REINFORCEMENT TABLE ═══
    rebar_y = total_row_y + row_h + 20
    engine.text(table_x, rebar_y - 5, "REINFORCEMENT QUANTITIES", font_size=3.5, bold=True)

    rebar_cols = [100, 120, 100, 120]
    rebar_headers = ["Bar Size", "Mass (kg)", "Length (m)", "Remarks"]

    x_cursor = table_x
    for header, w in zip(rebar_headers, rebar_cols):
        engine.rect(x_cursor, rebar_y, w, row_h, fill="#2a2a3a", stroke="none")
        engine.text(x_cursor + w/2, rebar_y + 6.5, header, font_size=2.5,
                    fill="#fff", anchor="middle", bold=True)
        x_cursor += w

    for i, (bar_size, mass) in enumerate(sorted(rebar_kg.items())):
        ry = rebar_y + row_h + i * row_h
        bg = "#f5f5f5" if i % 2 == 0 else "#fff"
        engine.rect(table_x, ry, sum(rebar_cols), row_h, fill=bg, stroke="#ddd", stroke_width=0.15)

        # Estimate length from mass
        dia = int(bar_size.replace("Φ", ""))
        mass_per_m = 0.617 if dia == 10 else (0.888 if dia == 12 else (
            1.579 if dia == 16 else (2.466 if dia == 20 else (
                3.853 if dia == 25 else (4.834 if dia == 28 else (
                    6.313 if dia == 32 else 7.990))))))
        est_length = mass / mass_per_m if mass_per_m > 0 else 0

        row_data = [bar_size, f"{mass:.0f}", f"{est_length:.0f}", "HRB500" if dia >= 25 else "HRB400"]
        x_cursor = table_x
        for j, (cell, w) in enumerate(zip(row_data, rebar_cols)):
            engine.text(x_cursor + 3, ry + 6.5, cell, font_size=2.2)
            x_cursor += w

    # Total rebar
    total_rebar_y = rebar_y + row_h + len(rebar_kg) * row_h
    engine.rect(table_x, total_rebar_y, sum(rebar_cols), row_h, fill="#dde", stroke="#333", stroke_width=0.3)
    total_rebar = quantities.get("total_rebar_kg", sum(rebar_kg.values()))
    engine.text(table_x + 3, total_rebar_y + 6.5, "TOTAL REINFORCEMENT", font_size=2.5, bold=True)
    engine.text(table_x + rebar_cols[0] + 3, total_rebar_y + 6.5,
                f"{total_rebar:.0f} kg ({total_rebar/1000:.1f} tonnes)", font_size=2.5, bold=True)

    # ═══ OTHER MATERIALS ═══
    other_y = total_rebar_y + row_h + 20
    engine.text(table_x, other_y - 5, "OTHER MATERIALS & COMPONENTS", font_size=3.5, bold=True)

    other_cols = [200, 120, 120]
    other_headers = ["Item", "Quantity", "Unit"]

    x_cursor = table_x
    for header, w in zip(other_headers, other_cols):
        engine.rect(x_cursor, other_y, w, row_h, fill="#2a2a3a", stroke="none")
        engine.text(x_cursor + w/2, other_y + 6.5, header, font_size=2.5,
                    fill="#fff", anchor="middle", bold=True)
        x_cursor += w

    other_items = [
        ("Asphalt Wearing Surface", f"{quantities.get('asphalt_m3', 0):.1f} m³", "—"),
        ("Formwork", f"{quantities.get('formwork_m2', 0):.0f} m²", "—"),
        ("Bearings", f"{quantities.get('bearings_count', 0)} units",
         sub.get('bearing_type', 'elastomeric')),
        ("Expansion Joints", f"{quantities.get('expansion_joints_m', 0):.1f}m", "Strip seal type"),
        ("Drainage System", f"{max(2, int(30/15))} units", "Deck drains"),
        ("Bridge Railing", f"{30*2:.0f}m", "Steel barrier, H=1.1m"),
    ]

    for i, (item, qty, unit) in enumerate(other_items):
        ry = other_y + row_h + i * row_h
        bg = "#f5f5f5" if i % 2 == 0 else "#fff"
        engine.rect(table_x, ry, sum(other_cols), row_h, fill=bg, stroke="#ddd", stroke_width=0.15)
        engine.text(table_x + 3, ry + 6.5, item, font_size=2.2)
        engine.text(table_x + other_cols[0] + 3, ry + 6.5, qty, font_size=2.2)
        engine.text(table_x + other_cols[0] + other_cols[1] + 3, ry + 6.5, unit, font_size=2.2)

    # ═══ SPECIFICATIONS ═══
    spec_x = table_x + sum(other_cols) + 30
    spec_y = 40
    engine.text(spec_x, spec_y, "MATERIAL SPECIFICATIONS", font_size=3.5, bold=True)

    specs = [
        ("Concrete", [
            "Deck/Girders: C40/50 (f'c=40 MPa)",
            "Piers/Abutments: C40/50",
            "Wearing surface: Asphalt AC-20",
            "Cover: 50mm (deck), 75mm (piers)",
        ]),
        ("Reinforcement", [
            "Main bars: HRB500 (fy=500 MPa)",
            "Stirrups: HRB400 (fy=400 MPa)",
            "Welded wire fabric: per ASTM A1064",
            "Lap splice: Class B, 1.3×Ld",
        ]),
        ("Bearings", [
            f"Type: {sub.get('bearing_type', 'laminated elastomeric')}",
            "Design per AASHTO LRFD §14",
            "Elastomer: neoprene (60 durometer)",
            "Stainless steel sliding surface",
        ]),
        ("Construction", [
            "Cast-in-place concrete",
            "Formwork: steel forms for girders",
            "Falsework: design per contractor",
            "Curing: 7 days minimum",
        ]),
    ]

    sy = spec_y + 8
    for section_title, items in specs:
        engine.text(spec_x, sy, section_title, font_size=2.5, bold=True)
        sy += 6
        for item in items:
            engine.text(spec_x + 5, sy, f"• {item}", font_size=2.0, fill="#444")
            sy += 4.5
        sy += 5

    engine.title_block("BOM-01", "A")
    output_path = Path(output_dir) / "BOM_table.svg"
    engine.render(str(output_path))
    return output_path


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Generate professional bridge construction drawings"
    )
    parser.add_argument("design", help="Path to detailed_design.json")
    parser.add_argument("--output-dir", "-o", default="./drawings",
                        help="Output directory for SVG drawings")
    parser.add_argument("--all", action="store_true", default=True,
                        help="Generate all drawings (default)")
    parser.add_argument("--sheets", "-s", default="GA,Super,Sub,BOM",
                        help="Comma-separated sheet codes: GA,Super,Sub,BOM")
    args = parser.parse_args()

    # Load design
    with open(args.design, "r") as f:
        design = json.load(f)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    sheets = [s.strip() for s in args.sheets.split(",")]

    print("=" * 60)
    print("Bridge Construction Drawing Generator")
    print("=" * 60)
    print(f"Design: {args.design}")
    print(f"Bridge type: {design.get('bridge_type', 'N/A')}")
    print(f"Output: {output_dir}")
    print()

    generated = []

    if "GA" in sheets or args.all:
        print("[1/4] General Arrangement...")
        p = draw_general_arrangement(design, output_dir)
        generated.append(p)

    if "Super" in sheets or args.all:
        print("[2/4] Superstructure Details...")
        p = draw_superstructure_details(design, output_dir)
        generated.append(p)

    if "Sub" in sheets or args.all:
        print("[3/4] Substructure Details...")
        p = draw_substructure_details(design, output_dir)
        generated.append(p)

    if "BOM" in sheets or args.all:
        print("[4/4] Bill of Materials & Specifications...")
        p = draw_bill_of_materials(design, output_dir)
        generated.append(p)

    print(f"\n{'=' * 60}")
    print(f"Generated {len(generated)} drawing sheets:")
    for p in generated:
        print(f"  → {p}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
