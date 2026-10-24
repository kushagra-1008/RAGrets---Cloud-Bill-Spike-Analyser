"""Safe HTTP(S) downloader for user-supplied Agentverse PDF attachments."""

import ipaddress
import os
from urllib.parse import urljoin, urlparse

import requests

DEFAULT_ALLOWED_HOSTS = {"res.cloudinary.com"}
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_REDIRECTS = 3
DOWNLOAD_TIMEOUT = (5, 20)


def _allowed_hosts() -> set[str]:
    configured = os.getenv("RAGRETS_ATTACHMENT_ALLOWED_HOSTS", "").strip()
    if not configured:
        return DEFAULT_ALLOWED_HOSTS.copy()
    return {
        host.strip().lower().rstrip(".")
        for host in configured.split(",")
        if host.strip()
    }


def _validate_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise ValueError("The attachment does not contain a download URL.")

    parsed = urlparse(url.strip())
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("For safety, attachments must use an HTTPS download URL.")
    if parsed.username or parsed.password:
        raise ValueError("Attachment URLs containing credentials are not accepted.")
    if parsed.port not in (None, 443):
        raise ValueError("Attachment URLs using a non-standard port are not accepted.")

    hostname = parsed.hostname.lower().rstrip(".")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ValueError("Attachment URLs using IP addresses are not accepted.")

    allowed = _allowed_hosts()
    if not any(hostname == host or hostname.endswith("." + host) for host in allowed):
        raise ValueError(
            "The attachment host is not allowed. Add its trusted HTTPS domain to "
            "RAGRETS_ATTACHMENT_ALLOWED_HOSTS if this is an expected file host."
        )
    return url.strip()


def download_pdf_bytes(url: str) -> bytes:
    """Download a PDF from an allowlisted HTTPS host with size and redirect limits."""
    current_url = _validate_url(url)

    for redirect_count in range(MAX_REDIRECTS + 1):
        response = None
        try:
            response = requests.get(
                current_url,
                headers={"User-Agent": "RAGrets/0.2 PDF attachment loader"},
                stream=True,
                timeout=DOWNLOAD_TIMEOUT,
                allow_redirects=False,
            )

            if response.status_code in {301, 302, 303, 307, 308}:
                if redirect_count >= MAX_REDIRECTS:
                    raise ValueError("The attachment URL redirected too many times.")
                location = response.headers.get("Location")
                if not location:
                    raise ValueError("The attachment server returned an invalid redirect.")
                current_url = _validate_url(urljoin(current_url, location))
                continue

            response.raise_for_status()
            declared_size = response.headers.get("Content-Length")
            if declared_size:
                try:
                    if int(declared_size) > MAX_ATTACHMENT_BYTES:
                        raise ValueError("The PDF exceeds the 20 MB attachment limit.")
                except ValueError as exc:
                    if "20 MB" in str(exc):
                        raise
                    # Ignore malformed Content-Length values; actual bytes are bounded below.

            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_ATTACHMENT_BYTES:
                    raise ValueError("The PDF exceeds the 20 MB attachment limit.")
                chunks.append(chunk)

            payload = b"".join(chunks)
            if b"%PDF-" not in payload[:1024]:
                raise ValueError("The attachment is not a recognizable PDF file.")
            return payload

        except requests.RequestException as exc:
            raise ValueError(
                "The PDF could not be downloaded (network or HTTP error)."
            ) from exc
        finally:
            if response is not None:
                response.close()

    raise ValueError("The attachment URL could not be downloaded.")
