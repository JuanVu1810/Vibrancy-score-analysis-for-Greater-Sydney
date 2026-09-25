"""Command line: python -m etl list | run | verify"""
from __future__ import annotations

import argparse
import json
import sys
import time

from . import quality
from .core import STAGING, Ctx, EtlError, MissingCredential, Snapshot, environment, utc_now
from .sources import BY_ID, SOURCES, TABLES
from .stage import write_staged


def cmd_list(_args) -> int:
    print(f"{'source':<16} {'tables':<32} title")
    for s in SOURCES:
        print(f"{s.id:<16} {', '.join(s.outputs):<32} {s.title}")
    return 0


def cmd_run(args) -> int:
    ctx = Ctx(mode=args.mode, refresh=args.refresh)
    # --only accepts source ids (abs_business) or the table names they produce (businesses)
    wanted = [BY_ID[w].id if w in BY_ID else TABLES[w].id if w in TABLES else w for w in (args.only or [])]
    unknown = [w for w in wanted if w not in BY_ID]
    if unknown:
        sys.exit(f"unknown source(s): {', '.join(unknown)}. Try: python -m etl list")
    wanted = wanted or [s.id for s in SOURCES]

    if args.mode == "latest":  # what this download run was made with, as the CPI project's manifest does
        ctx.manifest.data["environment"] = environment()
    started_at = utc_now()
    report, tables, failed = {}, {}, []
    for src in (s for s in SOURCES if s.id in wanted):
        print(f"\n== {src.id}: {src.title}", flush=True)
        started = time.time()
        try:
            if args.mode == "pinned":
                record = ctx.manifest.get(src.id)
                if record is None:
                    raise MissingCredential(f"{src.id} is not in the manifest yet; run it in latest mode first")
                snap = Snapshot.from_record(src.id, record)
            else:
                snap = src.fetch(ctx)
            out = src.parse(snap)
            records = quality.assess(src, out, ctx)
            ctx.quality += records
            for r in records:
                if r.status != "PASS":
                    for note in r.notes.split("; "):
                        print(f"  [{r.status}] {r.dataset}: {note}")
            failures = [r for r in records if r.status == "FAIL"]
            if failures:
                raise EtlError("failed its checks: " + "; ".join(f"{r.dataset}: {r.notes}" for r in failures))
            for name, frame in out.items():
                ctx.frames[name] = frame
                tables[name] = frame
                print(f"  {name}: {len(frame):,} rows -> staging/{write_staged(name, frame)}")
            ctx.manifest.put(src.id, snap.to_record())
            ctx.manifest.save()
            print(f"  release: {snap.release}")
            report[src.id] = {"status": "ok", "release": snap.release, "seconds": round(time.time() - started, 1),
                              "rows": {n: len(f) for n, f in out.items()},
                              "issues": [f"{r.dataset}: {r.notes}" for r in records if r.status != "PASS"]}
        except MissingCredential as e:
            failed.append(src.id)
            print(f"  NOT RUN: {e}")
            report[src.id] = {"status": "not run", "reason": str(e)}
        except Exception as e:
            failed.append(src.id)
            print(f"  FAILED: {e}")
            report[src.id] = {"status": "failed", "reason": str(e)}

    if not args.no_db and tables:
        try:
            from . import load
            settings = load.connection_settings(args.credentials, args.db_host, args.db_name)
            print(f"\n== loading into PostGIS at {load.describe(settings)}")
            table_sources = {t: TABLES[t] for t in tables}
            bad = load.load(tables, table_sources, dict(ctx.manifest.data["sources"]), BY_ID,
                            quality=quality.records_to_frame(ctx.quality).assign(run_at=started_at, mode=args.mode),
                            settings=settings)
            failed += [f"load:{t}" for t, _ in bad]
        except Exception as e:
            failed.append("load")
            print(f"  FAILED: could not load into the database: {str(e).splitlines()[0]}")

    STAGING.mkdir(parents=True, exist_ok=True)
    if ctx.quality:
        quality.records_to_frame(ctx.quality).to_csv(STAGING / "data_quality_report.csv", index=False)
    (STAGING / "run_report.json").write_text(json.dumps(
        {"finished_at": utc_now(), "mode": args.mode, "sources": report}, indent=2), encoding="utf-8")
    print("\n== summary")
    for sid, r in report.items():
        print(f"  {sid:<16} {r['status']:<8} {r.get('release', r.get('reason', ''))}")
    if failed:
        print(f"\n{len(failed)} problem(s): {', '.join(failed)}")
        return 1
    print("\nAll sources loaded.")
    return 0


def cmd_verify(args) -> int:
    from . import verify
    return verify.run(args.parity)


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m etl", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="show the sources and the tables they produce").set_defaults(func=cmd_list)

    r = sub.add_parser("run", help="fetch, clean, check and load the sources")
    r.add_argument("--mode", choices=["latest", "pinned"], default="latest",
                   help="latest: resolve and download the newest release; pinned: reuse the exact files in raw/manifest.json")
    r.add_argument("--only", nargs="+", metavar="SOURCE", help="run just these sources or tables (see 'list')")
    r.add_argument("--refresh", action="store_true", help="download again even if the server says nothing changed")
    r.add_argument("--no-db", action="store_true", help="write staging/ files only, skip PostGIS")
    r.add_argument("--credentials", metavar="FILE", help="load into the database in this credentials file (like "
                   "Credentials.json) instead of the one docker compose starts")
    r.add_argument("--db-host", metavar="HOST", help="override the database host (from inside Docker, "
                   "host.docker.internal is your own computer)")
    r.add_argument("--db-name", metavar="NAME", help="override the database name")
    r.set_defaults(func=cmd_run)

    v = sub.add_parser("verify", help="check the staged tables (add --parity to test the parsers against v1)")
    v.add_argument("--parity", action="store_true",
                   help="also parse the older ABS releases behind data/ and compare (downloads about 10 MB)")
    v.set_defaults(func=cmd_verify)

    args = p.parse_args()
    sys.exit(args.func(args))
