# Decision log

| # | Decision (owner-approved) | Implementation | Consequence |
|---|---|---|---|
| 1 | Score weights & thresholds acceptable | `scoring.weights`, `standards.*` in `configs/barcelona.yaml` | Changing them requires a new approval; `/v1/meta` always shows the weights used by the live run |
| 2 | Parks = mix of OSM and the city register | OSM polygons ∪ city GeoPackage polygons (`espais-verds-publics`, `afectacions-turistiques-a-espais-verds`), dissolved. The point register (`culturailleure-parcsjardins`) is used as an independent QA cross-check | Area is never double counted. `green_layer` in `/v1/stats` reports OSM-only vs official-only area so the contribution of each source is visible |
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
