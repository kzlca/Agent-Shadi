import json
import os
import re
import hashlib
import logging
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse

try:
    import emoji
except ImportError:
    class _EmojiFallback:
        @staticmethod
        def emojize(text, language="alias"):
            return text
    emoji = _EmojiFallback()

import jdatetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
try:
    from .browser_runtime import launch_persistent_context
except ImportError:  # collector_runner imports these modules from the collector directory
    from browser_runtime import launch_persistent_context

try:
    from .inspector_control import pause_in_inspector, report_collector_phase
except ImportError:  # collector_runner imports these modules from the collector directory
    from inspector_control import pause_in_inspector, report_collector_phase


CONFIG_PATH = "config.json"
OUTPUT_DIR = "Collected_InputData_Extractions_Outputs"
SESSION_DIR = "./browser_session"

# Keep the original channel configuration as the default, but do not overwrite an
# existing config.json.
DEFAULT_CONFIG = {
    "start_date": "1405.01.01",
    "end_date": "1405.01.01",
    "telegram_channels": [],
    "rubika_channels": [],
}

if not os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=4)

os.makedirs(OUTPUT_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

SELECTORS = {
    "Telegram": {
        "logged_in_indicator": "div.input-search, .sidebar-header, input[type='text']",
        "login_screen_indicator": "canvas, button:has-text('Log in by QR Code'), .auth-form",
        "message_container": ".message, .bubble, .chat-message, div[class*='message'], div[class*='bubble'], div[class*='row']",
    },
    "Rubika": {
        "logged_in_indicator": "ul.chatlist, .chat-list, .chatlist",
        "login_screen_indicator": ".login-container, button:has-text('ورود')",
        "message_container": ".message-item, .message, div[class*='message-item'], div[class*='message']",
    },
}

# =============================================================================
# Persian normalization
# =============================================================================
ARABIC_TO_PERSIAN = str.maketrans({
    "ي": "ی",
    "ى": "ی",
    "ئ": "ئ",
    "ك": "ک",
    "ۀ": "ه",
    "ة": "ه",
    "ؤ": "و",
    "إ": "ا",
    "أ": "ا",
    "ٱ": "ا",
    "ـ": "",  # Tatweel
})

PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def normalize_persian(text: str) -> str:
    """Normalize common Persian/Arabic Unicode and presentation differences."""
    if not text:
        return ""
    text = text.translate(ARABIC_TO_PERSIAN)
    text = text.translate(PERSIAN_DIGITS).translate(ARABIC_DIGITS)
    text = text.replace("\u200c", " ")       # ZWNJ
    text = text.replace("\u200f", "").replace("\u200e", "")
    text = text.replace("\u202a", "").replace("\u202b", "").replace("\u202c", "")
    text = re.sub(r"\s+", " ", text).strip()
    # Normalize hashtags written as '# آپارتمان' to '#آپارتمان'.
    text = re.sub(r"#\s+", "#", text)
    return text


def normalize_for_fingerprint(text: str) -> str:
    text = normalize_persian(text).lower()
    # Remove volatile UI-only whitespace/punctuation while preserving the content.
    text = re.sub(r"[^\w\u0600-\u06ff]+", "", text, flags=re.UNICODE)
    return text


def fingerprint(text: str) -> str:
    return hashlib.sha1(normalize_for_fingerprint(text).encode("utf-8")).hexdigest()


# =============================================================================
# Date parsing
# =============================================================================
MONTHS_FA = {
    "فروردین": 1,
    "اردیبهشت": 2,
    "خرداد": 3,
    "تیر": 4,
    "مرداد": 5,
    "شهریور": 6,
    "مهر": 7,
    "آبان": 8,
    "آذر": 9,
    "دی": 10,
    "بهمن": 11,
    "اسفند": 12,
}

MONTHS_EN = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7,
    "july": 7, "aug": 8, "august": 8, "sep": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def parse_chat_date(date_str, fallback_today_int=None):
    if not date_str:
        return None
    date_text = normalize_persian(str(date_str)).lower()

    if "امروز" in date_text or "today" in date_text:
        return fallback_today_int

    if "دیروز" in date_text or "yesterday" in date_text:
        if fallback_today_int:
            s = str(fallback_today_int)
            try:
                y, m, d = int(s[:4]), int(s[4:6]), int(s[6:8])
                j_date = jdatetime.date(y, m, d) - timedelta(days=1)
                return int(f"{j_date.year}{j_date.month:02d}{j_date.day:02d}")
            except Exception:
                return None
        return None

    # Persian month date, e.g. "17 مرداد" / "17 مرداد 1405"
    parts = date_text.replace("،", " ").split()
    for i, part in enumerate(parts):
        if part in MONTHS_FA:
            day = None
            if i > 0:
                m = re.search(r"\d+", parts[i - 1])
                if m:
                    day = int(m.group())
            if day is None:
                continue
            year = None
            if i + 1 < len(parts) and re.fullmatch(r"\d{4}", parts[i + 1]):
                year = int(parts[i + 1])
            elif fallback_today_int:
                year = int(str(fallback_today_int)[:4])
            else:
                year = 1405
            return int(f"{year}{MONTHS_FA[part]:02d}{day:02d}")

    # Numeric Jalali date: 1405/05/17, 1405-05-17, etc.
    m = re.search(r"(14\d{2})\D+(\d{1,2})\D+(\d{1,2})", date_text)
    if m:
        return int(f"{int(m.group(1)):04d}{int(m.group(2)):02d}{int(m.group(3)):02d}")

    # Gregorian date shown by Telegram Web.
    clean = re.sub(r"\s+at\s+\d{1,2}:\d{2}.*", "", date_text).replace(",", " ").strip()
    tokens = clean.split()
    day = month = year = None
    for token in tokens:
        if token in MONTHS_EN:
            month = MONTHS_EN[token]
        elif token.isdigit():
            val = int(token)
            if len(token) == 4 and val > 31:
                year = val
            elif 1 <= val <= 31 and day is None:
                day = val
    if month and day:
        year = year or datetime.now().year
        try:
            gregorian_dt = datetime(year, month, day)
            jalali = jdatetime.date.fromgregorian(date=gregorian_dt)
            return int(f"{jalali.year}{jalali.month:02d}{jalali.day:02d}")
        except ValueError:
            pass

    return None


# =============================================================================
# High-recall real-estate classifier
# =============================================================================
# These are deliberately broad. The channel is already a real-estate source, so
# we prefer a false-positive diagnostic entry over silently losing a genuine ad.
PROPERTY_TERMS = {
    "ویلایی", "ویلا", "آپارتمان", "اپارتمان", "زمین", "تجاری", "مغازه", "باغ",
    "سوله", "اداری", "سوئیت", "سویت", "ملک", "خانه", "منزل", "انباری", "دفتر",
}
RENT_TERMS = {
    "اجاره", "رهن", "رهن و اجاره", "رهن کامل", "قابل تبدیل", "تبدیل ندارد",
    "رهن: کاری", "اجاره:", "رهن:", "مستاجر", "مستاجری", "استیجاری",
}
PROPERTY_DETAIL_TERMS = {
    "متر", "متری", "متراژ", "زمین", "بنا", "خواب", "طبقه", "پارکینگ", "انباری",
    "آسانسور", "کابینت", "حیاط", "آدرس", "لوکیشن", "خیابان", "کوی", "بلوار",
    "ساخت", "تخلیه", "سند", "گاز", "برق", "آب", "سرامیک", "پکیج",
}
PRICE_PATTERNS = [
    r"\b\d+[\s]*م(?:ی|یون|لیون)?\b",
    r"\b\d+[\s]*(?:میلیون|میلیارد)\b",
    r"(?:رهن|اجاره|پیش)\s*[:：]?\s*[\d.,/]+",
]
CONTACT_PATTERNS = [
    r"(?:09|0098)\d{8,10}",
    r"\b\+?98\d{10}\b",
]
NOISE_EXACT_PATTERNS = [
    r"^پیام سنجاق شد$",
    r"^جستجوی سریع$",
    r"^روش جستجوی سریع$",
]
NOISE_PHRASES = [
    "فایل های شخصی املاک امروز سایت",
    "کانال متقاضی",
]


def compact_words(text: str):
    normalized = normalize_persian(text)
    return set(re.findall(r"[\w\u0600-\u06ff]+", normalized, flags=re.UNICODE))


def classify_real_estate_ad(text: str, channel_hint: str = ""):
    """
    Return (accepted, score, reasons).

    The classifier is intentionally high-recall. It does NOT require a hashtag,
    and it never rejects an ad merely because the word 'مشترک' appears in a
    property description.
    """
    if not text or len(normalize_persian(text)) < 15:
        return False, 0, ["too_short"]

    normalized = normalize_persian(text)
    lowered = normalized.lower()
    words = compact_words(normalized)
    reasons = []
    score = 0

    # Explicit UI/system messages.
    nonempty_lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    if len(nonempty_lines) == 1 and any(re.fullmatch(p, nonempty_lines[0]) for p in NOISE_EXACT_PATTERNS):
        return False, -10, ["ui_noise"]
    if any(p in lowered for p in NOISE_PHRASES):
        return False, -10, ["channel_noise"]

    property_hits = sorted(words.intersection(PROPERTY_TERMS))
    rent_hits = []
    for term in RENT_TERMS:
        if term in lowered:
            rent_hits.append(term)
    detail_hits = sorted(words.intersection(PROPERTY_DETAIL_TERMS))
    price_hits = [p for p in PRICE_PATTERNS if re.search(p, normalized, flags=re.IGNORECASE)]
    contact_hits = [p for p in CONTACT_PATTERNS if re.search(p, normalized)]
    hashtags = re.findall(r"#[\w\u0600-\u06ff]+", normalized, flags=re.UNICODE)

    if property_hits:
        score += 3
        reasons.append(f"property:{','.join(property_hits[:4])}")
    if rent_hits:
        score += 4
        reasons.append(f"rental:{','.join(sorted(set(rent_hits))[:4])}")
    if detail_hits:
        score += min(3, len(detail_hits))
        reasons.append(f"details:{','.join(detail_hits[:5])}")
    if price_hits:
        score += 2
        reasons.append("price_pattern")
    if contact_hits:
        score += 1
        reasons.append("phone")
    if hashtags:
        score += 1
        reasons.append("hashtag")

    # Strong direct rental signals can qualify a message even when the title is
    # malformed or contains no property noun.
    if ("اجاره" in lowered or "رهن" in lowered) and ("متر" in lowered or "خواب" in lowered or "طبقه" in lowered):
        score += 2
        reasons.append("strong_rental_structure")

    # For the rental channel, slightly lower the threshold because the source
    # itself is already semantically constrained to rental listings.
    is_rental_channel = any(k in normalize_persian(channel_hint) for k in ("اجاره", "استیجاری", "رهن"))
    threshold = 4 if is_rental_channel else 5

    accepted = score >= threshold
    if accepted:
        reasons.insert(0, f"accepted_score={score}")
    else:
        reasons.insert(0, f"rejected_score={score}_threshold={threshold}")
    return accepted, score, reasons


# Backwards-compatible name used by older launchers/imports.
def is_valid_real_estate_ad(text, channel_hint=""):
    return classify_real_estate_ad(text, channel_hint)[0]


# =============================================================================
# Footer cleaning / message extraction
# =============================================================================
def clean_rubika_footer(text: str) -> str:
    """Legacy fallback for older extraction paths.

    Primary Rubika extraction now removes metadata at the DOM level, before text
    is returned. Keeping this conservative cleaner avoids changing legitimate ad
    content if a malformed/legacy message ever reaches this point.
    """
    if not text:
        return text
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    if len(lines) < 3:
        return text.strip()

    time_pattern = re.compile(r"^\d{1,2}:\d{2}$")
    views_pattern = re.compile(r"^\d+(?:\.\d+)?[Kk]?$")
    reaction_count_pattern = re.compile(r"^\d+$")

    if not time_pattern.fullmatch(lines[-1].strip()):
        return text.strip()
    if not re.fullmatch(r"[A-Za-zآ-یءئؤإأۀة‌ ]+", lines[-2].strip()):
        return text.strip()
    if not views_pattern.fullmatch(lines[-3].strip()):
        return text.strip()

    remove_count = 3
    if len(lines) >= 4 and reaction_count_pattern.fullmatch(lines[-4].strip()):
        remove_count = 4
        if len(lines) >= 5 and lines[-5].strip() and not re.search(r"[A-Za-zآ-ی0-9]", lines[-5].strip()):
            remove_count = 5
    cleaned = "\n".join(lines[:-remove_count]).strip()
    return cleaned or text.strip()


# =============================================================================
# Authentication / UI helpers
# =============================================================================
def ensure_authenticated(page, platform, base_url, selectors):
    logging.info("Checking %s authentication state...", platform)
    page.goto(base_url, wait_until="domcontentloaded")
    prompted = False
    for attempt in range(1, 121):
        try:
            if page.locator(selectors["logged_in_indicator"]).first.is_visible(timeout=1500):
                logging.info("%s authenticated.", platform)
                return
        except Exception:
            pass
        try:
            if page.locator(selectors["login_screen_indicator"]).first.is_visible(timeout=1500):
                if not prompted:
                    logging.warning("Waiting for %s login. Please scan/login in the browser window.", platform)
                    prompted = True
        except Exception:
            pass
        page.wait_for_timeout(2000)
    raise RuntimeError(f"Timed out waiting for {platform} authentication")


def verify_expected_channel(page, platform, channel_url, search_name, selected_result_text="", expected_active_title=""):
    """Fail closed unless the active chat matches the configured channel."""
    parsed = urlparse(channel_url)
    token_match = re.search(r"@([A-Za-z0-9_]{2,64})", channel_url)
    expected_token = token_match.group(1).casefold() if token_match else ""
    current_url = str(getattr(page, "url", "") or "").casefold()
    if expected_token and expected_token in current_url and not expected_active_title:
        return True
    try:
        titles = page.evaluate("""() => {
          const selectors=['.peer-title','.chat-info .title','.chat-info-container .title',
            'header h3','header [dir=auto]','.topbar .title','[data-testid=chat-info]'];
          return selectors.flatMap(s=>[...document.querySelectorAll(s)])
            .filter(el=>el.getBoundingClientRect().width>0)
            .map(el=>(el.innerText||el.textContent||'').trim()).filter(Boolean).slice(0,12);
        }""") or []
    except Exception:
        titles = []

    def compact(value):
        value = normalize_persian(str(value or "")).casefold().lstrip("@")
        return re.sub(r"[\s@_\-]+", "", value)

    expected = compact(search_name)
    selected = compact(selected_result_text)
    active_expected = compact(expected_active_title)
    for title in titles:
        candidate = compact(title)
        if not candidate:
            continue
        # Manual selections are pinned to the active chat title observed at
        # selection time. A different title after Continue is a hard failure.
        if active_expected:
            if candidate == active_expected:
                return True
            continue
        if expected and (candidate == expected or expected in candidate or candidate in expected):
            return True
        # Search result rows may expose both the human title and @username.
        if selected and (candidate in selected or selected in candidate):
            return True

    host = (urlparse(current_url).hostname or '').casefold()
    expected_host = (parsed.hostname or '').casefold()
    if expected_host and host != expected_host:
        raise RuntimeError(
            f"Collector is on {host or 'an unknown page'}, not {expected_host}. No collection was performed."
        )
    raise RuntimeError(
        f"Cannot verify the active {platform} channel. Expected '{search_name}'"
        + (f" (@{expected_token})" if expected_token else "")
        + f"; visible chat titles: {titles[:5]}. No messages were collected."
    )


def _click_rubika_search_result(page, search_terms):
    """Click only a visible Rubika search row that matches the configured identity."""
    return page.evaluate(r"""(terms) => {
      const norm = value => String(value || '').toLocaleLowerCase()
        .replace(/^@/, '').replace(/[\s@_\-]+/g, '');
      const wanted = (terms || []).map(norm).filter(x => x.length >= 2);
      if (!wanted.length) return {clicked:false, reason:'empty_search_identity'};
      const selectors = [
        '.search-group .chatlist .rp', '.search-group .rp',
        '.search-group .chatlist li', '.search-group .chatlist a',
        '.search-group [class*="chat"]', '.search-group [class*="result"]',
        '.search-group .c-ripple', '.search-group [role="option"]',
        '.search-group [role="button"]', '.search-group li', '.search-group a',
        '.search-group-contacts [class*="chat"]', '.search-group-contacts [class*="result"]',
        '.search-group-contacts .c-ripple', '.search-group-contacts [role="option"]',
        '.search-group-contacts [role="button"]', '.search-group-contacts li', '.search-group-contacts a'
      ];
      const seen = new Set();
      const candidates = selectors.flatMap(selector => [...document.querySelectorAll(selector)])
        .filter(el => {
          if (seen.has(el)) return false;
          seen.add(el);
          const r = el.getBoundingClientRect();
          return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
        });
      let best = null;
      for (const el of candidates) {
        const text = String(el.innerText || el.textContent || '').trim();
        const compact = norm(text);
        if (!compact) continue;
        let score = 0;
        for (const term of wanted) {
          if (compact === term) score = Math.max(score, 100);
          else if (compact.includes(term)) score = Math.max(score, 80);
          else if (term.includes(compact) && compact.length >= 4) score = Math.max(score, 55);
        }
        if (!best || score > best.score) best = {el, text, score};
      }
      if (!best || best.score < 55) {
        return {clicked:false, reason:'no_matching_search_result', candidates:candidates.slice(0,8).map(el=>String(el.innerText||el.textContent||'').trim().slice(0,160))};
      }
      const target = best.el.matches('a,button,[role="button"],.c-ripple')
        ? best.el
        : (best.el.querySelector('a,button,[role="button"],.c-ripple') || best.el);
      target.click();
      return {clicked:true, text:best.text.slice(0,500), score:best.score,
        href:target.getAttribute('href') || best.el.getAttribute('href') || ''};
    }""", search_terms)


def _install_rubika_operator_click_watch(page):
    """Record a real operator click inside Rubika search results."""
    return page.evaluate(r"""() => {
      window.__shadiRubikaSearchStartedAt = Date.now();
      window.__shadiRubikaSearchClick = null;
      if (window.__shadiRubikaSearchClickListenerInstalled) return true;
      window.__shadiRubikaSearchClickListenerInstalled = true;
      document.addEventListener('click', event => {
        const target = event.target && event.target.nodeType === 1 ? event.target : event.target?.parentElement;
        const root = target?.closest?.('.search-group, .search-group-contacts');
        if (!root) return;
        let node = target;
        let selectedText = '';
        for (let depth = 0; node && node !== root && depth < 8; depth++, node = node.parentElement) {
          const text = String(node.innerText || node.textContent || '').replace(/\s+/g, ' ').trim();
          if (text.length >= 3 && text.length <= 900) {
            selectedText = text;
            if (/\d[\d,.]*\s*(مشترک|عضو)/.test(text)) break;
          }
        }
        window.__shadiRubikaSearchClick = {
          at: Date.now(), text: selectedText || String(target?.innerText || target?.textContent || '').trim().slice(0,900)
        };
      }, true);
      return true;
    }""")


def _rubika_active_chat_state(page, message_selector=None):
    """Read visible chat-header candidates and a stable message signature."""
    selector = message_selector or SELECTORS["Rubika"]["message_container"]
    return page.evaluate(r"""selector => {
      const visible = el => !!(el && el.getBoundingClientRect().width > 0 &&
        el.getBoundingClientRect().height > 0 && getComputedStyle(el).visibility !== 'hidden');
      const titleSelectors = [
        '.peer-title', '.chat-info .title', '.chat-info-container .title',
        'header h3', 'header [dir=auto]', '.topbar .title', '[data-testid=chat-info]'
      ];
      const titleDetails = titleSelectors.flatMap(selector =>
        [...document.querySelectorAll(selector)].filter(visible).map(el => ({
          selector, text: String(el.innerText || el.textContent || '').replace(/\s+/g,' ').trim(),
          className: String(el.className || '').slice(0,120),
          rect: (() => { const r=el.getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height}; })()
        }))
      ).filter(x => x.text).slice(0,16);
      const messages = [...document.querySelectorAll(selector)].filter(visible);
      const signature = messages.slice(-10).map(el =>
        String(el.innerText || el.textContent || '').replace(/\s+/g,' ').trim().slice(0,160)
      ).filter(Boolean).join('\u241f');
      const click = window.__shadiRubikaSearchClick || null;
      return {
        title: titleDetails[0]?.text || '', titles: titleDetails.map(x=>x.text).slice(0,12),
        title_details:titleDetails, message_count: messages.length,
        signature, click: click && Number(click.at) >= Number(window.__shadiRubikaSearchStartedAt || 0) ? click : null,
        url: location.href
      };
    }""", selector)

def _rubika_manual_selection_started(page, initial_title=""):
    """Detect the operator's result click early so we never submit stale search input afterward."""
    try:
        state = _rubika_active_chat_state(page)
    except Exception:
        return False
    if state.get("click"):
        return True
    initial = normalize_persian(initial_title).casefold().strip()
    current = normalize_persian(str(state.get("title") or "")).casefold().strip()
    # If there was no active chat before searching, a title appearing in the
    # results overlay is not sufficient evidence. In that case require the
    # captured result-row click event instead.
    return bool(initial and current and current != initial)


def rubika_manual_identity_evidence(clicked_result_text, title_candidates):
    """Compare the clicked result's first line with visible active-header candidates.

    This is only consistency evidence, never proof of username ownership.
    """
    click_text = str(clicked_result_text or "").strip()
    row_title = next((line.strip() for line in click_text.splitlines() if line.strip()), "")

    def identity_key(value):
        value = normalize_persian(str(value or "")).casefold().lstrip("@")
        return re.sub(r"[\W_]+", "", value, flags=re.UNICODE)

    row_key = identity_key(row_title)
    candidates = [str(value).strip() for value in (title_candidates or []) if str(value).strip()]
    matching_header = next((title for title in candidates
        if row_key and identity_key(title) and (
            identity_key(title) == row_key or
            identity_key(title) in row_key or row_key in identity_key(title)
        )), "")
    return {
        "row_title": row_title,
        "matching_header": matching_header,
        "evidence_match": bool(matching_header),
    }


def wait_for_manual_rubika_channel_selection(page, search_name, initial_title="", timeout_seconds=180, visible_candidates=None):
    """Detect the operator's result click and wait for a stable message pane.

    A click is not proof that a result belongs to the configured username. The
    app exposes clicked-row and header evidence and asks the operator to confirm
    the selection before scanning.
    """
    report_collector_phase(
        "operator_select_channel", "Rubika", search_name,
        "Rubika did not expose the configured username in its search results. Select the intended channel result in the browser. The collector will detect the opened chat automatically; do not use Inspector controls."
    )
    logging.info("Rubika did not expose the channel username. Waiting for the operator to select the intended result.")
    deadline = time.monotonic() + max(1, int(timeout_seconds))
    previous_signature = None
    stable_rounds = 0
    last_state = {}
    initial = normalize_persian(initial_title).casefold().strip()
    while time.monotonic() < deadline:
        if getattr(page, "is_closed", lambda: False)():
            raise RuntimeError("The Rubika browser closed while waiting for you to select the channel result.")
        try:
            last_state = _rubika_active_chat_state(page)
        except Exception as exc:
            raise RuntimeError(f"Could not inspect Rubika after manual channel selection: {str(exc)[:220]}") from exc
        title = normalize_persian(str(last_state.get("title") or "")).casefold().strip()
        changed_title = bool(title and (not initial or title != initial))
        operator_clicked = bool(last_state.get("click"))
        messages = int(last_state.get("message_count") or 0)
        signature = str(last_state.get("signature") or "")
        if (operator_clicked or changed_title) and title and messages > 0 and signature:
            if signature == previous_signature:
                stable_rounds += 1
            else:
                previous_signature = signature
                stable_rounds = 0
            if stable_rounds >= 2:
                click_text = str((last_state.get("click") or {}).get("text") or "").strip()
                title_candidates = [str(value).strip() for value in (last_state.get("titles") or []) if str(value).strip()]
                # Compare the row's title with all visible header candidates.
                # This is consistency evidence only, never username ownership.
                evidence = rubika_manual_identity_evidence(click_text, title_candidates)
                active_title = evidence["matching_header"] or str(last_state.get("title") or "").strip()
                evidence_match = bool(evidence["evidence_match"])
                return {
                    "operator_selected": True,
                    "text": click_text or active_title,
                    "clicked_result_text": click_text,
                    "active_title": active_title,
                    "active_title_candidates": title_candidates,
                    "active_title_details": list(last_state.get("title_details") or []),
                    "message_count": messages,
                    "signature": signature,
                    "identity_evidence_match": evidence_match,
                    "identity_requires_operator_confirmation": True,
                }
        else:
            previous_signature = None
            stable_rounds = 0
        page.wait_for_timeout(450)

    raise RuntimeError(
        f"Rubika could not verify an opened channel for '{search_name}'. Select the intended channel result in the browser; "
        f"the collector waited {timeout_seconds}s but did not observe a stable chat. "
        f"Search candidates before the click: {(visible_candidates or [])[:5]}; "
        f"last visible chat titles: {(last_state or {}).get('titles', [])[:5]}; "
        f"visible messages: {(last_state or {}).get('message_count', 0)}. No messages were collected."
    )


def open_channel(page, platform, url, search_name):
    """Wait for the operator to select one Rubika channel; never navigate it."""
    base_url = url.split("#")[0] or "https://web.rubika.ir/"
    ensure_authenticated(page, platform, base_url, SELECTORS.get(platform, SELECTORS["Rubika"]))
    report_collector_phase(
        "operator_select_channel", platform, search_name,
        "Select the intended Rubika channel manually in the open browser. Shadi will not search for or open channels."
    )
    try:
        initial_state = _rubika_active_chat_state(page)
        initial_title = str(initial_state.get("title") or "")
    except Exception:
        initial_title = ""
    _install_rubika_operator_click_watch(page)
    manual = wait_for_manual_rubika_channel_selection(
        page, search_name, initial_title=initial_title,
        timeout_seconds=int(os.environ.get("STRUCTURA_RUBIKA_MANUAL_SELECT_TIMEOUT", "300")),
    )
    selection = {
        "clicked": True,
        "operator_selected": True,
        "text": manual.get("text") or manual.get("active_title"),
        "clicked_result_text": manual.get("clicked_result_text") or "",
        "active_title": manual.get("active_title"),
        "active_title_candidates": manual.get("active_title_candidates") or [],
        "active_title_details": manual.get("active_title_details") or [],
        "identity_evidence_match": bool(manual.get("identity_evidence_match")),
        "identity_requires_operator_confirmation": True,
        "score": 0,
        "message_count": manual.get("message_count", 0),
    }
    expected_active_title = str(selection.get("active_title") or "")
    report_collector_phase(
        "channel_opened", platform, search_name,
        f"Manually selected Rubika chat detected. Header: {expected_active_title or '(unknown)'}. This is not proof of username ownership; operator confirmation is required."
    )
    return selection

def wait_for_rubika_channel_ready(page, platform, channel_url, search_name, selectors, timeout_ms=18000, selected_result_text="", expected_active_title=""):
    """Wait until the verified Rubika chat has a stable visible message list."""
    if getattr(page, "is_closed", lambda: False)(): raise RuntimeError("The browser tab was closed before collection started.")
    verify_expected_channel(page,platform,channel_url,search_name,selected_result_text,expected_active_title=expected_active_title)
    deadline=page.evaluate("() => Date.now()")+timeout_ms
    previous=None; previous_signature=None; stable=0; last={}
    while page.evaluate("() => Date.now()")<deadline:
        if getattr(page, "is_closed", lambda: False)(): raise RuntimeError("The browser tab was closed while the channel was loading.")
        try: login=page.locator(selectors.get("login_screen_indicator","body __never_match__")).first.is_visible(timeout=250)
        except Exception: login=False
        if login: raise RuntimeError(f"{platform} returned to its sign-in screen. Log in again, reopen '{search_name}', and restart collection.")
        try:
            last=page.evaluate(r"""selector => {
              const visible=el=>!!(el && el.getBoundingClientRect().width>0 && el.getBoundingClientRect().height>0);
              const messages=[...document.querySelectorAll(selector)].filter(visible);
              const busy=[...document.querySelectorAll('[aria-busy=true], [role=progressbar], .loading, .loader, .spinner')].some(visible);
              const signature=messages.slice(-8).map(el=>String(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim().slice(0,120)).join('\u241f');
              return {message_count:messages.length,signature,busy,ready_state:document.readyState,title:document.title};
            }""",selectors.get("message_container",".message-item,.message"))
        except Exception as exc: raise RuntimeError(f"Could not inspect Rubika channel readiness: {str(exc)[:240]}") from exc
        count=int(last.get("message_count") or 0)
        signature=str(last.get("signature") or "")
        if count>0 and signature and not last.get("busy"):
            if count==previous and signature==previous_signature: stable+=1
            else: previous=count; previous_signature=signature; stable=0
            if stable>=3: return last
        else: previous=None; previous_signature=None; stable=0
        page.wait_for_timeout(500)
    raise RuntimeError(f"Rubika channel '{search_name}' did not reach a stable message-list state within {timeout_ms//1000}s. No scrolling was attempted. Last browser state: {last}")



def _rubika_scroll_probe(page, message_selector=None):
    """Discover scrollable ancestors of actual message nodes, not guessed CSS classes."""
    selector = message_selector or SELECTORS["Rubika"]["message_container"]
    script = r"""selector => {
      const visible = el => {
        const r=el.getBoundingClientRect(), s=getComputedStyle(el);
        return r.width>80 && r.height>80 && s.display!=='none' && s.visibility!=='hidden';
      };
      let messages=[];
      try { messages=[...document.querySelectorAll(selector)].filter(visible); } catch(e) {}
      if (!messages.length) messages=[...document.querySelectorAll('.message-item,.message,[class*=message]')].filter(visible);
      const primary=[...document.querySelectorAll('.message-item')].filter(visible);
      if (primary.length) messages=primary;
      const aggregate=new Map();
      for (const message of messages.slice(-160)) {
        let node=message;
        for(let depth=0;node && node!==document.documentElement && depth<16;depth++,node=node.parentElement){
          if(!visible(node)) continue;
          const style=getComputedStyle(node), overflowY=style.overflowY||'';
          const range=Math.max(0,node.scrollHeight-node.clientHeight);
          const wheelable=/auto|scroll|overlay|hidden/.test(overflowY);
          if(node.clientHeight<100 || node.clientWidth<160 || (!wheelable && range<8 && depth>6)) continue;
          let item=aggregate.get(node);
          if(!item){
            const r=node.getBoundingClientRect();
            const left=Math.max(0,r.left), right=Math.min(window.innerWidth,r.right);
            const top=Math.max(0,r.top), bottom=Math.min(window.innerHeight,r.bottom);
            item={el:node,depth,contained:0,range,scrollTop:node.scrollTop,scrollHeight:node.scrollHeight,
              clientHeight:node.clientHeight,overflowY,flexDirection:style.flexDirection,
              x:r.x,y:r.y,width:r.width,height:r.height,mouse_x:left+Math.max(0,right-left)*0.55,
              mouse_y:top+Math.max(0,bottom-top)*0.55,wheel_points:[],className:String(node.className||'').slice(0,140),
              tag:node.tagName.toLowerCase()};
            aggregate.set(node,item);
          }
          item.contained++;
          item.depth=Math.min(item.depth,depth);
          const mr=message.getBoundingClientRect();
          if(mr.width>8 && mr.height>8 && mr.bottom>0 && mr.top<window.innerHeight && mr.right>0 && mr.left<window.innerWidth && item.wheel_points.length<10){
            const px=Math.max(1,Math.min(window.innerWidth-1,mr.left+mr.width*0.5));
            const py=Math.max(1,Math.min(window.innerHeight-1,mr.top+mr.height*0.5));
            item.wheel_points.push({x:px,y:py});
          }
        }
      }
      // Some Rubika builds attach scrolling to the document root rather than
      // to a dedicated chat element. Add it only when the page itself really
      // has vertical overflow and contains the visible message cards.
      const pageRoot=document.scrollingElement;
      if(pageRoot && messages.length && pageRoot.scrollHeight-pageRoot.clientHeight>80 && !aggregate.has(pageRoot)){
        const r=pageRoot.getBoundingClientRect();
        aggregate.set(pageRoot,{el:pageRoot,depth:16,contained:messages.filter(m=>pageRoot.contains(m)).length,
          range:pageRoot.scrollHeight-pageRoot.clientHeight,scrollTop:pageRoot.scrollTop,scrollHeight:pageRoot.scrollHeight,
          clientHeight:pageRoot.clientHeight,overflowY:getComputedStyle(pageRoot).overflowY||'',flexDirection:getComputedStyle(pageRoot).flexDirection,
          x:r.x,y:r.y,width:r.width,height:r.height,mouse_x:window.innerWidth*0.55,mouse_y:window.innerHeight*0.55,
          wheel_points:[],className:String(pageRoot.className||'').slice(0,140),tag:pageRoot.tagName.toLowerCase()});
      }
      const candidates=[...aggregate.values()].map(item=>{
        const keyword=/(bubble|message|history|scroll|chat|conversation|virtual)/i.test(item.className)?35:0;
        const overflow=/auto|scroll|overlay/.test(item.overflowY)?45:0;
        const rangeScore=Math.min(50,item.range/80);
        const areaScore=Math.min(30,item.height/30);
        const countScore=Math.min(90,item.contained*3);
        const depthScore=Math.max(0,30-item.depth*3);
        const rootPenalty=item.el===document.body?80:(item.el===document.scrollingElement?110:0);
        item.score=keyword+overflow+rangeScore+areaScore+countScore+depthScore-rootPenalty;
        delete item.el;
        return item;
      }).sort((a,b)=>b.score-a.score).slice(0,12);
      let message_rect=null;
      if(messages.length){
        const rects=messages.slice(-80).map(el=>el.getBoundingClientRect()).filter(r=>r.width>0&&r.height>0);
        if(rects.length){
          const left=Math.min(...rects.map(r=>r.left)), right=Math.max(...rects.map(r=>r.right));
          const top=Math.min(...rects.map(r=>r.top)), bottom=Math.max(...rects.map(r=>r.bottom));
          message_rect={x:left,y:top,width:right-left,height:bottom-top};
        }
      }
      if(!candidates.length && message_rect){
        const left=Math.max(0,message_rect.x), right=Math.min(window.innerWidth,message_rect.x+message_rect.width);
        const top=Math.max(0,message_rect.y), bottom=Math.min(window.innerHeight,message_rect.y+message_rect.height);
        candidates.push({tag:'message-surface',className:'message-surface',depth:0,contained:messages.length,
          scrollTop:0,scrollHeight:0,clientHeight:0,overflowY:'event-target',score:1,
          x:message_rect.x,y:message_rect.y,width:message_rect.width,height:message_rect.height,
          mouse_x:left+Math.max(0,right-left)*0.55,mouse_y:top+Math.max(0,bottom-top)*0.55});
      }
      return {message_count:messages.length,candidates,message_rect};
    }"""
    try:
        return page.evaluate(script, selector) or {"message_count": 0, "candidates": []}
    except Exception as exc:
        return {"message_count": 0, "candidates": [], "error": str(exc)[:240]}


def scroll_up(page, amount=1600, message_selector=None):
    """Adaptively scroll a message-containing container using DOM and wheel input.

    Rubika changes class names and may intercept wheel events. We inspect the
    live ancestors of message cards, try their actual viewport coordinates, and
    record whether the browser moved. We never PageUp a random focused widget.
    """
    probe = _rubika_scroll_probe(page, message_selector)
    candidates = probe.get("candidates") or []
    if not candidates:
        return {"ok": False, "reason": "message_scroller_not_found", "probe": probe}

    attempts = []
    for index, candidate in enumerate(candidates[:12]):
        attempt = {k: candidate.get(k) for k in ("tag", "className", "overflowY", "scrollTop", "scrollHeight", "clientHeight", "depth", "contained", "score")}
        try:
            # A real wheel gesture triggers virtual-list handlers that direct scrollTop
            # mutations may miss. The target is the center of a message ancestor.
            before_live = _rubika_active_chat_state(page, message_selector).get("signature", "")
            before_scroll = get_rubika_scroll_state(page, message_selector) or {}
            if hasattr(page, "mouse"):
                points = candidate.get("wheel_points") or [{
                    "x": candidate.get("mouse_x", float(candidate.get("x", 0)) + float(candidate.get("width", 0)) * 0.55),
                    "y": candidate.get("mouse_y", float(candidate.get("y", 0)) + float(candidate.get("height", 0)) * 0.55),
                }]
                # Prefer actual message-card coordinates over the geometric
                # center of a large wrapper, which may be blank space or a
                # neighboring pane in a responsive Rubika layout.
                if len(points) > 3:
                    points = [points[0], points[len(points)//2], points[-1]]
                for point in points:
                    before_live = _rubika_active_chat_state(page, message_selector).get("signature", "")
                    before_scroll = get_rubika_scroll_state(page, message_selector) or {}
                    x, y = float(point.get("x", 0)), float(point.get("y", 0))
                    page.mouse.move(x, y)
                    page.mouse.wheel(0, -int(amount))
                    page.wait_for_timeout(260)
                    after_live = _rubika_active_chat_state(page, message_selector).get("signature", "")
                    after_scroll = get_rubika_scroll_state(page, message_selector) or {}
                    if ((after_live and after_live != before_live) or
                        (after_scroll and before_scroll and (
                            after_scroll.get("scrollTop") != before_scroll.get("scrollTop") or
                            after_scroll.get("scrollHeight") != before_scroll.get("scrollHeight")
                        ))):
                        attempt["wheel_progress"] = True
                        attempt["wheel_point"] = {"x": x, "y": y}
                        attempts.append(attempt)
                        return {"ok": True, "strategy": "targeted_message_wheel", "candidate": attempt, "attempts": attempts, "probe": probe}
            direct = page.evaluate(r"""({selector,index,amount}) => {
              const visible=el=>{const r=el.getBoundingClientRect();return r.width>80&&r.height>80&&getComputedStyle(el).display!=='none'&&getComputedStyle(el).visibility!=='hidden';};
              let messages=[];try{messages=[...document.querySelectorAll(selector)].filter(visible);}catch(e){}
              const primary=[...document.querySelectorAll('.message-item')].filter(visible);if(primary.length)messages=primary;
              const aggregate=new Map();
              for(const msg of messages.slice(-160)){let n=msg;for(let d=0;n&&n!==document.documentElement&&d<16;d++,n=n.parentElement){
                const s=getComputedStyle(n),r=n.getBoundingClientRect(),range=Math.max(0,n.scrollHeight-n.clientHeight),overflowY=s.overflowY||'';
                const wheelable=/auto|scroll|overlay|hidden/.test(overflowY);
                if(r.width<=80||r.height<=80||n.clientHeight<100||n.clientWidth<160||(!wheelable&&range<8&&d>6))continue;
                let item=aggregate.get(n);if(!item){item={el:n,depth:d};aggregate.set(n,item);}else item.depth=Math.min(item.depth,d);
              }}
              const pageRoot=document.scrollingElement;
              if(pageRoot&&messages.length&&pageRoot.scrollHeight-pageRoot.clientHeight>80&&!aggregate.has(pageRoot))aggregate.set(pageRoot,{el:pageRoot,depth:16});
              const list=[...aggregate.values()].map(item=>{const el=item.el,s=getComputedStyle(el),r=el.getBoundingClientRect();
                const contained=messages.filter(m=>el.contains(m)).length,cls=String(el.className||''),range=Math.max(0,el.scrollHeight-el.clientHeight);
                const score=contained*3+Math.min(50,range/80)+Math.min(30,r.height/30)
                  +(/bubble|message|history|scroll|chat|conversation|virtual/i.test(cls)?35:0)
                  +(/auto|scroll|overlay/.test(s.overflowY||'')?45:0)+Math.max(0,30-item.depth*3)
                  -(el===document.body?80:(el===document.scrollingElement?110:0));
                return {el,score,depth:item.depth};}).sort((a,b)=>b.score-a.score);
              const selected=list[index];if(!selected)return {ok:false,reason:'candidate_disappeared'};
              const el=selected.el,before=el.scrollTop,maxScroll=Math.max(0,el.scrollHeight-el.clientHeight);
              if(maxScroll>0 || /auto|scroll|overlay|hidden/.test(getComputedStyle(el).overflowY||'')){
                el.scrollBy({top:-amount,behavior:'instant'});
                el.dispatchEvent(new Event('scroll',{bubbles:true}));
              }
              const after=el.scrollTop,rect=el.getBoundingClientRect();
              return {ok:true,before,after,maxScroll,scrollHeight:el.scrollHeight,clientHeight:el.clientHeight,
                moved:Math.abs(after-before)>0.5,className:String(el.className||'').slice(0,140),tag:el.tagName.toLowerCase(),depth:selected.depth,
                x:rect.x,y:rect.y,width:rect.width,height:rect.height};
            }""", {"selector": message_selector or SELECTORS["Rubika"]["message_container"], "index": index, "amount": int(amount)})
            attempt["direct"] = direct
            attempts.append(attempt)
            same_candidate = (
                str(direct.get("tag") or candidate.get("tag") or "").lower() == str(candidate.get("tag") or "").lower()
                and str(direct.get("className") or "") == str(candidate.get("className") or "")
                and int(direct.get("depth", candidate.get("depth", -1))) == int(candidate.get("depth", -1))
            )
            wheel_moved = (
                same_candidate and direct.get("ok")
                and abs(float(direct.get("before", candidate.get("scrollTop", 0))) - float(candidate.get("scrollTop", 0))) > 0.5
            )
            direct_moved = bool(direct.get("moved")) and abs(float(direct.get("after", 0)) - float(direct.get("before", 0))) > 0.5
            if direct_moved:
                return {"ok": True, "strategy": "targeted_dom_scroll", "candidate": attempt, "attempts": attempts, "probe": probe}
            if wheel_moved:
                attempt["wheel_progress"] = True
                return {"ok": True, "strategy": "targeted_mouse_wheel", "candidate": attempt, "attempts": attempts, "probe": probe}
            # A successful evaluate() call is NOT evidence of a scroll. The
            # previous implementation returned here even when scrollTop did not
            # change, preventing it from trying the next real message ancestor.
            # Continue through all candidates instead of retrying the same dead pane.
        except Exception as exc:
            attempt["error"] = str(exc)[:220]
            attempts.append(attempt)

    return {"ok": False, "reason": "scroll_attempts_exhausted", "attempts": attempts, "probe": probe}


def get_rubika_scroll_state(page, message_selector=None):
    """Return the best live message scroller and alternatives for diagnostics."""
    probe = _rubika_scroll_probe(page, message_selector)
    candidates = probe.get("candidates") or []
    if not candidates:
        return None
    best = dict(candidates[0])
    best["candidate_count"] = len(candidates)
    best["message_count"] = probe.get("message_count", 0)
    best["alternatives"] = candidates[1:4]
    return best

def _oldest_rubika_visible_date(page, selectors, fallback_date):
    try:
        payload=extract_visible_messages(page,selectors,fallback_date)
        dates=[parse_chat_date(x.get("date_str", ""),fallback_today_int=fallback_date) for x in payload.get("items",[])]
        valid=[x for x in dates if x is not None]
        return min(valid) if valid else None
    except Exception:
        return None


def wait_for_rubika_progress(page, previous_state, previous_oldest, selectors, fallback_date, timeout_ms=7000):
    """Wait for the message scroller or oldest visible date to actually advance."""
    try:
        deadline=page.evaluate("() => Date.now()")+timeout_ms
        last_state=previous_state
        while page.evaluate("() => Date.now()")<deadline:
            page.wait_for_timeout(350)
            state=get_rubika_scroll_state(page, selectors.get("message_container"))
            oldest=_oldest_rubika_visible_date(page,selectors,fallback_date)
            try:
                live_signature=str(_rubika_active_chat_state(page, selectors.get("message_container")).get("signature") or "")
            except Exception:
                live_signature=""
            previous_signature=str((previous_state or {}).get("viewport_signature") or "")
            if oldest is not None and (previous_oldest is None or oldest<previous_oldest):
                return True,state,oldest
            if live_signature and previous_signature and live_signature != previous_signature:
                return True,state,oldest
            if state and last_state and (
                state.get("scrollHeight")!=last_state.get("scrollHeight") or
                state.get("scrollTop")!=last_state.get("scrollTop") or
                state.get("className")!=last_state.get("className")
            ):
                return True,state,oldest
            last_state=state
        return False,get_rubika_scroll_state(page, selectors.get("message_container")),_oldest_rubika_visible_date(page,selectors,fallback_date)
    except Exception:
        return False,get_rubika_scroll_state(page, selectors.get("message_container")),_oldest_rubika_visible_date(page,selectors,fallback_date)


JS_EXTRACT = r"""
(args) => {
    const containerSelector = args[0];
    const fallbackDate = args[2];

    // Rubika date separators are structural UI elements, not message text.
    const dateSelector = '.bubble.service.is-date, .is-date';

    const dateNodes = Array.from(document.querySelectorAll(dateSelector));

    // Prefer Rubika's original `.message-item` post container. The old broad
    // selector also matched nested div[class*=message] descendants (message
    // text/body/meta wrappers), which could be emitted as tiny separate posts.
    let messageCandidates = Array.from(document.querySelectorAll('.message-item'));
    if (!messageCandidates.length) {
        messageCandidates = Array.from(document.querySelectorAll('.message'));
    }
    if (!messageCandidates.length) {
        messageCandidates = Array.from(document.querySelectorAll('div[class*="message"]'))
            .filter(el => !/(?:message[-_ ]?(?:text|body|content|time|date|meta|author|sender|reaction|status|header|footer))/i.test(String(el.className || '')));
    }

    const candidateSet = new Set(messageCandidates);
    const messageNodes = messageCandidates.filter(el => {
        let parent = el.parentElement;
        while (parent && parent !== document.body) {
            if (candidateSet.has(parent)) return false;
            parent = parent.parentElement;
        }
        return true;
    });
    const nodes = [...dateNodes, ...messageNodes].sort((a, b) => {
        const relation = a.compareDocumentPosition(b);
        return relation & Node.DOCUMENT_POSITION_FOLLOWING ? -1 :
               relation & Node.DOCUMENT_POSITION_PRECEDING ? 1 : 0;
    });

    const results = [];

    // Keep the message's explicit DOM line structure.  Rubika uses <br> for
    // message line breaks, but rendered innerText is not reliable for every UI
    // state (especially some messages with attached media).  Convert <br>
    // elements explicitly before reading textContent.
    const cleanRenderedText = (value) => {
        if (!value) return '';

        return value
            .replace(/\r/g, '')
            .split('\n')
            .map(line => line.replace(/[ \t\f\v]+/g, ' ').trim())
            .filter((line, index, arr) => {
                // Remove blank lines only at the very beginning/end.  Internal
                // blank lines are meaningful section separators in many ads.
                if (line !== '') return true;
                return index > 0 && index < arr.length - 1;
            })
            .join('\n')
            .trim();
    };

    const extractDomText = (root) => {
        const clone = root.cloneNode(true);

        // Only explicit Rubika line-break elements are converted.  This avoids
        // depending on CSS/rendering behavior and preserves double <br><br>
        // separators exactly as newline characters.
        clone.querySelectorAll('br').forEach(br => {
            br.replaceWith(document.createTextNode('\n'));
        });

        return cleanRenderedText(clone.textContent || '');
    };

    // Extract the actual listing node whenever possible.  Known Rubika metadata
    // lives outside this node, so it never enters the extracted text.
    const extractAdText = (messageEl) => {
        const copyable = messageEl.querySelector('[rb-copyable]');
        if (copyable) {
            const text = extractDomText(copyable);
            if (text) return text;
        }

        // Guarded fallback for UI variants where rb-copyable is missing.
        // Clone the message DOM, remove only known metadata/UI nodes, then
        // convert explicit <br> elements before reading textContent.
        const clone = messageEl.cloneNode(true);
        clone.querySelectorAll(
            '.reactions.reactions-block, [rb-message-time], .service-msg, .is-date'
        ).forEach(node => node.remove());

        return extractDomText(clone);
    };

    let currentDate = fallbackDate || 'امروز';

    for (const el of nodes) {
        if (el.matches(dateSelector) || el.classList.contains('is-date')) {
            const value = (el.innerText || '').trim();
            if (value) currentDate = value;
            continue;
        }

        // Ignore Rubika service/system notices.
        if (el.classList.contains('service-msg')) continue;
        if (!el.matches(containerSelector)) continue;

        const text = extractAdText(el);
        if (!text) continue;

        const rect = el.getBoundingClientRect();
        results.push({
            text,
            date_str: currentDate,
            dom_hint: `${Math.round(rect.top)}:${Math.round(rect.left)}:${text.slice(0,80)}`
        });
    }

    return {
        items: results,
        page_height: document.documentElement.scrollHeight
    };
}
"""





def extract_visible_messages(page, selectors, fallback_date):
    return page.evaluate(
        JS_EXTRACT,
        [selectors["message_container"], ".bubble.service.is-date, .is-date", fallback_date],
    )


# =============================================================================
# Main high-recall extractor
# =============================================================================
def rubika_visible_signature(items):
    """Compact fingerprint of the current virtualized viewport, independent of duplicate capture count."""
    return tuple(fingerprint(str(item.get("text") or "").strip()) for item in items if str(item.get("text") or "").strip())


def rubika_scroll_state_signature(state):
    if not state:
        return None
    return (
        round(float(state.get("scrollTop", 0)), 1),
        int(state.get("scrollHeight", 0)),
        int(state.get("clientHeight", 0)),
        str(state.get("className") or ""),
        str(state.get("overflowY") or ""),
    )


def extract_messages(page, platform, url, search_name, selectors, start_date_str, end_date_str):
    selection = open_channel(page, platform, url, search_name)
    # Prove the result is really open and the message list is loaded before
    # asking the operator to position history. The app Continue action replaces
    # the confusing two-stage Playwright Inspector Resume sequence.
    expected_active_title = str(selection.get("active_title") or "")
    verify_expected_channel(
        page, platform, url, search_name, selection.get("text", ""),
        expected_active_title=expected_active_title,
    )
    readiness = wait_for_rubika_channel_ready(
        page, platform, url, search_name, selectors,
        selected_result_text=selection.get("text", ""), expected_active_title=expected_active_title,
    )
    logging.info("%s channel verified and message list stable (%s visible); waiting for operator positioning", platform, readiness.get("message_count"))
    pause_in_inspector(
        page, platform, search_name, end_date_str,
        active_title=expected_active_title,
        selected_result_text=(
            selection.get("clicked_result_text", "")
            if selection.get("identity_requires_operator_confirmation")
            else selection.get("text", "")
        ),
        identity_requires_operator_confirmation=bool(selection.get("identity_requires_operator_confirmation")),
        identity_evidence_match=selection.get("identity_evidence_match"),
    )
    verify_expected_channel(
        page, platform, url, search_name, selection.get("text", ""),
        expected_active_title=expected_active_title,
    )
    readiness = wait_for_rubika_channel_ready(
        page, platform, url, search_name, selectors,
        selected_result_text=selection.get("text", ""), expected_active_title=expected_active_title,
    )
    logging.info("%s resumed on verified channel; message list stable (%s visible); scanning from the selected position", platform, readiness.get("message_count"))

    start_date_int = int(start_date_str.replace(".", ""))
    end_date_int = int(end_date_str.replace(".", ""))

    # We intentionally collect before filtering.
    raw_by_fingerprint = {}
    rejected = []
    reached_start_boundary = False
    oldest_seen = None
    no_new_cycles = 0
    no_progress_cycles = 0
    consecutive_scroll_failures = 0
    last_scroll_signature = None
    last_view_signature = None
    last_scroll_state_signature = None
    last_oldest_date = None
    scan_complete = False
    manual_recovery_count = 0

    def request_manual_history_recovery(cycle_number, reason, previous_oldest, previous_scroll_state):
        """Offer a bounded in-app manual fallback when adaptive scrolling cannot move.

        This is not a blind retry: the channel is revalidated after the operator
        acts, and the checkpoint only counts as recovery if the visible messages,
        scroll state, or oldest parsed date actually changes.
        """
        nonlocal manual_recovery_count, consecutive_scroll_failures
        if not os.environ.get("STRUCTURA_COLLECTOR_RESUME_FILE") or manual_recovery_count >= 2:
            return False
        manual_recovery_count += 1
        current_state = {}
        try:
            current_state = _rubika_active_chat_state(page, selectors.get("message_container")) or {}
        except Exception:
            pass
        before_signature = str(current_state.get("signature") or "")
        before_scroll_signature = rubika_scroll_state_signature(previous_scroll_state)
        detail = (
            f"MANUAL HISTORY RECOVERY: automatic Rubika scrolling stalled at cycle {cycle_number}. "
            f"Reason: {str(reason)[:90]}. Keep the same channel open, hover the message list and scroll upward "
            f"manually until older messages appear, then press Continue history. Attempt {manual_recovery_count}/2."
        )
        report_collector_phase("scroll_recovery_required", platform, search_name, detail)
        logging.warning("Rubika manual history recovery requested: %s", detail)
        pause_in_inspector(
            page, platform, search_name, start_date_str,
            active_title=expected_active_title,
            selected_result_text=(selection.get("clicked_result_text", "")
                                  if selection.get("identity_requires_operator_confirmation")
                                  else selection.get("text", "")),
            identity_requires_operator_confirmation=bool(selection.get("identity_requires_operator_confirmation")),
            identity_evidence_match=selection.get("identity_evidence_match"),
            operator_instruction=detail,
        )
        verify_expected_channel(
            page, platform, url, search_name, selection.get("text", ""),
            expected_active_title=expected_active_title,
        )
        wait_for_rubika_channel_ready(
            page, platform, url, search_name, selectors,
            selected_result_text=selection.get("text", ""), expected_active_title=expected_active_title,
        )
        recovered_oldest = _oldest_rubika_visible_date(page, selectors, end_date_int)
        try:
            recovered_state = _rubika_active_chat_state(page, selectors.get("message_container")) or {}
        except Exception:
            recovered_state = {}
        recovered_signature = str(recovered_state.get("signature") or "")
        recovered_scroll = get_rubika_scroll_state(page, selectors.get("message_container")) or {}
        recovered_scroll_signature = rubika_scroll_state_signature(recovered_scroll)
        changed = (
            (recovered_oldest is not None and previous_oldest is not None and recovered_oldest < previous_oldest)
            or (recovered_signature and recovered_signature != before_signature)
            or (recovered_scroll_signature and recovered_scroll_signature != before_scroll_signature)
        )
        if not changed:
            raise RuntimeError(
                "Manual history recovery was confirmed, but the visible message list still did not change. "
                "The collector kept the browser open and stopped safely. Make sure the pointer is over the message "
                "list (not the sidebar), scroll upward inside it, and check that the oldest visible date changes. "
                f"Oldest date before={previous_oldest}, after={recovered_oldest}; "
                f"message signature changed={bool(recovered_signature and recovered_signature != before_signature)}; "
                f"scroll state before={before_scroll_state}, after={recovered_scroll}."
            )
        consecutive_scroll_failures = 0
        report_collector_phase(
            "history_recovered", platform, search_name,
            f"Manual recovery detected real history movement. Oldest visible date: {recovered_oldest or 'date unchanged'}; resuming automatic scan."
        )
        logging.info("Rubika manual recovery succeeded; continuing automatic history scan.")
        return True

    # A bounded but substantially larger safety limit than the old version.
    max_cycles = 500

    logging.info(
        "%s: high-recall collection from %s through %s",
        platform,
        start_date_str,
        end_date_str,
    )

    current_fallback = end_date_int

    for cycle in range(1, max_cycles + 1):
        if cycle == 1 or cycle % 5 == 0:
            report_collector_phase("scanning_history", platform, search_name, f"History scan cycle {cycle}; {len(raw_by_fingerprint)} unique in-range messages captured.")
        verify_expected_channel(
            page, platform, url, search_name, selection.get("text", ""),
            expected_active_title=expected_active_title,
        )
        payload = extract_visible_messages(page, selectors, current_fallback)
        items = payload.get("items", [])

        before_count = len(raw_by_fingerprint)
        cycle_oldest = None
        cycle_newest = None

        for item in items:
            text = emoji.emojize(item.get("text", ""), language="alias").strip()
            date_str = item.get("date_str", "")
            parsed_date = parse_chat_date(date_str, fallback_today_int=end_date_int)
            if parsed_date is None:
                # Don't silently discard it; record the reason for diagnostics.
                fp = fingerprint(text) if text else None
                if fp:
                    rejected.append({
                        "date_str": date_str,
                        "parsed_date": None,
                        "text": text,
                        "reason": "unparsed_date",
                    })
                continue

            cycle_oldest = parsed_date if cycle_oldest is None else min(cycle_oldest, parsed_date)
            cycle_newest = parsed_date if cycle_newest is None else max(cycle_newest, parsed_date)
            oldest_seen = parsed_date if oldest_seen is None else min(oldest_seen, parsed_date)

            if parsed_date < start_date_int:
                reached_start_boundary = True
                continue
            if parsed_date > end_date_int:
                continue
            if len(text) < 5:
                continue

            # Rubika metadata is removed at the DOM level in JS_EXTRACT.
            # Do not run the legacy footer regex here: the ad's final lines are
            # legitimate content and should never be removed heuristically.
            cleaned = text.strip()
            fp = fingerprint(cleaned)
            if not fp:
                continue

            # Keep the first complete version of the message.
            if fp not in raw_by_fingerprint:
                raw_by_fingerprint[fp] = {
                    "text": cleaned,
                    "date": parsed_date,
                    "date_str": date_str,
                }

        if cycle == 1 and cycle_newest is not None and cycle_newest < start_date_int:
            raise RuntimeError(
                f"The visible Rubika history is already older than the requested start date ({cycle_newest} < {start_date_int}). "
                "No scrolling or collection was attempted. Return to this channel and position at the requested end date before resuming."
            )

        new_count = len(raw_by_fingerprint) - before_count
        no_new_cycles = 0 if new_count else no_new_cycles + 1
        current_view_signature=rubika_visible_signature(items)
        current_scroll_state=get_rubika_scroll_state(page, selectors.get("message_container"))
        current_scroll_signature=rubika_scroll_state_signature(current_scroll_state)
        older_history_appeared=(cycle_oldest is not None and last_oldest_date is not None and cycle_oldest < last_oldest_date)
        viewport_changed=(current_view_signature != last_view_signature) or (current_scroll_signature != last_scroll_state_signature)
        if viewport_changed or older_history_appeared:
            no_progress_cycles=0
        else:
            no_progress_cycles+=1
        last_view_signature=current_view_signature
        last_scroll_state_signature=current_scroll_signature
        if cycle_oldest is not None:
            last_oldest_date=cycle_oldest if last_oldest_date is None else min(last_oldest_date,cycle_oldest)

        logging.info(
            "%s cycle %d: visible=%d, unique_in_range=%d, new=%d, oldest=%s",
            platform,
            cycle,
            len(items),
            len(raw_by_fingerprint),
            new_count,
            cycle_oldest,
        )

        # Once we have seen a date older than the requested start and scrolling
        # is no longer exposing new messages, the target interval is complete.
        if reached_start_boundary and no_new_cycles >= 3:
            scan_complete = True
            report_collector_phase("history_boundary_confirmed", platform, search_name, f"Requested start boundary {start_date_int} confirmed after three scans without new in-range messages.")
            break
        if no_progress_cycles >= 20:
            logging.warning("Stopping after 20 cycles without any observable viewport, scroll-position or older-date progress.")
            rejected.append({"reason":"collector_stalled","cycle":cycle,"oldest_seen":oldest_seen,"unique_in_range":len(raw_by_fingerprint),"no_progress_cycles":no_progress_cycles})
            break

        report_collector_phase("loading_older_history", platform, search_name, f"Loading older Rubika history after scan cycle {cycle}.")
        previous_scroll=get_rubika_scroll_state(page, selectors.get("message_container")) or {}
        try:
            previous_scroll["viewport_signature"] = str(_rubika_active_chat_state(page, selectors.get("message_container")).get("signature") or "")
        except Exception:
            previous_scroll["viewport_signature"] = ""
        previous_oldest=cycle_oldest
        scroll_state = scroll_up(page, message_selector=selectors.get("message_container"))
        if not scroll_state.get("ok"):
            detail=scroll_state.get("reason","unknown")
            probe_detail = json.dumps(scroll_state.get("probe") or scroll_state.get("attempts") or {}, ensure_ascii=False, default=str)[:1400]
            logging.warning("Rubika scroll candidates exhausted at cycle %s: %s", cycle, probe_detail)
            if request_manual_history_recovery(cycle, detail, cycle_oldest, previous_scroll):
                last_view_signature = None
                last_scroll_state_signature = None
                last_oldest_date = cycle_oldest
                no_progress_cycles = 0
                continue
            rejected.append({"reason":"message_scroller_not_found","cycle":cycle,"detail":detail,"probe":scroll_state})
            raise RuntimeError(f"Could not identify or operate Rubika's message-history scroller ({detail}). DOM evidence: {probe_detail}. The collector stopped safely; no unrelated pane or page scrolling was attempted.")
        candidate = scroll_state.get("candidate") or {}
        direct = candidate.get("direct") or {}
        phase_detail = (
            f"Adaptive scroll strategy={scroll_state.get('strategy')}; target={str(candidate.get('className') or candidate.get('tag') or 'message area')[:90]}; "
            f"scrollTop={direct.get('before', candidate.get('scrollTop', 'n/a'))}->{direct.get('after', 'wheel')}; "
            f"message ancestors={candidate.get('contained', 'n/a')}"
        )
        report_collector_phase("scroll_strategy", platform, search_name, phase_detail)
        logging.info("Rubika adaptive scroll: %s", phase_detail)
        progressed,new_scroll,new_oldest=wait_for_rubika_progress(page,previous_scroll,previous_oldest,selectors,end_date_int,timeout_ms=7000)
        if not progressed:
            consecutive_scroll_failures += 1
            diagnostic = {
                "cycle": cycle,
                "scroll": scroll_state,
                "before": previous_scroll,
                "after": new_scroll,
                "oldest_before": previous_oldest,
                "oldest_after": new_oldest,
            }
            logging.warning("%s cycle %d: adaptive scroll attempt %d made no observable history progress: %s", platform, cycle, consecutive_scroll_failures, json.dumps(diagnostic, ensure_ascii=False, default=str)[:1800])
            if consecutive_scroll_failures >= 2:
                diagnostic_text = json.dumps(diagnostic, ensure_ascii=False, default=str)[:2200]
                if request_manual_history_recovery(cycle, "two adaptive attempts showed no message-history movement", cycle_oldest, previous_scroll):
                    last_view_signature = None
                    last_scroll_state_signature = None
                    last_oldest_date = cycle_oldest
                    no_progress_cycles = 0
                    continue
                raise RuntimeError(
                    "Rubika history is not moving. The collector inspected message-containing scroll containers, "
                    "tried targeted mouse-wheel input and direct container scrolling twice, and observed no older "
                    "messages or viewport movement. It stopped safely instead of looping or collecting the wrong area. "
                    f"Scroll diagnostics: {diagnostic_text}"
                )
        else:
            consecutive_scroll_failures = 0
        signature = json.dumps({
            "count": len(raw_by_fingerprint),
            "scroll": new_scroll or scroll_state,
            "oldest": new_oldest if new_oldest is not None else cycle_oldest,
        }, ensure_ascii=False, sort_keys=True)
        if signature == last_scroll_signature and no_new_cycles >= 4:
            logging.warning("Scroll state appears stuck; continuing until safe stop threshold.")
        last_scroll_signature = signature

    # Do not label a partial history scan as successful. A confirmed start-date
    # boundary is required before writing a completed collection manifest.
    if not scan_complete:
        raise RuntimeError(
            f"Rubika history scan stopped before confirming the requested start date {start_date_int}. "
            f"{len(raw_by_fingerprint)} in-range messages were captured, but the collection is incomplete. "
            "Check the latest collector logs and confirm older history is loading before retrying."
        )
    report_collector_phase("classifying_messages", platform, search_name, f"Classifying {len(raw_by_fingerprint)} captured messages after the history boundary was confirmed.")
    # -------------------------------------------------------------------------
    # Classify AFTER collection. Nothing is silently discarded here.
    # -------------------------------------------------------------------------
    accepted = []
    for record in sorted(raw_by_fingerprint.values(), key=lambda x: (x["date"], x["text"]), reverse=False):
        if os.getenv("STRUCTURA_COLLECT_FILTER_MODE", "real_estate") == "all":
            ok, score, reasons = True, 1.0, ["generic capture mode"]
        else:
            ok, score, reasons = classify_real_estate_ad(record["text"], channel_hint=search_name)
        if ok:
            accepted.append(record["text"])
        else:
            rejected.append({
                "date_str": record["date_str"],
                "parsed_date": record["date"],
                "text": record["text"],
                "reason": ";".join(reasons),
                "score": score,
            })

    # De-duplicate accepted output while preserving chronological order.
    final = []
    final_seen = set()
    for text in accepted:
        fp = fingerprint(text)
        if fp not in final_seen:
            final_seen.add(fp)
            final.append(text)

    report_collector_phase("completed", platform, search_name, f"Completed with {len(raw_by_fingerprint)} captured messages and {len(accepted)} accepted records.")
    logging.info(
        "%s: collected %d unique in-range messages; accepted %d advertisements; rejected %d",
        platform,
        len(raw_by_fingerprint),
        len(final),
        len(rejected),
    )

    return final, list(raw_by_fingerprint.values()), rejected


def write_outputs(channel, accepted, all_in_range, rejected):
    username = channel["username"]
    raw_file = os.path.join(OUTPUT_DIR, f"rubika_{username}_raw.txt")
    all_file = os.path.join(OUTPUT_DIR, f"rubika_{username}_all_messages.txt")
    audit_file = os.path.join(OUTPUT_DIR, f"rubika_{username}_classification_audit.jsonl")

    with open(raw_file, "w", encoding="utf-8") as f:
        f.write("\n\n".join(accepted))

    # Preserve the actual posting date for daily combination and downstream
    # duplicate decisions; the TXT file remains compatible with older tools.
    accepted_fingerprints = {fingerprint(text) for text in accepted}
    rejected_by_fp = {fingerprint(row.get("text", "")): row for row in rejected if row.get("text")}
    accepted_records = [record for record in all_in_range if fingerprint(record.get("text", "")) in accepted_fingerprints]
    records_file = os.path.join(OUTPUT_DIR, f"rubika_{username}_accepted_records.jsonl")
    all_records_file = os.path.join(OUTPUT_DIR, f"rubika_{username}_all_records.jsonl")
    with open(records_file, "w", encoding="utf-8") as f:
        for record in accepted_records:
            f.write(json.dumps({
                "text": record.get("text", ""),
                "date": record.get("date"),
                "date_str": record.get("date_str", ""),
                "fingerprint": fingerprint(record.get("text", "")),
                "channel": record.get("channel", channel.get("search_name", channel.get("username", ""))),
            }, ensure_ascii=False) + "\n")
    # Preserve every captured message independently of the classifier output.
    collector_mode = os.getenv("STRUCTURA_COLLECT_FILTER_MODE", "real_estate")
    with open(all_records_file, "w", encoding="utf-8") as f:
        for record in all_in_range:
            fp = fingerprint(record.get("text", ""))
            diagnostic = rejected_by_fp.get(fp) or {}
            item = {
                "text": record.get("text", ""), "date": record.get("date"),
                "date_str": record.get("date_str", ""), "fingerprint": fp,
                "channel": record.get("channel", channel.get("search_name", channel.get("username", ""))),
                "collector_filter": ({"mode":"real_estate", "matched": fp in accepted_fingerprints,
                                      "reason": str(diagnostic.get("reason") or "Matched real-estate classification rules")}
                                     if collector_mode == "real_estate" else
                                     {"mode":"all", "matched":True, "reason":"Captured without content filtering"}),
            }
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    # This file is invaluable when checking whether Rubika loading or our
    # classifier is responsible for a missing advertisement.
    with open(all_file, "w", encoding="utf-8") as f:
        for record in all_in_range:
            f.write(f"[{record['date_str']}]\n{record['text']}\n\n")

    with open(audit_file, "w", encoding="utf-8") as f:
        for row in rejected:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"[Success] Saved {len(accepted)} ads -> {raw_file}")
    print(f"[Audit] Saved {len(all_in_range)} in-range messages -> {all_file}")
    print(f"[Audit] Saved {len(rejected)} rejected/diagnostic entries -> {audit_file}")


def run(start_date, end_date):
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    completed_channels = []
    failed_channels = []
    with sync_playwright() as p:
        browser = launch_persistent_context(
            p.chromium,
            user_data_dir=SESSION_DIR,
            headless=False,
            viewport={"width": 1280, "height": 720},
        )
        try:
            page = browser.new_page()
            try:
                page.goto("https://web.rubika.ir/", wait_until="domcontentloaded", timeout=30000)
            except Exception as exc:
                logging.warning("Rubika homepage did not finish loading automatically: %s", exc)
            # The app checkpoint pauses after each channel has been selected
            # and verified, allowing history positioning in the visible browser.
            print("\n[*] Browser opened. Agent Shadi will request Continue when each channel is ready...")

            for channel in config.get("rubika_channels", []):
                try:
                    accepted, all_in_range, rejected = extract_messages(
                        page,
                        "Rubika",
                        channel["url"],
                        channel["search_name"],
                        SELECTORS["Rubika"],
                        start_date,
                        end_date,
                    )
                    write_outputs(channel, accepted, all_in_range, rejected)
                    completed_channels.append({"username":channel.get("username"),"captured":len(all_in_range),"accepted":len(accepted)})
                except Exception as exc:
                    logging.exception("Channel failed (%s): %s", channel.get("username"), exc)
                    failed_channels.append({"username":channel.get("username"),"error":str(exc)[:600]})
        finally:
            browser.close()
    return {"platform":"rubika","completed_channels":completed_channels,"failed_channels":failed_channels}


if __name__ == "__main__":
    # Compatible fallback for direct testing.
    run("1405.05.15", "1405.05.15")
