import tempfile
import unittest
from pathlib import Path

from tdc.envfile import (
    parse_env_file, check_reserved, merge_env, render_env_file,
)
from tdc.model import ConfigError

FIXTURES = Path(__file__).parent / "fixtures"
DEMO_ENV = (FIXTURES / "demo_repo" / "test_docker_config" / "post_commit"
            / "postgres_integration" / ".env.default")
BAD_ENV = (FIXTURES / "bad_repo" / "test_docker_config" / "post_commit"
           / "violations" / ".env.default")
EMPTY_ENV = (FIXTURES / "bad_repo" / "test_docker_config" / "post_commit"
             / "Bad_Name" / ".env.default")


class ParseEnvFileTest(unittest.TestCase):
    def _parse(self, text):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / ".env.default"
            path.write_text(text, encoding="utf-8")
            return parse_env_file(path)

    def test_demo_repo_fixture(self):
        self.assertEqual(parse_env_file(DEMO_ENV),
                         {"POSTGRES_USER": "test", "POSTGRES_PASSWORD": "test",
                          "READ_DB": "openide_read",
                          "WRITE_DB": "openide"})

    def test_empty_file(self):
        self.assertEqual(parse_env_file(EMPTY_ENV), {})

    def test_comments_and_blank_lines(self):
        env = self._parse("# comment\n\n  \nA=1\n  # indented comment\nB=2\n")
        self.assertEqual(env, {"A": "1", "B": "2"})

    def test_quote_stripping_single_matching_pair_only(self):
        env = self._parse(
            "A='hello world'\n"
            "B=\"v\"\n"
            "C=\"mixed'\n"
            "D=''\n"
            "E=\"\n"
            "F=\"'x'\"\n"
            "G=a\"b\n"
            "H=a=b\n")
        self.assertEqual(env, {
            "A": "hello world",
            "B": "v",
            "C": "\"mixed'",   # mismatched pair -> untouched
            "D": "",
            "E": "\"",         # lone quote is not a pair
            "F": "'x'",        # only the outer pair is stripped
            "G": "a\"b",
            "H": "a=b",        # value may contain '='
        })

    def test_underscore_names_and_empty_value(self):
        env = self._parse("_LEADING=1\nX_9=\n")
        self.assertEqual(env, {"_LEADING": "1", "X_9": ""})

    def test_malformed_collects_all_lines(self):
        text = "GOOD=1\n1BAD=x\nNOEQUALS\nBAD-NAME=x\nGOOD2=2\n"
        with self.assertRaises(ConfigError) as cm:
            self._parse(text)
        issues = cm.exception.issues
        self.assertEqual(len(issues), 3)
        for issue in issues:
            self.assertEqual(issue.severity, "error")
            self.assertEqual(issue.code, "env.malformed_line")
        # line numbers of all malformed lines are reported
        messages = " ".join(i.message for i in issues)
        for lineno in (":2:", ":3:", ":4:"):
            self.assertIn(lineno, messages)


class CheckReservedTest(unittest.TestCase):
    def test_bad_repo_fixture(self):
        env = parse_env_file(BAD_ENV)
        issues = check_reserved(env)
        self.assertEqual(len(issues), 3)
        flagged = " ".join(i.message for i in issues)
        for name in ("COMPOSE_FILE", "DOCKER_HOST", "TEST_INPUT"):
            self.assertIn(name, flagged)
        self.assertNotIn("NORMAL_VAR", flagged)
        for issue in issues:
            self.assertEqual(issue.severity, "error")
            self.assertEqual(issue.code, "env.reserved_name")

    def test_all_reserved_prefixes(self):
        env = {"COMPOSE_X": "1", "DOCKER_X": "1", "TEST_X": "1",
               "BUILD_X": "1", "VCS_X": "1", "OK_VAR": "1"}
        issues = check_reserved(env)
        self.assertEqual(len(issues), 5)

    def test_clean_env(self):
        self.assertEqual(check_reserved({"POSTGRES_USER": "test"}), [])


class MergeEnvTest(unittest.TestCase):
    def test_ci_wins(self):
        defaults = {"A": "d", "B": "d"}
        ci = {"B": "ci", "C": "ci"}
        merged = merge_env(defaults, ci)
        self.assertEqual(merged, {"A": "d", "B": "ci", "C": "ci"})
        # inputs untouched, result is a new dict
        self.assertEqual(defaults, {"A": "d", "B": "d"})
        self.assertEqual(ci, {"B": "ci", "C": "ci"})
        self.assertIsNot(merged, defaults)
        self.assertIsNot(merged, ci)


class RenderEnvFileTest(unittest.TestCase):
    def test_sorted_with_trailing_newline(self):
        self.assertEqual(render_env_file({"B": "2", "A": "1", "C": ""}),
                         "A=1\nB=2\nC=\n")

    def test_empty(self):
        self.assertEqual(render_env_file({}), "")

    def test_newline_in_value_rejected(self):
        for value in ("a\nb", "a\rb"):
            with self.assertRaises(ValueError):
                render_env_file({"A": value})

    def test_round_trip(self):
        env = {"A": "1", "POSTGRES_USER": "test", "EMPTY": ""}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / ".env"
            path.write_text(render_env_file(env), encoding="utf-8")
            self.assertEqual(parse_env_file(path), env)


if __name__ == "__main__":
    unittest.main()
