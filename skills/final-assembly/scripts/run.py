"""Relocatable skill entrypoint. Release bundles carry the package beside it."""
import sys
from pathlib import Path

sys.dont_write_bytecode = True
here = Path(__file__).resolve().parent
if (here / "final_assembly").is_dir():
    sys.path.insert(0, str(here))
else:
    source_root = here.parents[2]
    if (source_root / "final_assembly").is_dir():
        sys.path.insert(0, str(source_root))
from final_assembly.__main__ import main

raise SystemExit(main())
