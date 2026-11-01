# Green Space Accessibility System — Barcelona

Turns open data (Open Data BCN + OpenStreetMap, all via API) into a **Green Accessibility Score and ranking for the
73 barris of Barcelona**, an investment **priority index**, equity indicators, a REST API and a dashboard. It is the
production version of the approved experiment notebook (`notebooks/`), which itself re-implemented the Chicago Green
Area Analysis (NOVA IMS, 2025).

## Verification status — read this first

| Part | Status |
|---|---|
| Config, scoring, ranking, priority index, rank stability, validation gate, run store, scheduler, stats, API data layer, CLI (`check-config`, `status`) | **46 tests passed** (run in a sandbox with a pytest stand-in) |
| Geospatial code (`geo`, `green`, `metrics`, `sources/*`), FastAPI app, dashboard, `pipeline.run_pipeline`, Docker images | **Compiled but NOT executed** — no network, geopandas or Docker were available when it was written |
| `tests/test_geo.py`, `tests/test_api.py` | Written, **not yet run** (skipped without the extras). CI runs them. |
| Live portal / Overpass calls | **Never run end to end.** The loaders are ports of the notebook cells you ran, but expect to fix small things on the first real run |

**First thing to do:** `pip install -e ".[pipeline,api,dev]" && pytest -q`, then `greenspace run`. The pipeline refuses to
publish a run that fails its quality checks, so a bad first run cannot reach the API or dashboard.

## Architecture

```
 Open Data BCN (CKAN API) ─┐                     ┌───────────────┐   data/runs/barcelona/
   boundaries, population, ├─► greenspace run ──►│ quality gate  │──►  <run_id>/  barris.csv, barris.geojson,
   income, park register,  │   (pipeline job)    │ (validate.py) │      green_patches.geojson, stations.geojson,
   official green polygons │                     └──────┬────────┘      green_metrics.gpkg, metadata.json, checks.json
 OpenStreetMap (Overpass) ─┘                  pass: atomic rename        latest.json  → points at the live run
   parks, stations, buildings,                fail: <run_id>.failed (never served)
   Collserola boundary                                                          │ read-only volume
                                                                                ▼
                                                    REST API (FastAPI) ◄── Dashboard (Streamlit)
```

* **Pipeline** (`greenspace run`): batch job. Raw API responses are cached (`data/cache`, 30 days, keyed by query).
* **Run store**: each run is a folder; `latest.json` is switched atomically, so readers never see half-written data and
  every published number is traceable (`metadata.json` holds sources, parameters, timings, checks).
* **API**: read-only, no geo libraries, reloads automatically when a new run is published.
* **Dashboard**: only calls the API.
* **Why files instead of a database:** 73 rows per run. A DB would add operations without benefit. If you later add many
  cities or need history queries, swap `store.py`/`repository.py` for PostGIS — nothing else depends on the storage.

## Approved decisions (see `docs/DECISIONS.md`)

1. Score weights and thresholds as in the notebook: 0.30 / 0.35 / 0.15 / 0.20; 300 m & ≥0.5 ha; 1 km & ≥5 ha; 9 m²/person.
2. **Parks = hybrid**: OSM polygons ∪ the city's official green polygons (dissolved: no double counting).
3. **Collserola is not green space**: the natural-park polygon (found via OSM by name) is subtracted from the union;
   the run **fails** if the zone cannot be found (`green.exclusion.required`).
4. **Barri level** (73 units).

## Quick start

### A. Docker
```bash
docker compose --profile jobs run --rm pipeline      # first data load (several minutes: buildings download)
docker compose up -d api dashboard
open http://localhost:8501        # dashboard      |   http://localhost:8000/docs   # API docs
docker compose --profile scheduler up -d scheduler   # optional: refresh every 30 days
```

