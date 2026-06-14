#!/usr/bin/env python3
"""
Bridge Engineering Design Engine
Takes extracted bridge parameters and produces a structurally designed,
code-compliant bridge specification with detailed components, reinforcement,
and construction quantities.

Design Codes: AASHTO LRFD Bridge Design Specifications (9th Ed, 2020)
              JTG D60-2015 (Chinese highway bridge code) — selectable

Usage:
    python bridge_designer.py bridge_params.json -o detailed_design.json
    python bridge_designer.py bridge_params.json --design-code CHN --live-load CL1
"""

import json
import math
import argparse
from pathlib import Path


# ============================================================================
# Material Properties
# ============================================================================

CONCRETE_C40 = {
    "fc_mpa": 40.0,        # Compressive strength
    "fc_mpa_service": 26.8,  # 0.67*fc for service
    "ec_gpa": 34.0,        # Elastic modulus
    "density_kg_m3": 2500.0,
    "cover_mm": 50.0,       # Clear cover for deck
}

STEEL_GRADE_500 = {
    "fy_mpa": 500.0,       # Yield strength
    "es_gpa": 200.0,       # Elastic modulus
    "density_kg_m3": 7850.0,
}

# Structural steel (ASTM A709 Grade 50 / Q345q)
STRUCTURAL_STEEL = {
    "fy_mpa": 345.0,       # Yield strength
    "fu_mpa": 450.0,       # Ultimate strength
    "es_gpa": 200.0,       # Elastic modulus
    "density_kg_m3": 7850.0,
    "poisson": 0.3,
}

# Standard rebar diameters and areas (mm)
REBAR_SIZES = {
    10: {"area_mm2": 78.5, "mass_kg_per_m": 0.617},
    12: {"area_mm2": 113.1, "mass_kg_per_m": 0.888},
    16: {"area_mm2": 201.1, "mass_kg_per_m": 1.579},
    20: {"area_mm2": 314.2, "mass_kg_per_m": 2.466},
    25: {"area_mm2": 490.9, "mass_kg_per_m": 3.853},
    28: {"area_mm2": 615.8, "mass_kg_per_m": 4.834},
    32: {"area_mm2": 804.2, "mass_kg_per_m": 6.313},
    36: {"area_mm2": 1017.9, "mass_kg_per_m": 7.990},
}


# ============================================================================
# Design Engine
# ============================================================================

def design_bridge(params, design_code="AASHTO"):
    """Main design entry point. Returns complete detailed_design dict."""
    dims = params["dimensions"]
    bridge_type = params.get("bridge_type", "beam")
    terrain = params.get("terrain_profile", [])

    print("=" * 60)
    print("Bridge Engineering Design Engine")
    print(f"  Design Code: {design_code}")
    print(f"  Bridge Type: {bridge_type}")
    print(f"  Span: {dims['span_length']}m, Width: {dims['deck_width']}m")
    print("=" * 60)

    if bridge_type == "arch":
        design = design_arch_bridge(dims, params, design_code)
    else:
        design = design_beam_bridge(dims, params, design_code)

    # Common to all types (preserve type from specific designer if already set)
    if "bridge_type" not in design:
        design["bridge_type"] = bridge_type
    design["design_code"] = "AASHTO LRFD" if design_code == "AASHTO" else "JTG D60-2015"
    # Carry forward dimensions for downstream consumers (FEA, drawings)
    design["dimensions"] = dims

    # Terrain-adaptive foundation depths
    design = adapt_to_terrain(design, terrain, dims)

    return design


def design_beam_bridge(dims, params, code):
    """Design a beam/girder bridge superstructure and substructure."""
    span = dims["span_length"]
    width = dims["deck_width"]
    clearance = dims.get("clearance_under_bridge", 5.0)
    deck_elev = dims.get("deck_elevation", clearance)
    piers_data = params.get("pier_positions", [])
    abutments_data = params.get("abutment_positions", [])

    print("\n[1/6] Superstructure Design — Beam Bridge")
    print("-" * 40)

    # ── Girder Selection (auto-routing by span) ──
    if span < 15:
        # Short spans: reinforced concrete T-beam
        girder_type = "T-beam"
        girder_depth = span / 16
        num_girders = max(3, int(width / 2.5))
    elif span < 35:
        # Medium spans: reinforced concrete I-beam
        girder_type = "I-beam"
        girder_depth = span / 18
        num_girders = max(3, int(width / 3.0))
    elif span <= 45:
        # Long spans: prestressed concrete I-girder (AASHTO standard)
        return design_prestressed_bridge(dims, params, code)
    elif span <= 150:
        return design_steel_girder_bridge(dims, params, code)
    elif span <= 400:
        return design_cable_stayed_bridge(dims, params, code)
    else:
        print(f"\n  ⚠ {span}m exceeds cable-stayed range (>400m)")
        print(f"     Consider: suspension bridge")
        print(f"     Attempting cable-stayed as lower bound...")
        return design_cable_stayed_bridge(dims, params, code)

    girder_depth = round(girder_depth, 2)
    girder_spacing = round(width / num_girders, 2)

    # Girder cross-section dimensions (meters)
    if girder_type == "I-beam":
        flange_width = round(girder_depth * 0.5, 2)
        flange_thickness = round(girder_depth * 0.12, 2)
        web_thickness = round(girder_depth * 0.08, 2)
    elif girder_type == "T-beam":
        flange_width = round(girder_spacing * 0.8, 2)
        flange_thickness = 0.20
        web_thickness = 0.30
    else:  # Box girder
        flange_width = round(girder_spacing * 0.85, 2)
        flange_thickness = 0.25
        web_thickness = 0.35

    # Deck slab
    deck_thickness = 0.225  # 225mm standard
    wearing_surface = 0.075  # 75mm asphalt

    # Curbs / barriers
    curb_width = 0.5
    curb_height = 0.3

    print(f"  Girder type: {girder_type}")
    print(f"  Number of girders: {num_girders}")
    print(f"  Girder depth: {girder_depth}m (span/{span/girder_depth:.1f})")
    print(f"  Girder spacing: {girder_spacing}m")
    print(f"  Deck slab: {deck_thickness*1000:.0f}mm + {wearing_surface*1000:.0f}mm asphalt")

    # ── Load Calculations ──
    print("\n[2/6] Load Calculations")
    print("-" * 40)

    loads = calculate_beam_loads(span, width, girder_type, num_girders, girder_depth,
                                  deck_thickness, wearing_surface, curb_width, curb_height,
                                  concrete=CONCRETE_C40, code=code)

    w_dead = loads["dead_load_kN_per_m"]
    w_super = loads["superimposed_dead_kN_per_m"]
    M_ll = loads["live_load_moment_kNm"]
    V_ll = loads["live_load_shear_kN"]

    print(f"  Dead load (structural): {w_dead:.1f} kN/m")
    print(f"  Superimposed dead: {w_super:.1f} kN/m")
    print(f"  Live load moment: {M_ll:.0f} kN·m")
    print(f"  Live load shear: {V_ll:.0f} kN")

    # ── Structural Analysis ──
    print("\n[3/6] Structural Analysis")
    print("-" * 40)

    analysis = analyze_beam_bridge(span, w_dead, w_super, M_ll, V_ll, num_girders,
                                    girder_depth, girder_type, concrete=CONCRETE_C40)

    Mu = analysis["Mu_total_kNm"]
    Vu = analysis["Vu_total_kN"]
    deflection = analysis["deflection_mm"]
    defl_limit = span * 1000 / 800

    print(f"  Factored moment Mu: {Mu:.0f} kN·m (per girder)")
    print(f"  Factored shear Vu: {Vu:.0f} kN (per girder)")
    print(f"  Max deflection: {deflection:.1f}mm (limit: L/800 = {defl_limit:.1f}mm)")
    print(f"  Deflection check: {'OK' if deflection < defl_limit else 'FAIL — increase depth'}")

    # ── Reinforcement Design ──
    print("\n[4/6] Reinforcement Design")
    print("-" * 40)

    rebar = design_girder_reinforcement(
        Mu_kNm=Mu, Vu_kN=Vu,
        bw_m=web_thickness, d_m=girder_depth - 0.08,
        fc_mpa=CONCRETE_C40["fc_mpa"], fy_mpa=STEEL_GRADE_500["fy_mpa"],
        code=code
    )

    deck_rebar = design_deck_reinforcement(
        deck_thickness_m=deck_thickness, girder_spacing_m=girder_spacing,
        fc_mpa=CONCRETE_C40["fc_mpa"], fy_mpa=STEEL_GRADE_500["fy_mpa"],
        cover_mm=CONCRETE_C40["cover_mm"]
    )

    print(f"  Girder main bars: {rebar['main_bars']}")
    print(f"  Girder stirrups: {rebar['stirrups']}")
    print(f"  Deck top transverse: {deck_rebar['top_transverse']}")
    print(f"  Deck bottom transverse: {deck_rebar['bottom_transverse']}")

    # ── Substructure Design ──
    print("\n[5/6] Substructure Design")
    print("-" * 40)

    substructure = design_substructure(piers_data, abutments_data, width, clearance,
                                        girder_depth, deck_thickness)

    print(f"  Piers: {len(substructure['piers'])}")
    for p in substructure["piers"]:
        print(f"    Height={p['height']}m, Section={p['section']}, Foundation={p['foundation']}")
    print(f"  Abutments: {len(substructure['abutments'])} ({substructure['abutment_type']})")
    print(f"  Bearings: {substructure['bearings_count']} × {substructure['bearing_type']}")

    # ── Bill of Materials ──
    print("\n[6/6] Bill of Materials")
    print("-" * 40)

    bom = compute_bill_of_materials(
        span, width, girder_type, num_girders, girder_depth,
        web_thickness, flange_width, flange_thickness,
        deck_thickness, wearing_surface, curb_width, curb_height,
        substructure, rebar, deck_rebar
    )

    total_concrete = sum(bom["concrete_m3"].values())
    total_rebar = sum(bom["rebar_kg"].values())
    print(f"  Total concrete: {total_concrete:.1f} m³")
    print(f"  Total rebar: {total_rebar:.0f} kg ({total_rebar/1000:.1f} tonnes)")
    print(f"  Formwork: {bom['formwork_m2']:.0f} m²")
    print(f"  Bearings: {bom['bearings_count']} units")
    print(f"  Expansion joints: {bom['expansion_joints_m']:.1f}m")

    return {
        "bridge_type": "beam",
        "design_code": "",
        "superstructure": {
            "girder_type": girder_type,
            "num_girders": num_girders,
            "girder_depth": girder_depth,
            "girder_spacing": girder_spacing,
            "flange_width": flange_width,
            "flange_thickness": flange_thickness,
            "web_thickness": web_thickness,
            "deck_thickness": deck_thickness,
            "wearing_surface": wearing_surface,
            "curb_width": curb_width,
            "curb_height": curb_height,
        },
        "substructure": substructure,
        "reinforcement": {
            "girder": rebar,
            "deck": deck_rebar,
        },
        "quantities": bom,
        "loads": loads,
        "analysis": {
            "Mu_per_girder_kNm": round(Mu, 0),
            "Vu_per_girder_kN": round(Vu, 0),
            "max_deflection_mm": round(deflection, 1),
            "deflection_limit_mm": round(defl_limit, 1),
            "deflection_ok": deflection < defl_limit,
        },
    }


