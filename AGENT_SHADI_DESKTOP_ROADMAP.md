# Agent Shadi — Desktop Distribution Roadmap

## Current distribution (1.8.37)

Agent Shadi is currently a local-first Python application with a browser-based interface served by FastAPI. The supplied launch scripts support Linux, macOS, and Windows where Python and a compatible Chromium-based browser are available. The service binds to `127.0.0.1:8765` when started through the provided scripts.

This is source distribution, not a compiled or signed native desktop installer. The project directory name `Structura_Flow/` used by older installations and the `STRUCTURA_FLOW_DATA` environment variable are retained internally to avoid breaking existing databases, browser profiles, archives, or exports.

## Target desktop architecture

```text
Native desktop shell (Tauri 2 / Rust)
        |
        +-- Web UI (current frontend, migrated when justified)
        |
        +-- Python sidecar (FastAPI + existing Agent Shadi engine)
                |
                +-- Collectors / Playwright / extraction / validation
                +-- SQLite / local archives / workflow assets
```

Keep collection, extraction, policies, and data-quality logic in Python initially. The desktop shell should own window lifecycle, desktop menus, file dialogs, notifications, deep links, and update installation. Use a narrow, versioned local IPC contract between the shell and Python sidecar; keep the sidecar bound to loopback or a private local socket.

## Packaging sequence

1. Separate UI from server lifecycle with a supervisor that starts the Python sidecar, waits for `/health`, records its PID, and shuts it down cleanly.
2. Package the Python sidecar with a reproducible build process. Keep user data, browser profiles, settings, and logs outside the application bundle.
3. Add a desktop shell with explicit sidecar permissions; do not permit arbitrary shell execution from the frontend.
4. Evaluate operating-system credential storage for model credentials and migrate existing settings with recovery tests.
5. Build each platform on its own CI runner rather than assuming cross-compilation works for native dependencies.
6. Sign Windows installers and sign/notarize macOS distributions where certificates and infrastructure are available.
7. Test install, upgrade, rollback, browser detection, Unicode paths, shutdown/restart, model connectivity, and data migration on clean systems.

## Potential release artifacts

| Platform | Possible artifact |
|---|---|
| Windows | Signed `.msi` or installer `.exe` |
| macOS | Signed/notarized `.dmg` containing an `.app` |
| Linux | AppImage, `.deb`, or `.rpm` where practical |

## Release requirements

- Upgrades must not overwrite `data/`, browser profiles, user databases, or exports.
- Uninstall must not delete user data without an explicit confirmation and backup path.
- Each release must include version metadata, checksums, and a rollback strategy.
- Raw credentials must not be exposed to the frontend without a clear need.
- The local service must not be exposed to the LAN by default.
- A release must not be described as a native desktop installer until the produced artifacts have been tested on their target platforms.
