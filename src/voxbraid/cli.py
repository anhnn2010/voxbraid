"""VoxBraid CLI: offline preview and M2 per-segment speech synthesis."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from voxbraid import __version__
from voxbraid.diagnostics import collect_diagnostics
from voxbraid.parser import TextFormatError, parse_file
from voxbraid.planner import PauseOptions, plan_segments
from voxbraid.synthesis import synthesize_segments
from voxbraid.tts.registry import default_registry
from voxbraid.voices import VoiceConfigError, load_voices


def _pause_arguments(command: argparse.ArgumentParser) -> None:
    for arg, default, help_text in (
        ("intro", 3.0, "Initial silence (seconds)"),
        ("sentence", 1.5, "Pause between sentences in one paragraph"),
        ("paragraph", 3.0, "Pause between paragraphs of the same voice"),
        ("speaker", 1.0, "Pause when changing speakers"),
        ("attribution", 0.4, "Pause around a [narrator:tag]"),
        ("lead", 0.6, "Pause after a [narrator:lead]"),
    ):
        flag = f"--{arg}-gap" if arg != "intro" else "--intro"
        command.add_argument(flag, type=float, default=default, help=help_text)


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
        description="VoxBraid: prepare TXT narration and synthesize multi-voice speech clips.",
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
        help="Generate separate speech clips (no pauses or music yet; M4 joins them).",
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
        "--overwrite", action="store_true", help="Replace existing output clips (no resume in M2)"
    )
    _pause_arguments(synthesize)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "doctor":
        for check in collect_diagnostics():
            status = "OK" if check.available else "MISSING"
            print(f"[{status}] {check.name}: {check.detail}")
        print("M2: 'synthesize' creates speech clips; M4 will compose a single MP3.")
        return 0
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
            profiles = load_voices(args.voices)
            result = asyncio.run(synthesize_segments(
                selected, profiles, args.out_dir, default_registry(), overwrite=args.overwrite
            ))
        except (OSError, UnicodeError, VoiceConfigError, ValueError, RuntimeError) as exc:
            parser.error(str(exc))
        print(f"Created {len(result.clips)} speech clips in {result.output_dir}")
        print(f"Sequence and pause metadata: {result.manifest}")
        print("M2: these are separate speech clips; pauses/music/full MP3 arrive in M4.")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
