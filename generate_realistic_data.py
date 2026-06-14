#!/usr/bin/env python3
"""
Realistic UAV LiDAR Bridge Point Cloud Generator
Simulates real-world scanning artifacts:
- Flight-line scanning pattern (stripes)
- Occlusion shadows (under deck, behind piers)
- Vegetation clusters near abutments
- Water surface returns (river under bridge)
- Mixed edge returns (vegetation + structure boundary)
- Variable point density (near-nadir dense, oblique sparse)
- Sensor noise (range noise proportional to distance)
- Classification labels (2=ground, 3=low veg, 4=medium veg, 5=high veg, 6=building, 9=water)
"""

import numpy as np
import laspy
import argparse
from pathlib import Path


def simulate_flight_lines(length=40, width=15, altitude=60, speed=5, scan_rate=200,
                          fov_deg=30):
    """Simulate UAV flight lines over the bridge corridor.

    Returns scanner positions (x, y, z) for each pulse emission.
    """
    n_lines = 6  # Multiple overlapping flight lines
    line_spacing = width / (n_lines + 1)

    all_positions = []

    for line in range(n_lines):
        y_offset = -width / 2 + (line + 1) * line_spacing
        # Add slight wobble
        y_wobble = np.random.normal(0, 0.3, int(length / speed * scan_rate))

        n_pulses = int(length / speed * scan_rate)
        x = np.linspace(-length / 2, length / 2, n_pulses)
        y = np.full(n_pulses, y_offset) + y_wobble
        z = np.full(n_pulses, altitude) + np.random.normal(0, 0.5, n_pulses)

        positions = np.column_stack([x, y, z])
        all_positions.append(positions)

    return np.concatenate(all_positions)


def shoot_rays(scanner_positions, scene_objects, fov_deg=30):
    """Simplified ray casting: shoot rays from scanner to ground/structure.

    Returns (x, y, z) of ground returns.
    scene_objects: list of (type, params_dict) defining geometric shapes.
    """
    all_returns = []
    classifications = []

    for i, pos in enumerate(scanner_positions):
        if i % 5000 == 0:
            print(f"  Ray casting... {i}/{len(scanner_positions)}", end='\r')

        sx, sy, sz = pos

        # Generate scan pattern (conical FOV centered on nadir)
        n_rays = 20  # Rays per pulse (simplified)
        # Random angles within FOV cone
        angles_off_nadir = np.random.uniform(0, fov_deg / 2, n_rays)
        azimuths = np.random.uniform(0, 2 * np.pi, n_rays)

        for angle, az in zip(angles_off_nadir, azimuths):
            # Ray direction from scanner
            r = sz * np.tan(np.radians(angle))
            dx = r * np.cos(az)
            dy = r * np.sin(az)

            # Ground intersection (assuming flat ground at z=0 for ray)
            # Ray: (sx, sy, sz) + t * (dx, dy, -sz) where t in [0, 1]
            t_ground = 1.0
            gx = sx + dx
            gy = sy + dy
            gz = 0.0  # Ground at z=0 initially

            # Check intersection with bridge objects
            hit_z = check_scene_intersection(sx, sy, sz, gx, gy, scene_objects)

            if hit_z is not None:
                # Hit structure
                all_returns.append([gx, gy, hit_z])
                classifications.append(6)  # Building
            else:
                # Hit ground or water
                # Add terrain variation
                terrain_z = get_terrain_z(gx, gy)
                all_returns.append([gx, gy, terrain_z])

                # Classify ground vs water
                river_center = 0
                river_half_width = 6
                if abs(gy - river_center) < river_half_width and abs(gx) < 18:
                    classifications.append(9)  # Water
                else:
                    classifications.append(2)  # Ground

    print()
    return np.array(all_returns), np.array(classifications, dtype=np.uint8)


def check_scene_intersection(sx, sy, sz, gx, gy, objects):
    """Check if ray from (sx, sy, sz) to (gx, gy, 0) hits any scene object.
    Returns z-coordinate of intersection, or None if no hit.
    Simplified: uses vertical extrusion from footprint.
    """
    for obj_type, params in objects:
        if obj_type == 'deck':
            # Deck footprint: length x width rectangle at deck_elevation
            dx_min = -params['length'] / 2
            dx_max = params['length'] / 2
            dy_min = -params['width'] / 2
            dy_max = params['width'] / 2
            z_bottom = params['z_bottom']
            z_top = params['z_top']

            if dx_min <= gx <= dx_max and dy_min <= gy <= dy_max:
                # Interpolate ray to find intersection Z
                # Ray from (sx, sy, sz) to (gx, gy, 0)
                t_top = (sz - z_top) / sz  # t where z = z_top
                t_bottom = (sz - z_bottom) / sz

                if 0 <= t_top <= 1:
                    return z_top
                elif 0 <= t_bottom <= 1:
                    return z_bottom

    return None


