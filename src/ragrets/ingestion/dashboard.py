"""Explicit, consented dashboard retrieval; never bypasses access controls."""
import requests


def fetch_configured_dashboard(url: str, headers: dict[str, str] | None = None) -> dict:
    if not url:
        raise ValueError("A configured dashboard URL is required")
    response = requests.get(url, headers=headers or {}, timeout=20)
    response.raise_for_status()
    return {"url": url, "content_type": response.headers.get("content-type"), "body": response.text}


def playwright_notice() -> str:
    return "Playwright may be used only for an explicitly configured JavaScript dashboard after interactive authentication; OTPs, CAPTCHAs, and access controls are never bypassed."
