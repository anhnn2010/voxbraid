# VoxBraid development checkpoints

## Agreed scope

- Input: UTF-8 TXT only, plain or with manual speaker tags.
- No PDF, EPUB, OCR or AI character inference within VoxBraid.
- Edge TTS first, provider-neutral API allowing different providers per character.
- Keep a light installation. Optional providers have optional dependencies.
- Python 3.10+ and FFmpeg/FFprobe for actual audio work (future milestones).

## M0 — Foundation (current checkpoint)

Deliverables:
- `pyproject.toml` package with editable installation and `voxbraid` entry point.
- CLI `--help`, `--version`, `doctor`, plus `python -m voxbraid`.
- pytest fixtures and offline tests, Ruff configuration, GitHub CI smoke tests.
- Rapunzel legacy script and source kept in git-ignored `local_samples/` for local comparison.

**Exit criteria (verify on user's Arch Linux):**

```bash
python -m pip install -e '.[dev]'
voxbraid --help
voxbraid --version
voxbraid doctor
python -m pytest -q
python -m ruff check .
```

Do not treat M0 as an audio-producing release. Its version is `0.0.1`.

## M1 — TXT parser & segment planner

- Plain TXT, manual `[role]`, `[narrator:tag]`, `[narrator:lead]`.
- Blank lines distinguish paragraphs; a wrapped line is not necessarily a new paragraph.
- Sentence splitting with quote/abbreviation regression fixtures.
- Structured segments with source provenance, roles, boundaries and pause classes.
- `voxbraid preview file.txt` (fully offline).
- Strict validation: unknown/malformed role tags must fail visibly.
- Verify the Rapunzel baseline against the M1 preview.

## M2 — Provider abstraction + Edge TTS

- Provider protocol + per-role profile (`provider`, `voice`, provider-specific options).
- First implementation: Edge; user-preferred voices Brian, Andrew, Emma, Ava.
- Test doubles to exercise mixed-provider routing without installing heavy dependencies.
- Render a short multi-voice sample; no music yet.

## M3 — Reliability

- Retry transient socket errors with exponential backoff + jitter and a bounded limit.
- Validate audio before committing cache files atomically.
- Resume interrupted jobs; cache key includes provider/model/voice/text/options.
- Don't rerun successful speech when another segment fails.

## M4 — Audio composer

- Distinct sentence, paragraph, speaker, dialogue attribution, chapter pauses.
- Intermediate common PCM format and optional speech-only output.
- Optional background music, loop, fade; do not resynthesize for music/pause changes.
- Start with the existing successful Baroque volume value as a comparison point.

## M5 — Configuration and CLI

- YAML voice profiles with provider per character; optional provider dependencies.
- Presets and friendly validation errors; stable `preview`/`render` interface.
- Clearly document cost implications; never silently use a paid fallback provider.

## M6 — Integration and packaging

- Full Rapunzel audio compared with original legacy demo by listening.
- Tests for Mr./Dr., dialogue tags, resume/cache, malformed TXT, audio verification.
- Arch Linux and Windows smoke tests, README and packaging review.
- Decide release license before public publication.

## Design decision log

- 2026-11-04: Name finalized as **VoxBraid**.
- 2026-11-04: Scope limited to prepared TXT-to-audio; upstream extraction/manual AI is separate.
- 2026-11-04: A future book may use different TTS providers for different characters.
- 2026-11-04: Start with one Edge adapter, avoid installing PyTorch/BookNLP.
- 2026-11-04: Baseline Rapunzel was reported satisfactory; keep it for local regression.
