from __future__ import annotations

import csv
import json
import subprocess
import sys
import types
from builtins import __import__ as real_import
from pathlib import Path

import click
import pytest

from welfare_inspections import cli
from welfare_inspections.collect import report_index as report_index_module
from welfare_inspections.collect.govil_client import JsonFetch, PageFetch
from welfare_inspections.collect.models import HttpDiagnostic
from welfare_inspections.collect.report_index import (
    BrowserCollectionResult,
    BrowserCollectionUnavailable,
    ReportIndexRunDiagnostics,
    collect_report_index,
    collect_report_index_from_browser,
    parse_report_index_dom_records,
    parse_structured_report_index_records,
)

PAGE_URL = (
    "https://www.gov.il/he/departments/dynamiccollectors/"
    "molsa-supervision-frames-reports?skip=0"
)
SHELL_HTML = """
<div ng-init="dynamicCtrl.Events.initCtrl({},0,
  'template-id','https://www.gov.il/he/api/DynamicCollector',10,'',[],
  'MultiAutoComplete','client-id')"></div>
"""


def test_collect_report_index_uses_complete_structured_response(
    tmp_path: Path,
) -> None:
    client = FakeClient(
        pages=[
            PageFetch(
                url=PAGE_URL,
                html=SHELL_HTML,
                diagnostic=HttpDiagnostic(url=PAGE_URL, status_code=200),
            )
        ],
        json_pages=[
            JsonFetch(
                url="https://www.gov.il/he/api/DynamicCollector",
                data=_structured_payload(),
                diagnostic=HttpDiagnostic(
                    url="https://www.gov.il/he/api/DynamicCollector",
                    status_code=200,
                ),
            )
        ],
    )

    records, diagnostics = collect_report_index(
        output_csv_path=tmp_path / "outputs" / "reports_index.csv",
        output_jsonl_path=tmp_path / "outputs" / "reports_index.jsonl",
        diagnostics_path=tmp_path / "outputs" / "report_index_diagnostics.json",
        max_pages=1,
        request_delay_seconds=0,
        client=client,
    )

    assert len(records) == 1
    assert records[0].institution_name == "בית הדר"
    assert records[0].administration == "מוגבלויות"
    assert records[0].district == "ירושלים"
    assert records[0].survey_date == "13/02/2024"
    assert diagnostics.source_path_used == "structured_dynamic_collector"
    assert diagnostics.field_coverage_by_path["structured_dynamic_collector"][
        "שם מסגרת"
    ] == {"present": 1, "total": 1}
    assert diagnostics.page_record_counts[PAGE_URL] == 1
    assert diagnostics.source_total_results_by_path["structured_dynamic_collector"] == 1


def test_collect_report_index_falls_back_when_structured_fields_are_incomplete(
    tmp_path: Path,
) -> None:
    structured = _structured_payload()
    del structured["Results"][0]["Data"]["מחוז"]
    client = FakeClient(
        pages=[
            PageFetch(
                url=PAGE_URL,
                html=SHELL_HTML,
                diagnostic=HttpDiagnostic(url=PAGE_URL, status_code=200),
            )
        ],
        json_pages=[
            JsonFetch(
                url="https://www.gov.il/he/api/DynamicCollector",
                data=structured,
                diagnostic=HttpDiagnostic(
                    url="https://www.gov.il/he/api/DynamicCollector",
                    status_code=200,
                ),
            )
        ],
    )

    def fake_browser_collector(
        start_url: str,
        max_pages: int,
        page_size: int,
        request_delay_seconds: float,
        collection_run_id: str,
    ) -> BrowserCollectionResult:
        assert page_size == 10
        records = parse_report_index_dom_records(
            _dom_html(),
            page_url=start_url,
            source_skip=0,
            collection_run_id=collection_run_id,
        )
        diagnostics = ReportIndexRunDiagnostics(
            start_url=start_url,
            collection_run_id=collection_run_id,
            source_path_used="browser_dom",
            source_path_attempted=["browser_dom"],
            page_record_counts={start_url: len(records)},
            output_csv_path=str(tmp_path / "outputs" / "reports_index.csv"),
            output_jsonl_path=str(tmp_path / "outputs" / "reports_index.jsonl"),
            diagnostics_path=str(
                tmp_path / "outputs" / "report_index_diagnostics.json"
            ),
        )
        return BrowserCollectionResult(records=records, diagnostics=diagnostics)

    records, diagnostics = collect_report_index(
        output_csv_path=tmp_path / "outputs" / "reports_index.csv",
        output_jsonl_path=tmp_path / "outputs" / "reports_index.jsonl",
        diagnostics_path=tmp_path / "outputs" / "report_index_diagnostics.json",
        max_pages=1,
        page_size=99,
        request_delay_seconds=0,
        client=client,
        browser_collector=fake_browser_collector,
    )

    assert len(records) == 1
    assert records[0].district == "ירושלים"
    assert diagnostics.source_path_used == "browser_dom"
    assert diagnostics.source_path_attempted == [
        "structured_dynamic_collector",
        "browser_dom",
    ]
    assert any("omitted required card fields" in note for note in diagnostics.notes)


