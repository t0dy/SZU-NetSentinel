import unittest
from szu_sentinel.memory import trim_memory


class MemoryTests(unittest.TestCase):
    def test_trim_memory_runs_cleanly(self) -> None:
        # trim_memory should never raise exceptions regardless of environment
        try:
            trim_memory()
        except Exception as exc:
            self.fail(f"trim_memory raised an unexpected exception: {exc}")


if __name__ == "__main__":
    unittest.main()
