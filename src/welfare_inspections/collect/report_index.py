"""Report index collection for Gov.il listing-page facts."""

from __future__ import annotations

import csv
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import structlog
from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel, ConfigDict, Field

from welfare_inspections import __version__
from welfare_inspections.collect.govil_client import GovilClient
from welfare_inspections.collect.local_outputs import validate_local_output_path
from welfare_inspections.collect.models import (
    DynamicCollectorConfig,
    HttpDiagnostic,
    utc_now,
)
from welfare_inspections.collect.portal_parser import parse_dynamic_collector_config

CANONICAL_SOURCE_URL = (
    "https://www.gov.il/he/departments/dynamiccollectors/"
    "molsa-supervision-frames-reports?skip=0"
)
COLLECTOR_VERSION = f"report-index-{__version__}"
HEBREW_COLUMNS = (
    "שם מסגרת",
    "סוג מסגרת",
    "סמל מסגרת",
    "מינהל",
    "מחוז",
    "תאריך ביצוע",
)
FIELD_ALIASES = {
    "institution_name": "שם מסגרת",
    "institution_type": "סוג מסגרת",
    "institution_symbol": "סמל מסגרת",
    "administration": "מינהל",
    "district": "מחוז",
    "survey_date": "תאריך ביצוע",
}
HEBREW_TO_ALIAS = {value: key for key, value in FIELD_ALIASES.items()}
DATE_TEXT_PATTERN = re.compile(r"^\s*\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\s*$")

logger = structlog.get_logger(__name__)


class BrowserCollectionUnavailable(RuntimeError):
    """Raised when browser-rendered fallback collection cannot run locally."""


class ReportIndexRecord(BaseModel):
    """One report-card row from the Gov.il listing page."""

    model_config = ConfigDict(extra="forbid")

    institution_name: str | None = None
    institution_type: str | None = None
    institution_symbol: str | None = None
    administration: str | None = None
    district: str | None = None
    survey_date: str | None = None
    report_index_id: str
    source_record_id: str
    govil_item_url: str | None = None
    pdf_url: str | None = None
    discovered_at: datetime = Field(default_factory=utc_now)
    source_page_url: str
    source_skip: int | None = None
    source_position: int | None = None
    collection_run_id: str
    collector_version: str = COLLECTOR_VERSION

    def csv_row(self) -> dict[str, str]:
        return {
            hebrew: getattr(self, alias) or ""
            for alias, hebrew in FIELD_ALIASES.items()
        }

    def jsonl_row(self) -> dict[str, Any]:
        values = self.csv_row()
        values.update(
            {
                "report_index_id": self.report_index_id,
                "source_record_id": self.source_record_id,
                "govil_item_url": self.govil_item_url,
                "pdf_url": self.pdf_url,
                "discovered_at": self.discovered_at.isoformat(),
                "source_page_url": self.source_page_url,
                "source_skip": self.source_skip,
                "source_position": self.source_position,
                "collection_run_id": self.collection_run_id,
                "collector_version": self.collector_version,
            }
        )
        return values


class ReportIndexRecordDiagnostic(BaseModel):
    """Per-record diagnostics for report-index validation."""

    model_config = ConfigDict(extra="forbid")

    report_index_id: str | None = None
    source_record_id: str | None = None
    source_path: str
    source_page_url: str
    source_skip: int | None = None
    source_position: int | None = None
    status: str
    missing_fields: list[str] = Field(default_factory=list)
    malformed_date_text: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ReportIndexRunDiagnostics(BaseModel):
    """Run-level diagnostics for report-index collection."""

    model_config = ConfigDict(extra="forbid")

    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    start_url: str
    collection_run_id: str
    collector_version: str = COLLECTOR_VERSION
    source_path_used: str | None = None
    source_path_attempted: list[str] = Field(default_factory=list)
    attempted_urls: list[str] = Field(default_factory=list)
    http_diagnostics: list[HttpDiagnostic] = Field(default_factory=list)
    field_coverage_by_path: dict[str, dict[str, dict[str, int]]] = Field(
        default_factory=dict
    )
    page_record_counts: dict[str, int] = Field(default_factory=dict)
    source_total_results_by_path: dict[str, int | None] = Field(default_factory=dict)
    total_records: int = 0
    emitted_records: int = 0
    duplicate_id_records: int = 0
    missing_field_records: int = 0
    malformed_date_text_records: int = 0
    blocked_responses: int = 0
    stop_reason: str | None = None
    output_csv_path: str
    output_jsonl_path: str
    diagnostics_path: str
    record_diagnostics: list[ReportIndexRecordDiagnostic] = Field(
        default_factory=list
    )
    notes: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class BrowserCollectionResult:
    records: list[ReportIndexRecord]
    diagnostics: ReportIndexRunDiagnostics


