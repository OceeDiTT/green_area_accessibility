"""Streamlit dashboard. Talks only to the REST API (API_URL). Run: streamlit run src/greenspace/dashboard/app.py"""
import os
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2]                 # .../src  (lets Streamlit Community Cloud import the package without installing it)
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pandas as pd  # noqa: E402
import plotly.express as px  # noqa: E402
import streamlit as st  # noqa: E402

from greenspace.dashboard.data_access import make_getter  # noqa: E402
from greenspace.dashboard.helpers import (checks_headline, filter_ranking, fmt_dt, fmt_duration, green_layer_summary,
                                          map_view, quality_table, source_rows)

# API_URL set  -> talk to the REST API (Docker / server deployment).
# API_URL empty -> read the published snapshot directly (free Streamlit Community Cloud deployment, no API server).
API = os.getenv("API_URL", "").rstrip("/")
PUBLISHED = os.getenv("GREENSPACE_PUBLISHED_DIR", str(_SRC.parent / "published"))
CITY = os.getenv("GREENSPACE_CITY", "barcelona")
st.set_page_config(page_title="Green Space Accessibility", page_icon="🌳", layout="wide")

METRICS = {
    "Accessibility score (0–100)": ("access_score", "RdYlGn"),
    "Investment priority index": ("priority_index", "Reds"),
    "Green coverage (%)": ("green_cover_pct", "Greens"),
    "Green m² per inhabitant": ("green_m2_pp", "YlGn"),
    "Population density (inhabitants / km²)": ("pop_density_km2", "OrRd"),
    "Residents within 300 m of a ≥ 0.5 ha green space": ("share_300m_05ha", "YlGn"),
    "Income index (city = 100)": ("rfd_index", "Blues"),
}


@st.cache_resource
def _client():
    return make_getter(API or None, PUBLISHED, CITY)


@st.cache_data(ttl=300, show_spinner=False)
def get(path: str, **params):
    return _client()(path, **params)


def table(rows) -> pd.DataFrame:
    return pd.DataFrame(rows)


try:
    meta = get("/v1/meta")
except Exception as e:                                    # API down
    st.error(f"Cannot load the data ({'API ' + API if API else 'folder ' + PUBLISHED}): {e}")
    st.stop()
if "_unavailable" in meta:
    st.warning(f"No published data yet: {meta['_unavailable']}")
    st.stop()

stats = get("/v1/stats")
df = table(get("/v1/barris", limit=500, sort="access_rank")["items"])
gj = get("/v1/geojson")
view = map_view(gj)

# ------------------------------------------------------------------------------------------------ sidebar
st.sidebar.title("🌳 Green Space Accessibility")
st.sidebar.caption(f"**{meta['city']}** · data updated {fmt_dt(meta.get('finished_utc'), with_time=False)}")
st.sidebar.caption(checks_headline(meta.get("checks_summary")))
page = st.sidebar.radio("View", ["Overview", "Ranking", "Barri profile", "Priorities", "Equity", "Method & data"])
st.sidebar.divider()
st.sidebar.caption("Data: Ajuntament de Barcelona – Open Data BCN (CC BY 4.0); © OpenStreetMap contributors (ODbL).")


def choropleth(metric_label: str, height: int = 620):
    col, scale = METRICS[metric_label]
    kw = dict(geojson=gj, locations="barri_code", featureidkey="properties.barri_code", color=col, hover_name="barri",
              hover_data={"district": True, "access_score": ":.0f", "green_m2_pp": ":.1f", "barri_code": False},
              labels={col: metric_label, "district": "District", "access_score": "Score", "green_m2_pp": "Green m²/inhabitant"},
              color_continuous_scale=scale, opacity=0.75, center=view["center"], zoom=view["zoom"])
    if hasattr(px, "choropleth_map"):
        fig = px.choropleth_map(df, map_style="open-street-map", **kw)          # keyless basemap
    else:
        fig = px.choropleth_mapbox(df, mapbox_style="open-street-map", **kw)
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=height, coloraxis_colorbar=dict(title=""))
    return fig


# ------------------------------------------------------------------------------------------------ pages
if page == "Overview":
    st.header(f"Green space accessibility in {meta['city']}")
    c = st.columns(4)
    c[0].metric("Green space per inhabitant", f"{stats['green_m2_per_capita_city']:.1f} m²",
                help=f"Guide value: {stats['who_target_m2_pp']:.0f} m² per inhabitant")
    c[1].metric("Green coverage", f"{stats['green_cover_pct']:.1f}%", help="Share of the city's area that is green space")
    c[2].metric("Residents without nearby green", f"{stats['estimated_residents_without_300m_access']:,}",
                help="Estimated residents with no green space of at least 0.5 ha within 300 m")
    c[3].metric("Barris below the guide value", f"{stats['units_below_who_target']} of {stats['units']}",
                help=f"Barris with less than {stats['who_target_m2_pp']:.0f} m² of green space per inhabitant")
    metric = st.selectbox("Map metric", list(METRICS))
    st.plotly_chart(choropleth(metric))
    st.caption(f"Collserola natural park is excluded from green space by design. {stats.get('units_near_natural_park', 0)} barris "
               f"({stats.get('population_near_natural_park', 0):,} residents) are mostly within 500 m of it and are marked in the ranking.")

