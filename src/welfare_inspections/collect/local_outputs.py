"""Guards for generated local pipeline outputs."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
IGNORED_OUTPUT_ROOT = REPO_ROOT / "outputs"


def validate_local_output_path(path: Path, *, label: str = "output path") -> None:
    """Require generated outputs inside this repo to stay under ignored outputs/."""
    resolved_path = path.resolve()
    resolved_repo_root = REPO_ROOT.resolve()
    resolved_ignored_root = IGNORED_OUTPUT_ROOT.resolve()
    if (
        resolved_path == resolved_ignored_root
        or resolved_ignored_root in resolved_path.parents
    ):
        return
    if (
        resolved_path == resolved_repo_root
        or resolved_repo_root in resolved_path.parents
    ):
        msg = (
            f"{label} must be under the ignored local outputs/ directory when "
            "writing inside the repository."
        )
        raise ValueError(msg)
