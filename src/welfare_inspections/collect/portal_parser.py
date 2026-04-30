"""HTML parser for Gov.il dynamic collector result pages."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from welfare_inspections import __version__
from welfare_inspections.collect.models import (
    SourceDocumentRecord,
    source_document_id_from,
)

LANGUAGE_RE = re.compile(r"/(he|ar|en)(?:/|$)", re.IGNORECASE)
DATE_PATTERNS = (
    re.compile(r"\b(?P<year>20\d{2})-(?P<month>\d{1,2})-(?P<day>\d{1,2})\b"),
    re.compile(r"\b(?P<day>\d{1,2})[./](?P<month>\d{1,2})[./](?P<year>20\d{2})\b"),
)


def parse_source_records(
    html: str,
    *,
    page_url: str,
    http_status: int | None,
    response_headers: dict[str, str],
) -> list[SourceDocumentRecord]:
    soup = BeautifulSoup(html, "lxml")
    records: list[SourceDocumentRecord] = []

    for link in soup.find_all("a", href=True):
        href = str(link.get("href", "")).strip()
        if not _is_pdf_link(href):
            continue

        pdf_url = urljoin(page_url, href)
        container = _record_container(link)
        item_url = _item_url(container, page_url, pdf_url)
        slug = _slug_from_url(item_url)
        title = _title_from(link, container)
        source_published_at = _date_from(container)
        language_path = _language_path(item_url) or _language_path(page_url)
        source_document_id = source_document_id_from(slug, item_url, pdf_url)

        records.append(
            SourceDocumentRecord(
                source_document_id=source_document_id,
                govil_item_slug=slug,
                govil_item_url=item_url,
                pdf_url=pdf_url,
                title=title,
                language_path=language_path,
                source_published_at=source_published_at,
                source_updated_at=None,
                http_status=http_status,
                response_headers=response_headers,
                collector_version=__version__,
            )
        )

    return _dedupe(records)


def page_signature(html: str) -> str:
    normalized = re.sub(r"\s+", " ", BeautifulSoup(html, "lxml").get_text(" ")).strip()
    return normalized


def _is_pdf_link(href: str) -> bool:
    parsed = urlparse(href)
    path = parsed.path.lower()
    return path.endswith(".pdf") or ("/blobfolder/" in path and "pdf" in path)


def _record_container(link: Tag) -> Tag:
    for parent in link.parents:
        if isinstance(parent, Tag) and parent.name in {
            "article",
            "li",
            "tr",
            "section",
            "div",
        }:
            if parent.find("a", href=True):
                return parent
    return link


def _item_url(container: Tag, page_url: str, pdf_url: str) -> str:
    page_path = urlparse(page_url).path.rstrip("/")
    for link in container.find_all("a", href=True):
        href = str(link.get("href", "")).strip()
        absolute = urljoin(page_url, href)
        path = urlparse(absolute).path.rstrip("/")
        if absolute == pdf_url or _is_pdf_link(href) or path == page_path:
            continue
        if "/departments/" in path.lower():
            return absolute
    return page_url


def _slug_from_url(url: str) -> str | None:
    path = PurePosixPath(urlparse(url).path)
    name = path.name
    if not name or name.lower() in {"dynamiccollectors", "departments"}:
        return None
    return name


def _title_from(link: Tag, container: Tag) -> str | None:
    candidates: list[str] = []
    for heading_name in ("h1", "h2", "h3", "h4"):
        heading = container.find(heading_name)
        if heading:
            candidates.append(heading.get_text(" ", strip=True))
    candidates.extend(
        [
            str(link.get("title", "")).strip(),
            str(link.get("aria-label", "")).strip(),
            link.get_text(" ", strip=True),
        ]
    )

    for candidate in candidates:
        if candidate:
            return re.sub(r"\s+", " ", candidate)
    return None


def _date_from(container: Tag) -> datetime | None:
    time_tag = container.find("time")
    if time_tag:
        raw_datetime = str(time_tag.get("datetime", "")).strip()
        parsed = _parse_date(raw_datetime)
        if parsed:
            return parsed

    text = container.get_text(" ", strip=True)
    return _parse_date(text)


def _parse_date(text: str) -> datetime | None:
    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        parts = {key: int(value) for key, value in match.groupdict().items()}
        try:
            return datetime(parts["year"], parts["month"], parts["day"], tzinfo=UTC)
        except ValueError:
            continue
    return None


def _language_path(url: str) -> str | None:
    match = LANGUAGE_RE.search(urlparse(url).path)
    if not match:
        return None
    return f"/{match.group(1).lower()}/"


def _dedupe(records: list[SourceDocumentRecord]) -> list[SourceDocumentRecord]:
    seen: set[str] = set()
    unique: list[SourceDocumentRecord] = []
    for record in records:
        if record.source_document_id in seen:
            continue
        seen.add(record.source_document_id)
        unique.append(record)
    return unique
