#!/usr/bin/env python3
"""
Bridge Point Cloud Processing Pipeline
Processes UAV-derived point clouds to extract bridge structural parameters.

Pipeline:
  1. Load & downsample point cloud (voxel grid 0.1m)
  2. Multi-plane RANSAC: ground (lowest), deck (highest horizontal), other planes
  3. Remove ground & deck planes, cluster remainder -> piers & abutments
  4. Extract deck centerline, pier positions
  5. Compute key dimensions
  6. Output bridge_params.json for downstream FreeCAD modeling
"""

import numpy as np
import open3d as o3d
import laspy
import json
import argparse
from pathlib import Path
from scipy.spatial import ConvexHull
from scipy.optimize import curve_fit


def load_point_cloud(las_path):
    """Load LAS/LAZ point cloud and return open3d PointCloud + metadata."""
    print(f"[1/6] Loading point cloud: {las_path}")
    las = laspy.read(las_path)

    x = np.array(las.x, dtype=np.float64)
    y = np.array(las.y, dtype=np.float64)
    z = np.array(las.z, dtype=np.float64)

    points = np.column_stack([x, y, z])

    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(points)

    print(f"  Loaded {len(points):,} points")
    print(f"  Bounds X: [{x.min():.2f}, {x.max():.2f}]")
    print(f"  Bounds Y: [{y.min():.2f}, {y.max():.2f}]")
    print(f"  Bounds Z: [{z.min():.2f}, {z.max():.2f}]")

    return pcd, points


def downsample(pcd, voxel_size=0.1):
    """Downsample point cloud using voxel grid filter."""
    print(f"\n[2/6] Downsampling to {voxel_size}m resolution...")
    n_before = len(pcd.points)
    pcd_down = pcd.voxel_down_sample(voxel_size)
    n_after = len(pcd_down.points)
    print(f"  {n_before:,} -> {n_after:,} points ({100 * n_after / n_before:.1f}%)")
    return pcd_down


def segment_multiple_planes(pcd, distance_threshold=0.15, max_planes=5):
    """Segment multiple planes from point cloud using iterative RANSAC.

    Returns list of planes sorted by Z elevation, each with:
      {model: [a,b,c,d], inliers: indices, z_median: float, n_points: int, pcd: o3d.PointCloud}
    """
    print(f"\n[3/6] Multi-plane RANSAC segmentation...")

    remaining = pcd
    planes = []
    all_points = np.asarray(pcd.points)

    for i in range(max_planes):
        if len(remaining.points) < 100:
            break
        try:
            plane_model, inliers = remaining.segment_plane(
                distance_threshold=distance_threshold,
                ransac_n=3,
                num_iterations=1500
            )
            inlier_pcd = remaining.select_by_index(inliers)
            inlier_pts = np.asarray(inlier_pcd.points)
            z_median = np.median(inlier_pts[:, 2])

            a, b, c, d = plane_model
            # Ensure normal points upward
            if c < 0:
                a, b, c, d = -a, -b, -c, -d
                plane_model = [a, b, c, d]

            planes.append({
                'model': [float(a), float(b), float(c), float(d)],
                'inliers': inliers,
                'z_median': float(z_median),
                'n_points': len(inliers),
                'pcd': inlier_pcd,
            })

            # Remove inliers for next iteration
            remaining = remaining.select_by_index(inliers, invert=True)
        except RuntimeError:
            break

    # Sort by Z elevation
    planes.sort(key=lambda p: p['z_median'])

    print(f"  Found {len(planes)} planes:")
    for i, p in enumerate(planes):
        a, b, c, d = p['model']
        horizontal = "H" if abs(c) > 0.7 else "V"
        print(f"    Plane {i}: z={p['z_median']:.2f}m, n={p['n_points']:,}, "
              f"normal=({a:.3f},{b:.3f},{c:.3f}) [{horizontal}]")

    return planes, remaining


