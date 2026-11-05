from __future__ import annotations

import subprocess
import sys

import pytest

from voxbraid import __version__
from voxbraid.cli import main
from voxbraid.diagnostics import Diagnostic, collect_diagnostics


def test_version_is_semverish() -> None:
    assert __version__ == "0.0.4"


def test_help_works_without_tts(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "voxbraid" in output
    assert "doctor" in output
    assert "    render " not in output
    assert "synthesize" in output
    assert "preview" in output


def test_version_argument(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert f"voxbraid {__version__}" in capsys.readouterr().out


def test_doctor_runs_offline(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["doctor"]) == 0
    stdout = capsys.readouterr().out
    assert "python" in stdout
    assert "ffmpeg" in stdout
    assert "ffprobe" in stdout
    assert "edge-tts" in stdout


def test_diagnostics_are_strictly_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("voxbraid.diagnostics.shutil.which", lambda _: None)
    checks = collect_diagnostics()
    assert len(checks) == 4
    assert isinstance(checks[0], Diagnostic)
    assert checks[0].available
    assert all(not item.available for item in checks[1:])


def test_render_is_not_fake_or_premature() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["render", "story.txt"])
    assert exc.value.code == 2


def test_module_invocation() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "voxbraid", "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "voxbraid 0.0.4" in result.stdout
