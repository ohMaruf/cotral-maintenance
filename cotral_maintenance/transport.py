"""HTTP plumbing shared by the API clients: retries, and errors that never contain the API key."""

import json

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .errors import ApiError, TransportError

RETRY_HTTP_STATUSES = (429, 500, 502, 503, 504)
MAX_RETRIES = 3
RETRY_BACKOFF_S = 0.5
ERROR_BODY_CHARS = 300


def build_session(referrer: str | None = None) -> requests.Session:
    """Session with retries. `referrer` is sent on every request, for keys restricted
    to specific websites (HTTP-referrer restriction)."""
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=RETRY_BACKOFF_S,
        status_forcelist=RETRY_HTTP_STATUSES,
        # Every endpoint we call is read-only, so POST (Places search) is safe to retry too.
        allowed_methods=frozenset({"GET", "POST"}),
    )
    session = requests.Session()
    if referrer:
        session.headers["Referer"] = referrer
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def send(
    session: requests.Session, method: str, url: str, timeout_s: float, **kwargs
) -> requests.Response:
    try:
        response = session.request(method, url, timeout=timeout_s, **kwargs)
    except requests.RequestException as exc:
        # `from None`: the original exception's message contains the URL, and so the key.
        raise TransportError(f"{method} {url} failed: {type(exc).__name__}") from None
    if not response.ok:
        raise ApiError(f"HTTP_{response.status_code}", google_error(response.text))
    return response


def google_error(body: str) -> str:
    """A Google API error body on one line: message, status, and the details' reasons and metadata (the API, the
    project, the key restriction that refused it), which say what to fix. Other bodies: cut to ERROR_BODY_CHARS."""
    try:
        error = json.loads(body)["error"]
    except (ValueError, KeyError, TypeError):
        return body[:ERROR_BODY_CHARS]
    parts = [str(error.get("message", "")).strip(), str(error.get("status", ""))]
    for detail in error.get("details") or []:
        if not isinstance(detail, dict):
            continue
        if detail.get("reason"):
            parts.append(f"reason={detail['reason']}")
        for key, value in (detail.get("metadata") or {}).items():
            parts.append(f"{key}={value}")
        for link in detail.get("links") or []:
            if isinstance(link, dict) and link.get("url"):
                parts.append(f"see {link['url']}")
    return "; ".join(p for p in parts if p)


def parse_json(response: requests.Response) -> dict:
    try:
        return response.json()
    except ValueError:
        raise ApiError("INVALID_JSON", response.text[:ERROR_BODY_CHARS]) from None
