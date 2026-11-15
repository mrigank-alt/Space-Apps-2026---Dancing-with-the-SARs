from __future__ import annotations

import os
import tempfile
from pathlib import Path


_test_data_directory = Path(tempfile.mkdtemp(prefix="groundsignal-tests-"))
os.environ["SELECTION_DATABASE_PATH"] = str(_test_data_directory / "selections.sqlite3")
