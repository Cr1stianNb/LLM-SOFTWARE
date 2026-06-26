"""HTML acquisition layer.

Deliberately thin so the rest of the pipeline does not care whether HTML came
from the live network or a frozen fixture on disk:

* ``fetch_live(url)``   — normal CLI operation, hits the real site.
* ``read_fixture(path)``— reproducible test execution, reads a local snapshot.
"""

from __future__ import annotations

import os

from .core.errors import FetchError

_USER_AGENT = (
    "Mozilla/5.0 (compatible; llmscrape/0.1; +https://example.invalid/llmscrape)"
)


def fetch_live(url: str, timeout: float = 30.0) -> str:
    """Fetch HTML from a live URL. Raises FetchError on any network problem."""
    try:
        import requests
    except ImportError as exc:  # pragma: no cover
        raise FetchError("the 'requests' package is required to fetch live URLs.") from exc

    try:
        resp = requests.get(
            url, headers={"User-Agent": _USER_AGENT}, timeout=timeout
        )
    except requests.exceptions.RequestException as exc:
        raise FetchError(f"could not reach URL '{url}': {exc}") from exc
    if resp.status_code != 200:
        raise FetchError(f"URL '{url}' returned HTTP {resp.status_code}.")
    return resp.text


def read_fixture(path: str) -> str:
    """Read a frozen HTML snapshot from disk."""
    if not os.path.exists(path):
        raise FetchError(f"fixture not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        raise FetchError(f"could not read fixture '{path}': {exc}") from exc
