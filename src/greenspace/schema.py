"""Column contract shared by pipeline, API and dashboard."""
from .config import COMPONENTS

IDENTITY = ["barri_code", "barri", "district"]
BASE_METRICS = ["population", "area_m2", "green_m2", "green_cover_pct", "pop_density_km2", "green_m2_pp",
                "people_per_1000m2_green", "income_eur_pc", "rfd_index", "low_income", "n_stations",
                "share_300m_05ha", "share_1km_5ha"]
SCORE_COLS = list(COMPONENTS) + ["access_score", "access_rank", "access_tier", "priority_index", "priority_rank",
                                 "rank_p05", "rank_median", "rank_p95", "rank_range90", "meets_who_target"]
EXPORT_COLS = IDENTITY + BASE_METRICS + SCORE_COLS

TIERS = ["Very low", "Low", "Medium", "High", "Very high"]

# numeric columns that may be used for sorting / map colouring through the API
MAP_METRICS = ["access_score", "priority_index", "green_cover_pct", "green_m2_pp", "pop_density_km2",
               "people_per_1000m2_green", "rfd_index", "share_300m_05ha", "share_1km_5ha", "population",
               "access_rank", "priority_rank", *COMPONENTS]
