"""Small examples for the formulas and spatial rules used by the index."""

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString, Point, Polygon

from index_tools import (
    assign_points_to_sa2s,
    assign_polygons_to_sa2s,
    classify_place_type,
    count_intersections,
    global_morans_i,
    local_morans_i,
    local_morans_labels,
    local_morans_observed,
    local_morans_p_values,
    normalised_entropy,
    polygon_area_shares,
    score_index,
    standardised_score,
    zscore,
)


def two_sa2s():
    """Two adjacent unit squares with the higher code on the left."""
    return gpd.GeoDataFrame(
        {"SA2_CODE21": [20, 10]},
        geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
                  Polygon([(1, 0), (2, 0), (2, 1), (1, 1)])],
        crs=3857,
    )


def test_a_boundary_point_keeps_the_lower_sa2_code():
    points = gpd.GeoDataFrame(geometry=[Point(1, 0.5)], crs=3857)
    assigned = assign_points_to_sa2s(points, two_sa2s())
    assert assigned.iloc[0] == 10


def test_a_polygon_goes_to_the_sa2_with_seventy_percent():
    polygons = gpd.GeoDataFrame(
        geometry=[Polygon([(0.3, 0.2), (1.3, 0.2), (1.3, 0.8), (0.3, 0.8)])],
        crs=3857,
    )
    assigned = assign_polygons_to_sa2s(polygons, two_sa2s(), metric_crs=3857)
    assert assigned.loc[0, "assigned_sa2"] == 20
    assert abs(assigned.loc[0, "winner_share"] - 0.7) < 1e-9


def test_a_polygon_mostly_outside_is_dropped():
    polygons = gpd.GeoDataFrame(
        geometry=[Polygon([(-2, 0.2), (0.5, 0.2), (0.5, 0.8), (-2, 0.8)])],
        crs=3857,
    )
    assigned = assign_polygons_to_sa2s(polygons, two_sa2s(), metric_crs=3857)
    assert pd.isna(assigned.loc[0, "assigned_sa2"])
    assert assigned.loc[0, "outside_share"] > assigned.loc[0, "winner_share"]


def test_an_exact_polygon_tie_keeps_the_lower_sa2_code():
    polygons = gpd.GeoDataFrame(
        geometry=[Polygon([(0.5, 0.2), (1.5, 0.2), (1.5, 0.8), (0.5, 0.8)])],
        crs=3857,
    )
    assigned = assign_polygons_to_sa2s(polygons, two_sa2s(), metric_crs=3857)
    assert assigned.loc[0, "assigned_sa2"] == 10


def test_entropy_is_one_for_equal_shares_and_zero_for_one_category():
    assert abs(normalised_entropy([0.25, 0.25, 0.25, 0.25], 4) - 1) < 1e-9
    assert normalised_entropy([1, 0, 0, 0], 4) == 0


def test_zscore_has_mean_zero_and_population_sd_one():
    scores = zscore(pd.Series([1, 2, 3, 4]))
    assert abs(scores.mean()) < 1e-12
    assert abs(scores.std(ddof=0) - 1) < 1e-12


def test_intersections_count_t_junctions_and_four_way_crossings_only():
    roads = gpd.GeoDataFrame(
        geometry=[
            LineString([(0, 0), (1, 0), (2, 0)]),
            LineString([(1, 0), (1, 1)]),
            LineString([(3, 0), (3.5, 0), (4, 0)]),
            LineString([(3.5, -1), (3.5, 0), (3.5, 1)]),
            LineString([(5, 0), (5.5, 0.5), (6, 0)]),
            LineString([(7, 0), (8, 0)]),
            LineString([(8, 0), (9, 0)]),
        ],
        crs=4326,
    )
    intersections = count_intersections(roads)
    result = {(point.x, point.y): legs for point, legs in zip(intersections.geometry, intersections["legs"])}
    assert result == {(1.0, 0.0): 3, (3.5, 0.0): 4}


def test_area_shares_split_a_polygon_seventy_thirty():
    polygons = gpd.GeoDataFrame(
        geometry=[Polygon([(0.3, 0.2), (1.3, 0.2), (1.3, 0.8), (0.3, 0.8)])],
        crs=3857,
    )
    shares = polygon_area_shares(polygons, two_sa2s(), metric_crs=3857)
    allocated = shares.set_index("assigned_sa2")["area_share"]
    assert abs(allocated.loc[20] - 0.7) < 1e-9
    assert abs(allocated.loc[10] - 0.3) < 1e-9


def test_area_shares_keep_twenty_percent_inside():
    polygons = gpd.GeoDataFrame(
        geometry=[Polygon([(-0.8, 0.2), (0.2, 0.2), (0.2, 0.8), (-0.8, 0.8)])],
        crs=3857,
    )
    shares = polygon_area_shares(polygons, two_sa2s(), metric_crs=3857)
    assert abs(shares.iloc[0]["area_share"] - 0.2) < 1e-9
    assert shares.iloc[0]["assigned_sa2"] == 20