def classify_planes(planes):
    """Classify segmented planes into ground, deck, and others.

    Returns:
        ground_plane: lowest near-horizontal plane
        deck_plane: highest near-horizontal plane
        other_planes: everything else
    """
    horizontal_planes = [p for p in planes if abs(p['model'][2]) > 0.7]

    if not horizontal_planes:
        print("  Warning: no horizontal planes found!")
        return None, None, planes

    # Ground = lowest horizontal plane (or just the lowest plane)
    ground_plane = horizontal_planes[0]

    # Deck = highest horizontal plane
    if len(horizontal_planes) >= 2:
        deck_plane = horizontal_planes[-1]
    else:
        # Only one horizontal plane - if it's high, it's deck; if low, it's ground
        all_pts = np.concatenate([np.asarray(p['pcd'].points) for p in planes])
        z_max = all_pts[:, 2].max()
        if ground_plane['z_median'] > z_max * 0.5:
            deck_plane = ground_plane
            ground_plane = None
        else:
            deck_plane = None

    # Filter out planes that are subsets of deck or ground
    other_planes = [p for p in planes if p is not ground_plane and p is not deck_plane]

    if ground_plane:
        print(f"  Ground plane: z={ground_plane['z_median']:.2f}m ({ground_plane['n_points']:,} pts)")
    if deck_plane:
        print(f"  Deck plane: z={deck_plane['z_median']:.2f}m ({deck_plane['n_points']:,} pts)")

    return ground_plane, deck_plane, other_planes


def compute_deck_from_plane(deck_plane):
    """Extract deck geometry (centerline, dimensions) from deck plane inliers.

    Uses DBSCAN on XY projection to isolate the densest cluster (actual deck)
    from sparse outliers at similar elevations (flight line artifacts).
    """
    if deck_plane is None:
        return None

    points = np.asarray(deck_plane['pcd'].points)
    z_mean = points[:, 2].mean()

    # --- Density-based filtering: keep only the densest XY cluster ---
    xy = points[:, :2]

    # DBSCAN in XY space to find the main deck cluster
    xy_pcd = o3d.geometry.PointCloud()
    xy_pcd.points = o3d.utility.Vector3dVector(np.column_stack([xy, np.zeros(len(xy))]))
    labels = np.array(xy_pcd.cluster_dbscan(eps=1.5, min_points=50, print_progress=False))

    # Find the largest cluster (the deck)
    unique_labels = set(labels)
    unique_labels.discard(-1)  # Remove noise
    if unique_labels:
        largest_label = max(unique_labels, key=lambda l: (labels == l).sum())
        deck_mask = labels == largest_label
        points = points[deck_mask]
        print(f"  Deck density filter: {deck_mask.sum():,}/{len(labels):,} points in main cluster")
        xy = points[:, :2]

    if len(points) < 50:
        return None

    # PCA on XY for main axis
    centered = xy - xy.mean(axis=0)
    cov = np.cov(centered.T)
    eigenvalues, eigenvectors = np.linalg.eigh(cov)

    main_axis = eigenvectors[:, -1]  # Longest direction
    perpendicular = eigenvectors[:, 0]  # Shortest direction

    # Project onto axes
    proj_main = centered @ main_axis
    length = float(proj_main.max() - proj_main.min())
    proj_perp = centered @ perpendicular
    width = float(proj_perp.max() - proj_perp.min())

    center_2d = xy.mean(axis=0)
    half_len = length / 2

    start_2d = center_2d - main_axis * half_len
    end_2d = center_2d + main_axis * half_len

    return {
        'axis_direction': main_axis.tolist(),
        'perpendicular_direction': perpendicular.tolist(),
        'length': round(length, 2),
        'width': round(width, 2),
        'center': [float(center_2d[0]), float(center_2d[1]), float(z_mean)],
        'start': [float(start_2d[0]), float(start_2d[1]), float(z_mean)],
        'end': [float(end_2d[0]), float(end_2d[1]), float(z_mean)],
        'elevation': round(float(z_mean), 2),
    }


