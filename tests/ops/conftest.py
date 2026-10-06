"""ops/killswitch isn't a package (Cloud Run functions deploy a flat folder), so put
it on the path like the function runtime does."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ops" / "killswitch"))