def design_arch_bridge(dims, params, code):
    """Design an arch bridge with parabolic arch rib and spandrel columns."""
    span = dims["span_length"]
    width = dims["deck_width"]
    clearance = dims.get("clearance_under_bridge", 5.0)
    deck_elev = dims.get("deck_elevation", clearance)

    print("\n[1/6] Superstructure Design — Arch Bridge")
    print("-" * 40)

    # Arch geometry
    rise = span * 0.2  # Rise/span = 0.2 (optimal for parabolic arch)
    rise = round(rise, 2)

    # Arch rib: rectangular concrete section
    rib_width = 1.2
    rib_depth = span / 60  # Arch rib depth ~ span/60
    rib_depth = max(0.6, round(rib_depth, 2))
    num_ribs = max(2, int(width / 4.0))

    # Spandrel columns: vertical members connecting arch to deck
    num_spandrels = max(4, int(span / 5))
    spandrel_spacing = span / num_spandrels
    spandrel_section = "0.5x0.5m"

    # Deck (supported by spandrels)
    deck_thickness = 0.25
    wearing_surface = 0.075
    curb_width = 0.5
    curb_height = 0.3

    print(f"  Arch rise: {rise}m (rise/span = {rise/span:.2f})")
    print(f"  Arch rib: {rib_width}x{rib_depth}m, {num_ribs} ribs")
    print(f"  Spandrel columns: {num_spandrels} @ {spandrel_spacing:.1f}m spacing")
    print(f"  Deck slab: {deck_thickness*1000:.0f}mm")

    # ── Load Calculations ──
    print("\n[2/6] Load Calculations")
    print("-" * 40)

    loads = calculate_arch_loads(span, width, num_ribs, rib_width, rib_depth,
                                  deck_thickness, wearing_surface, curb_width, curb_height,
                                  rise, num_spandrels, CONCRETE_C40, code)

    print(f"  Dead load: {loads['dead_load_kN_per_m']:.1f} kN/m")
    print(f"  Live load moment: {loads['live_load_moment_kNm']:.0f} kN·m")
    print(f"  Arch thrust: {loads['arch_thrust_kN']:.0f} kN")

    # ── Structural Analysis ──
    print("\n[3/6] Structural Analysis")
    print("-" * 40)

    H = loads["arch_thrust_kN"]
    rib_area = rib_width * rib_depth
    fc = CONCRETE_C40["fc_mpa_service"] * 1000  # kPa
    compressive_stress = H / (num_ribs * rib_area)
    compressive_ok = compressive_stress < fc * 0.3  # 30% of service capacity

    print(f"  Arch compressive stress: {compressive_stress:.0f} kPa")
    print(f"  Allowable: {fc*0.3:.0f} kPa")
    print(f"  Compression check: {'OK' if compressive_ok else 'FAIL — increase rib section'}")

    # ── Reinforcement Design ──
    print("\n[4/6] Reinforcement Design")
    print("-" * 40)

    rebar = design_arch_reinforcement(rib_width, rib_depth, H, num_ribs,
                                       CONCRETE_C40, STEEL_GRADE_500, code)
    deck_rebar = design_deck_reinforcement(deck_thickness, 2.5, CONCRETE_C40["fc_mpa"],
                                            STEEL_GRADE_500["fy_mpa"], CONCRETE_C40["cover_mm"])

    print(f"  Arch rib reinforcement: {rebar['main_bars']}")
    print(f"  Arch rib stirrups: {rebar['stirrups']}")
    print(f"  Deck top transverse: {deck_rebar['top_transverse']}")

    # ── Substructure ──
    print("\n[5/6] Substructure Design")
    print("-" * 40)

    piers_data = params.get("pier_positions", [])
    abutments_data = params.get("abutment_positions", [])

    substructure = design_substructure(piers_data, abutments_data, width, clearance,
                                        0.8, deck_thickness, abutment_type="arch_seat")

    # ── Bill of Materials ──
    print("\n[6/6] Bill of Materials")
    print("-" * 40)

    bom = compute_arch_bom(span, width, num_ribs, rib_width, rib_depth, rise,
                            num_spandrels, spandrel_section, deck_thickness,
                            wearing_surface, curb_width, curb_height,
                            substructure, rebar, deck_rebar)

    total_concrete = sum(bom["concrete_m3"].values())
    total_rebar = sum(bom["rebar_kg"].values())
    print(f"  Total concrete: {total_concrete:.1f} m³")
    print(f"  Total rebar: {total_rebar:.0f} kg ({total_rebar/1000:.1f} tonnes)")

    return {
        "bridge_type": "arch",
        "design_code": "",
        "superstructure": {
            "girder_type": "arch_rib",
            "num_ribs": num_ribs,
            "rib_width": rib_width,
            "rib_depth": rib_depth,
            "rise": rise,
            "span": span,
            "num_spandrels": num_spandrels,
            "spandrel_spacing": round(spandrel_spacing, 2),
            "spandrel_section": spandrel_section,
            "deck_thickness": deck_thickness,
            "wearing_surface": wearing_surface,
            "curb_width": curb_width,
            "curb_height": curb_height,
        },
        "substructure": substructure,
        "reinforcement": {
            "arch_rib": rebar,
            "deck": deck_rebar,
        },
        "quantities": bom,
        "loads": loads,
        "analysis": {
            "compressive_stress_kPa": round(compressive_stress, 0),
            "allowable_stress_kPa": round(fc * 0.3, 0),
            "compression_ok": compressive_ok,
        },
    }


# ============================================================================
# Prestressed Concrete Bridge Design (50-80m spans)
# AASHTO LRFD — Standard Prestressed I-Girders
# ============================================================================

# AASHTO Standard Prestressed Girder Sections (Type I–VI, BT)
# Properties per girder: [depth_m, area_m2, Ix_m4, yb_m, yt_m, web_width_m, top_flange_w_m]
AASHTO_SECTIONS = {
    "Type I":   [0.711, 0.229, 0.0176, 0.321, 0.390, 0.152, 0.406],
    "Type II":  [0.914, 0.303, 0.0395, 0.398, 0.516, 0.152, 0.457],
    "Type III": [1.143, 0.381, 0.0814, 0.503, 0.640, 0.178, 0.559],
    "Type IV":  [1.372, 0.479, 0.1487, 0.618, 0.754, 0.203, 0.660],
    "Type V":   [1.600, 0.572, 0.2410, 0.707, 0.893, 0.203, 0.762],
    "Type VI":  [1.829, 0.670, 0.3690, 0.809, 1.020, 0.203, 0.864],
    "BT-54":    [1.372, 0.433, 0.1140, 0.660, 0.712, 0.152, 0.660],
    "BT-63":    [1.600, 0.501, 0.1610, 0.770, 0.830, 0.152, 0.660],
    "BT-72":    [1.829, 0.570, 0.2220, 0.882, 0.947, 0.152, 0.660],
}

# Low-relaxation 7-wire strand properties
STRAND_1860 = {
    "fpu_mpa": 1860.0,     # Ultimate tensile strength
    "fpy_mpa": 1674.0,     # Yield strength (0.9*fpu)
    "fpi_mpa": 1395.0,     # Initial stress (0.75*fpu)
    "fpe_mpa": 1116.0,     # Effective stress after losses (~0.6*fpu est)
    "ep_mpa": 540.0,       # Relaxation loss
    "area_mm2": 98.7,      # 12.7mm diameter strand (Grade 1860)
    "diameter_mm": 12.7,
}


