from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

BASE = Path.cwd()
PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = PROJECT_ROOT / "app"
COLLECTOR_DIR = APP_DIR / "collectors"
# The runner is launched as a standalone script with a per-workflow working
# directory. Add the actual project root so absolute ``app.*`` imports work.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
OUTPUT_DIR = BASE / "Collected_InputData_Extractions_Outputs"
CONFIG_PATH = BASE / "config.json"
SESSION_ROOT = BASE / "browser_sessions"

MONTH_NAMES = {
    1: "farvardin", 2: "ordibehesht", 3: "khordad", 4: "tir",
    5: "mordad", 6: "shahrivar", 7: "mehr", 8: "aban",
    9: "azar", 10: "dey", 11: "bahman", 12: "esfand",
}


def normalise(text: str) -> str:
    table = str.maketrans({
        "ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "ـ": "",
        "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
        "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
        "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
        "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    })
    text = text.translate(table).replace("\u200c", " ")
    text = re.sub(r"[\u200b-\u200f\ufeff]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fingerprint(text: str) -> str:
    compact = re.sub(r"[^\w\u0600-\u06ff]+", "", normalise(text).casefold())
    return hashlib.sha256(compact.encode("utf-8")).hexdigest()


def validate_date(value: str):
    from app.core.jalali import validate_jalali, format_jalali
    year, month, day = validate_jalali(normalise(value))
    return format_jalali(year, month, day), year, month, day


def category_for(channel: dict[str, Any]) -> str:
    category = str(channel.get("deal_type") or channel.get("category") or "").strip().lower()
    if category in {"rent", "rental", "estijari", "rahn", "اجاره", "استیجاری", "رهن", "رهن و اجاره"}:
        return "rental"
    if category in {"sale", "foroshi", "فروش", "فروشی"}:
        return "sale"
    hint = normalise(str(channel.get("search_name", ""))).lower()
    if any(x in hint for x in ("اجاره", "استیجاری", "رهن")):
        return "rental"
    return "sale"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
            if isinstance(value, dict) and value.get("text"):
                rows.append(value)
        except json.JSONDecodeError:
            continue
    return rows


def _record_matches_date(record: dict[str, Any], date_value: str) -> bool:
    wanted = date_value.replace(".", "")
    raw = record.get("date")
    if raw not in (None, ""):
        digits = re.sub(r"\D", "", str(raw))
        if len(digits) >= 8:
            return digits[:8] == wanted
    date_str = normalise(str(record.get("date_str") or ""))
    match = re.search(r"(14\d{2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{1,2})", date_str)
    if not match:
        return False
    try:
        _, y, m, d = validate_date(f"{match.group(1)}.{int(match.group(2)):02d}.{int(match.group(3)):02d}")
        return f"{y:04d}{m:02d}{d:02d}" == wanted
    except ValueError:
        return False


def combine_for_day(config: dict[str, Any], date_value: str, expected_platforms: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Combine one day while preserving message boundaries in a JSONL sidecar.

    The TXT file remains compatible with the legacy property-listing workflow.  The
    JSONL sidecar is authoritative for application imports because a real post
    may contain blank lines internally; splitting that TXT on blank lines would
    incorrectly turn one post into several records.
    """
    date_value, year, month, day = validate_date(date_value)
    day_folder = OUTPUT_DIR / date_value
    day_folder.mkdir(parents=True, exist_ok=True)
    generic_workflow = bool(config.get("workflow_profile") and config.get("workflow_profile") != "real_estate_fa")
    groups: dict[str, list[tuple[str, list[dict[str, Any]]]]] = ({"all": []} if generic_workflow else {"rental": [], "sale": []})
    missing: list[str] = []
    captured_for_day: list[dict[str, Any]] = []

    for platform in ("telegram", "rubika"):
        for channel in config.get(f"{platform}_channels", []):
            username = str(channel.get("username", "")).strip().lstrip("@")
            if not username:
                continue
            source_name = f"{platform}:{username}"
            raw_name = f"{platform}_{username}_raw.txt"
            records_name = f"{platform}_{username}_accepted_records.jsonl"
            all_records_name = f"{platform}_{username}_all_records.jsonl"
            current_records = OUTPUT_DIR / records_name
            archived_records = day_folder / records_name
            current_all_records = OUTPUT_DIR / all_records_name
            archived_all_records = day_folder / all_records_name
            current_raw = OUTPUT_DIR / raw_name
            archived_raw = day_folder / raw_name
            source_records: list[dict[str, Any]] = []

            # Prefer explicit per-message JSONL records.  These preserve the
            # exact boundary emitted by the platform collector, even when the
            # source message itself contains one or more blank lines.
            if current_all_records.exists() or archived_all_records.exists() or current_records.exists() or archived_records.exists():
                # Prefer the complete acquisition sidecar. It includes messages
                # rejected by the legacy real-estate classifier; policy routing
                # happens later in the application, never during acquisition.
                if current_all_records.exists() or archived_all_records.exists():
                    records = _read_jsonl(archived_all_records) + _read_jsonl(current_all_records)
                else:
                    records = _read_jsonl(archived_records) + _read_jsonl(current_records)
                day_records: list[dict[str, Any]] = []
                seen_records: set[str] = set()
                for record in records:
                    if not _record_matches_date(record, date_value):
                        continue
                    text = str(record.get("text") or "").strip()
                    fp = fingerprint(text)
                    if not fp or fp in seen_records:
                        continue
                    seen_records.add(fp)
                    normalized_record = dict(record)
                    normalized_record["text"] = text
                    normalized_record.setdefault("source", source_name)
                    normalized_record.setdefault("platform", platform)
                    normalized_record.setdefault("channel", username)
                    normalized_record.setdefault("collector_filter", {"mode":"all", "matched":True, "reason":"Captured without content filtering"})
                    day_records.append(normalized_record)
                source_records = day_records
                if day_records:
                    with archived_all_records.open("w", encoding="utf-8") as f:
                        for record in day_records:
                            f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    with archived_records.open("w", encoding="utf-8") as f:
                        for record in day_records:
                            if record.get("collector_filter", {}).get("matched", True):
                                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    archived_raw.write_text("\n\n".join(r["text"] for r in day_records), encoding="utf-8")
            else:
                # Legacy TXT-only inputs remain supported.  They cannot encode
                # embedded blank-line boundaries unambiguously, so new collector
                # runs must always use the structured sidecar above.
                candidates = [path for path in (archived_raw, current_raw) if path.exists()]
                if candidates:
                    seen_records: set[str] = set()
                    for source_path in candidates:
                        content = source_path.read_text(encoding="utf-8", errors="replace")
                        for entry in re.split(r"\n\s*\n", content):
                            text = entry.strip()
                            fp = fingerprint(text)
                            if text and fp and fp not in seen_records:
                                seen_records.add(fp)
                                source_records.append({
                                    "text": text,
                                    "date": date_value.replace(".", ""),
                                    "date_str": date_value,
                                    "source": source_name,
                                    "platform": platform,
                                    "channel": username,
                                    "legacy_text_import": True,
                                })
                    if source_records:
                        archived_raw.write_text("\n\n".join(r["text"] for r in source_records), encoding="utf-8")
                elif expected_platforms is None or platform in expected_platforms:
                    missing.append(source_name)

            if source_records:
                groups["all" if generic_workflow else category_for(channel)].append((source_name, source_records))
                captured_for_day.extend(source_records)

    outputs: dict[str, Any] = {}
    output_definitions = (
        (("all", f"messages-{day}-{MONTH_NAMES[month]}.txt"),)
        if generic_workflow else
        (("rental", f"estijari-{day}-{MONTH_NAMES[month]}.txt"), ("sale", f"foroshi-{day}-{MONTH_NAMES[month]}.txt"))
    )
    for key, out_name in output_definitions:
        seen: set[str] = set()
        pieces: list[str] = []
        combined_records: list[dict[str, Any]] = []
        source_counts = {}
        for source_name, entries in groups[key]:
            added = 0
            for record in entries:
                entry = str(record.get("text") or "").strip()
                fp = fingerprint(entry)
                if fp and fp not in seen:
                    seen.add(fp)
                    pieces.append(entry)
                    out_record = dict(record)
                    out_record["text"] = entry
                    out_record.setdefault("source", source_name)
                    out_record.setdefault("posted_date", date_value)
                    combined_records.append(out_record)
                    added += 1
            source_counts[source_name] = {"read": len(entries), "unique_added": added}

        output_path = day_folder / out_name
        output_path.write_text("\n\n".join(pieces), encoding="utf-8")
        records_path = output_path.with_suffix(".jsonl")
        with records_path.open("w", encoding="utf-8") as f:
            for record in combined_records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        outputs[key] = {
            "file": str(output_path.relative_to(BASE)),
            "records_file": str(records_path.relative_to(BASE)),
            "captured_count": sum(len(rows) for _, rows in groups[key]),
            "count": len(combined_records),
            "sources": source_counts,
        }

    captured_path = day_folder / "captured_messages.jsonl"
    # Save all source captures to a single per-day archive, including items the
    # active policy may later hold. This is never filtered or auto-deleted.
    captured_seen: set[str] = set()
    with captured_path.open("w", encoding="utf-8") as f:
        for record in captured_for_day:
            fp = fingerprint(str(record.get("text") or ""))
            key = f"{record.get('source','')}|{record.get('channel','')}|{fp}"
            if not fp or key in captured_seen:
                continue
            captured_seen.add(key)
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    manifest = {
        "date": date_value,
        "platforms_run": list(expected_platforms) if expected_platforms else ["telegram", "rubika"],
        "outputs": outputs,
        "missing_sources": missing,
        "generated_files": [item["file"] for item in outputs.values()],
        "generated_record_files": [item["records_file"] for item in outputs.values()],
        "captured_records_file": str(captured_path.relative_to(BASE)),
        "captured_count": len(captured_seen),
        "workflow_profile": config.get("workflow_profile", "real_estate_fa"),
    }
    (day_folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def read_combined_messages(run_dir: Path, detail: dict[str, Any], fallback_date: str):
    """Yield exact collector messages from JSONL; use TXT splitting only for legacy manifests.

    Returns tuples of (text, source, source_ref, posted_at, native collector decision).
    """
    records_rel = detail.get("records_file")
    records_path = run_dir / str(records_rel) if records_rel else None
    if records_path is not None and records_path.exists():
        with records_path.open("r", encoding="utf-8", errors="replace") as f:
            for index, line in enumerate(f, 1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                text = str(record.get("text") or "").strip()
                if not text:
                    continue
                source = str(record.get("source") or "Telegram/Rubika collection")
                channel = str(record.get("channel") or record.get("username") or "")
                source_ref = f"{source}:{channel or index}"
                yield text, source, source_ref, str(record.get("posted_date") or record.get("date_str") or fallback_date), record.get("collector_filter")
        return

    # Backward compatibility for older manifests that only contain TXT output.
    from app.core.normalization import segment_messages
    text_path = run_dir / str(detail.get("file") or "")
    if not text_path.exists():
        return
    raw = text_path.read_text(encoding="utf-8", errors="replace")
    for index, message in enumerate(segment_messages(raw), 1):
        yield message, "Telegram/Rubika collection", f"{text_path.name}:{index}", fallback_date, None


def _archive_current_range_sources(start_date: str, end_date: str) -> str | None:
    suffixes = ("_raw.txt", "_accepted_records.jsonl", "_all_records.jsonl", "_all_messages.txt", "_classification_audit.jsonl")
    candidates = [p for p in OUTPUT_DIR.iterdir() if p.is_file() and p.name.endswith(suffixes)]
    if not candidates:
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    archive = OUTPUT_DIR / "source_ranges" / f"{start_date}_to_{end_date}" / stamp
    archive.mkdir(parents=True, exist_ok=True)
    for source in candidates:
        shutil.move(str(source), str(archive / source.name))
    return str(archive.relative_to(BASE))


def combine_for_range(
    config: dict[str, Any],
    start_date: str,
    end_date: str,
    expected_platforms: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    _, sy, sm, sd = validate_date(start_date)
    _, ey, em, ed = validate_date(end_date)
    # Iterate in Gregorian ordinals, converting each day back to Jalali. This
    # uses the same Borkowski calendar implementation as the application and
    # does not rely on optional date-formatting packages in the runner.
    from app.core.jalali import jalali_to_gregorian, gregorian_to_jalali
    current = date(*jalali_to_gregorian(sy, sm, sd))
    last = date(*jalali_to_gregorian(ey, em, ed))
    if current > last:
        raise ValueError("Start date must be on or before end date")
    if (last - current).days > 90:
        raise ValueError("A collection range is limited to 90 days")

    days: list[dict[str, Any]] = []
    while current <= last:
        jy, jm, jd = gregorian_to_jalali(current.year, current.month, current.day)
        date_text = f"{jy:04d}.{jm:02d}.{jd:02d}"
        days.append(combine_for_day(config, date_text, expected_platforms))
        current += timedelta(days=1)

    archive = _archive_current_range_sources(start_date, end_date)
    flattened: dict[str, Any] = {}
    for day_manifest in days:
        for kind, detail in day_manifest["outputs"].items():
            flattened[f"{day_manifest['date']}:{kind}"] = detail
    return {
        "start_date": f"{sy:04d}.{sm:02d}.{sd:02d}",
        "end_date": f"{ey:04d}.{em:02d}.{ed:02d}",
        "days": days,
        "outputs": flattened,
        "generated_files": [detail["file"] for detail in flattened.values()],
        "source_archive": archive,
        "captured_count": sum(int(day_manifest.get("captured_count") or 0) for day_manifest in days),
        "total_unique_messages": sum(detail["count"] for detail in flattened.values()),
        # Kept for older dashboards/integrations that still use the original
        # real-estate terminology. Generic workflows use total_unique_messages.
        "total_unique_ads": sum(detail["count"] for detail in flattened.values()),
    }


def main():
    parser = argparse.ArgumentParser(description="Agent Shadi collector runner")
    parser.add_argument("--platform", choices=["telegram", "rubika"], required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    args = parser.parse_args()

    start_date, *_ = validate_date(args.start_date)
    end_date, *_ = validate_date(args.end_date)
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    for platform in ("telegram", "rubika"):
        channels = config.get(f"{platform}_channels", [])
        if platform == args.platform and channels and len(channels) != 1:
            raise ValueError(f"A {platform.title()} collection run must contain exactly one configured channel; found {len(channels)}")
        for item in channels:
            if not re.fullmatch(r"[A-Za-z0-9_]{2,64}", str(item.get("username", "")).lstrip("@")):
                raise ValueError(f"Invalid {platform} channel username in configuration: {item.get('username')!r}")
            if not item.get("url") or not item.get("search_name"):
                raise ValueError(f"Each {platform} channel needs url and search_name")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_ROOT.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(COLLECTOR_DIR))

    import telegram_collector
    import rubika_collector

    for module, platform in ((telegram_collector, "telegram"), (rubika_collector, "rubika")):
        module.CONFIG_PATH = str(CONFIG_PATH)
        module.OUTPUT_DIR = str(OUTPUT_DIR)
        module.SESSION_DIR = str(SESSION_ROOT / platform)
        Path(module.SESSION_DIR).mkdir(parents=True, exist_ok=True)

    print(f"Agent Shadi collector run: {args.platform} · {start_date} → {end_date}", flush=True)
    platform_results: dict[str, Any] = {}
    # Remove previous outputs for the one channel being collected. A failed channel must
    # never cause yesterday's raw file to be mistaken for today's result.
    for active_platform in (args.platform,):
        for channel in config.get(f"{active_platform}_channels", []):
            username = str(channel.get("username", "")).strip().lstrip("@")
            for suffix in ("_raw.txt", "_accepted_records.jsonl", "_all_records.jsonl", "_all_messages.txt", "_classification_audit.jsonl"):
                stale = OUTPUT_DIR / f"{active_platform}_{username}{suffix}"
                if stale.exists():
                    stale.unlink()
    if args.platform == "rubika":
        if config.get("rubika_channels"):
            print("=== RUBIKA COLLECTION ===", flush=True)
            platform_results["rubika"] = rubika_collector.run(start_date, end_date) or {}
        else:
            print("No Rubika channels configured; skipping.", flush=True)
    if args.platform == "telegram":
        if config.get("telegram_channels"):
            print("=== TELEGRAM COLLECTION ===", flush=True)
            platform_results["telegram"] = telegram_collector.run(start_date, end_date) or {}
        else:
            print("No Telegram channels configured; skipping.", flush=True)

    expected_platforms = (args.platform,)
    manifest = combine_for_range(config, start_date, end_date, expected_platforms=expected_platforms)
    total = manifest["total_unique_ads"]
    # Report only messages actually captured by channels in this run. The daily
    # archive may intentionally contain other platforms from earlier runs.
    run_scope_source_counts = {}
    for platform_name, platform_result in platform_results.items():
        for channel_result in platform_result.get("completed_channels", []) or []:
            source_key=f"{platform_name}:{channel_result.get('username') or 'channel'}"
            run_scope_source_counts[source_key]=int(channel_result.get("captured") or channel_result.get("count") or 0)
    manifest["run_import_scope"] = list(expected_platforms)
    manifest["run_scope_source_counts"] = run_scope_source_counts
    manifest["run_scope_captured_count"] = sum(run_scope_source_counts.values())
    collector_warnings = []
    for platform_name, platform_result in platform_results.items():
        for failure in platform_result.get("failed_channels", []) or []:
            collector_warnings.append({"platform":platform_name, **failure})
    manifest["collector_warnings"] = collector_warnings
    manifest["collector_channel_results"] = platform_results
    if collector_warnings:
        print(f"WARNING: {len(collector_warnings)} configured channel(s) failed; successful channel outputs will still be imported.", flush=True)
        for failure in collector_warnings:
            print(f"[Channel failure] {failure.get('platform')}:{failure.get('username')}: {failure.get('error')}", flush=True)
    if total == 0:
        print("WARNING: no accepted ads were available to combine. Check captured-message counts and channel diagnostics.", flush=True)
    print("STRUCTURA_RESULT_JSON=" + json.dumps(manifest, ensure_ascii=False), flush=True)
    print(f"Collection finished. Current-run captures: {manifest['run_scope_captured_count']}; daily combined archive: {total} unique ads across {len(manifest['days'])} day(s).", flush=True)


if __name__ == "__main__":
    main()