BrowserCollector = Callable[
    [str, int, int, float, str],
    BrowserCollectionResult,
]


def collect_report_index(
    *,
    output_csv_path: Path,
    output_jsonl_path: Path,
    diagnostics_path: Path,
    start_url: str = CANONICAL_SOURCE_URL,
    max_pages: int = 5,
    page_size: int = 10,
    request_delay_seconds: float = 1.0,
    client: GovilClient | None = None,
    browser_collector: BrowserCollector | None = None,
) -> tuple[list[ReportIndexRecord], ReportIndexRunDiagnostics]:
    """Collect Gov.il listing-page report cards into local ignored artifacts."""
    _validate_output_paths(output_csv_path, output_jsonl_path, diagnostics_path)
    collection_run_id = _collection_run_id(start_url)
    diagnostics = ReportIndexRunDiagnostics(
        start_url=start_url,
        collection_run_id=collection_run_id,
        output_csv_path=str(output_csv_path),
        output_jsonl_path=str(output_jsonl_path),
        diagnostics_path=str(diagnostics_path),
    )

    own_client = client is None
    http_client = client or GovilClient()
    try:
        records, diagnostics, needs_browser = _collect_structured(
            start_url=start_url,
            max_pages=max_pages,
            page_size=page_size,
            request_delay_seconds=request_delay_seconds,
            collection_run_id=collection_run_id,
            diagnostics=diagnostics,
            client=http_client,
        )
    finally:
        if own_client:
            http_client.close()

    if needs_browser:
        collector = browser_collector or collect_report_index_from_browser
        browser_result = collector(
            start_url,
            max_pages,
            page_size,
            request_delay_seconds,
            collection_run_id,
        )
        records = browser_result.records
        browser_diagnostics = browser_result.diagnostics
        browser_diagnostics.output_csv_path = str(output_csv_path)
        browser_diagnostics.output_jsonl_path = str(output_jsonl_path)
        browser_diagnostics.diagnostics_path = str(diagnostics_path)
        browser_diagnostics.source_path_attempted = list(
            dict.fromkeys(
                [
                    *diagnostics.source_path_attempted,
                    *browser_diagnostics.source_path_attempted,
                ]
            )
        )
        browser_diagnostics.attempted_urls = list(
            dict.fromkeys(
                [
                    *diagnostics.attempted_urls,
                    *browser_diagnostics.attempted_urls,
                ]
            )
        )
        browser_diagnostics.http_diagnostics = [
            *diagnostics.http_diagnostics,
            *browser_diagnostics.http_diagnostics,
        ]
        browser_diagnostics.field_coverage_by_path = {
            **diagnostics.field_coverage_by_path,
            **browser_diagnostics.field_coverage_by_path,
        }
        browser_diagnostics.page_record_counts = {
            **diagnostics.page_record_counts,
            **browser_diagnostics.page_record_counts,
        }
        browser_diagnostics.source_total_results_by_path = {
            **diagnostics.source_total_results_by_path,
            **browser_diagnostics.source_total_results_by_path,
        }
        browser_diagnostics.blocked_responses += diagnostics.blocked_responses
        browser_diagnostics.notes = [
            *diagnostics.notes,
            *browser_diagnostics.notes,
        ]
        diagnostics = browser_diagnostics

    records, diagnostics = _validate_and_dedupe(records, diagnostics)
    diagnostics.finished_at = utc_now()
    _write_outputs(
        output_csv_path,
        output_jsonl_path,
        diagnostics_path,
        records,
        diagnostics,
    )
    logger.info(
        "report_index_collection_complete",
        records=len(records),
        source_path=diagnostics.source_path_used,
        stop_reason=diagnostics.stop_reason,
    )
    return records, diagnostics