def test_collect_report_index_closes_owned_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _complete_client()

    def fake_client_factory() -> FakeClient:
        return client

    monkeypatch.setattr(report_index_module, "GovilClient", fake_client_factory)

    collect_report_index(
        output_csv_path=tmp_path / "outputs" / "reports_index.csv",
        output_jsonl_path=tmp_path / "outputs" / "reports_index.jsonl",
        diagnostics_path=tmp_path / "outputs" / "report_index_diagnostics.json",
        max_pages=1,
        request_delay_seconds=0,
    )

    assert client.closed is True


@pytest.mark.parametrize(
    ("page_fetch", "json_fetch", "expected_stop", "expected_note"),
    [
        (
            PageFetch(
                url=PAGE_URL,
                html="blocked",
                diagnostic=HttpDiagnostic(
                    url=PAGE_URL,
                    status_code=403,
                    is_blocked=True,
                ),
            ),
            None,
            "blocked_response",
            "structured_path_blocked_before_fallback",
        ),
        (
            PageFetch(
                url=PAGE_URL,
                html="",
                diagnostic=HttpDiagnostic(url=PAGE_URL, status_code=500),
            ),
            None,
            "http_error_or_empty_response",
            "structured_path_unavailable_before_fallback",
        ),
        (
            PageFetch(
                url=PAGE_URL,
                html="<html></html>",
                diagnostic=HttpDiagnostic(url=PAGE_URL, status_code=200),
            ),
            None,
            "missing_dynamic_collector_config",
            "structured_config_missing_before_fallback",
        ),
        (
            PageFetch(
                url=PAGE_URL,
                html=SHELL_HTML,
                diagnostic=HttpDiagnostic(url=PAGE_URL, status_code=200),
            ),
            JsonFetch(
                url="https://www.gov.il/he/api/DynamicCollector",
                data={},
                diagnostic=HttpDiagnostic(
                    url="https://www.gov.il/he/api/DynamicCollector",
                    status_code=403,
                    is_blocked=True,
                ),
            ),
            "blocked_response",
            "structured_endpoint_blocked_before_fallback",
        ),
        (
            PageFetch(
                url=PAGE_URL,
                html=SHELL_HTML,
                diagnostic=HttpDiagnostic(url=PAGE_URL, status_code=200),
            ),
            JsonFetch(
                url="https://www.gov.il/he/api/DynamicCollector",
                data={},
                diagnostic=HttpDiagnostic(
                    url="https://www.gov.il/he/api/DynamicCollector",
                    error="ConnectError",
                ),
            ),
            "http_error_or_empty_response",
            "structured_endpoint_error_before_fallback",
        ),
        (
            PageFetch(
                url=PAGE_URL,
                html=SHELL_HTML,
                diagnostic=HttpDiagnostic(url=PAGE_URL, status_code=200),
            ),
            JsonFetch(
                url="https://www.gov.il/he/api/DynamicCollector",
                data={},
                diagnostic=HttpDiagnostic(
                    url="https://www.gov.il/he/api/DynamicCollector",
                    status_code=500,
                ),
            ),
            "http_error_or_empty_response",
            "structured_endpoint_error_before_fallback",
        ),
    ],
)
def test_structured_failures_fall_back_with_diagnostics(
    tmp_path: Path,
    page_fetch: PageFetch,
    json_fetch: JsonFetch | None,
    expected_stop: str,
    expected_note: str,
) -> None:
    json_pages = [] if json_fetch is None else [json_fetch]
    client = FakeClient(pages=[page_fetch], json_pages=json_pages)

    def fake_browser_collector(
        start_url: str,
        max_pages: int,
        page_size: int,
        request_delay_seconds: float,
        collection_run_id: str,
    ) -> BrowserCollectionResult:
        diagnostics = ReportIndexRunDiagnostics(
            start_url=start_url,
            collection_run_id=collection_run_id,
            source_path_used="browser_dom",
            source_path_attempted=["browser_dom"],
            stop_reason="browser_completed",
            output_csv_path="placeholder.csv",
            output_jsonl_path="placeholder.jsonl",
            diagnostics_path="placeholder.json",
        )
        return BrowserCollectionResult(records=[], diagnostics=diagnostics)

    _, diagnostics = collect_report_index(
        output_csv_path=tmp_path / "outputs" / "reports_index.csv",
        output_jsonl_path=tmp_path / "outputs" / "reports_index.jsonl",
        diagnostics_path=tmp_path / "outputs" / "report_index_diagnostics.json",
        max_pages=1,
        request_delay_seconds=0,
        client=client,
        browser_collector=fake_browser_collector,
    )

    assert diagnostics.source_path_used == "browser_dom"
    assert expected_note in diagnostics.notes
    assert diagnostics.output_csv_path == str(
        tmp_path / "outputs" / "reports_index.csv"
    )
    assert diagnostics.stop_reason == "browser_completed"
    if expected_stop == "blocked_response":
        assert diagnostics.blocked_responses == 1


