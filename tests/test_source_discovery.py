from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import typer

from welfare_inspections import cli
from welfare_inspections.collect import govil_client, portal_discovery
from welfare_inspections.collect.govil_client import (
    GovilClient,
    PageFetch,
    is_blocked_response,
)
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


def test_parse_blobfolder_link_without_pdf_extension_and_missing_metadata() -> None:
    page_url = "https://www.gov.il/departments/dynamiccollectors?skip=0"
    html = """
    <a href="/BlobFolder/reports/standalone/he/pdf-file"></a>
    """

    records = parse_source_records(
        html,
        page_url=page_url,
        http_status=200,
        response_headers={},
    )

    assert len(records) == 1
    assert records[0].title is None
    assert records[0].govil_item_slug is None
    assert records[0].govil_item_url == page_url


def test_parse_falls_back_to_aria_label_and_page_language_missing() -> None:
    page_url = "https://www.gov.il/departments/dynamiccollectors?skip=0"
    html = """
    <article>
      <a href="/departments/dynamiccollectors?skip=0">same page</a>
      <a href="/files/report.pdf" aria-label="Accessible report"></a>
    </article>
    """

    records = parse_source_records(
        html,
        page_url=page_url,
        http_status=200,
        response_headers={},
    )

    assert len(records) == 1
    assert records[0].title == "Accessible report"
    assert records[0].language_path is None
    assert records[0].govil_item_slug is None


def test_parse_deduplicates_duplicate_pdf_records() -> None:
    html = """
    <article>
      <a href="/he/departments/publications/reports/duplicate">פרסום</a>
      <a href="/BlobFolder/reports/duplicate/he/report.pdf">דוח</a>
      <a href="/BlobFolder/reports/duplicate/he/report.pdf">דוח</a>
    </article>
    """

    records = parse_source_records(
        html,
        page_url=PAGE_URL,
        http_status=200,
        response_headers={},
    )

    assert len(records) == 1


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


