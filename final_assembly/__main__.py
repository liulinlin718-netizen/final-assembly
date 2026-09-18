import argparse
import json
import sys
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
        elif name == "verify":
            command.add_argument("--file", required=True)
            command.add_argument("--report")
    command = sub.add_parser("import-pack")
    command.add_argument("pack")
    command.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)
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
    else:
        from .importer import import_pack
        report = import_pack(args.pack, args.out_dir)
    return report

if __name__ == "__main__":
    sys.exit(main())
