# VoxBraid development checkpoints

## Agreed scope

- Input: UTF-8 TXT only, plain or with manual speaker tags.
- No PDF, EPUB, OCR or AI character inference within VoxBraid.
- Edge TTS first; provider-neutral API allowing different providers per character.
- Keep a light installation. Optional providers have optional dependencies.
- Python 3.10+ and FFmpeg/FFprobe for future audio work.

## M0 — Foundation (committed baseline)

- `pyproject.toml` editable package, CLI `--help`, `--version`, `doctor`, Python module entry.
- pytest fixtures, lint configuration and GitHub CI scaffold.
- Rapunzel legacy script and source under git-ignored `local_samples/`.
- M0 package version: `0.0.1`.

## M1 — TXT parser & segment planner (delivered; awaiting user's Arch verification)

- Plain TXT, `[role]`, `[narrator:tag]`, `[narrator:lead]`.
- Blank lines delimit paragraphs; wrapped lines remain in the same paragraph.
- English sentence splitting with quote/abbreviation regression tests.
- Provider-independent segment data with role, kind, original lines, paragraph
  number, pause class and duration.
- Offline `voxbraid preview FILE` and optional `--json` / `--limit`.
- Invalid markup and invalid pause values fail visibly.
- Legacy Rapunzel remains 77 preview segments; no full book content tracked in Git.
- M1 package version: `0.0.2`. No audio rendering yet.

Acceptance on Arch Linux (pyenv):

```bash
python -m pip install -e '.[dev]'
pyenv rehash
voxbraid --version
voxbraid preview tests/fixtures/plain_story.txt
voxbraid preview tests/fixtures/multivoice_story.txt --json
voxbraid preview local_samples/rapunzel_legacy/rapunzel_dialogue.txt --limit 12
python -m pytest -q
python -m ruff check .
```

## M2 — Provider abstraction + Edge TTS

- Provider protocol + per-role profile (`provider`, `voice`, provider-specific options).
- First implementation: Edge; user-preferred voices Brian, Andrew, Emma, Ava.
- Test doubles to exercise mixed-provider routing without heavy dependencies.
- Render a short multi-voice sample; no music yet.

## M3 — Reliability

- Retry transient socket errors with exponential backoff, jitter and a bound.
- Validate audio before atomically committing cached speech.
- Resume interrupted jobs; cache key includes provider/model/voice/text/options.
- Avoid re-running successful speech when another segment fails.

## M4 — Audio composer

- Render distinct sentence, paragraph, speaker and attribution pauses.
- Common PCM intermediate format and optional speech-only output.
- Optional background music, loop, fade; no resynthesis for pause/music changes.
- Compare Baroque volume baseline with original Rapunzel demo.

## M5 — Configuration and CLI

- YAML voice profiles with provider per character; optional dependencies.
- Presets and friendly validation errors; stable `preview`/`render` interface.
- Document cost implications; never silently use paid provider as fallback.

## M6 — Integration and packaging

- Full Rapunzel audio listening regression against the original demo.
- Tests for dialogue, resume, cache and corrupted audio.
- Arch Linux and Windows smoke tests, README and packaging review.
- Choose release license before public publication.

## Design decision log

- 2026-11-04: Name finalized as **VoxBraid**.
- 2026-11-04: Scope limited to prepared TXT-to-audio; upstream extraction/manual AI separate.
- 2026-11-04: A book may use different TTS providers for different characters.
- 2026-11-04: Start with one Edge adapter, avoid installing PyTorch/BookNLP.
- 2026-11-04: Rapunzel baseline was satisfactory; keep it for local regression.
- 2026-11-04: M1: only offline parsing/planning; no premature `render` command.
