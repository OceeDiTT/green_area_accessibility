"""Streamlit dashboard. Talks only to the REST API (API_URL). Run: streamlit run src/greenspace/dashboard/app.py"""
import os

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

API = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
st.set_page_config(page_title="Green Space Accessibility", page_icon="🌳", layout="wide")

METRICS = {
    "Accessibility score (0-100)": ("access_score", "RdYlGn"),
    "Investment priority index": ("priority_index", "Reds"),
    "Green coverage (%)": ("green_cover_pct", "Greens"),
    "Green m² per inhabitant": ("green_m2_pp", "YlGn"),
    "Population density (inh/km²)": ("pop_density_km2", "OrRd"),
    "Residents within 300 m of ≥0.5 ha green": ("share_300m_05ha", "YlGn"),
    "Income index (city = 100)": ("rfd_index", "Blues"),
}


@st.cache_data(ttl=300, show_spinner=False)
def get(path: str, **params):
    r = requests.get(f"{API}{path}", params=params, timeout=60)
    if r.status_code == 503:
        return {"_unavailable": r.json().get("detail", "no data")}
    r.raise_for_status()
    return r.json()


def table(rows) -> pd.DataFrame:
    return pd.DataFrame(rows)


try:
    meta = get("/v1/meta")
except Exception as e:                                    # API down
    st.error(f"Cannot reach the API at {API}: {e}")
    st.stop()
if "_unavailable" in meta:
    st.warning(f"No published data yet: {meta['_unavailable']}")
    st.stop()

stats = get("/v1/stats")
df = table(get("/v1/barris", limit=500, sort="access_rank")["items"])
gj = get("/v1/geojson")

st.sidebar.title("🌳 Green Space Accessibility")
st.sidebar.caption(f"{meta['city']} · run {meta['run_id']}")
page = st.sidebar.radio("View", ["Overview", "Ranking", "Barri profile", "Priorities", "Equity", "Method & data"])
st.sidebar.caption("Data: Ajuntament de Barcelona – Open Data BCN (CC BY 4.0); © OpenStreetMap contributors (ODbL).")


def choropleth(metric_label: str, height=620):
    col, scale = METRICS[metric_label]
    kw = dict(geojson=gj, locations="barri_code", featureidkey="properties.barri_code", color=col, hover_name="barri",
              hover_data={"district": True, "access_score": ":.0f", "green_m2_pp": ":.1f", "barri_code": False},
              color_continuous_scale=scale, opacity=0.75, center={"lat": 41.395, "lon": 2.165}, zoom=10.6)
    if hasattr(px, "choropleth_map"):
        fig = px.choropleth_map(df, map_style="open-street-map", **kw)          # keyless basemap
    else:
        fig = px.choropleth_mapbox(df, mapbox_style="open-street-map", **kw)
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=height)
    return fig


if page == "Overview":
    st.header(f"Green space accessibility in {meta['city']}")
    c = st.columns(4)
    c[0].metric("Green per inhabitant", f"{stats['green_m2_per_capita_city']:.1f} m²", f"guide {stats['who_target_m2_pp']:.0f} m²", delta_color="off")
    c[1].metric("Green coverage", f"{stats['green_cover_pct']:.1f}%")
    c[2].metric("Residents ≥300 m from a ≥0.5 ha green space", f"{stats['estimated_residents_without_300m_access']:,}")
    c[3].metric("Barris below guide value", f"{stats['units_below_who_target']} / {stats['units']}")
    metric = st.selectbox("Map metric", list(METRICS))
    st.plotly_chart(choropleth(metric))
    st.caption("Collserola natural park is excluded from green space by design. Green layer = OSM + city polygons.")

elif page == "Ranking":
    st.header("Barri ranking – Green Accessibility Score")
    c1, c2 = st.columns(2)
    dist = c1.multiselect("District", sorted(df["district"].unique()))
    tier = c2.multiselect("Tier", ["Very low", "Low", "Medium", "High", "Very high"])
    d = df[(df["district"].isin(dist) if dist else True) & (df["access_tier"].isin(tier) if tier else True)]
    show = d[["access_rank", "barri", "district", "access_score", "access_tier", "green_m2_pp", "share_300m_05ha",
              "share_1km_5ha", "green_cover_pct", "population", "rank_p05", "rank_p95"]].rename(columns={
        "rank_p05": "rank (best case)", "rank_p95": "rank (worst case)"})
    st.dataframe(show, hide_index=True)
    st.download_button("Download CSV", show.to_csv(index=False), "green_accessibility_ranking.csv", "text/csv")
    fig = px.bar(d.sort_values("access_score"), x="access_score", y="barri", color="access_tier", orientation="h",
                 height=max(400, 18 * len(d)))
    st.plotly_chart(fig)