def find_piers_abutments(non_plane_pcd, deck_elevation, ground_elevation,
                         deck_info=None, eps=0.5, min_points=30,
                         original_pcd=None):
    """Cluster remaining points (after removing ground and deck) to find piers and abutments.

    Uses deck extent to distinguish:
    - Piers: vertical structures within the deck span (interior)
    - Abutments: vertical structures at the deck ends

    When RANSAC absorbs pier base points into ground plane, falls back to
    Z-based filtering on the original point cloud for vertical structure detection.
    """
    print(f"\n[4/6] Finding piers and abutments...")

    points = np.asarray(non_plane_pcd.points)

    # ── Primary detection from non-plane points ──
    piers, abutments = _cluster_piers(points, deck_elevation, ground_elevation,
                                       deck_info, eps, min_points)

    # ── Fallback: if few/no piers found, search original cloud by Z range ──
    if len(piers) < 1 and original_pcd is not None:
        print("  Primary search found 0 piers, trying Z-based fallback...")
        orig_pts = np.asarray(original_pcd.points)

        # Use deck XY extent to narrow search area
        if deck_info:
            d_start = np.array(deck_info['start'][:2])
            d_end = np.array(deck_info['end'][:2])
            d_axis = np.array(deck_info['axis_direction'])
            d_perp = np.array(deck_info['perpendicular_direction'])
            d_len = deck_info['length']
            d_wid = deck_info['width']

            # Project all points onto bridge axis
            proj_axis = (orig_pts[:, :2] - d_start) @ d_axis
            proj_perp = (orig_pts[:, :2] - d_start) @ d_perp

            # XY mask: within deck bounds + 2m margin
            xy_mask = (proj_axis > -2) & (proj_axis < d_len + 2) & \
                      (np.abs(proj_perp) < d_wid/2 + 2)

            # Z mask: exclude ground, include pier tops just below deck
            z_mask = (orig_pts[:, 2] > ground_elevation + 0.2) & \
                     (orig_pts[:, 2] < deck_elevation - 0.05)

            mid_pts = orig_pts[xy_mask & z_mask]
            n_filtered = len(mid_pts)
            print(f"  XY+Z-filtered cloud: {n_filtered:,} points in bridge footprint")

            if n_filtered > min_points * 3:
                piers2, abutments2 = _cluster_piers(mid_pts, deck_elevation,
                                                      ground_elevation, deck_info,
                                                      eps * 0.8, min_points)
                # Filter by height: piers must be taller than 1/3 clearance
                min_pier_h = max(1.5, (deck_elevation - ground_elevation) * 0.3)
                valid_piers = [p for p in piers2 if p.get('height', 0) > min_pier_h]
                if valid_piers:
                    piers = valid_piers
                    print(f"  Fallback found {len(piers)} piers ({len(piers2)} candidates, "
                          f"min_height={min_pier_h:.1f}m)")
                if len(abutments2) > len(abutments):
                    abutments = abutments2
        else:
            # No deck info, use simple Z range
            z_mask = (orig_pts[:, 2] > ground_elevation + 0.3) & \
                     (orig_pts[:, 2] < deck_elevation - 0.3)
            mid_pts = orig_pts[z_mask]
            if len(mid_pts) > min_points:
                piers2, _ = _cluster_piers(mid_pts, deck_elevation,
                                            ground_elevation, deck_info, eps, min_points)
                if piers2:
                    piers = piers2

    return piers, abutments


