"""
Reclaim workflow cycles whose owning worker is gone.

    python -m backend.app.cli.sweep_stale_workflows
    python -m backend.app.cli.sweep_stale_workflows --grace 120 --json

Exit codes: ``0`` nothing to do or reclaimed cleanly, ``1`` the sweep itself
failed. A non-zero exit is what makes a monitoring system notice.

WHY THIS IS A CLI AND NOT A BUILT-IN SCHEDULER
----------------------------------------------
The application has NO background-task infrastructure: ``lifespan`` starts the
engine and returns, there is no task registry, and no scheduling dependency is
declared in ``requirements.txt``. (APScheduler happens to be present in the
environment as a transitive dependency, but relying on an undeclared transitive
import is how a deploy breaks at the worst moment.)

Three viable triggers, in increasing order of commitment:

**(a) External cron -> this CLI. RECOMMENDED.**
    Zero new runtime surface, works across replicas without coordination, and
    the operator can see every run in the cron log. The sweep is already safe
    under concurrency, so overlapping runs on two hosts are harmless: every
    transition is a compare-and-set whose rowcount decides the winner.
    Example crontab (every 5 minutes)::

        */5 * * * * cd /srv/razorgrowth && python -m backend.app.cli.sweep_stale_workflows

**(b) An ``asyncio`` task started in ``lifespan``.**
    Attractive because it needs no external process, but it starts once per
    application PROCESS. With more than one replica, or with ``--reload``, every
    instance would run its own sweep. That is survivable only because the sweep
    is compare-and-set and idempotent -- and it stays correct precisely because
    of that property. Still, it hides the schedule inside the web process and
    runs only while a web process is alive. Use (a) unless there is a reason
    not to.

**(c) APScheduler / Celery inside the app.**
    Not recommended here. It requires declaring a new dependency and choosing a
    job store, and buys nothing the sweep does not already give: the work is a
    single idempotent statement batch, not a queue of long tasks. Worth
    revisiting if the platform later needs real scheduled work.

The mechanism itself lives in
``backend.app.services.workflow_run_service.sweep_stale_workflows``; this file
only supplies the process, the logging and the exit code.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

log = logging.getLogger("razorgrowth.sweep")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.app.cli.sweep_stale_workflows",
        description="Reclaim workflow cycles whose owning worker is gone.",
    )
    parser.add_argument(
        "--grace", type=int, default=0,
        help="extra seconds of slack before a lease counts as expired "
             "(default 0; the lease already encodes the timeout)",
    )
    parser.add_argument(
        "--max-batch", type=int, default=100,
        help="maximum cycles examined in one pass (default 100)",
    )
    parser.add_argument("--json", action="store_true", help="emit a JSON report")
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    from backend.app.core.config import get_settings
    from backend.app.core.logging import configure_logging
    from backend.app.db.engine import build_engine
    from backend.app.db.session import init_db
    from backend.app.services.workflow_run_service import sweep_stale_workflows

    settings = get_settings()
    configure_logging("INFO")

    # Reuse the application's own engine and session wiring so the CLI cannot
    # drift from how the web process connects.
    engine = build_engine(settings.DATABASE_URL)
    init_db(engine)
    from backend.app.db.session import get_db  # noqa: F401  (bound by init_db)

    from sqlalchemy.orm import Session as OrmSession
    from backend.app.db import session as session_module

    session = session_module._SessionLocal()  # noqa: SLF001
    try:
        report = sweep_stale_workflows(
            session, grace_seconds=args.grace, max_batch=args.max_batch
        )
    except Exception:
        log.exception("stale-workflow sweep failed")
        return 1
    finally:
        session.close()
        engine.dispose()

    if args.json:
        print(json.dumps({
            "scanned": report.scanned,
            "reclaimed": report.reclaimed_count,
            "skipped": report.skipped,
            "steps_interrupted": report.steps_interrupted,
        }, indent=2))
    else:
        log.info(
            "sweep complete: scanned=%d reclaimed=%d skipped=%d steps_closed=%d",
            report.scanned, report.reclaimed_count, report.skipped,
            sum(len(v) for v in report.steps_interrupted.values()),
        )
        for workflow_id, steps in report.steps_interrupted.items():
            log.warning("cycle %s abandoned with steps in flight: %s", workflow_id, steps)
    return 0


if __name__ == "__main__":
    sys.exit(main())