elif page == "Ranking":
    st.header("Barri ranking – Green Accessibility Score")
    c1, c2 = st.columns(2)
    dist = c1.multiselect("District", sorted(df["district"].unique()))
    tier = c2.multiselect("Tier", ["Very low", "Low", "Medium", "High", "Very high"])
    d = filter_ranking(df, dist, tier)
    d = d.assign(note=d["near_natural_park"].map({True: "Score excludes adjacent natural park", False: ""}))
    show = pd.DataFrame({
        "Rank": d["access_rank"], "Barri": d["barri"], "District": d["district"], "Score": d["access_score"].round(0),
        "Tier": d["access_tier"], "Green m²/inh.": d["green_m2_pp"].round(1),
        "≥0.5 ha within 300 m (%)": (d["share_300m_05ha"] * 100).round(0),
        "≥5 ha within 1 km (%)": (d["share_1km_5ha"] * 100).round(0), "Green coverage (%)": d["green_cover_pct"].round(1),
        "Population": d["population"].astype(int), "Best rank": d["rank_p05"].round(0), "Worst rank": d["rank_p95"].round(0),
        "Note": d["note"]})
    st.dataframe(show, hide_index=True, column_config={
        "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
        "Population": st.column_config.NumberColumn(format="%d")})
    st.caption("Best / worst rank: range of the barri's rank under 2,000 alternative weightings of the score components.")
    st.download_button("Download CSV", show.to_csv(index=False), "green_accessibility_ranking.csv", "text/csv")
    fig = px.bar(d.sort_values("access_score"), x="access_score", y="barri", color="access_tier", orientation="h",
                 labels={"access_score": "Score", "barri": "", "access_tier": "Tier"}, height=max(400, 18 * len(d)))
    st.plotly_chart(fig)

elif page == "Barri profile":
    st.header("Barri profile")
    name = st.selectbox("Barri", df.sort_values("barri")["barri"])
    code = int(df.loc[df["barri"] == name, "barri_code"].iloc[0])
    b = get(f"/v1/barris/{code}")
    c = st.columns(4)
    c[0].metric("Accessibility score", f"{b['access_score']:.0f} / 100", help=f"Rank {b['access_rank']} of {len(df)}")
    c[1].metric("Green space per inhabitant", f"{b['green_m2_pp']:.1f} m²")
    c[2].metric("Residents within 300 m of ≥ 0.5 ha green", f"{b['share_300m_05ha']:.0%}")
    c[3].metric("Investment priority", f"#{b['priority_rank']}", help="1 = most urgent")
    if b.get("near_natural_park"):
        st.info(f"{b['natural_park_share']:.0%} of residents live within 500 m of the Collserola natural park. By design the park is "
                "not counted as green space, so this barri's score understates its real access to nature.")
    comp = pd.DataFrame({"Component": ["Green per inhabitant", "Proximity (300 m)", "Large park (1 km)", "Green coverage"],
                         "Score": [b["c_percapita"], b["c_prox300"], b["c_large1km"], b["c_coverage"]]})
    st.plotly_chart(px.bar(comp, x="Component", y="Score", range_y=[0, 100], height=320))
    st.caption(f"Rank {b['access_rank']} of {len(df)}; between {b['rank_p05']:.0f} and {b['rank_p95']:.0f} under alternative weightings "
               f"(90 % of 2,000 random weightings).")
    st.subheader(f"Barris in {b['district']}")
    peers = table(b["same_district_ranking"]).rename(columns={"barri_code": "Code", "barri": "Barri", "access_score": "Score", "access_rank": "Rank"})
    peers["Score"] = peers["Score"].round(0)
    st.dataframe(peers, hide_index=True)

elif page == "Priorities":
    st.header("Where would extra green space help most?")
    st.write("Priority index = access need (50 %) + population density (25 %) + income need (25 %). Rank 1 is the most urgent.")
    n = st.slider("Show top N", 5, 30, 15)
    pr = table(get("/v1/ranking", by="priority", order="best", limit=n))
    st.dataframe(pd.DataFrame({
        "Priority": pr["priority_rank"], "Barri": pr["barri"], "District": pr["district"], "Priority index": pr["priority_index"].round(1),
        "Access score": pr["access_score"].round(0), "Green m²/inh.": pr["green_m2_pp"].round(1),
        "Population": pr["population"].astype(int), "Income index": pr["rfd_index"].round(0)}), hide_index=True)
    st.plotly_chart(choropleth("Investment priority index", 520))

