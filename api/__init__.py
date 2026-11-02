"""League Lab's API for the React app (docs/reactDocs/ui-rebuild-plan.md, section 8).

It reuses the Streamlit app's modules (app/analysis, app/points, tenancy ...) the way
Streamlit runs them: with app/ itself on the import path, plus the repo root for the
ingest package.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "app"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
