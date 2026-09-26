"""Run actual tests and retain machine-readable evidence inside this project."""
import io
import argparse
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from final_assembly.paths import checked_path

os.chdir(ROOT)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--out-dir", default="exports/qa", help="Evidence directory inside this checkout")
args = parser.parse_args()
qa = checked_path(ROOT / args.out_dir)
qa.mkdir(parents=True, exist_ok=True)
stream = io.StringIO()
suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
(qa / "tests.txt").write_text(stream.getvalue(), encoding="utf-8")
summary = {"passed": result.wasSuccessful(), "tests_run": result.testsRun,
           "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
           "python": sys.executable, "command": [sys.executable, "-B", "scripts/validate.py", "--out-dir", args.out_dir],
           "timestamp": datetime.now(timezone.utc).isoformat(), "log": str(qa / "tests.txt")}
(qa / "tests.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, indent=2))
sys.exit(0 if result.wasSuccessful() else 1)
