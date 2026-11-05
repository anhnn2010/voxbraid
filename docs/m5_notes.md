# M5 — Configuration and one-command render (v0.0.6)

## CLI design

`voxbraid render FILE.txt -o OUTPUT.mp3` is a composition of existing stages:

1. Read and validate the user configuration/preset (pure and offline).
2. Parse TXT and plan provider-independent speech segments.
3. Validate voice profiles against the provider registry **before writing files**.
4. Run the exact M3 `synthesize_segments` pipeline with retry and verified cache.
5. Run the exact M4 `compose_audiobook` pipeline. Never call TTS from composer.

`--dry-run` exits after step 3. `--max-segments N` is for quick demonstrations;
its manifest contains only selected segments. `--out-dir` defaults to
`OUTPUT.voxbraid/` and is Git-ignored. `--cache-dir` can be shared across runs.

## Configuration model

- Named built-in preset: `bedtime`; file presets may be YAML/JSON.
- Per-book `--config` may be YAML or JSON.
- `--voices` may be YAML or JSON and fully replaces the role mapping.
- Section keys: `voices`, `pauses`, `music`, `retry` with optional `version: 1`.
- Precedence: defaults → preset → book config → explicitly supplied CLI values.
- Music path from config resolves relative to config file, unless absolute or
  `~`-expanded; CLI music path follows shell/working-directory semantics.
- `--no-music` ignores configured music and seed for that run.
- Strict schema rejects unknown keys, invalid durations, booleans as numeric
  values, malformed YAML, and missing role mappings.
- Provider-specific `options` remain string-to-string; presets do not make
  any cloud vendor mandatory. `PyYAML` is a small core dependency, Edge TTS
  remains optional via `.[edge]`.
- The built-in `bedtime.yaml` ships inside the wheel via setuptools package
  data (verified in a wheel install, not only an editable checkout).

## Preserved M3/M4 guarantees

- Audio cache identity depends on speech/provider/voice/options, **not** music
  or gaps. Changing a pause recomposes, not resynthesizes.
- `--music FILE` selects it; `--music DIRECTORY` randomly selects one direct
  MP3 and loops it; seed makes selection repeatable.
- Speech clips are verified before being committed to the cache; failed
  composition cannot replace an existing complete output MP3.
- Music gain `0.04`, fade-in `2`, fade-out `5` remain the baseline.
- `render` does not silently fall back to a paid or alternative TTS provider.

## Acceptance (Arch Linux, pyenv)

```bash
python -m pip install -e '.[dev,edge]'
pyenv rehash
voxbraid --version       # 0.0.6
python -m pytest -q
python -m ruff check .
voxbraid render examples/forest_dialogue.txt \
  --preset bedtime --config examples/forest_book.yaml \
  --dry-run -o local_samples/forest_final.mp3
voxbraid render examples/forest_dialogue.txt \
  --preset bedtime --config examples/forest_book.yaml \
  -o local_samples/forest_final.mp3
# Re-run to inspect RESUME (no new Edge requests).
voxbraid render examples/forest_dialogue.txt \
  --preset bedtime --config examples/forest_book.yaml \
  -o local_samples/forest_final.mp3
```

Optional live acceptance: use `--music ~/Music/baroque/ --music-seed 42` to
listen to a random Baroque track, then rerun with different pauses and
confirm no additional network requests. The assistant runtime can test the
pipeline with a fake provider but not actual online Edge TTS.

## Explicitly outside M5

- No OCR, PDF/EPUB or AI character analysis.
- No new TTS providers, GUI, auto-loudness matching, ducking or batch mode.
- No global system config/magic file discovery, no credential management.
- M6 will handle public release, documentation polish and listening tests.
