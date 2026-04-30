"""Command line interface for the welfare inspection dataset builder."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from welfare_inspections import __version__
from welfare_inspections.collect.metadata_parser import (
    parse_metadata_from_text_diagnostics,
)
from welfare_inspections.collect.pdf_download import download_source_pdfs
from welfare_inspections.collect.pdf_text import extract_embedded_text_from_manifest
from welfare_inspections.collect.portal_discovery import (
    discover_source_documents,
)
from welfare_inspections.collect.settings import (
    DiscoverySettings,
    DownloadSettings,
    MetadataParseSettings,
    ParseSettings,
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
    MetadataParseSettings()
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
