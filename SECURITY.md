# Security Policy

## Supported version

Security fixes are developed against the latest published release. Please update to the latest version before reporting an issue where possible.

## Reporting a vulnerability

Please do not publish credentials, browser-session files, private source content, or an exploitable vulnerability in a public issue. Use GitHub's **Report a vulnerability** feature on the repository's Security tab when it is enabled. Include a concise impact description, affected version, reproduction steps, and a safe proof of concept.

## Data and credential handling

- Application databases and browser profiles are stored locally. Browser profiles may contain authenticated session material.
- The current application does not encrypt model credentials at rest inside its local SQLite database. Use operating-system account protections and full-disk encryption; do not share database files or backups casually.
- Do not attach `data/`, `config.json`, browser profiles, exported records, or unredacted diagnostic bundles to public issues.
- When a remote model endpoint is configured, selected source content may be sent to that endpoint for extraction or connector assistance.
- The supplied launch scripts bind the local service to `127.0.0.1`. Do not expose the development server to an untrusted network.

## Responsible use

Only use Agent Shadi to access and process sources you are authorized to use. Respect privacy obligations, service terms, access controls, and rate limits.
