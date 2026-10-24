import requests
import pytest

from ragrets import attachment_download


class FakeResponse:
    def __init__(self, status_code=200, headers=None, chunks=()):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("HTTP failure")

    def iter_content(self, chunk_size):
        yield from self._chunks

    def close(self):
        self.closed = True


def test_download_pdf_from_allowlisted_https_host(monkeypatch):
    monkeypatch.setenv("RAGRETS_ATTACHMENT_ALLOWED_HOSTS", "files.example.test")
    payload = b"%PDF-1.7\nexample PDF"
    response = FakeResponse(
        headers={"Content-Length": str(len(payload))},
        chunks=[payload[:8], payload[8:]],
    )
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return response

    monkeypatch.setattr(attachment_download.requests, "get", fake_get)

    assert attachment_download.download_pdf_bytes(
        "https://files.example.test/bill.pdf"
    ) == payload
    assert captured["allow_redirects"] is False
    assert captured["timeout"] == attachment_download.DOWNLOAD_TIMEOUT
    assert response.closed


@pytest.mark.parametrize(
    "url",
    [
        "http://res.cloudinary.com/bill.pdf",
        "https://example.com/bill.pdf",
        "https://127.0.0.1/bill.pdf",
        "https://user:password@res.cloudinary.com/bill.pdf",
    ],
)
def test_rejects_unsafe_or_unapproved_urls_before_network(url, monkeypatch):
    monkeypatch.delenv("RAGRETS_ATTACHMENT_ALLOWED_HOSTS", raising=False)

    def should_not_be_called(*args, **kwargs):
        pytest.fail("Network request should not be made for an unsafe URL.")

    monkeypatch.setattr(attachment_download.requests, "get", should_not_be_called)

    with pytest.raises(ValueError):
        attachment_download.download_pdf_bytes(url)


def test_rejects_redirect_to_unapproved_host(monkeypatch):
    monkeypatch.setenv("RAGRETS_ATTACHMENT_ALLOWED_HOSTS", "files.example.test")
    response = FakeResponse(
        status_code=302,
        headers={"Location": "http://127.0.0.1/private"},
    )
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return response

    monkeypatch.setattr(attachment_download.requests, "get", fake_get)

    with pytest.raises(ValueError, match="HTTPS"):
        attachment_download.download_pdf_bytes(
            "https://files.example.test/redirect"
        )
    assert len(calls) == 1
    assert response.closed


def test_rejects_pdf_over_size_limit_from_content_length(monkeypatch):
    monkeypatch.setenv("RAGRETS_ATTACHMENT_ALLOWED_HOSTS", "files.example.test")
    monkeypatch.setattr(attachment_download, "MAX_ATTACHMENT_BYTES", 8)
    response = FakeResponse(
        headers={"Content-Length": "9"},
        chunks=[],
    )
    monkeypatch.setattr(
        attachment_download.requests,
        "get",
        lambda *args, **kwargs: response,
    )

    with pytest.raises(ValueError, match="attachment limit"):
        attachment_download.download_pdf_bytes(
            "https://files.example.test/large.pdf"
        )
    assert response.closed


def test_rejects_non_pdf_payload(monkeypatch):
    monkeypatch.setenv("RAGRETS_ATTACHMENT_ALLOWED_HOSTS", "files.example.test")
    response = FakeResponse(chunks=[b"this is not a PDF"])
    monkeypatch.setattr(
        attachment_download.requests,
        "get",
        lambda *args, **kwargs: response,
    )

    with pytest.raises(ValueError, match="not a recognizable PDF"):
        attachment_download.download_pdf_bytes(
            "https://files.example.test/not-a-pdf"
        )
    assert response.closed
