# M3 — Retry, Resume & Cache (v0.0.4)

## Scope

- **Only prepared TXT -> speech clips**. This milestone does not add OCR,
  EPUB/PDF input, automatic character detection, silence, background music, or
  a final combined audiobook. M4 adds audio composition.
- All M1 paragraph, dialogue, speaker, source-line and pause metadata survive
  in the successful `manifest.json`.
- All role/provider validation still happens before any online TTS request.

## Retry design

- A request gets **up to 5 total attempts by default** (1 initial + 4 retries).
- Exponential backoff: 2, 4, 8, 16 seconds **plus jitter**, capped at 30 seconds.
- Transient exceptions include socket/reset/timeouts, Edge `NoAudioReceived`,
  WebSocket disconnects, HTTP 429 and HTTP 5xx, empty/undecodable audio.
- Invalid voice/config, HTTP 401/403 and unknown providers are not retried.
- A failed attempt's temporary file is removed before retrying.
- `--retries 0` disables retries. Adjust using `--retry-base-delay` and
  `--retry-max-delay`. No automatic fallback to a paid provider or a different voice.

## Content-addressed cache

- Cache key: SHA-256 of exact segment text, provider ID, voice, sorted options,
  native audio extension, and adapter `cache_version` (default `"1"`).
- **Not** part of cache key: paragraph/sentence pause, speaker role name,
  book position, music. Changing these does not need a TTS request.
- Clips are synthesized into uniquely named temporary files **within the cache
  directory** so rename is atomic on the same filesystem.
- Require **FFprobe + FFmpeg** at runtime for actual clip validation. FFprobe
  verifies audio stream/duration; FFmpeg decodes the entire clip. This rejects
  empty and corrupt outputs instead of trusting file length alone.
- On success, the verified clip is atomically moved to its SHA-256 cache path;
  metadata tracks SHA-256 checksum, length and verified duration. Cache reads
  verify checksum and length. Corrupt or incomplete cache entries are misses.
- Default cache directory is `<out-dir>/.voxbraid_cache/`. Set `--cache-dir PATH`
  to use one shared cache across books/output directories.
- A provider adapter should bump `cache_version` if it changes its synthesis
  semantics (for example default sampling/model/voice interpretation).

## Safe resume and output management

- `.voxbraid_state.json` is updated atomically after each completed clip, with
  the cache key and SHA-256 of the output. Rerunning the same command verifies
  and skips matching clips (`RESUME`), even if a prior run failed halfway.
- If a previously generated clip is missing/corrupt but its cache is valid,
  restore it (`CACHE HIT`). If both are missing/corrupt, synthesize again.
- A new voice/text/engine key invalidates the corresponding clip only.
- A complete `manifest.json` is written **only when all requested clips pass**.
  Any new run removes an earlier success manifest before processing, so an
  interrupted/failed run cannot falsely claim completion.
- Files already present without checkpoint/cached provenance (e.g. M2 outputs)
  cannot be silently overwritten. Use a **new `--out-dir`** or `--overwrite`
  once to replace them. `--overwrite` explicitly forces fresh synthesis.
- Do not run two VoxBraid synthesize processes against the same `--out-dir`
  simultaneously; multi-process locking is outside M3.
- Cache state and manifest are generated data; `.gitignore` excludes them.

## CLI example (Arch Linux / pyenv)

```bash
python -m pip install -e '.[dev,edge]'
pyenv rehash
python -m pytest -q
python -m ruff check .
voxbraid doctor

# A new M3 output directory avoids replacing previous M2 clips.
voxbraid synthesize examples/forest_dialogue.txt \
  --voices examples/forest_voices.json \
  --out-dir local_samples/forest_m3

# Same command again: skips existing verified outputs (RESUME).
voxbraid synthesize examples/forest_dialogue.txt \
  --voices examples/forest_voices.json \
  --out-dir local_samples/forest_m3

# Share cache between outputs:
voxbraid synthesize examples/forest_dialogue.txt \
  --voices examples/forest_voices.json \
  --out-dir local_samples/forest_m3_second \
  --cache-dir local_samples/shared_cache
```

## Test coverage

- All prior M0/M1/M2 tests, updated for automatic resume semantics.
- Transient `ConnectionError` retry then success; exhaustion after bounded
  retries, with no stale success manifest and no leftover temp files.
- Resume after a mid-book failure; no repeated request for completed segments.
- Shared cache, duplicate sentences, changed voice, changed pause, changed
  adapter version, forced overwrite, and untracked legacy outputs.
- Corrupt cache checksum and corrupt output detection/repair.
- No retry for a permanent configuration error or HTTP 401/403; retry for
  HTTP 429/5xx and `NoAudioReceived`.
- Real WAV generation with Python stdlib + decode validation via FFmpeg/FFprobe.
- Actual **Edge online** synthesis should still be smoke-tested on Arch Linux;
  automated tests use fake providers and make **no network TTS requests**.

## M4 integration contract

- Speech files may be native `.mp3`, `.wav`, or other provider formats.
- The ordered, complete manifest carries `pause_kind`, `pause_before`, and
  voice/profile information for the future composer.
- Re-rendering a new pause/music mix consumes already synthesized clips; the
  audio composition step must not call TTS again.
