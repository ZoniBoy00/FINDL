import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from findl.core.runtime import redact_message
from findl.config import BASE_DIR, LOG_DIR, WVD_PATH


def test_sensitive_values_are_redacted():
    message = "Authorization: Bearer secret Cookie: sid=secret 0123456789abcdef0123456789abcdef:abcdef0123456789abcdef0123456789"
    safe = redact_message(message)
    assert "secret" not in safe
    assert "<redacted>" in safe
    assert "<key-redacted>" in redact_message("0123456789abcdef0123456789abcdef:abcdef0123456789abcdef0123456789")


def test_paths_are_project_relative():
    assert Path(BASE_DIR) == ROOT
    assert Path(LOG_DIR).is_absolute()
    assert Path(WVD_PATH).is_absolute()
