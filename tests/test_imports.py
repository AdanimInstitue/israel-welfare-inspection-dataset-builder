from __future__ import annotations

import runpy
import subprocess
import sys

import pytest

import welfare_inspections


def test_package_imports() -> None:
    assert welfare_inspections.__version__


def test_cli_module_entrypoint_works(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["welfare-inspections"])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("welfare_inspections.cli", run_name="__main__")

    assert exc_info.value.code == 0


def test_cli_help_works() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "welfare_inspections.cli", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "welfare-inspections" in result.stdout


def test_cli_version_works() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "welfare_inspections.cli", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "welfare-inspections" in result.stdout


def test_cli_discover_help_works() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "welfare_inspections.cli", "discover", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--output" in result.stdout


def test_cli_main_accepts_empty_args() -> None:
    from welfare_inspections.cli import main

    assert main([]) == 0
