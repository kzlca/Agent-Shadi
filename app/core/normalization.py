from __future__ import annotations
import hashlib, json, re, unicodedata
from pathlib import Path
from typing import Any

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_ARABIC = str.maketrans({"ي":"ی", "ى":"ی", "ك":"ک", "ۀ":"هٔ", "ة":"ه", "ـ":""})

def normalize_persian(value: Any, *, digits: bool = False, zwnj: str = " ") -> str:
    if value is None: return ""
    text = unicodedata.normalize("NFKC", str(value)).translate(_ARABIC)
    if digits: text = text.translate(_DIGITS)
    text = text.replace("\u200c", zwnj).replace("\u200f", " ").replace("\u200e", " ").replace("\ufeff", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def compact_fingerprint(text: str) -> str:
    normalized = normalize_persian(text, digits=True).casefold()
    compact = re.sub(r"[^\w\u0600-\u06ff]+", "", normalized)
    return hashlib.sha256(compact.encode("utf-8")).hexdigest() if compact else ""

def preprocess_for_ai(text: str, options: dict[str, Any] | None = None) -> str:
    options = options or {}
    out = normalize_persian(text, digits=bool(options.get("normalize_digits", False)), zwnj=options.get("zwnj", " "))
    if options.get("remove_urls"):
        out = re.sub(r"https?://\S+|www\.\S+", " ", out)
    if options.get("remove_phone_numbers"):
        out = re.sub(r"(?<!\d)(?:\+98|0098|0)?9\d{9}(?!\d)", " ", out)
    for pattern in options.get("remove_patterns", [])[:30]:
        try: out = re.sub(str(pattern), " ", out, flags=re.I | re.M)
        except re.error: continue
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()

def segment_messages(text: str, mode: str = "blank_lines", delimiter: str = "") -> list[str]:
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    if not text.strip(): return []
    if mode == "one_file_one_record":
        return [text.strip()]
    if mode == "custom_delimiter" and delimiter:
        parts = text.split(delimiter)
    else:
        # Channel collector output and common copy/paste format: blank line(s) split posts.
        parts = re.split(r"\n\s*\n+", text)
    cleaned = []
    seen = set()
    for part in parts:
        item = part.strip()
        if not item or re.fullmatch(r"[=\-_*#·\s]{4,}", item): continue
        item = re.sub(r"(?m)^\s*[=\-_*]{5,}\s*$", "", item).strip()
        if not item: continue
        fp = compact_fingerprint(item)
        if fp and fp not in seen:
            cleaned.append(item); seen.add(fp)
    return cleaned

def extract_date_from_filename(filename: str) -> str | None:
    base = Path(filename).stem
    m = re.search(r"(1[234]\d{2})[._-](\d{1,2})[._-](\d{1,2})", base)
    if m: return f"{int(m.group(1)):04d}.{int(m.group(2)):02d}.{int(m.group(3)):02d}"
    return None

def _escape_unquoted_json_string_quotes(content: str) -> str:
    """Escape quote characters embedded inside JSON strings when they are not delimiters."""
    out: list[str] = []
    in_string = False
    escaped = False
    i = 0
    while i < len(content):
        ch = content[i]
        if in_string:
            if escaped:
                out.append(ch)
                escaped = False
            elif ch == "\\":
                out.append(ch)
                escaped = True
            elif ch == '"':
                look = i + 1
                while look < len(content) and content[look].isspace():
                    look += 1
                # A JSON string can end only before a structural delimiter or EOF.
                if look >= len(content) or content[look] in ",}]:":
                    out.append(ch)
                    in_string = False
                else:
                    out.append('\\"')
            elif ord(ch) < 0x20:
                out.append({"\n": r"\n", "\r": r"\r", "\t": r"\t"}.get(ch, f"\\u{ord(ch):04x}"))
            else:
                out.append(ch)
        elif ch == '"':
            in_string = True
            out.append(ch)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _remove_json_trailing_commas(content: str) -> str:
    """Remove commas immediately before an object/array close, outside strings."""
    out: list[str] = []
    in_string = False
    escaped = False
    i = 0
    while i < len(content):
        ch = content[i]
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
            out.append(ch)
        elif ch == ",":
            look = i + 1
            while look < len(content) and content[look].isspace():
                look += 1
            if look >= len(content) or content[look] not in "}]":
                out.append(ch)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _insert_missing_object_commas(content: str) -> str:
    """Repair omitted commas between newline-separated JSON object members."""
    # This is intentionally limited to a value token followed by a quoted key
    # and colon. It does not attempt to invent missing values or closing braces.
    content = re.sub(
        r'(?m)([}\]0-9]|(?<!\\)")([ \t]*\r?\n[ \t]*)(?="[^"\r\n]+"\s*:)',
        r"\1,\2", content,
    )
    return content


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse one model-produced JSON object, tolerating common formatting defects.

    Recovery is deliberately syntax-only: it can remove Markdown fences, escape
    unescaped quotes inside strings, remove trailing commas and insert a missing
    comma between clearly separated object members. It never invents values or
    closes truncated structures.
    """
    content = str(text or "").strip().lstrip("\ufeff")
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", content, flags=re.I | re.S)
    if fenced:
        content = fenced.group(1).strip()
    else:
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.I).strip()

    # Tolerate a short preamble/postscript, but isolate only a complete-looking
    # object candidate. A truncated response is left truncated and will fail.
    start, end = content.find("{"), content.rfind("}")
    if start >= 0 and end > start:
        content = content[start:end + 1]

    attempts = [content]
    repaired = _escape_unquoted_json_string_quotes(content)
    repaired = _remove_json_trailing_commas(repaired)
    repaired = _insert_missing_object_commas(repaired)
    if repaired != content:
        attempts.append(repaired)

    last_error: json.JSONDecodeError | None = None
    for candidate in attempts:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if isinstance(value, dict):
            return value
        raise ValueError("The model response must be a JSON object, not an array or scalar.")

    if last_error:
        raise ValueError(
            f"The model returned malformed or incomplete JSON at line {last_error.lineno}, "
            f"column {last_error.colno}: {last_error.msg}. The proposal was not applied."
        )
    raise ValueError("The model did not return a valid JSON object. The proposal was not applied.")
