# Decision log

| # | Decision (owner-approved) | Implementation | Consequence |
|---|---|---|---|
| 1 | Score weights & thresholds acceptable | `scoring.weights`, `standards.*` in `configs/barcelona.yaml` | Changing them requires a new approval; `/v1/meta` always shows the weights used by the live run |
| 2 | Parks = mix of OSM and the city register | OSM polygons ∪ the city's *Public green spaces > 0.5 ha* polygons (`espais-verds-publics`, file `pev_parcs`; private and in-works sites excluded), dissolved. The point register (`culturailleure-parcsjardins`) is used as an independent QA cross-check | Area is never double counted. `green_layer` in `/v1/stats` reports OSM-only vs official-only area. Only parks > 0.5 ha come from the official file; smaller green comes from OSM |
| 3 | Collserola forest is not green space | Natural-park polygon fetched from OSM (name contains "collserola") and subtracted from the union; OSM `natural=wood`/`nature_reserve` no longer used as green tags; run fails if the zone is missing | Hillside barris (e.g. Vallvidrera) score on their built-up parks only |
| 4 | Analysis stays at barri level | `validation.n_units: 73` | Finer units (census sections / hex grid) would need a new adapter and a re-approval of the metrics |

## Differences from the experiment notebook
* The notebook included `leisure=nature_reserve` in its OSM tags, which can pull in the whole Collserola park. Removed.
* The notebook used OSM only; production uses the hybrid layer.
* Resource selection, date parsing and download fixes found while running the notebook are built in.
* Quality gate, versioned runs, API, dashboard and scheduler are new.

## Open questions for the owner
* Should the official 2019 layers stay enabled? They add authority but may be outdated (check `official_only_km2`).
* Publish publicly? If yes: set `CORS_ORIGINS`, put the API behind a reverse proxy with rate limiting and TLS.


## Incident log
**2026-11-01 – tourism layer counted as green space.** The second official source (`afectacions-turistiques-a-espais-verds`) was
added from a search snippet without inspecting its contents; the "latest file" rule then selected `2021_espais_gran_afluencia.gpkg`
(high-visitor-flow zones: La Rambla, Camp Nou, ...), adding 14 km² of non-green area. Ciutat Vella showed 67–100 % green cover and
ranked near the top. Found by sanity-checking the first published run. Fixes: source removed; the remaining source is pinned by
file name and filtered; new checks `unit_cover_plausible` (warn > 70 %) and `unit_cover_sane` (**reject** > 90 %);
`greenspace explore-official` shows what a file contains before it is used. Rule going forward: *inspect every new source with
`explore-official` and review the per-barri results before publishing.*

**2026-11-02 – Collserola-edge barris.** With Collserola excluded (decision 3), Vallvidrera/Tibidabo/les Planes ranks last and Torre Baró 68th although
their residents live next to a very large natural park. The score and ranking are unchanged (as approved). A context indicator was added:
`natural_park_share` (share of residents within 500 m of the excluded park) and `near_natural_park` (>= 50 %), shown next to the score in the
API (`?near_natural_park=true`) and flagged in the dashboard. It does not enter the score, the ranking or the priority index.