def test_discovery_stops_on_http_error_or_empty_response(tmp_path: Path) -> None:
    client = FakeClient(
        [
            PageFetch(
                url=PAGE_URL,
                html="",
                diagnostic=HttpDiagnostic(url=PAGE_URL, status_code=500),
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
    assert diagnostics.stop_reason == "http_error_or_empty_response"


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


def test_discovery_counts_duplicates_and_stops_with_no_new_records(
    tmp_path: Path,
) -> None:
    first_html = """
    <article>
      <a href="/he/departments/publications/reports/duplicate">פרסום</a>
      <a href="/BlobFolder/reports/duplicate/he/report.pdf">דוח</a>
    </article>
    """
    second_html = first_html + "<p>updated footer</p>"
    second_url = PAGE_URL.replace("skip=0", "skip=10")
    client = FakeClient(
        [
            PageFetch(
                url=PAGE_URL,
                html=first_html,
                diagnostic=HttpDiagnostic(url=PAGE_URL, status_code=200),
            ),
            PageFetch(
                url=second_url,
                html=second_html,
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
    assert diagnostics.duplicate_records == 1
    assert diagnostics.stop_reason == "no_new_records"


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


def test_discovery_respects_request_delay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls: list[float] = []
    pages = []
    for index in range(2):
        skip = index * 10
        url = PAGE_URL.replace("skip=0", f"skip={skip}")
        html = f"""
        <article>
          <a href="/he/departments/publications/reports/delay-{index}">פרסום</a>
          <a href="/BlobFolder/reports/delay-{index}/he/report.pdf">דוח</a>
        </article>
        """
        pages.append(
            PageFetch(
                url=url,
                html=html,
                diagnostic=HttpDiagnostic(url=url, status_code=200),
            )
        )
    monkeypatch.setattr(portal_discovery.time, "sleep", sleep_calls.append)

    discover_source_documents(
        output_path=tmp_path / "source_manifest.jsonl",
        diagnostics_path=tmp_path / "diagnostics.json",
        max_pages=2,
        request_delay_seconds=0.25,
        client=FakeClient(pages),
    )

    assert sleep_calls == [0.25]


def test_discovery_closes_owned_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = """
    <article>
      <a href="/he/departments/publications/reports/owned">פרסום</a>
      <a href="/BlobFolder/reports/owned/he/report.pdf">דוח</a>
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
    monkeypatch.setattr(portal_discovery, "GovilClient", lambda: client)

    discover_source_documents(
        output_path=tmp_path / "source_manifest.jsonl",
        diagnostics_path=tmp_path / "diagnostics.json",
        max_pages=1,
        request_delay_seconds=0,
    )

    assert client.closed is True


def test_http_diagnostics_detect_cloudflare_block() -> None:
    html = "<title>Attention Required! | Cloudflare</title>You have been blocked"

    assert is_blocked_response(403, html) is True
    assert is_blocked_response(200, "<html>ok</html>") is False


def test_govil_client_fetch_success_and_context_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_http_client = FakeHttpxClient(
        response=httpx.Response(
            200,
            text="<html>ok</html>",
            headers={
                "content-type": "text/html",
                "x-ignored": "ignored",
            },
            request=httpx.Request("GET", PAGE_URL),
        )
    )
    monkeypatch.setattr(
        govil_client.httpx,
        "Client",
        lambda **_kwargs: fake_http_client,
    )

    with GovilClient(timeout_seconds=1, user_agent="test-agent") as client:
        fetch = client.fetch(PAGE_URL)

    assert fake_http_client.closed is True
    assert fake_http_client.requested_urls == [PAGE_URL]
    assert fetch.html == "<html>ok</html>"
    assert fetch.diagnostic.status_code == 200
    assert fetch.diagnostic.response_headers == {"content-type": "text/html"}
    assert fetch.diagnostic.is_blocked is False


def test_govil_client_fetch_records_request_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_http_client = FakeHttpxClient(
        error=httpx.ConnectError(
            "network unavailable",
            request=httpx.Request("GET", PAGE_URL),
        )
    )
    monkeypatch.setattr(
        govil_client.httpx,
        "Client",
        lambda **_kwargs: fake_http_client,
    )

    client = GovilClient()
    fetch = client.fetch(PAGE_URL)

    assert fetch.html == ""
    assert fetch.diagnostic.error == "ConnectError"


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


def test_cli_version_callback_exits(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(typer.Exit):
        cli._version_callback(True)

    assert "welfare-inspections" in capsys.readouterr().out


def test_cli_discover_invokes_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "manifest.jsonl"
    diagnostics = tmp_path / "diagnostics.json"
    calls: list[dict[str, object]] = []

    def fake_discover_source_documents(**kwargs: object) -> tuple[list[object], object]:
        calls.append(kwargs)
        return [object(), object()], SimpleDiagnostics(stop_reason="max_pages")

    monkeypatch.setattr(
        cli,
        "discover_source_documents",
        fake_discover_source_documents,
    )

    cli.discover(
        output=output,
        diagnostics=diagnostics,
        max_pages=7,
        page_size=20,
        request_delay_seconds=0,
    )

    assert calls[0]["output_path"] == output
    assert calls[0]["diagnostics_path"] == diagnostics
    assert calls[0]["max_pages"] == 7
    assert (
        "Discovered 2 source records; stop_reason=max_pages"
        in capsys.readouterr().out
    )


def test_cli_main_returns_one_for_non_integer_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_app(**_kwargs: object) -> None:
        raise SystemExit("not an int")

    monkeypatch.setattr(cli, "app", fake_app)

    assert cli.main([]) == 1


def test_cli_main_returns_zero_when_app_does_not_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_app(**_kwargs: object) -> None:
        return None

    monkeypatch.setattr(cli, "app", fake_app)

    assert cli.main([]) == 0


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


class FakeHttpxClient:
    def __init__(
        self,
        *,
        response: httpx.Response | None = None,
        error: httpx.RequestError | None = None,
    ) -> None:
        self._response = response
        self._error = error
        self.closed = False
        self.requested_urls: list[str] = []

    def get(self, url: str) -> httpx.Response:
        self.requested_urls.append(url)
        if self._error is not None:
            raise self._error
        if self._response is None:
            raise AssertionError("FakeHttpxClient requires a response or error")
        return self._response

    def close(self) -> None:
        self.closed = True


class SimpleDiagnostics:
    def __init__(self, *, stop_reason: str) -> None:
        self.stop_reason = stop_reason