def test_collect_report_index_records_empty_structured_page(tmp_path: Path) -> None:
    client = FakeClient(
        pages=[
            PageFetch(
                url=PAGE_URL,
                html=SHELL_HTML,
                diagnostic=HttpDiagnostic(url=PAGE_URL, status_code=200),
            )
        ],
        json_pages=[
            JsonFetch(
                url="https://www.gov.il/he/api/DynamicCollector",
                data={"Results": [], "TotalResults": 0},
                diagnostic=HttpDiagnostic(
                    url="https://www.gov.il/he/api/DynamicCollector",
                    status_code=200,
                ),
            )
        ],
    )

    records, diagnostics = collect_report_index(
        output_csv_path=tmp_path / "outputs" / "reports_index.csv",
        output_jsonl_path=tmp_path / "outputs" / "reports_index.jsonl",
        diagnostics_path=tmp_path / "outputs" / "report_index_diagnostics.json",
        max_pages=1,
        request_delay_seconds=0,
        client=client,
    )

    assert records == []
    assert diagnostics.stop_reason == "empty_page"
    assert diagnostics.source_path_used == "structured_dynamic_collector"
    assert diagnostics.source_total_results_by_path["structured_dynamic_collector"] == 0


def test_collect_report_index_delays_between_structured_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    second_url = PAGE_URL.replace("skip=0", "skip=10")
    client = FakeClient(
        pages=[
            PageFetch(
                url=PAGE_URL,
                html=SHELL_HTML,
                diagnostic=HttpDiagnostic(url=PAGE_URL, status_code=200),
            ),
            PageFetch(
                url=second_url,
                html=SHELL_HTML,
                diagnostic=HttpDiagnostic(url=second_url, status_code=200),
            ),
        ],
        json_pages=[
            JsonFetch(
                url="https://www.gov.il/he/api/DynamicCollector",
                data=_structured_payload(),
                diagnostic=HttpDiagnostic(
                    url="https://www.gov.il/he/api/DynamicCollector",
                    status_code=200,
                ),
            ),
            JsonFetch(
                url="https://www.gov.il/he/api/DynamicCollector",
                data={"Results": [], "TotalResults": 1},
                diagnostic=HttpDiagnostic(
                    url="https://www.gov.il/he/api/DynamicCollector",
                    status_code=200,
                ),
            ),
        ],
    )
    sleeps: list[float] = []
    monkeypatch.setattr(report_index_module.time, "sleep", sleeps.append)

    collect_report_index(
        output_csv_path=tmp_path / "outputs" / "reports_index.csv",
        output_jsonl_path=tmp_path / "outputs" / "reports_index.jsonl",
        diagnostics_path=tmp_path / "outputs" / "report_index_diagnostics.json",
        max_pages=2,
        page_size=99,
        request_delay_seconds=0.25,
        client=client,
    )

    assert sleeps == [0.25]
    assert client.urls == [PAGE_URL, second_url]