def _cluster_piers(points, deck_elevation, ground_elevation, deck_info,
                   eps, min_points):
    """Internal: cluster points into piers and abutments."""
    if len(points) < min_points:
        return [], []

    # Get deck extent
    deck_x_min, deck_x_max = None, None
    if deck_info:
        deck_start_x = deck_info['start'][0]
        deck_end_x = deck_info['end'][0]
        deck_x_min = min(deck_start_x, deck_end_x)
        deck_x_max = max(deck_start_x, deck_end_x)

    # DBSCAN on points
    pcd_temp = o3d.geometry.PointCloud()
    pcd_temp.points = o3d.utility.Vector3dVector(points)
    labels = np.array(pcd_temp.cluster_dbscan(
        eps=eps, min_points=min_points, print_progress=False
    ))

    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    print(f"  DBSCAN found {n_clusters} clusters in non-plane points")

    piers = []
    abutments = []

    for label in range(n_clusters):
        mask = labels == label
        cluster_pts = points[mask]
        if len(cluster_pts) < min_points:
            continue

        z = cluster_pts[:, 2]
        centroid = cluster_pts.mean(axis=0)
        z_range = z.ptp()
        z_min = z.min()
        z_max = z.max()

        # Compute flatness via PCA
        centered = cluster_pts - centroid
        cov = np.cov(centered.T)
        if cov.shape == (3, 3):
            eigenvalues = np.sort(np.linalg.eigvalsh(cov))
            flatness = float(eigenvalues[0] / eigenvalues[2]) if eigenvalues[2] > 0 else 1.0
        else:
            flatness = 1.0

        total_height = z_range
        cluster_x = centroid[0]

        # Position-based classification
        is_at_end = False
        if deck_x_min is not None and deck_x_max is not None:
            margin = (deck_x_max - deck_x_min) * 0.15  # 15% margin at each end
            is_at_end = (cluster_x < deck_x_min + margin or
                         cluster_x > deck_x_max - margin)

        if total_height > 1.5 and len(cluster_pts) > 100:
            if is_at_end:
                abutments.append({
                    'centroid': centroid.tolist(),
                    'x': float(centroid[0]),
                    'y': float(centroid[1]),
                    'z': float(centroid[2]),
                    'z_min': float(z_min),
                    'z_max': float(z_max),
                    'height': round(float(total_height), 2),
                    'n_points': len(cluster_pts),
                    'width': round(float(np.sqrt(eigenvalues[1])) * 2 if len(eigenvalues) > 1 else 0, 2),
                })
            else:
                piers.append({
                    'centroid': centroid.tolist(),
                    'x': float(centroid[0]),
                    'y': float(centroid[1]),
                    'z': float(centroid[2]),
                    'z_min': float(z_min),
                    'z_max': float(z_max),
                    'height': round(float(total_height), 2),
                    'n_points': len(cluster_pts),
                    'flatness': flatness,
                })

    piers.sort(key=lambda p: p['n_points'], reverse=True)
    abutments.sort(key=lambda p: p['n_points'], reverse=True)

    print(f"  Piers: {len(piers)} detected")
    for p in piers:
        print(f"    - ({p['x']:.1f}, {p['y']:.1f}), h={p['height']:.2f}m, {p['n_points']:,} pts")

    print(f"  Abutments: {len(abutments)} detected")
    for a in abutments:
        print(f"    - ({a['x']:.1f}, {a['y']:.1f}), h={a['height']:.2f}m, {a['n_points']:,} pts")

    return piers, abutments


