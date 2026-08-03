"""Unit tests for tdc.composebin (resolution order, no docker required)."""
import unittest
from pathlib import Path
from unittest import mock

from tdc import composebin


class VendoredPathTest(unittest.TestCase):
    def test_non_linux_has_no_vendored_binary(self):
        self.assertIsNone(composebin.vendored_path("Darwin", "arm64"))

    def test_unknown_arch(self):
        self.assertIsNone(composebin.vendored_path("Linux", "riscv64"))

    def test_amd64_is_an_alias_of_x86_64(self):
        # both spellings must land on the same shipped file
        for machine in ("x86_64", "amd64", "X86_64"):
            self.assertEqual(composebin.vendored_path("Linux", machine),
                             composebin.vendored_path("Linux", "x86_64"),
                             machine)

    def test_x86_64_binary_is_shipped_and_executable(self):
        path = composebin.VENDOR_DIR / "docker-compose-linux-x86_64"
        self.assertTrue(path.is_file(), "pinned compose binary is missing")
        self.assertTrue(path.stat().st_mode & 0o111,
                        "pinned compose binary is not executable")


class ResolveTest(unittest.TestCase):
    def test_env_override_wins(self):
        with mock.patch.object(composebin, "vendored_path") as vendored:
            binary, source = composebin.resolve(
                {"TDC_COMPOSE_BIN": "/opt/compose/docker-compose"})
        self.assertEqual(binary, ("/opt/compose/docker-compose",))
        self.assertEqual(source, "TDC_COMPOSE_BIN")
        vendored.assert_not_called()  # override is never second-guessed

    def test_override_may_carry_arguments(self):
        binary, _ = composebin.resolve({"TDC_COMPOSE_BIN": "docker compose"})
        self.assertEqual(binary, ("docker", "compose"))

    def test_vendored_wins_over_system_plugin(self):
        pinned = Path("/repo/vendor/compose/docker-compose-linux-x86_64")
        with mock.patch.object(composebin, "vendored_path",
                               return_value=pinned), \
             mock.patch.object(composebin, "_works", return_value=True):
            binary, source = composebin.resolve({})
        self.assertEqual(binary, (str(pinned),))
        self.assertEqual(source, "vendored")

    def test_falls_back_to_system_plugin(self):
        with mock.patch.object(composebin, "vendored_path",
                               return_value=None), \
             mock.patch.object(composebin, "_works", return_value=True):
            binary, source = composebin.resolve({})
        self.assertEqual(binary, ("docker", "compose"))
        self.assertEqual(source, "system plugin")

    def test_nothing_available_explains_why(self):
        with mock.patch.object(composebin, "vendored_path",
                               return_value=None), \
             mock.patch.object(composebin, "_works", return_value=False):
            binary, reason = composebin.resolve({})
        self.assertIsNone(binary)
        self.assertIn("no compose v2", reason)

    def test_unrunnable_vendored_binary_is_named_in_the_reason(self):
        pinned = Path("/repo/vendor/compose/docker-compose-linux-x86_64")
        with mock.patch.object(composebin, "vendored_path",
                               return_value=pinned), \
             mock.patch.object(composebin, "_works", return_value=False):
            binary, reason = composebin.resolve({})
        self.assertIsNone(binary)
        self.assertIn(str(pinned), reason)


if __name__ == "__main__":
    unittest.main()