def test_collect_report_index_writes_diagnostics_when_browser_fallback_fails(
    tmp_path: Path,
) -> None:
    structured = _structured_payload()
    del structured["Results"][0]["Data"]["מחוז"]
    client = FakeClient(
        pages=[
            PageFetch(
                url=PAGE_URL,
                html=SHELL_HTML,
                diagnostic=HttpDiagnostic(url=PAGE_URL, status_code=200),
            )
        ],
        json_pages=[
            JsonFetch(
                url="https://www.gov.il/he/api/DynamicCollector",
                data=structured,
                diagnostic=HttpDiagnostic(
                    url="https://www.gov.il/he/api/DynamicCollector",
                    status_code=200,
                ),
            )
        ],
    )

    def failing_browser_collector(
        start_url: str,
        max_pages: int,
        page_size: int,
        request_delay_seconds: float,
        collection_run_id: str,
    ) -> BrowserCollectionResult:
        raise BrowserCollectionUnavailable("playwright missing")

    diagnostics_path = tmp_path / "outputs" / "report_index_diagnostics.json"
    with pytest.raises(BrowserCollectionUnavailable, match="playwright missing"):
        collect_report_index(
            output_csv_path=tmp_path / "outputs" / "reports_index.csv",
            output_jsonl_path=tmp_path / "outputs" / "reports_index.jsonl",
            diagnostics_path=diagnostics_path,
            max_pages=1,
            request_delay_seconds=0,
            client=client,
            browser_collector=failing_browser_collector,
        )

    diagnostics_payload = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    assert diagnostics_payload["source_path_used"] == "browser_dom"
    assert diagnostics_payload["stop_reason"] == "browser_fallback_error"
    assert diagnostics_payload["finished_at"] is not None
    assert "browser_dom" in diagnostics_payload["source_path_attempted"]
    assert not (tmp_path / "outputs" / "reports_index.csv").exists()