def test_area_shares_for_any_polygon_add_up_to_at_most_one():
    polygons = gpd.GeoDataFrame(
        geometry=[Polygon([(-0.2, 0.2), (1.3, 0.2), (1.3, 0.8), (-0.2, 0.8)])],
        crs=3857,
    )
    shares = polygon_area_shares(polygons, two_sa2s(), metric_crs=3857)
    assert shares.groupby("source_index")["area_share"].sum().iloc[0] <= 1 + 1e-9


def test_score_index_averages_the_three_pillars():
    values = pd.DataFrame({"i1": [0.0, 1.0], "d1": [0.0, 2.0], "g1": [0.0, 3.0]})
    scaled, pillars = score_index(values, ["i1", "g1"], ["i1"], ["d1"], ["g1"])
    assert np.allclose(scaled["i1"], [-1.0, 1.0])
    assert np.allclose(pillars["intensity"], [-1.0, 1.0])
    assert np.allclose(pillars["diversity"], [-1.0, 1.0])
    assert np.allclose(pillars["design"], [-1.0, 1.0])
    assert np.allclose(pillars["vibrancy"], [-1.0, 1.0])


def test_place_type_uses_density_and_diversity_quadrants():
    """Scores are on the 100-centred scale: density is the mean of Intensity and Design, and 100 is the cut."""
    assert classify_place_type(110.0, 110.0, 95.0) == "dense and diverse"
    assert classify_place_type(110.0, 90.0, 105.0) == "dense and less diverse"
    assert classify_place_type(90.0, 110.0, 95.0) == "less dense and diverse"
    assert classify_place_type(90.0, 90.0, 95.0) == "less dense and less diverse"
    assert pd.isna(classify_place_type(np.nan, 100.0, 100.0))
    assert classify_place_type(90.0, np.nan, 95.0) == "less dense and less diverse"


def test_place_type_cut_is_exactly_the_displayed_100():
    """A score of exactly 100 counts as dense or diverse; a score just under 100 does not."""
    assert classify_place_type(100.0, 100.0, 100.0) == "dense and diverse"
    assert classify_place_type(99.9, 99.9, 99.9) == "less dense and less diverse"
    assert classify_place_type(96.7, 100.1, 103.4) == "dense and diverse"
    assert classify_place_type(96.7, 100.1, 102.9) == "less dense and diverse"


def chain_weights():
    """Row-standardised weights for a four-area chain."""
    return np.array([[0.0, 1.0, 0.0, 0.0],
                     [0.5, 0.0, 0.5, 0.0],
                     [0.0, 0.5, 0.0, 0.5],
                     [0.0, 0.0, 1.0, 0.0]])


def test_global_morans_i_matches_hand_checked_chain_values():
    weights = chain_weights()
    # For +1, +1, -1, -1, z'Wz is 2 and z'z is 4, so I is +0.5.
    positive_i, _ = global_morans_i([1, 1, -1, -1], weights, permutations=9, seed=1)
    # Reordering to +1, -1, +1, -1 gives z'Wz of -4, so I is -1.
    negative_i, _ = global_morans_i([1, -1, 1, -1], weights, permutations=9, seed=1)
    assert abs(positive_i - 0.5) < 1e-12
    assert abs(negative_i + 1.0) < 1e-12


def test_local_morans_i_returns_hand_checked_local_values():
    local = local_morans_i([1, 1, -1, -1], chain_weights(), permutations=9, seed=1)
    assert np.allclose(local["local_i"], [1.0, 0.0, 0.0, 1.0])
    assert set(local["hotspot_class"]) == {"not significant"}


def test_local_morans_observed_matches_the_chain_example():
    local_i, neighbour_mean = local_morans_observed([1, 1, -1, -1], chain_weights())
    assert np.allclose(neighbour_mean, [1.0, 0.0, 0.0, -1.0])
    assert np.allclose(local_i, [1.0, 0.0, 0.0, 1.0])


def test_local_morans_p_values_are_reproducible_with_a_fixed_seed():
    local_i, _ = local_morans_observed([1, 1, -1, -1], chain_weights())
    p_values = local_morans_p_values([1, 1, -1, -1], chain_weights(), local_i, permutations=9, seed=1)
    assert np.allclose(p_values, [1.0, 1.0, 1.0, 1.0])


def test_local_morans_labels_cover_all_four_significant_quadrants():
    labels = local_morans_labels([1, -1, 1, -1], [1, -1, -1, 1], [0.01] * 4)
    assert labels == ["high-high", "low-low", "high-low", "low-high"]


def test_standardised_score_has_mean_one_hundred_sd_ten_and_keeps_missing():
    values = pd.Series([1.0, 2.0, 3.0, np.nan])
    scores = standardised_score(values)
    assert abs(scores.mean() - 100) < 1e-12
    assert abs(scores.std(ddof=0) - 10) < 1e-12
    assert pd.isna(scores.iloc[3])
