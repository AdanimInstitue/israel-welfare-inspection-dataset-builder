"""Conservative HTTP client for manual Gov.il source discovery probes."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import (
    RetryError,
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


@dataclass(frozen=True)
class JsonFetch:
    url: str
    data: dict[str, Any]
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

    @retry(
        retry=retry_if_exception_type(httpx.RequestError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    def _get_with_retries(self, url: str) -> httpx.Response:
        return self._client.get(url)

    @retry(
        retry=retry_if_exception_type(httpx.RequestError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    def _post_with_retries(
        self,
        url: str,
        payload: dict[str, Any],
        x_client_id: str,
    ) -> httpx.Response:
        return self._client.post(
            url,
            json=payload,
            headers={"x-client-id": x_client_id},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> GovilClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def fetch(self, url: str) -> PageFetch:
        started = time.monotonic()
        try:
            response = self._get_with_retries(url)
        except RetryError as exc:
            elapsed = time.monotonic() - started
            return _error_fetch(url, elapsed, _retry_error_name(exc))
        except Exception as exc:
            elapsed = time.monotonic() - started
            return _error_fetch(url, elapsed, exc.__class__.__name__)

        elapsed = time.monotonic() - started
        try:
            html = response.text
            diagnostic = HttpDiagnostic(
                url=str(response.url),
                status_code=response.status_code,
                response_headers=_diagnostic_headers(response.headers),
                elapsed_seconds=elapsed,
                is_blocked=is_blocked_response(response.status_code, html),
            )
            return PageFetch(url=str(response.url), html=html, diagnostic=diagnostic)
        except Exception as exc:
            return _error_fetch(url, elapsed, exc.__class__.__name__)

    def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        x_client_id: str,
    ) -> JsonFetch:
        started = time.monotonic()
        try:
            response = self._post_with_retries(url, payload, x_client_id)
        except RetryError as exc:
            elapsed = time.monotonic() - started
            return _error_json_fetch(url, elapsed, _retry_error_name(exc))
        except Exception as exc:
            elapsed = time.monotonic() - started
            return _error_json_fetch(url, elapsed, exc.__class__.__name__)

        elapsed = time.monotonic() - started
        try:
            text = response.text
            diagnostic = HttpDiagnostic(
                url=str(response.url),
                status_code=response.status_code,
                response_headers=_diagnostic_headers(response.headers),
                elapsed_seconds=elapsed,
                is_blocked=is_blocked_response(response.status_code, text),
            )
            data = response.json() if response.status_code == 200 else {}
            return JsonFetch(
                url=str(response.url),
                data=data if isinstance(data, dict) else {},
                diagnostic=diagnostic,
            )
        except Exception as exc:
            return _error_json_fetch(url, elapsed, exc.__class__.__name__)


def _error_fetch(url: str, elapsed_seconds: float, error: str) -> PageFetch:
    diagnostic = HttpDiagnostic(
        url=url,
        elapsed_seconds=elapsed_seconds,
        error=error,
    )
    return PageFetch(url=url, html="", diagnostic=diagnostic)


def _error_json_fetch(url: str, elapsed_seconds: float, error: str) -> JsonFetch:
    diagnostic = HttpDiagnostic(
        url=url,
        elapsed_seconds=elapsed_seconds,
        error=error,
    )
    return JsonFetch(url=url, data={}, diagnostic=diagnostic)


def _retry_error_name(exc: RetryError) -> str:
    try:
        last_exception = exc.last_attempt.exception()
    except Exception:
        return exc.__class__.__name__
    if last_exception is None:
        return exc.__class__.__name__
    return last_exception.__class__.__name__


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
