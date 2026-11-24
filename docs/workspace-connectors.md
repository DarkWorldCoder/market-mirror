# Remote MCP connections

The chat workspace can save remote Streamable HTTP MCP endpoints and discover their actual tool catalogs. Open **Connections → MCP servers**, choose a preset or enter your own public HTTPS endpoint, save its bearer token if needed, then check the connection. Saving alone makes no remote request and does not mark an account connected.

The Meta / Facebook Ads preset uses `https://mcp.facebook.com/ads`, documented in [Meta's setup guide](https://developers.facebook.com/documentation/ads-commerce/ads-ai-connectors/ads-mcp-server/ads-mcp-server-get-started). Meta supports user and employee-role system-user bearer tokens; its guide requires `ads_mcp_management` and `ads_read` or `ads_management`. The workspace uses bearer authentication, not a Facebook OAuth browser flow. Provider account eligibility and permissions still apply.

The Google Analytics preset links to [Google's official MCP setup](https://developers.google.com/analytics/devguides/MCP). It requires a user-deployed compatible HTTPS endpoint; no Google-hosted remote endpoint is assumed. CSV/JSON/PDF/text exports remain available through the existing chat attachment flow.

## Supported protocol and tools

This client supports Streamable HTTP versions `2025-11-25` and `2025-06-18`, with initialization, session headers, paginated `tools/list`, JSON and request-scoped SSE responses. It does not launch local stdio commands, complete OAuth, execute server-side sampling, or support endpoints requiring only newer protocol revisions. Use a compatible remote bridge where necessary.

Discovery reads at most three pages or 100 tools. A successful check stores a timestamp and catalog; it does not guarantee continued account access. A 401 or 403 response is shown as authentication required or account access denied. Other transport and protocol errors are displayed without echoing response bodies or credentials.

Chat execution requires all of the following:

- The connector is enabled by the user.
- The user has explicitly selected the tool in its allowlist.
- A fresh discovery still declares the tool's `readOnlyHint` as `true`.

Tools without that annotation, including unknown and write tools, cannot run through this client. A remote server's annotation is a declaration by that server, so only configure servers you trust. Tool schemas, descriptions and outputs remain external data. Calls are bounded to 16,000 characters of arguments and 20,000 characters of returned text. Provider billing, rate limits and access restrictions remain in effect.

## Configuration and transport

- `GET /api/workspace/connectors`: safe saved configuration and discovery status.
- `POST /api/workspace/connectors`: create `{name,url,token?,enabled?,allowed_tools?,protocol_version?}`.
- `PATCH /api/workspace/connectors/<id>`: update supported fields. Blank token retains the saved token; `clear_token: true` removes it.
- `DELETE /api/workspace/connectors/<id>`: remove configuration and its stored credential.
- `POST /api/workspace/connectors/<id>/discover`: contact the server and refresh its catalog.

These routes use the local workspace guard. Chat's backend uses the bounded `call_tool(id,name,arguments)` helper; there is no unrestricted HTTP proxy or public tool-call endpoint.

Configuration is saved atomically with owner-only permissions under the instance's upload directory in `workspace_connectors.json`. The bearer token is never returned in API responses and is redacted if the remote server echoes it. Keep the upload directory private and outside version control. Independent hosted workers must have separate upload directories and account-level routing; this module does not provide hosted authentication itself.

Only public HTTPS targets are supported. The transport validates all DNS answers, pins a validated public address while verifying the original hostname and TLS certificate, and refuses redirects. Local/private networks, URL-embedded credentials and URL query tokens are rejected. Response sizes and request times are bounded.

Protocol references: [MCP Streamable HTTP 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports) and [MCP tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools).