def test_report_index_outputs_csv_order_and_jsonl_provenance(tmp_path: Path) -> None:
    records, diagnostics = collect_report_index(
        output_csv_path=tmp_path / "outputs" / "reports_index.csv",
        output_jsonl_path=tmp_path / "outputs" / "reports_index.jsonl",
        diagnostics_path=tmp_path / "outputs" / "report_index_diagnostics.json",
        max_pages=1,
        request_delay_seconds=0,
        client=_complete_client(),
    )

    with (tmp_path / "outputs" / "reports_index.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    jsonl_rows = [
        json.loads(line)
        for line in (tmp_path / "outputs" / "reports_index.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert reader.fieldnames == [
        "שם מסגרת",
        "סוג מסגרת",
        "סמל מסגרת",
        "מינהל",
        "מחוז",
        "תאריך ביצוע",
    ]
    assert rows == [
        {
            "שם מסגרת": "בית הדר",
            "סוג מסגרת": "הוסטל",
            "סמל מסגרת": "12345",
            "מינהל": "מוגבלויות",
            "מחוז": "ירושלים",
            "תאריך ביצוע": "13/02/2024",
        }
    ]
    assert jsonl_rows[0]["שם מסגרת"] == "בית הדר"
    assert jsonl_rows[0]["report_index_id"] == records[0].report_index_id
    assert jsonl_rows[0]["source_record_id"] == records[0].source_record_id
    assert jsonl_rows[0]["govil_item_url"].endswith("DCRI_UrlName=report-one")
    assert jsonl_rows[0]["pdf_url"].endswith(
        "/BlobFolder/dynamiccollectorresultitem/report-one/he/report.pdf"
    )
    assert jsonl_rows[0]["collection_run_id"] == diagnostics.collection_run_id
    assert jsonl_rows[0]["collector_version"].startswith("report-index-")


def test_report_index_diagnostics_cover_duplicates_missing_fields_and_bad_dates(
    tmp_path: Path,
) -> None:
    payload = _structured_payload()
    payload["Results"].append(payload["Results"][0])
    payload["Results"].append(
        {
            "UrlName": "missing-fields",
            "Data": {
                "שם מסגרת": "בית חסר",
                "סוג מסגרת": "הוסטל",
                "סמל מסגרת": "99999",
                "מינהל": "מוגבלויות",
                "מחוז": "צפון",
                "תאריך ביצוע": "אתמול",
                "report": [{"FileName": "missing.pdf"}],
            },
        }
    )
    client = FakeClient(
        pages=[
            PageFetch(
                url=PAGE_URL,
                html=SHELL_HTML,
                diagnostic=HttpDiagnostic(url=PAGE_URL, status_code=200),
            )
        ],
        json_pages=[
            JsonFetch(
                url="https://www.gov.il/he/api/DynamicCollector",
                data=payload,
                diagnostic=HttpDiagnostic(
                    url="https://www.gov.il/he/api/DynamicCollector",
                    status_code=200,
                ),
            )
        ],
    )

    records, diagnostics = collect_report_index(
        output_csv_path=tmp_path / "outputs" / "reports_index.csv",
        output_jsonl_path=tmp_path / "outputs" / "reports_index.jsonl",
        diagnostics_path=tmp_path / "outputs" / "report_index_diagnostics.json",
        max_pages=1,
        request_delay_seconds=0,
        client=client,
    )

    payload = json.loads(
        (tmp_path / "outputs" / "report_index_diagnostics.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(records) == 2
    assert diagnostics.duplicate_id_records == 1
    assert diagnostics.malformed_date_text_records == 1
    assert payload["record_diagnostics"][1]["status"] == "duplicate_report_index_id"
    assert payload["record_diagnostics"][2]["malformed_date_text"] == "אתמול"
    assert payload["field_coverage_by_path"]["structured_dynamic_collector"][
        "תאריך ביצוע"
    ] == {"present": 2, "total": 2}


def test_report_index_diagnostics_cover_missing_fields_after_browser_fallback(
    tmp_path: Path,
) -> None:
    structured = _structured_payload()
    del structured["Results"][0]["Data"]["מחוז"]
    client = FakeClient(
        pages=[
            PageFetch(
                url=PAGE_URL,
                html=SHELL_HTML,
                diagnostic=HttpDiagnostic(url=PAGE_URL, status_code=200),
            )
        ],
        json_pages=[
            JsonFetch(
                url="https://www.gov.il/he/api/DynamicCollector",
                data=structured,
                diagnostic=HttpDiagnostic(
                    url="https://www.gov.il/he/api/DynamicCollector",
                    status_code=200,
                ),
            )
        ],
    )

    def fake_browser_collector(
        start_url: str,
        max_pages: int,
        page_size: int,
        request_delay_seconds: float,
        collection_run_id: str,
    ) -> BrowserCollectionResult:
        records = parse_report_index_dom_records(
            """
            <article>
              <a href="/BlobFolder/report/he/report.pdf">PDF</a>
              <div>שם מסגרת: בית חסר</div>
              <div>סוג מסגרת: הוסטל</div>
              <div>סמל מסגרת: 99999</div>
              <div>מינהל: מוגבלויות</div>
              <div>תאריך ביצוע: 13/02/2024</div>
            </article>
            """,
            page_url=start_url,
            source_skip=0,
            collection_run_id=collection_run_id,
        )
        diagnostics = ReportIndexRunDiagnostics(
            start_url=start_url,
            collection_run_id=collection_run_id,
            source_path_used="browser_dom",
            source_path_attempted=["browser_dom"],
            output_csv_path=str(tmp_path / "outputs" / "reports_index.csv"),
            output_jsonl_path=str(tmp_path / "outputs" / "reports_index.jsonl"),
            diagnostics_path=str(
                tmp_path / "outputs" / "report_index_diagnostics.json"
            ),
        )
        return BrowserCollectionResult(records=records, diagnostics=diagnostics)

    _, diagnostics = collect_report_index(
        output_csv_path=tmp_path / "outputs" / "reports_index.csv",
        output_jsonl_path=tmp_path / "outputs" / "reports_index.jsonl",
        diagnostics_path=tmp_path / "outputs" / "report_index_diagnostics.json",
        max_pages=1,
        request_delay_seconds=0,
        client=client,
        browser_collector=fake_browser_collector,
    )

    assert diagnostics.missing_field_records == 1
    assert diagnostics.record_diagnostics[0].status == "missing_required_visible_fields"
    assert diagnostics.record_diagnostics[0].missing_fields == ["מחוז"]


def test_collect_report_index_rejects_builder_repo_non_outputs_paths() -> None:
    from welfare_inspections.collect import local_outputs

    with pytest.raises(ValueError, match="outputs/"):
        collect_report_index(
            output_csv_path=local_outputs.REPO_ROOT / "docs" / "reports_index.csv",
            output_jsonl_path=local_outputs.REPO_ROOT
            / "outputs"
            / "report_index"
            / "reports_index.jsonl",
            diagnostics_path=local_outputs.REPO_ROOT
            / "outputs"
            / "report_index"
            / "report_index_diagnostics.json",
        )


def test_parse_structured_report_index_records_skips_malformed_items() -> None:
    records = parse_structured_report_index_records(
        {
            "Results": [
                "not-a-dict",
                {
                    "Data": {
                        "fields": [
                            {"Label": "שם מסגרת", "Value": "בית תוויות"},
                            {"Label": "סוג מסגרת", "Value": "הוסטל"},
                            {"Label": "סמל מסגרת", "Value": "777"},
                            {"Label": "מינהל", "Value": "מוגבלויות"},
                            {"Label": "מחוז", "Value": "מרכז"},
                            {"Label": "תאריך ביצוע", "Value": "01/03/2024"},
                            {"Label": "קישור", "Value": "/BlobFolder/x/he/file.pdf"},
                        ]
                    }
                },
            ]
        },
        page_url=PAGE_URL,
        source_skip=0,
        collection_run_id="run-test",
    )

    assert len(records) == 1
    assert records[0].institution_name == "בית תוויות"
    assert records[0].govil_item_url == PAGE_URL
    assert records[0].pdf_url == "https://www.gov.il/BlobFolder/x/he/file.pdf"


def test_parse_structured_report_index_records_handles_missing_pdf_url() -> None:
    records = parse_structured_report_index_records(
        {
            "Results": [
                {
                    "UrlName": "no-pdf",
                    "Data": {
                        "שם מסגרת": "בית ללא קובץ",
                        "סוג מסגרת": "הוסטל",
                        "סמל מסגרת": "888",
                        "מינהל": "מוגבלויות",
                        "מחוז": "דרום",
                        "תאריך ביצוע": "04/03/2024",
                        "report": ["not-a-file-object"],
                    },
                },
            ]
        },
        page_url=PAGE_URL,
        source_skip=0,
        collection_run_id="run-no-pdf",
    )

    assert len(records) == 1
    assert records[0].pdf_url is None
    assert records[0].institution_name == "בית ללא קובץ"


def test_parse_report_index_dom_records_handles_attributes_and_missing_links() -> None:
    records = parse_report_index_dom_records(
        """
        <section>
          <article>
            <a href="/he/departments/publications/reports/item">פריט</a>
            <span aria-label="שם מסגרת: בית נגיש">שם</span>
            <span title="סוג מסגרת: הוסטל">סוג</span>
            <span data-label="סמל מסגרת: 555">סמל</span>
            <span data-value="מינהל מוגבלויות">מינהל</span>
            <span>מחוז מרכז</span>
            <span>תאריך ביצוע 02/03/2024</span>
          </article>
        </section>
        """,
        page_url=PAGE_URL,
        source_skip=0,
        collection_run_id="run-dom",
    )

    assert len(records) == 1
    assert records[0].institution_name == "בית נגיש"
    assert records[0].institution_type == "הוסטל"
    assert records[0].institution_symbol == "555"
    assert records[0].administration == "מוגבלויות"
    assert records[0].district == "מרכז"
    assert records[0].survey_date == "02/03/2024"
    assert records[0].pdf_url is None
    assert records[0].govil_item_url == (
        "https://www.gov.il/he/departments/publications/reports/item"
    )


def test_parse_report_index_dom_records_ignores_cards_without_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    soup = report_index_module.BeautifulSoup(
        "<article><a href='/x.pdf'>PDF</a></article>",
        "lxml",
    )
    empty_card = soup.find("article")
    assert empty_card is not None
    monkeypatch.setattr(
        report_index_module,
        "_dom_candidate_cards",
        lambda _soup: [empty_card],
    )

    records = parse_report_index_dom_records(
        "<article><a href='/x.pdf'>PDF</a></article>",
        page_url=PAGE_URL,
        source_skip=0,
        collection_run_id="run-empty",
    )

    assert records == []


def test_collect_report_index_from_browser_handles_empty_and_max_page_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        sys.modules,
        "playwright",
        types.ModuleType("playwright"),
    )
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: FakePlaywrightContext(
        ["<article><a href='/x'>no fields</a></article>"]
    )
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)

    empty_result = collect_report_index_from_browser(
        PAGE_URL,
        max_pages=2,
        page_size=10,
        request_delay_seconds=0,
        collection_run_id="run-browser-empty",
    )

    assert empty_result.records == []
    assert empty_result.diagnostics.stop_reason == "empty_page"

    sync_api.sync_playwright = lambda: FakePlaywrightContext([_dom_html()])
    max_page_result = collect_report_index_from_browser(
        PAGE_URL,
        max_pages=1,
        page_size=10,
        request_delay_seconds=0,
        collection_run_id="run-browser-max",
    )

    assert len(max_page_result.records) == 1
    assert max_page_result.diagnostics.stop_reason == "max_pages"
    assert max_page_result.diagnostics.field_coverage_by_path["browser_dom"][
        "שם מסגרת"
    ] == {"present": 1, "total": 1}


def test_collect_report_index_from_browser_delays_between_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: FakePlaywrightContext([_dom_html(), _dom_html()])
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)
    sleeps: list[float] = []
    monkeypatch.setattr(report_index_module.time, "sleep", sleeps.append)

    result = collect_report_index_from_browser(
        PAGE_URL,
        max_pages=2,
        page_size=10,
        request_delay_seconds=0.5,
        collection_run_id="run-browser-delay",
    )

    assert len(result.records) == 2
    assert sleeps == [0.5]


