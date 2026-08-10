import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.local_config import local_setting


class LocalConfigTests(unittest.TestCase):
    def test_reads_quoted_literal_value(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.local"
            path.write_text('SEC_USER_AGENT="Radar contact@example.test"\n', encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(local_setting("SEC_USER_AGENT", path=path), "Radar contact@example.test")

    def test_environment_takes_precedence(self):
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Environment value"}):
            self.assertEqual(local_setting("SEC_USER_AGENT", path="missing"), "Environment value")


if __name__ == "__main__":
    unittest.main()
