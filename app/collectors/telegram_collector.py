import json
import os
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
try:
    from .browser_runtime import launch_persistent_context
except ImportError:  # collector_runner imports these modules from the collector directory
    from browser_runtime import launch_persistent_context

try:
    from .inspector_control import pause_in_inspector, report_collector_phase
except ImportError:  # collector_runner imports these modules from the collector directory
    from inspector_control import pause_in_inspector, report_collector_phase

try:
    from .telegram_auth import first_visible_selector, login_screen_state
except ImportError:  # collector_runner imports these modules from the collector directory
    from telegram_auth import first_visible_selector, login_screen_state

import emoji
import re
import jdatetime
import logging
import time
from urllib.parse import urlparse

CONFIG_PATH = 'config.json'
OUTPUT_DIR = "Collected_InputData_Extractions_Outputs"
SESSION_DIR = "./browser_session"

# ==============================================================================
# REQUIREMENT 3: Correct channel usernames & Config Handling
# ==============================================================================
if not os.path.exists(CONFIG_PATH):
    # No personal or customer channel identifiers are bundled in the product.
    # Configure channels in Structura Studio before starting a collection run.
    default_config = {
        "start_date": "1405.01.01",
        "end_date": "1405.01.01",
        "telegram_channels": [],
        "rubika_channels": [],
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(default_config, f, ensure_ascii=False, indent=4)

# ==============================================================================
# REQUIREMENT 7: DOM SELECTORS
# ==============================================================================
SELECTORS = {
    "Telegram": {
        "logged_in_indicator": "div.input-search, .sidebar-header",
        "login_screen_indicator": "button:has-text('Log in by QR Code'), .auth-form",

        # Telegram Web actual message structure
        "message_container": "#column-center .message, #column-center .bubble, #column-center [data-message-id], #column-center .message-list-item, .chat .message, .chat .bubble",
        "message_text": "span.translatable-message, .message-text, .text-content, .message-content",

        "message_date": ".i18n"
    },
    "Rubika": {
        "logged_in_indicator": "input.input-field, ul.chatlist, .chat-list",
        "login_screen_indicator": ".login-container, button:has-text('ورود')",
        "message_container": ".message-item, div[class*='message']",
        "message_text": ".message-text, .text-content",
        "message_date": ".message-time, .message-date"
    }
}
# ==============================================================================


# # ==============================================================================
# Persian normalization + high-recall classification
# ==============================================================================

ARABIC_TO_PERSIAN = str.maketrans({
    "ي": "ی",
    "ى": "ی",
    "ك": "ک",
    "ۀ": "ه",
    "ة": "ه",
    "ؤ": "و",
    "إ": "ا",
    "أ": "ا",
    "ٱ": "ا",
    "ـ": "",
})

PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def normalize_persian(text: str) -> str:
    """Normalize common Persian/Arabic Unicode and presentation differences."""
    if not text:
        return ""

    text = text.translate(ARABIC_TO_PERSIAN)
    text = text.translate(PERSIAN_DIGITS).translate(ARABIC_DIGITS)
    text = text.replace("\u200c", " ")
    text = text.replace("\u200f", "").replace("\u200e", "")
    text = text.replace("\u202a", "").replace("\u202b", "").replace("\u202c", "")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"#\s+", "#", text)
    return text


def normalize_for_fingerprint(text: str) -> str:
    text = normalize_persian(text).lower()
    return re.sub(r"[^\w\u0600-\u06ff]+", "", text, flags=re.UNICODE)


def fingerprint(text: str) -> str:
    import hashlib
    normalized = normalize_for_fingerprint(text)
    if not normalized:
        return ""
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


PROPERTY_TERMS = {
    "ویلایی", "ویلا", "آپارتمان", "اپارتمان", "زمین", "تجاری", "مغازه",
    "باغ", "سوله", "اداری", "سوئیت", "سویت", "اقامتی", "استیجاری",
    "ملک", "خانه", "منزل", "دفتر", "انباری",
}

RENT_TERMS = {
    "اجاره", "رهن", "رهن و اجاره", "رهن کامل", "قابل تبدیل",
    "تبدیل", "تخلیه", "مستاجر", "مستاجری", "استیجاری", "ماهانه",
}

PROPERTY_DETAIL_TERMS = {
    "متر", "متری", "متراژ", "زمین", "بنا", "خواب", "طبقه", "پارکینگ",
    "انباری", "آسانسور", "کابینت", "حیاط", "آدرس", "لوکیشن", "خیابان",
    "کوی", "بلوار", "ساخت", "سند", "گاز", "برق", "آب", "سرامیک", "پکیج",
}

