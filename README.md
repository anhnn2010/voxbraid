# VoxBraid

**Weave voices into stories.**

VoxBraid is a planned modular, multi-voice text-to-audio toolkit. Its **only source format is
prepared UTF-8 TXT**, optionally annotated with speaker labels. OCR, PDF/EPUB extraction,
cleanup and AI speaker identification happen **before** VoxBraid, outside this repository.

> **Current state: M0 scaffold (version 0.0.1).** The package installs and provides a working
> `voxbraid` CLI for help, version and environment diagnostics. **It cannot synthesize audio
> yet.** `preview` starts in M1; `render` starts later. The Rapunzel legacy demo is supplied
> separately under ignored `local_samples/` for personal comparison.

## Quick start

### Arch Linux / Linux

```bash
cd voxbraid_m0  # Or the directory into which you extracted the ZIP
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
voxbraid --help
voxbraid --version
voxbraid doctor
python -m pytest -q
```

### Windows (PowerShell)

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
voxbraid --help
voxbraid doctor
python -m pytest -q
```

`python -m voxbraid --help` also works if you prefer not to use the installed console script.

`voxbraid doctor` checks for Python and the available `ffmpeg`, `ffprobe` and `edge-tts`
executables. Missing tools do not fail M0: synthesis has not been implemented yet.

## Scope and design invariants

- **Input:** prepared UTF-8 TXT only. Plain narration and manually tagged multiple voices.
- **Provider-neutral:** the future voice assignment is per character/segment, not per book.
- **M1 parser:** preserve paragraph boundaries and validate speaker tags; no AI/NLP.
- **M2+ speech:** Edge TTS adapter first; allow optional providers without mandatory heavy deps.
- **Reliability:** retry transient failures, validate cached audio, resume interrupted jobs.
- **Composer:** sentence vs paragraph vs dialogue pauses; optional music and fades.
- **Re-render:** editing music/pauses must not call TTS again if speech is cached.
- **Cross-platform:** Python 3.10+; no Arch-specific commands in package logic.

## Repo structure

```text
src/voxbraid/           Installable Python package (CLI + diagnostics in M0)
tests/                  Automated tests without internet access
tests/fixtures/         Original synthetic TXT fixtures
docs/roadmap.md         Milestones, acceptance criteria, and checkpoints
local_samples/          Ignored local-only Rapunzel benchmark and old script
```

`local_samples/` is **excluded from Git by default** because the demo contains a retelling
from a source book; review rights before sharing. No audio cache, generated MP3 or model
artifacts should be committed.

## Development

```bash
python -m pytest -q
python -m ruff check .
```

See [docs/roadmap.md](docs/roadmap.md) for the next milestones and their exit criteria.

**License:** Not chosen yet. Select a license before publishing this as a public repo.
