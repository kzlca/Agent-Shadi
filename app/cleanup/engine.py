from __future__ import annotations

import difflib
import html
import json
import math
import re
import unicodedata
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import pandas as pd
from rapidfuzz import fuzz, process
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors

from app.jalali import gregorian_to_jalali, jalali_to_gregorian

PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

def _jalali_to_gregorian(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    """Use the shared, strictly validated Borkowski Jalali conversion."""
    return jalali_to_gregorian(jy, jm, jd)


def normalize_persian(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = unicodedata.normalize("NFKC", str(value)).translate(PERSIAN_DIGITS)
    text = text.replace("ي", "ی").replace("ى", "ی").replace("ك", "ک")
    text = text.replace("ۀ", "هٔ").replace("ة", "ه").replace("ـ", "")
    text = text.replace("\u200c", " ").replace("\u200f", " ").replace("\u200e", " ")
    text = text.replace("\ufeff", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def similarity(a: str, b: str) -> float:
    left, right = normalize_persian(a), normalize_persian(b)
    if not left or not right:
        return 0.0
    return 0.55 * fuzz.ratio(left, right) + 0.30 * fuzz.token_set_ratio(left, right) + 0.15 * fuzz.WRatio(left, right)


def _date_sort_value(value: Any) -> tuple[float, str] | None:
    """Return a comparable ordinal and a display string; supports Shamsi and Gregorian dates."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        dt = value.to_pydatetime()
    elif isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, time.min)
    else:
        text = unicodedata.normalize("NFKC", str(value)).translate(PERSIAN_DIGITS).strip()
        text = text.replace("٫", ".").replace("⁄", "/")
        m = re.fullmatch(r"(\d{4})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?", text)
        if m and 1200 <= int(m.group(1)) <= 1499:
            y, mo, d = map(int, m.group(1, 2, 3))
            h, mi, sec = int(m.group(4) or 0), int(m.group(5) or 0), int(m.group(6) or 0)
            try:
                gy, gm, gd = _jalali_to_gregorian(y, mo, d)
                dt = datetime(gy, gm, gd, h, mi, sec)
            except (TypeError, ValueError, OverflowError):
                return None
            ordinal = dt.toordinal() + (h * 3600 + mi * 60 + sec) / 86400
            return ordinal, f"{y:04d}.{mo:02d}.{d:02d}" + (f" {h:02d}:{mi:02d}" if m.group(4) else "")
        try:
            parsed = pd.to_datetime(text, errors="coerce")
            if pd.isna(parsed):
                return None
            dt = pd.Timestamp(parsed).to_pydatetime()
        except Exception:
            return None

    ordinal = dt.toordinal() + (dt.hour * 3600 + dt.minute * 60 + dt.second) / 86400
    return ordinal, dt.strftime("%Y-%m-%d") + (f" {dt.hour:02d}:{dt.minute:02d}" if dt.time() != time.min else "")


def display_date(value: Any) -> str:
    parsed = _date_sort_value(value)
    if parsed:
        return parsed[1]
    return "Date unavailable" if value is None else normalize_persian(value) or "Date unavailable"


def find_message_column(columns: list[Any]) -> str | None:
    names = [str(c).strip() for c in columns]
    candidates = [
        "متن کامل پیام (Full Message)", "متن کامل پیام", "متن کامل",
        "Full Message", "full_message", "message", "raw_text", "text",
    ]
    for candidate in candidates:
        if candidate in names:
            return candidate
    for name in names:
        low = name.casefold()
        if "متن کامل" in name or "full message" in low:
            return name
    return None


def find_date_column(columns: list[Any]) -> str | None:
    names = [str(c).strip() for c in columns]
    candidates = ["تاریخ", "تاریخ و زمان", "تاریخ/زمان", "تاریخ ارسال", "زمان", "Date", "Datetime", "DateTime"]
    for candidate in candidates:
        if candidate in names:
            return candidate
    for name in names:
        low = name.casefold()
        if "تاریخ" in name or "date" in low or "datetime" in low:
            return name
    return None


def _date_groups(df: pd.DataFrame, messages: list[str], date_column: str | None, cross_date: bool) -> dict[str, list[int]]:
    if not date_column or cross_date:
        return {"ALL": [i for i, message in enumerate(messages) if message]}
    groups: dict[str, list[int]] = {}
    for i, message in enumerate(messages):
        if not message:
            continue
        parsed = _date_sort_value(df.iloc[i][date_column])
        key = parsed[1][:10] if parsed else "DATE_UNAVAILABLE"
        groups.setdefault(key, []).append(i)
    return groups


def analyze_dataframe(
    df: pd.DataFrame,
    message_column: str,
    date_column: str | None = None,
    threshold: float = 95.0,
    cross_date: bool = True,
    scan_mode: str = "exhaustive",
    neighbors: int = 100,
) -> list[dict[str, Any]]:
    """Text-aware duplicate scan; exhaustive mode is maximum-recall and the default."""
    if message_column not in df.columns:
        raise ValueError(f"Message column not found: {message_column}")
    if date_column and date_column not in df.columns:
        raise ValueError(f"Date column not found: {date_column}")
    if not 80 <= float(threshold) <= 100:
        raise ValueError("Similarity threshold must be between 80 and 100")
    if scan_mode not in {"exhaustive", "fast"}:
        raise ValueError("Scan mode must be exhaustive or fast")
    neighbors = max(5, min(int(neighbors), 500))

    messages = [normalize_persian(v) for v in df[message_column].tolist()]
    groups = _date_groups(df, messages, date_column, cross_date)
    scores: dict[tuple[int, int], float] = {}
    edges: dict[int, set[int]] = {i: set() for i, message in enumerate(messages) if message}
    char_min = max(0.0, min(100.0, (float(threshold) - 45.0) / 0.55))

    for active in groups.values():
        n = len(active)
        if n < 2:
            continue
        active_text = [messages[i] for i in active]
        if scan_mode == "fast":
            try:
                vectorizer = TfidfVectorizer(
                    analyzer="char", ngram_range=(3, 5), min_df=1,
                    max_df=1.0, sublinear_tf=True, max_features=250_000,
                )
                matrix_x = vectorizer.fit_transform(active_text)
            except ValueError:
                continue
            k = min(neighbors + 1, n)
            nearest = NearestNeighbors(n_neighbors=k, metric="cosine", algorithm="brute", n_jobs=-1)
            nearest.fit(matrix_x)
            distances, indices = nearest.kneighbors(matrix_x)
            candidate_pairs: set[tuple[int, int]] = set()
            for pos, row_indices in enumerate(indices):
                for offset, candidate_pos in enumerate(row_indices[1:], start=1):
                    if 1.0 - float(distances[pos][offset]) < 0.25:
                        continue
                    i, j = sorted((pos, int(candidate_pos)))
                    if i != j:
                        candidate_pairs.add((i, j))
            for i, j in candidate_pairs:
                char_score = fuzz.ratio(active_text[i], active_text[j])
                if char_score < char_min:
                    continue
                score = (0.55 * char_score + 0.30 * fuzz.token_set_ratio(active_text[i], active_text[j])
                         + 0.15 * fuzz.WRatio(active_text[i], active_text[j]))
                if score >= threshold:
                    left_idx, right_idx = active[i], active[j]
                    key = (min(left_idx, right_idx), max(left_idx, right_idx))
                    scores[key] = float(score)
                    edges[left_idx].add(right_idx)
                    edges[right_idx].add(left_idx)
            continue

        # Maximum-recall mode: every unique pair is considered. A safe
        # character-score lower bound avoids expensive scoring of impossible pairs.
        block_size = 192
        for base_start in range(0, n, block_size):
            base_end = min(n, base_start + block_size)
            matrix = process.cdist(
                active_text[base_start:base_end], active_text,
                scorer=fuzz.ratio, score_cutoff=char_min,
                workers=-1, dtype="float32",
            )
            for local_i in range(base_end - base_start):
                global_i = base_start + local_i
                row = matrix[local_i]
                for j in range(global_i + 1, n):
                    char_score = float(row[j])
                    if char_score < char_min:
                        continue
                    left_idx, right_idx = active[global_i], active[j]
                    left, right = active_text[global_i], active_text[j]
                    token_score = fuzz.token_set_ratio(left, right)
                    wratio_score = fuzz.WRatio(left, right)
                    score = 0.55 * char_score + 0.30 * token_score + 0.15 * wratio_score
                    if score >= threshold:
                        key = (min(left_idx, right_idx), max(left_idx, right_idx))
                        scores[key] = float(score)
                        edges[left_idx].add(right_idx)
                        edges[right_idx].add(left_idx)

    visited: set[int] = set()
    result: list[dict[str, Any]] = []
    for node in sorted(edges):
        if node in visited or not edges[node]:
            continue
        stack, component = [node], []
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            component.append(cur)
            stack.extend(edges[cur] - visited)
        if len(component) < 2:
            continue
        members = sorted(component)
        pairs = {f"{a}:{b}": score for (a, b), score in scores.items() if a in component and b in component}
        member_items = []
        for idx in members:
            related = [score for (a, b), score in scores.items() if (a == idx and b in component) or (b == idx and a in component)]
            dt = _date_sort_value(df.iloc[idx][date_column]) if date_column else None
            member_items.append({
                "row_index": idx,
                "excel_row": idx + 2,
                "date": dt[1] if dt else (display_date(df.iloc[idx][date_column]) if date_column else "Date unavailable"),
                "message": messages[idx],
                "best_similarity": round(max(related) if related else 0.0, 2),
            })
        result.append({"members": member_items, "pair_scores": pairs})
    result.sort(key=lambda group: group["members"][0]["row_index"])
    return result


def pair_score(group: dict[str, Any], a: int, b: int) -> float:
    key = f"{min(a,b)}:{max(a,b)}"
    if key in group.get("pair_scores", {}):
        return float(group["pair_scores"][key])
    members = {int(m["row_index"]): m["message"] for m in group.get("members", [])}
    return similarity(str(members.get(a, "")), str(members.get(b, "")))


def _diff_opcodes(left: str, right: str) -> tuple[str, str]:
    left = normalize_persian(left)
    right = normalize_persian(right)
    left_lines = left.splitlines(keepends=True)
    right_lines = right.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(a=left_lines, b=right_lines, autojunk=False)
    left_html: list[str] = []
    right_html: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        a = "".join(left_lines[i1:i2])
        b = "".join(right_lines[j1:j2])
        if tag == "equal":
            safe = html.escape(a).replace("\n", "<br>")
            left_html.append(safe)
            right_html.append(safe)
        elif tag == "replace":
            char_matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
            lparts, rparts = [], []
            for ctag, c1, c2, d1, d2 in char_matcher.get_opcodes():
                la = html.escape(a[c1:c2]).replace("\n", "<br>")
                rb = html.escape(b[d1:d2]).replace("\n", "<br>")
                if ctag == "equal":
                    lparts.append(la); rparts.append(rb)
                elif ctag == "delete":
                    lparts.append(f'<span class="diff-del">{la}</span>')
                elif ctag == "insert":
                    rparts.append(f'<span class="diff-add">{rb}</span>')
                else:
                    lparts.append(f'<span class="diff-del">{la}</span>')
                    rparts.append(f'<span class="diff-add">{rb}</span>')
            left_html.append("".join(lparts)); right_html.append("".join(rparts))
        elif tag == "delete":
            left_html.append(f'<span class="diff-del">{html.escape(a).replace(chr(10), "<br>")}</span>')
        elif tag == "insert":
            right_html.append(f'<span class="diff-add">{html.escape(b).replace(chr(10), "<br>")}</span>')
    return "".join(left_html), "".join(right_html)


def compare_members(group: dict[str, Any], left_index: int, right_index: int) -> dict[str, Any]:
    members = {int(m["row_index"]): m for m in group["members"]}
    if left_index not in members or right_index not in members or left_index == right_index:
        raise ValueError("Choose two different rows from the same duplicate group")
    left, right = members[left_index], members[right_index]
    lhtml, rhtml = _diff_opcodes(left["message"], right["message"])
    score = pair_score(group, left_index, right_index)
    return {
        "score": round(score, 2), "left_html": lhtml, "right_html": rhtml,
        "left_date": left["date"], "right_date": right["date"],
        "identical": score >= 99.9999,
        "warning": "Very close but not identical" if 99 <= score < 99.9999 else ("Near duplicate" if score < 99 else "Identical"),
    }


def choose_survivor(members: list[int], df: pd.DataFrame, date_column: str | None) -> tuple[int, str]:
    if not members:
        raise ValueError("Empty duplicate group")
    if not date_column:
        return members[0], "no_date_column_keep_first"
    dated = []
    for row in members:
        parsed = _date_sort_value(df.iloc[row][date_column])
        if parsed:
            dated.append((row, parsed[0], parsed[1]))
    if not dated:
        return members[0], "no_valid_dates_keep_first"
    day_keys = {entry[2][:10] for entry in dated}
    if len(day_keys) == 1:
        return dated[0][0], "same_date_keep_first"
    newest = max(dated, key=lambda entry: entry[1])
    return newest[0], f"different_dates_keep_newest:{newest[2]}"


def auto_clean_dataframe(
    source_df: pd.DataFrame,
    message_column: str,
    date_column: str | None,
    threshold: float = 95.0,
    cross_date: bool = True,
    max_passes: int = 100,
    scan_mode: str = "exhaustive",
    neighbors: int = 100,
) -> dict[str, Any]:
    active_df = source_df.copy().reset_index(drop=True)
    active_original_indices = list(range(len(source_df)))
    deleted_original: set[int] = set()
    log_rows: list[dict[str, Any]] = []
    passes = 0
    initial_groups: int | None = None
    while passes < max_passes:
        passes += 1
        groups = analyze_dataframe(active_df, message_column, date_column, threshold, cross_date, scan_mode, neighbors) if len(active_df) >= 2 else []
        if initial_groups is None:
            initial_groups = len(groups)
        if not groups:
            break
        delete_local: set[int] = set()
        decisions: list[dict[str, Any]] = []
        for group_no, group in enumerate(groups, start=1):
            members = [int(m["row_index"]) for m in group["members"]]
            keep_local, rule = choose_survivor(members, active_df, date_column)
            candidates = [m for m in members if m != keep_local]
            if not candidates:
                continue
            if rule.startswith("different_dates") and date_column:
                def old_key(idx: int) -> float:
                    parsed = _date_sort_value(active_df.iloc[idx][date_column])
                    return parsed[0] if parsed else float("-inf")
                delete_row = min(candidates, key=old_key)
            else:
                delete_row = next(m for m in candidates if m not in delete_local) if any(m not in delete_local for m in candidates) else candidates[0]
            if delete_row in delete_local:
                continue
            delete_local.add(delete_row)
            keep_orig = active_original_indices[keep_local]
            delete_orig = active_original_indices[delete_row]
            score = pair_score(group, keep_local, delete_row)
            decisions.append({
                "pass": passes, "group_in_pass": group_no, "group_size_in_pass": len(members),
                "kept_original_index": keep_orig, "deleted_original_index": delete_orig,
                "kept_excel_row": keep_orig + 2, "deleted_excel_row": delete_orig + 2,
                "kept_date_time": display_date(active_df.iloc[keep_local][date_column]) if date_column else "",
                "deleted_date_time": display_date(active_df.iloc[delete_row][date_column]) if date_column else "",
                "similarity_percent": round(score, 2), "automatic_rule": rule,
                "decision": "auto_delete_one_per_group_per_pass",
            })
        if not delete_local:
            raise RuntimeError("Auto-clean could not make progress while duplicate groups remained")
        actually_deleted = set()
        for decision in decisions:
            target = int(decision["deleted_original_index"])
            local = active_original_indices.index(target)
            if local in delete_local and target not in actually_deleted:
                log_rows.append(decision)
                actually_deleted.add(target)
        for local_idx in sorted(delete_local, reverse=True):
            deleted_original.add(active_original_indices[local_idx])
            del active_original_indices[local_idx]
        active_df = active_df.drop(index=sorted(delete_local)).reset_index(drop=True)
    else:
        raise RuntimeError(f"Auto-clean reached safety limit ({max_passes} passes) before verification reached zero groups")

    final_groups = analyze_dataframe(active_df, message_column, date_column, threshold, cross_date, scan_mode, neighbors) if len(active_df) >= 2 else []
    if final_groups:
        raise RuntimeError(f"Final verification found {len(final_groups)} duplicate groups remaining")
    return {
        "cleaned_df": active_df, "deleted_original": deleted_original,
        "log_rows": log_rows, "passes": passes, "initial_groups": initial_groups or 0,
        "final_groups": len(final_groups), "original_rows": len(source_df),
    }