def extract_dimensions(deck_info, piers, ground_elevation, deck_elevation, all_points):
    """Compute final bridge dimensions."""
    print(f"\n[5/6] Computing key dimensions...")

    dims = {}

    # Deck dimensions from PCA of deck plane
    if deck_info:
        dims['span_length'] = deck_info['length']
        dims['deck_width'] = deck_info['width']
        dims['deck_elevation'] = deck_info['elevation']
    else:
        # Fallback: XY bounding box of high points
        high_pts = all_points[all_points[:, 2] > ground_elevation + 2.0]
        if len(high_pts) > 0:
            xy = high_pts[:, :2]
            centered = xy - xy.mean(axis=0)
            cov = np.cov(centered.T)
            eigenvalues, eigenvectors = np.linalg.eigh(cov)
            main_axis = eigenvectors[:, -1]
            perp = eigenvectors[:, 0]
            proj_main = centered @ main_axis
            proj_perp = centered @ perp
            dims['span_length'] = round(float(proj_main.max() - proj_main.min()), 2)
            dims['deck_width'] = round(float(proj_perp.max() - proj_perp.min()), 2)
        else:
            dims['span_length'] = 0
            dims['deck_width'] = 0
        dims['deck_elevation'] = round(float(deck_elevation), 2)

    dims['ground_elevation'] = round(float(ground_elevation), 2)
    dims['clearance_under_bridge'] = round(dims['deck_elevation'] - dims['ground_elevation'], 2)

    # Pier info
    dims['num_piers'] = len(piers)
    if len(piers) >= 2:
        sorted_piers = sorted(piers, key=lambda p: p['x'])
        spacings = []
        for i in range(len(sorted_piers) - 1):
            dx = sorted_piers[i + 1]['x'] - sorted_piers[i]['x']
            dy = sorted_piers[i + 1]['y'] - sorted_piers[i]['y']
            spacing = np.sqrt(dx ** 2 + dy ** 2)
            spacings.append(round(float(spacing), 2))
        dims['pier_spacings'] = spacings
    else:
        dims['pier_spacings'] = []

    # Global bounding box
    dims['bbox'] = {
        'x_min': round(float(all_points[:, 0].min()), 2),
        'x_max': round(float(all_points[:, 0].max()), 2),
        'y_min': round(float(all_points[:, 1].min()), 2),
        'y_max': round(float(all_points[:, 1].max()), 2),
        'z_min': round(float(all_points[:, 2].min()), 2),
        'z_max': round(float(all_points[:, 2].max()), 2),
    }

    print(f"  Span length: {dims['span_length']} m")
    print(f"  Deck width: {dims['deck_width']} m")
    print(f"  Deck elevation: {dims['deck_elevation']} m")
    print(f"  Clearance: {dims['clearance_under_bridge']} m")
    print(f"  Number of piers: {dims['num_piers']}")
    if dims['pier_spacings']:
        print(f"  Pier spacings: {dims['pier_spacings']} m")

    return dims


def determine_bridge_type(deck_info, piers, args_type, deck_points=None):
    """Determine bridge type from geometry and curvature analysis."""
    if args_type != "auto":
        return args_type

    # Check for arch via curvature detection
    if deck_points is not None and len(deck_points) > 100:
        is_arch, curvature_score = detect_arch_curvature(deck_points)
        if is_arch:
            print(f"  Arch curvature detected (score={curvature_score:.3f})")
            return "arch"

    if deck_info and deck_info['length'] < 20 and len(piers) == 0:
        return "arch"
    return "beam"


# ============================================================================
# NEW: Terrain Profile Extraction
# ============================================================================

def extract_terrain_profile(ground_plane, deck_info, num_samples=40):
    """Extract terrain elevation profile along bridge centerline.

    Uses ground plane points and samples elevation along the bridge axis
    to build a longitudinal terrain profile for foundation design.

    Args:
        ground_plane: dict with 'pcd' (ground point cloud)
        deck_info: dict with 'start', 'end', 'axis_direction'
        num_samples: number of sample points along centerline

    Returns:
        List of {x, z} points representing terrain profile
    """
    if ground_plane is None or deck_info is None:
        return []

    ground_pts = np.asarray(ground_plane['pcd'].points)

    # Bridge centerline in XY
    start = np.array(deck_info['start'][:2])
    end = np.array(deck_info['end'][:2])
    axis = np.array(deck_info['axis_direction'])
    length = deck_info['length']

    profile = []
    for i in range(num_samples):
        t = i / (num_samples - 1)
        sample_xy = start + t * (end - start)

        # Find ground points within 1m bandwidth of this sample
        perp = np.array([-axis[1], axis[0]])
        distances = np.abs((ground_pts[:, :2] - sample_xy) @ perp)
        along_dist = np.abs((ground_pts[:, :2] - sample_xy) @ axis)

        nearby = ground_pts[(distances < 1.5) & (along_dist < 2.0)]
        if len(nearby) > 5:
            # Use median Z of nearby ground points
            z_median = float(np.median(nearby[:, 2]))
            profile.append({
                "x": round(float(sample_xy[0]), 2),
                "y": round(float(sample_xy[1]), 2),
                "z": round(z_median, 2),
                "n_points": len(nearby),
            })

    if len(profile) > 0:
        z_range = max(p["z"] for p in profile) - min(p["z"] for p in profile)
        print(f"\n  Terrain profile: {len(profile)} samples, "
              f"Z range: {z_range:.2f}m, "
              f"min Z: {min(p['z'] for p in profile):.2f}m, "
              f"max Z: {max(p['z'] for p in profile):.2f}m")

    return profile


