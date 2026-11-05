# VoxBraid M6 — integration checks and release candidate

**Version:** `0.0.7`. M6 is an acceptance checkpoint and packaging review,
**not an approved public v1.0 release**.

## What changed since M5

- New `tests/test_release_integration.py`: required offline end-to-end tests
  with **real** WAV and MP3 from two separate mock TTS providers. This checks
  per-role provider routing, FFmpeg conversion, and final audiobook decoding.
- Checks music-folder selection with seed, very short looped background MP3,
  speech-only export, and repeat render without extra synthesis.
- Changing sentence pauses should recompose without TTS; changing a voice
  should synthesize only its affected segments.
- A broken music input must not replace a previously valid final MP3.
- GitHub Actions now installs and verifies FFmpeg/FFprobe before executing
  audio tests on Linux and Windows. Builds an installable wheel.
- No behavior changes to the M5 `render`, `preview`, `synthesize`, `compose`
  user commands, except the updated package version and `doctor` text.

## Arch Linux acceptance (pyenv)

Run **from the existing VoxBraid checkout**, with the `voxbraid` pyenv
virtualenv selected:

```bash
cd ~/Downloads/projects/voxbraid
unzip -o ~/Downloads/voxbraid_M6_update.zip -d .
pyenv version
python -m pip install -e '.[dev,edge]'
pyenv rehash
voxbraid --version        # expected: 0.0.7
voxbraid doctor
python -m pytest -q       # release suite + M0-M5 tests
python -m ruff check .
```

Verify the M6 tests were **not skipped**; they require FFmpeg/FFprobe:

```bash
python -m pytest tests/test_release_integration.py -q
ffmpeg -version
ffprobe -version
```

### Actual Edge TTS and listening acceptance

Use the **user-owned local Rapunzel TXT**, not a copy checked into Git.
The `bedtime` preset uses the current sentence/paragraph pause defaults;
compare it against the old demo and adjust with CLI flags if needed.

```bash
voxbraid render \
  local_samples/rapunzel_legacy/rapunzel_dialogue.txt \
  --preset bedtime \
  --voices examples/rapunzel_voices.template.json \
  --max-segments 8 \
  --dry-run \
  -o local_samples/rapunzel_m6_sample.mp3
```

If the plan looks correct, remove `--dry-run` and listen to the short MP3.
Next, render the full story (omit `--max-segments`), optionally adding a
single Baroque MP3 or a music directory:

```bash
voxbraid render \
  local_samples/rapunzel_legacy/rapunzel_dialogue.txt \
  --preset bedtime \
  --voices examples/rapunzel_voices.template.json \
  --music ~/Music/baroque/ \
  --music-volume 0.04 \
  -o local_samples/rapunzel_m6_full.mp3
```

Check the following *by listening*, because offline unit tests cannot
validate the online voices' expressiveness:

- Narrator/witch/prince/Rapunzel voices are mapped as intended, no misplaced
  dialogue attribution or cut-off words.
- Different sentence, paragraph and attribution gaps sound natural.
- Background music does not overpower speech; chosen song is in the
  adjacent `.compose.json`, as is the actual timeline.
- The ending music fades without continuing after the final spoken word.
- Run the **same command again**: expect a wholly resumed/cached synthesis;
  change `--paragraph-gap 4` and confirm no new TTS calls.
- Interrupt a long run, re-run without `--overwrite`, and confirm successful
  segments are preserved. Simulating a socket error is **not required**;
  retry behavior is covered by offline tests.

## Windows compatibility acceptance

On Windows with a supported Python version, run:

```powershell
py -m pip install -e ".[dev,edge]"
py -m pytest -q
py -m ruff check .
py -m voxbraid doctor
py -m voxbraid preview examples/forest_dialogue.txt --limit 4
```

FFmpeg and FFprobe must be available on `PATH`. Also confirm that the GitHub
Actions Windows CI job is green; the assistant's local environment is Linux
and **cannot itself verify the hosted Windows workflow completed**.

## Packaging review

- The wheel must include `voxbraid/presets/bedtime.yaml`.
- No original Rapunzel story, generated speech/MP3 or local cache should be
  included in the tracked sources or downloadable ZIP.
- `.python-version` and `local_samples/` remain untracked.
- `voxbraid --help`, `--version`, `doctor`, `preview` remain functional.
- No silent fallback from Edge TTS to a paid service.
- FFmpeg WAV intermediate has a size limit for very long books: chapter
  batching may be needed later. Avoid two concurrent renders in the same
  output directory.
- A public release **needs a user-selected license** and a decision on
  distributing code that invokes the unofficial online Edge TTS service.
  Do not assume that `edge-tts` provides commercial usage rights.

## Commit and release decision

When Arch checks, Ruff and the listening regression are satisfactory:

```bash
git status
git add .
git commit -m 'test: validate offline audiobook pipeline and release checks (M6)'
```

**Do not tag v1.0.0 or publish to PyPI yet.** Mark the candidate as accepted
only after a clean CI run, a satisfactory Rapunzel listening comparison, and
license/usage terms have been reviewed.
