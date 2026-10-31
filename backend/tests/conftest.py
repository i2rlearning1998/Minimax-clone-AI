"""All provider tests must inject transports; never contact a live provider."""
import httpx
import pytest


@pytest.fixture(autouse=True)
def forbid_external_http(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('External network blocked in tests; inject MockTransport')
    async def async_blocked(*args, **kwargs):
        blocked()
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', async_blocked)
