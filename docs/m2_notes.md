# M2 — TTS Provider Architecture (v0.0.3)

## Deliverable

- `src/voxbraid/tts/base.py`: `VoiceProfile` and asynchronous `TTSProvider` contract.
- `src/voxbraid/tts/registry.py`: explicit registry / dependency injection.
- `src/voxbraid/tts/edge.py`: optional Edge adapter; imports `edge_tts` only
  during synthesis, not at import time.
- `src/voxbraid/voices.py`: fail-fast JSON mapping of each role to its voice.
- `src/voxbraid/synthesis.py`: per-segment audio generation with a manifest.
- `voxbraid synthesize`: short clips / manual smoke testing on Arch Linux.
- Synthetic offline tests exercise routing, file writes and error cases.

## Why the CLI emits clips instead of a final audiobook

M2 validates the provider boundary and real Edge integration. The M1 planner
already computes pauses, but adding PCM conversion, silence insertion, FFmpeg
mixing and music at this point would overlap M4 and conceal adapter defects.
M2 therefore emits one native-format file per planned speech segment, plus
metadata showing how M4 should concatenate them.

## Native audio format

Providers implement `audio_extension`. Edge outputs `.mp3`; a future local
provider may output `.wav`. The eventual M4 composer decodes each segment into
one consistent PCM format. This avoids lying about codecs by naming all files
`.mp3` regardless of their actual contents.

## Error / overwrite behavior

- All voice roles and provider IDs are validated before any request.
- Unknown roles do not silently use narrator voice.
- Unknown provider is an error, never an automatic paid-service fallback.
- No retry or cache in M2; if Edge times out, stop and report the failing
  segment and its underlying error.
- Each native clip is first written as `*.partial`, then renamed on success.
- A zero-length output is an error. M3 will add decodability checks and cache.
- A full `manifest.json` is written only after all segments succeed.
- A rerun refuses conflicting output files unless `--overwrite` is explicit.
- A failed overwrite removes the stale success manifest; an interrupted run
  may leave completed audio segments in the folder. M3 will resume those jobs.

## Test plan (no Internet)

- Existing M0/M1 tests remain green.
- JSON config accepts different providers for different roles.
- Missing role stops before network or output directory creation.
- Unsupported Edge options fail before synthesis.
- Registry can route to fake Edge and fake local adapter in one story.
- Fake provider's native `.wav` extension is respected.
- Unsafe provider file extension is rejected.
- Output collisions fail unless `--overwrite` is explicit.
- Failure cleans `.partial` and leaves no success manifest.
- Empty audio and an invalid JSON config are caught.
- `edge-tts` Python API calls (`Communicate` / `save`) are mocked.
- CLI creates clips via fake provider and honors `--max-segments`.

## Manual acceptance on Arch Linux (Internet required)

1. `python -m pip install -e '.[dev,edge]'`.
2. `python -m pytest -q` and `python -m ruff check .`.
3. `voxbraid preview examples/forest_dialogue.txt`.
4. `voxbraid synthesize examples/forest_dialogue.txt --voices
   examples/forest_voices.json --max-segments 8 --out-dir local_samples/forest_m2`.
5. Listen to `segment_*.mp3` individually and check `manifest.json` for
   role, provider and voice mapping.
6. Repeat only with a new directory or `--overwrite`.

## Deferred to later milestones

- M3: retries for transient WebSocket errors, resumable validated cache.
- M4: actual intro/sentence/paragraph/speaker pauses; normalize audio;
  final mixed MP3; background music and fade.
- M5: YAML/presets/refined render interface and optional provider adapters.
