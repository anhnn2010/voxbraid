# M4 — Offline Audio Composer (v0.0.5)

## Design boundary

- `synthesize` performs TTS; `compose` accepts only an M3 `manifest.json`.
- `compose` does not import the TTS provider registry and does not synthesize.
- Any change to pauses or music affects just the composition pass.
- `compose --music FILE.mp3`: use exactly the file.
- `compose --music DIRECTORY`: choose exactly one (non-recursive) MP3 randomly
  from sorted filenames, with optional `--music-seed` for repeatable selection.
- A single selected track loops through the entire story. No shuffle between
  loops; no ducking or loudness normalization in M4.

## Timeline and intermediate format

Manifest `pause_kind` and `pause_before` are authoritative; an optional
CLI override of a pause category takes precedence. Each segment has exactly
one pause placed **before** its audio; that duration is quantized to the nearest
48,000-Hz audio frame. The composition layer never performs TXT parsing.

Before assembly, FFprobe identifies each clip and FFmpeg fully decodes it.
Audio clips are then decoded a second time, streamed through FFmpeg as stereo
48-kHz 16-bit PCM to a bounded-memory WAV writer. Silence consists of zero
PCM frames; the temporary WAV is encoded once to the final MP3. This is
slower than blind MP3 concatenation but avoids mixing native formats,
resampling incompatibilities and repeated lossy re-encoding.

When music is enabled, FFmpeg loops the selected MP3 with `-stream_loop -1`,
sets background gain, applies fades to music only, mixes it for precisely the
speech-stream duration and applies a mild limiter. Without music the speech
PCM goes straight to the MP3 encoder. The encoder can add padding; elapsed
file time is not necessarily bit-exact to the PCM duration.

## Error handling

- Strict manifest format and sequential index check.
- Reject manifest audio filenames with path separators or escaping symlinks.
- Reject missing/corrupted clips and invalid music before writing final output.
- Atomic rename after successful encode/validation; an existing output is
  not replaced if the FFmpeg process fails.
- Chosen music, paths, settings, and timeline are recorded in a Git-ignored
  `.compose.json` sidecar.
- Boundaries: WAV RIFF size limit (not yet chapter streaming), no automatic
  silence trimming, no user-facing normalization/ducking in M4.

## Acceptance tests (Arch + pyenv)

```bash
python -m pip install -e '.[dev,edge]'
pyenv rehash
python -m pytest -q
python -m ruff check .
voxbraid compose --help
voxbraid compose local_samples/forest_m3/manifest.json \
  -o local_samples/forest_speech.mp3
voxbraid compose local_samples/forest_m3/manifest.json \
  --music ~/Music/baroque/ --music-seed 42 \
  -o local_samples/forest_baroque.mp3
```

Check the log/sidecar for the selected track. Re-run with a different pause
or music track and verify no `synthesize` activity/network is triggered.
Compare the resulting complete Rapunzel recording with the legacy demo by ear.
