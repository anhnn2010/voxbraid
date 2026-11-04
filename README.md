# VoxBraid

**Weave voices into stories.**

VoxBraid is a modular TXT-to-audio project with multi-character narration and future
per-character TTS providers. Only **prepared UTF-8 TXT** belongs in this repository.
OCR, PDF/EPUB extraction, text cleanup and AI speaker identification are separate
upstream tasks.

> **M1 checkpoint — v0.0.2.** `voxbraid preview` parses TXT, identifies sentence and
> paragraph boundaries, labels roles, and plans pauses **fully offline**. The `render`
> command is **not implemented yet**; audio generation starts in a later milestone.

## Install and test (Arch Linux + pyenv)

In your existing `voxbraid` repository and pyenv environment:

```bash
cd ~/Downloads/projects/voxbraid
pyenv version
python -m pip install -e '.[dev]'
pyenv rehash
voxbraid --version
voxbraid doctor
python -m pytest -q
python -m ruff check .
```

If you are **updating from M0**, extract the M1 update ZIP at the **root of the
existing repository**. It adds or replaces only project code, tests and documentation.
It does not touch `.git`, `.python-version`, your virtual environment or ignored
`local_samples/`.

On Windows, use a normal Python 3.10+ environment and the same `pip install -e ".[dev]"`.

## M1 preview (no synthesis / no internet)

Plain narration TXT:

```bash
voxbraid preview tests/fixtures/plain_story.txt
```

Tagged multiple-speaker TXT:

```bash
voxbraid preview tests/fixtures/multivoice_story.txt
```

The original Rapunzel demo from M0 (if kept under `local_samples/`):

```bash
voxbraid preview local_samples/rapunzel_legacy/rapunzel_dialogue.txt --limit 20
```

The M1 planner produces 77 segments from that Rapunzel source; it does **not**
produce audio or call any provider. The count is a regression check, not a guarantee
of perfect sentence detection for arbitrary texts.

Tune pause settings without modifying the TXT:

```bash
voxbraid preview tests/fixtures/plain_story.txt \
  --intro 3 \
  --sentence-gap 1.5 \
  --paragraph-gap 3 \
  --speaker-gap 1 \
  --attribution-gap 0.4 \
  --lead-gap 0.6
```

Export a machine-readable preview for inspection:

```bash
voxbraid preview tests/fixtures/multivoice_story.txt --json
```

See [the input format specification](docs/text_format.md) for role markers,
paragraph conventions, pause precedence, quote handling and limitations.

## Repository scope and structure

```text
src/voxbraid/
    cli.py          Preview/doctor entry point
    parser.py       TXT and role parsing
    models.py       Provider-independent document and segment models
    planner.py      Sentence splitting and pause planning
    diagnostics.py  External tool checks

tests/              Offline pytest regression suite
tests/fixtures/     Original synthetic test data
docs/roadmap.md     Milestone plan and checkpoint log
docs/text_format.md User-facing TXT rules
local_samples/      Git-ignored legacy demo kept for local listening comparison
```

**Future:** M2 provider abstraction + Edge TTS, M3 retry/resume/cache, M4 audio
composer with music, M5 configuration and CLI polishing, M6 integration and release.
Optional providers such as Kokoro/ElevenLabs will not be compulsory dependencies.

`local_samples/` is intentionally excluded from Git: do not accidentally publish
full book text or personal audio. Audio caches and generated MP3 files are also ignored.

## Development

```bash
python -m pytest -q
python -m ruff check .
```

**License:** not selected yet. Decide before making the repository public.
