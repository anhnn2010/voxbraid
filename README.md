# VoxBraid

**Weave voices into stories.**

VoxBraid is a modular, multi-voice **prepared TXT -> audio** toolkit. It does
not extract PDFs/EPUBs, run OCR, clean book text, or infer speakers with AI.
Those tasks happen before VoxBraid. A single book may assign different TTS
providers to different roles; **M2 includes only the Edge TTS adapter**.

> **M2 checkpoint — v0.0.3.** `preview` works offline; `synthesize` creates
> separate per-segment speech clips plus `manifest.json` with roles, voices,
> text and *planned* pauses. **It does not yet join clips into one audiobook,
> add actual silence, mix music, retry socket errors, or resume from cache.**
> Those are reserved for M3/M4. Do not mistake the per-clip output for a
> completed audiobook.

## Install / update on Arch Linux (pyenv)

Extract the **M2 update ZIP at the root of the existing M1 git repository**;
it replaces only source/tests/docs, not `.git`, `.python-version`, or private
`local_samples/`. Use your existing `voxbraid` pyenv environment:

```bash
cd ~/Downloads/projects/voxbraid
pyenv version
python -m pip install -e '.[dev,edge]'
pyenv rehash
voxbraid --version
voxbraid doctor
python -m pytest -q
python -m ruff check .
```

Python 3.10+ is supported; Arch Linux and Windows should work. `edge-tts` is
installed by the optional `[edge]` extra; the core package and offline preview
do not require it. `ffmpeg` is **not needed for M2 synthesis**, but will be used
by the M4 composer. Since Edge TTS calls an online Microsoft Edge speech
service through a community library, it needs Internet access and can fail
when the service/network is unavailable.

## M2: synthesize a short sample

Start with **our original, synthetic forest dialogue**, not a full book:

```bash
voxbraid preview examples/forest_dialogue.txt --limit 12

voxbraid synthesize examples/forest_dialogue.txt \
  --voices examples/forest_voices.json \
  --max-segments 8 \
  --out-dir local_samples/forest_m2
```

You will get `segment_0001.mp3`, `segment_0002.mp3`, etc. and a `manifest.json`.
Each clip can be played separately with `mpv local_samples/forest_m2/segment_0001.mp3`
(or another audio player). The manifest preserves the clip order and metadata.
The planned pauses are **not inserted into the audio yet**.

To test the legacy Rapunzel source retained locally from M0:

```bash
voxbraid synthesize \
  local_samples/rapunzel_legacy/rapunzel_dialogue.txt \
  --voices examples/rapunzel_voices.template.json \
  --max-segments 8 \
  --out-dir local_samples/rapunzel_m2
```

**Do not generate all 77 clips yet unless you want to**: this milestone has no
retry or resume, so a socket error can interrupt the run. The private Rapunzel
TXT and its legacy script are **not included in the M2 update ZIP** and must
stay under the Git-ignored `local_samples/` directory.

On a repeat run, VoxBraid refuses to overwrite existing clips unless you
specify `--overwrite`, or select a new `--out-dir`. M3 will replace this simple
safety rule with automatic content-based caching and resume. For example:

```bash
voxbraid synthesize examples/forest_dialogue.txt \
  --voices examples/forest_voices.json \
  --out-dir local_samples/forest_m2 \
  --overwrite
```

### Plain TXT

```bash
voxbraid synthesize tests/fixtures/plain_story.txt \
  --max-segments 2 \
  --out-dir local_samples/plain_m2
```

Without a voice file, plain TXT uses default narrator `en-US-BrianNeural`
with rate `-10%`. Tagged text requires an explicit voice for **every role**;
VoxBraid will not silently read an undefined character in the narrator's
voice.

## Voice files and provider routing

M2 uses **JSON (standard library)** for voice profiles; YAML/presets will come
in M5. The role tags in TXT are unchanged from M1. Example:

```json
{
  "narrator": {"provider": "edge", "voice": "en-US-BrianNeural", "options": {"rate": "-10%"}},
  "prince": {"provider": "edge", "voice": "en-US-AndrewNeural", "options": {"rate": "-10%"}},
  "witch": {"provider": "edge", "voice": "en-US-EmmaNeural", "options": {"rate": "-10%"}},
  "rapunzel": {"provider": "edge", "voice": "en-US-AvaNeural", "options": {"rate": "-10%"}}
}
```

Edge supports `rate`, `pitch` and `volume` as strings compatible with the
`edge-tts` Python API. Different providers can have different options; the
core will not assume every provider supports the same parameters. **Other
provider IDs such as `kokoro` and `elevenlabs` do not work yet**: only an
adapter implementation registered in the runtime can be used.

Internally, each provider declares its native audio extension (currently
`.mp3` for Edge, potentially `.wav` for future local providers). M4 will
normalize and mix different formats to one final MP3. The test suite uses
fake providers to prove mixed-provider routing without installing GPU models
or using paid APIs.

## Commands

```bash
voxbraid --help
voxbraid doctor
voxbraid preview examples/forest_dialogue.txt --json
voxbraid synthesize --help
```

## Scope / roadmap

- **M0:** Python foundation and offline tests.
- **M1:** TXT parser, role markers, sentence/paragraph segmentation, preview.
- **M2 (this release):** provider protocol and registry, Edge TTS adapter,
  per-role voice JSON, per-segment synthesis and manifest.
- **M3:** retry/backoff, validated content-addressed cache, auto resume.
- **M4:** actual pauses, WAV normalization, voice mixing, music/loop/fade,
  single final audiobook.
- **M5:** user presets, YAML, refined stable `render` CLI, optional providers.
- **M6:** Arch/Windows integration tests, docs, release readiness.

See [M2 implementation notes](docs/m2_notes.md),
[TXT syntax](docs/text_format.md), and [full roadmap](docs/roadmap.md).

## Development and privacy

```bash
python -m pytest -q
python -m ruff check .
```

The unit tests run without Internet or Edge TTS by using fake providers. The
real Edge TTS smoke test is **manual on your Arch machine**; it is not run by
CI. Keep commercial/copyrighted story TXT, generated MP3s, API credentials and
local listening assets under `local_samples/`, which is ignored by Git.

**License:** not selected; decide before publishing as an open-source project.
