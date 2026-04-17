from __future__ import annotations

import sys
from pathlib import Path

from mtglib_contract import build_arg_parser, iter_markdown_files, lint_card_file


def main() -> int:
    parser = build_arg_parser("Rewrite MTGLib card files into the canonical CONTRACT.md format.")
    parser.add_argument(
        "--cards-dir",
        default=str(Path(__file__).resolve().parent.parent / "cards"),
        help="Default directory to lint when no positional paths are provided.",
    )
    args = parser.parse_args()

    raw_paths = [Path(path) for path in args.paths] if args.paths else [Path(args.cards_dir)]
    files = iter_markdown_files(raw_paths)
    if not files:
        print("No Markdown files found to lint.", file=sys.stderr)
        return 1

    changed_files: list[Path] = []
    for file_path in files:
        try:
            changed = lint_card_file(file_path, check_only=args.check)
        except Exception as error:  # noqa: BLE001
            print(f"Failed to lint {file_path}: {error}", file=sys.stderr)
            return 1
        if changed:
            changed_files.append(file_path)

    if args.check:
        if changed_files:
            for file_path in changed_files:
                print(file_path)
            return 1
        print(f"Checked {len(files)} files. No formatting drift found.")
        return 0

    print(f"Rewrote {len(changed_files)} of {len(files)} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())