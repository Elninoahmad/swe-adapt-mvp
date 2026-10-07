import os
import sys
from pathlib import Path

REPO = Path(
    os.environ.get("SWE_ADAPT_REPO", Path(__file__).parent.parent / "repo")
)
sys.path.insert(0, str(REPO))
