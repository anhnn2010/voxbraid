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
        results.append(
            Diagnostic(
                name=program,
                available=bool(resolved),
                detail=resolved or "not found on PATH (optional at M0)",
            )
        )
    return results