elif page == "Equity":
    st.header("Is green space equitably distributed?")
    r1, r2 = stats.get("spearman_income_vs_green_per_capita"), stats.get("spearman_income_vs_access_score")
    c = st.columns(2)
    c[0].metric("Income vs green space per inhabitant", "n/a" if r1 is None else f"{r1:+.2f}",
                help="Rank correlation across barris: positive = richer barris have more green space per person")
    c[1].metric("Income vs accessibility score", "n/a" if r2 is None else f"{r2:+.2f}",
                help="Rank correlation across barris: positive = richer barris have better access")
    d = df.dropna(subset=["rfd_index"]).copy()
    d["green_capped"] = d["green_m2_pp"].clip(upper=d["green_m2_pp"].quantile(0.95))
    st.plotly_chart(px.scatter(d, x="rfd_index", y="green_capped", size="population", color="district", hover_name="barri",
                               labels={"rfd_index": "Income index (city = 100)", "green_capped": "Green m² per inhabitant (capped)",
                                       "district": "District", "population": "Population"}, height=520))
    q = table(stats.get("equity_by_income_quartile", []))
    if len(q):
        st.subheader("By income quartile (population-weighted)")
        st.dataframe(pd.DataFrame({
            "Income quartile": q["quartile"], "Barris": q["units"], "Population": q["population"],
            "Median green m²/inh.": q["median_green_m2_pp"].round(1), "Mean green coverage (%)": q["mean_green_cover_pct"].round(1),
            "Mean access score": q["mean_access_score"].round(0)}), hide_index=True)
    st.subheader("By district")
    dd = table(get("/v1/districts"))
    st.dataframe(pd.DataFrame({
        "District": dd["district"], "Barris": dd["units"], "Population": dd["population"],
        "Access score": dd["access_score_pop_weighted"].round(0), "Green m²/inh.": dd["green_m2_per_capita"].round(1),
        "Green coverage (%)": dd["green_cover_pct"].round(1), "Mean priority index": dd["mean_priority_index"].round(1)}), hide_index=True)

else:
    st.header("Method & data")
    p, cs = meta["parameters"], meta.get("checks_summary") or {}

    st.subheader("Data run")
    c = st.columns(4)
    c[0].metric("Status", "Published" if meta.get("status") == "published" else str(meta.get("status", "–")).title())
    c[1].metric("Last updated", fmt_dt(meta.get("finished_utc"), with_time=False), help=fmt_dt(meta.get("finished_utc")))
    c[2].metric("Quality checks", f"{cs.get('pass', 0)} passed", help=checks_headline(cs))
    c[3].metric("Warnings / failures", f"{cs.get('warn', 0)} / {cs.get('fail', 0)}")
    st.caption(f"Run {meta['run_id']} · software v{meta.get('software_version', '–')} · processing time {fmt_duration(meta.get('duration_s'))}")

    st.subheader("How the score works")
    st.markdown(f"""
The **Green Accessibility Score (0–100)** is a weighted average of four components:

| Component | Weight |
|---|---|
| Green space per inhabitant | {p['weights']['c_percapita']:.0%} |
| Residents within {p['standards']['near_dist_m']:.0f} m of a green space of at least {p['standards']['near_min_m2'] / 1e4:.1f} ha | {p['weights']['c_prox300']:.0%} |
| Residents within {p['standards']['large_dist_m'] / 1000:.0f} km of a green space of at least {p['standards']['large_min_m2'] / 1e4:.0f} ha | {p['weights']['c_large1km']:.0%} |
| Share of the barri's area that is green | {p['weights']['c_coverage']:.0%} |

Residents are located with building footprints and distances are straight-line. Green space combines OpenStreetMap with the city's
official register of public green spaces and **excludes the Collserola natural park**.
    """)

    st.subheader("Green space layer")
    cols = st.columns(4)
    for col, (label, value, hint) in zip(cols, green_layer_summary(stats.get("green_layer"))):
        col.metric(label, value, help=hint)
    share = (stats.get("green_layer") or {}).get("official_share_also_in_osm")
    if share is not None:
        st.caption(f"{share:.0%} of the area of the city's official parks is also mapped in OpenStreetMap.")

    st.subheader("Data sources")
    st.dataframe(source_rows(meta.get("sources")), hide_index=True)
    for line in meta.get("attribution") or []:
        st.caption(line)

    st.subheader("Quality checks")
    st.dataframe(quality_table(get("/v1/quality")), hide_index=True)
