"""python -m pipeline: run M1 -> M3 -> M2 into outputs/ and update the database (see run_all.py)."""
import sys

from pipeline.run_all import main

sys.exit(main())
