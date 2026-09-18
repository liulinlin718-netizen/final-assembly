"""Build source and standalone-skill ZIPs from explicit release allowlists."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]


def archive(path, entries):
    with path.open("xb") as stream, ZipFile(stream, "w", compression=ZIP_DEFLATED) as bundle:
        for name, source in sorted(entries.items()):
            entry = ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            bundle.writestr(entry, source.read_bytes())
    return {"file": str(path), "files": len(entries), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="dist/0.2.2")
    args = parser.parse_args()
    output = Path(args.out_dir).resolve()
    if not output.is_relative_to(ROOT):
        parser.error("Release artifacts must remain inside this checkout.")
    output.mkdir(parents=True, exist_ok=True)
    files = {}
    for directory, pattern in (("final_assembly", "*.py"), ("tests", "*.py"), ("examples/approved", "*.md"), ("examples/approved", "*.json"), ("examples/common-markdown", "*.md"), ("examples/common-markdown", "*.json")):
        for path in (ROOT / directory).rglob(pattern):
            if path.is_file() and "__pycache__" not in path.parts:
                files[path.relative_to(ROOT).as_posix()] = path
    for name in ("README.md", "LICENSE", "requirements.txt", "pyproject.toml", "scripts/run.ps1", "scripts/demo.py", "scripts/demo.ps1", "scripts/validate.py", "scripts/package.py", "examples/reference-pack.json", "skills/final-assembly/SKILL.md", "skills/final-assembly/scripts/run.py", "skills/final-assembly/references/manifest.md"):
        files[name] = ROOT / name
    skill = {name.removeprefix("skills/"): source for name, source in files.items() if name.startswith("skills/")}
    skill["final-assembly/requirements.txt"] = ROOT / "requirements.txt"
    skill["final-assembly/LICENSE"] = ROOT / "LICENSE"
    for source in (ROOT / "final_assembly").glob("*.py"):
        skill["final-assembly/scripts/final_assembly/" + source.name] = source
    results = [archive(output / "final-assembly-0.2.2-source.zip", files), archive(output / "final-assembly-0.2.2-skill.zip", skill)]
    print(json.dumps({"artifacts": results}, indent=2))


if __name__ == "__main__":
    main()
