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
    JsonFetch,
    PageFetch,
    is_blocked_response,
)
from welfare_inspections.collect.models import HttpDiagnostic
from welfare_inspections.collect.portal_discovery import discover_source_documents
from welfare_inspections.collect.portal_parser import (
    parse_dynamic_collector_config,
    parse_source_records,
    parse_structured_records,
)
from welfare_inspections.collect.settings import DiscoverySettings

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


def test_parse_invalid_date_returns_nullable_date() -> None:
    html = """
    <article>
      <a href="/he/departments/publications/reports/bad-date">פרסום</a>
      <time datetime="2024-02-31">31/02/2024</time>
      <a href="/BlobFolder/reports/bad-date/he/report.pdf">דוח</a>
    </article>
    """

    records = parse_source_records(
        html,
        page_url=PAGE_URL,
        http_status=200,
        response_headers={},
    )

    assert len(records) == 1
    assert records[0].source_published_at is None


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


def test_parse_multiple_fallback_page_records_keep_unique_pdf_ids() -> None:
    page_url = "https://www.gov.il/departments/dynamiccollectors?skip=0"
    html = """
    <div>
      <a href="/BlobFolder/reports/one/he/report.pdf">דוח ראשון</a>
      <a href="/BlobFolder/reports/two/he/report.pdf">דוח שני</a>
    </div>
    """

    records = parse_source_records(
        html,
        page_url=page_url,
        http_status=200,
        response_headers={},
    )

    assert len(records) == 2
    assert records[0].govil_item_url == page_url
    assert records[1].govil_item_url == page_url
    assert records[0].source_document_id != records[1].source_document_id


def test_parse_shared_container_records_keep_unique_pdf_ids() -> None:
    html = """
    <section>
      <a href="/he/departments/publications/reports/shared">פרסום</a>
      <a href="/BlobFolder/reports/shared/he/one.pdf">דוח ראשון</a>
      <a href="/BlobFolder/reports/shared/he/two.pdf">דוח שני</a>
    </section>
    """

    records = parse_source_records(
        html,
        page_url=PAGE_URL,
        http_status=200,
        response_headers={},
    )

    assert len(records) == 2
    assert records[0].govil_item_slug == "shared"
    assert records[1].govil_item_slug == "shared"
    assert records[0].source_document_id != records[1].source_document_id


def test_discovery_uses_structured_dynamic_collector_endpoint(
    tmp_path: Path,
) -> None:
    html = """
    <div ng-init="dynamicCtrl.Events.initCtrl({},0,
      'template-id','',10,'',[],'MultiAutoComplete','client-id')">
      <a href="{{ dynamicCtrl.Helpers.getFileSource(
        'https://www.gov.il/BlobFolder/dynamiccollectorresultitem/',
        item.UrlName,
        'he',
        file.FileName) }}"></a>
    </div>
    """
    endpoint_url = "https://www.gov.il/he/api/DynamicCollector"
    client = FakeClient(
        [
            PageFetch(
                url=PAGE_URL,
                html=html,
                diagnostic=HttpDiagnostic(url=PAGE_URL, status_code=200),
            )
        ],
        json_pages=[
            JsonFetch(
                url=endpoint_url,
                data={
                    "Results": [
                        {
                            "UrlName": "structured-one",
                            "Data": {
                                "report": [
                                    {
                                        "FileName": "one.pdf",
                                        "DisplayName": "דוח מובנה",
                                    }
                                ]
                            },
                        }
                    ],
                    "TotalResults": 1,
                },
                diagnostic=HttpDiagnostic(url=endpoint_url, status_code=200),
            )
        ],
    )

    records, diagnostics = discover_source_documents(
        output_path=tmp_path / "source_manifest.jsonl",
        diagnostics_path=tmp_path / "diagnostics.json",
        max_pages=1,
        request_delay_seconds=0,
        client=client,
    )

    assert len(records) == 1
    assert records[0].govil_item_slug == "structured-one"
    assert records[0].title == "דוח מובנה"
    assert records[0].pdf_url.endswith(
        "/BlobFolder/dynamiccollectorresultitem/structured-one/he/one.pdf"
    )
    assert client.json_requests == [
        (
            endpoint_url,
            {
                "DynamicTemplateID": "template-id",
                "QueryFilters": {"skip": {"Query": 0}},
                "From": 0,
                "ItemUrlName": None,
            },
            "client-id",
        )
    ]
    assert endpoint_url in diagnostics.attempted_urls


