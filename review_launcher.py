#!/usr/bin/env python3
"""Launch wrapper for the desktop Review Desk with a readiness handshake."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def write_state(state: str, detail: str = "") -> None:
    target = os.environ.get("AGENT_SHADI_REVIEW_HANDSHAKE", "").strip()
    if not target:
        return
    path = Path(target)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps({"state": state, "detail": detail[:1200], "pid": os.getpid(), "updated_at": time.time()}), encoding="utf-8")
        temp.replace(path)
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--handshake-file", default="")
    args, _ = parser.parse_known_args()
    if args.handshake_file:
        os.environ["AGENT_SHADI_REVIEW_HANDSHAKE"] = args.handshake_file
    write_state("starting")
    try:
        from review_tui import main as review_main
        code = int(review_main() or 0)
        # Preserve the ready marker: the API uses it to confirm the UI reached
        # its initialized state, even if a very fast user closes the window.
        if code:
            write_state("error", f"Review Desk exited with code {code}.")
        return code
    except BaseException as exc:
        write_state("error", f"{type(exc).__name__}: {exc}")
        print(f"Agent Shadi Review Desk failed to start: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
