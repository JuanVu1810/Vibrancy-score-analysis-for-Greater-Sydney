"""Small, tested helpers for the Greater Sydney vibrancy index."""

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point


def normalised_entropy(shares, n_categories):
    """Return Shannon entropy on a 0 to 1 scale for a fixed category count."""
    values = np.asarray(shares, dtype=float)
    values = values[np.isfinite(values) & (values > 0)]
    if len(values) == 0:
        return np.nan
    values = values / values.sum()
    entropy = -(values * np.log(values)).sum()
    return float(entropy / np.log(n_categories))


def zscore(values):
    """Return z-scores using the population standard deviation (divide by n)."""
    values = pd.Series(values, copy=False, dtype=float)
    standard_deviation = values.std(ddof=0)
    if standard_deviation == 0 or pd.isna(standard_deviation):
        return pd.Series(np.nan, index=values.index, dtype=float)
    return (values - values.mean()) / standard_deviation


def standardised_score(values):
    """Rescale values to a mean of 100 and population SD of 10, keeping missing values."""
    values = pd.Series(values, copy=False, dtype=float)
    standard_deviation = values.std(ddof=0)
    if standard_deviation == 0 or pd.isna(standard_deviation):
        return pd.Series(np.nan, index=values.index, dtype=float)
    return 100 + 10 * (values - values.mean()) / standard_deviation


def assign_points_to_sa2s(points, sa2s, code_column="SA2_CODE21"):
    """Return one SA2 code per point, using the lower code for boundary ties."""
    point_rows = points[[points.geometry.name]].copy()
    if point_rows.geometry.name != "geometry":
        point_rows = point_rows.rename_geometry("geometry")
    point_rows = point_rows.reset_index(names="source_index")
    point_rows["feature_id"] = np.arange(len(point_rows))
    boundary_rows = sa2s[[code_column, sa2s.geometry.name]].copy()
    if boundary_rows.geometry.name != "geometry":
        boundary_rows = boundary_rows.rename_geometry("geometry")
    joined = gpd.sjoin(point_rows, boundary_rows, how="left", predicate="intersects")
    joined = joined.sort_values(["feature_id", code_column], na_position="last")
    joined = joined.drop_duplicates("feature_id", keep="first")
    assigned = joined.set_index("source_index")[code_column]
    assigned = assigned.reindex(points.index)
    return assigned.astype("Int64")


def assign_polygons_to_sa2s(polygons, sa2s, code_column="SA2_CODE21", metric_crs=7856):
    """Assign each polygon to its largest SA2 overlap, unless outside has more area."""
    polygon_rows = polygons[[polygons.geometry.name]].copy()
    if polygon_rows.geometry.name != "geometry":
        polygon_rows = polygon_rows.rename_geometry("geometry")
    polygon_rows = polygon_rows.to_crs(metric_crs)
    polygon_rows.geometry = polygon_rows.geometry.make_valid()
    polygon_rows = polygon_rows.reset_index(names="source_index")
    polygon_rows["feature_id"] = np.arange(len(polygon_rows))
    boundary_rows = sa2s[[code_column, sa2s.geometry.name]].copy()
    if boundary_rows.geometry.name != "geometry":
        boundary_rows = boundary_rows.rename_geometry("geometry")
    boundary_rows = boundary_rows.to_crs(metric_crs)
    matches = gpd.sjoin(polygon_rows, boundary_rows, how="left", predicate="intersects")
    matches = matches.reset_index(drop=True)
    matches["overlap_area"] = 0.0
    matched = matches[code_column].notna()
    boundary_geometry = boundary_rows.geometry
    for row_index, row in matches[matched].iterrows():
        polygon = polygon_rows.loc[row["feature_id"], "geometry"]
        boundary = boundary_geometry.loc[row["index_right"]]
        matches.loc[row_index, "overlap_area"] = polygon.intersection(boundary).area
    return _choose_polygon_matches(polygon_rows, matches, code_column)