def collect_report_index_from_browser(
    start_url: str,
    max_pages: int,
    page_size: int,
    request_delay_seconds: float,
    collection_run_id: str,
) -> BrowserCollectionResult:
    """Collect rendered public DOM cards with Playwright when available."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        msg = (
            "Structured Gov.il data was incomplete and browser-rendered DOM "
            "fallback requires optional Playwright support in the local "
            "environment."
        )
        raise BrowserCollectionUnavailable(msg) from exc

    diagnostics = ReportIndexRunDiagnostics(
        start_url=start_url,
        collection_run_id=collection_run_id,
        source_path_used="browser_dom",
        source_path_attempted=["browser_dom"],
        output_csv_path="",
        output_jsonl_path="",
        diagnostics_path="",
    )
    records: list[ReportIndexRecord] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            for page_index in range(max_pages):
                skip = page_index * page_size
                page_url = _url_with_skip(start_url, skip)
                diagnostics.attempted_urls.append(page_url)
                page.goto(page_url, wait_until="networkidle", timeout=60_000)
                html = page.content()
                page_records = parse_report_index_dom_records(
                    html,
                    page_url=page_url,
                    source_skip=skip,
                    collection_run_id=collection_run_id,
                )
                diagnostics.page_record_counts[page_url] = len(page_records)
                records.extend(page_records)
                if not page_records:
                    diagnostics.stop_reason = "empty_page"
                    break
                if page_index < max_pages - 1 and request_delay_seconds > 0:
                    time.sleep(request_delay_seconds)
            else:
                diagnostics.stop_reason = "max_pages"
        finally:
            browser.close()
    _record_field_coverage(diagnostics, "browser_dom", records)
    return BrowserCollectionResult(records=records, diagnostics=diagnostics)


def parse_structured_report_index_records(
    payload: dict[str, Any],
    *,
    page_url: str,
    source_skip: int,
    collection_run_id: str,
) -> list[ReportIndexRecord]:
    records: list[ReportIndexRecord] = []
    for position, item in enumerate(payload.get("Results", []), 1):
        if not isinstance(item, dict):
            continue
        values = _extract_report_index_values(item)
        url_name = _clean_text(item.get("UrlName"))
        pdf_url = _structured_pdf_url(item, page_url)
        govil_item_url = _structured_item_url(page_url, url_name)
        source_record_id = _stable_source_record_id(
            govil_item_url=govil_item_url,
            pdf_url=pdf_url,
            values=values,
        )
        records.append(
            ReportIndexRecord(
                **values,
                report_index_id=_stable_report_index_id(source_record_id, values),
                source_record_id=source_record_id,
                govil_item_url=govil_item_url,
                pdf_url=pdf_url,
                source_page_url=page_url,
                source_skip=source_skip,
                source_position=position,
                collection_run_id=collection_run_id,
            )
        )
    return records


def parse_report_index_dom_records(
    html: str,
    *,
    page_url: str,
    source_skip: int,
    collection_run_id: str,
) -> list[ReportIndexRecord]:
    soup = BeautifulSoup(html, "lxml")
    candidates = _dom_candidate_cards(soup)
    records: list[ReportIndexRecord] = []
    for position, card in enumerate(candidates, 1):
        values = _extract_label_value_pairs(card)
        if not any(values.values()):
            continue
        pdf_url = _first_pdf_url(card, page_url)
        govil_item_url = _first_item_url(card, page_url, pdf_url)
        source_record_id = _stable_source_record_id(
            govil_item_url=govil_item_url,
            pdf_url=pdf_url,
            values=values,
        )
        records.append(
            ReportIndexRecord(
                **values,
                report_index_id=_stable_report_index_id(source_record_id, values),
                source_record_id=source_record_id,
                govil_item_url=govil_item_url,
                pdf_url=pdf_url,
                source_page_url=page_url,
                source_skip=source_skip,
                source_position=position,
                collection_run_id=collection_run_id,
            )
        )
    return records


def _collect_structured(
    *,
    start_url: str,
    max_pages: int,
    page_size: int,
    request_delay_seconds: float,
    collection_run_id: str,
    diagnostics: ReportIndexRunDiagnostics,
    client: GovilClient,
) -> tuple[list[ReportIndexRecord], ReportIndexRunDiagnostics, bool]:
    diagnostics.source_path_attempted.append("structured_dynamic_collector")
    records: list[ReportIndexRecord] = []
    config: DynamicCollectorConfig | None = None

    for page_index in range(max_pages):
        skip = page_index * page_size
        page_url = _url_with_skip(start_url, skip)
        diagnostics.attempted_urls.append(page_url)
        page_fetch = client.fetch(page_url)
        diagnostics.http_diagnostics.append(page_fetch.diagnostic)
        if page_fetch.diagnostic.is_blocked:
            diagnostics.blocked_responses += 1
            diagnostics.stop_reason = "blocked_response"
            diagnostics.notes.append("structured_path_blocked_before_fallback")
            return records, diagnostics, True
        if not page_fetch.html or page_fetch.diagnostic.status_code not in {200, None}:
            diagnostics.stop_reason = "http_error_or_empty_response"
            diagnostics.notes.append("structured_path_unavailable_before_fallback")
            return records, diagnostics, True

        if config is None:
            config = parse_dynamic_collector_config(page_fetch.html, page_url=page_url)
        if config is None:
            diagnostics.stop_reason = "missing_dynamic_collector_config"
            diagnostics.notes.append("structured_config_missing_before_fallback")
            return records, diagnostics, True

        diagnostics.attempted_urls.append(config.endpoint_url)
        structured_fetch = client.post_json(
            config.endpoint_url,
            {
                "DynamicTemplateID": config.dynamic_template_id,
                "QueryFilters": {"skip": {"Query": skip}},
                "From": skip,
                "ItemUrlName": None,
            },
            config.x_client_id,
        )
        diagnostics.http_diagnostics.append(structured_fetch.diagnostic)
        if structured_fetch.diagnostic.is_blocked:
            diagnostics.blocked_responses += 1
            diagnostics.stop_reason = "blocked_response"
            diagnostics.notes.append("structured_endpoint_blocked_before_fallback")
            return records, diagnostics, True
        if structured_fetch.diagnostic.error:
            diagnostics.stop_reason = "http_error_or_empty_response"
            diagnostics.notes.append("structured_endpoint_error_before_fallback")
            return records, diagnostics, True

        page_records = parse_structured_report_index_records(
            structured_fetch.data,
            page_url=page_url,
            source_skip=skip,
            collection_run_id=collection_run_id,
        )
        diagnostics.page_record_counts[page_url] = len(page_records)
        total_results = structured_fetch.data.get("TotalResults")
        if isinstance(total_results, int):
            diagnostics.source_total_results_by_path[
                "structured_dynamic_collector"
            ] = total_results
        if not page_records:
            diagnostics.stop_reason = "empty_page"
            break
        records.extend(page_records)
        _record_field_coverage(diagnostics, "structured_dynamic_collector", records)
        if any(_missing_fields(record) for record in page_records):
            diagnostics.stop_reason = "structured_incomplete_fields"
            diagnostics.notes.append(
                "Structured DynamicCollector response omitted required card fields; "
                "falling back to browser-rendered DOM collection."
            )
            return records, diagnostics, True
        if page_index < max_pages - 1 and request_delay_seconds > 0:
            time.sleep(request_delay_seconds)
    else:
        diagnostics.stop_reason = "max_pages"

    diagnostics.source_path_used = "structured_dynamic_collector"
    return records, diagnostics, False


def _validate_and_dedupe(
    records: list[ReportIndexRecord],
    diagnostics: ReportIndexRunDiagnostics,
) -> tuple[list[ReportIndexRecord], ReportIndexRunDiagnostics]:
    diagnostics.total_records = len(records)
    unique: list[ReportIndexRecord] = []
    seen_ids: set[str] = set()
    for record in records:
        missing_fields = _missing_fields(record)
        warnings: list[str] = []
        malformed_date_text = None
        if record.survey_date and not DATE_TEXT_PATTERN.match(record.survey_date):
            malformed_date_text = record.survey_date
            warnings.append("survey_date_source_text_is_not_date_like")
            diagnostics.malformed_date_text_records += 1

        if record.report_index_id in seen_ids:
            diagnostics.duplicate_id_records += 1
            diagnostics.record_diagnostics.append(
                ReportIndexRecordDiagnostic(
                    report_index_id=record.report_index_id,
                    source_record_id=record.source_record_id,
                    source_path=diagnostics.source_path_used or "unknown",
                    source_page_url=record.source_page_url,
                    source_skip=record.source_skip,
                    source_position=record.source_position,
                    status="duplicate_report_index_id",
                    missing_fields=missing_fields,
                    malformed_date_text=malformed_date_text,
                    warnings=warnings,
                )
            )
            continue
        seen_ids.add(record.report_index_id)
        if missing_fields:
            diagnostics.missing_field_records += 1
            status = "missing_required_visible_fields"
        elif malformed_date_text:
            status = "warning"
        else:
            status = "valid"
        diagnostics.record_diagnostics.append(
            ReportIndexRecordDiagnostic(
                report_index_id=record.report_index_id,
                source_record_id=record.source_record_id,
                source_path=diagnostics.source_path_used or "unknown",
                source_page_url=record.source_page_url,
                source_skip=record.source_skip,
                source_position=record.source_position,
                status=status,
                missing_fields=missing_fields,
                malformed_date_text=malformed_date_text,
                warnings=warnings,
            )
        )
        unique.append(record)
    diagnostics.emitted_records = len(unique)
    _record_field_coverage(
        diagnostics,
        diagnostics.source_path_used or "unknown",
        unique,
    )
    return unique, diagnostics


def _write_outputs(
    output_csv_path: Path,
    output_jsonl_path: Path,
    diagnostics_path: Path,
    records: list[ReportIndexRecord],
    diagnostics: ReportIndexRunDiagnostics,
) -> None:
    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    output_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output_csv_path, records)
    _atomic_write_text(
        output_jsonl_path,
        "".join(
            f"{_json_dumps(record.jsonl_row())}\n"
            for record in records
        ),
    )
    _atomic_write_text(diagnostics_path, diagnostics.model_dump_json(indent=2) + "\n")


def _write_csv(path: Path, records: list[ReportIndexRecord]) -> None:
    temporary_path = path.with_name(f"{path.name}.tmp")
    with temporary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(HEBREW_COLUMNS))
        writer.writeheader()
        for record in records:
            writer.writerow(record.csv_row())
    temporary_path.replace(path)


def _atomic_write_text(path: Path, content: str) -> None:
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text(content, encoding="utf-8")
    temporary_path.replace(path)


def _json_dumps(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _validate_output_paths(*paths: Path) -> None:
    for path in paths:
        validate_local_output_path(path, label="report index output path")


def _record_field_coverage(
    diagnostics: ReportIndexRunDiagnostics,
    source_path: str,
    records: list[ReportIndexRecord],
) -> None:
    coverage: dict[str, dict[str, int]] = {}
    for alias, hebrew in FIELD_ALIASES.items():
        present = sum(1 for record in records if getattr(record, alias))
        coverage[hebrew] = {"present": present, "total": len(records)}
    diagnostics.field_coverage_by_path[source_path] = coverage


def _extract_report_index_values(item: dict[str, Any]) -> dict[str, str | None]:
    values: dict[str, str | None] = {alias: None for alias in FIELD_ALIASES}
    flattened = _flatten_item_values(item)
    for raw_key, value in flattened:
        alias = _field_alias_from_key(raw_key)
        if alias and not values[alias]:
            values[alias] = value
    return values


def _flatten_item_values(value: Any, *, prefix: str = "") -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    if isinstance(value, dict):
        label = _clean_text(
            value.get("Label") or value.get("label") or value.get("Key")
        )
        text_value = _clean_text(
            value.get("Value")
            or value.get("value")
            or value.get("Text")
            or value.get("text")
            or value.get("Title")
        )
        if label and text_value:
            pairs.append((label, text_value))
        for key, nested in value.items():
            nested_prefix = f"{prefix}.{key}" if prefix else str(key)
            pairs.extend(_flatten_item_values(nested, prefix=nested_prefix))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            pairs.extend(_flatten_item_values(nested, prefix=f"{prefix}.{index}"))
    else:
        text_value = _clean_text(value)
        if prefix and text_value:
            pairs.append((prefix, text_value))
    return pairs


def _field_alias_from_key(key: str) -> str | None:
    normalized = _normalize_key(key)
    aliases = {
        "institutionname": "institution_name",
        "frameworkname": "institution_name",
        "shememisgeret": "institution_name",
        "שםמסגרת": "institution_name",
        "institutiontype": "institution_type",
        "frameworktype": "institution_type",
        "סוגמסגרת": "institution_type",
        "institutionsymbol": "institution_symbol",
        "frameworksymbol": "institution_symbol",
        "semelmisgeret": "institution_symbol",
        "סמלמסגרת": "institution_symbol",
        "administration": "administration",
        "minhal": "administration",
        "מינהל": "administration",
        "מנהל": "administration",
        "district": "district",
        "מחוז": "district",
        "surveydate": "survey_date",
        "inspectiondate": "survey_date",
        "visitdate": "survey_date",
        "תאריךביצוע": "survey_date",
    }
    direct = aliases.get(normalized)
    if direct:
        return direct
    for suffix, alias in aliases.items():
        if normalized.endswith(suffix):
            return alias
    return None


def _normalize_key(key: str) -> str:
    return re.sub(r"[\W_]+", "", key, flags=re.UNICODE).lower()


def _structured_pdf_url(item: dict[str, Any], page_url: str) -> str | None:
    data = item.get("Data") if isinstance(item.get("Data"), dict) else {}
    url_name = _clean_text(item.get("UrlName"))
    for file_info in data.get("report", []):
        if not isinstance(file_info, dict):
            continue
        file_name = _clean_text(file_info.get("FileName"))
        if url_name and file_name:
            return urljoin(
                page_url,
                f"/BlobFolder/dynamiccollectorresultitem/{url_name}/he/{file_name}",
            )
    for key, value in _flatten_item_values(item):
        if _field_alias_from_key(key):
            continue
        if _is_pdf_url(value):
            return urljoin(page_url, value)
    return None


def _structured_item_url(page_url: str, url_name: str | None) -> str | None:
    if not url_name:
        return page_url
    parsed = urlparse(page_url)
    return urlunparse(parsed._replace(query=f"DCRI_UrlName={url_name}", fragment=""))


def _dom_candidate_cards(soup: BeautifulSoup) -> list[Tag]:
    cards: list[Tag] = []
    for tag in soup.find_all(["article", "li", "tr", "section", "div"]):
        if not isinstance(tag, Tag):
            continue
        values = _extract_label_value_pairs(tag)
        has_enough_fields = sum(1 for value in values.values() if value) >= 2
        if has_enough_fields and tag.find("a", href=True):
            nested = [
                child
                for child in tag.find_all(["article", "li", "tr", "section", "div"])
                if isinstance(child, Tag)
                and child is not tag
                and _has_enough_report_index_fields(child)
            ]
            if not nested:
                cards.append(tag)
    return cards


def _extract_label_value_pairs(card: Tag) -> dict[str, str | None]:
    values: dict[str, str | None] = {alias: None for alias in FIELD_ALIASES}
    for text in card.stripped_strings:
        parsed = _parse_label_text(text)
        if not parsed:
            continue
        alias, value = parsed
        if not values[alias]:
            values[alias] = value
    for element in card.find_all(attrs=True):
        for attr in ("aria-label", "title", "data-label", "data-value"):
            parsed = _parse_label_text(str(element.get(attr, "")))
            if not parsed:
                continue
            alias, value = parsed
            if not values[alias]:
                values[alias] = value
    return values


def _has_enough_report_index_fields(card: Tag) -> bool:
    values = _extract_label_value_pairs(card)
    return sum(1 for value in values.values() if value) >= 2


def _parse_label_text(text: str) -> tuple[str, str] | None:
    clean = re.sub(r"\s+", " ", text).strip()
    for hebrew, alias in HEBREW_TO_ALIAS.items():
        if clean == hebrew:
            continue
        if clean.startswith(f"{hebrew}:") or clean.startswith(f"{hebrew}："):
            value = clean.split(":", maxsplit=1)[-1].strip()
            if value:
                return alias, value
        pattern = re.compile(rf"^{re.escape(hebrew)}\s+(.+)$")
        match = pattern.match(clean)
        if match:
            return alias, match.group(1).strip()
    return None


def _first_pdf_url(card: Tag, page_url: str) -> str | None:
    for link in card.find_all("a", href=True):
        href = str(link.get("href", "")).strip()
        if _is_pdf_url(href):
            return urljoin(page_url, href)
    return None


def _first_item_url(card: Tag, page_url: str, pdf_url: str | None) -> str | None:
    page_path = urlparse(page_url).path.rstrip("/")
    for link in card.find_all("a", href=True):
        href = str(link.get("href", "")).strip()
        absolute = urljoin(page_url, href)
        path = urlparse(absolute).path.rstrip("/")
        if absolute == pdf_url or _is_pdf_url(href) or path == page_path:
            continue
        if "/departments/" in path.lower():
            return absolute
    return page_url


def _is_pdf_url(value: str | None) -> bool:
    if not value:
        return False
    path = urlparse(value).path.lower()
    return path.endswith(".pdf") or ("/blobfolder/" in path and "pdf" in path)


def _missing_fields(record: ReportIndexRecord) -> list[str]:
    return [
        hebrew
        for alias, hebrew in FIELD_ALIASES.items()
        if not getattr(record, alias)
    ]


def _stable_source_record_id(
    *,
    govil_item_url: str | None,
    pdf_url: str | None,
    values: dict[str, str | None],
) -> str:
    key = "|".join(
        [
            govil_item_url or "",
            pdf_url or "",
            values.get("institution_symbol") or "",
            values.get("survey_date") or "",
            values.get("institution_name") or "",
        ]
    )
    return f"source-record-{sha256(key.encode('utf-8')).hexdigest()[:16]}"


def _stable_report_index_id(
    source_record_id: str,
    values: dict[str, str | None],
) -> str:
    key = "|".join(
        [source_record_id, *(values.get(alias) or "" for alias in FIELD_ALIASES)]
    )
    return f"report-index-{sha256(key.encode('utf-8')).hexdigest()[:16]}"


def _collection_run_id(start_url: str) -> str:
    now = utc_now().isoformat()
    digest = sha256(f"{start_url}|{now}".encode()).hexdigest()[:12]
    return f"report-index-run-{digest}"


def _url_with_skip(url: str, skip: int) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["skip"] = str(skip)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None
