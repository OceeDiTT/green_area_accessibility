import pandas as pd
import pytest
from greenspace.tabular import filter_features, find_col, latest_by_unit, norm, pick_resource, year_of


def _res():
    names = [f"{y}_pad_mdbas.csv" for y in range(1997, 2025)] + ["2012_pad_mdbas.json"]
    return pd.DataFrame({"name": names, "format": ["csv"] * 28 + ["json"],
                         "url": ["https://x/resource/ab2012cd-2012-4e5f/download"] * 29,   # random ids contain '2012'
                         "id": range(29), "datastore_active": False})


def test_pick_latest_uses_name_not_url():
    assert pick_resource(_res(), ["csv"])["name"] == "2024_pad_mdbas.csv"


def test_pick_closest_to_target_year():
    assert pick_resource(_res(), ["csv"], target_year=2023)["name"] == "2023_pad_mdbas.csv"
    assert pick_resource(_res(), ["csv"], target_year=2030)["name"] == "2024_pad_mdbas.csv"


def test_pick_missing_format():
    with pytest.raises(LookupError):
        pick_resource(_res(), ["gpkg"])


def test_year_of_handles_dates_and_years():
    assert year_of(pd.Series(["2012-01-01T00:00:00", "2013-01-01T00:00:00"])).tolist() == [2012, 2013]
    assert year_of(pd.Series([2020, 2021])).tolist() == [2020, 2021]


def test_find_col_accent_and_case_insensitive():
    df = pd.DataFrame(columns=["Codi_Barri", "Població"])
    assert find_col(df, ["codi_barri"]) == "Codi_Barri"
    assert find_col(df, ["poblacio"]) == "Població"
    with pytest.raises(KeyError):
        find_col(df, ["nothing"])
    assert norm("Sant Martí") == "sant_marti"


def test_latest_by_unit_filters_to_latest_year_and_aggregates():
    df = pd.DataFrame({"Data_Referencia": ["2023-01-01T00:00:00"] * 4 + ["2024-01-01T00:00:00"] * 4,
                       "Codi_Barri": [1, 1, 2, 2, 1, 1, 2, 2], "Valor": [10, 20, 30, 40, 1, 2, 3, 4]})
    out, year = latest_by_unit(df, "Codi_Barri", "Valor", "Data_Referencia", agg="sum")
    assert year == 2024 and out["_v"].tolist() == [3, 7] and out["barri_code"].tolist() == [1, 2]


def _feat():
    return pd.DataFrame({"_layer": ["parcs", "parcs", "illes", "illes", "illes"],
                         "TIPUS": ["Parc històric", "Plaça verda", "Illa", "Interior d'illa", "Illa"], "id": range(5)})


def test_filter_by_layer_and_category_is_accent_and_case_insensitive():
    f = _feat()
    assert filter_features(f, layers=["PARCS"])["id"].tolist() == [0, 1]
    assert filter_features(f, where={"tipus": ["parc historic", "placa verda"]})["id"].tolist() == [0, 1]
    assert filter_features(f, exclude={"TIPUS": ["illa"]})["id"].tolist() == [0, 1, 3]
    assert filter_features(f, layers=["illes"], where={"TIPUS": ["Interior d'illa"]})["id"].tolist() == [3]
    assert len(filter_features(f)) == 5


def test_filter_unknown_column_or_missing_layer_info_is_an_error():
    with pytest.raises(KeyError):
        filter_features(_feat(), where={"nope": ["x"]})
    with pytest.raises(KeyError):
        filter_features(_feat().drop(columns="_layer"), layers=["parcs"])
