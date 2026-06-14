#!/usr/bin/env python3
"""
Synthetic Bridge Point Cloud Generator
Generates a realistic point cloud of a simple beam bridge with:
- Deck (30m span, 8m width, 0.5m thickness)
- Two piers at 10m spacing (rectangular columns, 5m height)
- Two abutments at ends
- Ground plane beneath
- Gaussian noise to simulate real LiDAR data
Output: bridge.las (LAS 1.2 format)
"""

import numpy as np
import laspy
import argparse
import sys
from pathlib import Path


def generate_deck_points(length=30.0, width=8.0, thickness=0.5, deck_height=5.0,
                         density=200, noise_std=0.02):
    """Generate deck/road surface points."""
    # Top surface of deck
    n_points = int(length * width * density)
    x = np.random.uniform(-length / 2, length / 2, n_points)
    y = np.random.uniform(-width / 2, width / 2, n_points)
    z = np.full(n_points, deck_height + thickness / 2)

    # Add noise
    x += np.random.normal(0, noise_std, n_points)
    y += np.random.normal(0, noise_std, n_points)
    z += np.random.normal(0, noise_std * 0.5, n_points)

    # Bottom of deck
    n_bottom = int(n_points * 0.3)
    xb = np.random.uniform(-length / 2, length / 2, n_bottom)
    yb = np.random.uniform(-width / 2, width / 2, n_bottom)
    zb = np.full(n_bottom, deck_height - thickness / 2)
    xb += np.random.normal(0, noise_std, n_bottom)
    yb += np.random.normal(0, noise_std, n_bottom)
    zb += np.random.normal(0, noise_std * 0.5, n_bottom)

    # Side edges of deck (for thickness representation)
    n_side = int(n_points * 0.4)
    xs = np.random.uniform(-length / 2, length / 2, n_side)
    # Distribute between left and right edges
    side_y = np.where(np.random.random(n_side) > 0.5, width / 2, -width / 2)
    ys = side_y + np.random.normal(0, noise_std * 0.5, n_side)
    zs = np.random.uniform(deck_height - thickness / 2, deck_height + thickness / 2, n_side)
    xs += np.random.normal(0, noise_std, n_side)
    zs += np.random.normal(0, noise_std * 0.5, n_side)

    all_x = np.concatenate([x, xb, xs])
    all_y = np.concatenate([y, yb, ys])
    all_z = np.concatenate([z, zb, zs])

    return all_x, all_y, all_z


def generate_pier_points(pier_x, pier_y_base, pier_z_base=0.0,
                         pier_width=1.0, pier_length=2.0, pier_height=5.0,
                         density=500, noise_std=0.02):
    """Generate a single rectangular pier as point cloud."""
    n_points = int(pier_width * pier_length * pier_height * density)

    px = np.random.uniform(pier_x - pier_length / 2, pier_x + pier_length / 2, n_points)
    py = np.random.uniform(pier_y_base - pier_width / 2, pier_y_base + pier_width / 2, n_points)
    pz = np.random.uniform(pier_z_base, pier_z_base + pier_height, n_points)

    px += np.random.normal(0, noise_std, n_points)
    py += np.random.normal(0, noise_std, n_points)
    pz += np.random.normal(0, noise_std, n_points)

    return px, py, pz


def generate_abutment_points(x_pos, width=8.0, height=5.0, depth=1.5,
                             density=400, noise_std=0.02):
    """Generate an abutment at one end of the bridge."""
    n_points = int(width * height * depth * density)

    half_depth = depth / 2
    ax = np.random.uniform(x_pos - half_depth, x_pos + half_depth, n_points)
    ay = np.random.uniform(-width / 2, width / 2, n_points)
    az = np.random.uniform(0, height, n_points)

    ax += np.random.normal(0, noise_std, n_points)
    ay += np.random.normal(0, noise_std, n_points)
    az += np.random.normal(0, noise_std, n_points)

    return ax, ay, az


def generate_ground_points(length=35.0, width=12.0, height=0.0,
                           density=50, noise_std=0.05):
    """Generate ground plane points under and around the bridge."""
    n_points = int(length * width * density)

    gx = np.random.uniform(-length / 2, length / 2, n_points)
    gy = np.random.uniform(-width / 2, width / 2, n_points)
    gz = np.full(n_points, height)

    # Sloped ground toward river center (gentle V-shape)
    river_depth = np.abs(gy) * 0.3
    gz -= river_depth

    gx += np.random.normal(0, noise_std, n_points)
    gy += np.random.normal(0, noise_std, n_points)
    gz += np.random.normal(0, noise_std * 0.5, n_points)

    return gx, gy, gz


