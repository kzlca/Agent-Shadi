"""Narrow authentication-state detection for browser collectors."""


def first_visible_selector(page, candidates, timeout_ms=150):
    """Return the first individually visible selector; avoid union-selector .first pitfalls."""
    for selector in candidates:
        try:
            if page.locator(selector).first.is_visible(timeout=timeout_ms):
                return selector
        except Exception:
            continue
    return ""


def login_screen_state(page, platform, selectors):
    """Detect actual login UI without mistaking Telegram's ordinary canvas for QR login."""
    if str(platform).casefold() == "telegram":
        # Telegram Web uses canvas for more than QR login (stickers/media and other UI).
        # A bare canvas is not authentication evidence. Require an explicit login
        # control/form and ensure the authenticated chat shell is not still visible.
        login_evidence = first_visible_selector(page, (
            "button:has-text('Log in by QR Code')",
            "button:has-text('Log in by phone Number')",
            ".auth-form",
            ".auth-form canvas",
        ))
        if not login_evidence:
            return {"visible": False, "evidence": "", "app_shell_visible": False}
        app_shell_visible = bool(first_visible_selector(page, (
            "div.input-search",
            ".sidebar-header",
        )))
        return {
            "visible": not app_shell_visible,
            "evidence": login_evidence,
            "app_shell_visible": app_shell_visible,
        }

    login_selector = selectors.get("login_screen_indicator", "")
    login_visible = bool(login_selector and first_visible_selector(page, (login_selector,)))
    return {
        "visible": login_visible,
        "evidence": login_selector if login_visible else "",
        "app_shell_visible": False,
    }
