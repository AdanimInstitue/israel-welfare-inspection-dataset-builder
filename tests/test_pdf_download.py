from __future__ import annotations

import json
from pathlib import Path

import httpx

from welfare_inspections import cli
from welfare_inspections.collect.govil_client import BinaryFetch
from welfare_inspections.collect.manifest import (
    read_source_manifest,
    write_source_manifest,
)
from welfare_inspections.collect.models import HttpDiagnostic, SourceDocumentRecord
from welfare_inspections.collect.pdf_download import (
    download_source_pdfs,
    sha256_bytes,
)


def test_manifest_read_write_roundtrip(tmp_path: Path) -> None:
    manifest_path = tmp_path / "source.jsonl"
    source_record = _record("one")

    write_source_manifest(manifest_path, [source_record])

    records = read_source_manifest(manifest_path)
    assert records == [source_record]


def test_manifest_reader_reports_line_number_for_invalid_jsonl(tmp_path: Path) -> None:
    manifest_path = tmp_path / "source.jsonl"
    manifest_path.write_text("{}\nnot-json\n", encoding="utf-8")

    try:
        read_source_manifest(manifest_path)
    except ValueError as exc:
        assert f"{manifest_path}:1" in str(exc)
    else:
        raise AssertionError("Expected invalid source manifest to raise ValueError")


def test_download_success_updates_manifest_and_diagnostics(tmp_path: Path) -> None:
    manifest_path = tmp_path / "source.jsonl"
    output_path = tmp_path / "download.jsonl"
    diagnostics_path = tmp_path / "diagnostics.json"
    content = b"%PDF-1.7\nmock pdf\n"
    write_source_manifest(manifest_path, [_record("downloaded")])
    client = FakeDownloadClient(
        [
            BinaryFetch(
                url="https://www.gov.il/file.pdf",
                content=content,
                diagnostic=HttpDiagnostic(
                    url="https://www.gov.il/file.pdf",
                    status_code=200,
                    response_headers={"content-type": "application/pdf"},
                ),
            )
        ]
    )

    records, diagnostics = download_source_pdfs(
        source_manifest_path=manifest_path,
        output_manifest_path=output_path,
        diagnostics_path=diagnostics_path,
        download_dir=tmp_path / "pdfs",
        request_delay_seconds=0,
        client=client,
    )

    local_path = Path(records[0].local_path or "")
    payload = json.loads(output_path.read_text(encoding="utf-8").splitlines()[0])
    diagnostics_payload = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    assert local_path.read_bytes() == content
    assert records[0].downloaded_at is not None
    assert records[0].pdf_sha256 == sha256_bytes(content)
    assert payload["pdf_sha256"] == sha256_bytes(content)
    assert diagnostics.downloaded_records == 1
    assert diagnostics_payload["record_diagnostics"][0]["status"] == "downloaded"
    assert client.urls == ["https://www.gov.il/file.pdf"]


def test_existing_valid_file_is_skipped_without_network(tmp_path: Path) -> None:
    content = b"%PDF-1.7\nalready here\n"
    local_path = tmp_path / "pdfs" / "existing.pdf"
    local_path.parent.mkdir(parents=True)
    local_path.write_bytes(content)
    record = _record(
        "existing",
        pdf_sha256=sha256_bytes(content),
        local_path=str(local_path),
    )
    manifest_path = tmp_path / "source.jsonl"
    write_source_manifest(manifest_path, [record])
    client = FakeDownloadClient([])

    records, diagnostics = download_source_pdfs(
        source_manifest_path=manifest_path,
        output_manifest_path=tmp_path / "download.jsonl",
        diagnostics_path=tmp_path / "diagnostics.json",
        download_dir=tmp_path / "pdfs",
        request_delay_seconds=0,
        client=client,
    )

    assert records[0].pdf_sha256 == sha256_bytes(content)
    assert diagnostics.skipped_existing_records == 1
    assert diagnostics.record_diagnostics[0].status == "skipped_existing"
    assert client.urls == []


def test_existing_checksum_mismatch_is_diagnostic_without_overwrite(
    tmp_path: Path,
) -> None:
    local_path = tmp_path / "pdfs" / "mismatch.pdf"
    local_path.parent.mkdir(parents=True)
    local_path.write_bytes(b"unexpected content")
    record = _record(
        "mismatch",
        pdf_sha256=sha256_bytes(b"expected content"),
        local_path=str(local_path),
    )
    manifest_path = tmp_path / "source.jsonl"
    write_source_manifest(manifest_path, [record])

    records, diagnostics = download_source_pdfs(
        source_manifest_path=manifest_path,
        output_manifest_path=tmp_path / "download.jsonl",
        diagnostics_path=tmp_path / "diagnostics.json",
        download_dir=tmp_path / "pdfs",
        request_delay_seconds=0,
        client=FakeDownloadClient([]),
    )

    assert local_path.read_bytes() == b"unexpected content"
    assert records[0] == record
    assert diagnostics.failed_records == 1
    assert diagnostics.checksum_mismatch_records == 1
    assert diagnostics.record_diagnostics[0].status == "checksum_mismatch"


