import sys
from pathlib import Path

FRONTEND_DIR = Path(__file__).parent
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))