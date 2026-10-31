import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from szu_sentinel.startup import _set_linux_autostart, is_autostart_enabled


class StartupLinuxTests(unittest.TestCase):
    def test_linux_autostart_creates_systemd_and_desktop_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            svc_file = tmppath / ".config" / "systemd" / "user" / "szu-sentinel.service"
            desktop_file = tmppath / ".config" / "autostart" / "szu-sentinel.desktop"

            with patch("szu_sentinel.startup._linux_service_path", return_value=svc_file), \
                 patch("szu_sentinel.startup._linux_desktop_path", return_value=desktop_file), \
                 patch("szu_sentinel.startup.shutil.which", return_value=None):
                
                # Test enable
                _set_linux_autostart(True)
                self.assertTrue(svc_file.exists())
                self.assertTrue(desktop_file.exists())
                self.assertIn("SZU NetSentinel", svc_file.read_text(encoding="utf-8"))
                self.assertIn("Type=Application", desktop_file.read_text(encoding="utf-8"))

                # Test is_autostart_enabled on Linux
                with patch("szu_sentinel.startup.sys.platform", "linux"):
                    self.assertTrue(is_autostart_enabled())

                # Test disable
                _set_linux_autostart(False)
                self.assertFalse(svc_file.exists())
                self.assertFalse(desktop_file.exists())
                with patch("szu_sentinel.startup.sys.platform", "linux"):
                    self.assertFalse(is_autostart_enabled())


if __name__ == "__main__":
    unittest.main()
