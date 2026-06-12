import sys
from pathlib import Path

# Package modules import each other flat (`import rag`, `import db`, ...),
# so the package directory itself must be on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data_spear"))
