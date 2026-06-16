"""CLI for cross-platform system inventory."""
from __future__ import annotations

from arena.inventory.probe_common import *  # noqa: F401,F403
from arena.inventory.report import collect, format_text

def main():
    # On Windows console, force UTF-8 so dashes/bullets don't become mojibake
    if platform.system() == "Windows":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    p = argparse.ArgumentParser(description="Cross-platform system inventory")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.add_argument("--section", help="Only one section")
    p.add_argument("-o", "--output", help="Write to file")
    p.add_argument("-q", "--quiet", action="store_true", help="Don't print to stdout")
    args = p.parse_args()

    data = collect(only_section=args.section)
    out_text = json.dumps(data, indent=2, ensure_ascii=False) if args.json else format_text(data)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out_text)
        if not args.quiet:
            print(f"[inventory] Wrote {len(out_text)} chars to {args.output}", file=sys.stderr)
    elif not args.quiet:
        print(out_text)

if __name__ == "__main__":
    raise SystemExit(main())