def test_structured_dynamic_collector_errors_stop_discovery(tmp_path: Path) -> None:
    html = """
    <div ng-init="dynamicCtrl.Events.initCtrl({},0,
      'template-id','',10,'',[],'MultiAutoComplete','client-id')"></div>
    """
    endpoint_url = "https://www.gov.il/he/api/DynamicCollector"
    client = FakeClient(
        [
            PageFetch(
                url=PAGE_URL,
                html=html,
                diagnostic=HttpDiagnostic(url=PAGE_URL, status_code=200),
            )
        ],
        json_pages=[
            JsonFetch(
                url=endpoint_url,
                data={},
                diagnostic=HttpDiagnostic(
                    url=endpoint_url,
                    error="ConnectError",
                ),
            )
        ],
    )

    records, diagnostics = discover_source_documents(
        output_path=tmp_path / "source_manifest.jsonl",
        diagnostics_path=tmp_path / "diagnostics.json",
        max_pages=1,
        request_delay_seconds=0,
        client=client,
    )

    assert records == []
    assert diagnostics.stop_reason == "http_error_or_empty_response"


def test_structured_dynamic_collector_block_stops_discovery(tmp_path: Path) -> None:
    html = """
    <div ng-init="dynamicCtrl.Events.initCtrl({},0,
      'template-id','',10,'',[],'MultiAutoComplete','client-id')"></div>
    """
    endpoint_url = "https://www.gov.il/he/api/DynamicCollector"
    client = FakeClient(
        [
            PageFetch(
                url=PAGE_URL,
                html=html,
                diagnostic=HttpDiagnostic(url=PAGE_URL, status_code=200),
            )
        ],
        json_pages=[
            JsonFetch(
                url=endpoint_url,
                data={},
                diagnostic=HttpDiagnostic(
                    url=endpoint_url,
                    status_code=403,
                    is_blocked=True,
                ),
            )
        ],
    )

    records, diagnostics = discover_source_documents(
        output_path=tmp_path / "source_manifest.jsonl",
        diagnostics_path=tmp_path / "diagnostics.json",
        max_pages=1,
        request_delay_seconds=0,
        client=client,
    )

    assert records == []
    assert diagnostics.stop_reason == "blocked_response"
    assert diagnostics.blocked_responses == 1


def test_dynamic_collector_config_rejects_malformed_init_values() -> None:
    assert parse_dynamic_collector_config("<div></div>", page_url=PAGE_URL) is None
    assert (
        parse_dynamic_collector_config(
            '<div ng-init="otherCtrl.Events.initCtrl()"></div>',
            page_url=PAGE_URL,
        )
        is None
    )
    assert (
        parse_dynamic_collector_config(
            '<div ng-init="dynamicCtrl.Events.initCtrl({},0)"></div>',
            page_url=PAGE_URL,
        )
        is None
    )
    assert (
        parse_dynamic_collector_config(
            "<div ng-init=\"dynamicCtrl.Events.initCtrl("
            "{},0,'','',10,'',[],'MultiAutoComplete','')\"></div>",
            page_url=PAGE_URL,
        )
        is None
    )


def test_dynamic_collector_config_handles_custom_endpoint_and_bad_page_size() -> None:
    config = parse_dynamic_collector_config(
        "<div ng-init=\"dynamicCtrl.Events.initCtrl("
        "{filters:['a,b']},0,'template-id','/custom/api','bad',"
        "'',[],'MultiAutoComplete','client-id')\"></div>",
        page_url=PAGE_URL,
    )

    assert config is not None
    assert config.endpoint_url == "/custom/api"
    assert config.items_per_page == 10