def test_collect_report_index_from_browser_reports_missing_playwright(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_import(
        name: str,
        globals: object | None = None,
        locals: object | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "playwright.sync_api":
            raise ImportError("no playwright")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)

    with pytest.raises(BrowserCollectionUnavailable, match="Playwright"):
        collect_report_index_from_browser(
            PAGE_URL,
            max_pages=1,
            page_size=10,
            request_delay_seconds=0,
            collection_run_id="run-no-browser",
        )


def test_cli_collect_report_index_invokes_collector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, object]] = []

    def fake_collect_report_index_layer(
        **kwargs: object,
    ) -> tuple[list[object], object]:
        calls.append(kwargs)
        return [object(), object()], SimpleReportIndexDiagnostics()

    monkeypatch.setattr(
        cli,
        "collect_report_index_layer",
        fake_collect_report_index_layer,
    )

    cli.collect_report_index(
        output_csv=tmp_path / "reports.csv",
        output_jsonl=tmp_path / "reports.jsonl",
        diagnostics=tmp_path / "diagnostics.json",
        start_url=PAGE_URL,
        max_pages=2,
        page_size=10,
        request_delay_seconds=0,
    )

    assert calls[0]["output_csv_path"] == tmp_path / "reports.csv"
    assert calls[0]["output_jsonl_path"] == tmp_path / "reports.jsonl"
    assert calls[0]["diagnostics_path"] == tmp_path / "diagnostics.json"
    assert "Collected 2 report-index records" in capsys.readouterr().out


