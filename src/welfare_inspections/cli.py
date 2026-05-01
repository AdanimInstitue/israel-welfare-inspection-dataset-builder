"""Command line interface for the welfare inspection dataset builder."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from welfare_inspections import __version__
from welfare_inspections.collect.export import export_reports_from_metadata
from welfare_inspections.collect.llm_extract import extract_llm_candidates
from welfare_inspections.collect.metadata_parser import (
    parse_metadata_from_text_diagnostics,
)
from welfare_inspections.collect.pdf_download import download_source_pdfs
from welfare_inspections.collect.pdf_render import (
    DEFAULT_RENDER_PROFILE,
    render_pages_from_manifest,
)
from welfare_inspections.collect.pdf_text import extract_embedded_text_from_manifest
from welfare_inspections.collect.portal_discovery import (
    discover_source_documents,
)
from welfare_inspections.collect.reconcile import (
    reconcile_report_metadata,
    run_backfill_dry_run,
)
from welfare_inspections.collect.settings import (
    DiscoverySettings,
    DownloadSettings,
    ParseSettings,
)
from welfare_inspections.collect.weekly import (
    UnsupportedWeeklyProductionMode,
    create_weekly_run_plan,
)

app = typer.Typer(
    name="welfare-inspections",
    help="Israel welfare inspection dataset builder.",
    no_args_is_help=False,
    invoke_without_command=True,
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"welfare-inspections {__version__}")
        raise typer.Exit()


@app.callback()
def root(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the package version and exit.",
        ),
    ] = None,
) -> None:
    """Run local builder commands."""


@app.command()
def discover(
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            help="Path for discovered source manifest JSONL.",
        ),
    ] = Path("outputs/source_manifest.jsonl"),
    diagnostics: Annotated[
        Path,
        typer.Option(
            "--diagnostics",
            help="Path for discovery diagnostics JSON.",
        ),
    ] = Path("outputs/discovery_diagnostics.json"),
    start_url: Annotated[
        str | None,
        typer.Option(help="Gov.il dynamic collector URL to start from."),
    ] = None,
    max_pages: Annotated[
        int | None,
        typer.Option(min=1, help="Maximum collector pages to inspect."),
    ] = None,
    page_size: Annotated[
        int | None,
        typer.Option(min=1, help="Skip increment between collector pages."),
    ] = None,
    request_delay_seconds: Annotated[
        float | None,
        typer.Option(min=0.0, help="Delay between page requests."),
    ] = None,
) -> None:
    """Manually probe Gov.il and write a local source manifest."""
    settings = DiscoverySettings()
    records, run_diagnostics = discover_source_documents(
        output_path=output,
        diagnostics_path=diagnostics,
        start_url=start_url or settings.start_url,
        max_pages=max_pages or settings.max_pages,
        page_size=page_size or settings.page_size,
        request_delay_seconds=(
            request_delay_seconds
            if request_delay_seconds is not None
            else settings.request_delay_seconds
        ),
    )
    console.print(
        f"Discovered {len(records)} source records; "
        f"stop_reason={run_diagnostics.stop_reason}"
    )


@app.command()
def download(
    source_manifest: Annotated[
        Path,
        typer.Option(
            "--source-manifest",
            help="Path to a PR 2 source manifest JSONL.",
        ),
    ] = Path("outputs/source_manifest.jsonl"),
    output_manifest: Annotated[
        Path,
        typer.Option(
            "--output-manifest",
            help="Path for the updated download manifest JSONL.",
        ),
    ] = Path("outputs/download_manifest.jsonl"),
    diagnostics: Annotated[
        Path,
        typer.Option(
            "--diagnostics",
            help="Path for download diagnostics JSON.",
        ),
    ] = Path("outputs/download_diagnostics.json"),
    download_dir: Annotated[
        Path,
        typer.Option(
            "--download-dir",
            help="Directory for downloaded PDFs.",
        ),
    ] = Path("downloads/pdfs"),
    force: Annotated[
        bool,
        typer.Option(
            "--force/--no-force",
            help="Redownload even when an existing valid local file is present.",
        ),
    ] = False,
    request_delay_seconds: Annotated[
        float | None,
        typer.Option(min=0.0, help="Delay between PDF requests."),
    ] = None,
) -> None:
    """Manually download PDFs from a source manifest and record checksums."""
    settings = DownloadSettings()
    records, run_diagnostics = download_source_pdfs(
        source_manifest_path=source_manifest,
        output_manifest_path=output_manifest,
        diagnostics_path=diagnostics,
        download_dir=download_dir,
        force=force,
        request_delay_seconds=(
            request_delay_seconds
            if request_delay_seconds is not None
            else settings.request_delay_seconds
        ),
    )
    console.print(
        f"Processed {len(records)} source records; "
        f"downloaded={run_diagnostics.downloaded_records}; "
        f"skipped_existing={run_diagnostics.skipped_existing_records}; "
        f"failed={run_diagnostics.failed_records}"
    )


@app.command()
def parse(
    source_manifest: Annotated[
        Path,
        typer.Option(
            "--source-manifest",
            help="Path to a PR 3 download manifest JSONL.",
        ),
    ] = Path("outputs/download_manifest.jsonl"),
    text_output_dir: Annotated[
        Path,
        typer.Option(
            "--text-output-dir",
            help="Directory for ignored extracted text files.",
        ),
    ] = Path("outputs/extracted_text"),
    diagnostics: Annotated[
        Path,
        typer.Option(
            "--diagnostics",
            help="Path for embedded text extraction diagnostics JSON.",
        ),
    ] = Path("outputs/text_extraction_diagnostics.json"),
    overwrite: Annotated[
        bool | None,
        typer.Option(
            "--overwrite/--no-overwrite",
            help="Overwrite existing extracted text files.",
        ),
    ] = None,
) -> None:
    """Manually extract embedded text from downloaded PDFs."""
    settings = ParseSettings()
    run_diagnostics = extract_embedded_text_from_manifest(
        source_manifest_path=source_manifest,
        text_output_dir=text_output_dir,
        diagnostics_path=diagnostics,
        overwrite=overwrite if overwrite is not None else settings.overwrite,
    )
    console.print(
        f"Processed {run_diagnostics.total_records} source records; "
        f"extracted={run_diagnostics.extracted_records}; "
        f"failed={run_diagnostics.failed_records}; "
        f"warnings={run_diagnostics.warning_records}"
    )


@app.command("parse-metadata")
def parse_metadata(
    text_diagnostics: Annotated[
        Path,
        typer.Option(
            "--text-diagnostics",
            help="Path to PR 4 embedded text extraction diagnostics JSON.",
        ),
    ] = Path("outputs/text_extraction_diagnostics.json"),
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            help="Path for ignored report metadata JSONL output.",
        ),
    ] = Path("outputs/report_metadata.jsonl"),
    diagnostics: Annotated[
        Path,
        typer.Option(
            "--diagnostics",
            help="Path for metadata parse diagnostics JSON.",
        ),
    ] = Path("outputs/metadata_parse_diagnostics.json"),
) -> None:
    """Manually parse top-level report metadata from extracted text."""
    run_diagnostics = parse_metadata_from_text_diagnostics(
        text_diagnostics_path=text_diagnostics,
        output_path=output,
        diagnostics_path=diagnostics,
    )
    console.print(
        f"Processed {run_diagnostics.total_records} text records; "
        f"parsed={run_diagnostics.parsed_records}; "
        f"failed={run_diagnostics.failed_records}; "
        f"warnings={run_diagnostics.warning_records}"
    )


@app.command("render-pages")
def render_pages(
    source_manifest: Annotated[
        Path,
        typer.Option(
            "--source-manifest",
            help="Path to a PR 3 download manifest JSONL.",
        ),
    ] = Path("outputs/download_manifest.jsonl"),
    output_manifest: Annotated[
        Path,
        typer.Option(
            "--output-manifest",
            help="Path for rendered page artifact manifest JSONL.",
        ),
    ] = Path("outputs/rendered_pages_manifest.jsonl"),
    page_output_dir: Annotated[
        Path,
        typer.Option(
            "--page-output-dir",
            help="Ignored local directory for rendered page images.",
        ),
    ] = Path("outputs/rendered_pages"),
    diagnostics: Annotated[
        Path,
        typer.Option(
            "--diagnostics",
            help="Path for page rendering diagnostics JSON.",
        ),
    ] = Path("outputs/page_render_diagnostics.json"),
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite/--no-overwrite",
            help="Overwrite existing rendered page images.",
        ),
    ] = False,
) -> None:
    """Manually render local downloaded PDFs into ignored page images."""
    artifacts, run_diagnostics = render_pages_from_manifest(
        source_manifest_path=source_manifest,
        output_manifest_path=output_manifest,
        diagnostics_path=diagnostics,
        page_output_dir=page_output_dir,
        render_profile=DEFAULT_RENDER_PROFILE,
        overwrite=overwrite,
    )
    console.print(
        f"Processed {run_diagnostics.total_records} source records; "
        f"artifacts={len(artifacts)}; "
        f"rendered={run_diagnostics.rendered_records}; "
        f"failed={run_diagnostics.failed_records}"
    )


@app.command("extract-llm")
def extract_llm(
    source_manifest: Annotated[
        Path,
        typer.Option(
            "--source-manifest",
            help="Path to a PR 3 download manifest JSONL.",
        ),
    ] = Path("outputs/download_manifest.jsonl"),
    text_diagnostics: Annotated[
        Path | None,
        typer.Option(
            "--text-diagnostics",
            help=(
                "Optional path to PR 4 embedded text extraction diagnostics "
                "JSON. If omitted, no text diagnostics are used."
            ),
        ),
    ] = None,
    render_manifest: Annotated[
        Path | None,
        typer.Option(
            "--render-manifest",
            help=(
                "Optional path to rendered page artifact manifest JSONL. "
                "If omitted, no rendered artifacts are used."
            ),
        ),
    ] = None,
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            help="Path for ignored LLM extraction candidate JSONL output.",
        ),
    ] = Path("outputs/llm_metadata_candidates.jsonl"),
    diagnostics: Annotated[
        Path,
        typer.Option(
            "--diagnostics",
            help="Path for LLM extraction diagnostics JSON.",
        ),
    ] = Path("outputs/llm_extraction_diagnostics.json"),
    eval_fixtures: Annotated[
        Path | None,
        typer.Option(
            "--eval-fixtures",
            help="Optional JSONL reviewed expectations for offline evaluation.",
        ),
    ] = None,
    eval_report: Annotated[
        Path | None,
        typer.Option(
            "--eval-report",
            help="Optional output path for offline LLM evaluation report.",
        ),
    ] = Path("outputs/llm_eval_report.json"),
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            help="Extraction mode: dry-run, mock, or production.",
        ),
    ] = "dry-run",
    mock_response_path: Annotated[
        Path | None,
        typer.Option(
            "--mock-response-path",
            help="JSONL mock provider responses for offline test extraction.",
        ),
    ] = None,
) -> None:
    """Validate schema-bound LLM extraction plumbing without live CI calls."""
    candidates, run_diagnostics = extract_llm_candidates(
        source_manifest_path=source_manifest,
        text_diagnostics_path=text_diagnostics,
        render_manifest_path=render_manifest,
        output_path=output,
        diagnostics_path=diagnostics,
        eval_fixtures_path=eval_fixtures,
        eval_report_path=eval_report,
        mode=mode,
        mock_response_path=mock_response_path,
    )
    console.print(
        f"Processed {run_diagnostics.total_records} source records; "
        f"candidates={len(candidates)}; "
        f"failed={run_diagnostics.failed_records}; "
        f"warnings={run_diagnostics.warning_records}"
    )


@app.command("export")
def export(
    metadata: Annotated[
        Path,
        typer.Option(
            "--metadata",
            help="Path to PR 5 report metadata JSONL.",
        ),
    ] = Path("outputs/report_metadata.jsonl"),
    metadata_diagnostics: Annotated[
        Path,
        typer.Option(
            "--metadata-diagnostics",
            help="Path to PR 5 metadata parse diagnostics JSON.",
        ),
    ] = Path("outputs/metadata_parse_diagnostics.json"),
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            help="Ignored local directory for canonical CSV/JSONL exports.",
        ),
    ] = Path("outputs/exports"),
) -> None:
    """Manually validate parsed metadata and export local report rows."""
    run_diagnostics = export_reports_from_metadata(
        metadata_path=metadata,
        metadata_diagnostics_path=metadata_diagnostics,
        output_dir=output_dir,
    )
    console.print(
        f"Processed {run_diagnostics.total_records} metadata records; "
        f"exported={run_diagnostics.exported_records}; "
        f"validation_failed={run_diagnostics.validation_failed_records}; "
        f"duplicate_ids={run_diagnostics.duplicate_id_records}"
    )


@app.command("reconcile")
def reconcile(
    metadata: Annotated[
        Path,
        typer.Option(
            "--metadata",
            help="Path to PR 5 report metadata JSONL.",
        ),
    ] = Path("outputs/report_metadata.jsonl"),
    metadata_diagnostics: Annotated[
        Path,
        typer.Option(
            "--metadata-diagnostics",
            help="Path to PR 5 metadata parse diagnostics JSON.",
        ),
    ] = Path("outputs/metadata_parse_diagnostics.json"),
    llm_candidates: Annotated[
        Path | None,
        typer.Option(
            "--llm-candidates",
            help="Optional PR 7 LLM metadata candidate JSONL manifest.",
        ),
    ] = Path("outputs/llm_metadata_candidates.jsonl"),
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            help="Path for ignored reconciled report metadata JSONL.",
        ),
    ] = Path("outputs/reconciled_report_metadata.jsonl"),
    diagnostics: Annotated[
        Path,
        typer.Option(
            "--diagnostics",
            help="Path for reconciliation diagnostics JSON.",
        ),
    ] = Path("outputs/reconciliation_diagnostics.json"),
) -> None:
    """Manually reconcile deterministic and LLM report metadata candidates."""
    records, run_diagnostics = reconcile_report_metadata(
        metadata_path=metadata,
        metadata_diagnostics_path=metadata_diagnostics,
        llm_candidates_path=llm_candidates,
        output_path=output,
        diagnostics_path=diagnostics,
    )
    console.print(
        f"Processed {run_diagnostics.total_records} metadata records; "
        f"reconciled={len(records)}; "
        f"accepted={run_diagnostics.accepted_decisions}; "
        f"needs_review={run_diagnostics.needs_review_decisions}"
    )


@app.command("backfill")
def backfill(
    reconciled_metadata: Annotated[
        Path,
        typer.Option(
            "--reconciled-metadata",
            help="Path to reconciled report metadata JSONL.",
        ),
    ] = Path("outputs/reconciled_report_metadata.jsonl"),
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            help="Path for ignored backfill diagnostics JSON.",
        ),
    ] = Path("outputs/backfill_diagnostics.json"),
    evaluation_report: Annotated[
        Path | None,
        typer.Option(
            "--evaluation-report",
            help="Optional PR 7 LLM evaluation report JSON reference.",
        ),
    ] = Path("outputs/llm_eval_report.json"),
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--no-dry-run",
            help="Backfill is currently diagnostics-only and must remain dry-run.",
        ),
    ] = True,
) -> None:
    """Create diagnostics-first dry-run backfill summaries."""
    if not dry_run:
        raise typer.BadParameter("Backfill only supports --dry-run in PR 8.")
    diagnostics = run_backfill_dry_run(
        reconciled_metadata_path=reconciled_metadata,
        output_path=output,
        evaluation_report_path=evaluation_report,
    )
    console.print(
        f"Backfill dry-run fields={len(diagnostics.field_changes)}; "
        f"changed={diagnostics.changed_count}; "
        f"no_baseline={diagnostics.no_baseline_count}; "
        f"unresolved={diagnostics.unresolved_count}; "
        f"rejected={diagnostics.rejected_count}"
    )


@app.command("weekly-plan")
def weekly_plan(
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            help="Ignored local directory for weekly run sidecars.",
        ),
    ] = Path("outputs/weekly"),
    artifact_dir: Annotated[
        Path | None,
        typer.Option(
            "--artifact-dir",
            help="Ignored local directory reserved for uploaded review artifacts.",
        ),
    ] = None,
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            help="Weekly mode. PR 9 supports dry-run only.",
        ),
    ] = "dry-run",
    max_pages: Annotated[
        int,
        typer.Option(
            "--max-pages",
            min=1,
            help="Maximum Gov.il collector pages for the weekly source probe.",
        ),
    ] = 1,
    request_delay_seconds: Annotated[
        float,
        typer.Option(
            "--request-delay-seconds",
            min=0.0,
            help="Delay between network requests for collection stages.",
        ),
    ] = 2.0,
) -> None:
    """Plan a safe weekly dry-run review-artifact workflow."""
    try:
        plan = create_weekly_run_plan(
            output_dir=output_dir,
            artifact_dir=artifact_dir,
            mode=mode,
            max_pages=max_pages,
            request_delay_seconds=request_delay_seconds,
        )
    except UnsupportedWeeklyProductionMode as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=2) from exc
    console.print(
        f"Weekly plan mode={plan.mode}; commands={len(plan.commands)}; "
        f"summary={plan.summary_path}"
    )


def main(argv: list[str] | None = None) -> int:
    try:
        app(args=argv, prog_name="welfare-inspections")
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
