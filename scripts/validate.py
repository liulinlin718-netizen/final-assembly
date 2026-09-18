"""Run actual tests and retain machine-readable evidence inside this project."""
import io
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
qa = checked_path(ROOT / "exports/qa")
qa.mkdir(parents=True, exist_ok=True)
stream = io.StringIO()
suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
(qa / "tests.txt").write_text(stream.getvalue(), encoding="utf-8")
summary = {"passed": result.wasSuccessful(), "tests_run": result.testsRun,
           "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
           "python": sys.executable, "command": "python -B scripts/validate.py",
           "timestamp": datetime.now(timezone.utc).isoformat(), "log": str(qa / "tests.txt")}
(qa / "tests.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, indent=2))
sys.exit(0 if result.wasSuccessful() else 1)