def test_cli_collect_report_index_handles_browser_fallback_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_collect_report_index_layer(
        **kwargs: object,
    ) -> tuple[list[object], object]:
        raise BrowserCollectionUnavailable("browser unavailable")

    monkeypatch.setattr(
        cli,
        "collect_report_index_layer",
        fail_collect_report_index_layer,
    )

    with pytest.raises(click.exceptions.Exit) as exc_info:
        cli.collect_report_index(
            output_csv=tmp_path / "reports.csv",
            output_jsonl=tmp_path / "reports.jsonl",
            diagnostics=tmp_path / "diagnostics.json",
            start_url=PAGE_URL,
            max_pages=1,
            page_size=10,
            request_delay_seconds=0,
        )

    assert exc_info.value.exit_code == 2
    assert "browser unavailable" in capsys.readouterr().out


def test_report_index_pdf_url_helper_handles_none() -> None:
    assert report_index_module._is_pdf_url(None) is False


def test_cli_collect_report_index_help_works() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "welfare_inspections.cli",
            "collect-report-index",
            "--help",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "report-index" in result.stdout


def _complete_client() -> FakeClient:
    return FakeClient(
        pages=[
            PageFetch(
                url=PAGE_URL,
                html=SHELL_HTML,
                diagnostic=HttpDiagnostic(url=PAGE_URL, status_code=200),
            )
        ],
        json_pages=[
            JsonFetch(
                url="https://www.gov.il/he/api/DynamicCollector",
                data=_structured_payload(),
                diagnostic=HttpDiagnostic(
                    url="https://www.gov.il/he/api/DynamicCollector",
                    status_code=200,
                ),
            )
        ],
    )