def test_dynamic_collector_config_handles_escaped_quoted_args() -> None:
    config = parse_dynamic_collector_config(
        "<div ng-init=\"dynamicCtrl.Events.initCtrl("
        "{label:'escaped\\\\\\' quote'},0,'template-id','',10,"
        "'',[],'MultiAutoComplete','client-id')\"></div>",
        page_url=PAGE_URL,
    )

    assert config is not None
    assert config.dynamic_template_id == "template-id"


def test_dynamic_collector_config_accepts_unquoted_string_args() -> None:
    config = parse_dynamic_collector_config(
        "<div ng-init=\"dynamicCtrl.Events.initCtrl("
        "{},0,templateId,'',10,'',[],'MultiAutoComplete',clientId)\"></div>",
        page_url=PAGE_URL,
    )

    assert config is not None
    assert config.dynamic_template_id == "templateId"
    assert config.x_client_id == "clientId"


def test_structured_records_skip_malformed_items_and_dedupe() -> None:
    records = parse_structured_records(
        {
            "Results": [
                "not an object",
                {"UrlName": "missing-data"},
                {"UrlName": "bad-file", "Data": {"report": ["not an object"]}},
                {"UrlName": "missing-name", "Data": {"report": [{}]}},
                {
                    "UrlName": "ok",
                    "Data": {
                        "report": [
                            {"FileName": "report.pdf", "DisplayName": "Report"},
                            {"FileName": "report.pdf", "DisplayName": "Report"},
                        ]
                    },
                },
            ]
        },
        page_url=PAGE_URL,
        endpoint_status=200,
        response_headers={},
    )

    assert len(records) == 1
    assert records[0].govil_item_slug == "ok"


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


def test_discovery_does_not_stop_on_same_text_with_new_hrefs(tmp_path: Path) -> None:
    first_html = """
    <article>
      <a href="/he/departments/publications/reports/same-title">פרסום</a>
      <a href="/BlobFolder/reports/same-title/he/one.pdf">דוח זהה</a>
    </article>
    """
    second_html = """
    <article>
      <a href="/he/departments/publications/reports/same-title">פרסום</a>
      <a href="/BlobFolder/reports/same-title/he/two.pdf">דוח זהה</a>
    </article>
    """
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
        max_pages=2,
        request_delay_seconds=0,
        client=client,
    )

    assert len(records) == 2
    assert diagnostics.stop_reason == "max_pages"


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
    assert fake_http_client.requested_urls == [PAGE_URL, PAGE_URL, PAGE_URL]


def test_govil_client_fetch_records_unexpected_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_http_client = FakeHttpxClient(error=ValueError("bad response"))
    monkeypatch.setattr(
        govil_client.httpx,
        "Client",
        lambda **_kwargs: fake_http_client,
    )

    client = GovilClient()
    fetch = client.fetch(PAGE_URL)

    assert fetch.html == ""
    assert fetch.diagnostic.error == "ValueError"
    assert fake_http_client.requested_urls == [PAGE_URL]


def test_govil_client_fetch_records_response_text_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_http_client = FakeHttpxClient(response=BadTextResponse())
    monkeypatch.setattr(
        govil_client.httpx,
        "Client",
        lambda **_kwargs: fake_http_client,
    )

    client = GovilClient()
    fetch = client.fetch(PAGE_URL)

    assert fetch.html == ""
    assert fetch.diagnostic.error == "ValueError"


def test_govil_client_post_json_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint_url = "https://www.gov.il/he/api/DynamicCollector"
    fake_http_client = FakeHttpxClient(
        post_response=httpx.Response(
            200,
            json={"Results": []},
            headers={"content-type": "application/json"},
            request=httpx.Request("POST", endpoint_url),
        )
    )
    monkeypatch.setattr(
        govil_client.httpx,
        "Client",
        lambda **_kwargs: fake_http_client,
    )

    client = GovilClient()
    fetch = client.post_json(endpoint_url, {"From": 0}, "client-id")

    assert fetch.data == {"Results": []}
    assert fetch.diagnostic.status_code == 200
    assert fetch.diagnostic.response_headers == {"content-type": "application/json"}
    assert fake_http_client.posted == [(endpoint_url, {"From": 0}, "client-id")]


