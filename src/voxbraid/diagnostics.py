"""Non-invasive checks for future audio dependencies.

The checks do not install libraries or access the network.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Diagnostic:
    name: str
    available: bool
    detail: str


def collect_diagnostics() -> list[Diagnostic]:
    """Report Python and optional external executables from PATH."""
    results = [
        Diagnostic(
            name="python",
            available=sys.version_info >= (3, 10),
            detail=sys.version.split()[0],
        )
    ]
    for program in ("ffmpeg", "ffprobe", "edge-tts"):
        resolved = shutil.which(program)
        missing_detail = (
            'not found; install with python -m pip install -e ".[edge]"'
            if program == "edge-tts"
            else "not found on PATH (needed for M4 audio composition)"
        )
        results.append(
            Diagnostic(
                name=program,
                available=bool(resolved),
                detail=resolved or missing_detail,
            )
        )
    return results
