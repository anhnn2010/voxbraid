# VoxBraid

**Weave voices into stories.**

VoxBraid turns **already-prepared UTF-8 TXT** into multi-voice audiobooks. It
supports manually assigned characters; TXT extraction, OCR, PDF/EPUB handling
and AI speaker inference are intentionally **out of scope**. Each character can
use a different TTS provider; only optional **Edge TTS** is implemented so far.

> **M4 checkpoint — v0.0.5.** `preview` plans the text offline, `synthesize`
> generates independently cached speech clips with retry/resume (M3), and the
> new **`compose`** command assembles a finished MP3. It inserts real pauses,
> optionally mixes an MP3 music track with looping and fades, and **never calls
> Edge TTS**. `render`/presets/YAML are planned for M5.

## Upgrade from M3 (Arch Linux with pyenv)

Unzip the **M4 update ZIP** into your existing M3 repo. It contains only
source, tests and docs, not your `.git`, `.python-version` or local audio.

```bash
cd ~/Downloads/projects/voxbraid
unzip -o ~/Downloads/voxbraid_M4_update.zip -d .
python -m pip install -e '.[dev,edge]'
pyenv rehash
voxbraid --version  # 0.0.5
voxbraid doctor
python -m pytest -q
python -m ruff check .
```

**FFmpeg and FFprobe** must be on `PATH`. The `compose` command runs offline
once the speech clips are present; Edge TTS needs Internet only when using
`synthesize`.

## Quick start: from TXT to finished audio

First synthesize a prepared TXT into independent speech clips:

```bash
voxbraid synthesize examples/forest_dialogue.txt \
  --voices examples/forest_voices.json \
  --out-dir local_samples/forest_m4
```

Then compose the clips into a speech-only audiobook:

```bash
voxbraid compose local_samples/forest_m4/manifest.json \
  -o local_samples/forest_speech.mp3
```

Add **one specific MP3 music file**:

```bash
voxbraid compose local_samples/forest_m4/manifest.json \
  --music ~/Music/baroque/bach.mp3 \
  --music-volume 0.04 --fade-in 2 --fade-out 5 \
  -o local_samples/forest_baroque.mp3
```

Or provide a **directory**: one MP3 file is chosen randomly from its immediate
contents (not subfolders), then looped as needed until the story ends:

```bash
voxbraid compose local_samples/forest_m4/manifest.json \
  --music ~/Music/baroque/ \
  --music-seed 42 \
  --speech-output local_samples/forest_speech_only.mp3 \
  -o local_samples/forest_random_music.mp3
```

`--music-seed` is optional. With the same seed and the same set of MP3
filenames, selection is reproducible; without a seed each `compose` chooses a
new random track. An explicit music file always uses that exact file. The
selected path appears in CLI output and in an output sidecar,
`forest_random_music.compose.json` (Git-ignored because it contains local
paths). If music is shorter than the story, the **chosen track** is looped,
not replaced by another random track. Mixing ends with the speech timeline;
fade-out affects only background music, not speech. Default background gain is
`0.04`, matching the earlier Baroque experiment.

## Change pauses without another TTS request

The M3 manifest records `pause_kind` and `pause_before` for each segment.
`compose` uses the recorded duration unless you override it:

```bash
voxbraid compose local_samples/forest_m4/manifest.json \
  --intro 3 \
  --sentence-gap 1.5 \
  --paragraph-gap 3 \
  --speaker-gap 1 \
  --attribution-gap 0.4 \
  --lead-gap 0.6 \
  -o local_samples/forest_custom_pauses.mp3
```

Each segment receives **one** pause, classified by the M1 planner. Paragraph
and sentence pauses do not add together. `compose` does not alter input clips,
cache, checkpoint files or the manifest. You can create as many mixes as you
like from a single set of speech clips.

**Audio handling:** clips are fully decoded/checked with FFmpeg and FFprobe;
then audio is streamed into a temporary **48 kHz, stereo, 16-bit PCM WAV** with
sample-counted silence. FFmpeg encodes MP3 **once** at the end. This is a
provider-neutral interface, so future providers can output different native
formats. Default speech gain is unmodified; when music is present the mixed
output uses a limiter to prevent clipping. Automatic loudness normalization
and ducking are intentionally postponed until we've listened to more books.

The WAV intermediary uses local disk space and the standard WAV size limit;
very long books may need chapter-by-chapter rendering in the future. M4 does
not trim natural silence within individual provider clips.

## Run Rapunzel using existing M3 clips

If you already synthesized Rapunzel with M3, you do **not** need to generate
new speech clips:

```bash
voxbraid compose local_samples/rapunzel_m3/manifest.json \
  --music ~/Music/baroque/ \
  --music-seed 42 \
  -o local_samples/rapunzel_m4.mp3
```

The prepared Rapunzel story and generated audio live under Git-ignored
`local_samples/`; do not add copyrighted book content to public releases.

## Safety and reproducibility

- The manifest must be a complete `voxbraid-synthesis-v1` manifest. Missing,
  corrupted and unsafe/outside-folder audio paths are rejected.
- Inputs are checked before composing. Partial FFmpeg results are written in a
  temporary directory and cannot replace an existing final MP3 on failure.
- `--music` accepts only a `.mp3` file or a folder with direct `.mp3` children;
  empty folders and unsupported files fail with a clear message.
- No silent changes of TTS voice or provider; no network calls during compose.
- Music metadata is for reproducibility. Recreating the exact **audio bytes**
  is not guaranteed across FFmpeg versions or changed music files.
- Concurrent compose operations targeting the same output filename are not
  supported. Output MP3 and optional speech-only MP3 are replaced individually
  only after each is completely encoded and validated.

## Developer notes and roadmap

```bash
voxbraid preview examples/forest_dialogue.txt --limit 10
voxbraid synthesize --help
voxbraid compose --help
python -m pytest -q
python -m ruff check .
```

Offline unit/integration tests include real WAV/MP3 audio composed by FFmpeg;
they **never contact the Edge service**. Additional details are in
[docs/m4_notes.md](docs/m4_notes.md), [docs/text_format.md](docs/text_format.md)
and [docs/roadmap.md](docs/roadmap.md).

- M0: Python project/CLI foundation.
- M1: TXT parser/segment planner/preview.
- M2: Edge TTS provider abstraction and clips/manifest.
- M3: retry, resumable synthesis, validated cache.
- **M4: speech composer, actual pauses, optional music and fade.**
- M5: polished `render`, presets and configuration.
- M6: end-to-end listening regression and release.

License not yet selected: choose before publishing publicly.
