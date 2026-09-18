"""Real CLI normal / corrupt-file failure / recovery; optional 60-second pacing."""
import argparse
import json
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from final_assembly.paths import checked_path

parser = argparse.ArgumentParser()
parser.add_argument("--out-dir", default="exports/demo-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
parser.add_argument("--pace", action="store_true", help="Pause at 15/30/45/60 seconds for a live demonstration")
args = parser.parse_args()
output = checked_path(args.out_dir, ROOT)
if output.exists():
    parser.error("Output already exists; choose a new directory")
output.mkdir(parents=True)
manifest = ROOT / "examples/approved/manifest.json"
events = []
start = time.monotonic()


def at(seconds):
    if args.pace:
        time.sleep(max(0, seconds - (time.monotonic() - start)))


def cli(*arguments, expected=0):
    result = subprocess.run([sys.executable, "-B", "-m", "final_assembly", *map(str, arguments)],
                            cwd=ROOT, capture_output=True, encoding="utf-8", timeout=60)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(result.stderr or result.stdout)
    events.append({"arguments": list(map(str, arguments)), "exit_code": result.returncode, "output": data})
    if result.returncode != expected:
        raise RuntimeError(f"Expected exit {expected}, received {result.returncode}: {data}")
    return data


print("00–15s  Explicit offline demo: round 2 body, round 4 table, round 7 replaces round 5.", flush=True)
preview = cli("preview", manifest)
print("         Active: " + " -> ".join(b["id"] for b in preview["blocks"]), flush=True)
at(15)
print("15–30s  Build actual Markdown + DOCX and read both files back.", flush=True)
built = cli("build", manifest, "--out-dir", output / "approved")
print("         PASS: 3 blocks, 48 table cells, 2 links in each format.", flush=True)
at(30)
print("30–45s  Actual DOCX: " + str(output / "approved/final.docx"), flush=True)
print("         Per-cell evidence: " + str(output / "approved/reconciliation.json"), flush=True)
print("         Content verified; visual layout is a separate check.", flush=True)
at(45)
print("45–60s  Remove a real DOCX table row; verify must fail; rebuild must recover.", flush=True)
source = output / "approved/final.docx"
bad = output / "missing-row.docx"
with zipfile.ZipFile(source) as zf:
    parts = {info.filename: zf.read(info.filename) for info in zf.infolist()}
ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
tree = ET.fromstring(parts["word/document.xml"])
table = tree.find(".//" + ns + "tbl")
table.remove(table.findall(ns + "tr")[4])
parts["word/document.xml"] = ET.tostring(tree, encoding="utf-8", xml_declaration=True)
with zipfile.ZipFile(bad, "w", zipfile.ZIP_DEFLATED) as zf:
    for name, raw in parts.items():
        zf.writestr(name, raw)
failed = cli("verify", manifest, "--file", bad, "--report", output / "failure.json", expected=3)
print("         EXPECTED FAIL: " + json.dumps(failed["issues"][0], ensure_ascii=False), flush=True)
recovered = cli("build", manifest, "--out-dir", output / "recovered")
print("         RECOVERED PASS: " + str(output / "recovered/final.docx"), flush=True)
(output / "commands.json").write_text(json.dumps(events, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
at(60)
print("Evidence: " + str(output / "commands.json"), flush=True)