PRICE_PATTERNS = [
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
    High-recall real-estate classifier.

    Collection and classification are deliberately separated so a message
    that fails classification is still retained in the all-message audit.
    """
    normalized = normalize_persian(text)
    if not normalized or len(normalized) < 15:
        return False, 0, ["too_short"]

    lowered = normalized.lower()
    words = compact_words(normalized)
    reasons = []
    score = 0

    nonempty_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(nonempty_lines) == 1 and any(
        re.fullmatch(pattern, nonempty_lines[0]) for pattern in NOISE_EXACT_PATTERNS
    ):
        return False, -10, ["ui_noise"]

    if any(phrase in lowered for phrase in NOISE_PHRASES):
        return False, -10, ["channel_noise"]

    property_hits = sorted(words.intersection(PROPERTY_TERMS))
    rent_hits = [term for term in RENT_TERMS if term in lowered]
    detail_hits = sorted(words.intersection(PROPERTY_DETAIL_TERMS))
    price_hits = [p for p in PRICE_PATTERNS if re.search(p, normalized, flags=re.IGNORECASE)]
    contact_hits = [p for p in CONTACT_PATTERNS if re.search(p, normalized)]

    hashtag_hits = re.findall(r"#[\w\u0600-\u06ff]+", normalized, flags=re.UNICODE)

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

    if hashtag_hits:
        score += 1
        reasons.append("hashtag")

    if (
        ("اجاره" in lowered or "رهن" in lowered)
        and ("متر" in lowered or "خواب" in lowered or "طبقه" in lowered)
    ):
        score += 2
        reasons.append("strong_rental_structure")

    is_rental_channel = any(
        k in normalize_persian(channel_hint)
        for k in ("اجاره", "استیجاری", "رهن")
    )
    threshold = 4 if is_rental_channel else 5

    accepted = score >= threshold
    if accepted:
        reasons.insert(0, f"accepted_score={score}")
    else:
        reasons.insert(0, f"rejected_score={score}_threshold={threshold}")

    return accepted, score, reasons


def is_valid_real_estate_ad(text, channel_hint=""):
    """Backwards-compatible wrapper for older imports."""
    return classify_real_estate_ad(text, channel_hint)[0]

def ensure_authenticated(page, platform, base_url, selectors):
    print(f"\n[*] Checking {platform} authentication state...", flush=True)
    page.goto(base_url)
    
    prompted = False
    attempt = 0
    
    while attempt < 240:
        attempt += 1
        print(f"    [{platform}] Polling auth state (Attempt {attempt})...", flush=True)
        
        logged_in_candidates = [item.strip() for item in selectors["logged_in_indicator"].split(",") if item.strip()]
        if first_visible_selector(page, logged_in_candidates, timeout_ms=500):
            print(f"[+] {platform}: Authenticated successfully (Session active).", flush=True)
            return

        login_candidates = [item.strip() for item in selectors["login_screen_indicator"].split(",") if item.strip()]
        if first_visible_selector(page, login_candidates, timeout_ms=500):
            if not prompted:
                print(f"[!] Waiting for {platform} login...", flush=True)
                print(f"    Please scan the QR code in the browser window.", flush=True)
                prompted = True
                
        page.wait_for_timeout(3000)

    raise RuntimeError(f"Timed out waiting for {platform} authentication after 12 minutes")


logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

def parse_chat_date(date_str, fallback_today_int=None):
    """
    Handles both Persian (Jalali) dates from Rubika and Gregorian/Relative dates from Telegram.
    Converts all valid dates to a Jalali integer (e.g., 14050512) for comparison.
    """
    if not date_str:
        logging.debug("Input date_str is empty. Returning None.")
        return None
        
    date_text = date_str.strip().lower()
    logging.debug(f"--- Parsing date string: '{date_text}' (Fallback Today: {fallback_today_int}) ---")

    # 1. Handle Relative Dates ('Today' / 'Yesterday')
    if "امروز" in date_text or "today" in date_text:
        logging.debug(f"Matched Today. Returning fallback: {fallback_today_int}")
        return fallback_today_int

    if "دیروز" in date_text or "yesterday" in date_text:
        if fallback_today_int:
            # Convert fallback integer back to jdatetime object to subtract 1 day safely
            str_val = str(fallback_today_int)
            y, m, d = int(str_val[:4]), int(str_val[4:6]), int(str_val[6:8])
            j_date = jdatetime.date(y, m, d) - timedelta(days=1)
            yesterday_int = int(f"{j_date.year}{j_date.month:02d}{j_date.day:02d}")
            logging.debug(f"Matched Yesterday. Derived Jalali date: {yesterday_int}")
            return yesterday_int
        return None

    # 2. Persian (Jalali) Date Check (Rubika / Persian UI Telegram)
    months_fa = {
        'فروردین': '01', 'اردیبهشت': '02', 'خرداد': '03', 
        'تیر': '04', 'مرداد': '05', 'شهریور': '06', 
        'مهر': '07', 'آبان': '08', 'آذر': '09', 
        'دی': '10', 'بهمن': '11', 'اسفند': '12'
    }
    
    parts = date_text.replace('،', '').split()
    try:
        for i, part in enumerate(parts):
            if part in months_fa:
                # Extract Day
                day = re.sub(r'\D', '', parts[i-1]).zfill(2) if i > 0 else "01"
                month = months_fa[part]
                
                # Extract Year if present, otherwise default to fallback year
                if i + 1 < len(parts) and parts[i+1].isdigit() and len(parts[i+1]) == 4:
                    year = parts[i+1]
                else:
                    year = str(fallback_today_int)[:4] if fallback_today_int else "1405"
                    
                result = int(f"{year}{month}{day}")
                logging.debug(f"Persian Success -> {result}")
                return result
    except Exception as e:
        logging.debug(f"Persian parse error: {e}")

    # 3. English (Gregorian) Date Check (Telegram Web)
    # Includes both full and abbreviated month names
    months_en_map = {
        "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
        "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
        "aug": 8, "august": 8, "sep": 9, "september": 9, "oct": 10, "october": 10,
        "nov": 11, "november": 11, "dec": 12, "december": 12
    }

    # Strip out time signatures if present (e.g. "Aug 12 at 14:30" -> "Aug 12")
    clean_date_str = re.sub(r'\s+at\s+\d{1,2}:\d{2}.*', '', date_text)
    clean_date_str = clean_date_str.replace(',', '').strip()

    try:
        # Match pattern for "12 Aug", "Aug 12", "12 Aug 2026", "Aug 12 2026"
        tokens = clean_date_str.split()
        day, month_num, year = None, None, None

        for token in tokens:
            if token in months_en_map:
                month_num = months_en_map[token]
            elif token.isdigit():
                val = int(token)
                if val > 31 and len(token) == 4:
                    year = val
                elif val <= 31 and day is None:
                    day = val

        if month_num and day:
            if not year:
                # Default to current Gregorian year
                year = datetime.now().year

            gregorian_dt = datetime(year, month_num, day)
            jalali_date = jdatetime.date.fromgregorian(date=gregorian_dt)
            result = int(f"{jalali_date.year}{jalali_date.month:02d}{jalali_date.day:02d}")
            logging.debug(f"Gregorian Success ({clean_date_str}) -> Converted to Jalali: {result}")
            return result

    except Exception as e:
        logging.debug(f"Gregorian parsing failed for '{date_str}': {e}")

    logging.debug(f"Failed to parse date string: '{date_str}'. Returning None.")
    return None

def get_telegram_scroll_state(page):
    """Find the scrollable ancestor that actually contains Telegram messages."""
    try:
        return page.evaluate("""() => {
          const messages=[...document.querySelectorAll('div.message')];
          const candidates=[...document.querySelectorAll('*')]
            .filter(el=>el.scrollHeight>el.clientHeight+20 && el.clientHeight>80 && el.getBoundingClientRect().width>0)
            .filter(el=>messages.some(msg=>el.contains(msg)));
          const best=candidates.sort((a,b)=>b.clientHeight-a.clientHeight)[0];
          if(!best)return null;
          const flexDirection=getComputedStyle(best).flexDirection;
          const minScrollTop=flexDirection==='column-reverse'?Math.min(0,best.clientHeight-best.scrollHeight):0;
          return {scrollTop:best.scrollTop,scrollHeight:best.scrollHeight,clientHeight:best.clientHeight,flexDirection,minScrollTop};
        }""")
    except Exception:
        return None


def scroll_up(page):
    """
    Move upward with enough overlap that virtualized Telegram messages are not
    skipped. Returns the scroll state before/after the move.
    """
    before = get_telegram_scroll_state(page)

    script = """
    () => {
        const messages=[...document.querySelectorAll('div.message')];
        const candidates=[...document.querySelectorAll('*')]
          .filter(el=>el.scrollHeight>el.clientHeight+20 && el.clientHeight>80 && el.getBoundingClientRect().width>0)
          .filter(el=>messages.some(msg=>el.contains(msg)));
        const container=candidates.sort((a,b)=>b.clientHeight-a.clientHeight)[0] || null;

        if (!container) {
            return {ok: false, reason: 'message_scroller_not_found'};
        }

        const step = Math.max(450, Math.min(
            1000,
            Math.floor(container.clientHeight * 0.85)
        ));

        const oldTop = container.scrollTop;
        const flexDirection=getComputedStyle(container).flexDirection;
        const minTop=flexDirection==='column-reverse'?Math.min(0,container.clientHeight-container.scrollHeight):0;
        container.scrollTop = Math.max(minTop, oldTop - step);
        container.dispatchEvent(new Event('scroll', {bubbles: true}));

        return {
            ok: true, oldTop, newTop: container.scrollTop, step,
            height: container.scrollHeight, minTop, flexDirection
        };
    }
    """

    try:
        result = page.evaluate(script)
    except Exception as exc:
        result = {"ok": False, "reason": "scroll_script_failed", "error": str(exc)[:300]}

    page.wait_for_timeout(350)
    after = get_telegram_scroll_state(page)

    return {
        "before": before,
        "after": after,
        "result": result,
    }


def telegram_history_start_reached(state):
    """Handle normal and column-reverse message lists without assuming scrollTop >= 0."""
    if not state:
        return False
    try:
        if state.get("flexDirection")=="column-reverse":
            return float(state.get("scrollTop",0)) <= float(state.get("minScrollTop",0)) + 5
        return float(state.get("scrollTop",0)) <= 5
    except (TypeError,ValueError):
        return False


def wait_for_telegram_progress(page, previous_state, previous_oldest, timeout_ms=12000):
    """
    Telegram may request older history asynchronously after reaching the top
    of the currently-rendered virtualized window. Poll both DOM state and dates.
    """
    deadline = page.evaluate("() => Date.now()") + timeout_ms
    last_state = previous_state

    while page.evaluate("() => Date.now()") < deadline:
        page.wait_for_timeout(500)

        state = get_telegram_scroll_state(page)
        oldest = get_oldest_visible_date(page)

        if oldest is not None and (
            previous_oldest is None or oldest < previous_oldest
        ):
            return True, state, oldest

        if (
            state is not None
            and last_state is not None
            and (
                state["scrollHeight"] != last_state["scrollHeight"]
                or state["scrollTop"] != last_state["scrollTop"]
            )
        ):
            return True, state, oldest

        last_state = state

    return False, get_telegram_scroll_state(page), get_oldest_visible_date(page)


def _extract_visible_telegram_messages(page, selectors):
    """
    Extract all currently rendered Telegram messages in DOM order.

    Date separators are tracked as we walk the DOM. Message text is extracted
    strictly from message-body elements; the full message container is never
    used as a text fallback.
    """
    js_extract = """
    (selectors) => {
        // Only actual date separators may modify the inherited date.
        // `.service-msg` includes system events such as pinned-message notices.
        const dateSelector = ".bubble.service.is-date, .is-date";
        const messageSelector = selectors.message_container;

        const dateNodes = Array.from(document.querySelectorAll(dateSelector));
        const candidates = Array.from(document.querySelectorAll(messageSelector));
        // Telegram's actual top-level post is `div.message`. Some UI builds
        // nest matching message elements for forwarded/reply content. Do not
        // promote those nested fragments to separate source messages.
        const messageNodes = candidates.filter((el) => {
            let parent = el.parentElement;
            while (parent && parent !== document.body) {
                if (parent.matches && parent.matches(messageSelector)) return false;
                parent = parent.parentElement;
            }
            return true;
        });
        const nodes = [...dateNodes, ...messageNodes].sort((a, b) => {
            const relation = a.compareDocumentPosition(b);
            return relation & Node.DOCUMENT_POSITION_FOLLOWING ? -1 :
                   relation & Node.DOCUMENT_POSITION_PRECEDING ? 1 : 0;
        });

        let currentDateStr = "";
        const results = [];

        for (const el of nodes) {
            if (
                el.matches(dateSelector) ||
                el.classList.contains("is-date")
            ) {
                const value = (el.innerText || "").trim();
                if (value) currentDateStr = value;
                continue;
            }

            // Telegram service/system messages are not advertisement messages
            // and must not affect date inheritance.
            if (el.classList.contains("service-msg")) continue;
            if (!el.matches(messageSelector)) continue;

            // STRICT BODY EXTRACTION:
            // never use the complete message container as a text fallback.
            const bodySelectors = [
                "span.translatable-message",
                ".translatable-message",
                ".text-content",
                ".message-text",
                ".message-content",
                ".content-inner",
                ".bubble-content",
                ".media-caption",
                "[data-message-text]",
                "[data-testid='message-text']",
                "[class*='message-text']",
                "[class*='translatable']"
            ];

            let body = null;
            for (const selector of bodySelectors) {
                const candidate = el.querySelector(selector);
                if (candidate && (candidate.innerText || "").trim()) {
                    body = candidate;
                    break;
                }
            }

            if (!body) continue;

            const clone = body.cloneNode(true);

            // Strip UI-only descendants. The message body should contain
            // advertisement content only, not sender/views/reactions/time.
            clone.querySelectorAll(
                "button, [role='button'], time, " +
                "[class*='reaction'], [class*='views'], [class*='view-count'], " +
                "[class*='sender'], [class*='author'], [class*='timestamp'], " +
                "[class*='time'], [class*='meta'], " +
                "[aria-label*='reaction'], [aria-label*='view'], " +
                "[aria-label*='واکنش'], [aria-label*='بازدید']"
            ).forEach(node => node.remove());

            clone.querySelectorAll(
                "img.emoji, img.emoji-image"
            ).forEach(img => {
                const alt = img.getAttribute("alt");
                if (alt) {
                    img.replaceWith(document.createTextNode(alt));
                } else {
                    img.remove();
                }
            });

            const text = (clone.innerText || "").trim();
            if (!text) continue;

            // Metadata is still collected separately for diagnostics only.
            const metadataNodes = [
                el.querySelector("time"),
                el.querySelector("[title]"),
                el.querySelector(".i18n"),
                el.querySelector("[aria-label]")
            ].filter(Boolean);

            const metadata = metadataNodes.map(node => ({
                text: (node.innerText || "").trim(),
                title: node.getAttribute("title") || "",
                aria: node.getAttribute("aria-label") || "",
                datetime: node.getAttribute("datetime") || ""
            }));

            results.push({
                text,
                date_str: currentDateStr,
                metadata
            });
        }

        return results;
    }
    """

    return page.evaluate(js_extract, selectors)


def get_oldest_visible_date(page):
    try:
        items = _extract_visible_telegram_messages(page, SELECTORS["Telegram"])
    except Exception:
        return None

    dates = []
    for item in items:
        parsed = parse_chat_date(
            item.get("date_str", ""),
            fallback_today_int=int(jdatetime.date.today().strftime("%Y%m%d")),
        )
        if parsed:
            dates.append(parsed)

    return min(dates) if dates else None


def _record_unparsed_date(rejected, item):
    text = (item.get("text") or "").strip()
    if not text:
        return

    rejected.append({
        "date_str": item.get("date_str", ""),
        "parsed_date": None,
        "text": text,
        "reason": "unparsed_date",
        "metadata": item.get("metadata", []),
    })


def _install_telegram_operator_click_watch(page):
    """Capture a real click on a Telegram search result before navigation completes."""
    return page.evaluate(r"""() => {
      window.__shadiTelegramSearchStartedAt = Date.now();
      window.__shadiTelegramSearchClick = null;
      if (window.__shadiTelegramSearchClickListenerInstalled) return true;
      window.__shadiTelegramSearchClickListenerInstalled = true;
      document.addEventListener('click', event => {
        const target = event.target && event.target.nodeType === 1 ? event.target : event.target?.parentElement;
        if (!target) return;
        const row = target.closest('.chatlist-chat[data-peer-id], .search-group-contacts .chatlist-chat, .search-group .chatlist-chat, .search-results .chatlist-chat, [class*="search"] [data-peer-id], [class*="search"] [role="option"], [class*="search"] [role="button"], .search-group-contacts li, .search-group-contacts a, .search-group-contacts .c-ripple');
        if (!row) return;
        const text = String(row.innerText || row.textContent || '').replace(/\s+/g, ' ').trim();
        window.__shadiTelegramSearchClick = {
          at: Date.now(), text: text.slice(0, 900),
          peerId: String(row.getAttribute('data-peer-id') || row.closest('[data-peer-id]')?.getAttribute('data-peer-id') || '')
        };
      }, true);
      return true;
    }""")


def _click_telegram_search_result(page, search_terms):
    """Click only a visible Telegram result whose text/identity matches the requested channel."""
    return page.evaluate(r"""(terms) => {
      const norm = value => String(value || '').normalize('NFKC').toLocaleLowerCase()
        .replace(/^@+/, '').replace(/[\s@_\-./]+/g, '').replace(/[^\p{L}\p{N}]/gu, '');
      const wanted = [...new Set((terms || []).map(norm).filter(x => x.length >= 3))];
      if (!wanted.length) return {clicked:false, reason:'empty_search_identity', candidates:[]};
      const visible = el => {
        if (!el || !el.getBoundingClientRect) return false;
        const r = el.getBoundingClientRect(), style = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
      };
      const selectors = [
        '.chatlist-chat[data-peer-id]', '.search-group-contacts .chatlist-chat', '.search-group-contacts .c-ripple',
        '.search-group-contacts [data-peer-id]', '.search-group-contacts [role="option"]',
        '.search-group-contacts [role="button"]', '.search-group-contacts li', '.search-group-contacts a',
        '.search-group .chatlist-chat', '.search-group [data-peer-id]', '.search-group [role="option"]',
        '.search-results .chatlist-chat', '.search-results [data-peer-id]',
        '[class*="search"] .chatlist-chat', '[class*="search"] [data-peer-id]',
        '[class*="search"] [role="option"]'
      ];
      const seen = new Set();
      const candidates = selectors.flatMap(selector => {
        try { return [...document.querySelectorAll(selector)]; } catch { return []; }
      }).filter(el => {
        if (seen.has(el) || !visible(el)) return false;
        seen.add(el);
        const text = String(el.innerText || el.textContent || '').trim();
        return text.length >= 2 && text.length <= 1200;
      });
      const scored = candidates.map(el => {
        const r = el.getBoundingClientRect();
        const attrs = [el.getAttribute('aria-label'), el.getAttribute('title'), el.getAttribute('data-username'),
          el.getAttribute('data-peer-id'), el.getAttribute('href'), el.closest('[data-peer-id]')?.getAttribute('data-peer-id')].filter(Boolean).join(' ');
        const raw = [String(el.innerText || el.textContent || ''), attrs].join(' ');
        const hay = norm(raw);
        let score = 0, matched = '';
        for (const term of wanted) {
          if (!hay.includes(term)) continue;
          const lineHit = String(el.innerText || el.textContent || '').split(/\n+/).some(line => norm(line) === term);
          const candidateScore = lineHit ? 120 : hay === term ? 115 : 90;
          if (candidateScore > score) { score = candidateScore; matched = term; }
        }
        return {el, score, matched, text:String(el.innerText || el.textContent || '').trim(), area:r.width*r.height};
      }).filter(x => x.score >= 90).sort((a,b) => b.score-a.score || a.text.length-b.text.length || a.area-b.area);
      if (!scored.length) return {clicked:false, reason:'no_matching_search_result', candidates:candidates.slice(0,10).map(el=>String(el.innerText||el.textContent||'').trim().slice(0,180))};
      const best = scored[0];
      let target = best.el.closest('button, a, [role="button"], .chatlist-chat, [data-peer-id], li, .c-ripple') || best.el;
      // Prefer the smallest clickable node that still contains the matching identity.
      const clickable = [...best.el.querySelectorAll('button, a, [role="button"], .c-ripple')].filter(visible)
        .find(el => wanted.some(term => norm([el.innerText,el.getAttribute('aria-label'),el.getAttribute('title')].join(' ')).includes(term)));
      if (clickable) target = clickable;
      const box=target.getBoundingClientRect();
      return {clicked:true, text:best.text.slice(0,900), matched:best.matched, score:best.score,
        peer_id:target.getAttribute('data-peer-id') || best.el.getAttribute('data-peer-id') || target.closest('[data-peer-id]')?.getAttribute('data-peer-id') || '',
        href:target.getAttribute('href') || best.el.getAttribute('href') || '',
        selector: target.matches('a.chatlist-chat[data-peer-id]') ? `a.chatlist-chat[data-peer-id="${target.getAttribute('data-peer-id')}"]` : '',
        click_x:Math.round(box.left+box.width/2), click_y:Math.round(box.top+box.height/2)};
    }""", search_terms)


def _activate_telegram_search_result(page, selection):
    """Activate an evidenced result using Playwright's real pointer sequence."""
    peer_id = str((selection or {}).get("peer_id") or "").strip()
    if peer_id and re.fullmatch(r"-?[A-Za-z0-9_-]{1,100}", peer_id):
        locator = page.locator(f'a.chatlist-chat[data-peer-id="{peer_id}"]').first
        try:
            if locator.count() and locator.is_visible():
                locator.click(timeout=7000)
                return {"method": "peer_id_locator", "peer_id": peer_id}
        except Exception as exc:
            logging.warning("Telegram exact peer-row click failed; trying observed coordinates: %s", str(exc)[:180])
    x, y = (selection or {}).get("click_x"), (selection or {}).get("click_y")
    if x is None or y is None:
        raise RuntimeError("A matching Telegram result was found, but it had no safe clickable locator or observed coordinates.")
    page.mouse.click(int(x), int(y))
    return {"method": "observed_coordinates", "peer_id": peer_id}


def _telegram_active_chat_state(page):
    """Return active Telegram header, message signature and any observed result click."""
    return page.evaluate(r"""() => {
      const visible = el => !!(el && el.getBoundingClientRect().width > 0 &&
        el.getBoundingClientRect().height > 0 && getComputedStyle(el).visibility !== 'hidden');
      // Scope title and peer-ID evidence to the active conversation pane.
      // Unscoped .peer-title nodes also occur in Telegram's result/sidebar rows
      // and can falsely make a search result look like an opened conversation.
      // Only dedicated title nodes in the active conversation pane. Broad
      // `[dir=auto]` and generic `.title` selectors can include stale search
      // rows or unrelated controls and must not certify channel identity.
      const titleSelectors = [
        '#column-center .chat-info .peer-title',
        '#column-center .chat-info-container .peer-title',
        '#column-center .topbar .peer-title',
        '#column-center header .peer-title',
        '#column-center [data-testid="chat-info"] .peer-title',
        '#column-center .chat-info .title',
        '#column-center .chat-info-container .title',
        '#column-center .topbar .title',
        '#column-center header h3'
      ];
      const titleDetails = titleSelectors.flatMap(selector => {
        try { return [...document.querySelectorAll(selector)]; } catch { return []; }
      }).filter(visible).map(el => ({
        selector: el.matches ? titleSelectors.find(s => { try { return el.matches(s); } catch { return false; } }) || '' : '',
        text:String(el.innerText || el.textContent || '').replace(/\s+/g,' ').trim().slice(0,180),
        peer_id:String(el.getAttribute('data-peer-id') || el.closest('[data-peer-id]')?.getAttribute('data-peer-id') || '')
      })).filter(x=>x.text).slice(0,16);
      const messageSelector = '#column-center .message, #column-center .bubble, #column-center [data-message-id], #column-center .message-list-item, .chat .message, .chat .bubble';
      const messages = [...document.querySelectorAll(messageSelector)].filter(visible)
        .filter(el => !el.closest('.chatlist, .sidebar, .search-results, [class*="sidebar"]'));
      const signature = messages.slice(-10).map(el => String(el.innerText || el.textContent || '')
        .replace(/\s+/g,' ').trim().slice(0,160)).filter(Boolean).join('\u241f');
      const activePeerIds = [...titleDetails.map(x=>x.peer_id), ...[...document.querySelectorAll('#column-center header [data-peer-id], #column-center .chat-info [data-peer-id], #column-center .topbar [data-peer-id], #column-center [data-testid*="chat-info"] [data-peer-id]')]
        .filter(visible).map(el=>String(el.getAttribute('data-peer-id')||''))].filter(Boolean);
      const click = window.__shadiTelegramSearchClick || null;
      return {
        title:titleDetails[0]?.text || '', titles:titleDetails.map(x=>x.text).slice(0,12),
        title_details:titleDetails, message_count:messages.length, signature, active_peer_ids:[...new Set(activePeerIds)],
        click:click && Number(click.at) >= Number(window.__shadiTelegramSearchStartedAt || 0) ? click : null,
        url:location.href
      };
    }""")


def _telegram_identity_evidence(clicked_result_text, title_candidates, expected_token,
                                active_peer_ids=None, expected_peer_id=""):
    """Compare configured identity, clicked result and the *active* chat.

    A username printed in the search result proves only that the result row
    matched the configuration. It does not prove that Telegram opened it.
    Active identity must be evidenced by a matching active title or peer ID.
    """
    text = str(clicked_result_text or '').strip()
    token = re.sub(r'[^a-z0-9_]+', '', str(expected_token or '').casefold().lstrip('@'))
    compact_row = re.sub(r'[^a-z0-9_]+', '', text.casefold().replace('@', ''))
    username_match = bool(token and token in compact_row)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    row_title = next((line for line in lines if not line.lstrip().startswith('@') and
                      re.sub(r'[^a-z0-9_]+', '', line.casefold()) != token), '')

    def key(value):
        return re.sub(r'[\W_]+', '', str(value or '').casefold(), flags=re.UNICODE)

    candidates = [str(value).strip() for value in (title_candidates or []) if str(value).strip()]
    header_match = next((title for title in candidates if row_title and key(title) and
                         (key(title) == key(row_title) or key(title) in key(row_title) or key(row_title) in key(title))), '')
    expected_peer_id = str(expected_peer_id or '').strip()
    observed_peer_ids = {str(value or '').strip() for value in (active_peer_ids or []) if str(value or '').strip()}
    peer_id_match = bool(expected_peer_id and expected_peer_id in observed_peer_ids)
    peer_id_conflict = bool(expected_peer_id and observed_peer_ids and not peer_id_match)
    return {
        "row_title": row_title,
        "matching_header": header_match,
        "username_match": username_match,
        "peer_id_match": peer_id_match,
        "peer_id_conflict": peer_id_conflict,
        "observed_peer_ids": sorted(observed_peer_ids),
        # This is deliberately about the active pane, never the result row.
        # A contradictory live peer ID overrides a coincidental title match.
        "evidence_match": bool(peer_id_match or (header_match and not peer_id_conflict)),
        "evidence_source": "peer_id" if peer_id_match else ("active_header" if header_match else "none"),
    }


def wait_for_manual_telegram_channel_selection(page, search_name, timeout_seconds=180, visible_candidates=None,
                                               automatic=False, clicked_result_text="", clicked_peer_id=""):
    """Wait until the clicked result is demonstrably the active Telegram chat.

    Existing message bubbles are not sufficient: they may belong to the chat
    that was open before the search result was clicked. The active header or
    active pane peer ID must match the selected result before readiness passes.
    """
    if not automatic:
        report_collector_phase(
            "operator_select_channel", "Telegram", search_name,
            "Telegram search results are visible, but the collector could not safely activate a matching result. Click the intended channel row in the open browser; do not close the browser."
        )
        logging.info("Telegram result selection needs an operator click; keeping the authenticated browser open.")
    deadline = time.monotonic() + max(1, int(timeout_seconds))
    previous_signature = None
    stable_rounds = 0
    last_state = {}
    last_evidence = {}
    expected_match = re.search(r'@([A-Za-z0-9_]{2,64})', str(search_name or ''))
    expected_token = expected_match.group(1) if expected_match else str(search_name or '').lstrip('@')
    while time.monotonic() < deadline:
        if getattr(page, "is_closed", lambda: False)():
            raise RuntimeError("The Telegram browser closed while waiting for you to select the channel result.")
        try:
            last_state = _telegram_active_chat_state(page)
        except Exception as exc:
            raise RuntimeError(f"Could not inspect Telegram after channel selection: {str(exc)[:220]}") from exc
        clicked = last_state.get("click") or ({"text": clicked_result_text, "peerId": clicked_peer_id} if automatic and clicked_result_text else {})
        click_text = str(clicked.get("text") or clicked_result_text or '').strip()
        observed_clicked_peer = str(clicked_peer_id or clicked.get("peerId") or "").strip()
        title = str(last_state.get("title") or '').strip()
        signature = str(last_state.get("signature") or '')
        messages = int(last_state.get("message_count") or 0)
        titles = [str(value).strip() for value in (last_state.get("titles") or []) if str(value).strip()]
        last_evidence = _telegram_identity_evidence(
            click_text, titles, expected_token,
            active_peer_ids=last_state.get("active_peer_ids") or [],
            expected_peer_id=observed_clicked_peer,
        )
        identity_confirmed = bool(last_evidence.get("evidence_match"))
        content_confirmed = messages > 0 and bool(signature)
        # A result-row click plus old/stale bubbles is not a selected channel.
        if clicked and title and identity_confirmed and content_confirmed:
            stability_key = signature + "|" + str(last_evidence.get("evidence_source"))
            if stability_key == previous_signature:
                stable_rounds += 1
            else:
                previous_signature = stability_key
                stable_rounds = 0
            if stable_rounds >= 2:
                active_title = title
                return {
                    "operator_selected": not automatic,
                    "text": click_text or active_title,
                    "clicked_result_text": click_text,
                    "active_title": active_title,
                    "active_title_candidates": titles,
                    "message_count": messages,
                    "active_peer_ids": last_state.get("active_peer_ids") or [],
                    "peer_confirmed": bool(last_evidence.get("peer_id_match")),
                    "peer_id": observed_clicked_peer,
                    "signature": signature,
                    "identity_evidence_match": True,
                    "identity_evidence_source": last_evidence.get("evidence_source"),
                    "identity_requires_operator_confirmation": not automatic,
                }
        else:
            previous_signature = None
            stable_rounds = 0
        page.wait_for_timeout(400)

    last_titles = (last_state or {}).get("titles", [])[:5]
    if last_state and (last_state.get("title") or last_state.get("message_count")) and not last_evidence.get("evidence_match"):
        raise RuntimeError(
            f"Telegram did not activate the configured channel. The selected search result was "
            f"'{str(clicked_result_text or (last_state.get('click') or {}).get('text') or '')[:140]}', "
            f"but the active chat header remained '{str(last_state.get('title') or '(not detected)')[:100]}'. "
            f"Active peer IDs: {(last_state.get('active_peer_ids') or [])[:5]}. "
            "The visible messages may belong to a previously open chat; no collection was attempted."
        )
    raise RuntimeError(
        f"Telegram did not reach a verified, stable chat after '{search_name}' was searched. "
        f"The collector waited {timeout_seconds}s for both matching active-chat identity and messages; "
        f"visible candidates: {(visible_candidates or [])[:5]}; last chat titles: {last_titles}."
    )


def verify_expected_channel(page, platform, channel_url, search_name, selected_result_text="",
                            expected_active_title="", allow_operator_selection=False,
                            expected_peer_id=""):
    """Fail closed unless the currently active pane still matches the target.

    The selected-result username is not active-chat evidence. A matching peer
    ID or a title match against the clicked row/configured title is required.
    """
    parsed = urlparse(channel_url)
    token_match = re.search(r"@([A-Za-z0-9_]{2,64})", channel_url)
    expected_token = token_match.group(1).casefold() if token_match else ""
    if not expected_token and (parsed.hostname or "").casefold() in {"t.me", "www.t.me"}:
        parts = [part for part in parsed.path.split("/") if part]
        if parts and parts[0].casefold() not in {"s", "c", "joinchat", "addstickers"}:
            expected_token = parts[0].lstrip("@").casefold()

    current_url = str(getattr(page, "url", "") or "").casefold()
    if platform.casefold() != "telegram":
        try:
            titles = page.evaluate("""() => {
                const selectors = ['.peer-title', '.chat-info .title', '.chat-info-container .title',
                  'header h3', 'header [dir=auto]', '.topbar .title', '[data-testid=chat-info]'];
                return selectors.flatMap(s => [...document.querySelectorAll(s)])
                  .filter(el => el.getBoundingClientRect().width > 0)
                  .map(el => (el.innerText || el.textContent || '').trim())
                  .filter(Boolean).slice(0, 12);
            }""") or []
        except Exception:
            titles = []
        expected = str(search_name or expected_token).strip().casefold()
        if expected and any(expected == str(title).strip().casefold() or expected in str(title).strip().casefold() for title in titles):
            return True
        selected_text = str(selected_result_text or "").casefold()
        if expected_token and re.search(rf"(?<![a-z0-9_])@?{re.escape(expected_token)}(?![a-z0-9_])", selected_text) and titles:
            return True
        if allow_operator_selection and titles:
            return True
        host = (urlparse(current_url).hostname or "").casefold()
        expected_host = (parsed.hostname or "").casefold()
        if expected_host and host != expected_host:
            raise RuntimeError(f"Inspector resumed on {host or 'an unknown page'}, not the configured {platform} site {expected_host}. Select the configured channel and resume again.")
        raise RuntimeError(
            f"Cannot verify the active {platform} channel. Expected '{search_name}'; visible chat titles: {titles[:5]}. "
            "No messages were collected. Reopen the configured channel before resuming."
        )

    try:
        state = _telegram_active_chat_state(page)
    except Exception as exc:
        raise RuntimeError(f"Cannot inspect the active {platform} chat identity: {str(exc)[:200]}") from exc
    # Compatibility with older test doubles and inspector adapters that expose
    # only a list of visible titles rather than the richer state object.
    if isinstance(state, list):
        state = {"title": str(state[0] if state else ""), "titles": state, "active_peer_ids": []}
    if not isinstance(state, dict):
        state = {"title": "", "titles": [], "active_peer_ids": []}
    titles = [str(value).strip() for value in (state.get("titles") or []) if str(value).strip()]
    active_title = str(state.get("title") or "").strip()
    expected_peer_id = str(expected_peer_id or "").strip()
    observed_peer_ids = [str(value or "").strip() for value in (state.get("active_peer_ids") or []) if str(value or "").strip()]
    peer_match = bool(expected_peer_id and expected_peer_id in observed_peer_ids)
    peer_conflict = bool(expected_peer_id and observed_peer_ids and not peer_match)

    if platform.casefold() == "telegram":
        if peer_match:
            return True
        if peer_conflict:
            raise RuntimeError(
                f"The active Telegram peer changed after selection. Expected peer ID '{expected_peer_id}', "
                f"but the active pane reports {observed_peer_ids[:5]}. No messages were collected."
            )
        clicked_title = _telegram_identity_evidence(
            selected_result_text, titles, expected_token,
            active_peer_ids=observed_peer_ids,
            expected_peer_id=expected_peer_id,
        ).get("row_title")
        expected_titles = [value for value in (expected_active_title, clicked_title, search_name) if value and not str(value).strip().startswith("@")]
        def title_matches(candidate, value):
            left = re.sub(r"[\W_]+", "", str(candidate or "").casefold(), flags=re.UNICODE)
            right = re.sub(r"[\W_]+", "", str(value or "").casefold(), flags=re.UNICODE)
            return bool(left and right and (left == right or left in right or right in left))
        title_match = next((title for title in titles if any(title_matches(title, expected) for expected in expected_titles)), "")
        if title_match:
            return True
        if expected_active_title and active_title:
            raise RuntimeError(
                f"The active Telegram chat changed after selection. Expected '{expected_active_title[:100]}', "
                f"but the active header is '{active_title[:100]}'. No messages were collected."
            )
        if not active_title and not titles:
            raise RuntimeError(
                f"Cannot verify the active Telegram channel '{search_name}': no dedicated active-chat header "
                f"or peer ID was detected. No messages were collected."
            )
        raise RuntimeError(
            f"The active Telegram chat does not match the configured channel '{search_name}'. "
            f"Selected result: '{str(selected_result_text or '(unavailable)')[:140]}'. "
            f"Expected title: '{str(expected_active_title or clicked_title or '(not detected)')[:100]}'. "
            f"Actual active header: '{active_title or '(not detected)'}'; visible headers: {titles[:5]}; "
            f"expected peer ID: '{expected_peer_id or '(unavailable)'}'; active peer IDs: {observed_peer_ids[:5]}. "
            "No messages were collected. Do not press Continue on a mismatched chat; reopen the correct result."
        )



def wait_for_telegram_channel_ready(page, platform, channel_url, search_name, selectors, timeout_ms=18000,
                                    selected_result_text="", expected_active_title="",
                                    allow_operator_selection=False, expected_peer_id=""):
    """Wait for a stable, visible message list and fail closed on real login/loading screens."""
    if page.is_closed():
        raise RuntimeError("The browser tab was closed before collection started.")
    verify_expected_channel(page, platform, channel_url, search_name, selected_result_text,
                             expected_active_title, allow_operator_selection, expected_peer_id)
    deadline=page.evaluate("() => Date.now()")+timeout_ms
    stable_count=None; stable_rounds=0; last_signature=None; last_state={}
    while page.evaluate("() => Date.now()")<deadline:
        if page.is_closed():
            raise RuntimeError("The browser tab was closed while the channel was loading.")
        login_state = login_screen_state(page, platform, selectors)
        if login_state["visible"]:
            try:
                page_url = str(page.url)
                page_title = str(page.title())
            except Exception:
                page_url, page_title = "", ""
            raise RuntimeError(
                f"{platform} displayed an actual sign-in view while opening '{search_name}' "
                f"(matched {login_state['evidence']}; URL={page_url!r}; title={page_title!r}). "
                "Log in again, reopen the channel, and restart collection."
            )
        try:
            state=page.evaluate(r"""selector => {
              const visible=el=>!!(el && el.getBoundingClientRect().width>0 && el.getBoundingClientRect().height>0);
              const messages=[...document.querySelectorAll(selector)].filter(visible);
              const busy=[...document.querySelectorAll('[aria-busy=true], [role=progressbar], .loading, .loader, .spinner')].some(visible);
              const signature=messages.slice(-8).map(el=>String(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim().slice(0,120)).join('\u241f');
              return {message_count:messages.length,signature,busy,ready_state:document.readyState,title:document.title};
            }""", selectors.get("message_container", "div.message"))
        except Exception as exc:
            raise RuntimeError(f"Could not inspect {platform} channel readiness: {str(exc)[:240]}") from exc
        last_state=state
        count=int(state.get("message_count") or 0)
        signature=str(state.get("signature") or "")
        if count>0 and signature and not state.get("busy"):
            if count==stable_count and signature==last_signature: stable_rounds+=1
            else: stable_count=count; last_signature=signature; stable_rounds=0
            if stable_rounds>=3:
                return state
        else:
            stable_count=None; last_signature=None; stable_rounds=0
        page.wait_for_timeout(500)
    raise RuntimeError(f"{platform} channel '{search_name}' did not reach a stable message-list state within {timeout_ms//1000}s. No scrolling was attempted. Last browser state: {last_state}")


def extract_messages(page, platform, url, search_name, selectors, start_date_str, end_date_str):
    """
    High-recall Telegram collector.

    Important design:
        CAPTURE -> NORMALIZE/FINGERPRINT -> CLASSIFY -> OUTPUT/AUDIT

    We collect while moving upward through history. There is no second
    down-scroll pass, so the virtualized message window cannot silently lose
    items between a "find date" pass and a "collect date" pass.
    """
    print(f"\n[{platform}] Opening channel: {search_name}")

    # Telegram channel URLs such as t.me/<username> are public preview routes,
    # not the authenticated application. Always enter Telegram Web first,
    # verify/sign in there, then locate the channel through the in-app search.
    base_url = "https://web.telegram.org/k/" if platform == "Telegram" else url.split("#")[0]
    report_collector_phase("opening_site", platform, search_name, "Opening the authenticated application entry point and checking its sign-in state.")
    ensure_authenticated(page, platform, base_url, selectors)
    page.goto(base_url, wait_until="domcontentloaded")
    page.wait_for_timeout(1800)

    start_date_int = int(start_date_str.replace(".", ""))
    end_date_int = int(end_date_str.replace(".", ""))

    # -------------------------------------------------------------
    # Open channel
    # -------------------------------------------------------------
    username = str(search_name or "").lstrip("@")
    try:
        # Strict manual-selection mode: Shadi never searches for, clicks, or
        # opens a channel. The operator navigates to the intended chat.
        report_collector_phase(
            "operator_select_channel", platform, search_name,
            "Select the intended Telegram channel manually in the open browser. Shadi will not search for or open channels."
        )
        _install_telegram_operator_click_watch(page)
        selection = wait_for_manual_telegram_channel_selection(
            page, search_name,
            timeout_seconds=int(os.environ.get("STRUCTURA_TELEGRAM_MANUAL_SELECT_TIMEOUT", "300")),
        )
        selected_result_text = str(selection.get("clicked_result_text") or selection.get("text") or "")
        expected_active_title = str(selection.get("active_title") or "")
        identity_requires_operator_confirmation = True
        identity_evidence_match = bool(selection.get("identity_evidence_match", False))
        allow_operator_selection = True
        verify_expected_channel(
            page, platform, url, search_name, selected_result_text,
            expected_active_title=expected_active_title,
            allow_operator_selection=True,
            expected_peer_id=str(selection.get("peer_id") or ""),
        )
        report_collector_phase(
            "checking_message_list", platform, search_name,
            "The manually selected Telegram chat is open; verifying its active identity and message list."
        )
        readiness = wait_for_telegram_channel_ready(
            page, platform, url, search_name, selectors,
            selected_result_text=selected_result_text,
            expected_active_title=expected_active_title,
            allow_operator_selection=True,
            expected_peer_id=str(selection.get("peer_id") or ""),
        )
        report_collector_phase(
            "channel_opened", platform, search_name,
            f"Manually selected chat detected. Header='{expected_active_title[:70]}'; {readiness.get('message_count', 0)} visible messages. Operator confirmation is required."
        )
        pause_in_inspector(
            page, platform, search_name, end_date_str,
            active_title=expected_active_title,
            selected_result_text=selected_result_text,
            identity_requires_operator_confirmation=True,
            identity_evidence_match=identity_evidence_match,
            operator_instruction=(
                f"MANUAL TELEGRAM CHANNEL CHECK: configured @{username}. "
                f"Active chat header='{expected_active_title[:100] or '(not detected)'}'. "
                "Confirm this is the intended channel, position history near the requested end date, then Continue."
            ),
        )
        verify_expected_channel(
            page, platform, url, search_name, selected_result_text,
            expected_active_title=expected_active_title,
            allow_operator_selection=True,
            expected_peer_id=str(selection.get("peer_id") or ""),
        )
        readiness = wait_for_telegram_channel_ready(
            page, platform, url, search_name, selectors,
            selected_result_text=selected_result_text,
            expected_active_title=expected_active_title,
            allow_operator_selection=True,
            expected_peer_id=str(selection.get("peer_id") or ""),
        )
        print(f"[{platform}] Continue received; manually selected chat verified and message list stable ({readiness.get('message_count')} visible). Beginning history scan from the visible position.", flush=True)

    except Exception as exc:
        logging.exception("[%s] Manual channel selection failed: %s", platform, exc)
        raise RuntimeError(
            f"Could not verify manually selected {platform} channel '{search_name}': {str(exc)[:520]}"
        ) from exc
    print(f"[{platform}] Channel opened. Starting one-pass high-recall history scan.")

    # Confirm the real body extractor can see messages before any history
    # scrolling. A stable message-container count alone is insufficient.
    try:
        preflight_items = _extract_visible_telegram_messages(page, selectors)
    except Exception as exc:
        raise RuntimeError(f"Telegram message extraction preflight failed before scrolling: {str(exc)[:260]}") from exc
    if not preflight_items:
        diagnostic = page.evaluate(r"""() => {
          const roots = [...document.querySelectorAll('#column-center .message, #column-center .bubble, #column-center [data-message-id], #column-center .message-list-item')]
            .filter(el => { const r=el.getBoundingClientRect(); return r.width>0 && r.height>0; });
          return {
            activeTitle: (document.querySelector('#column-center .topbar .peer-title, #column-center .chat-info .peer-title, #column-center header .peer-title')?.innerText || '').trim().slice(0,120),
            visibleMessageRoots: roots.length,
            samples: roots.slice(0,4).map(el => ({tag:el.tagName, classes:String(el.className||'').toString().slice(0,220), text:String(el.innerText||el.textContent||'').trim().slice(0,180), descendants:[...el.querySelectorAll('[class]')].slice(0,12).map(n=>String(n.className||'').toString().slice(0,100))}))
          };
        }""")
        raise RuntimeError(
            "Telegram's message list appeared ready, but the message-body extractor found zero messages. "
            "Collection stopped before scrolling; history cannot be marked complete. "
            f"DOM diagnostics: {json.dumps(diagnostic, ensure_ascii=False)[:1800]}"
        )

    raw_by_fingerprint = {}
    rejected = []

    max_cycles = 700
    no_progress_cycles = 0
    oldest_seen = None
    reached_start_boundary = False
    boundary_confirmation_cycles = 0
    scan_complete = False
    last_state_signature = None

    fallback_today = int(jdatetime.date.today().strftime("%Y%m%d"))

    for cycle in range(1, max_cycles + 1):
        if cycle == 1 or cycle % 5 == 0:
            report_collector_phase("scanning_history", platform, search_name, f"History scan cycle {cycle}; {len(raw_by_fingerprint)} unique in-range messages captured.")
        # Re-check the active route before each scan block. A page navigation,
        # expired session or accidental channel switch must stop before capture.
        verify_expected_channel(
            page, platform, url, search_name, selected_result_text,
            expected_active_title, allow_operator_selection,
            expected_peer_id=str(selection.get("peer_id") or ""),
        )
        try:
            items = _extract_visible_telegram_messages(page, selectors)
        except Exception as exc:
            logging.exception("[%s] Message extraction failed at cycle %d: %s", platform, cycle, exc)
            rejected.append({
                "reason": "dom_extraction_failed",
                "cycle": cycle,
                "error": str(exc),
            })
            items = []

        before_count = len(raw_by_fingerprint)
        cycle_oldest = None
        cycle_newest = None

        for item in items:
            text = (item.get("text") or "").strip()
            date_str = (item.get("date_str") or "").strip()

            parsed_date = parse_chat_date(
                date_str,
                fallback_today_int=fallback_today,
            )

            if parsed_date is None:
                _record_unparsed_date(rejected, item)
                continue

            cycle_oldest = (
                parsed_date
                if cycle_oldest is None
                else min(cycle_oldest, parsed_date)
            )
            cycle_newest = (
                parsed_date
                if cycle_newest is None
                else max(cycle_newest, parsed_date)
            )

            if oldest_seen is None or parsed_date < oldest_seen:
                oldest_seen = parsed_date

            # Never throw away newer messages before the range. We simply don't
            # put them into the in-range capture set.
            if parsed_date < start_date_int:
                reached_start_boundary = True
                continue

            if parsed_date > end_date_int:
                continue

            if len(text) < 5:
                # Preserve it in audit rather than silently losing it.
                rejected.append({
                    "date_str": date_str,
                    "parsed_date": parsed_date,
                    "text": text,
                    "reason": "too_short_for_candidate",
                })
                continue

            normalized_text = normalize_persian(text)
            fp = fingerprint(normalized_text)

            if not fp:
                rejected.append({
                    "date_str": date_str,
                    "parsed_date": parsed_date,
                    "text": text,
                    "reason": "empty_fingerprint",
                })
                continue

            # Capture stage: first sighting wins; classification is deferred.
            if fp not in raw_by_fingerprint:
                raw_by_fingerprint[fp] = {
                    "text": text,
                    "normalized_text": normalized_text,
                    "date": parsed_date,
                    "date_str": date_str,
                    "fingerprint": fp,
                    "channel": search_name,
                }

        if cycle == 1 and cycle_newest is not None and cycle_newest < start_date_int:
            raise RuntimeError(
                f"The visible Telegram history is already older than the requested start date ({cycle_newest} < {start_date_int}). "
                "No scrolling or collection was attempted. Return to this channel and position at the requested end date before resuming."
            )

        new_count = len(raw_by_fingerprint) - before_count

        # Progress means either new unique target-range messages OR deeper
        # visible history.
        state = get_telegram_scroll_state(page)
        state_signature = json.dumps(
            {
                "count": len(raw_by_fingerprint),
                "oldest": cycle_oldest,
                "scroll": state,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

        if new_count == 0 and state_signature == last_state_signature:
            no_progress_cycles += 1
        else:
            no_progress_cycles = 0

        last_state_signature = state_signature

        logging.info(
            "%s cycle %d: visible=%d, unique_in_range=%d, new=%d, "
            "oldest=%s, newest=%s, no_progress=%d",
            platform,
            cycle,
            len(items),
            len(raw_by_fingerprint),
            new_count,
            cycle_oldest,
            cycle_newest,
            no_progress_cycles,
        )

        # We have passed into the day before the target. Because collection was
        # continuous while scrolling upward, the target interval is complete.
        if cycle_oldest is not None and cycle_oldest < start_date_int and new_count == 0:
            boundary_confirmation_cycles += 1
        else:
            boundary_confirmation_cycles = 0
        if reached_start_boundary and boundary_confirmation_cycles >= 3:
            scan_complete = True
            report_collector_phase("history_boundary_confirmed", platform, search_name, f"Requested start boundary {start_date_int} confirmed across three stable scans.")
            print(
                f"[{platform}] Confirmed history beyond the start date "
                f"({oldest_seen} < {start_date_int}) across three stable scans. Scan complete."
            )
            break

        # If Telegram is truly stuck and has not changed after several cycles,
        # attempt additional gentle scrolls before declaring failure.
        if no_progress_cycles >= 10:
            logging.warning(
                "[%s] No observable progress for %d cycles; stopping with "
                "audit evidence instead of silently dropping data.",
                platform,
                no_progress_cycles,
            )
            rejected.append({
                "reason": "collector_stalled",
                "cycle": cycle,
                "oldest_seen": oldest_seen,
                "unique_in_range": len(raw_by_fingerprint),
            })
            break

        report_collector_phase("loading_older_history", platform, search_name, f"Loading older Telegram history after scan cycle {cycle}.")
        before_state = get_telegram_scroll_state(page)
        scroll_result = scroll_up(page)

        after_state = get_telegram_scroll_state(page)
        if not (scroll_result.get("result") or {}).get("ok"):
            detail=(scroll_result.get("result") or {}).get("reason","unknown")
            rejected.append({"reason":"message_scroller_not_found","cycle":cycle,"detail":detail})
            raise RuntimeError(f"Could not identify Telegram's message-history scroller ({detail}). Collection stopped; no unrelated pane or page scrolling was attempted.")

        # If we have reached the current rendered top, explicitly wait for
        # Telegram to request older history.
        if (
            after_state is not None
            and telegram_history_start_reached(after_state)
        ):
            loaded, _, new_oldest = wait_for_telegram_progress(
                page,
                after_state,
                cycle_oldest,
                timeout_ms=12000,
            )

            if loaded:
                continue

            # Final boundary check after the loading wait.
            final_oldest = get_oldest_visible_date(page)
            if final_oldest is not None and final_oldest < start_date_int:
                reached_start_boundary = True
                continue

        # Small overlap wait for normal virtualized rendering.
        page.wait_for_timeout(
            850 if new_count else 1200
        )

    else:
        logging.warning(
            "[%s] Maximum history cycles (%d) reached before the start-date "
            "boundary was observed.",
            platform,
            max_cycles,
        )
        rejected.append({
            "reason": "max_cycles_reached",
            "max_cycles": max_cycles,
            "oldest_seen": oldest_seen,
            "unique_in_range": len(raw_by_fingerprint),
        })

    # A partial scan must not be reported as successful. We only mark complete
    # after observing and confirming the requested start-date boundary.
    if not scan_complete:
        raise RuntimeError(
            f"Telegram history scan stopped before confirming the requested start date {start_date_int}. "
            f"{len(raw_by_fingerprint)} in-range messages were captured, but the collection is incomplete. "
            "Check the latest collector logs, return to the configured channel and resume only after older history is visible."
        )
    report_collector_phase("classifying_messages", platform, search_name, f"Classifying {len(raw_by_fingerprint)} captured messages after the history boundary was confirmed.")
    # -------------------------------------------------------------
    # Classification stage — ONLY AFTER capture is complete.
    # -------------------------------------------------------------
    accepted_records = []

    for record in sorted(
        raw_by_fingerprint.values(),
        key=lambda row: (row["date"], row["text"]),
    ):
        if os.getenv("STRUCTURA_COLLECT_FILTER_MODE", "real_estate") == "all":
            ok, score, reasons = True, 1.0, ["generic capture mode"]
        else:
            ok, score, reasons = classify_real_estate_ad(
                record["text"],
                channel_hint=search_name,
            )

        if ok:
            accepted_records.append(record)
        else:
            rejected.append({
                "date_str": record["date_str"],
                "parsed_date": record["date"],
                "text": record["text"],
                "fingerprint": record["fingerprint"],
                "reason": ";".join(reasons),
                "score": score,
            })

    # Accepted output is kept de-duplicated by fingerprint.
    accepted = []
    accepted_seen = set()

    for record in accepted_records:
        fp = record["fingerprint"]
        if fp not in accepted_seen:
            accepted_seen.add(fp)
            accepted.append(record["text"])

    all_in_range = sorted(
        raw_by_fingerprint.values(),
        key=lambda row: (row["date"], row["text"]),
    )

    logging.info(
        "%s final: captured=%d, accepted=%d, rejected/audit=%d",
        platform,
        len(all_in_range),
        len(accepted),
        len(rejected),
    )

    return accepted, all_in_range, rejected


def write_outputs(channel, accepted, all_in_range, rejected):
    username = channel["username"]

    raw_file = os.path.join(
        OUTPUT_DIR,
        f"telegram_{username}_raw.txt",
    )
    all_file = os.path.join(
        OUTPUT_DIR,
        f"telegram_{username}_all_messages.txt",
    )
    audit_file = os.path.join(
        OUTPUT_DIR,
        f"telegram_{username}_classification_audit.jsonl",
    )

    with open(raw_file, "w", encoding="utf-8") as f:
        f.write("\n\n".join(accepted))

    # Keep each accepted ad linked to its actual Jalali posting date. The
    # plain TXT file remains for compatibility with the original workflow.
    accepted_fingerprints = {fingerprint(text) for text in accepted}
    rejected_by_fp = {str(row.get("fingerprint") or fingerprint(row.get("text", ""))): row for row in rejected if row.get("text")}
    accepted_records = [record for record in all_in_range if record.get("fingerprint") in accepted_fingerprints]
    records_file = os.path.join(OUTPUT_DIR, f"telegram_{username}_accepted_records.jsonl")
    all_records_file = os.path.join(OUTPUT_DIR, f"telegram_{username}_all_records.jsonl")
    with open(records_file, "w", encoding="utf-8") as f:
        for record in accepted_records:
            f.write(json.dumps({
                "text": record.get("text", ""),
                "date": record.get("date"),
                "date_str": record.get("date_str", ""),
                "fingerprint": record.get("fingerprint", ""),
                "channel": record.get("channel", channel.get("search_name", channel.get("username", ""))),
            }, ensure_ascii=False) + "\n")
    # Complete, exact-boundary sidecar: it includes classifier rejects too.
    # Structura applies its configurable workflow policy after acquisition.
    collector_mode = os.getenv("STRUCTURA_COLLECT_FILTER_MODE", "real_estate")
    with open(all_records_file, "w", encoding="utf-8") as f:
        for record in all_in_range:
            fp = str(record.get("fingerprint") or fingerprint(record.get("text", "")))
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

    with open(all_file, "w", encoding="utf-8") as f:
        for record in all_in_range:
            f.write(
                f"[{record['date_str']}]\n"
                f"{record['text']}\n\n"
            )

    with open(audit_file, "w", encoding="utf-8") as f:
        for row in rejected:
            f.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                ) + "\n"
            )

    print(f"[Success] Saved {len(accepted)} ads -> {raw_file}")
    print(f"[Audit] Saved {len(all_in_range)} in-range messages -> {all_file}")
    print(f"[Audit] Saved {len(rejected)} audit entries -> {audit_file}")

# def run():
#     with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
#         config = json.load(f)

#     with sync_playwright() as p:
#         browser = p.chromium.launch_persistent_context(
#             user_data_dir=SESSION_DIR,
#             headless=False,
#             viewport={"width": 1280, "height": 720}
#         )
#         page = browser.new_page()

#         ensure_authenticated(page, "Telegram", "https://web.telegram.org/k/", SELECTORS["Telegram"])
#         print("\n[*] Telegram Authenticated. Starting raw data collection...")
        
#         for channel in config.get("telegram_channels", []):
#             messages = extract_messages(
#                 page,
#                 "Telegram",
#                 channel["url"],
#                 channel["search_name"],
#                 SELECTORS["Telegram"],
#                 config.get("start_date"),
#                 config.get("end_date")
#             )

#             if messages:
#                 output_file = os.path.join(
#                     OUTPUT_DIR,
#                     f"telegram_{channel['username']}_raw.txt"
#                 )
#                 with open(output_file, "w", encoding="utf-8") as f:
#                     f.write("\n\n".join(messages))
#                 print(f"[Success] Saved {len(messages)} raw messages to {output_file}")

#         browser.close()

# if __name__ == "__main__":
#     run()

def run(start_date, end_date):
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
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
                page.goto("https://web.telegram.org/k/", wait_until="domcontentloaded", timeout=30000)
            except Exception as exc:
                logging.warning("Telegram homepage did not finish loading automatically: %s", exc)
            # The app checkpoint pauses after each channel is verified, allowing the operator
            # to position history in the visible browser before continuing.
            print("\n[*] Browser opened. The app will request confirmation after each channel is ready...")

            for channel in config.get("telegram_channels", []):
                try:
                    accepted, all_in_range, rejected = extract_messages(
                        page,
                        "Telegram",
                        channel["url"],
                        channel["search_name"],
                        SELECTORS["Telegram"],
                        start_date,
                        end_date,
                    )

                    write_outputs(
                        channel,
                        accepted,
                        all_in_range,
                        rejected,
                    )
                    completed_channels.append({"username":channel.get("username"),"captured":len(all_in_range),"accepted":len(accepted)})

                except Exception as exc:
                    logging.exception(
                        "Telegram channel failed (%s): %s",
                        channel.get("username"),
                        exc,
                    )
                    failed_channels.append({"username":channel.get("username"),"error":str(exc)[:600]})

        finally:
            browser.close()
    return {"platform":"telegram","completed_channels":completed_channels,"failed_channels":failed_channels}

if __name__ == "__main__":
    # Fallback for testing the script directly without the launcher
    run("1405.05.15", "1405.05.15")