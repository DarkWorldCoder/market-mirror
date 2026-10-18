# Security

MarketMirror runs locally with your own model key. Please report vulnerabilities privately through GitHub's "Report a vulnerability" on this repository rather than a public issue; we aim to answer within a week.

Notes for operators:
- The backend has no authentication and binds to localhost by default. Put it behind your own auth or network rules before exposing it.
- `.env` holds your key; it is gitignored and the tools never print it.
- `research` fetches public pages; treat fetched text as data, not instructions. The report prompt only sees the compact fact sheet.
- The no-key gateway runs the `claude` / `codex` CLIs on your behalf; it listens on 127.0.0.1 only.
