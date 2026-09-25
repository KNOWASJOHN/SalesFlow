"""
Pytest bootstrap for the backend project.

Ensures the repository root (the directory containing `app/`) is importable
when tests are run as `pytest tests/...` as well as `python -m pytest`, so
`import app.signaling...` works in every invocation style without needing a
package install or a pytest.ini/pyproject.toml change.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
