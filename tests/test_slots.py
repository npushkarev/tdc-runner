import unittest

from tdc.model import Slot, OSES, ARCHES
from tdc.slots import parse_slot, path_matches_slot

LIN_X64 = Slot("lin", "x64")
LIN_ARM = Slot("lin", "arm")
LIN_ARM64 = Slot("lin", "arm64")
WIN_X64 = Slot("win", "x64")
WIN_ARM64 = Slot("win", "arm64")


class ParseSlotTest(unittest.TestCase):
    def test_all_valid_combinations(self):
        for os_ in OSES:
            for arch in ARCHES:
                text = "%s-%s" % (os_, arch)
                slot = parse_slot(text)
                self.assertEqual(slot, Slot(os_, arch))
                self.assertEqual(str(slot), text)

    def test_invalid(self):
        for text in ("", "lin", "x64", "lin_x64", "lin x64", "mac-x64",
                     "lin-x86", "x64-lin", "lin-arm-64", "LIN-X64",
                     "win-", "-x64", "lin-arm64-extra"):
            with self.assertRaises(ValueError, msg=text):
                parse_slot(text)


class PathMatchesSlotTest(unittest.TestCase):
    def test_nupkg_x64_tokens(self):
        rel = "grpc.lin.gcc.shared.x64.1.78.1.nupkg"
        self.assertTrue(path_matches_slot(rel, LIN_X64))
        self.assertFalse(path_matches_slot(rel, LIN_ARM64))
        self.assertFalse(path_matches_slot(rel, LIN_ARM))
        self.assertFalse(path_matches_slot(rel, WIN_X64))

    def test_arm64_is_not_arm(self):
        rel = "zlib.lin.gcc.static.arm64.1.3.1.nupkg"
        self.assertTrue(path_matches_slot(rel, LIN_ARM64))
        self.assertFalse(path_matches_slot(rel, LIN_ARM))
        self.assertFalse(path_matches_slot(rel, LIN_X64))

    def test_arm_is_not_arm64(self):
        rel = "zlib.lin.gcc.static.arm.1.3.1.nupkg"
        self.assertTrue(path_matches_slot(rel, LIN_ARM))
        self.assertFalse(path_matches_slot(rel, LIN_ARM64))

    def test_neutral_path_matches_everything(self):
        rel = "shared/data/readme.txt"
        for os_ in OSES:
            for arch in ARCHES:
                self.assertTrue(path_matches_slot(rel, Slot(os_, arch)))

    def test_os_only_axis(self):
        rel = "win/tool.nupkg"
        self.assertTrue(path_matches_slot(rel, WIN_X64))
        self.assertTrue(path_matches_slot(rel, WIN_ARM64))
        self.assertFalse(path_matches_slot(rel, LIN_X64))
        self.assertFalse(path_matches_slot(rel, LIN_ARM64))

    def test_arch_only_axis(self):
        rel = "packages/foo.arm64.nupkg"
        self.assertTrue(path_matches_slot(rel, LIN_ARM64))
        self.assertTrue(path_matches_slot(rel, WIN_ARM64))
        self.assertFalse(path_matches_slot(rel, LIN_ARM))
        self.assertFalse(path_matches_slot(rel, LIN_X64))

    def test_tokens_from_path_segments(self):
        rel = "packages/lin/x64/foo.nupkg"
        self.assertTrue(path_matches_slot(rel, LIN_X64))
        self.assertFalse(path_matches_slot(rel, LIN_ARM64))
        self.assertFalse(path_matches_slot(rel, WIN_X64))

    def test_underscore_and_dash_separators(self):
        self.assertTrue(path_matches_slot("grpc_lin_x64_1.78.1.nupkg", LIN_X64))
        self.assertTrue(path_matches_slot("grpc-lin-x64.nupkg", LIN_X64))
        self.assertFalse(path_matches_slot("grpc-lin-x64.nupkg", LIN_ARM64))

    def test_backslash_separators(self):
        rel = "packages\\win\\x64\\tool.nupkg"
        self.assertTrue(path_matches_slot(rel, WIN_X64))
        self.assertFalse(path_matches_slot(rel, LIN_X64))

    def test_no_substring_matching(self):
        # "linx64" is a single token, matches neither axis -> neutral.
        self.assertTrue(path_matches_slot("linx64.nupkg", WIN_ARM64))


if __name__ == "__main__":
    unittest.main()
