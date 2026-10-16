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
    return 100 + 10 * zscore(values)


def with_geometry(frame, columns):
    """Return a copy of the named columns plus the geometry column, with the geometry column called "geometry"."""
    rows = frame[columns + [frame.geometry.name]].copy()
    if rows.geometry.name != "geometry":
        rows = rows.rename_geometry("geometry")
    return rows


def assign_points_to_sa2s(points, sa2s, code_column="SA2_CODE21"):
    """Return one SA2 code per point, using the lower code for boundary ties."""
    point_rows = with_geometry(points, [])
    point_rows = point_rows.reset_index(names="source_index")
    point_rows["feature_id"] = np.arange(len(point_rows))
    boundary_rows = with_geometry(sa2s, [code_column])
    joined = gpd.sjoin(point_rows, boundary_rows, how="left", predicate="intersects")
    joined = joined.sort_values(["feature_id", code_column], na_position="last")
    joined = joined.drop_duplicates("feature_id", keep="first")
    assigned = joined.set_index("source_index")[code_column]
    assigned = assigned.reindex(points.index)
    return assigned.astype("Int64")


def assign_polygons_to_sa2s(polygons, sa2s, code_column="SA2_CODE21", metric_crs=7856):
    """Assign each polygon to its largest SA2 overlap, unless outside has more area. Ties keep the lower code."""
    shares = polygon_area_shares(polygons, sa2s, code_column, metric_crs)
    winners = shares.sort_values(["area_share", "assigned_sa2"], ascending=[False, True])
    winners = winners.drop_duplicates("source_index").set_index("source_index")
    inside = shares.groupby("source_index")["area_share"].agg(inside_share="sum", n_sa2_touched="count")
    result = pd.DataFrame({"winner_share": winners["area_share"], "inside_share": inside["inside_share"],
                           "n_sa2_touched": inside["n_sa2_touched"]}).reindex(polygons.index)
    result.index.name = "source_index"
    result["winner_share"] = result["winner_share"].fillna(0.0)
    result["outside_share"] = (1 - result["inside_share"].fillna(0.0)).clip(lower=0.0)
    result["n_sa2_touched"] = result["n_sa2_touched"].fillna(0).astype(int)
    won = result["outside_share"] <= result["winner_share"]
    result["assigned_sa2"] = winners["assigned_sa2"].reindex(result.index).where(won).astype("Int64")
    return result[["assigned_sa2", "winner_share", "outside_share", "n_sa2_touched"]]


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
    polygon_rows = with_geometry(polygons, []).to_crs(metric_crs)
    polygon_rows.geometry = polygon_rows.geometry.make_valid()
    polygon_rows = polygon_rows.reset_index(names="source_index")
    polygon_rows["feature_id"] = np.arange(len(polygon_rows))
    boundary_rows = with_geometry(sa2s, [code_column]).to_crs(metric_crs)
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


# The cut between "less" and "more" for density and diversity: 100 is the Greater Sydney average on the scale of the
# displayed scores, so the page's chart lines at 100 and this rule cut at the same place.
PLACE_TYPE_CUTOFF = 100


def classify_place_type(intensity_score, diversity_score, design_score):
    """Label an SA2 by density and diversity from its displayed scores, with missing Diversity as less diverse.

    Density is the mean of the Intensity and Design scores. An SA2 is dense, or diverse, when that score is at or
    above PLACE_TYPE_CUTOFF.
    """
    if pd.isna(intensity_score) or pd.isna(design_score):
        return pd.NA
    density_score = (float(intensity_score) + float(design_score)) / 2
    density_label = "dense" if density_score >= PLACE_TYPE_CUTOFF else "less dense"
    diversity_is_high = pd.notna(diversity_score) and float(diversity_score) >= PLACE_TYPE_CUTOFF
    diversity_label = "diverse" if diversity_is_high else "less diverse"
    return f"{density_label} and {diversity_label}"


def require_standardised(values):
    """Stop if the values are not z-scores (mean 0, SD 1); the Moran formulas below assume they are."""
    assert abs(np.mean(values)) < 1e-9 and abs(np.std(values) - 1) < 1e-9, \
        "Moran's I needs z-scores (mean 0, standard deviation 1), not raw scores"


def global_morans_i(values, weights, permutations=999, seed=20260926):
    """Return global Moran's I and a two-sided permutation p-value. The values must be z-scores."""
    values = np.asarray(values, dtype=float)
    require_standardised(values)
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
    """Return local Moran's I values and row-standardised neighbour means. The values must be z-scores."""
    values = np.asarray(values, dtype=float)
    require_standardised(values)
    weights = np.asarray(weights, dtype=float)
    neighbour_mean = weights @ values
    local_i = values * neighbour_mean
    return local_i, neighbour_mean


def local_morans_p_values(values, weights, local_i, permutations=999, seed=20260926):
    """Return conditional-permutation p-values for local Moran's I values. The values must be z-scores."""
    values = np.asarray(values, dtype=float)
    require_standardised(values)
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
