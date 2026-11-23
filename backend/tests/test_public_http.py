"""All public evidence fetches pin checked public addresses and validate redirects."""
import socket
from types import SimpleNamespace

import pytest

from app.utils import public_http as public
from app.services import product_profile, cro_and_sparring, research
from app import create_app


@pytest.mark.parametrize("url", ["http://127.0.0.1/admin", "http://169.254.169.254/latest/meta-data", "http://10.0.0.1", "http://[::1]", "http://224.0.0.1", "http://[fec0::1]", "file:///etc/passwd", "https://user:secret@example.com", "http://public.example\\@127.0.0.1"])
def test_private_or_ambiguous_urls_never_connect(monkeypatch, url):
    monkeypatch.setattr(public.urllib3, "HTTPConnectionPool", lambda *a, **k: pytest.fail("must not connect"))
    monkeypatch.setattr(public.urllib3, "HTTPSConnectionPool", lambda *a, **k: pytest.fail("must not connect"))
    with pytest.raises(public.PublicFetchError):
        public.get_public(url)


def response(status=200, headers=None, body=b"public content"):
    packets = [body, b""]
    return SimpleNamespace(status=status, headers=headers or {"Content-Type": "text/html"},
                           read1=lambda *args, **kwargs: packets.pop(0), close=lambda: None)


def test_public_address_is_pinned_with_tls_sni_not_re_resolved(monkeypatch):
    dns, calls = [], []
    def resolve(host, port, **kwargs):
        dns.append(host)
        return [(None, None, None, None, ("93.184.216.34", port))]
    monkeypatch.setattr(public.socket, "getaddrinfo", resolve)
    class Pool:
        def __init__(self, address, **kwargs):
            assert address == "93.184.216.34"
            assert kwargs["server_hostname"] == kwargs["assert_hostname"] == "public.example"
            assert kwargs["cert_reqs"] == "CERT_REQUIRED"
        def urlopen(self, method, path, **kwargs):
            calls.append((method, path, kwargs))
            return response()
        def close(self):
            pass
    monkeypatch.setattr(public.urllib3, "HTTPSConnectionPool", Pool)
    result = public.get_public("https://public.example/page", params={"q": "real source"})
    assert result["body"] == b"public content"
    assert dns == ["public.example"]
    assert calls[0][0:2] == ("GET", "/page?q=real+source")
    assert calls[0][2]["redirect"] is False
    assert set(calls[0][2]["headers"]) == {"Host", "User-Agent", "Accept"}


def test_redirect_to_private_is_rejected_before_second_connection(monkeypatch):
    monkeypatch.setattr(public.socket, "getaddrinfo", lambda host, port, **kw: [(None, None, None, None, ("93.184.216.34", port))])
    connections = []
    class Pool:
        def __init__(self, address, **kwargs):
            connections.append(address)
        def urlopen(self, *args, **kwargs):
            return response(302, {"Location": "http://169.254.169.254/credentials"})
        def close(self):
            pass
    monkeypatch.setattr(public.urllib3, "HTTPSConnectionPool", Pool)
    monkeypatch.setattr(public.urllib3, "HTTPConnectionPool", lambda *a, **k: pytest.fail("private redirect must not connect"))
    with pytest.raises(public.PublicFetchError, match="Private"):
        public.get_public("https://public.example")
    assert connections == ["93.184.216.34"]


def test_all_dns_answers_must_be_public(monkeypatch):
    monkeypatch.setattr(public.socket, "getaddrinfo", lambda host, port, **kw: [(None, None, None, None, (address, port)) for address in ("93.184.216.34", "127.0.0.1")])
    monkeypatch.setattr(public.urllib3, "HTTPSConnectionPool", lambda *a, **k: pytest.fail("mixed DNS answers must not connect"))
    with pytest.raises(public.PublicFetchError):
        public.get_public("https://public-looking.example")


@pytest.mark.parametrize("fetch", [product_profile.fetch_url_text, cro_and_sparring.fetch_url_snapshot, research._get])
def test_legacy_fetches_all_reject_metadata_before_network(monkeypatch, fetch):
    monkeypatch.setattr(public.urllib3, "HTTPConnectionPool", lambda *a, **k: pytest.fail("must not connect"))
    with pytest.raises(public.PublicFetchError):
        fetch("http://169.254.169.254/latest/meta-data")


def test_product_api_surfaces_policy_error_before_model_call(monkeypatch):
    from app.api import product
    monkeypatch.setattr(product, "_client", lambda: pytest.fail("private page must not call model"))
    client = create_app().test_client()
    response = client.post("/api/graph/profile", json={"url": "http://169.254.169.254/latest/meta-data"})
    assert response.status_code == 400
    assert "Private" in response.json["error"]


def test_size_limit_and_public_http_errors_are_explicit(monkeypatch):
    monkeypatch.setattr(public.socket, "getaddrinfo", lambda host, port, **kw: [(None, None, None, None, ("93.184.216.34", port))])
    status = [200]
    class Pool:
        def __init__(self, *args, **kwargs):
            pass
        def urlopen(self, *args, **kwargs):
            return response(status[0], body=b"x" * 11)
        def close(self):
            pass
    monkeypatch.setattr(public.urllib3, "HTTPSConnectionPool", Pool)
    with pytest.raises(public.PublicFetchError, match="size"):
        public.get_public("https://public.example", max_bytes=10)
    status[0] = 403
    with pytest.raises(public.PublicFetchError, match="HTTP 403"):
        public.get_public("https://public.example")
