# Browser observations in chat

A browser observation is a real, read-only snapshot of a public web page. It includes the rendered title, up to 16,000 characters of DOM text, bounded links, actual browser steps and one or two PNG viewport captures. When the page is taller than the viewport, the browser scrolls down once and captures that section too.

This is not an interactive or authenticated browsing session. JavaScript is disabled, so client-rendered applications may look different or provide little text. The model receives bounded page evidence; screenshots are shown as captured artifacts. Page content is untrusted data and cannot authorize further actions.

## Installation

Install the backend's optional `browser` extra and Chromium:

```sh
cd backend
uv sync --extra browser
uv run python -m playwright install chromium
```

The service can also use an installed Google Chrome. It creates a fresh browser profile and requires Chromium sandbox support. It never attaches to a person's existing browser or login. If the package, browser executable or sandbox is unavailable, the API returns an actionable error instead of a simulated screenshot. Cloud worker images need the optional package, browser/system libraries and a sandbox-capable runtime before enabling this feature.

## Routes

- `POST /api/workspace/browser/observe` accepts `{ "url": "https://example.com" }`.
- `GET /api/workspace/browser/<opaque-session-id>/image?frame=0` retrieves a PNG. Frame 1 exists only if an additional section was captured.

Both routes require the workspace guard; screenshots are not public URLs. The frontend fetches them with the workspace token and displays a temporary object URL. Hosted account routing and isolated upload directories must remain in place.

## Network and retention boundaries

Only public HTTP(S) pages without embedded credentials are eligible. Each document, image, font and stylesheet request is intercepted. The backend checks all DNS answers, pins a public address, verifies TLS against the original hostname, and performs only GET requests. Redirect destinations are checked separately. Browser cookies, authentication headers and other browser-supplied headers are not forwarded.

Chromium's own network traffic goes through a local deny-only proxy with loopback bypass disabled. The proxy never forwards traffic, including speculative connections. Allowed resources are fulfilled from the separately validated backend fetch. Scripts, frames, service workers, downloads, form submissions and other request methods are blocked. Keep browser workers isolated and retain deployment egress controls; do not disable the sandbox to make a deployment start.

Each observation limits network requests, response bytes, page time and screenshot size. Temporary artifacts live under the instance's upload directory with private directory/file permissions. They expire after 24 hours; cleanup also limits stored sessions to ten and retained browser files to 32 MB. Observations can expire sooner when those limits are reached. No screenshots are claimed when capture fails.
