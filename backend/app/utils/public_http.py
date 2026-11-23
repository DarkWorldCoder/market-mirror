"""Bounded credential-free public GETs with DNS-address pinning and checked redirects."""
import ipaddress
import math
import socket
import time
from urllib.parse import quote, urlencode, urljoin, urlsplit, urlunsplit

import urllib3


class PublicFetchError(ValueError):
    pass


def is_public_address(value):
    address = ipaddress.ip_address(value)
    return (address.is_global and not address.is_multicast and not address.is_reserved
            and not getattr(address, "is_site_local", False) and not getattr(address, "sixtofour", None)
            and not getattr(address, "teredo", None))


def resolve_public(url):
    if not isinstance(url, str) or not 1 <= len(url) <= 8192 or "\\" in url or any(ord(c) < 32 or ord(c) == 127 for c in url):
        raise PublicFetchError("Use a valid public HTTP or HTTPS URL")
    try:
        parsed = urlsplit(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise PublicFetchError("Use a public HTTP or HTTPS URL without credentials")
        try:
            literal = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            literal = None
        if literal is not None and not is_public_address(str(literal)):
            raise PublicFetchError("Private, local and reserved page destinations are not allowed")
        host = parsed.hostname.encode("idna").decode("ascii")
        addresses = {row[4][0] for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    except (OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, PublicFetchError):
            raise
        raise PublicFetchError("The public page hostname could not be resolved") from None
    if not addresses or any(not is_public_address(address) for address in addresses):
        raise PublicFetchError("Private, local and reserved page destinations are not allowed")
    return parsed, host, port, sorted(addresses)[0]


def get_public(url, *, timeout=8, max_bytes=400000, params=None, user_agent="MarketMirror-Public-Research/1.0", accept="text/html,application/json;q=0.9,*/*;q=0.5"):
    """Return {url,status,headers,body}. No ambient proxy, cookies, auth or unchecked redirect."""
    if params:
        parts = urlsplit(url)
        url = urlunsplit(parts._replace(query=parts.query + ("&" if parts.query else "") + urlencode(params, doseq=True)))
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise PublicFetchError("Invalid public fetch time limit")
    if type(max_bytes) is not int or not 1 <= max_bytes <= 2 * 1024 * 1024:
        raise PublicFetchError("Invalid public fetch size limit")
    deadline = time.monotonic() + timeout
    for redirects in range(5):
        parsed, hostname, port, address = resolve_public(url)
        left = deadline - time.monotonic()
        if left <= 0:
            raise PublicFetchError("Public page fetch timed out")
        options = {"port": port, "timeout": urllib3.Timeout(connect=min(3, left), read=min(3, left)), "retries": False}
        pool = urllib3.HTTPSConnectionPool(address, server_hostname=hostname, assert_hostname=hostname,
                                          cert_reqs="CERT_REQUIRED", **options) if parsed.scheme == "https" else urllib3.HTTPConnectionPool(address, **options)
        response = None
        try:
            path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
            if parsed.query:
                path += "?" + quote(parsed.query, safe="%=&?/:@!$'()*+,;[]-._~")
            host_header = (f"[{hostname}]" if ":" in hostname else hostname) + (f":{port}" if parsed.port else "")
            response = pool.urlopen("GET", path, headers={"Host": host_header, "User-Agent": user_agent, "Accept": accept},
                                    redirect=False, preload_content=False)
            if response.status in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location or redirects >= 4:
                    raise PublicFetchError("Public page redirected too many times or omitted its destination")
                url = urljoin(url, location)
                # The next iteration re-resolves, validates and pins the new target before any connection.
                continue
            if not 200 <= response.status < 300:
                raise PublicFetchError(f"Public page returned HTTP {response.status}")
            body = bytearray()
            while len(body) <= max_bytes:
                if time.monotonic() >= deadline:
                    raise PublicFetchError("Public page fetch timed out")
                chunk = response.read1(min(8192, max_bytes + 1 - len(body)), decode_content=True)
                if not chunk:
                    break
                body.extend(chunk)
            if len(body) > max_bytes:
                raise PublicFetchError("Public page exceeds its response size limit")
            return {"url": url, "status": response.status,
                    "headers": {"content-type": response.headers.get("Content-Type", "")}, "body": bytes(body)}
        except PublicFetchError:
            raise
        except Exception:
            raise PublicFetchError("Public page could not be retrieved securely") from None
        finally:
            if response is not None:
                response.close()
            pool.close()
    raise PublicFetchError("Public page redirect limit reached")