def _choose_polygon_matches(polygons, matches, code_column):
    """Summarise polygon overlaps and apply the outside and lower-code tie rules."""
    rows = []
    for feature_id, group in matches.groupby("feature_id", sort=True):
        polygon_area = polygons.loc[feature_id, "geometry"].area
        candidates = group[group[code_column].notna()].sort_values(
            ["overlap_area", code_column], ascending=[False, True]
        )
        inside_area = candidates["overlap_area"].sum()
        outside_area = max(0.0, polygon_area - inside_area)
        winner_area = 0.0 if candidates.empty else candidates.iloc[0]["overlap_area"]
        assigned = pd.NA
        if not candidates.empty and outside_area <= winner_area:
            assigned = int(candidates.iloc[0][code_column])
        rows.append({
            "source_index": polygons.loc[feature_id, "source_index"],
            "assigned_sa2": assigned,
            "winner_share": winner_area / polygon_area,
            "outside_share": outside_area / polygon_area,
            "n_sa2_touched": int(len(candidates)),
        })
    result = pd.DataFrame(rows).set_index("source_index")
    result["assigned_sa2"] = result["assigned_sa2"].astype("Int64")
    return result


def count_intersections(roads, precision=7, min_legs=3):
    """Return road vertices where at least three segment ends meet."""
    legs_by_point = {}
    for geometry in roads.geometry:
        if geometry is None or geometry.is_empty:
            continue
        lines = geometry.geoms if geometry.geom_type == "MultiLineString" else [geometry]
        for line in lines:
            coordinates = list(line.coords)
            for position, coordinate in enumerate(coordinates):
                point = (round(coordinate[0], precision), round(coordinate[1], precision))
                legs = 1 if position in (0, len(coordinates) - 1) else 2
                legs_by_point[point] = legs_by_point.get(point, 0) + legs
    rows = []
    for (x, y), legs in legs_by_point.items():
        if legs >= min_legs:
            rows.append({"legs": legs, "geometry": Point(x, y)})
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=roads.crs)


def polygon_area_shares(polygons, sa2s, code_column="SA2_CODE21", metric_crs=7856):
    """Return one fractional SA2 allocation for every positive polygon overlap."""
    polygon_rows = polygons[[polygons.geometry.name]].copy()
    if polygon_rows.geometry.name != "geometry":
        polygon_rows = polygon_rows.rename_geometry("geometry")
    polygon_rows = polygon_rows.to_crs(metric_crs)
    polygon_rows.geometry = polygon_rows.geometry.make_valid()
    polygon_rows = polygon_rows.reset_index(names="source_index")
    polygon_rows["feature_id"] = np.arange(len(polygon_rows))
    boundary_rows = sa2s[[code_column, sa2s.geometry.name]].copy()
    if boundary_rows.geometry.name != "geometry":
        boundary_rows = boundary_rows.rename_geometry("geometry")
    boundary_rows = boundary_rows.to_crs(metric_crs)
    matches = gpd.sjoin(polygon_rows, boundary_rows, how="left", predicate="intersects")
    rows = []
    for _, match in matches[matches[code_column].notna()].iterrows():
        feature_id = int(match["feature_id"])
        polygon = polygon_rows.loc[feature_id, "geometry"]
        overlap = polygon.intersection(boundary_rows.loc[match["index_right"], "geometry"]).area
        if polygon.area > 0 and overlap > 0:
            rows.append({"source_index": polygon_rows.loc[feature_id, "source_index"],
                         "assigned_sa2": int(match[code_column]), "area_share": overlap / polygon.area})
    return pd.DataFrame(rows, columns=["source_index", "assigned_sa2", "area_share"])


def scale_indicators(values, density_columns, scale="zscore", log_densities=True):
    """Log density columns when requested, then return z-scores or 0 to 1 values."""
    scaled = values.astype(float).copy()
    if log_densities:
        for column in density_columns:
            scaled[column] = np.log1p(scaled[column])
    for column in scaled.columns:
        if scale == "zscore":
            scaled[column] = zscore(scaled[column])
        elif scale == "minmax":
            minimum = scaled[column].min()
            maximum = scaled[column].max()
            scaled[column] = (scaled[column] - minimum) / (maximum - minimum)
        else:
            raise ValueError(f"Unknown scale: {scale}")
    return scaled


