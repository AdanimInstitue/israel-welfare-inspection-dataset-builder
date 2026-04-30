from __future__ import annotations

import json
from pathlib import Path

from welfare_inspections.collect.govil_client import PageFetch, is_blocked_response
from welfare_inspections.collect.models import HttpDiagnostic
from welfare_inspections.collect.portal_discovery import discover_source_documents
from welfare_inspections.collect.portal_parser import parse_source_records

PAGE_URL = (
    "https://www.gov.il/he/departments/dynamiccollectors/"
    "molsa-supervision-frames-reports?skip=0"
)


def test_parse_single_hebrew_pdf_record_preserves_title_and_date() -> None:
    html = """
    <article>
      <a href="/he/departments/publications/reports/framework-a">פרטי פרסום</a>
      <h3>דו"ח פיקוח מסגרת אלון</h3>
      <time datetime="2024-02-13">13/02/2024</time>
      <a href="/BlobFolder/reports/framework-a/he/report.pdf">קובץ PDF</a>
    </article>
    """

    records = parse_source_records(
        html,
        page_url=PAGE_URL,
        http_status=200,
        response_headers={"content-type": "text/html"},
    )

    assert len(records) == 1
    assert records[0].title == 'דו"ח פיקוח מסגרת אלון'
    assert records[0].govil_item_slug == "framework-a"
    assert records[0].language_path == "/he/"
    assert records[0].source_published_at is not None
    assert records[0].source_published_at.year == 2024
    assert str(records[0].pdf_url).endswith(
        "/BlobFolder/reports/framework-a/he/report.pdf"
    )


def test_parse_multiple_records_and_nullable_dates() -> None:
    html = """
    <section>
      <div>
        <a href="/he/departments/publications/reports/first">פרסום ראשון</a>
        <a href="https://www.gov.il/BlobFolder/a/he/first.pdf">דוח ראשון</a>
      </div>
      <div>
        <a href="/he/departments/publications/reports/second">פרסום שני</a>
        <a href="https://www.gov.il/BlobFolder/b/he/second.pdf">דוח שני</a>
      </div>
    </section>
    """

    records = parse_source_records(
        html,
        page_url=PAGE_URL,
        http_status=200,
        response_headers={},
    )

    assert [record.title for record in records] == ["דוח ראשון", "דוח שני"]
    assert records[0].source_published_at is None
    assert records[1].source_published_at is None


def test_source_document_id_is_deterministic() -> None:
    html = """
    <article>
      <a href="/he/departments/publications/reports/stable-slug">פרסום</a>
      <a href="/BlobFolder/reports/stable/he/report.pdf">דוח</a>
    </article>
    """

    first = parse_source_records(
        html,
        page_url=PAGE_URL,
        http_status=200,
        response_headers={},
    )
    second = parse_source_records(
        html,
        page_url=PAGE_URL,
        http_status=200,
        response_headers={},
    )

    assert first[0].source_document_id == second[0].source_document_id


def test_discovery_writes_manifest_and_diagnostics(tmp_path: Path) -> None:
    html = """
    <article>
      <a href="/he/departments/publications/reports/item-a">פרסום</a>
      <a href="/BlobFolder/reports/item-a/he/report.pdf">דוח</a>
    </article>
    """
    client = FakeClient(
        [
            PageFetch(
                url=PAGE_URL,
                html=html,
                diagnostic=HttpDiagnostic(url=PAGE_URL, status_code=200),
            )
        ]
    )
    output = tmp_path / "source_manifest.jsonl"
    diagnostics = tmp_path / "diagnostics.json"

    records, run_diagnostics = discover_source_documents(
        output_path=output,
        diagnostics_path=diagnostics,
        max_pages=1,
        request_delay_seconds=0,
        client=client,
    )

    manifest_lines = output.read_text(encoding="utf-8").splitlines()
    diagnostics_payload = json.loads(diagnostics.read_text(encoding="utf-8"))
    assert len(records) == 1
    assert len(manifest_lines) == 1
    assert json.loads(manifest_lines[0])["downloaded_at"] is None
    assert diagnostics_payload["new_records"] == 1
    assert run_diagnostics.stop_reason == "max_pages"
    assert client.closed is False