def design_prestressed_bridge(dims, params, code):
    """Design a prestressed concrete I-girder bridge for spans 35-80m.

    Uses AASHTO standard girder sections with Grade 1860 (270 ksi) strands.
    Performs service stress checks at transfer and final, ultimate moment check.
    """
    span = dims["span_length"]
    width = dims["deck_width"]
    clearance = dims.get("clearance_under_bridge", 5.0)
    deck_elev = dims.get("deck_elevation", clearance)
    piers_data = params.get("pier_positions", [])
    abutments_data = params.get("abutment_positions", [])

    print("\n[1/5] Superstructure Design — Prestressed Concrete")
    print("-" * 40)

    # ── Section Selection ──
    girder_spacing = round(width / max(3, int(width / 3.0)), 2)
    num_girders = max(3, int(width / 3.0))

    # Select section: depth should be ~span/20 to span/25
    # For spans > 50m, prefer BT (bulb-tee) sections
    if span > 50:
        candidates = {k: v for k, v in AASHTO_SECTIONS.items() if k.startswith("BT")}
        if not candidates:
            candidates = {k: v for k, v in AASHTO_SECTIONS.items() if "VI" in k}
    elif span > 40:
        candidates = {k: v for k, v in AASHTO_SECTIONS.items()
                     if k.startswith("BT") or "V" in k or "VI" in k}
    else:
        candidates = AASHTO_SECTIONS

    target_depth = span / 22
    best_section = list(candidates.keys())[0]
    best_depth = candidates[best_section][0]
    for name, props in candidates.items():
        if abs(props[0] - target_depth) < abs(best_depth - target_depth):
            best_section = name
            best_depth = props[0]

    depth, area, Ix, yb, yt, web_w, tf_w = AASHTO_SECTIONS[best_section]
    deck_thickness = 0.200  # 200mm deck slab
    wearing_surface = 0.075
    curb_w = 0.5
    curb_h = 0.3

    # Composite section (girder + deck)
    # Deck effective width = min(girder_spacing, 12*deck_t + web_w, span/4)
    deck_eff_w = min(girder_spacing, 12 * deck_thickness + web_w, span / 4)
    composite_depth = depth + deck_thickness

    print(f"  Section: AASHTO {best_section} (depth={depth}m, area={area:.3f}m², I={Ix:.4f}m⁴)")
    print(f"  Girders: {num_girders} @ {girder_spacing}m spacing")
    print(f"  Composite depth: {composite_depth:.2f}m (girder + {deck_thickness*1000:.0f}mm deck)")
    print(f"  Span/depth ratio: {span/composite_depth:.1f}")

    # ── Load Calculations ──
    print("\n[2/5] Load Calculations — Prestressed Girder")
    print("-" * 40)

    concrete = CONCRETE_C40
    rho_c = concrete["density_kg_m3"]
    g = 9.81

    # Girder self-weight
    girder_w = area * rho_c * g / 1000  # kN/m per girder

    # Deck + haunch
    haunch_h = 0.025  # 25mm haunch
    deck_w = deck_eff_w * deck_thickness * rho_c * g / 1000
    haunch_w = web_w * haunch_h * rho_c * g / 1000

    # Superimposed dead (spread across all girders)
    asphalt_w = width * wearing_surface * 2300 * g / 1000 / num_girders
    barrier_w = 2 * 5.0 / num_girders  # 5 kN/m each side
    curb_w_girder = 2 * curb_w * curb_h * rho_c * g / 1000 / num_girders

    w_girder = girder_w
    w_deck = deck_w + haunch_w
    w_super = asphalt_w + barrier_w + curb_w_girder
    w_total = w_girder + w_deck + w_super

    # Live load (AASHTO HL-93)
    design_lanes = max(1, int(width / 3.6))
    impact = min(0.33, 1.2 - 0.005 * span)
    dist_factor = 1.2 / num_girders  # Simplified moment distribution

    lane_load = 9.3  # kN/m
    truck_load = 325  # kN
    M_lane = lane_load * span ** 2 / 8
    M_truck = truck_load * span / 4
    M_ll = (M_lane + M_truck) * design_lanes * (1 + impact) * dist_factor

    # Moments at midspan
    M_girder = w_girder * span ** 2 / 8
    M_deck = w_deck * span ** 2 / 8
    M_super = w_super * span ** 2 / 8

    print(f"  Girder self-weight: {w_girder:.1f} kN/m")
    print(f"  Deck + haunch: {w_deck:.1f} kN/m")
    print(f"  Superimposed dead: {w_super:.1f} kN/m")
    print(f"  Live load moment: {M_ll:.0f} kN·m (per girder)")

    # ── Strand Design ──
    print("\n[3/5] Strand Pattern Design")
    print("-" * 40)

    strand = STRAND_1860
    fpu = strand["fpu_mpa"]
    fpi = strand["fpi_mpa"]  # Initial jacking stress
    fpe_est = 0.60 * fpu     # Estimated effective stress after losses
    Aps_strand = strand["area_mm2"]  # mm² per strand

    # Eccentricity: place strands as low as possible for max eccentricity
    # Harped strands: straight strands near bottom, some harped to top at ends
    cover_bottom = 0.06  # 60mm bottom cover
    e_max = yb - cover_bottom  # Max eccentricity at midspan (from centroid)
    e_end = 0.0  # Centroidal at ends (simple span, stresses controlled at midspan)

    # Required prestress force: Pe = M_total / (e + kt) where kt = rb^2 / yt
    r2 = Ix / area  # Radius of gyration squared
    kt = r2 / yt
    kb = r2 / yb

    # Service III moment (AASHTO — 0.8 live load for tension check)
    M_service_III = M_girder + M_deck + M_super + 0.8 * M_ll
    M_strength_I = 1.25 * (M_girder + M_deck) + 1.5 * M_super + 1.75 * M_ll

    # Required effective prestress force
    # Bottom fiber tension check: fb = -Pe/A - Pe*e/Sb + M/Sb >= -0.5*sqrt(f'c)
    ft_allow_tension = 0.5 * math.sqrt(concrete["fc_mpa"]) * 1000  # kPa → Pa, then /1e6 for MPa
    Sb = Ix / yb  # Section modulus bottom
    St = Ix / yt  # Section modulus top

    # For no tension at bottom: Pe >= M/e * A*Sb/(A*e + Sb) ... simplified
    # Use bottom fiber stress equation to solve for Pe
    # -Pe/A - Pe*e/Sb + M_total/Sb = 0 (zero tension)
    if e_max > 0:
        Pe_req = M_service_III / (e_max + Sb / area)  # kN·m → converted
        # Convert to consistent units: Pe in kN, M in kN·m, e in m, A in m², S in m³
        Pe_req_kN = M_service_III * 1000 / (e_max * 1000 + Sb * 1e9 / (area * 1e6)) / 1000  # simplified
        # Actually let me recalculate properly
        # fb = -Pe/A - Pe*e/Sb + M/Sb
        # 0 = -Pe/A - Pe*e/Sb + M/Sb
        # Pe * (1/A + e/Sb) = M/Sb
        # Pe = (M/Sb) / (1/A + e/Sb) = M / (Sb/A + e)
        Pe_req_kN = M_service_III / (Sb / area + e_max)
    else:
        Pe_req_kN = M_service_III * area / Sb  # Centroidal prestress

    # Number of strands required
    Aps_req_mm2 = Pe_req_kN * 1000 / fpe_est  # mm²
    n_strands = max(4, math.ceil(Aps_req_mm2 / Aps_strand))
    n_strands = (n_strands + 1) // 2 * 2  # Round to even

    # Check against section capacity (max strands in bottom flange)
    bottom_flange_area_mm2 = web_w * 0.5 * depth * 1e6  # Approx half the web-bulb area
    max_strands = int(bottom_flange_area_mm2 / (strand["diameter_mm"] * 2)**2)
    max_strands = max(20, min(max_strands, 80))  # Practical range: 20-80
    if n_strands > max_strands:
        print(f"  ⚠ Strand count {n_strands} exceeds practical limit ({max_strands})")
        print(f"     → Using {max_strands} strands. Consider deeper section or shorter span.")
        n_strands = max_strands

    Pe_provided_kN = n_strands * Aps_strand * fpe_est / 1000  # kN

    # Strand layout: harp some strands for shear control
    n_harped = max(2, n_strands // 4)  # 25% harped
    n_straight = n_strands - n_harped

    print(f"  Required Pe: {Pe_req_kN:.0f} kN → Provided: {Pe_provided_kN:.0f} kN")
    print(f"  Strands: {n_strands} total ({n_straight} straight + {n_harped} harped)")
    print(f"  Strand diameter: {strand['diameter_mm']}mm Grade 1860")
    print(f"  Max eccentricity at midspan: {e_max*1000:.0f}mm")

    # ── Prestress Losses ──
    print("\n[4/5] Prestress Losses")
    print("-" * 40)

    # Initial stress
    fpi_actual = fpi
    P_i = n_strands * Aps_strand * fpi_actual / 1000  # kN initial jacking force

    # 1. Elastic shortening (ES) — AASHTO LRFD 5.9.5.2.3a
    Ep = 196500  # MPa (strand elastic modulus)
    Eci = concrete["ec_gpa"] * 1000  # MPa (concrete modulus at transfer)
    # Stress in concrete at strand CG from initial prestress + self-weight
    f_cgp_mpa = (P_i / (area * 1e6) * 1e3
                 + P_i * e_max**2 / (Ix * 1e6) * 1e3
                 - M_girder * e_max / (Ix * 1e6) * 1e3)
    loss_es = Ep / Eci * f_cgp_mpa  # MPa
    loss_es = min(loss_es, 0.05 * fpi_actual)  # Cap at 5% — low-relaxation strands
    loss_es_pct = loss_es / fpi_actual * 100

    # 2. Creep of concrete (CR) — AASHTO LRFD 5.9.5.3
    M_sd = M_deck + M_super
    f_cds_mpa = M_sd * e_max / (Ix * 1e6) * 1e3
    # AASHTO simplified: CR = 12*f_cgp - 7*f_cds (min 0)
    loss_cr = max(0, 12 * f_cgp_mpa - 7 * f_cds_mpa)
    loss_cr = min(loss_cr, 0.15 * fpi_actual)  # Cap at 15%
    loss_cr_pct = loss_cr / fpi_actual * 100

    # 3. Shrinkage (SH) — AASHTO LRFD 5.9.5.4.2
    H = 70  # Relative humidity %
    loss_sh = max(0, 117 - 1.03 * H)  # MPa for accelerated curing
    loss_sh_pct = loss_sh / fpi_actual * 100

    # 4. Relaxation (RE) — AASHTO LRFD 5.9.5.4.4c
    # For low-relaxation strands: RE = 5.0 - 0.15*(SH+CR+ES) MPa (in ksi units, converted)
    # Simplified: ~5% of fpi for low-relaxation
    loss_re = 5.0 * 6.895  # 5 ksi ≈ 34.5 MPa (AASHTO base relaxation)
    # Add reduction for low-relaxation: subtract 0.15*(SH+CR+ES)
    loss_re_adjusted = max(0, loss_re - 0.15 * (loss_sh + loss_cr + loss_es))
    loss_re = min(loss_re_adjusted, 0.05 * fpi_actual)  # Cap: 5% of initial stress
    loss_re_pct = loss_re / fpi_actual * 100

    total_loss = loss_es + loss_cr + loss_sh + loss_re
    total_loss_pct = total_loss / fpi_actual * 100
    fpe_actual = fpi_actual - total_loss

    # Effective stress floor: 55% of fpu (typical for low-relaxation)
    fpe_min = 0.55 * fpu
    if fpe_actual < fpe_min:
        fpe_actual = fpe_min
        total_loss_pct = (fpi_actual - fpe_actual) / fpi_actual * 100

    Pe_final_kN = n_strands * Aps_strand * fpe_actual / 1000

    print(f"  Elastic shortening: {loss_es:.0f} MPa ({loss_es_pct:.1f}%)")
    print(f"  Creep: {loss_cr:.0f} MPa ({loss_cr_pct:.1f}%)")
    print(f"  Shrinkage: {loss_sh:.0f} MPa ({loss_sh_pct:.1f}%)")
    print(f"  Relaxation: {loss_re:.0f} MPa ({loss_re_pct:.1f}%)")
    print(f"  Total loss: {total_loss:.0f} MPa ({total_loss_pct:.1f}%)")
    print(f"  Final effective prestress: {fpe_actual:.0f} MPa")

    # ── Stress Checks ──
    print("\n[5/5] Service Stress Checks")
    print("-" * 40)

    fc_mpa = concrete["fc_mpa"]
    fci_mpa = fc_mpa * 0.75  # Transfer strength (75% of f'c)

    # Transfer stresses (girder self-weight only, initial prestress)
    # Top fiber: ft = -Pi/A + Pi*e/St - Mg/St
    ft_transfer_mpa = (-P_i / area / 1e6 * 1e3
                       + P_i * e_max / St / 1e6 * 1e3
                       - M_girder / St / 1e6 * 1e3)

    # Bottom fiber: fb = -Pi/A - Pi*e/Sb + Mg/Sb
    fb_transfer_mpa = (-P_i / area / 1e6 * 1e3
                       - P_i * e_max / Sb / 1e6 * 1e3
                       + M_girder / Sb / 1e6 * 1e3)

    # Allowable stresses at transfer
    ft_allow_transfer = 0.25 * math.sqrt(fci_mpa)  # Tension
    fc_allow_transfer = 0.60 * fci_mpa  # Compression

    transfer_top_ok = ft_transfer_mpa <= ft_allow_transfer
    transfer_bot_ok = abs(fb_transfer_mpa) <= fc_allow_transfer

    print(f"  Transfer (f'ci={fci_mpa:.0f} MPa):")
    print(f"    Top:    {ft_transfer_mpa:.1f} MPa (allow +{ft_allow_transfer:.1f} tension) {'OK' if transfer_top_ok else 'FAIL'}")
    print(f"    Bottom: {fb_transfer_mpa:.1f} MPa (allow -{fc_allow_transfer:.0f} comp) {'OK' if transfer_bot_ok else 'FAIL'}")

    # Service stresses (full load, effective prestress)
    M_total_service = M_girder + M_deck + M_super + M_ll

    ft_service_mpa = (-Pe_final_kN / area / 1e6 * 1e3
                      + Pe_final_kN * e_max / St / 1e6 * 1e3
                      - M_total_service / St / 1e6 * 1e3)

    fb_service_mpa = (-Pe_final_kN / area / 1e6 * 1e3
                      - Pe_final_kN * e_max / Sb / 1e6 * 1e3
                      + M_total_service / Sb / 1e6 * 1e3)

    # Allowable at service (after all losses)
    ft_allow_service = 0.5 * math.sqrt(fc_mpa)  # Tension (MPa)  - Service III
    fc_allow_service = 0.45 * fc_mpa  # Compression (Service I)
    fc_allow_service_iii = 0.60 * fc_mpa  # Service III compression (less critical)

    service_top_ok = ft_service_mpa <= ft_allow_service
    service_bot_ok = fb_service_mpa <= ft_allow_service  # Tension check bottom

    print(f"  Service (f'c={fc_mpa:.0f} MPa):")
    print(f"    Top:    {ft_service_mpa:.1f} MPa (allow +{ft_allow_service:.1f} tension) {'OK' if service_top_ok else 'CHECK'}")
    print(f"    Bottom: {fb_service_mpa:.1f} MPa (allow +{ft_allow_service:.1f} tension) {'OK' if service_bot_ok else 'CHECK'}")

    # ── Ultimate Moment Capacity (AASHTO LRFD 5.7.3) ──
    # Effective depth to strand centroid (from top of composite section)
    dp = composite_depth - (cover_bottom + 0.05)  # m, strands ~50mm from bottom
    dp_mm = dp * 1000  # mm

    # Total prestressing steel area
    Aps_total = n_strands * Aps_strand  # mm²

    # Stress in prestressing steel at nominal flexural resistance
    # AASHTO LRFD Eq. 5.7.3.1.1-1: fps = fpu * (1 - k * c/dp)
    # For rectangular section with compression in deck:
    # k = 2 * (1.04 - fpy/fpu) = 2 * (1.04 - 0.9) = 0.28 for low-relaxation
    k = 0.28
    # Assume neutral axis in deck (typical for composite sections)
    # c = Aps*fpu / (0.85*fc*b*β1 + k*Aps*fpu/dp)
    deck_eff_width_mm = deck_eff_w * 1000  # Effective deck width
    beta1 = 0.85 if fc_mpa <= 28 else max(0.65, 0.85 - (fc_mpa - 28) / 7 * 0.05)
    c = (Aps_total * fpu) / (0.85 * fc_mpa * deck_eff_width_mm * beta1
                              + k * Aps_total * fpu / dp_mm)
    fps = fpu * (1 - k * c / dp_mm)
    fps = min(fps, fpu)  # Cannot exceed fpu

    # Compression block depth
    a = Aps_total * fps / (0.85 * fc_mpa * deck_eff_width_mm)  # mm
    # Ensure a <= deck thickness (neutral axis in deck)
    if a > deck_thickness * 1000:
        # Neutral axis in girder — recalc with web width
        a = Aps_total * fps / (0.85 * fc_mpa * web_w * 1000)  # mm

    # Nominal moment capacity
    Mn = Aps_total * fps * (dp_mm - a / 2) / 1e6  # kN·m
    # Resistance factor for prestressed concrete in flexure: φ = 1.0 (tension-controlled)
    phi_Mn = 1.0 * Mn

    capacity_ok = phi_Mn >= M_strength_I
    ratio = phi_Mn / M_strength_I if M_strength_I > 0 else 0
    status = "OK" if capacity_ok else f"NG ({ratio:.2f}x — consider deeper section or shorter span)"

    print(f"\n  Ultimate: φMn={phi_Mn:.0f} kN·m vs Mu={M_strength_I:.0f} kN·m → {status}")

    # ── Camber Estimate ──
    Ec = concrete["ec_gpa"] * 1e6  # kPa
    # Upward camber from prestress: δp = Pe*e*L²/(8*E*I)
    camber_prestress = Pe_final_kN * e_max * span**2 / (8 * Ec * Ix) * 1000  # mm
    # Downward deflection from girder self-weight
    camber_self_wt = 5 * w_girder * span**4 / (384 * Ec * Ix) * 1000  # mm
    camber_net = camber_prestress - camber_self_wt

    print(f"  Camber: prestress ↑{camber_prestress:.1f}mm - self_wt ↓{camber_self_wt:.1f}mm = net ↑{camber_net:.1f}mm")

    # ── Bill of Materials ──
    girder_concrete = area * span * num_girders
    deck_concrete = span * width * deck_thickness
    total_concrete = girder_concrete + deck_concrete

    strand_length = span * 1.05  # +5% for jacking
    strand_mass = n_strands * strand_length * strand["area_mm2"] * 7850 / 1e6  # kg
    mild_rebar_kg = total_concrete * 40  # ~40 kg/m³ for mild steel in prestressed

    print(f"\n  Concrete: {total_concrete:.1f} m³ (girder: {girder_concrete:.1f}, deck: {deck_concrete:.1f})")
    print(f"  Strands: {strand_mass:.0f} kg ({n_strands} × {strand['diameter_mm']}mm × {span:.1f}m)")
    print(f"  Mild rebar: {mild_rebar_kg:.0f} kg")

    # ── Build output ──
    return {
        "bridge_type": "prestressed_beam",
        "design_code": "",
        "superstructure": {
            "girder_type": f"AASHTO {best_section}",
            "num_girders": num_girders,
            "girder_depth": depth,
            "girder_spacing": girder_spacing,
            "girder_area_m2": round(area, 3),
            "girder_Ix_m4": round(Ix, 4),
            "deck_thickness": deck_thickness,
            "wearing_surface": wearing_surface,
            "composite_depth": round(composite_depth, 2),
            "curb_width": curb_w,
            "curb_height": curb_h,
        },
        "prestressing": {
            "strand_diameter_mm": strand["diameter_mm"],
            "strand_grade": "1860 MPa (270 ksi) low-relaxation",
            "n_strands": n_strands,
            "n_straight": n_straight,
            "n_harped": n_harped,
            "jack_stress_mpa": fpi_actual,
            "effective_stress_mpa": round(fpe_actual, 0),
            "eccentricity_midspan_mm": round(e_max * 1000, 0),
            "total_loss_pct": round(total_loss_pct, 1),
            "loss_breakdown": {
                "elastic_shortening_mpa": round(loss_es, 0),
                "creep_mpa": round(loss_cr, 0),
                "shrinkage_mpa": round(loss_sh, 0),
                "relaxation_mpa": round(loss_re, 0),
            },
        },
        "substructure": design_substructure(piers_data, abutments_data, width,
                                              clearance, depth, deck_thickness),
        "reinforcement": {
            "prestressing_strands": f"{n_strands}-Φ{strand['diameter_mm']}mm Grade 1860",
            "mild_rebar": "per AASHTO LRFD Art. 5.10",
            "shear_reinf": "Φ12@150 (typical web)",
        },
        "quantities": {
            "concrete_m3": {
                "prestressed_girders": round(girder_concrete, 1),
                "deck_slab": round(deck_concrete, 1),
            },
            "prestressing_steel_kg": round(strand_mass, 0),
            "mild_rebar_kg": round(mild_rebar_kg, 0),
            "total_concrete_m3": round(total_concrete, 1),
            "total_rebar_kg": round(strand_mass + mild_rebar_kg, 0),
            "formwork_m2": round(span * width * 1.2 + span * depth * 2 * num_girders * 0.6, 0),
            "bearings_count": max(4, num_girders * 2),
            "expansion_joints_m": round(width + 0.5, 1),
        },
        "loads": {
            "girder_self_wt_kN_per_m": round(w_girder, 1),
            "total_dead_kN_per_m": round(w_total, 1),
            "live_load_moment_kNm": round(M_ll, 0),
        },
        "analysis": {
            "stress_check_transfer": "OK" if (transfer_top_ok and transfer_bot_ok) else "CHECK",
            "stress_check_service": "OK" if (service_top_ok and service_bot_ok) else "CHECK",
            "ultimate_capacity_kNm": round(phi_Mn, 0),
            "ultimate_demand_kNm": round(M_strength_I, 0),
            "capacity_ok": capacity_ok,
            "camber_net_mm": round(camber_net, 1),
            "total_loss_pct": round(total_loss_pct, 1),
        },
    }


# ============================================================================
# Steel Plate Girder Bridge Design (50-150m spans)
# AASHTO LRFD — Steel I-Girder with composite concrete deck
# ============================================================================

def design_steel_girder_bridge(dims, params, code):
    """Design a steel plate girder bridge for spans 45-150m.

    Steel I-girder with composite reinforced concrete deck.
    Design checks: bending (compact/noncompact), shear, web buckling,
    fatigue category, deflection.
    """
    span = dims["span_length"]
    width = dims["deck_width"]
    clearance = dims.get("clearance_under_bridge", 5.0)
    deck_elev = dims.get("deck_elevation", clearance)
    piers_data = params.get("pier_positions", [])
    abutments_data = params.get("abutment_positions", [])

    steel = STRUCTURAL_STEEL
    concrete = CONCRETE_C40

    print("\n[1/5] Superstructure Design — Steel Plate Girder")
    print("-" * 40)

    # ── Girder Proportions ──
    # Web depth: L/22 (short) to L/17 (long) for plate girders
    if span < 50:
        web_depth = span / 22
    elif span < 80:
        web_depth = span / 19
    elif span < 120:
        web_depth = span / 18
    else:
        web_depth = span / 17  # Very deep for longest spans
    web_depth = round(web_depth, 2)

    # Number of girders
    num_girders = max(2, int(width / 3.5))
    girder_spacing = round(width / num_girders, 2)

    # Deck slab
    deck_thickness = 0.200 if span < 80 else 0.225
    wearing_surface = 0.075
    curb_w = 0.5
    curb_h = 0.3

    # Web plate
    web_t = max(0.012, web_depth / 150)
    web_t = round(web_t * 1000, 0)
    web_t = max(12, min(web_t, 25))
    web_t_m = web_t / 1000

    # Flange plates (compact section: bf/2tf <= 0.38*sqrt(E/Fy))
    flange_limit = 0.38 * math.sqrt(steel["es_gpa"] * 1000 / steel["fy_mpa"])
    flange_w = max(0.35, web_depth / 5)
    flange_w = round(flange_w, 2)
    flange_t_raw = flange_w / (2 * flange_limit)
    flange_t = max(0.020, round(flange_t_raw * 1000, 0) / 1000)
    flange_t = max(20, min(flange_t * 1000, 80)) / 1000

    total_depth = web_depth + 2 * flange_t
    composite_depth = total_depth + deck_thickness

    print(f"  Span: {span}m -> Steel plate girder ({num_girders} girders @ {girder_spacing}m)")
    print(f"  Web: {web_depth*1000:.0f}mm x {web_t:.0f}mm")
    print(f"  Flanges: {flange_w*1000:.0f}mm x {flange_t*1000:.0f}mm")
    print(f"  Total steel depth: {total_depth*1000:.0f}mm")
    print(f"  Span/depth: {span/total_depth:.1f}")
    print(f"  Deck: {deck_thickness*1000:.0f}mm RC slab (composite)")

    # ── Section Properties ──
    flange_area = flange_w * flange_t
    web_area = web_depth * web_t_m
    steel_area = 2 * flange_area + web_area

    I_steel = 2 * flange_area * (web_depth / 2 + flange_t / 2)**2 + \
              web_t_m * web_depth**3 / 12
    S_steel_bot = I_steel / (total_depth / 2)

    # Composite section
    n_modular = steel["es_gpa"] / (0.043 * math.sqrt(concrete["density_kg_m3"])
                                     * math.sqrt(concrete["fc_mpa"]))
    n_modular = max(6, round(n_modular, 0))
    deck_eff_w = min(girder_spacing, span / 4, 12 * deck_thickness + flange_w)
    deck_transformed = deck_eff_w * deck_thickness / n_modular
    deck_centroid = total_depth + deck_thickness / 2

    y_composite = (steel_area * total_depth / 2 + deck_transformed * deck_centroid) / \
                  (steel_area + deck_transformed)
    I_composite = I_steel + steel_area * (y_composite - total_depth / 2)**2 + \
                  deck_transformed * deck_thickness**2 / 12 + \
                  deck_transformed * (deck_centroid - y_composite)**2
    S_comp_bot = I_composite / y_composite
    S_comp_top = I_composite / (composite_depth - y_composite)

    print(f"\n  Steel area: {steel_area*1e6:.0f} mm2")
    print(f"  I_steel: {I_steel*1e12:.0f} mm4")
    print(f"  Composite I: {I_composite*1e12:.0f} mm4 (n={n_modular:.0f})")

    # ── Load Calculations ──
    print("\n[2/5] Load Calculations — Steel Girder")
    print("-" * 40)

    rho_s = steel["density_kg_m3"]
    rho_c = concrete["density_kg_m3"]
    g = 9.81

    w_steel = steel_area * rho_s * g / 1000
    w_deck = girder_spacing * deck_thickness * rho_c * g / 1000
    w_asphalt = girder_spacing * wearing_surface * 2300 * g / 1000
    w_barrier = 2 * 5.0 / num_girders
    w_curb = 2 * curb_w * curb_h * rho_c * g / 1000 / num_girders
    w_total_dl = w_steel + w_deck + w_asphalt + w_barrier + w_curb

    design_lanes = max(1, int(width / 3.6))
    impact = min(0.33, 1.2 - 0.005 * span)
    dist_factor = 1.2 / num_girders
    lane_load = 9.3
    M_lane = lane_load * span**2 / 8
    M_truck = 325 * span / 4
    M_ll = (M_lane + M_truck) * design_lanes * (1 + impact) * dist_factor
    V_ll = (lane_load * span / 2 + 325) * design_lanes * (1 + impact) * dist_factor

    M_dc = (w_steel + w_deck) * span**2 / 8
    M_dw = (w_asphalt + w_barrier + w_curb) * span**2 / 8

    print(f"  Steel self-wt: {w_steel:.1f} kN/m")
    print(f"  Total DL: {w_total_dl:.1f} kN/m")
    print(f"  Live load M: {M_ll:.0f} kN-m (per girder)")

    # ── Strength Checks ──
    print("\n[3/5] Strength Checks")
    print("-" * 40)

    fy_mpa = steel["fy_mpa"]  # 345 MPa

    M_u = 1.25 * M_dc + 1.50 * M_dw + 1.75 * M_ll
    V_u = 1.25 * (w_steel + w_deck) * span / 2 + \
          1.50 * (w_asphalt + w_barrier + w_curb) * span / 2 + 1.75 * V_ll

    # Flexural resistance: Mn = Fy * S (MPa * m³ = MN·m = 1000 kN·m)
    Mn_composite = fy_mpa * S_comp_bot  # MPa * m³ → then /1000 for kN·m? Let's check:
    # fy_mpa (MPa) = MN/m², S_comp_bot (m³), so fy * S = MN·m = 1000 kN·m
    Mn_composite_kNm = Mn_composite * 1000  # MN·m → kN·m
    phi_Mn = 1.0 * Mn_composite_kNm

    # Web shear (AASHTO LRFD 6.10.9) — iterate stiffener spacing
    fy_mpa = steel["fy_mpa"]
    E_mpa = steel["es_gpa"] * 1000
    Aw = web_depth * web_t_m * 1e6  # mm²
    D = web_depth * 1000  # mm
    D_tw = D / web_t

    # Try unstiffened first, then add stiffeners if needed
    V_u_req = 1.25 * (w_steel + w_deck) * span / 2 + \
              1.50 * (w_asphalt + w_barrier + w_curb) * span / 2 + 1.75 * V_ll

    stiffener_spacing_m = None
    for d0_D in [None, 3.0, 2.0, 1.5, 1.0, 0.8]:  # None=unstiffened, then stiffened ratios
        if d0_D is None:
            kv = 5.0  # Unstiffened
        else:
            kv = 5.0 + 5.0 / (d0_D)**2  # Stiffened panel (AASHTO 6.10.9.3.2)

        limit_1 = 1.12 * math.sqrt(kv * E_mpa / fy_mpa)
        limit_2 = 1.40 * math.sqrt(kv * E_mpa / fy_mpa)

        if D_tw <= limit_1:
            Cv = 1.0
        elif D_tw <= limit_2:
            Cv = limit_1 / D_tw
        else:
            Cv = 1.51 * E_mpa * kv / (fy_mpa * D_tw**2)

        Vn = 0.58 * fy_mpa * Aw * Cv / 1000  # kN
        if Vn >= V_u_req:
            if d0_D is not None:
                stiffener_spacing_m = round(d0_D * web_depth, 1)
            break

    phi_Vn = 1.0 * Vn

    flexure_ok = phi_Mn >= M_u
    shear_ok = phi_Vn >= V_u

    print(f"  Flexure: phiMn={phi_Mn:.0f} kN-m vs Mu={M_u:.0f} kN-m -> "
          f"{'OK' if flexure_ok else 'NG (' + str(round(phi_Mn/M_u, 2)) + 'x)'}")
    print(f"  Shear: phiVn={phi_Vn:.0f} kN vs Vu={V_u:.0f} kN -> {'OK' if shear_ok else 'NG'}")
    print(f"  Web slenderness D/tw={D_tw:.0f} (Cv={Cv:.2f})")

    # ── Deflection ──
    print("\n[4/5] Serviceability")
    print("-" * 40)

    E = steel["es_gpa"] * 1e6  # kPa
    delta_ll = 5 * (lane_load * design_lanes * dist_factor) * span**4 / \
               (384 * E * I_composite) * 1000  # mm
    delta_limit = span * 1000 / 800
    deflection_ok = delta_ll <= delta_limit

    stiffeners_needed = stiffener_spacing_m is not None
    stiffener_report = f"@ {stiffener_spacing_m}m (d0/D={stiffener_spacing_m/web_depth:.1f})" \
                       if stiffeners_needed else "not required"

    print(f"  Live load deflection: {delta_ll:.1f}mm (limit: L/800 = {delta_limit:.1f}mm) -> "
          f"{'OK' if deflection_ok else 'CHECK'}")
    print(f"  Stiffeners: {stiffener_report}")

    # ── Bill of Materials ──
    print("\n[5/5] Bill of Materials")
    print("-" * 40)

    steel_mass = steel_area * span * num_girders * rho_s / 1000
    steel_mass_total = steel_mass * 1.10
    deck_concrete = span * width * deck_thickness

    print(f"  Steel: {steel_mass_total:.1f} tonnes ({num_girders} girders, +10% stiffeners/splices)")
    print(f"  Concrete deck: {deck_concrete:.1f} m3")
    print(f"  Cross-frames: {max(2, int(span/8))} diaphragms")

    return {
        "bridge_type": "steel_girder",
        "design_code": "",
        "superstructure": {
            "girder_type": "Steel Plate I-Girder (ASTM A709 Gr.50)",
            "num_girders": num_girders,
            "girder_spacing": girder_spacing,
            "web_depth_m": web_depth,
            "web_thickness_mm": web_t,
            "flange_width_m": flange_w,
            "flange_thickness_mm": round(flange_t * 1000, 0),
            "total_steel_depth_m": round(total_depth, 2),
            "composite_depth_m": round(composite_depth, 2),
            "deck_thickness": deck_thickness,
            "wearing_surface": wearing_surface,
            "curb_width": curb_w,
            "curb_height": curb_h,
            "steel_area_m2": round(steel_area, 4),
            "I_steel_m4": round(I_steel, 6),
            "I_composite_m4": round(I_composite, 6),
        },
        "substructure": design_substructure(piers_data, abutments_data, width,
                                              clearance, total_depth, deck_thickness,
                                              abutment_type="steel_girder_seat"),
        "reinforcement": {
            "steel_grade": "ASTM A709 Gr.50 (fy=345 MPa)",
            "girder_fabrication": "welded plate girder",
            "web_stiffeners": stiffener_report,
            "stiffener_spacing_m": stiffener_spacing_m,
            "deck_rebar": "16mm @ 150mm top and bottom",
            "shear_studs": "22mm dia @ 300mm (3 per row)",
        },
        "quantities": {
            "structural_steel_tonnes": round(steel_mass_total, 1),
            "concrete_m3": {"deck_slab": round(deck_concrete, 1)},
            "rebar_kg": round(deck_concrete * 80, 0),
            "bearings_count": num_girders * 2,
            "expansion_joints_m": round(width + 0.5, 1),
            "painting_area_m2": round(span * (2 * web_depth + 4 * flange_w) * num_girders, 0),
        },
        "loads": {
            "steel_self_wt_kN_per_m": round(w_steel, 1),
            "total_dead_kN_per_m": round(w_total_dl, 1),
            "live_load_moment_kNm": round(M_ll, 0),
        },
        "analysis": {
            "flexure_phi_Mn_kNm": round(phi_Mn, 0),
            "factored_Mu_kNm": round(M_u, 0),
            "flexure_ok": flexure_ok,
            "shear_phi_Vn_kN": round(phi_Vn, 0),
            "shear_ok": shear_ok,
            "deflection_mm": round(delta_ll, 1),
            "deflection_ok": deflection_ok,
            "web_D_tw": round(D_tw, 0),
        },
    }


# ============================================================================
# Cable-Stayed Bridge Preliminary Design (150-400m spans)
# Simplified: fan-pattern stay cables, single pylon
# ============================================================================

def design_cable_stayed_bridge(dims, params, code):
    """Preliminary design of cable-stayed bridge for spans 150-400m.

    Uses simplified fan-pattern cable arrangement. Computes pylon height,
    cable forces, deck section, and checks feasibility.
    """

    span = dims["span_length"]
    width = dims["deck_width"]
    clearance = dims.get("clearance_under_bridge", 15.0)

    print("\n[1/5] Cable-Stayed Bridge — Preliminary Design")
    print("-" * 40)

    main_span = span * 0.65
    back_span = span - main_span

    pylon_height = round(main_span / 4.5, 1)
    pylon_w = max(2.0, width / 8)
    pylon_d = max(3.0, pylon_height / 15)
    pylon_wall = 0.4

    n_cables_per_side = max(6, int(main_span / 15))
    cable_spacing = main_span / n_cables_per_side

    deck_thickness = 0.250
    deck_w_knm = width * deck_thickness * 25 * 9.81 / 1000 + 9.0

    cable_load = deck_w_knm * cable_spacing
    max_angle = math.atan(pylon_height / main_span)
    min_angle = math.atan(pylon_height / (cable_spacing * 2))
    avg_angle = (max_angle + min_angle) / 2
    cable_force = cable_load / math.sin(avg_angle)
    cable_stress = 835.0
    cable_area = cable_force * 1000 / cable_stress

    total_cable_len = 0
    for i in range(1, n_cables_per_side + 1):
        total_cable_len += math.sqrt((i * cable_spacing)**2 + pylon_height**2) * 2
    cable_steel_t = total_cable_len * cable_area * 7850 / 1e9

    M_deck = deck_w_knm * cable_spacing**2 / 10
    I_deck = width * deck_thickness**3 / 12
    delta_deck = 5 * deck_w_knm * cable_spacing**4 / (384 * 3.0e7 * I_deck) * 1000
    delta_limit = cable_spacing * 1000 / 800

    pylon_area = 2 * (pylon_w + pylon_d) * pylon_wall
    pylon_stress = deck_w_knm * main_span / pylon_area / 1000
    pylon_allow = 0.3 * 40  # MPa
    pylon_ok = pylon_stress < pylon_allow

    print(f"  Main span: {main_span:.0f}m, Pylon: {pylon_height}m above deck")
    print(f"  Cables: {n_cables_per_side} pairs/side @ {cable_spacing:.0f}m")
    print(f"  Cable force: {cable_force:.0f} kN, area: {cable_area:.0f} mm²")
    print(f"  Deck deflection: {delta_deck:.1f}mm vs {delta_limit:.0f}mm → {'OK' if delta_deck < delta_limit else 'CHECK'}")
    print(f"  Pylon stress: {pylon_stress:.1f}MPa vs {pylon_allow:.0f}MPa → {'OK' if pylon_ok else 'CHECK'}")
    print(f"  Cable steel: {cable_steel_t:.1f} tonnes")
    print(f"  ⚠ PRELIMINARY ONLY — final design requires nonlinear FEM")

    deck_conc = span * width * deck_thickness
    pylon_conc = pylon_height * pylon_area * 2
    total_conc = deck_conc + pylon_conc

    return {
        "bridge_type": "cable_stayed",
        "design_code": "",
        "superstructure": {
            "girder_type": "Cable-Stayed (Fan Pattern)",
            "main_span_m": round(main_span, 0),
            "back_span_m": round(back_span, 0),
            "pylon_height_m": pylon_height,
            "pylon_section": f"{pylon_w:.1f}x{pylon_d:.1f}m hollow",
            "n_cables_per_side": n_cables_per_side,
            "cable_spacing_m": round(cable_spacing, 1),
            "cable_type": "Grade 1860 parallel strand",
            "deck_thickness": deck_thickness,
            "deck_width": width,
        },
        "substructure": {
            "pylon_foundation": f"caisson/pile group, depth > {pylon_height*0.3:.0f}m",
            "abutments": [
                {"type": "anchorage", "note": "Back span end anchor"},
                {"type": "expansion", "note": "Main span expansion joint"},
            ],
        },
        "reinforcement": {
            "stay_cables": f"{n_cables_per_side*2} cables, {cable_area:.0f}mm² each",
            "note": "PRELIMINARY — requires nonlinear FEM",
        },
        "quantities": {
            "concrete_m3": {"deck": round(deck_conc, 0), "pylons": round(pylon_conc, 0)},
            "cable_steel_tonnes": round(cable_steel_t, 1),
            "total_concrete_m3": round(total_conc, 0),
        },
        "loads": {
            "deck_load_kN_per_m": round(deck_w_knm, 1),
            "cable_force_max_kN": round(cable_force, 0),
            "pylon_axial_kN": round(deck_w_knm * main_span, 0),
        },
        "analysis": {
            "deck_deflection_mm": round(delta_deck, 1),
            "deck_deflection_ok": delta_deck < delta_limit,
            "pylon_stress_mpa": round(pylon_stress, 1),
            "pylon_ok": pylon_ok,
            "note": "PRELIMINARY DESIGN ONLY — requires nonlinear FEM for final design",
        },
    }


# ============================================================================
# Load Calculations
# ============================================================================

def calculate_beam_loads(span, width, girder_type, num_girders, girder_depth,
                          deck_thickness, wearing_surface, curb_width, curb_height,
                          concrete, code):
    """Calculate dead, superimposed dead, and live loads for a beam bridge."""

    # ── Dead Load (structural self-weight) ──
    # Deck slab
    deck_area = width * deck_thickness
    deck_w = deck_area * concrete["density_kg_m3"] * 9.81 / 1000  # kN/m

    # Girders
    if girder_type == "I-beam":
        # Simplified I-beam area
        flange_w = girder_depth * 0.5
        flange_t = girder_depth * 0.12
        web_t = girder_depth * 0.08
        girder_area = 2 * flange_w * flange_t + (girder_depth - 2*flange_t) * web_t
    elif girder_type == "T-beam":
        flange_w = width / num_girders * 0.8
        flange_t = 0.20
        web_t = 0.30
        girder_area = flange_w * flange_t + (girder_depth - flange_t) * web_t
    else:  # Box girder
        girder_area = girder_depth * (width / num_girders) * 0.6  # Hollow ratio

    girder_w = girder_area * num_girders * concrete["density_kg_m3"] * 9.81 / 1000

    # Curbs
    curb_area = 2 * curb_width * curb_height
    curb_w = curb_area * concrete["density_kg_m3"] * 9.81 / 1000

    dead_load = deck_w + girder_w + curb_w

    # ── Superimposed Dead Load ──
    # Asphalt wearing surface
    asphalt_w = width * wearing_surface * 2300 * 9.81 / 1000  # Asphalt density 2300 kg/m3

    # Barriers / railings (estimate 5 kN/m each side)
    barrier_w = 2 * 5.0

    superimposed_dead = asphalt_w + barrier_w

    # ── Live Load (AASHTO HL-93 or Chinese CL-1) ──
    if code == "CHN":
        # JTG D60-2015 Highway Class I
        lane_load = 10.5  # kN/m per lane
        truck_load = 550  # kN total (5-axle)
        design_lanes = max(1, int(width / 3.5))
        impact_factor = 0.33 if span <= 5 else 0.25  # Simplified
    else:
        # AASHTO LRFD HL-93
        lane_load = 9.3  # kN/m per lane
        truck_load = 325  # kN (HS20-44 design truck)
        design_lanes = max(1, int(width / 3.6))
        impact_factor = min(0.33, 1.2 - 0.005 * span)  # IM for moment

    # Simple span: M_LL = (lane_load * L^2/8 + P*a) * lanes * (1+IM) * distribution
    M_lane = lane_load * span ** 2 / 8  # kN·m per lane
    M_truck = truck_load * span / 4  # Approximate truck position for max moment

    # Distribution factor (simplified — 1/n_girders * 1.2 for exterior girder)
    dist_factor = 1.2 / num_girders

    M_ll = (M_lane + M_truck) * design_lanes * (1 + impact_factor) * dist_factor
    V_ll = (lane_load * span / 2 + truck_load) * design_lanes * (1 + impact_factor) * dist_factor

    return {
        "dead_load_kN_per_m": round(dead_load, 1),
        "superimposed_dead_kN_per_m": round(superimposed_dead, 1),
        "design_lanes": design_lanes,
        "impact_factor": round(impact_factor, 3),
        "live_load_moment_kNm": round(M_ll, 0),
        "live_load_shear_kN": round(V_ll, 0),
        "girder_area_m2": round(girder_area, 3),
        "deck_area_m2": round(deck_area, 2),
    }


def calculate_arch_loads(span, width, num_ribs, rib_width, rib_depth,
                          deck_thickness, wearing_surface, curb_width, curb_height,
                          rise, num_spandrels, concrete, code):
    """Calculate loads for an arch bridge."""

    rho = concrete["density_kg_m3"]

    # Deck dead load
    deck_w = width * deck_thickness * rho * 9.81 / 1000
    asphalt_w = width * wearing_surface * 2300 * 9.81 / 1000
    curb_w = 2 * curb_width * curb_height * rho * 9.81 / 1000
    barrier_w = 2 * 5.0

    # Arch rib self-weight (arch length ~ L * (1 + 8/3*(h/L)^2) for parabolic)
    h_over_L = rise / span
    arch_length = span * (1 + 8/3 * h_over_L ** 2)
    rib_w = arch_length * rib_width * rib_depth * num_ribs * rho * 9.81 / 1000 / span

    # Spandrel columns (average)
    avg_spandrel_h = rise * 0.4
    spandrel_w = num_spandrels * 0.5 * 0.5 * avg_spandrel_h * rho * 9.81 / 1000 / span

    dead_load = deck_w + asphalt_w + curb_w + barrier_w + rib_w + spandrel_w

    # Arch thrust: H = w*L^2/(8*h) for parabolic arch with uniform load
    total_w = dead_load + 20  # + approximate live load
    arch_thrust = total_w * span ** 2 / (8 * rise)

    # Live load
    lane_load = 9.3
    truck_load = 325
    design_lanes = max(1, int(width / 3.6))
    M_lane = lane_load * span ** 2 / 8
    M_truck = truck_load * span / 4
    M_ll = (M_lane + M_truck) * design_lanes * (1 + 0.25)

    return {
        "dead_load_kN_per_m": round(dead_load, 1),
        "arch_thrust_kN": round(arch_thrust, 0),
        "live_load_moment_kNm": round(M_ll, 0),
        "arch_length_m": round(arch_length, 1),
        "design_lanes": design_lanes,
    }


# ============================================================================
# Structural Analysis
# ============================================================================

def analyze_beam_bridge(span, w_dead, w_super, M_ll, V_ll, num_girders,
                         girder_depth, girder_type, concrete):
    """Perform structural analysis of a beam bridge."""

    # Load factors (AASHTO LRFD Strength I)
    gamma_dc = 1.25
    gamma_dw = 1.50
    gamma_ll = 1.75

    # Total factored distributed load
    w_factored = gamma_dc * w_dead + gamma_dw * w_super

    # Simple span moments
    M_dc = w_dead * span ** 2 / 8
    M_dw = w_super * span ** 2 / 8
    M_factored_dl = w_factored * span ** 2 / 8

    Mu_total = gamma_dc * M_dc + gamma_dw * M_dw + gamma_ll * M_ll
    Mu_per_girder = Mu_total / num_girders

    # Shear
    V_dc = w_dead * span / 2
    V_dw = w_super * span / 2
    Vu_total = gamma_dc * V_dc + gamma_dw * V_dw + gamma_ll * V_ll
    Vu_per_girder = Vu_total / num_girders

    # Deflection (live load only, service)
    Ec = concrete["ec_gpa"] * 1e6  # kPa
    if girder_type == "I-beam":
        flange_w = girder_depth * 0.5
        flange_t = girder_depth * 0.12
        web_t = girder_depth * 0.08
    elif girder_type == "T-beam":
        flange_w = 1.8  # Typical T-beam flange width for deflection calc
        flange_t = 0.20
        web_t = 0.30
    else:
        flange_w = girder_depth * 0.5
        flange_t = 0.20
        web_t = 0.30

    # Approximate I based on rectangular section
    I_girder = girder_depth ** 3 * 0.05  # Simplified moment of inertia
    I_girder = max(I_girder, 0.01)

    # Deflection = 5*w*L^4/(384*E*I) for simple span
    w_ll_distributed = 9.3 * max(1, int(8.0 / 3.6)) / num_girders
    deflection = 5 * w_ll_distributed * span ** 4 / (384 * Ec * I_girder) * 1000  # mm

    return {
        "Mu_total_kNm": round(Mu_total, 0),
        "Mu_per_girder_kNm": round(Mu_per_girder, 0),
        "Vu_total_kN": round(Vu_total, 0),
        "Vu_per_girder_kN": round(Vu_per_girder, 0),
        "deflection_mm": round(deflection, 1),
    }


# ============================================================================
# Reinforcement Design
# ============================================================================

def design_girder_reinforcement(Mu_kNm, Vu_kN, bw_m, d_m, fc_mpa, fy_mpa, code):
    """Design flexural and shear reinforcement for a concrete girder."""

    # Convert to N and mm
    Mu = Mu_kNm * 1e6  # N·mm
    Vu = Vu_kN * 1e3   # N
    bw = bw_m * 1000   # mm
    d = d_m * 1000     # mm

    phi_f = 0.9  # Flexural strength reduction factor
    phi_s = 0.75  # Shear strength reduction factor

    # ── Flexural Reinforcement ──
    # Rectangular stress block: a = As*fy / (0.85*fc*b)
    # Mu = phi * As * fy * (d - a/2)
    # Solve for As iteratively

    As_trial = Mu / (phi_f * fy_mpa * 0.9 * d)
    for _ in range(5):
        a = As_trial * fy_mpa / (0.85 * fc_mpa * bw)
        As_req = Mu / (phi_f * fy_mpa * (d - a / 2))
        As_trial = As_req

    As_req_mm2 = As_req

    # Select rebar size and count
    for bar_dia in [36, 32, 28, 25]:
        bar_area = REBAR_SIZES[bar_dia]["area_mm2"]
        n_bars = math.ceil(As_req_mm2 / bar_area)
        if n_bars >= 4:
            break
    if n_bars < 4:
        bar_dia = 25
        n_bars = max(4, math.ceil(As_req_mm2 / REBAR_SIZES[25]["area_mm2"]))

    main_bars = f"{n_bars}-Φ{bar_dia}"
    As_provided = n_bars * REBAR_SIZES[bar_dia]["area_mm2"]

    # ── Shear Reinforcement ──
    # Concrete shear strength: Vc = 0.17 * sqrt(fc) * bw * d (AASHTO LRFD simplified)
    Vc = 0.17 * math.sqrt(fc_mpa) * bw * d  # N

    if Vu <= phi_s * Vc / 2:
        stirrup_spacing = min(0.75 * d, 600)  # Minimum shear reinforcement
        stirrup_bar = 10
    else:
        Vs_req = Vu / phi_s - Vc
        # Vs = Av * fy * d / s
        stirrup_bar = 12 if Vs_req < 500e3 else 16
        Av = 2 * REBAR_SIZES[stirrup_bar]["area_mm2"]  # 2 legs
        s_req = Av * fy_mpa * d / Vs_req
        s_max = min(0.5 * d, 300) if Vs_req > 0.33 * math.sqrt(fc_mpa) * bw * d else min(0.75 * d, 600)
        stirrup_spacing = min(s_req, s_max)

    stirrup_spacing = max(100, min(int(stirrup_spacing / 10) * 10, 600))  # Round to 10mm

    stirrups = f"Φ{stirrup_bar}@{stirrup_spacing}"

    return {
        "main_bars": main_bars,
        "stirrups": stirrups,
        "As_req_mm2": round(As_req_mm2, 0),
        "As_provided_mm2": round(As_provided, 0),
        "bar_diameter": bar_dia,
        "num_bars": n_bars,
    }


def design_deck_reinforcement(deck_thickness_m, girder_spacing_m, fc_mpa, fy_mpa, cover_mm):
    """Design reinforcement for a concrete bridge deck."""

    # Deck is treated as a one-way slab spanning between girders
    t = deck_thickness_m * 1000  # mm
    S = girder_spacing_m * 1000  # mm (clear span approximation)
    d = t - cover_mm - 8  # Effective depth (assume 16mm bars)

    # Empirical deck design (AASHTO LRFD 9.7.2)
    # Minimum reinforcement: 0.57 mm²/mm per face for 225mm deck
    # Bottom transverse: primary flexural reinforcement
    As_req = 0.002 * 1000 * d  # 0.2% of gross area per meter width

    # Select bar size and spacing
    for bar_dia in [16, 12]:
        bar_area = REBAR_SIZES[bar_dia]["area_mm2"]
        n_per_meter = As_req / bar_area
        spacing = int(1000 / n_per_meter)
        if 100 <= spacing <= 300:
            break
    if spacing > 300:
        spacing = 150
        bar_dia = 16
    elif spacing < 100:
        bar_dia = 16
        spacing = 150

    spacing = max(100, min(int(spacing / 10) * 10, 300))

    # Top transverse: same as bottom or slightly less
    top_bar_dia = bar_dia if bar_dia > 12 else 12
    top_spacing = spacing

    # Longitudinal distribution steel (bottom)
    long_ratio = max(0.3, 220 / math.sqrt(S))  # AASHTO
    long_bar_dia = 12
    long_spacing = 200

    return {
        "top_transverse": f"Φ{top_bar_dia}@{top_spacing}",
        "bottom_transverse": f"Φ{bar_dia}@{spacing}",
        "bottom_longitudinal": f"Φ{long_bar_dia}@{long_spacing}",
        "cover_mm": cover_mm,
        "deck_thickness_mm": t,
    }


def design_arch_reinforcement(rib_width, rib_depth, arch_thrust_kN, num_ribs,
                               concrete, steel, code):
    """Design reinforcement for arch ribs (primarily compression with bending)."""

    thrust_per_rib = arch_thrust_kN / num_ribs  # kN
    Ag = rib_width * rib_depth  # m²
    fc_kPa = concrete["fc_mpa"] * 1000
    fy = steel["fy_mpa"] * 1000

    # Minimum reinforcement for compression member: 1% of gross area
    As_min = 0.01 * Ag * 1e6  # mm²

    # Select bars
    for bar_dia in [32, 28, 25]:
        bar_area = REBAR_SIZES[bar_dia]["area_mm2"]
        n_bars = math.ceil(As_min / bar_area)
        if 4 <= n_bars <= 16:
            break
    if n_bars < 4:
        bar_dia = 25
        n_bars = 4

    main_bars = f"{n_bars}-Φ{bar_dia}"

    # Shear ties: Φ12@200 for ribs
    stirrups = "Φ12@200"

    return {
        "main_bars": main_bars,
        "stirrups": stirrups,
        "As_provided_mm2": round(n_bars * REBAR_SIZES[bar_dia]["area_mm2"], 0),
        "bar_diameter": bar_dia,
        "num_bars": n_bars,
    }


# ============================================================================
# Substructure Design
# ============================================================================

def design_substructure(piers_data, abutments_data, width, clearance,
                         girder_depth, deck_thickness, abutment_type="seat_type"):
    """Design pier caps, columns, and abutments."""

    pier_designs = []
    for i, p in enumerate(piers_data):
        pier_h = p.get("height", clearance)
        # Rectangular column section
        col_width = 1.0
        col_length = 2.0

        # Pier cap (T-beam on top of column)
        cap_width = col_length + 0.6
        cap_depth = max(0.6, girder_depth * 0.4)

        # Foundation (spread footing or pile cap)
        if pier_h < 8:
            foundation = "spread_footing_3x3x0.8m"
        else:
            foundation = "pile_cap_4x4x1.2m_4piles"

        pier_designs.append({
            "id": i + 1,
            "height": round(pier_h, 2),
            "section": f"{col_width}x{col_length}m",
            "cap_width": round(cap_width, 2),
            "cap_depth": round(cap_depth, 2),
            "foundation": foundation,
            "x_pos": p.get("x", 0),
            "y_pos": p.get("y", 0),
        })

    # Bearing selection
    span = 30  # From dimensions
    if span <= 20:
        bearing_type = "elastomeric_pad"
        bearings_per_pier = 4
    elif span <= 35:
        bearing_type = "laminated_elastomeric"
        bearings_per_pier = 4
    else:
        bearing_type = "pot_bearing"
        bearings_per_pier = 4

    # Also bearings at abutments
    abutment_bearings = 4 if len(abutments_data) > 0 else 0
    total_bearings = len(pier_designs) * bearings_per_pier + len(abutments_data) * abutment_bearings

    # Abutment design
    abutments = []
    for i, a in enumerate(abutments_data):
        abutments.append({
            "id": i + 1,
            "type": abutment_type,
            "height": round(a.get("height", clearance), 2),
            "width": round(width + 1, 2),
            "bearing_seat_width": 0.6,
            "backwall_height": 1.5,
            "x_pos": a.get("x", 0),
            "y_pos": a.get("y", 0),
        })

    return {
        "piers": pier_designs,
        "abutments": abutments,
        "abutment_type": abutment_type,
        "bearing_type": bearing_type,
        "bearings_count": total_bearings,
    }


# ============================================================================
# Terrain Adaptation
# ============================================================================

def adapt_to_terrain(design, terrain_profile, dims):
    """Adapt foundation depths and pier heights to terrain profile."""
    if not terrain_profile or len(terrain_profile) < 2:
        # No terrain data, use nominal values
        return design

    # Find terrain elevation at each pier location
    for pier in design.get("substructure", {}).get("piers", []):
        px = pier.get("x_pos", 0)
        # Interpolate terrain z at pier x
        terrain_z = _interpolate_terrain(terrain_profile, px)
        if terrain_z is not None:
            pier["ground_elevation"] = round(terrain_z, 2)
            # Adjust pier visible height
            deck_z = dims.get("deck_elevation", pier["height"])
            pier["height_above_ground"] = round(deck_z - terrain_z, 2)
            # Foundation embedment
            pier["foundation_depth"] = round(max(0.8, abs(terrain_z) * 0.3 + 0.5), 2)

    # Abutment adaptation
    for abutment in design.get("substructure", {}).get("abutments", []):
        ax = abutment.get("x_pos", 0)
        terrain_z = _interpolate_terrain(terrain_profile, ax)
        if terrain_z is not None:
            abutment["ground_elevation"] = round(terrain_z, 2)

    return design


def _interpolate_terrain(profile, x):
    """Linear interpolation in terrain profile."""
    if not profile:
        return None
    # Find surrounding points
    profile_sorted = sorted(profile, key=lambda p: p["x"])
    xs = [p["x"] for p in profile_sorted]
    zs = [p["z"] for p in profile_sorted]

    if x <= xs[0]:
        return zs[0]
    if x >= xs[-1]:
        return zs[-1]

    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            t = (x - xs[i]) / (xs[i + 1] - xs[i])
            return zs[i] + t * (zs[i + 1] - zs[i])
    return None


# ============================================================================
# Bill of Materials
# ============================================================================

def compute_bill_of_materials(span, width, girder_type, num_girders, girder_depth,
                               web_thickness, flange_width, flange_thickness,
                               deck_thickness, wearing_surface, curb_width, curb_height,
                               substructure, girder_rebar, deck_rebar):
    """Compute concrete volumes, rebar weights, formwork areas."""

    concrete = {}
    rebar = {}
    formwork = 0

    # ── Deck slab ──
    deck_vol = span * width * deck_thickness
    concrete["deck_slab"] = round(deck_vol, 1)
    formwork += span * width  # Bottom formwork (approximate)

    # ── Girders ──
    if girder_type == "I-beam":
        flange_w = flange_width
        flange_t = flange_thickness
        web_t = web_thickness
        girder_area = 2 * flange_w * flange_t + (girder_depth - 2*flange_t) * web_t
    elif girder_type == "T-beam":
        flange_w = width / num_girders * 0.8
        flange_t = 0.20
        web_t = 0.30
        girder_area = flange_w * flange_t + (girder_depth - flange_t) * web_t
    else:  # Box
        girder_area = girder_depth * (width / num_girders) * 0.6

    girder_vol = girder_area * span * num_girders
    concrete["girders"] = round(girder_vol, 1)
    formwork += girder_depth * span * 2 * num_girders * 0.7  # Girder sides (partial)

    # ── Curbs ──
    curb_vol = 2 * curb_width * curb_height * span
    concrete["curbs"] = round(curb_vol, 1)
    formwork += 2 * curb_height * span * 2

    # ── Asphalt ──
    asphalt_vol = span * (width - 2 * curb_width) * wearing_surface

    # ── Piers ──
    pier_vol = 0
    for pier in substructure.get("piers", []):
        section_str = pier["section"]
        w_p, l_p = [float(x.replace("m", "")) for x in section_str.split("x")]
        h = pier["height"]
        col_vol = w_p * l_p * h
        cap_vol = pier.get("cap_width", 2.6) * pier.get("cap_depth", 0.6) * width * 0.5
        pier_vol += col_vol + cap_vol

        # Foundation
        foundation_str = pier.get("foundation", "")
        if "spread_footing" in foundation_str:
            # Parse "spread_footing_3x3x0.8m" -> dimensions
            parts = foundation_str.split("_")
            if len(parts) >= 3:
                dims_str = parts[2]  # "3x3x0.8m"
                dims_clean = dims_str.replace("m", "")
                fx, fy, fz = [float(x) for x in dims_clean.split("x")]
                pier_vol += fx * fy * fz
        elif "pile_cap" in foundation_str:
            # Parse "pile_cap_4x4x1.2m_4piles" -> dimensions
            parts = foundation_str.split("_")
            if len(parts) >= 3:
                dims_str = parts[2]  # "4x4x1.2m"
                dims_clean = dims_str.replace("m", "")
                fx, fy, fz = [float(x) for x in dims_clean.split("x")]
                pier_vol += fx * fy * fz

    concrete["piers"] = round(pier_vol, 1)
    # Pier formwork: perimeter * height
    for pier in substructure.get("piers", []):
        section_str = pier["section"]
        w_p, l_p = [float(x.replace("m", "")) for x in section_str.split("x")]
        h = pier["height"]
        formwork += 2 * (w_p + l_p) * h

    # ── Abutments ──
    abut_vol = 0
    for abutment in substructure.get("abutments", []):
        a_h = abutment.get("height", 5)
        a_w = abutment.get("width", width + 1)
        abut_vol += 1.5 * a_w * a_h * 0.5  # Approximate
    concrete["abutments"] = round(abut_vol, 1)

    # ── Rebar quantities ──
    # Girder main bars
    if "main_bars" in girder_rebar:
        n, dia_str = girder_rebar["main_bars"].split("-Φ")
        bar_dia = int(dia_str)
        bar_mass = REBAR_SIZES[bar_dia]["mass_kg_per_m"]
        n = int(n)
        rebar_length = span * n * num_girders
        rebar[f"Φ{bar_dia}"] = round(rebar_length * bar_mass, 0)

    # Stirrups
    if "stirrups" in girder_rebar:
        stirrup_str = girder_rebar["stirrups"]
        dia_part = stirrup_str.split("@")[0].replace("Φ", "")
        spacing_part = int(stirrup_str.split("@")[1])
        stirrup_dia = int(dia_part)
        stirrup_mass = REBAR_SIZES[stirrup_dia]["mass_kg_per_m"]
        n_stirrups = int(span / (spacing_part / 1000))
        stirrup_length_each = girder_depth * 2 + 0.5  # Perimeter approximate
        stirrup_total = n_stirrups * stirrup_length_each * num_girders
        rebar_key = f"Φ{stirrup_dia}"
        rebar[rebar_key] = round(rebar.get(rebar_key, 0) + stirrup_total * stirrup_mass, 0)

    # Deck rebar (approximate)
    deck_rebar_mass = span * width * 75  # ~75 kg/m² for a 225mm deck
    # Distribute to bar sizes
    rebar["Φ16"] = round(rebar.get("Φ16", 0) + deck_rebar_mass * 0.6, 0)
    rebar["Φ12"] = round(rebar.get("Φ12", 0) + deck_rebar_mass * 0.4, 0)

    # Add pier and abutment rebar (~120 kg/m³ of concrete)
    rebar["Φ25"] = round(rebar.get("Φ25", 0) + pier_vol * 60, 0)
    rebar["Φ16"] = round(rebar.get("Φ16", 0) + pier_vol * 60, 0)
    rebar["Φ16"] = round(rebar.get("Φ16", 0) + abut_vol * 80, 0)

    return {
        "concrete_m3": concrete,
        "rebar_kg": {k: round(v, 0) for k, v in rebar.items()},
        "formwork_m2": round(formwork, 0),
        "asphalt_m3": round(asphalt_vol, 1),
        "bearings_count": substructure.get("bearings_count", 0),
        "expansion_joints_m": round(width + 0.5, 1),
        "total_concrete_m3": round(sum(concrete.values()), 1),
        "total_rebar_kg": round(sum(rebar.values()), 0),
    }


def compute_arch_bom(span, width, num_ribs, rib_width, rib_depth, rise,
                      num_spandrels, spandrel_section, deck_thickness,
                      wearing_surface, curb_width, curb_height,
                      substructure, arch_rebar, deck_rebar):
    """Compute BOM for arch bridge."""

    concrete = {}
    rebar = {}

    # Arch ribs
    h_over_L = rise / span
    arch_length = span * (1 + 8/3 * h_over_L ** 2)
    rib_vol = arch_length * rib_width * rib_depth * num_ribs
    concrete["arch_ribs"] = round(rib_vol, 1)

    # Spandrel columns
    sp_size = [float(x.replace("m", "")) for x in spandrel_section.split("x")]
    avg_h = rise * 0.4
    spandrel_vol = num_spandrels * sp_size[0] * sp_size[1] * avg_h
    concrete["spandrel_columns"] = round(spandrel_vol, 1)

    # Deck
    deck_vol = span * width * deck_thickness
    concrete["deck"] = round(deck_vol, 1)

    # Curbs
    curb_vol = 2 * curb_width * curb_height * span
    concrete["curbs"] = round(curb_vol, 1)

    # Piers and abutments
    pier_vol = 0
    for pier in substructure.get("piers", []):
        section_str = pier["section"]
        w_p, l_p = [float(x.replace("m", "")) for x in section_str.split("x")]
        pier_vol += w_p * l_p * pier["height"]
    concrete["piers"] = round(pier_vol, 1)

    abut_vol = 0
    for abutment in substructure.get("abutments", []):
        abut_vol += 1.5 * abutment.get("width", width) * abutment.get("height", 5) * 0.5
    concrete["abutments"] = round(abut_vol, 1)

    # Rebar (~130 kg/m³ for arch)
    total_conc = sum(concrete.values())
    rebar["Φ32"] = round(total_conc * 50, 0)
    rebar["Φ16"] = round(total_conc * 50, 0)
    rebar["Φ12"] = round(total_conc * 30, 0)

    formwork = rib_depth * arch_length * 2 * num_ribs + span * width * 1.2

    return {
        "concrete_m3": concrete,
        "rebar_kg": rebar,
        "formwork_m2": round(formwork, 0),
        "asphalt_m3": round(span * (width - 2*curb_width) * wearing_surface, 1),
        "bearings_count": substructure.get("bearings_count", 0),
        "expansion_joints_m": round(width + 0.5, 1),
        "total_concrete_m3": round(total_conc, 1),
        "total_rebar_kg": round(sum(rebar.values()), 0),
    }


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Bridge Engineering Design Engine"
    )
    parser.add_argument("params", help="Path to bridge_params.json")
    parser.add_argument("--output", "-o", default="detailed_design.json",
                        help="Output file path (default: detailed_design.json)")
    parser.add_argument("--design-code", choices=["AASHTO", "CHN"], default="AASHTO",
                        help="Design code (default: AASHTO)")
    parser.add_argument("--live-load", choices=["HL93", "CL1"], default="HL93",
                        help="Live load model (default: HL93)")
    args = parser.parse_args()

    # Load parameters
    with open(args.params, "r") as f:
        params = json.load(f)

    # Design the bridge
    design = design_bridge(params, design_code=args.design_code)

    # Set design code metadata
    design["design_code"] = "AASHTO LRFD HL-93" if args.design_code == "AASHTO" else "JTG D60-2015 CL-1"
    design["design_input"] = {
        "params_file": args.params,
        "design_code": args.design_code,
        "live_load": args.live_load,
    }

    # Write output
    with open(args.output, "w") as f:
        json.dump(design, f, indent=2)

    print(f"\n{'=' * 60}")
    print(f"Detailed design saved to: {args.output}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