def _structured_payload() -> dict[str, object]:
    return {
        "Results": [
            {
                "UrlName": "report-one",
                "Data": {
                    "שם מסגרת": "בית הדר",
                    "סוג מסגרת": "הוסטל",
                    "סמל מסגרת": "12345",
                    "מינהל": "מוגבלויות",
                    "מחוז": "ירושלים",
                    "תאריך ביצוע": "13/02/2024",
                    "report": [{"FileName": "report.pdf"}],
                },
            }
        ],
        "TotalResults": 1,
    }


def _dom_html() -> str:
    return """
    <article>
      <a href="/he/departments/dynamiccollectors/report?DCRI_UrlName=report-one">
        פריט
      </a>
      <a href="/BlobFolder/dynamiccollectorresultitem/report-one/he/report.pdf">PDF</a>
      <div>שם מסגרת: בית הדר</div>
      <div>סוג מסגרת: הוסטל</div>
      <div>סמל מסגרת: 12345</div>
      <div>מינהל: מוגבלויות</div>
      <div>מחוז: ירושלים</div>
      <div>תאריך ביצוע: 13/02/2024</div>
    </article>
    """


class FakeClient:
    def __init__(
        self,
        pages: list[PageFetch],
        json_pages: list[JsonFetch] | None = None,
    ) -> None:
        self.pages = pages
        self.json_pages = json_pages or []
        self.urls: list[str] = []
        self.json_requests: list[tuple[str, dict[str, object], str]] = []
        self.closed = False

    def fetch(self, url: str) -> PageFetch:
        self.urls.append(url)
        return self.pages.pop(0)

    def post_json(
        self,
        url: str,
        payload: dict[str, object],
        x_client_id: str,
    ) -> JsonFetch:
        self.json_requests.append((url, payload, x_client_id))
        return self.json_pages.pop(0)

    def close(self) -> None:
        self.closed = True


class FakePlaywrightContext:
    def __init__(self, html_pages: list[str]) -> None:
        self.chromium = FakeChromium(html_pages)

    def __enter__(self) -> FakePlaywrightContext:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


class FakeChromium:
    def __init__(self, html_pages: list[str]) -> None:
        self.html_pages = html_pages

    def launch(self, *, headless: bool) -> FakeBrowser:
        assert headless is True
        return FakeBrowser(self.html_pages)


class FakeBrowser:
    def __init__(self, html_pages: list[str]) -> None:
        self.html_pages = html_pages
        self.closed = False

    def new_page(self) -> FakePage:
        return FakePage(self.html_pages)

    def close(self) -> None:
        self.closed = True


class FakePage:
    def __init__(self, html_pages: list[str]) -> None:
        self.html_pages = html_pages
        self.page_index = -1

    def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        assert wait_until == "networkidle"
        assert timeout == 60_000
        self.page_index += 1

    def content(self) -> str:
        return self.html_pages[self.page_index]


class SimpleReportIndexDiagnostics:
    source_path_used = "structured_dynamic_collector"
    missing_field_records = 0
    duplicate_id_records = 0