def test_govil_client_post_json_records_request_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint_url = "https://www.gov.il/he/api/DynamicCollector"
    fake_http_client = FakeHttpxClient(
        post_error=httpx.ConnectError(
            "network unavailable",
            request=httpx.Request("POST", endpoint_url),
        )
    )
    monkeypatch.setattr(
        govil_client.httpx,
        "Client",
        lambda **_kwargs: fake_http_client,
    )

    client = GovilClient()
    fetch = client.post_json(endpoint_url, {"From": 0}, "client-id")

    assert fetch.data == {}
    assert fetch.diagnostic.error == "ConnectError"
    assert len(fake_http_client.posted) == 3


def test_govil_client_post_json_records_unexpected_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint_url = "https://www.gov.il/he/api/DynamicCollector"
    fake_http_client = FakeHttpxClient(post_error=ValueError("bad response"))
    monkeypatch.setattr(
        govil_client.httpx,
        "Client",
        lambda **_kwargs: fake_http_client,
    )

    client = GovilClient()
    fetch = client.post_json(endpoint_url, {"From": 0}, "client-id")

    assert fetch.data == {}
    assert fetch.diagnostic.error == "ValueError"
    assert len(fake_http_client.posted) == 1


def test_govil_client_post_json_records_response_decode_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint_url = "https://www.gov.il/he/api/DynamicCollector"
    fake_http_client = FakeHttpxClient(post_response=BadJsonResponse(endpoint_url))
    monkeypatch.setattr(
        govil_client.httpx,
        "Client",
        lambda **_kwargs: fake_http_client,
    )

    client = GovilClient()
    fetch = client.post_json(endpoint_url, {"From": 0}, "client-id")

    assert fetch.data == {}
    assert fetch.diagnostic.error == "ValueError"


def test_govil_client_post_json_non_200_keeps_empty_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint_url = "https://www.gov.il/he/api/DynamicCollector"
    fake_http_client = FakeHttpxClient(
        post_response=httpx.Response(
            500,
            text="server error",
            request=httpx.Request("POST", endpoint_url),
        )
    )
    monkeypatch.setattr(
        govil_client.httpx,
        "Client",
        lambda **_kwargs: fake_http_client,
    )

    client = GovilClient()
    fetch = client.post_json(endpoint_url, {"From": 0}, "client-id")

    assert fetch.data == {}
    assert fetch.diagnostic.status_code == 500


def test_govil_client_post_json_non_object_payload_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint_url = "https://www.gov.il/he/api/DynamicCollector"
    fake_http_client = FakeHttpxClient(
        post_response=httpx.Response(
            200,
            json=[],
            request=httpx.Request("POST", endpoint_url),
        )
    )
    monkeypatch.setattr(
        govil_client.httpx,
        "Client",
        lambda **_kwargs: fake_http_client,
    )

    client = GovilClient()
    fetch = client.post_json(endpoint_url, {"From": 0}, "client-id")

    assert fetch.data == {}


def test_retry_error_name_handles_unexpected_retry_shapes() -> None:
    assert govil_client._retry_error_name(BrokenRetryError()) == "BrokenRetryError"
    assert govil_client._retry_error_name(EmptyRetryError()) == "EmptyRetryError"


def test_discovery_settings_read_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WELFARE_INSPECTIONS_DISCOVERY_MAX_PAGES", "12")
    monkeypatch.setenv("WELFARE_INSPECTIONS_DISCOVERY_PAGE_SIZE", "25")
    monkeypatch.setenv("WELFARE_INSPECTIONS_DISCOVERY_REQUEST_DELAY_SECONDS", "0.5")

    settings = DiscoverySettings()

    assert settings.max_pages == 12
    assert settings.page_size == 25
    assert settings.request_delay_seconds == 0.5


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