# ============================================================================
# NEW: Vegetation Pre-filtering
# ============================================================================

def filter_by_classification(points, las_file_path, pcd=None):
    """Use LAS classification labels to exclude vegetation points.

    LAS classification:
      2 = Ground, 3 = Low Vegetation, 4 = Medium Vegetation,
      5 = High Vegetation, 6 = Building (bridge structure), 9 = Water

    Returns:
        structure_pcd: points classified as structure/ground/water
        veg_pcd: points classified as vegetation (excluded from pier detection)
        veg_mask: boolean mask on original points array
    """
    try:
        las = laspy.read(las_file_path)
        if not hasattr(las, 'classification'):
            print("  No classification data in LAS file, skipping veg filter")
            return pcd, None, np.zeros(len(points), dtype=bool)

        class_ids = np.array(las.classification)

        # Need to align with downsampled points
        if len(class_ids) != len(points):
            print(f"  Classification array size mismatch ({len(class_ids)} vs {len(points)}), "
                  f"applying filter on raw points")
            # Create mask for vegetation classes
            veg_classes = [3, 4, 5]
            veg_mask_raw = np.isin(class_ids, veg_classes)
            structure_mask_raw = ~veg_mask_raw

            veg_count = veg_mask_raw.sum()
            total = len(class_ids)
            print(f"  Vegetation points: {veg_count:,}/{total:,} ({100*veg_count/total:.1f}%)")

            # For downsampled points, approximate by spatial matching
            # Return masks for raw points — caller handles alignment
            return pcd, veg_mask_raw, structure_mask_raw
        else:
            veg_classes = [3, 4, 5]
            veg_mask = np.isin(class_ids, veg_classes)
            veg_count = veg_mask.sum()
            total = len(class_ids)
            print(f"  Vegetation points: {veg_count:,}/{total:,} ({100*veg_count/total:.1f}%)")

            if veg_count > 0 and pcd is not None:
                veg_pts = points[veg_mask]
                structure_pts = points[~veg_mask]
                veg_pcd = o3d.geometry.PointCloud()
                veg_pcd.points = o3d.utility.Vector3dVector(veg_pts)
                pcd_down = o3d.geometry.PointCloud()
                pcd_down.points = o3d.utility.Vector3dVector(structure_pts)
                print(f"  Structure/non-veg points after filter: {len(structure_pts):,}")
                return pcd_down, veg_pcd, veg_mask

    except Exception as e:
        print(f"  Classification filtering skipped: {e}")

    return pcd, None, np.zeros(len(points), dtype=bool)


# ============================================================================
# NEW: Arch Shape Detection
# ============================================================================

