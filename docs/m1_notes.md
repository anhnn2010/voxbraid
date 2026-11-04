# M1 delivery notes

**Checkpoint:** M1 TXT Parser & Segment Planner (`voxbraid 0.0.2`).

**Scope:** offline parsing and previews. No TTS requests, audio output,
network access, speaker inference, OCR, PDF/EPUB support or music mixing.

## Acceptance checks

1. `voxbraid --version` shows `0.0.2`.
2. `voxbraid preview tests/fixtures/plain_story.txt` lists sentence/paragraph pauses.
3. `voxbraid preview tests/fixtures/multivoice_story.txt --json` outputs roles
   including `fox` and `bird`, and the narrator attribution pause.
4. If local M0 samples are present, `voxbraid preview
   local_samples/rapunzel_legacy/rapunzel_dialogue.txt --limit 12` reports
   `Mode: tagged | Paragraphs: 47 | Segments: 77`.
5. `python -m pytest -q` passes the offline test suite.
6. `python -m ruff check .` passes (requires the optional `dev` extra).

**Checked in the assistant's environment:** 51 pytest tests passed, the
Rapunzel regression count was 77, and syntax compilation passed.
Ruff was **not available in that environment**, so lint success is pending
verification on the user's machine.

## Apply to existing M0 repo

Extract `voxbraid_M1_update.zip` **inside the existing repository root**.
All paths are relative to that root; no outer directory is included.
The ZIP only updates sources, tests, docs, example, project metadata,
and `.gitignore`. The user's `.git`, `.python-version`, and `local_samples/`
are intentionally not included.

```bash
python -m pip install -e '.[dev]'
pyenv rehash
python -m pytest -q
python -m ruff check .
```

Only after verification, review the staging list and make the M1 commit:

```bash
git status
git add .
git status
git commit -m "feat: add offline TXT parser and segment preview (M1)"
```
