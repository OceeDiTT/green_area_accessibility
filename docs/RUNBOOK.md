# Runbook

| Situation | What to do |
|---|---|
| First deployment | `docker compose --profile jobs run --rm pipeline`, then `docker compose up -d api dashboard`. `/ready` returns 503 until a run is published |
| `greenspace run` exits with code 2 | Run was rejected. Read `data/runs/barcelona/<id>.failed/checks.json` (and `error.txt` for crashes). The previous run stays live |
| Check `exclusion_zone` failed | Overpass did not return the Collserola park. Re-run later (or `--refresh`). Do **not** disable `green.exclusion.required` just to publish |
| Check `unit_cover_sane` fails / `unit_cover_plausible` warns | A barri is implausibly green (> 90 % rejects the run). A green source contains non-green polygons: run `greenspace explore-official`, look at categories and areas, and add `layers` / `where` / `exclude` filters or remove the source |
| Adding a new green source | 1) `greenspace explore-official` to see layers, columns, categories and area; 2) add it with filters; 3) run; 4) review the ten greenest and ten least green barris before trusting it |
| Check `register_match` warns | OSM + official layers miss many registered parks. Inspect `green_layer` (OSM-only vs official-only km²) |
| Check `rank_drift` warns | Ranking moved a lot since the last run. Compare the two `barris.csv` files; expected after a data refresh, suspicious otherwise |
| Overpass 502 / timeouts | Built in: 5 attempts with exponential back-off (20 s, 40 s, ...) rotating through `sources.overpass_endpoints`. If it still fails, just re-run later: parks and the exclusion zone are cached, so a re-run only repeats what failed. `--refresh` forces new downloads |
| Check `units_grid_filled` / `units_with_points` warns | Some barris have no usable OSM building footprints (data gap, or buildings only inside parks). Those units are sampled on a grid instead (named in the warning) so they are not scored as having zero access; if a unit still has no points its proximity shares are 0. Check the named units on the map before quoting their ranks |
| `Building footprints unavailable` | Overpass could not deliver buildings. Re-run later (preferred). To test the rest of the system now, set `sampling.allow_grid_fallback: true` — the run is then flagged by the `sampling_method` check because a uniform grid ignores where people actually live |
| Portal dataset id changed | The pipeline logs a WARNING and falls back to a portal search. Update `sources.*` in the config and re-run |
| Roll back | Edit `data/runs/barcelona/latest.json` to an older `run_id` (the API picks it up on the next request) |
| Disk usage | `runtime.keep_runs` runs are kept; failed runs: the 3 most recent |
| Update weights / thresholds | Change the config, re-run, and record the approval in `docs/DECISIONS.md` |
