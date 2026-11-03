"""Command line: greenspace run | schedule | status | publish | inspect | explore-official | check-config | serve"""
import argparse
import json
import logging
import os
import sys

from .logs import setup_logging

DEFAULT_CONFIG = os.getenv("GREENSPACE_CONFIG", "configs/barcelona.yaml")
DEFAULT_DATA = os.getenv("GREENSPACE_DATA_DIR", "data")


def _cfg(args):
    from .config import load_config
    return load_config(args.config)


def cmd_run(args) -> int:
    from .pipeline import PipelineError, run_pipeline
    try:
        res = run_pipeline(_cfg(args), args.data_dir, refresh=args.refresh, force=args.force)
    except PipelineError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 2
    print(json.dumps(res, indent=2))
    return 0


def cmd_schedule(args) -> int:
    from .pipeline import PipelineError, run_pipeline
    from .scheduler import run_forever
    from .store import RunStore
    cfg = _cfg(args)
    every = args.every_days or cfg.runtime.schedule_every_days
    store = RunStore(args.data_dir, cfg.city.slug)

    def job():
        try:
            run_pipeline(cfg, args.data_dir)
        except PipelineError as e:
            raise RuntimeError(str(e)) from e

    run_forever(job, store, every)
    return 0


def cmd_status(args) -> int:
    from .store import RunStore
    cfg = _cfg(args)
    store = RunStore(args.data_dir, cfg.city.slug)
    md = store.metadata()
    if not md:
        print("No published run yet. Create one with: greenspace run")
        return 1
    print(f"live run   : {md['run_id']}  ({md['status']}, finished {md['finished_utc']})")
    print(f"checks     : {md['checks_summary']}")
    st = md["stats"]
    print(f"units/pop  : {st['units']} / {st['population']:,}")
    print(f"green      : {st['green_km2']:.2f} km2 ({st['green_cover_pct']:.1f}%), {st['green_m2_per_capita_city']:.1f} m2/inhabitant")
    print(f"all runs   : {', '.join(store.runs())}")
    return 0


def cmd_check_config(args) -> int:
    cfg = _cfg(args)
    print(f"OK: {cfg.city.name} | weights {cfg.scoring.weights} | official layers {[o.label for o in cfg.sources.official_polygons]}")
    return 0


def cmd_publish(args) -> int:
    from .publish import publish
    cfg = _cfg(args)
    print(json.dumps(publish(args.data_dir, args.dest, cfg.city.slug), indent=2))
    return 0


def cmd_inspect(args) -> int:
    from .diagnose import inspect_units
    df = inspect_units(_cfg(args), args.data_dir, args.unit)
    if df.empty:
        print(f"No unit name contains any of {args.unit}")
        return 1
    print(df.to_string(index=False))
    return 0


def cmd_explore_official(args) -> int:
    from .diagnose import explore_official
    explore_official(_cfg(args), args.data_dir)
    return 0


def cmd_serve(args) -> int:
    import uvicorn
    uvicorn.run("greenspace.api.app:app", host=args.host, port=args.port, log_level="info")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="greenspace", description=__doc__)
    ap.add_argument("--log-level", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--config", default=DEFAULT_CONFIG)
        p.add_argument("--data-dir", default=DEFAULT_DATA)

    p = sub.add_parser("run", help="run the full pipeline once")
    common(p)
    p.add_argument("--refresh", action="store_true", help="ignore cached API responses")
    p.add_argument("--force", action="store_true", help="publish even if quality checks fail (not recommended)")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("schedule", help="re-run automatically when the live run is older than N days")
    common(p)
    p.add_argument("--every-days", type=float, default=None)
    p.set_defaults(fn=cmd_schedule)
    p = sub.add_parser("status", help="show the live run")
    common(p)
    p.set_defaults(fn=cmd_status)
    p = sub.add_parser("publish", help="export the live run into a small public snapshot (for git / free hosting)")
    common(p)
    p.add_argument("--dest", default="published")
    p.set_defaults(fn=cmd_publish)
    p = sub.add_parser("inspect", help="diagnose units: buildings vs green layer coverage (offline)")
    common(p)
    p.add_argument("--unit", action="append", required=True, help="part of a barri name; repeat for several")
    p.set_defaults(fn=cmd_inspect)
    p = sub.add_parser("explore-official", help="show layers / columns / categories inside the official polygon files")
    common(p)
    p.set_defaults(fn=cmd_explore_official)
    p = sub.add_parser("check-config", help="validate a config file")
    p.add_argument("--config", default=DEFAULT_CONFIG)
    p.set_defaults(fn=cmd_check_config)
    p = sub.add_parser("serve", help="start the REST API")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(fn=cmd_serve)

    args = ap.parse_args(argv)
    setup_logging(args.log_level)
    try:
        return args.fn(args)
    except Exception as e:                                   # config errors etc. -> clean message
        logging.getLogger("greenspace").debug("traceback", exc_info=True)
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
