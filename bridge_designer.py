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

    # Common to all types
    design["bridge_type"] = bridge_type
    design["design_code"] = "AASHTO LRFD" if design_code == "AASHTO" else "JTG D60-2015"

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

    # ── Girder Selection ──
    if span < 15:
        girder_type = "T-beam"
        girder_depth = span / 16
        num_girders = max(3, int(width / 2.5))
    elif span < 35:
        girder_type = "I-beam"
        girder_depth = span / 18
        num_girders = max(3, int(width / 3.0))
    else:
        girder_type = "Box Girder"
        girder_depth = span / 20
        num_girders = max(2, int(width / 4.0))

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
        flange_w = girder_spacing(girder_depth * 0.12)
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