def score_index(values, density_columns, intensity_columns, diversity_columns, design_columns,
                scale="zscore", log_densities=True):
    """Scale indicator values, average the three pillars, and average the available pillars."""
    scaled = scale_indicators(values, density_columns, scale=scale, log_densities=log_densities)
    pillars = pd.DataFrame(index=values.index)
    pillars["intensity"] = scaled[intensity_columns].mean(axis=1)
    pillars["diversity"] = scaled[diversity_columns].mean(axis=1)
    pillars["design"] = scaled[design_columns].mean(axis=1)
    pillars["vibrancy"] = pillars[["intensity", "diversity", "design"]].mean(axis=1)
    return scaled, pillars


def classify_place_type(intensity_z, diversity_z, design_z):
    """Label an SA2 by density and diversity, with missing Diversity as less diverse."""
    if pd.isna(intensity_z) or pd.isna(design_z):
        return pd.NA
    density_z = (float(intensity_z) + float(design_z)) / 2
    density_label = "dense" if density_z >= 0 else "less dense"
    diversity_label = "diverse" if pd.notna(diversity_z) and float(diversity_z) >= 0 else "less diverse"
    return f"{density_label} and {diversity_label}"


def global_morans_i(values, weights, permutations=999, seed=20260926):
    """Return global Moran's I and a two-sided permutation p-value."""
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    n_areas = len(values)
    weight_sum = weights.sum()
    observed = (n_areas / weight_sum) * (values @ weights @ values) / (values @ values)
    generator = np.random.default_rng(seed)
    simulated = np.empty(permutations)
    for position in range(permutations):
        shuffled = generator.permutation(values)
        simulated[position] = (n_areas / weight_sum) * (shuffled @ weights @ shuffled) / (shuffled @ shuffled)
    p_value = (1 + np.count_nonzero(np.abs(simulated) >= abs(observed))) / (1 + permutations)
    return float(observed), float(p_value)


def local_morans_observed(values, weights):
    """Return local Moran's I values and row-standardised neighbour means."""
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    neighbour_mean = weights @ values
    local_i = values * neighbour_mean
    return local_i, neighbour_mean


def local_morans_p_values(values, weights, local_i, permutations=999, seed=20260926):
    """Return conditional-permutation p-values for local Moran's I values."""
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    generator = np.random.default_rng(seed)
    p_values = np.empty(len(values))
    for area in range(len(values)):
        other_areas = np.arange(len(values)) != area
        simulated = np.empty(permutations)
        for position in range(permutations):
            shuffled = values.copy()
            shuffled[other_areas] = generator.permutation(values[other_areas])
            simulated[position] = values[area] * (weights[area] @ shuffled)
        p_values[area] = (1 + np.count_nonzero(np.abs(simulated) >= abs(local_i[area]))) / (1 + permutations)
    return p_values


def local_morans_labels(values, neighbour_mean, p_values, alpha=0.05):
    """Return local Moran quadrant labels for significant areas."""
    labels = []
    for value, neighbour, p_value in zip(values, neighbour_mean, p_values):
        if p_value >= alpha:
            labels.append("not significant")
        elif value >= 0 and neighbour >= 0:
            labels.append("high-high")
        elif value < 0 and neighbour < 0:
            labels.append("low-low")
        elif value >= 0:
            labels.append("high-low")
        else:
            labels.append("low-high")
    return labels


def local_morans_i(values, weights, permutations=999, seed=20260926, alpha=0.05):
    """Return local Moran's I, conditional p-values and descriptive classes."""
    local_i, neighbour_mean = local_morans_observed(values, weights)
    p_values = local_morans_p_values(values, weights, local_i, permutations, seed)
    labels = local_morans_labels(values, neighbour_mean, p_values, alpha)
    return pd.DataFrame({"local_i": local_i, "p_value": p_values, "hotspot_class": labels})