def test_cli_discover_reads_settings_at_command_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "manifest.jsonl"
    diagnostics = tmp_path / "diagnostics.json"
    calls: list[dict[str, object]] = []

    def fake_discover_source_documents(**kwargs: object) -> tuple[list[object], object]:
        calls.append(kwargs)
        return [], SimpleDiagnostics(stop_reason="empty_page")

    monkeypatch.setenv("WELFARE_INSPECTIONS_DISCOVERY_MAX_PAGES", "9")
    monkeypatch.setenv("WELFARE_INSPECTIONS_DISCOVERY_PAGE_SIZE", "30")
    monkeypatch.setenv("WELFARE_INSPECTIONS_DISCOVERY_REQUEST_DELAY_SECONDS", "0.0")
    monkeypatch.setattr(
        cli,
        "discover_source_documents",
        fake_discover_source_documents,
    )

    cli.discover(output=output, diagnostics=diagnostics)

    assert calls[0]["max_pages"] == 9
    assert calls[0]["page_size"] == 30
    assert calls[0]["request_delay_seconds"] == 0.0


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
    def __init__(
        self,
        pages: list[PageFetch],
        *,
        json_pages: list[JsonFetch] | None = None,
    ) -> None:
        self._pages = pages
        self._json_pages = json_pages or []
        self.urls: list[str] = []
        self.json_requests: list[tuple[str, dict[str, object], str]] = []
        self.closed = False

    def fetch(self, url: str) -> PageFetch:
        self.urls.append(url)
        return self._pages.pop(0)

    def post_json(
        self,
        url: str,
        payload: dict[str, object],
        x_client_id: str,
    ) -> JsonFetch:
        self.json_requests.append((url, payload, x_client_id))
        return self._json_pages.pop(0)

    def close(self) -> None:
        self.closed = True


class FakeHttpxClient:
    def __init__(
        self,
        *,
        response: httpx.Response | None = None,
        error: Exception | None = None,
        post_response: httpx.Response | None = None,
        post_error: Exception | None = None,
    ) -> None:
        self._response = response
        self._error = error
        self._post_response = post_response
        self._post_error = post_error
        self.closed = False
        self.requested_urls: list[str] = []
        self.posted: list[tuple[str, dict[str, object], str | None]] = []

    def get(self, url: str) -> httpx.Response:
        self.requested_urls.append(url)
        if self._error is not None:
            raise self._error
        if self._response is None:
            raise AssertionError("FakeHttpxClient requires a response or error")
        return self._response

    def post(
        self,
        url: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
    ) -> httpx.Response:
        self.posted.append((url, json, headers.get("x-client-id")))
        if self._post_error is not None:
            raise self._post_error
        if self._post_response is None:
            raise AssertionError("FakeHttpxClient requires a post response or error")
        return self._post_response

    def close(self) -> None:
        self.closed = True


class SimpleDiagnostics:
    def __init__(self, *, stop_reason: str) -> None:
        self.stop_reason = stop_reason


class BadTextResponse:
    url = PAGE_URL
    status_code = 200
    headers = httpx.Headers()

    @property
    def text(self) -> str:
        raise ValueError("bad response text")


class BadJsonResponse:
    status_code = 200
    headers = httpx.Headers()

    def __init__(self, url: str) -> None:
        self.url = url

    @property
    def text(self) -> str:
        return "{}"

    def json(self) -> dict[str, object]:
        raise ValueError("bad json")


class BrokenRetryAttempt:
    def exception(self) -> Exception | None:
        raise ValueError("bad retry state")


class BrokenRetryError(Exception):
    last_attempt = BrokenRetryAttempt()


class EmptyRetryAttempt:
    def exception(self) -> Exception | None:
        return None


class EmptyRetryError(Exception):
    last_attempt = EmptyRetryAttempt()
