# VoxBraid

**Weave voices into stories.**

VoxBraid turns **already-prepared UTF-8 TXT** into multi-voice speech clips.
Preparing text from scanned pages/PDF/EPUB, OCR cleanup and AI character
assignment are **outside this repository**. A single book may choose a
provider/voice per role. Only **Edge TTS** is implemented today; the provider
interface allows future engines without installing GPU dependencies now.

> **M3 checkpoint — v0.0.4.** `preview` plans segments offline, while
> `synthesize` produces separate native speech clips and a complete
> `manifest.json` with speaker, voice, and **planned** pauses. M3 adds
> **bounded retries, safe resume, validated caching**. The program **does not
> yet combine clips into one MP3, insert actual pauses, or add background
> music**. That's the next milestone, M4.

## Install / update (Arch Linux with pyenv)

Unzip the **M3 update** into your existing, committed M2 repository. This
ZIP contains only changes to package/docs/tests and leaves your `.git`,
`.python-version` and private `local_samples/` untouched.

```bash
cd ~/Downloads/projects/voxbraid
unzip -o ~/Downloads/voxbraid_M3_update.zip -d .
python -m pip install -e '.[dev,edge]'
pyenv rehash
voxbraid --version                 # 0.0.4
voxbraid doctor                    # Check Python, FFmpeg, FFprobe, Edge TTS
python -m pytest -q
python -m ruff check .
```

**FFmpeg and FFprobe are required from M3 onward to validate audio, including
native Edge MP3.** If missing on Arch, run `sudo pacman -Syu ffmpeg` (avoid a
partial upgrade). Edge TTS still requires Internet.

## Try a short book

```bash
voxbraid synthesize examples/forest_dialogue.txt \
  --voices examples/forest_voices.json \
  --out-dir local_samples/forest_m3
```

The first successful run creates `segment_0001.mp3`, `segment_0002.mp3`, etc.
plus `.voxbraid_state.json`, `.voxbraid_cache/` and a complete
`manifest.json`. Individual clips can be played with `mpv` or another player.
Planned pauses are **metadata only**, not silence inserted into these clips.

**Run exactly the same command again:**

```bash
voxbraid synthesize examples/forest_dialogue.txt \
  --voices examples/forest_voices.json \
  --out-dir local_samples/forest_m3
```

It should print `RESUME` for every clip and finish with something like:

```text
New: 0 | Cache: 0 | Resumed: 7 | Retries: 0
```

If the network disconnects, VoxBraid automatically retries with capped
exponential backoff. If all retries for a segment fail, the successful
segments are checkpointed. **Rerun the same command later, without
`--overwrite`, to pick up where it stopped.**

To regenerate all clips deliberately, add `--overwrite`. To control retries:

```bash
voxbraid synthesize examples/forest_dialogue.txt \
  --voices examples/forest_voices.json \
  --out-dir local_samples/forest_m3 \
  --retries 5 \
  --retry-base-delay 2 \
  --retry-max-delay 30
```

**M2 migration:** If you run M3 against the **old**
`local_samples/forest_m2/` directory, VoxBraid will refuse to silently adopt
files without M3 checkpoint/cache records. Either choose a new output
directory (recommended above) or use `--overwrite` **once**. After that,
automatic resume works.

## Cache behavior

The default cache is local to `--out-dir`. To reuse generated speech across
multiple output directories, specify the same `--cache-dir`:

```bash
voxbraid synthesize examples/forest_dialogue.txt \
  --voices examples/forest_voices.json \
  --out-dir local_samples/forest_another \
  --cache-dir local_samples/shared_cache
```

A cache key depends on **text, provider, voice, native audio format, adapter
version and provider-specific settings**. It does **not** depend on segment
position, speaker role, paragraph/sentence gap or future background music.
Changing only pauses should update the manifest without calling TTS.
Changing the voice for one character regenerates only affected speech.
An invalid/corrupted cache entry gets regenerated instead of reused.

Once a clip is synthesized, FFprobe checks the stream/duration and FFmpeg
decodes it. Only validated clips are committed atomically to cache. A run
checkpoint records the output SHA-256 and prevents accidental reuse of the
wrong audio. The full success manifest is produced only after all clips
succeed. Running two synthesis commands against the **same output directory
at the same time** is not supported yet.

## Rapunzel regression (private local sample)

```bash
voxbraid preview \
  local_samples/rapunzel_legacy/rapunzel_dialogue.txt --limit 12

voxbraid synthesize \
  local_samples/rapunzel_legacy/rapunzel_dialogue.txt \
  --voices examples/rapunzel_voices.template.json \
  --max-segments 8 \
  --out-dir local_samples/rapunzel_m3
```

The voice template uses **Brian, Andrew, Emma and Ava**. Remove
`--max-segments 8` to synthesize the whole story; on a temporary socket
failure, completed clips are preserved and the next run resumes. Private
story TXT and generated clips remain under Git-ignored `local_samples/`.

## TXT format and CLI

Prepared plain TXT uses narrator voice. Speaker tags route the speech from
that point until the next tag:

```text
[narrator]
The fox walked into the forest.

[fox]
Can you help me?

[narrator:tag]
asked the fox.
```

Plain TXT defaults to Edge `en-US-BrianNeural` at `-10%`. Tagged files with
other roles require an explicit `--voices` JSON file. For example:

```json
{
  "narrator": {"provider": "edge", "voice": "en-US-BrianNeural", "options": {"rate": "-10%"}},
  "fox": {"provider": "edge", "voice": "en-US-AndrewNeural", "options": {"rate": "-10%"}}
}
```

Only provider-specific parameters supported by the selected provider are
accepted (`rate`, `volume`, `pitch` for Edge). Unknown provider/voice mappings
are an error; **VoxBraid never silently switches to a paid engine or voice**.

```bash
voxbraid --help
voxbraid doctor
voxbraid preview examples/forest_dialogue.txt --limit 10
voxbraid preview examples/forest_dialogue.txt --json
voxbraid synthesize --help
```

## Milestone progression

- M0: installable Python repo, CLI, baseline tests.
- M1: TXT parser, paragraph/sentence splitting, voice tags and offline preview.
- M2: optional Edge adapter, provider registry, segment files and manifest.
- **M3: bounded retry, integrity-checked cache, safe automatic resume.**
- M4: speech composition, real pauses and optional Baroque music/fades.
- M5: presets, YAML voice configs and polished `render` CLI.
- M6: listening regression, Arch/Windows integration, packaging/release.

For details see [M3 design and acceptance](docs/m3_notes.md),
[M2 provider design](docs/m2_notes.md), [TXT format](docs/text_format.md) and
[roadmap](docs/roadmap.md).

## Development / privacy

```bash
python -m pytest -q
python -m ruff check .
```

Offline tests use fake providers. **Real online Edge synthesis must be
confirmed on your Arch machine**; tests do not call Microsoft services. The
`.gitignore` protects generated clips, run states, manifests, and
`local_samples/`. License not yet selected: decide before publishing publicly.
