from __future__ import annotations

import subprocess
import sys

import welfare_inspections
from welfare_inspections.cli import main


def test_package_imports() -> None:
    assert welfare_inspections.__version__


def test_cli_main_accepts_empty_args() -> None:
    assert main([]) == 0


def test_cli_help_works() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "welfare_inspections.cli", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "welfare-inspections" in result.stdout
