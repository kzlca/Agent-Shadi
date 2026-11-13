"""Operator-controlled collection checkpoint.

Normal application runs do not use Playwright Inspector's debugger toolbar.
The collector opens and verifies the configured channel, then waits here while
an operator positions the visible history. The application Resume endpoint
creates a one-shot signal file to continue collection.

For direct/manual CLI runs without a signal-file path, retain page.pause() as a
compatibility fallback.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import MutableMapping, Any


def enable_inspector_environment(
    env: MutableMapping[str, str], resume_file: str | os.PathLike[str] | None = None
) -> MutableMapping[str, str]:
    """Configure an in-app resume checkpoint without opening Playwright Inspector."""
    # PWDEBUG opens the Inspector and makes every Playwright action appear as a
    # debugger step. That is confusing for ordinary collection, so application
    # runs must not inherit it.
    env.pop("PWDEBUG", None)
    env.pop("STRUCTURA_COLLECTOR_RESUME_FILE", None)
    env["STRUCTURA_COLLECTOR_DEBUG_PAUSE"] = "1"
    if resume_file:
        env["STRUCTURA_COLLECTOR_RESUME_FILE"] = str(resume_file)
    return env


def pause_in_inspector(
    page: Any, platform: str, channel_name: str, end_date: str = "", active_title: str = "",
    selected_result_text: str = "", identity_requires_operator_confirmation: bool = False,
    identity_evidence_match: bool | None = None, operator_instruction: str = "",
) -> bool:
    """Wait for an explicit in-app Continue action after the channel is ready."""
    enabled = os.environ.get("STRUCTURA_COLLECTOR_DEBUG_PAUSE", "1").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return False

    label = f"{platform}|{channel_name}"
    resume_file = os.environ.get("STRUCTURA_COLLECTOR_RESUME_FILE", "").strip()
    if resume_file:
        marker = Path(resume_file)
        # Remove any stale signal before waiting. The API also clears it when a
        # new run starts; this second guard makes direct worker restarts safe.
        try:
            marker.unlink(missing_ok=True)
        except OSError as exc:
            raise RuntimeError(f"Cannot prepare the collection Continue checkpoint: {exc}") from exc

        date_note = f" ({end_date})" if end_date else ""
        header_value = str(active_title or "(not detected)")[:58]
        selected_value = str(selected_result_text or "(click text unavailable)")[:58]
        if operator_instruction:
            instruction = str(operator_instruction).strip()[:300]
        elif identity_requires_operator_confirmation:
            alignment = "MATCH" if identity_evidence_match else "MISMATCH / NOT PROVEN"
            instruction = (
                f"MANUAL IDENTITY CHECK ({alignment}): @{str(channel_name).lstrip('@')[:32]} is not username-verified. "
                f"Clicked result='{selected_value}'. Active chat header detected: '{header_value}'. "
                "Only continue if you recognize both as the intended channel."
            )
            instruction += f" Position history near {end_date or 'the requested end date'} and confirm in Agent Shadi."
        else:
            instruction = f"Configured identity matched. Active chat header detected: '{header_value}'."
            instruction += f" Position history near {end_date or 'the requested end date'} and confirm in Agent Shadi."
        report_collector_phase("operator_paused", platform, channel_name, instruction)
        print(f"STRUCTURA_OPERATOR_PAUSED={label}", flush=True)
        print(
            f"[{platform}] Collection checkpoint. {instruction} "
            "Then press the Continue button in Agent Shadi. Do not use Playwright debugger controls.",
            flush=True,
        )

        started = time.monotonic()
        timeout_seconds = int(os.environ.get("STRUCTURA_COLLECTOR_RESUME_TIMEOUT", "1800"))
        while not marker.exists():
            if getattr(page, "is_closed", lambda: False)():
                raise RuntimeError("The browser tab was closed while waiting for Continue collection.")
            if time.monotonic() - started > timeout_seconds:
                raise RuntimeError(
                    f"Collection remained paused for {timeout_seconds // 60} minutes without an in-app Continue action. "
                    "Start a new collection run when ready."
                )
            page.wait_for_timeout(200)

        try:
            marker.unlink(missing_ok=True)
        except OSError:
            pass
        report_collector_phase(
            "operator_resumed", platform, channel_name,
            "Continue received. Rechecking the selected channel and message-list readiness before collection.",
        )
        print(f"STRUCTURA_OPERATOR_RESUMED={label}", flush=True)
        return True

    # Legacy fallback for direct scripts launched by developers outside the app.
    report_collector_phase(
        "inspector_paused", platform, channel_name,
        "Direct CLI run: position the channel history and press Resume in Playwright Inspector.",
    )
    print(f"STRUCTURA_INSPECTOR_PAUSED={label}", flush=True)
    try:
        page.pause()
    except Exception as exc:
        raise RuntimeError(
            "Could not open the Playwright Inspector breakpoint. Ensure the browser is headed and the script is running in debug mode. "
            "Original error: " + str(exc)
        ) from exc
    report_collector_phase("inspector_resumed", platform, channel_name, "Inspector resumed; verifying channel identity and message readiness.")
    print(f"STRUCTURA_INSPECTOR_RESUMED={label}", flush=True)
    return True


def report_collector_phase(phase: str, platform: str = "", channel: str = "", detail: str = "") -> None:
    """Emit a machine-readable, privacy-safe collector phase for the app monitor."""
    payload = {
        "phase": str(phase or "working")[:80],
        "platform": str(platform or "")[:40],
        "channel": str(channel or "")[:160],
        "detail": str(detail or "")[:300],
    }
    print("STRUCTURA_COLLECTOR_PHASE=" + json.dumps(payload, ensure_ascii=False), flush=True)
