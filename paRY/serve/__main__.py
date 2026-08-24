"""Run the paRY server.

    python -m paRY.serve                       # 127.0.0.1:8900
    python -m paRY.serve --host 0.0.0.0        # reachable on the network
    python -m paRY.serve --origin https://etamil.in

The default bind is loopback. This server compiles source it is sent and is
meant to sit inside the network that owns the code, behind that network's own
authentication — binding it to every interface is a decision, so it has to be
typed out.
"""

from __future__ import annotations

import argparse

import uvicorn

from .. import config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the paRY server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8900)
    parser.add_argument(
        "--origin",
        action="append",
        dest="origins",
        help="an origin the browser client is served from (repeatable)",
    )
    parser.add_argument("--reload", action="store_true", help="restart when the code changes")
    args = parser.parse_args(argv)

    index = config.DATA_DIR / "index" / "paRY.db"
    if not index.exists():
        raise SystemExit(
            f"no index at {index} — run python -m paRY.corpus.collect, "
            "then python -m paRY.index.build"
        )

    if args.origins:
        # uvicorn's reloader re-imports the module, so a configured app cannot
        # be passed through it; origins and --reload are exclusive.
        if args.reload:
            raise SystemExit("--origin and --reload cannot be used together")
        from .app import create_app

        uvicorn.run(create_app(origins=tuple(args.origins)), host=args.host, port=args.port)
    else:
        uvicorn.run("paRY.serve.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
