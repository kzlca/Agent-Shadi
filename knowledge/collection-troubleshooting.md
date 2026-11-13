# Collection troubleshooting

## Diagnostic order

1. Inspect saved connector configuration and its workflow ID.
2. Check browser inspector status, configured session persistence, profile path and presence of cookie, local-storage, IndexedDB, session-storage or service-worker storage; never read or reveal cookie values.
3. Check exact current URL (remove secrets/query tokens from any model-visible context) and whether the user is authenticated and the intended channel/conversation is open.
4. Validate root selector count and text/timestamp coverage on the live page.
5. Verify channel identity separately from page URL.
6. Inspect navigation strategy and evidence of progress (URL, page cursor, root signature, oldest/newest timestamp, scrollTop or message count).
7. Inspect capture result counts and persistence in the inbox database.
8. If messages are present but records are absent, inspect queue status and run extraction; do not re-run collection unnecessarily.

## Common symptoms

- Browser ready but no channel opened: URL only located the app. Need channel name and a verified search/open action.
- Search result ambiguous: do not click arbitrary result. Ask the user to choose or configure exact result evidence.
- Root count zero: likely wrong page, wrong channel, virtualized/unloaded messages or stale selector.
- Text coverage low: root is not the message wrapper or text selector is wrong.
- Timestamps empty: check selector scope and attribute (`datetime`, `data-time`, etc.).
- Inspector Alt+click does nothing: do not insist on the keyboard modifier. Turn on the in-page Click select toolbar or use right-click → Select this element / Select nearest repeated item. Use DevTools Copy outerHTML as a fallback.
- Login is requested every launch: confirm the same connector/workflow is being opened, session persistence is enabled, and the same profile path has saved site-data metadata. Close the browser normally once after signing in. If data exists but login is still lost, the site may expire/revoke sessions or bind them to device/IP; do not claim storage is missing.
- Scroll command sent but no progress: inspect selected scroll container, step ratio/fixed pixels, direction, adaptive wait budget, DOM mutations and per-cycle message growth. No-change cycles consume the full wait and increase the next adaptive budget up to its cap; reduce the step if a virtualized list skips items, or raise max wait for slow platforms. Stop after bounded idle cycles.
- Capture says added=0: inspect found/root_count, duplicates, date filtering, undated count, policy-held count and DB inbox counts. Do not equate zero added with no source messages.
- Duplicate channel names or an already-open channel is not resolved: inspect saved target URL, username/handle and platform ID. Check the current URL and active-header identity before searching. A sidebar search result is not the active conversation. Configure a stable ID or active identity selector when available; only fall back to a display name if exactly one result matches.
- Messages queued but records=0: extraction has not run, or it failed; inspect extraction status and errors.
- Messages filtered: collection policy held them; they remain source messages and can be reviewed/requeued.

## Recovery

Use one change at a time, save it, revalidate against real page evidence, and run a small test. Never change multiple selectors or navigation controls simultaneously without a test that isolates the effect. Stop on repeated no-progress rather than looping indefinitely.