def add_classification(points_dict):
    """Add LAS classification labels."""
    # We'll store classification info for clarity
    # LAS classification: 1=unclassified, 2=ground, 6=building (bridge structure)
    pass


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic bridge point cloud")
    parser.add_argument("--span", type=float, default=30.0, help="Bridge span in meters")
    parser.add_argument("--width", type=float, default=8.0, help="Deck width in meters")
    parser.add_argument("--pier-height", type=float, default=5.0, help="Pier height in meters")
    parser.add_argument("--output", type=str, default="bridge.las", help="Output LAS file path")
    parser.add_argument("--noise", type=float, default=0.02, help="Noise standard deviation")
    parser.add_argument("--density", type=float, default=200, help="Point density per sq meter")
    args = parser.parse_args()

    print(f"Generating synthetic bridge point cloud:")
    print(f"  Span: {args.span}m, Width: {args.width}m, Pier Height: {args.pier_height}m")

    span = args.span
    width = args.width
    pier_h = args.pier_height
    noise = args.noise

    all_x, all_y, all_z = [], [], []
    classifications = []

    # 1. Deck
    print("  Generating deck...")
    dx, dy, dz = generate_deck_points(
        length=span, width=width, thickness=0.5,
        deck_height=pier_h, density=args.density, noise_std=noise
    )
    all_x.append(dx); all_y.append(dy); all_z.append(dz)
    classifications.append(np.full(len(dx), 6, dtype=np.uint8))  # Building

    # 2. Two piers at ~1/3 and 2/3 span
    pier_spacing = span * 0.4
    pier_x_positions = [-pier_spacing / 2, pier_spacing / 2]
    for i, px in enumerate(pier_x_positions):
        print(f"  Generating pier {i + 1} at x={px:.1f}m...")
        ppx, ppy, ppz = generate_pier_points(
            pier_x=px, pier_y_base=0, pier_z_base=0,
            pier_width=1.0, pier_length=2.0, pier_height=pier_h,
            density=args.density * 2, noise_std=noise
        )
        all_x.append(ppx); all_y.append(ppy); all_z.append(ppz)
        classifications.append(np.full(len(ppx), 6, dtype=np.uint8))

    # 3. Two abutments at ends
    for i, ax_pos in enumerate([-span / 2, span / 2]):
        print(f"  Generating abutment {i + 1} at x={ax_pos:.1f}m...")
        ax, ay, az = generate_abutment_points(
            x_pos=ax_pos, width=width, height=pier_h,
            density=args.density, noise_std=noise
        )
        all_x.append(ax); all_y.append(ay); all_z.append(az)
        classifications.append(np.full(len(ax), 6, dtype=np.uint8))

    # 4. Ground
    print("  Generating ground points...")
    gx, gy, gz = generate_ground_points(
        length=span + 5, width=width + 4, density=args.density // 4,
        noise_std=noise * 2
    )
    all_x.append(gx); all_y.append(gy); all_z.append(gz)
    classifications.append(np.full(len(gx), 2, dtype=np.uint8))  # Ground

    # Combine
    X = np.concatenate(all_x)
    Y = np.concatenate(all_y)
    Z = np.concatenate(all_z)
    class_ids = np.concatenate(classifications)

    print(f"  Total points: {len(X):,}")

    # Write LAS file
    header = laspy.LasHeader(point_format=3, version="1.2")
    header.scales = [0.001, 0.001, 0.001]
    header.offsets = [X.min(), Y.min(), Z.min()]

    las = laspy.LasData(header)
    las.x = X
    las.y = Y
    las.z = Z
    las.classification = class_ids
    # Intensity: higher for bridge structure
    intensity = np.where(class_ids == 6, 200, 80).astype(np.uint16)
    intensity += np.random.randint(0, 40, len(X)).astype(np.uint16)
    las.intensity = intensity

    output_path = Path(args.output)
    las.write(str(output_path))
    print(f"\nSaved point cloud to: {output_path.absolute()}")
    print(f"  Points: {len(X):,}")
    print(f"  Bounds X: [{X.min():.2f}, {X.max():.2f}] m")
    print(f"  Bounds Y: [{Y.min():.2f}, {Y.max():.2f}] m")
    print(f"  Bounds Z: [{Z.min():.2f}, {Z.max():.2f}] m")


if __name__ == "__main__":
    main()
