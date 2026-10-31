import json
import tempfile
import unittest
from pathlib import Path

from szu_sentinel.models import AppConfig
from szu_sentinel.storage import ConfigStore


class ConfigStoreTests(unittest.TestCase):
    @unittest.skipUnless(__import__("sys").platform == "win32", "Windows DPAPI only")
    def test_password_is_encrypted_at_rest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            store = ConfigStore(path)
            original = AppConfig(
                username="123456",
                password="very-private-password",
                interval_minutes=3,
            )

            store.save(original)
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            restored = store.load()

            self.assertNotIn(original.password, raw)
            self.assertTrue(payload["password_dpapi"])
            self.assertEqual(restored.password, original.password)

    def test_linux_secret_protection_roundtrip(self):
        from szu_sentinel.storage import _linux_protect_secret, _linux_unprotect_secret
        secret = "szu_linux_p@ssw0rd_2026!"
        protected = _linux_protect_secret(secret)
        self.assertNotEqual(protected, secret)
        self.assertTrue(protected.startswith("TE5YM"))  # base64("LNX1...")
        decrypted = _linux_unprotect_secret(protected)
        self.assertEqual(decrypted, secret)


if __name__ == "__main__":
    unittest.main()
