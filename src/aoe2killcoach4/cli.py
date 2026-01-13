"""CLI entrypoint for AoE2 KillCoach v4."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aoe2killcoach4.core import analyze_replay, parse_replay, write_outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AoE2 KillCoach v4 replay analyzer")
    parser.add_argument("replay", help="Path to the .aoe2record replay file")
    parser.add_argument(
        "--out-dir",
        default=".",
        help="Directory to write outputs",
    )
    parser.add_argument(
        "--you-name",
        help="Your in-game player name (case-insensitive match)",
    )
    parser.add_argument(
        "--you-player",
        type=int,
        choices=[1, 2],
        help="Player index (1 or 2) for your POV",
    )
    parser.add_argument(
        "--export-level",
        default="coach",
        choices=["coach", "full"],
        help="Export level for JSON output",
    )
    parser.add_argument(
        "--tsv-mode",
        default="row",
        choices=["row", "header-row"],
        help="Write TSV header row or append only",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print debug information about parsed data",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        parsed = parse_replay(args.replay)
        result = analyze_replay(
            parsed.data,
            you_name=args.you_name,
            you_player=args.you_player,
            export_level=args.export_level,
        )
    except Exception as exc:  # noqa: BLE001 - surfacing parse failures
        print(f"Error parsing replay: {exc}", file=sys.stderr)
        return 1

    outputs = write_outputs(result, Path(args.out_dir), args.tsv_mode)
    print("Written outputs:")
    for key, path in outputs.items():
        print(f"- {key}: {path}")

    if args.debug:
        print("Debug: JSON output created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