def detect_arch_curvature(deck_points, min_curvature=0.003, min_r2=0.6):
    """Detect if deck surface follows a parabolic arch shape.

    Fits a 2nd-order polynomial (parabola) to the deck points along the
    bridge axis and checks if the curvature is significant enough to be an arch.

    Args:
        deck_points: (N, 3) array of deck plane points
        min_curvature: minimum quadratic coefficient to classify as arch
        min_r2: minimum R² for the parabolic fit

    Returns:
        (is_arch: bool, curvature_score: float)
    """
    if len(deck_points) < 50:
        return False, 0.0

    # Project to 2D: along-axis (X) vs elevation (Z)
    xy = deck_points[:, :2]
    z = deck_points[:, 2]

    # Find principal axis
    centered = xy - xy.mean(axis=0)
    cov = np.cov(centered.T)
    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    main_axis = eigenvectors[:, -1]

    # Project points onto main axis
    proj = centered @ main_axis
    x_norm = (proj - proj.min()) / (proj.max() - proj.min() + 1e-10)

    # Fit 2nd order polynomial: z = a*x^2 + b*x + c
    try:
        coeffs = np.polyfit(x_norm, z, 2)
        a, b, c = coeffs

        # R² of fit
        z_pred = np.polyval(coeffs, x_norm)
        ss_res = np.sum((z - z_pred) ** 2)
        ss_tot = np.sum((z - z.mean()) ** 2)
        r2 = 1 - ss_res / (ss_tot + 1e-10)

        # Curvature magnitude (absolute 2nd derivative)
        curvature = abs(a)

        # Arch bridge: significant negative curvature (deck arches upward)
        # or positive curvature with strong R²
        is_arch = (curvature > min_curvature and r2 > min_r2)

        return is_arch, round(float(curvature), 4)

    except Exception:
        return False, 0.0


# ============================================================================
# NEW: Multi-span detection
# ============================================================================

def compute_multi_span(piers, deck_info):
    """Compute individual span segments for multi-span bridges.

    Args:
        piers: list of pier dicts with 'x' position
        deck_info: dict with 'start' and 'end'

    Returns:
        List of span lengths between consecutive supports (abutment-pier, pier-pier, pier-abutment)
    """
    if not piers or not deck_info:
        return []

    # Sort piers by X position
    sorted_piers = sorted(piers, key=lambda p: p['x'])

    start_x = min(deck_info['start'][0], deck_info['end'][0])
    end_x = max(deck_info['start'][0], deck_info['end'][0])

    spans = []
    prev_x = start_x

    for pier in sorted_piers:
        span_len = pier['x'] - prev_x
        if span_len > 0.5:  # Minimum meaningful span
            spans.append(round(float(span_len), 2))
        prev_x = pier['x']

    # Final span to end abutment
    final_span = end_x - prev_x
    if final_span > 0.5:
        spans.append(round(float(final_span), 2))

    return spans


