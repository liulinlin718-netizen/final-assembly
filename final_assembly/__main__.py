import argparse
import json
import sys
import uuid
from . import __version__
from .errors import AssemblyError
from .paths import checked_path, write_json, workspace


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="final-assembly", description="Assemble approved blocks and reconcile actual exported files.")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--workspace", default=".", help="Material/output boundary; defaults to current directory. Paths are relative to this directory.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("preview", "build", "verify"):
        command = sub.add_parser(name)
        command.add_argument("manifest")
        if name == "build":
            command.add_argument("--out-dir", required=True)
            command.add_argument("--summary", action="store_true", help="Print a compact receipt; keep the complete report on disk.")
        elif name == "verify":
            command.add_argument("--file", required=True)
            command.add_argument("--report")
            command.add_argument("--summary", action="store_true", help="Print a compact receipt; requires --report for full evidence.")
    command = sub.add_parser("prepare", help="Snapshot selected source files into an unapproved draft.")
    command.add_argument("sources", nargs="+")
    command.add_argument("--out-dir", required=True)
    command.add_argument("--title", required=True)
    command.add_argument("--origin", required=True)
    command.add_argument("--section", default="Content")
    command = sub.add_parser("inspect", help="Review sources and issues, including unapproved drafts.")
    command.add_argument("manifest")
    command.add_argument("--full-text", action="store_true")
    command = sub.add_parser("approve", help="Record an explicit adoption decision for selected active blocks.")
    command.add_argument("manifest")
    command.add_argument("--ids", nargs="+", required=True)
    command.add_argument("--decision", required=True)
    command.add_argument("--out-manifest", required=True)
    command = sub.add_parser("import-pack")
    command.add_argument("pack")
    command.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)
    if args.command == "verify" and args.summary and not args.report:
        parser.error("verify --summary requires --report to preserve complete evidence")
    try:
        with workspace(args.workspace):
            report = dispatch(args)
        code = 0 if report["passed"] else 3
    except AssemblyError as exc:
        report = {"passed": False, "error": exc.as_dict()}
        code = 2
    except ImportError as exc:
        report = {"passed": False, "error": {"code": "MISSING_DEPENDENCY", "message": str(exc), "hint": "Install final-assembly with its declared dependencies in your chosen environment."}}
        code = 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        report = {"passed": False, "error": {"code": "IO_OR_INPUT_ERROR", "message": str(exc)}}
        code = 2
    if getattr(args, "summary", False):
        from .reporting import summarize
        try:
            with workspace(args.workspace):
                if args.command == "build" and report.get("passed"):
                    target = checked_path(report["output_dir"]) / "reconciliation.json"
                elif args.command == "verify" and "format" in report:
                    target = checked_path(args.report)
                else:
                    # Input/build failures have no delivery; preserve full evidence
                    # separately without publishing or overwriting a delivery.
                    target = checked_path(".final-assembly-reports") / (args.command + "-" + uuid.uuid4().hex + ".json")
                    write_json(target, report)
                report = summarize(report, str(target))
        except (AssemblyError, OSError, ValueError) as exc:
            # Never hide details behind a report path that could not be written.
            report["summary_report_error"] = str(exc)
            code = 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


def dispatch(args):
    from .core import build, preview, verify_loaded
    from .manifest import load_manifest
    if args.command == "preview":
        report = preview(args.manifest)
    elif args.command == "build":
        report = build(args.manifest, args.out_dir)
    elif args.command == "verify":
        report = verify_loaded(load_manifest(args.manifest), args.file)
        if args.report:
            target = checked_path(args.report)
            if target.suffix.lower() != ".json":
                raise AssemblyError("REPORT_EXTENSION", "Report path must end in .json")
            write_json(target, report)
    elif args.command == "prepare":
        from .preparation import prepare
        report = prepare(args.sources, args.out_dir, args.title, args.origin, args.section)
    elif args.command == "inspect":
        from .preparation import inspect_manifest
        report = inspect_manifest(args.manifest, args.full_text)
    elif args.command == "approve":
        from .preparation import approve
        report = approve(args.manifest, args.ids, args.decision, args.out_manifest)
    else:
        from .importer import import_pack
        report = import_pack(args.pack, args.out_dir)
    return report

if __name__ == "__main__":
    sys.exit(main())
