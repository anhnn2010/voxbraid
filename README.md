# VoxBraid

**Weave voices into stories.**

VoxBraid turns **prepared UTF-8 TXT** into multi-voice MP3 audiobooks. It
supports manually tagged speakers, configurable sentence/paragraph/dialogue
pauses, optional Baroque music, and repeatable synthesis with retry and cache.
TXT extraction, OCR, EPUB/PDF processing and AI character detection are
**deliberately outside this repository**.

> **M5 checkpoint — v0.0.6.** `voxbraid render` can now run the complete
> TXT → speech clips → MP3 pipeline in one command. `preview`, `synthesize`,
> and `compose` remain separate commands. Only the **Edge TTS provider** is
> implemented today; the registry supports future providers per character.

## Upgrade M4 → M5 (Arch Linux + pyenv)

Extract the M5 incremental ZIP over the existing Git checkout. It does not
include `.git`, `.python-version`, personal story files or generated audio.

```bash
cd ~/Downloads/projects/voxbraid
unzip -o ~/Downloads/voxbraid_M5_update.zip -d .
python -m pip install -e '.[dev,edge]'
pyenv rehash
voxbraid --version         # 0.0.6
python -m pytest -q
python -m ruff check .
```

FFmpeg and FFprobe must be installed and available on `PATH`. Edge TTS is
online; `compose` and `render --dry-run` do not contact Microsoft.

## Single-command render

Generate a complete **speech-only** audiobook from an ordinary TXT file:

```bash
voxbraid render story.txt --preset bedtime -o story.mp3
```

For a **multi-voice** sample, use the supplied example configuration:

```bash
voxbraid render examples/forest_dialogue.txt \
  --preset bedtime \
  --config examples/forest_book.yaml \
  --dry-run \
  -o local_samples/forest_final.mp3
```

Remove `--dry-run` to actually generate MP3. The `--dry-run` option checks
text, speaker roles, provider names/voice settings, and prints the plan
without creating directories or calling TTS.

Add an explicit music MP3 or a folder of tracks:

```bash
voxbraid render examples/forest_dialogue.txt \
  --preset bedtime \
  --config examples/forest_book.yaml \
  --music ~/Music/baroque/ \
  --music-seed 42 \
  --music-volume 0.04 \
  --speech-output local_samples/forest_speech.mp3 \
  -o local_samples/forest_baroque.mp3
```

**Music rules:** `--music file.mp3` uses exactly that file; a directory
randomly selects **one direct-child MP3** and loops it throughout the story.
`--music-seed` makes folder selection reproducible, but is optional. A file
without a music argument results in speech-only MP3. Existing M4 `compose`
behavior is unchanged, including 2s/5s music fades and the default 0.04
background gain. `--no-music` ignores music in the book config.

### Where are the generated clips?

By default, `render -o local_samples/story.mp3` keeps reusable speech clips
in `local_samples/story.voxbraid/`. Use `--out-dir` to choose a folder, or
`--cache-dir` to share clips across books/runs. The final audiobook goes to
`-o` and its selected music/pauses are recorded in an adjacent
`.compose.json` sidecar. The sidecar and audio are Git-ignored.

- Run the same command again: successful clips **RESUME** without TTS calls.
- Modify one sentence or character voice: only affected clips resynthesize.
- Change music, fades or pauses: already synthesized speech is reused.
- Network/`NoAudioReceived`: M3 retry policy remains active (default **4
  retries after the first request**). No automatic fallback to a paid provider.
- `--max-segments 8` creates a quick, intentionally partial audiobook.
- `--overwrite` deliberately forces TTS for every selected segment.

## TXT and voice configuration

A plain TXT uses the default narrator voice **Brian** at rate **-10%**.
Speaker tags are simple labels; character inference is performed upstream:

```text
[narrator]
One day, a prince came to the tower.

[prince]
Rapunzel, Rapunzel, let down your hair!

[narrator:tag]
said the prince.
```

Create a **book configuration** in YAML, containing any of these sections:

```yaml
version: 1
voices:
  narrator:
    provider: edge
    voice: en-US-BrianNeural
    options:
      rate: "-10%"
  prince:
    provider: edge
    voice: en-US-AndrewNeural
pauses:
  intro: 3.0
  sentence: 1.5
  paragraph: 3.0
  speaker: 1.0
  attribution: 0.4
  lead: 0.6
music:
  # Optional: path relative to this YAML, or absolute / ~
  # source: music/baroque/
  volume: 0.04
  fade_in: 2.0
  fade_out: 5.0
retry:
  retries: 4
  base_delay: 2.0
  max_delay: 30.0
```

Use it with `--config book.yaml`. You may also supply a standalone
**role-to-voice** JSON *or* YAML with `--voices voices.yaml`. `--voices`
**replaces** the book's entire voice mapping; the program does not silently
assign an unknown character the narrator's voice. A book can assign distinct
providers per role, but only `edge` has an implemented adapter in M5.

**Configuration priority:** built-in defaults < `--preset bedtime` (or a
custom YAML/JSON preset path) < `--config` book config < explicit CLI flags.
The built-in bedtime preset preserves the validated 3s intro, 1.5s sentence
pause, 3s paragraph pause, and 0.04 music gain. Custom book YAML is loaded
with safe YAML parsing; unknown keys and invalid values fail loudly.

## Advanced: keep TTS and composing separate

```bash
# 1. Create/reuse individual TTS clips.
voxbraid synthesize examples/forest_dialogue.txt \
  --voices examples/forest_voices.json \
  --out-dir local_samples/forest_m5

# 2. Compose without TTS/network calls.
voxbraid compose local_samples/forest_m5/manifest.json \
  --music ~/Music/baroque/ --music-seed 42 \
  -o local_samples/forest_baroque.mp3

# 3. Inspect the TXT plan without synthesis.
voxbraid preview examples/forest_dialogue.txt --limit 20
```

The M4 composer takes native speech clips and converts them to streamed
48-kHz stereo PCM before exporting MP3. Separate sentence, paragraph,
speaker, attribution, and lead pauses are kept in the manifest. No
AI/NLP dependency, voice cloning or audio ducking is required.

## Roadmap and safety notes

- **M0–M4:** foundation, parser/planner, Edge adapter, retry/cache, composer.
- **M5:** one-command `render`, configuration/presets, YAML voice profiles.
- **M6:** Arch/Windows smoke tests, Rapunzel listening regression, release review.

The original Rapunzel story and demo remain local under `local_samples/`
and must not be committed to a public repository. Any external paid provider
added later must be explicitly configured; VoxBraid never silently swaps
providers after errors. FFmpeg produces an intermediate WAV, which uses disk
space and has a size limit for very long books; future chapter batching may
address this. Avoid running simultaneous renders with the same output folder.

For implementation and acceptance details, see
[docs/m5_notes.md](docs/m5_notes.md), [docs/m4_notes.md](docs/m4_notes.md),
[docs/text_format.md](docs/text_format.md), and
[docs/roadmap.md](docs/roadmap.md).

License has not yet been chosen; choose one before publishing publicly.