def test_discovery_stops_on_empty_page(tmp_path: Path) -> None:
    client = FakeClient(
        [
            PageFetch(
                url=PAGE_URL,
                html="<html><body>לא נמצאו תוצאות</body></html>",
                diagnostic=HttpDiagnostic(url=PAGE_URL, status_code=200),
            )
        ]
    )

    records, diagnostics = discover_source_documents(
        output_path=tmp_path / "source_manifest.jsonl",
        diagnostics_path=tmp_path / "diagnostics.json",
        max_pages=3,
        request_delay_seconds=0,
        client=client,
    )

    assert records == []
    assert diagnostics.stop_reason == "empty_page"
    assert client.urls == [PAGE_URL]


def test_discovery_stops_on_repeated_page_signature(tmp_path: Path) -> None:
    html = """
    <article>
      <a href="/he/departments/publications/reports/repeated">פרסום</a>
      <a href="/BlobFolder/reports/repeated/he/report.pdf">דוח</a>
    </article>
    """
    second_url = PAGE_URL.replace("skip=0", "skip=10")
    client = FakeClient(
        [
            PageFetch(
                url=PAGE_URL,
                html=html,
                diagnostic=HttpDiagnostic(url=PAGE_URL, status_code=200),
            ),
            PageFetch(
                url=second_url,
                html=html,
                diagnostic=HttpDiagnostic(url=second_url, status_code=200),
            ),
        ]
    )

    records, diagnostics = discover_source_documents(
        output_path=tmp_path / "source_manifest.jsonl",
        diagnostics_path=tmp_path / "diagnostics.json",
        max_pages=3,
        request_delay_seconds=0,
        client=client,
    )

    assert len(records) == 1
    assert diagnostics.stop_reason == "repeated_page_signature"
    assert len(client.urls) == 2


def test_discovery_stops_at_max_pages(tmp_path: Path) -> None:
    pages = []
    for index in range(2):
        skip = index * 10
        url = PAGE_URL.replace("skip=0", f"skip={skip}")
        html = f"""
        <article>
          <a href="/he/departments/publications/reports/item-{index}">פרסום</a>
          <a href="/BlobFolder/reports/item-{index}/he/report.pdf">דוח {index}</a>
        </article>
        """
        pages.append(
            PageFetch(
                url=url,
                html=html,
                diagnostic=HttpDiagnostic(url=url, status_code=200),
            )
        )

    records, diagnostics = discover_source_documents(
        output_path=tmp_path / "source_manifest.jsonl",
        diagnostics_path=tmp_path / "diagnostics.json",
        max_pages=2,
        request_delay_seconds=0,
        client=FakeClient(pages),
    )

    assert len(records) == 2
    assert diagnostics.stop_reason == "max_pages"


def test_http_diagnostics_detect_cloudflare_block() -> None:
    html = "<title>Attention Required! | Cloudflare</title>You have been blocked"

    assert is_blocked_response(403, html) is True
    assert is_blocked_response(200, "<html>ok</html>") is False


def test_discovery_stops_on_blocked_response(tmp_path: Path) -> None:
    html = "<title>Attention Required! | Cloudflare</title>You have been blocked"
    client = FakeClient(
        [
            PageFetch(
                url=PAGE_URL,
                html=html,
                diagnostic=HttpDiagnostic(
                    url=PAGE_URL,
                    status_code=403,
                    is_blocked=True,
                ),
            )
        ]
    )

    records, diagnostics = discover_source_documents(
        output_path=tmp_path / "source_manifest.jsonl",
        diagnostics_path=tmp_path / "diagnostics.json",
        max_pages=3,
        request_delay_seconds=0,
        client=client,
    )

    assert records == []
    assert diagnostics.stop_reason == "blocked_response"
    assert diagnostics.blocked_responses == 1


class FakeClient:
    def __init__(self, pages: list[PageFetch]) -> None:
        self._pages = pages
        self.urls: list[str] = []
        self.closed = False

    def fetch(self, url: str) -> PageFetch:
        self.urls.append(url)
        return self._pages.pop(0)

    def close(self) -> None:
        self.closed = True
