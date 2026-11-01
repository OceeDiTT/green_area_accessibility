# Runbook

| Situation | What to do |
|---|---|
| First deployment | `docker compose --profile jobs run --rm pipeline`, then `docker compose up -d api dashboard`. `/ready` returns 503 until a run is published |
| `greenspace run` exits with code 2 | Run was rejected. Read `data/runs/barcelona/<id>.failed/checks.json` (and `error.txt` for crashes). The previous run stays live |
| Check `exclusion_zone` failed | Overpass did not return the Collserola park. Re-run later (or `--refresh`). Do **not** disable `green.exclusion.required` just to publish |
| Check `register_match` warns | OSM + official layers miss many registered parks. Inspect `green_layer`; consider enabling the second official layer |
| Check `rank_drift` warns | Ranking moved a lot since the last run. Compare the two `barris.csv` files; expected after a data refresh, suspicious otherwise |
| Overpass timeouts | Retry; cached responses are reused for 30 days. `--refresh` forces new downloads |
| Portal dataset id changed | The pipeline logs a WARNING and falls back to a portal search. Update `sources.*` in the config and re-run |
| Roll back | Edit `data/runs/barcelona/latest.json` to an older `run_id` (the API picks it up on the next request) |
| Disk usage | `runtime.keep_runs` runs are kept; failed runs: the 3 most recent |
| Update weights / thresholds | Change the config, re-run, and record the approval in `docs/DECISIONS.md` |
