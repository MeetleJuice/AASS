import os
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def restore_process_environment():
    # Discovery intentionally mutates the process environment. Isolate every test,
    # including direct assignments made by the application rather than monkeypatch.
    with patch.dict(os.environ, {}, clear=False):
        yield