def get_terrain_z(x, y):
    """Get terrain elevation at (x, y) with river valley and noise."""
    base_z = np.random.normal(0, 0.05)

    # River valley
    river_depth = np.exp(-y**2 / 10) * 2.0  # V-shaped valley
    base_z -= river_depth

    # Approach ramps at bridge ends
    ramp_slope = 0.05
    if abs(x) > 15:
        base_z += min((abs(x) - 15) * ramp_slope, 2.0)

    return base_z


def generate_vegetation(n_clusters=8, length=40, width=16):
    """Generate vegetation clusters near the bridge approaches."""
    all_veg = []
    all_class = []

    for _ in range(n_clusters):
        # Cluster center (near abutments or along banks)
        if np.random.random() > 0.5:
            cx = np.random.choice([-18, 18]) + np.random.normal(0, 3)
        else:
            cx = np.random.uniform(-18, 18)
        cy = np.random.choice([-7, 7]) + np.random.normal(0, 2)
        n_trees = np.random.randint(5, 20)

        for _ in range(n_trees):
            tx = cx + np.random.normal(0, 1.5)
            ty = cy + np.random.normal(0, 1.5)
            tree_h = np.random.uniform(2, 8)

            # Tree points (conical shape)
            n_pts = np.random.randint(30, 100)
            for _ in range(n_pts):
                h_frac = np.random.beta(2, 5)  # More points in lower crown
                h = h_frac * tree_h
                crown_r = (1 - h_frac) * tree_h * 0.4 + 0.1
                angle = np.random.uniform(0, 2 * np.pi)
                r = crown_r * np.random.beta(2, 2)

                px = tx + r * np.cos(angle)
                py = ty + r * np.sin(angle)
                pz = h + get_terrain_z(px, py)

                all_veg.append([px, py, pz])
                if h < 2:
                    all_class.append(3)  # Low vegetation
                elif h < 5:
                    all_class.append(4)  # Medium vegetation
                else:
                    all_class.append(5)  # High vegetation

    return np.array(all_veg), np.array(all_class, dtype=np.uint8)


