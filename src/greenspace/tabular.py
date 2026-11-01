"""Pure pandas helpers for messy open-data tables (no geo dependencies)."""
import re
import unicodedata

import pandas as pd


def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def find_col(df, patterns, required=True):
    cols = {norm(c): c for c in df.columns}
    for p in patterns:                       # exact matches first
        if p in cols:
            return cols[p]
    for p in patterns:                       # then substring matches
        for n, c in cols.items():
            if p in n:
                return c
    if required:
        raise KeyError(f"None of {patterns} found. Available columns: {list(df.columns)}")
    return None


def year_of(s) -> pd.Series:
    """Year as int from plain years (2023) or date strings ('2012-01-01T00:00:00')."""
    num = pd.to_numeric(s, errors="coerce")
    if num.notna().all():
        return num.astype(int)
    return pd.to_datetime(s, errors="coerce").dt.year


def _name_year(name) -> int:
    m = re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", str(name))
    return max(map(int, m)) if m else 0


def pick_resource(res: pd.DataFrame, formats, target_year=None, name_contains=None):
    """Choose one CKAN resource row. The year is read from the resource NAME only (URLs hold random ids)."""
    formats = {f.lower() for f in formats}
    r = res[res["format"].str.lower().isin(formats)].copy()
    if name_contains:
        r = r[r["name"].fillna("").map(norm).str.contains(norm(name_contains))]
    if r.empty:
        raise LookupError(f"No resource with format {sorted(formats)}"
                          f"{' and name containing ' + repr(name_contains) if name_contains else ''}. "
                          f"Available formats: {sorted(res['format'].unique())}")
    r["year"] = r["name"].map(_name_year)
    if target_year is not None and (r["year"] > 0).any():
        r["gap"] = (r["year"] - target_year).abs()
        return r.sort_values(["gap", "year"], ascending=[True, False]).iloc[0]
    return r.sort_values("year", ascending=False).iloc[0]


def latest_by_unit(df, code_col, value_col, year_col=None, agg="sum"):
    """Reduce a long table to one value per unit for its latest reference year. Returns (frame, year|None)."""
    df = df.copy()
    df["_v"] = pd.to_numeric(df[value_col], errors="coerce")
    year = None
    if year_col is not None:
        yr = year_of(df[year_col])
        year = int(yr.max())
        df = df[yr == year]
    out = (df.assign(barri_code=pd.to_numeric(df[code_col], errors="coerce"))
             .dropna(subset=["barri_code"])
             .groupby("barri_code", as_index=False)["_v"].agg(agg))
    out["barri_code"] = out["barri_code"].astype("int64")
    return out, year


def filter_features(df, layers=None, where=None, exclude=None):
    """Attribute / layer filters for official polygon layers (names and values compared accent/case-insensitively)."""
    out = df
    if layers:
        if "_layer" not in out.columns:
            raise KeyError("a 'layers' filter was configured but the file has no layer information")
        out = out[out["_layer"].map(norm).isin({norm(x) for x in layers})]
    for col, vals in (where or {}).items():
        c = find_col(out, [norm(col)])
        out = out[out[c].astype(str).map(norm).isin({norm(v) for v in vals})]
    for col, vals in (exclude or {}).items():
        c = find_col(out, [norm(col)])
        out = out[~out[c].astype(str).map(norm).isin({norm(v) for v in vals})]
    return out
