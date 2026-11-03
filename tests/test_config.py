import pytest
from greenspace.config import ConfigError, from_dict, load_config
from helpers import make_cfg


def test_defaults_are_the_approved_values():
    c = make_cfg()
    assert c.scoring.weights == {"c_percapita": 0.30, "c_prox300": 0.35, "c_large1km": 0.15, "c_coverage": 0.20}
    assert (c.standards.near_dist_m, c.standards.near_min_m2) == (300, 5000)
    assert (c.standards.large_dist_m, c.standards.large_min_m2) == (1000, 50000)
    assert c.green.exclusion.required and "collserola" in c.green.exclusion.name_patterns
    assert c.validation.n_units == 73


def test_shipped_barcelona_config_loads(tmp_path):
    import pathlib
    c = load_config(pathlib.Path(__file__).parent.parent / "configs" / "barcelona.yaml")
    assert c.city.slug == "barcelona" and c.green.use_osm and c.green.use_official
    assert [o.label for o in c.sources.official_polygons] == ["public_green_over_half_ha"]
    o = c.sources.official_polygons[0]
    assert o.name_contains == "pev_parcs" and o.exclude == {"rao_no_fet": ["Privat", "Obres"]}


def test_unknown_key_rejected():
    with pytest.raises(ConfigError):
        from_dict({"scoring": {"wieghts": {}}})
    with pytest.raises(ConfigError):
        from_dict({"nonsense": 1})


def test_bad_weights_rejected():
    with pytest.raises(ConfigError):
        make_cfg(scoring={"weights": {"c_percapita": 1.0}})
    with pytest.raises(ConfigError):
        make_cfg(scoring={"weights": {"c_percapita": -1, "c_prox300": 1, "c_large1km": 1, "c_coverage": 1}})


def test_official_requires_sources():
    with pytest.raises(ConfigError):
        from_dict({"green": {"use_official": True}, "sources": {"official_polygons": []}})


def test_missing_file():
    with pytest.raises(ConfigError):
        load_config("/nonexistent.yaml")


def test_official_source_filters_are_parsed():
    c = make_cfg(sources={"official_polygons": [{"label": "a", "package": "p", "layers": ["parcs"],
                                                   "where": {"TIPUS": ["Parc"]}, "exclude": {"X": ["y"]}}]})
    o = c.sources.official_polygons[0]
    assert o.layers == ["parcs"] and o.where == {"TIPUS": ["Parc"]} and o.exclude == {"X": ["y"]}


def test_exclusion_context_defaults():
    e = make_cfg().green.exclusion
    assert e.context_dist_m == 500 and e.flag_share == 0.5