### B. Local (conda-forge recommended for the geospatial stack)
```bash
conda create -n greenspace -c conda-forge python=3.12 geopandas osmnx pyogrio fastapi uvicorn streamlit plotly pytest httpx pyyaml
conda activate greenspace && pip install -e . --no-deps
greenspace check-config          # validate configs/barcelona.yaml
greenspace run                   # add --refresh to ignore cached API responses
greenspace status
greenspace serve &               # API on :8000
API_URL=http://localhost:8000 streamlit run src/greenspace/dashboard/app.py
```

## Score, in one paragraph
Four components, each 0–100: green m² per inhabitant (winsorised 5–95 %), % of residents within 300 m of a ≥0.5 ha
green patch, % within 1 km of a ≥5 ha patch, % of the barri covered by green. Weighted mean = **access_score**;
rank 1 = best. Residents are located by OSM building footprints (grid fallback). **priority_index** = 50 % access need +
25 % population density + 25 % income need; rank 1 = most urgent. **rank_p05/p95** = the barri's rank range under 2,000
random weightings around the approved weights (how much the ranking depends on the weights).

## API (read-only)

| Endpoint | Purpose |
|---|---|
| `GET /health`, `GET /ready` | liveness / a published run exists (503 otherwise) |
| `GET /v1/meta`, `/v1/quality` | live run, sources, parameters, attribution / quality checks |
| `GET /v1/stats` | city indicators, equity by income quartile, green-layer composition |
| `GET /v1/barris` | filter (`district`, `tier`, `min_score`, `max_score`, `low_income`, `q`), sort, page |
| `GET /v1/barris/{code}` | one barri, all metrics + district peers |
| `GET /v1/ranking?by=access\|priority&order=best\|worst&limit=` | top / bottom lists |
| `GET /v1/districts` | district summary (population-weighted) |
| `GET /v1/geojson?props=a,b` | polygons with metrics (WGS84) |
| `GET /v1/layers/green\|stations` | context layers |

Interactive docs: `/docs`. Responses carry `Cache-Control: public, max-age=300`.

## Quality gate (`validate.py`)
Fails the run (nothing published): not 73 units, duplicate codes, missing population, population total or city green
cover outside plausible ranges, invalid scores, **exclusion zone not found**, income missing for >20 % of units.
Warns: population/income year gap > 2, OSM/city-register agreement < 80 %, official layers empty, few sample points,
mean rank shift vs the previous run > 8. Details are in `checks.json` and `/v1/quality`.

## Configuration
Everything tunable lives in `configs/barcelona.yaml` (typed and validated in `config.py`; unknown keys are rejected).
Environment: `GREENSPACE_CONFIG`, `GREENSPACE_DATA_DIR`, `GREENSPACE_CITY`, `CORS_ORIGINS`, `API_URL`, `LOG_LEVEL`.

## Adding another city
Add `configs/<city>.yaml` and a source adapter `src/greenspace/sources/<adapter>.py` exposing `load_boundaries`,
`load_income`, `load_population`, `load_register_points`, `load_official_polygons` (see `barcelona.py`), register it in
`pipeline.ADAPTERS`. Scoring, validation, storage, API and dashboard are city-agnostic apart from the unit count and
labels in the config.

## Known limitations
* Straight-line distances (no walking network); green quality (canopy, amenities, opening hours) not assessed.
* Income is a barri average → low-income residents inside rich barris are invisible.
* Official polygon layers are dated (2019 files); OSM supplies recency, so check `green_layer` in `/v1/stats`
  (OSM-only vs official-only area) after each run.
* Whether the official layers contain Collserola parts is handled only through the OSM exclusion polygon.
* Overpass can rate-limit or time out; cached data and retries mitigate this, a failed run simply leaves the previous
  published run live.

## Attribution & licences
Ajuntament de Barcelona – Open Data BCN (CC BY 4.0); © OpenStreetMap contributors (ODbL, share-alike applies to
derived OSM databases). Keep the attribution in `/v1/meta` visible in any public deployment. Source code: no licence
chosen yet.