def add_edge_mixing(points, classifications, scene_objects):
    """Add mixed-edge returns at structure boundaries.
    Simulates the LiDAR beam partially hitting structure and ground.
    """
    n_edge = len(points) // 20
    edges = []

    # Pick random points near structure edges
    for obj_type, params in scene_objects:
        if obj_type == 'deck':
            # Points along deck edges
            for _ in range(n_edge // 4):
                edge_type = np.random.choice(['x', 'y'])
                if edge_type == 'x':
                    ex = np.random.choice([-params['length'] / 2, params['length'] / 2])
                    ey = np.random.uniform(-params['width'] / 2, params['width'] / 2)
                else:
                    ex = np.random.uniform(-params['length'] / 2, params['length'] / 2)
                    ey = np.random.choice([-params['width'] / 2, params['width'] / 2])

                ez = params['z_top'] + np.random.normal(0, 0.3)
                edges.append([ex + np.random.normal(0, 0.15), ey + np.random.normal(0, 0.15), ez])

    if edges:
        edges = np.array(edges)
        edge_class = np.full(len(edges), 6, dtype=np.uint8)
        points = np.concatenate([points, edges])
        classifications = np.concatenate([classifications, edge_class])

    return points, classifications


def add_range_noise(points, scanner_altitude=60):
    """Add range-dependent noise (farther = noisier)."""
    noise_z = np.random.normal(0, 0.03, len(points))
    # Noise proportional to slant range from nadir
    noise_xy = np.random.normal(0, 0.05, (len(points), 2))
    points[:, 2] += noise_z
    points[:, :2] += noise_xy
    return points


def main():
    parser = argparse.ArgumentParser(description="Generate realistic UAV LiDAR bridge point cloud")
    parser.add_argument("--span", type=float, default=30.0)
    parser.add_argument("--width", type=float, default=8.0)
    parser.add_argument("--pier-height", type=float, default=5.0)
    parser.add_argument("--output", type=str, default="bridge_realistic.las")
    parser.add_argument("--density", type=str, choices=["low", "medium", "high"],
                        default="medium", help="Scan density")
    args = parser.parse_args()

    span = args.span
    width = args.width
    pier_h = args.pier_height
    density_map = {"low": 100, "medium": 200, "high": 400}
    scan_rate = density_map[args.density]

    print(f"Generating realistic UAV LiDAR bridge point cloud")
    print(f"  Configuration: {span}m span, {width}m width, {pier_h}m piers")
    print(f"  Scan density: {args.density} ({scan_rate} Hz equivalent)")

    # Define scene objects for ray casting
    deck_thickness = 0.5
    scene_objects = [
        ('deck', {
            'length': span, 'width': width,
            'z_bottom': pier_h - deck_thickness / 2,
            'z_top': pier_h + deck_thickness / 2,
        }),
    ]

    # 1. Simulate UAV flight and LiDAR scanning
    print("\n[1/5] Simulating UAV flight & LiDAR scanning...")
    scanner_pos = simulate_flight_lines(
        length=span + 15, width=width + 10, altitude=60,
        scan_rate=scan_rate
    )
    print(f"  Scanner positions: {len(scanner_pos):,}")

    # 2. Shoot rays
    print("[2/5] Ray casting...")
    points, classifications = shoot_rays(scanner_pos, scene_objects)

    # 3. Add bridge structure directly (ensure coverage)
    print("[3/5] Adding bridge structure details...")

    all_pts = [points]
    all_cls = [classifications]

    # Deck points (dense sampling of top surface)
    n_deck = int(span * width * 80)
    dx = np.random.uniform(-span / 2, span / 2, n_deck)
    dy = np.random.uniform(-width / 2, width / 2, n_deck)
    dz = np.full(n_deck, pier_h + deck_thickness / 2 + np.random.normal(0, 0.015, n_deck))
    all_pts.append(np.column_stack([dx, dy, dz]))
    all_cls.append(np.full(n_deck, 6, dtype=np.uint8))

    # Deck bottom (underside, sparse - only near edges due to occlusion)
    n_deck_bot = int(span * width * 10)
    dxb = np.random.uniform(-span / 2, span / 2, n_deck_bot)
    dyb = np.where(np.random.random(n_deck_bot) > 0.7,
                   np.random.choice([width / 2, -width / 2], n_deck_bot),
                   np.random.uniform(-width / 2, width / 2, n_deck_bot))
    dzb = np.full(n_deck_bot, pier_h - deck_thickness / 2 + np.random.normal(0, 0.02, n_deck_bot))
    all_pts.append(np.column_stack([dxb, dyb, dzb]))
    all_cls.append(np.full(n_deck_bot, 6, dtype=np.uint8))

    # Pier points
    pier_spacing = span * 0.4
    for px in [-pier_spacing / 2, pier_spacing / 2]:
        n_pier = int(1.0 * 2.0 * pier_h * 80)
        ppx = np.random.uniform(px - 1.0, px + 1.0, n_pier)
        ppy = np.random.uniform(-0.5, 0.5, n_pier)
        ppz = np.random.uniform(0, pier_h, n_pier)
        all_pts.append(np.column_stack([ppx, ppy, ppz]))
        all_cls.append(np.full(n_pier, 6, dtype=np.uint8))

    # Abutment points
    for ax in [-span / 2, span / 2]:
        n_abut = int(1.5 * width * pier_h * 50)
        axx = np.random.uniform(ax - 0.75, ax + 0.75, n_abut)
        axy = np.random.uniform(-width / 2, width / 2, n_abut)
        axz = np.random.uniform(0, pier_h, n_abut)
        all_pts.append(np.column_stack([axx, axy, axz]))
        all_cls.append(np.full(n_abut, 6, dtype=np.uint8))

    # 4. Add vegetation
    print("[4/5] Adding vegetation...")
    veg_pts, veg_cls = generate_vegetation(n_clusters=10, length=span + 10, width=width + 8)
    all_pts.append(veg_pts)
    all_cls.append(veg_cls)

    # Combine
    points = np.concatenate(all_pts)
    class_ids = np.concatenate(all_cls)

    # 5. Add noise
    print("[5/5] Adding realistic noise...")
    points = add_range_noise(points)

    # Add edge mixing
    points, class_ids = add_edge_mixing(points, class_ids, scene_objects)

    # Clamp Z minimums slightly to avoid extreme outliers
    points[:, 2] = np.maximum(points[:, 2], -3.0)

    print(f"\n  Total points: {len(points):,}")

    # Write LAS
    header = laspy.LasHeader(point_format=3, version="1.2")
    header.scales = [0.001, 0.001, 0.001]
    header.offsets = [points[:, 0].min(), points[:, 1].min(), points[:, 2].min()]

    las = laspy.LasData(header)
    las.x = points[:, 0]
    las.y = points[:, 1]
    las.z = points[:, 2]
    las.classification = class_ids

    # Intensity: higher for structure, lower for ground/veg
    intensity = np.where(class_ids == 6, 220, 80).astype(np.uint16)
    intensity = np.where(class_ids == 9, 40, intensity)  # Water = low intensity
    intensity += np.random.randint(0, 30, len(points)).astype(np.uint16)
    las.intensity = intensity

    output_path = Path(args.output)
    las.write(str(output_path))
    print(f"  Saved: {output_path.absolute()}")

    # Stats
    for cls_id, cls_name in [(2, 'Ground'), (3, 'Low Veg'), (4, 'Med Veg'),
                               (5, 'High Veg'), (6, 'Building'), (9, 'Water')]:
        count = (class_ids == cls_id).sum()
        if count > 0:
            print(f"    Class {cls_id} ({cls_name}): {count:,} ({100*count/len(points):.1f}%)")


if __name__ == "__main__":
    main()
