"""Typed, validated configuration. One YAML file per city (see configs/)."""
from dataclasses import dataclass, field, fields, asdict
from pathlib import Path

import yaml

COMPONENTS = ("c_percapita", "c_prox300", "c_large1km", "c_coverage")
PRIORITY_KEYS = ("access_need", "density", "income_need")


class ConfigError(ValueError):
    pass


@dataclass
class CityInfo:
    name: str = "Barcelona"
    slug: str = "barcelona"
    adapter: str = "barcelona_ckan"
    crs_proj: str = "EPSG:25831"      # metric CRS used for ALL area / distance work
    crs_wgs84: str = "EPSG:4326"


@dataclass
class OfficialPolygonSource:
    label: str = ""
    package: str = ""
    formats: list = field(default_factory=lambda: ["gpkg"])


@dataclass
class Sources:
    ckan_base: str = "https://opendata-ajuntament.barcelona.cat/data/api/3/action"
    boundaries: list = field(default_factory=lambda: ["20170706-districtes-barris"])
    population: list = field(default_factory=lambda: ["pad_mdbas", "pad_mdbas_sexe"])
    income: list = field(default_factory=lambda: ["renda-disponible-llars-bcn"])
    register: list = field(default_factory=lambda: ["culturailleure-parcsjardins"])
    official_polygons: list = field(default_factory=list)


@dataclass
class Exclusion:
    required: bool = True
    name_patterns: list = field(default_factory=lambda: ["collserola"])
    osm_tags: dict = field(default_factory=lambda: {"boundary": ["protected_area"], "leisure": ["nature_reserve"]})


@dataclass
class Green:
    use_osm: bool = True
    use_official: bool = True
    osm_tags: dict = field(default_factory=lambda: {
        "leisure": ["park", "garden", "playground", "common", "recreation_ground"],
        "landuse": ["grass", "recreation_ground", "village_green", "meadow"]})
    min_green_m2: float = 100
    register_tolerance_m: float = 50
    exclusion: Exclusion = field(default_factory=Exclusion)


@dataclass
class Standards:
    near_dist_m: float = 300
    near_min_m2: float = 5_000
    large_dist_m: float = 1_000
    large_min_m2: float = 50_000
    who_target_m2_pp: float = 9


@dataclass
class Sampling:
    method: str = "buildings"          # "buildings" (footprint-weighted) | "grid"
    grid_step_m: float = 50
    min_building_m2: float = 40


@dataclass
class Equity:
    low_income_index: float = 75


@dataclass
class Scoring:
    weights: dict = field(default_factory=lambda: dict(c_percapita=0.30, c_prox300=0.35, c_large1km=0.15, c_coverage=0.20))
    priority_weights: dict = field(default_factory=lambda: dict(access_need=0.50, density=0.25, income_need=0.25))
    winsor_lo: float = 0.05
    winsor_hi: float = 0.95
    stability_draws: int = 2000
    stability_concentration: float = 50
    seed: int = 42


@dataclass
class Validation:
    n_units: int = 73
    population_range: list = field(default_factory=lambda: [1_400_000, 1_900_000])
    city_green_cover_pct_range: list = field(default_factory=lambda: [3, 40])
    max_year_gap: int = 2
    min_register_match: float = 0.80
    max_mean_rank_shift: float = 8.0
    min_sample_points: int = 20_000


@dataclass
class Runtime:
    cache_max_age_days: float = 30
    keep_runs: int = 6
    schedule_every_days: float = 30


@dataclass
class CityConfig:
    city: CityInfo = field(default_factory=CityInfo)
    sources: Sources = field(default_factory=Sources)
    green: Green = field(default_factory=Green)
    standards: Standards = field(default_factory=Standards)
    sampling: Sampling = field(default_factory=Sampling)
    equity: Equity = field(default_factory=Equity)
    scoring: Scoring = field(default_factory=Scoring)
    validation: Validation = field(default_factory=Validation)
    runtime: Runtime = field(default_factory=Runtime)


def _make(cls, data, nested=None):
    data = dict(data or {})
    nested = nested or {}
    unknown = set(data) - {f.name for f in fields(cls)}
    if unknown:
        raise ConfigError(f"Unknown key(s) {sorted(unknown)} in section '{cls.__name__}'")
    kwargs = {}
    for k, v in data.items():
        spec = nested.get(k)
        if spec is None:
            kwargs[k] = v
        elif isinstance(spec, tuple):                  # list of dataclasses
            kwargs[k] = [_make(spec[0], x) for x in (v or [])]
        else:
            kwargs[k] = _make(spec, v)
    return cls(**kwargs)


def from_dict(data: dict) -> CityConfig:
    data = dict(data or {})
    top = {"city": CityInfo, "standards": Standards, "sampling": Sampling, "equity": Equity,
           "scoring": Scoring, "validation": Validation, "runtime": Runtime}
    unknown = set(data) - set(top) - {"sources", "green"}
    if unknown:
        raise ConfigError(f"Unknown top-level key(s): {sorted(unknown)}")
    kw = {k: _make(cls, data[k]) for k, cls in top.items() if k in data}
    if "sources" in data:
        kw["sources"] = _make(Sources, data["sources"], {"official_polygons": (OfficialPolygonSource,)})
    if "green" in data:
        kw["green"] = _make(Green, data["green"], {"exclusion": Exclusion})
    cfg = CityConfig(**kw)
    validate_config(cfg)
    return cfg


def load_config(path) -> CityConfig:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"Config file not found: {p}")
    return from_dict(yaml.safe_load(p.read_text(encoding="utf-8")))


def validate_config(cfg: CityConfig) -> None:
    s = cfg.scoring
    if set(s.weights) != set(COMPONENTS):
        raise ConfigError(f"scoring.weights must have exactly the keys {COMPONENTS}, got {tuple(s.weights)}")
    if set(s.priority_weights) != set(PRIORITY_KEYS):
        raise ConfigError(f"scoring.priority_weights must have exactly the keys {PRIORITY_KEYS}")
    for name, w in (("weights", s.weights), ("priority_weights", s.priority_weights)):
        if any(v < 0 for v in w.values()) or sum(w.values()) <= 0:
            raise ConfigError(f"scoring.{name} must be non-negative with a positive sum")
    if not 0 <= s.winsor_lo < s.winsor_hi <= 1:
        raise ConfigError("scoring.winsor_lo must be < winsor_hi, both within [0, 1]")
    if cfg.sampling.method not in ("buildings", "grid"):
        raise ConfigError("sampling.method must be 'buildings' or 'grid'")
    st = cfg.standards
    if min(st.near_dist_m, st.near_min_m2, st.large_dist_m, st.large_min_m2, st.who_target_m2_pp) <= 0:
        raise ConfigError("standards.* must all be positive")
    if not (cfg.green.use_osm or cfg.green.use_official):
        raise ConfigError("green: at least one of use_osm / use_official must be true")
    if cfg.green.use_official and not cfg.sources.official_polygons:
        raise ConfigError("green.use_official is true but sources.official_polygons is empty")
    labels = [o.label for o in cfg.sources.official_polygons]
    if len(labels) != len(set(labels)) or not all(labels):
        raise ConfigError("sources.official_polygons need unique, non-empty labels")
    for key in ("population_range", "city_green_cover_pct_range"):
        lo, hi = getattr(cfg.validation, key)
        if lo >= hi:
            raise ConfigError(f"validation.{key} must be [low, high] with low < high")


def to_dict(cfg: CityConfig) -> dict:
    return asdict(cfg)
