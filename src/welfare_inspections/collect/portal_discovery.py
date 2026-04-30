"""Gov.il source discovery orchestration."""

from __future__ import annotations

import time
from hashlib import sha256
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import structlog

from welfare_inspections.collect.govil_client import GovilClient
from welfare_inspections.collect.manifest import (
    write_discovery_diagnostics,
    write_source_manifest,
)
from welfare_inspections.collect.models import (
    DiscoveryRunDiagnostics,
    SourceDocumentRecord,
    utc_now,
)
from welfare_inspections.collect.portal_parser import (
    page_signature,
    parse_source_records,
)

CANONICAL_SOURCE_URL = (
    "https://www.gov.il/he/departments/dynamiccollectors/"
    "molsa-supervision-frames-reports?skip=0"
)

logger = structlog.get_logger(__name__)


def discover_source_documents(
    *,
    output_path: Path,
    diagnostics_path: Path,
    start_url: str = CANONICAL_SOURCE_URL,
    max_pages: int = 5,
    page_size: int = 10,
    request_delay_seconds: float = 1.0,
    client: GovilClient | None = None,
) -> tuple[list[SourceDocumentRecord], DiscoveryRunDiagnostics]:
    diagnostics = DiscoveryRunDiagnostics(start_url=start_url)
    own_client = client is None
    http_client = client or GovilClient()
    records: list[SourceDocumentRecord] = []
    seen_ids: set[str] = set()
    seen_signatures: set[str] = set()

    try:
        for page_index in range(max_pages):
            skip = page_index * page_size
            page_url = _url_with_skip(start_url, skip)
            diagnostics.attempted_urls.append(page_url)

            fetch = http_client.fetch(page_url)
            diagnostics.http_diagnostics.append(fetch.diagnostic)
            if fetch.diagnostic.is_blocked:
                diagnostics.blocked_responses += 1
                diagnostics.stop_reason = "blocked_response"
                break

            if not fetch.html or fetch.diagnostic.status_code not in {200, None}:
                diagnostics.stop_reason = "http_error_or_empty_response"
                break

            signature = _signature_digest(page_signature(fetch.html))
            if signature in seen_signatures:
                diagnostics.stop_reason = "repeated_page_signature"
                break
            seen_signatures.add(signature)

            page_records = parse_source_records(
                fetch.html,
                page_url=page_url,
                http_status=fetch.diagnostic.status_code,
                response_headers=fetch.diagnostic.response_headers,
            )
            diagnostics.page_record_counts[page_url] = len(page_records)
            diagnostics.total_records += len(page_records)

            if not page_records:
                diagnostics.stop_reason = "empty_page"
                break

            new_this_page = 0
            for record in page_records:
                if record.source_document_id in seen_ids:
                    diagnostics.duplicate_records += 1
                    continue
                seen_ids.add(record.source_document_id)
                records.append(record)
                new_this_page += 1

            diagnostics.new_records += new_this_page
            if new_this_page == 0:
                diagnostics.stop_reason = "no_new_records"
                break

            if page_index < max_pages - 1 and request_delay_seconds > 0:
                time.sleep(request_delay_seconds)
        else:
            diagnostics.stop_reason = "max_pages"
    finally:
        if own_client:
            http_client.close()

    diagnostics.finished_at = utc_now()
    write_source_manifest(output_path, records)
    write_discovery_diagnostics(diagnostics_path, diagnostics)
    logger.info(
        "source_discovery_complete",
        records=len(records),
        stop_reason=diagnostics.stop_reason,
    )
    return records, diagnostics


def _url_with_skip(url: str, skip: int) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["skip"] = str(skip)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _signature_digest(signature: str) -> str:
    return sha256(signature.encode("utf-8")).hexdigest()