def test_http_failure_records_diagnostics_and_preserves_record(tmp_path: Path) -> None:
    record = _record("http-failure")
    manifest_path = tmp_path / "source.jsonl"
    write_source_manifest(manifest_path, [record])

    records, diagnostics = download_source_pdfs(
        source_manifest_path=manifest_path,
        output_manifest_path=tmp_path / "download.jsonl",
        diagnostics_path=tmp_path / "diagnostics.json",
        download_dir=tmp_path / "pdfs",
        request_delay_seconds=0,
        client=FakeDownloadClient(
            [
                BinaryFetch(
                    url=record.pdf_url,
                    content=b"",
                    diagnostic=HttpDiagnostic(url=record.pdf_url, status_code=503),
                )
            ]
        ),
    )

    assert records[0] == record
    assert diagnostics.failed_records == 1
    assert diagnostics.record_diagnostics[0].status == "failed"
    assert diagnostics.record_diagnostics[0].error == "http_status_503"


def test_blocked_response_records_blocked_diagnostics(tmp_path: Path) -> None:
    record = _record("blocked")
    manifest_path = tmp_path / "source.jsonl"
    write_source_manifest(manifest_path, [record])

    _records, diagnostics = download_source_pdfs(
        source_manifest_path=manifest_path,
        output_manifest_path=tmp_path / "download.jsonl",
        diagnostics_path=tmp_path / "diagnostics.json",
        download_dir=tmp_path / "pdfs",
        request_delay_seconds=0,
        client=FakeDownloadClient(
            [
                BinaryFetch(
                    url=record.pdf_url,
                    content=b"",
                    diagnostic=HttpDiagnostic(
                        url=record.pdf_url,
                        status_code=403,
                        is_blocked=True,
                    ),
                )
            ]
        ),
    )

    assert diagnostics.failed_records == 1
    assert diagnostics.blocked_responses == 1
    assert diagnostics.record_diagnostics[0].status == "blocked"


def test_cli_download_invokes_downloader(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_download_source_pdfs(**kwargs: object) -> tuple[list[object], object]:
        calls.append(kwargs)
        return [object()], SimpleDownloadDiagnostics()

    monkeypatch.setattr(cli, "download_source_pdfs", fake_download_source_pdfs)

    cli.download(
        source_manifest=tmp_path / "source.jsonl",
        output_manifest=tmp_path / "download.jsonl",
        diagnostics=tmp_path / "diagnostics.json",
        download_dir=tmp_path / "pdfs",
        request_delay_seconds=0,
    )

    assert calls[0]["source_manifest_path"] == tmp_path / "source.jsonl"
    assert calls[0]["output_manifest_path"] == tmp_path / "download.jsonl"
    assert calls[0]["download_dir"] == tmp_path / "pdfs"
    assert "Processed 1 source records" in capsys.readouterr().out


def test_httpx_binary_fetch_success(monkeypatch) -> None:
    fake_http_client = FakeHttpxClient(
        response=httpx.Response(
            200,
            content=b"%PDF-1.7\n",
            headers={"content-type": "application/pdf"},
            request=httpx.Request("GET", "https://www.gov.il/file.pdf"),
        )
    )
    monkeypatch.setattr(
        "welfare_inspections.collect.govil_client.httpx.Client",
        lambda **_kwargs: fake_http_client,
    )

    from welfare_inspections.collect.govil_client import GovilClient

    client = GovilClient()
    fetch = client.fetch_binary("https://www.gov.il/file.pdf")

    assert fetch.content == b"%PDF-1.7\n"
    assert fetch.diagnostic.status_code == 200
    assert fetch.diagnostic.response_headers == {"content-type": "application/pdf"}


def _record(
    name: str,
    *,
    pdf_sha256: str | None = None,
    local_path: str | None = None,
) -> SourceDocumentRecord:
    return SourceDocumentRecord(
        source_document_id=f"source-doc-{name}",
        govil_item_slug=name,
        govil_item_url=f"https://www.gov.il/item/{name}",
        pdf_url="https://www.gov.il/file.pdf",
        title=f"Report {name}",
        language_path="/he/",
        pdf_sha256=pdf_sha256,
        local_path=local_path,
        collector_version="0.1.0",
    )


class FakeDownloadClient:
    def __init__(self, fetches: list[BinaryFetch]) -> None:
        self._fetches = fetches
        self.urls: list[str] = []
        self.closed = False

    def fetch_binary(self, url: str) -> BinaryFetch:
        self.urls.append(url)
        return self._fetches.pop(0)

    def close(self) -> None:
        self.closed = True


class FakeHttpxClient:
    def __init__(self, *, response: httpx.Response) -> None:
        self._response = response

    def get(self, url: str) -> httpx.Response:
        return self._response

    def close(self) -> None:
        return None


class SimpleDownloadDiagnostics:
    downloaded_records = 1
    skipped_existing_records = 0
    failed_records = 0