def main():
    parser = argparse.ArgumentParser(
        description="Process UAV point cloud to extract bridge structural parameters"
    )
    parser.add_argument("input", help="Path to input LAS/LAZ point cloud")
    parser.add_argument("--output", "-o", default="bridge_params.json",
                        help="Output JSON path (default: bridge_params.json)")
    parser.add_argument("--voxel-size", type=float, default=0.1,
                        help="Voxel grid size (default: 0.1m)")
    parser.add_argument("--ransac-threshold", type=float, default=0.15,
                        help="RANSAC distance threshold (default: 0.15m)")
    parser.add_argument("--dbscan-eps", type=float, default=0.5,
                        help="DBSCAN epsilon for pier clustering (default: 0.5m)")
    parser.add_argument("--dbscan-min-points", type=int, default=30,
                        help="DBSCAN minimum points (default: 30)")
    parser.add_argument("--bridge-type", choices=["beam", "arch", "auto"], default="auto",
                        help="Bridge type hint (default: auto)")
    parser.add_argument("--no-class-filter", action="store_true",
                        help="Disable classification-based vegetation filtering")
    parser.add_argument("--min-pier-height", type=float, default=1.5,
                        help="Minimum height (m) for pier detection (default: 1.5)")
    args = parser.parse_args()

    # 1. Load
    pcd, raw_points = load_point_cloud(args.input)

    # 2. Downsample
    pcd_down = downsample(pcd, voxel_size=args.voxel_size)
    all_points = np.asarray(pcd_down.points)

    # 2.5 Vegetation pre-filtering (if LAS has classification)
    veg_mask = None
    if not args.no_class_filter:
        print(f"\n[2.5/6] Classification-based vegetation filtering...")
        pcd_down, veg_pcd, veg_mask_raw = filter_by_classification(
            raw_points, args.input, pcd_down
        )
        if pcd_down is not None:
            all_points = np.asarray(pcd_down.points)
        print(f"  Points after veg filter: {len(all_points):,}")

    # 3. Multi-plane RANSAC
    planes, remaining_pcd = segment_multiple_planes(
        pcd_down, distance_threshold=args.ransac_threshold
    )
    ground_plane, deck_plane, other_planes = classify_planes(planes)

    # Extract elevations
    ground_z = ground_plane['z_median'] if ground_plane else float(all_points[:, 2].min())
    deck_z = deck_plane['z_median'] if deck_plane else float(all_points[:, 2].max())
    deck_info = compute_deck_from_plane(deck_plane)

    # If deck not found by RANSAC, estimate from top of point cloud
    if deck_info is None:
        print("\n  Deck plane not found by RANSAC, using top-surface estimate...")
        high_mask = all_points[:, 2] > deck_z - 0.5
        high_pts = all_points[high_mask]
        if len(high_pts) > 100:
            deck_pcd = o3d.geometry.PointCloud()
            deck_pcd.points = o3d.utility.Vector3dVector(high_pts)
            deck_plane = {'pcd': deck_pcd, 'z_median': deck_z, 'n_points': len(high_pts),
                          'model': [0, 0, 1, -deck_z]}
            deck_info = compute_deck_from_plane(deck_plane)

    # 3.5 Terrain profile extraction
    print(f"\n[3.5/6] Extracting terrain profile...")
    terrain_profile = extract_terrain_profile(ground_plane, deck_info)

    # 4. Find piers in remaining points (with Z-based fallback)
    piers, abutments = find_piers_abutments(
        remaining_pcd, deck_z, ground_z,
        deck_info=deck_info,
        eps=args.dbscan_eps, min_points=args.dbscan_min_points,
        original_pcd=pcd  # Use original (pre-downsample) for fallback
    )

    # 4.5 Multi-span computation
    span_segments = compute_multi_span(piers, deck_info)
    if span_segments and len(span_segments) > 1:
        print(f"\n  Multi-span segments: {span_segments} ({len(span_segments)} spans)")

    # 5. Extract dimensions
    dimensions = extract_dimensions(deck_info, piers, ground_z, deck_z, all_points)
    dimensions['span_segments'] = span_segments
    dimensions['num_spans'] = len(span_segments) if span_segments else 1

    # 6. Determine bridge type (with curvature analysis)
    deck_pts = np.asarray(deck_plane['pcd'].points) if deck_plane else np.array([])
    bridge_type = determine_bridge_type(deck_info, piers, args.bridge_type,
                                         deck_points=deck_pts)

    # Build output parameters
    params = {
        "bridge_type": bridge_type,
        "dimensions": dimensions,
        "centerline": deck_info,
        "ground_elevation": round(float(ground_z), 2),
        "deck_elevation": round(float(deck_z), 2),
        "num_piers": len(piers),
        "pier_positions": piers,
        "abutment_positions": abutments,
        "terrain_profile": terrain_profile,
        "span_segments": span_segments,
        "processing_params": {
            "voxel_size": args.voxel_size,
            "ransac_threshold": args.ransac_threshold,
            "dbscan_eps": args.dbscan_eps,
            "dbscan_min_points": args.dbscan_min_points,
            "min_pier_height": args.min_pier_height,
            "class_filter_enabled": not args.no_class_filter,
        },
    }

    # Write output
    output_path = Path(args.output)
    with open(output_path, 'w') as f:
        json.dump(params, f, indent=2)

    print(f"\n{'='*60}")
    print(f"Bridge parameters saved to: {output_path.absolute()}")
    print(f"{'='*60}")

    return params


if __name__ == "__main__":
    main()