elif page == "Barri profile":
    st.header("Barri profile")
    name = st.selectbox("Barri", df.sort_values("barri")["barri"])
    code = int(df.loc[df["barri"] == name, "barri_code"].iloc[0])
    b = get(f"/v1/barris/{code}")
    c = st.columns(4)
    c[0].metric("Score", f"{b['access_score']:.0f} / 100", f"rank {b['access_rank']} of {len(df)}", delta_color="off")
    c[1].metric("Green per inhabitant", f"{b['green_m2_pp']:.1f} m²")
    c[2].metric("≥0.5 ha within 300 m", f"{b['share_300m_05ha']:.0%}")
    c[3].metric("Priority rank", f"{b['priority_rank']}")
    comp = pd.DataFrame({"component": ["Green per capita", "Proximity 300 m", "Large park 1 km", "Coverage"],
                         "score": [b["c_percapita"], b["c_prox300"], b["c_large1km"], b["c_coverage"]]})
    st.plotly_chart(px.bar(comp, x="component", y="score", range_y=[0, 100], height=320))
    st.caption(f"Rank is robust between {b['rank_p05']:.0f} and {b['rank_p95']:.0f} under different weightings "
               f"(90% of 2,000 random weightings).")
    st.subheader(f"Peers in {b['district']}")
    st.dataframe(table(b["same_district_ranking"]), hide_index=True)

elif page == "Priorities":
    st.header("Where would extra green space help most?")
    st.write("Priority index = access need (50%) + population density (25%) + income need (25%).")
    n = st.slider("Show top N", 5, 30, 15)
    pr = table(get("/v1/ranking", by="priority", order="best", limit=n))
    st.dataframe(pr.rename(columns={"priority_index": "priority index"}), hide_index=True)
    st.plotly_chart(choropleth("Investment priority index", 520))

elif page == "Equity":
    st.header("Is green space equitably distributed?")
    r1, r2 = stats.get("spearman_income_vs_green_per_capita"), stats.get("spearman_income_vs_access_score")
    c = st.columns(2)
    c[0].metric("Rank correlation: income vs green m²/inhabitant", "n/a" if r1 is None else f"{r1:+.2f}")
    c[1].metric("Rank correlation: income vs accessibility score", "n/a" if r2 is None else f"{r2:+.2f}")
    d = df.dropna(subset=["rfd_index"]).copy()
    d["green_m2_pp_capped"] = d["green_m2_pp"].clip(upper=d["green_m2_pp"].quantile(0.95))
    st.plotly_chart(px.scatter(d, x="rfd_index", y="green_m2_pp_capped", size="population", color="district", hover_name="barri",
                               labels={"rfd_index": "Income index (city = 100)", "green_m2_pp_capped": "Green m² per inhabitant (capped)"},
                               height=520))
    q = table(stats.get("equity_by_income_quartile", []))
    if len(q):
        st.subheader("By income quartile (population-weighted)")
        st.dataframe(q, hide_index=True)
    st.subheader("By district")
    st.dataframe(table(get("/v1/districts")), hide_index=True)

else:
    st.header("Method & data")
    p = meta["parameters"]
    st.markdown(f"""
**Score (0–100)** = weighted mean of four components: green per inhabitant ({p['weights']['c_percapita']:.0%}),
residents within {p['standards']['near_dist_m']:.0f} m of ≥{p['standards']['near_min_m2']/1e4:.1f} ha green ({p['weights']['c_prox300']:.0%}),
residents within {p['standards']['large_dist_m']/1000:.0f} km of ≥{p['standards']['large_min_m2']/1e4:.0f} ha green ({p['weights']['c_large1km']:.0%}),
and green coverage ({p['weights']['c_coverage']:.0%}).
Residents are located with building footprints; distances are straight-line.
Green space = OpenStreetMap + city polygons, **excluding Collserola natural park**.
    """)
    st.subheader("Data quality of the live run")
    st.dataframe(table(get("/v1/quality")), hide_index=True)
    st.subheader("Green layer composition (km²)")
    st.json(stats.get("green_layer", {}))
    st.subheader("Sources")
    st.json(meta["sources"])
