"""VoxBraid CLI: prepare, synthesize, compose and one-command render."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from voxbraid import __version__
from voxbraid.composer import PauseOverrides, compose_audiobook
from voxbraid.diagnostics import collect_diagnostics
from voxbraid.parser import TextFormatError, parse_file
from voxbraid.planner import PauseOptions, plan_segments
from voxbraid.retry import RetryPolicy
from voxbraid.settings import SettingsError, load_render_settings
from voxbraid.synthesis import _prepare, synthesize_segments
from voxbraid.tts.registry import default_registry
from voxbraid.voices import VoiceConfigError, load_voices


def _pause_arguments(command: argparse.ArgumentParser, *, explicit_only: bool = False) -> None:
    for arg, default, help_text in (
        ("intro", 3.0, "Initial silence (seconds)"),
        ("sentence", 1.5, "Pause between sentences in one paragraph"),
        ("paragraph", 3.0, "Pause between paragraphs of the same voice"),
        ("speaker", 1.0, "Pause when changing speakers"),
        ("attribution", 0.4, "Pause around a [narrator:tag]"),
        ("lead", 0.6, "Pause after a [narrator:lead]"),
    ):
        flag = f"--{arg}-gap" if arg != "intro" else "--intro"
        command.add_argument(
            flag, type=float, default=None if explicit_only else default, help=help_text
        )


def _options(args: argparse.Namespace) -> PauseOptions:
    return PauseOptions(
        intro=args.intro,
        sentence=args.sentence_gap,
        paragraph=args.paragraph_gap,
        speaker=args.speaker_gap,
        attribution=args.attribution_gap,
        lead=args.lead_gap,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voxbraid",
        description="VoxBraid: plan TXT, synthesize speech clips, and compose audiobooks.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subcommands = parser.add_subparsers(dest="command", metavar="COMMAND")
    subcommands.add_parser("doctor", help="Inspect Python and optional audio tools (offline).")

    preview = subcommands.add_parser("preview", help="Plan a TXT book without any TTS calls.")
    preview.add_argument("input", type=Path, help="Prepared UTF-8 TXT file")
    preview.add_argument("--json", action="store_true", help="Output the plan as JSON")
    preview.add_argument("--limit", type=int, help="Display only the first N segments")
    _pause_arguments(preview)

    synthesize = subcommands.add_parser(
        "synthesize",
        help="Generate separately cached speech clips and manifest (M3).",
    )
    synthesize.add_argument("input", type=Path, help="Prepared UTF-8 TXT file")
    synthesize.add_argument(
        "--voices", type=Path, help="Optional JSON mapping roles to provider/voice profiles"
    )
    synthesize.add_argument(
        "--out-dir", type=Path, required=True, help="Directory for speech clips and manifest.json"
    )
    synthesize.add_argument(
        "--max-segments", type=int, help="Generate only the first N segments for a quick test"
    )
    synthesize.add_argument(
        "--overwrite", action="store_true", help="Force new synthesis and replace previous clips"
    )
    synthesize.add_argument(
        "--cache-dir", type=Path, help="Shared cache path (default: <out-dir>/.voxbraid_cache)"
    )
    synthesize.add_argument(
        "--retries", type=int, default=4, help="Retry temporary errors N times (default 4)"
    )
    synthesize.add_argument(
        "--retry-base-delay", type=float, default=2.0,
        help="Initial retry delay in seconds (default 2; exponential backoff)",
    )
    synthesize.add_argument(
        "--retry-max-delay", type=float, default=30.0,
        help="Maximum retry delay in seconds (default 30)",
    )
    _pause_arguments(synthesize)

    compose = subcommands.add_parser(
        "compose", help="Compose an M3 manifest into an MP3 (offline; never calls TTS)."
    )
    compose.add_argument("manifest", type=Path, help="Complete M3 manifest.json")
    compose.add_argument("-o", "--output", type=Path, required=True, help="Final audiobook MP3")
    compose.add_argument(
        "--music", type=Path,
        help="Specific MP3 file, or folder to randomly select one MP3 (no recursion)",
    )
    compose.add_argument(
        "--music-seed", type=int,
        help="Reproducible random selection when --music is a folder",
    )
    compose.add_argument(
        "--music-volume", type=float, default=0.04,
        help="Background music volume multiplier (0..1; default 0.04)",
    )
    compose.add_argument(
        "--fade-in", type=float, default=2.0,
        help="Music fade-in seconds (default 2)",
    )
    compose.add_argument(
        "--fade-out", type=float, default=5.0,
        help="Music fade-out seconds (default 5)",
    )
    compose.add_argument(
        "--speech-output", type=Path,
        help="Also export speech-only MP3 when mixing music",
    )
    for kind in ("intro", "sentence", "paragraph", "speaker", "attribution", "lead"):
        flag = "--intro" if kind == "intro" else f"--{kind}-gap"
        compose.add_argument(flag, type=float, default=None,
                             help=f"Override {kind} pause, in seconds")
    render = subcommands.add_parser(
        "render", help="Render prepared TXT to one MP3 (synthesize + compose).",
    )
    render.add_argument("input", type=Path, help="Prepared UTF-8 TXT file")
    render.add_argument("-o", "--output", type=Path, required=True, help="Final audiobook MP3")
    render.add_argument("--preset", help="Built-in 'bedtime' or path to YAML/JSON preset")
    render.add_argument("--config", type=Path, help="Book YAML/JSON configuration")
    render.add_argument("--voices", type=Path, help="Override all voice profiles from JSON/YAML")
    render.add_argument("--out-dir", type=Path, help="Reusable speech clips directory")
    render.add_argument("--cache-dir", type=Path, help="Shared TTS cache directory")
    render.add_argument("--max-segments", type=int, help="Only first N speech segments (demo)")
    render.add_argument("--overwrite", action="store_true", help="Re-synthesize every segment")
    render.add_argument("--dry-run", action="store_true", help="Preview plan; no TTS or files")
    render.add_argument("--retries", type=int, help="Retry transient synthesis failures N times")
    render.add_argument("--retry-base-delay", type=float, help="Initial retry delay in seconds")
    render.add_argument("--retry-max-delay", type=float, help="Maximum retry delay in seconds")
    music_selector = render.add_mutually_exclusive_group()
    music_selector.add_argument("--music", type=Path, help="MP3 or folder to select random MP3")
    music_selector.add_argument("--no-music", action="store_true", help="Ignore configured music")
    render.add_argument("--music-seed", type=int, help="Stable music selection from a folder")
    render.add_argument("--music-volume", type=float, help="Background music gain (0..1)")
    render.add_argument("--fade-in", type=float, help="Music fade-in seconds")
    render.add_argument("--fade-out", type=float, help="Music fade-out seconds")
    render.add_argument("--speech-output", type=Path, help="Also write a speech-only MP3")
    _pause_arguments(render, explicit_only=True)
    return parser


def _render(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.max_segments is not None and args.max_segments < 1:
        parser.error("--max-segments must be a positive integer")
    if args.output.suffix.lower() != ".mp3":
        parser.error("--output must have .mp3 extension")
    override = {
        **{name: getattr(args, name if name == "intro" else f"{name}_gap")
           for name in ("intro", "sentence", "paragraph", "speaker", "attribution", "lead")},
        "music_source": args.music,
        "no_music": args.no_music,
        "music_seed": args.music_seed,
        "music_volume": args.music_volume,
        "fade_in": args.fade_in,
        "fade_out": args.fade_out,
        "retries": args.retries,
        "retry_base_delay": args.retry_base_delay,
        "retry_max_delay": args.retry_max_delay,
    }
    try:
        settings = load_render_settings(
            preset=args.preset, config=args.config, voices=args.voices, overrides=override,
        )
        if args.speech_output is not None and settings.music.source is None:
            raise SettingsError("--speech-output requires background music")
        doc = parse_file(args.input)
        segments = plan_segments(doc, settings.pauses)
        selected = segments[:args.max_segments] if args.max_segments is not None else segments
        output_dir = (args.out_dir if args.out_dir is not None
                      else args.output.with_suffix(".voxbraid"))
        registry = default_registry()
        # Validate role mappings, provider-specific settings, and extensions before
        # any output directory is created or any remote TTS call is attempted.
        _prepare(selected, settings.voices, output_dir, registry)
        if args.dry_run:
            print(f"Plan: {doc.mode} TXT | {len(doc.paragraphs)} paragraphs | "
                  f"{len(selected)} segments")
            print(f"Audio: {args.output} | Speech clips: {output_dir}")
            for role in sorted({seg.role for seg in selected}):
                profile = settings.voices[role]
                print(f"[{role}] {profile.provider}:{profile.voice}")
            print(f"Music: {settings.music.source or 'none'}")
            print("Dry run only — no TTS call, audio files or directories created.")
            return 0
        speech = asyncio.run(synthesize_segments(
            selected, settings.voices, output_dir, registry,
            overwrite=args.overwrite, cache_dir=args.cache_dir, retry_policy=settings.retry,
        ))
        music = settings.music
        composition = compose_audiobook(
            speech.manifest, args.output,
            music_source=music.source, music_seed=music.seed,
            music_volume=music.volume, fade_in=music.fade_in,
            fade_out=music.fade_out, speech_output=args.speech_output,
        )
    except (OSError, UnicodeError, TextFormatError, VoiceConfigError, SettingsError,
            ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(f"Rendered {composition.segments} clips -> {composition.output}")
    print(f"New: {speech.generated} | Cache: {speech.cached} | "
          f"Resumed: {speech.resumed} | Retries: {speech.retried}")
    print(f"Music: {composition.music if composition.music else 'none'}")
    print(f"Speech clips: {speech.output_dir}")
    print(f"Composition metadata: {composition.metadata}")
    if composition.speech_output:
        print(f"Speech-only: {composition.speech_output}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "doctor":
        for check in collect_diagnostics():
            status = "OK" if check.available else "MISSING"
            print(f"[{status}] {check.name}: {check.detail}")
        print("M5: render TXT -> MP3; compose remains offline.")
        return 0
    if args.command == "render":
        return _render(args, parser)
    if args.command in {"preview", "synthesize"}:
        if args.command == "preview" and args.limit is not None and args.limit < 1:
            parser.error("--limit must be a positive integer")
        if args.command == "synthesize" and (
            args.max_segments is not None and args.max_segments < 1
        ):
            parser.error("--max-segments must be a positive integer")
        try:
            document = parse_file(args.input)
            segments = plan_segments(document, _options(args))
        except (OSError, UnicodeError, TextFormatError, ValueError) as exc:
            parser.error(str(exc))

        if args.command == "preview":
            visible = segments[:args.limit] if args.limit is not None else segments
            if args.json:
                print(json.dumps({
                    "input": str(args.input),
                    "mode": document.mode,
                    "paragraphs_total": len(document.paragraphs),
                    "segments_total": len(segments),
                    "segments": [asdict(item) for item in visible],
                }, ensure_ascii=False, indent=2))
                return 0
            print(f"Mode: {document.mode} | Paragraphs: {len(document.paragraphs)} | "
                  f"Segments: {len(segments)}")
            for seg in visible:
                line_range = (
                    str(seg.line_start) if seg.line_start == seg.line_end
                    else f"{seg.line_start}-{seg.line_end}"
                )
                print(f"{seg.index:>3}. +{seg.pause_before:g}s {seg.pause_kind:<11} "
                      f"[{seg.role}{':' + seg.kind if seg.kind != 'normal' else ''}] "
                      f"L{line_range} | {seg.text}")
            if args.limit is not None and args.limit < len(segments):
                print(f"... showing {len(visible)} of {len(segments)} segments")
            print("Preview only — no TTS request or audio file created.")
            return 0

        selected = (
            segments[:args.max_segments] if args.max_segments is not None else segments
        )
        try:
            policy = RetryPolicy(
                retries=args.retries,
                base_delay=args.retry_base_delay,
                max_delay=args.retry_max_delay,
            )
            profiles = load_voices(args.voices)
            result = asyncio.run(synthesize_segments(
                selected, profiles, args.out_dir, default_registry(),
                overwrite=args.overwrite, cache_dir=args.cache_dir, retry_policy=policy,
            ))
        except (OSError, UnicodeError, VoiceConfigError, ValueError, RuntimeError) as exc:
            parser.error(str(exc))
        print(f"Completed {len(result.clips)} speech clips in {result.output_dir}")
        print(f"New: {result.generated} | Cache: {result.cached} | "
              f"Resumed: {result.resumed} | Retries: {result.retried}")
        print(f"Sequence and pause metadata: {result.manifest}")
        print("To assemble an audiobook: voxbraid compose <out-dir>/manifest.json -o book.mp3")
        return 0
    if args.command == "compose":
        try:
            pauses = PauseOverrides(
                intro=args.intro,
                sentence=args.sentence_gap,
                paragraph=args.paragraph_gap,
                speaker=args.speaker_gap,
                attribution=args.attribution_gap,
                lead=args.lead_gap,
            )
            result = compose_audiobook(
                args.manifest, args.output, pauses=pauses,
                music_source=args.music, music_seed=args.music_seed,
                music_volume=args.music_volume, fade_in=args.fade_in,
                fade_out=args.fade_out, speech_output=args.speech_output,
            )
        except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
            parser.error(str(exc))
        print(f"Composed {result.segments} speech clips -> {result.output}")
        print(f"Audio duration: {result.duration:.2f}s | "
              f"Speech timeline: {result.speech_duration:.2f}s")
        print(f"Music: {result.music if result.music else 'none'}")
        if result.speech_output is not None:
            print(f"Speech-only: {result.speech_output}")
        print(f"Composition metadata: {result.metadata}")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
