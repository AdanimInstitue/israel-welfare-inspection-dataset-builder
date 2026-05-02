from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from welfare_inspections import cli
from welfare_inspections.collect.govil_client import JsonFetch, PageFetch
from welfare_inspections.collect.models import HttpDiagnostic
from welfare_inspections.collect.report_index import (
    BrowserCollectionResult,
    ReportIndexRunDiagnostics,
    collect_report_index,
    parse_report_index_dom_records,
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


class SimpleReportIndexDiagnostics:
    source_path_used = "structured_dynamic_collector"
    missing_field_records = 0
    duplicate_id_records = 0
