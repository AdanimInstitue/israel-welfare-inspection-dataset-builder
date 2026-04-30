"""Conservative HTTP client for manual Gov.il source discovery probes."""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from welfare_inspections.collect.models import HttpDiagnostic

DIAGNOSTIC_HEADERS = (
    "cache-control",
    "content-language",
    "content-type",
    "etag",
    "last-modified",
    "server",
    "x-frame-options",
)


@dataclass(frozen=True)
class PageFetch:
    url: str
    html: str
    diagnostic: HttpDiagnostic


class GovilClient:
    """Small sync client used only by manually invoked discovery runs."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        user_agent: str = (
            "welfare-inspections-source-discovery/0.1 "
            "(public-data research; contact via GitHub)"
        ),
    ) -> None:
        self._client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> GovilClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @retry(
        retry=retry_if_exception_type(httpx.RequestError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def fetch(self, url: str) -> PageFetch:
        started = time.monotonic()
        try:
            response = self._client.get(url)
        except httpx.RequestError as exc:
            elapsed = time.monotonic() - started
            diagnostic = HttpDiagnostic(
                url=url,
                elapsed_seconds=elapsed,
                error=exc.__class__.__name__,
            )
            return PageFetch(url=url, html="", diagnostic=diagnostic)

        elapsed = time.monotonic() - started
        html = response.text
        diagnostic = HttpDiagnostic(
            url=str(response.url),
            status_code=response.status_code,
            response_headers=_diagnostic_headers(response.headers),
            elapsed_seconds=elapsed,
            is_blocked=is_blocked_response(response.status_code, html),
        )
        return PageFetch(url=str(response.url), html=html, diagnostic=diagnostic)


def _diagnostic_headers(headers: httpx.Headers) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() in DIAGNOSTIC_HEADERS
    }


def is_blocked_response(status_code: int | None, html: str) -> bool:
    if status_code in {401, 403, 429}:
        return True
    lowered = html.lower()
    return (
        "cloudflare" in lowered
        and ("attention required" in lowered or "you have been blocked" in lowered)
    )
