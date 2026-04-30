"""Command line interface for the welfare inspection dataset builder."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from welfare_inspections import __version__
from welfare_inspections.collect.portal_discovery import (
    CANONICAL_SOURCE_URL,
    discover_source_documents,
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
        str,
        typer.Option(help="Gov.il dynamic collector URL to start from."),
    ] = CANONICAL_SOURCE_URL,
    max_pages: Annotated[
        int,
        typer.Option(min=1, help="Maximum collector pages to inspect."),
    ] = 5,
    page_size: Annotated[
        int,
        typer.Option(min=1, help="Skip increment between collector pages."),
    ] = 10,
    request_delay_seconds: Annotated[
        float,
        typer.Option(min=0.0, help="Delay between page requests."),
    ] = 1.0,
) -> None:
    """Manually probe Gov.il and write a local source manifest."""
    records, run_diagnostics = discover_source_documents(
        output_path=output,
        diagnostics_path=diagnostics,
        start_url=start_url,
        max_pages=max_pages,
        page_size=page_size,
        request_delay_seconds=request_delay_seconds,
    )
    console.print(
        f"Discovered {len(records)} source records; "
        f"stop_reason={run_diagnostics.stop_reason}"
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
