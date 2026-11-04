"""VoxBraid CLI: diagnostics and offline TXT planning (M1)."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from voxbraid import __version__
from voxbraid.diagnostics import collect_diagnostics
from voxbraid.parser import TextFormatError, parse_file
from voxbraid.planner import PauseOptions, plan_segments


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voxbraid",
        description="VoxBraid: plan multi-voice TXT narration (M1; audio rendering comes later).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subcommands = parser.add_subparsers(dest="command", metavar="COMMAND")
    subcommands.add_parser("doctor", help="Inspect Python and optional audio tools (offline).")
    preview = subcommands.add_parser("preview", help="Plan a TXT book without any TTS calls.")
    preview.add_argument("input", type=Path, help="Prepared UTF-8 TXT file")
    preview.add_argument("--json", action="store_true", help="Output the plan as JSON")
    preview.add_argument("--limit", type=int, help="Display only the first N segments")
    for arg, default, help_text in (
        ("intro", 3.0, "Initial silence (seconds)"),
        ("sentence", 1.5, "Pause between sentences in one paragraph"),
        ("paragraph", 3.0, "Pause between paragraphs of the same voice"),
        ("speaker", 1.0, "Pause when changing speakers"),
        ("attribution", 0.4, "Pause around a [narrator:tag]"),
        ("lead", 0.6, "Pause after a [narrator:lead]"),
    ):
        preview.add_argument(f"--{arg}-gap" if arg != "intro" else "--intro", type=float,
                             default=default, help=help_text)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "doctor":
        for check in collect_diagnostics():
            status = "OK" if check.available else "MISSING"
            print(f"[{status}] {check.name}: {check.detail}")
        print("M1: preview is offline; render starts in a later milestone.")
        return 0
    if args.command == "preview":
        if args.limit is not None and args.limit < 1:
            parser.error("--limit must be a positive integer")
        try:
            options = PauseOptions(
                intro=args.intro,
                sentence=args.sentence_gap,
                paragraph=args.paragraph_gap,
                speaker=args.speaker_gap,
                attribution=args.attribution_gap,
                lead=args.lead_gap,
            )
            document = parse_file(args.input)
            segments = plan_segments(document, options)
        except (OSError, UnicodeError, TextFormatError, ValueError) as exc:
            parser.error(str(exc))
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
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
