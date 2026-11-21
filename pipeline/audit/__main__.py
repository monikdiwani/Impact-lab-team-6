"""python -m pipeline.audit [out_dir]  -> writes M2 outputs (default: outputs/)."""
import sys
from pathlib import Path

from pipeline.audit import run

root = Path(__file__).resolve().parents[2]
out = run(root / "data", Path(sys.argv[1]) if len(sys.argv) > 1 else root / "outputs")
print({k: str(v) for k, v in out.items()})
