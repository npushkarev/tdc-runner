"""Unit tests for tdc.xmlcfg.parse_test_cfg (stdlib unittest, no docker)."""
import tempfile
import unittest
from pathlib import Path

from tdc.model import ConfigError
from tdc.xmlcfg import parse_test_cfg

FIXTURES = Path(__file__).parent / "fixtures"
DEMO_CFG = (FIXTURES / "demo_repo" / "test_docker_config" / "post_commit"
            / "postgres_integration" / "test_cfg.xml")
BAD_CFG = (FIXTURES / "bad_repo" / "test_docker_config" / "post_commit"
           / "violations" / "test_cfg.xml")

VALID_BODY = """<?xml version="1.0" encoding="UTF-8"?>
<test_cfg version="1">
  <environment><os>linux</os><arch>x64</arch></environment>
  <outputs><report type="tests" format="junit" path="junit/*.xml"/></outputs>
  <execution><main_service>tests</main_service><timeout_minutes>5</timeout_minutes></execution>
</test_cfg>
"""


class ParseTestCfgValidTest(unittest.TestCase):
    def test_demo_fixture_parses(self):
        cfg = parse_test_cfg(DEMO_CFG)
        self.assertEqual(cfg.oses, ["lin"])
        self.assertEqual(cfg.arches, ["x64"])
        self.assertIn("postgres", cfg.description)

        self.assertEqual(len(cfg.inputs), 1)
        src = cfg.inputs[0]
        self.assertEqual(src.kind, "source")
        self.assertEqual(src.path, "tests/data/**")
        self.assertEqual(src.dest, "data/")
        self.assertTrue(src.optional)
        self.assertTrue(src.slot_filter)

        # тот же профиль реально гоняется смоуком, поэтому набор отчётов боевой
        self.assertEqual([(r.type, r.format) for r in cfg.reports],
                         [("tests", "trx"), ("coverage", "cobertura"),
                          ("snapshots", "raw")])
        self.assertEqual(len(cfg.out_artifacts), 1)
        self.assertEqual(cfg.out_artifacts[0].path, "logs/**")
        self.assertTrue(cfg.out_artifacts[0].optional)
        self.assertEqual(cfg.cap_add,
                         {"postgres": ["CHOWN", "DAC_OVERRIDE", "FOWNER",
                                       "SETGID", "SETUID"]})

        self.assertIsNotNone(cfg.execution)
        self.assertEqual(cfg.execution.main_service, "tests")
        self.assertEqual(cfg.execution.timeout_minutes, 20)
        # name is the caller's job; dir defaults to the config directory
        self.assertEqual(cfg.name, "")
        self.assertEqual(cfg.dir, DEMO_CFG.parent)


class ParseTestCfgErrorsTest(unittest.TestCase):
    def _parse_text(self, body):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test_cfg.xml"
            path.write_text(body, encoding="utf-8")
            return parse_test_cfg(path)

    def _codes(self, ctx):
        return {i.code for i in ctx.exception.issues}

    def test_bad_fixture_collects_all_errors(self):
        with self.assertRaises(ConfigError) as ctx:
            parse_test_cfg(BAD_CFG)
        codes = self._codes(ctx)
        # every violation reported at once, not just the first
        self.assertLessEqual(
            {"environment.os_unknown", "environment.arch_unknown",
             "capability.unknown", "outputs.no_tests_report",
             "execution.timeout"},
            codes)
        self.assertTrue(all(i.severity == "error" for i in ctx.exception.issues))

    def test_broken_xml(self):
        with self.assertRaises(ConfigError) as ctx:
            self._parse_text("<test_cfg version='1'><unclosed>")
        self.assertEqual(self._codes(ctx), {"xml.malformed"})

    def test_unknown_version(self):
        with self.assertRaises(ConfigError) as ctx:
            self._parse_text(VALID_BODY.replace('version="1"', 'version="2"'))
        self.assertIn("cfg.version", self._codes(ctx))

    def test_missing_execution(self):
        body = VALID_BODY.replace(
            "<execution><main_service>tests</main_service>"
            "<timeout_minutes>5</timeout_minutes></execution>", "")
        with self.assertRaises(ConfigError) as ctx:
            self._parse_text(body)
        self.assertIn("execution.missing", self._codes(ctx))

    def test_unknown_report_type_is_a_warning_not_an_error(self):
        # open dictionary (ticket p.4): unknown type still reaches collection
        body = VALID_BODY.replace(
            '<report type="tests" format="junit" path="junit/*.xml"/>',
            '<report type="tests" format="junit" path="junit/*.xml"/>'
            '<report type="fuzzing" format="raw" path="fuzz/**"/>')
        cfg = self._parse_text(body)
        self.assertEqual([r.type for r in cfg.reports], ["tests", "fuzzing"])
        self.assertEqual([i.code for i in cfg.warnings],
                         ["outputs.report_type_unknown"])

    def test_snapshots_is_a_known_type(self):
        body = VALID_BODY.replace(
            '<report type="tests" format="junit" path="junit/*.xml"/>',
            '<report type="tests" format="junit" path="junit/*.xml"/>'
            '<report type="snapshots" format="raw" path="__snapshots__/**"/>')
        cfg = self._parse_text(body)
        self.assertEqual(cfg.warnings, [])

    def test_secrets_parsed_with_and_without_services(self):
        body = VALID_BODY.replace(
            "<execution>",
            '<secrets><secret name="db_password" services="postgres cache"/>'
            '<secret name="api_key"/></secrets><execution>')
        cfg = self._parse_text(body)
        self.assertEqual([(s.name, s.services) for s in cfg.secrets],
                         [("db_password", ["postgres", "cache"]),
                          ("api_key", [])])

    def test_secret_name_must_be_a_plain_file_name(self):
        for bad in ("../escape", "Db-Password", "with space", ""):
            body = VALID_BODY.replace(
                "<execution>",
                '<secrets><secret name="%s"/></secrets><execution>' % bad)
            with self.assertRaises(ConfigError) as ctx:
                self._parse_text(body)
            self.assertIn("secrets.bad_name", self._codes(ctx), bad)

    def test_duplicate_secret_rejected(self):
        body = VALID_BODY.replace(
            "<execution>",
            '<secrets><secret name="pw"/><secret name="pw"/></secrets><execution>')
        with self.assertRaises(ConfigError) as ctx:
            self._parse_text(body)
        self.assertIn("secrets.duplicate", self._codes(ctx))

    def test_privileges_cap_add_parsed(self):
        body = VALID_BODY.replace(
            "<execution>",
            '<privileges><service name="postgres" '
            'cap_add="CHOWN SETUID SETGID"/></privileges><execution>')
        cfg = self._parse_text(body)
        self.assertEqual(cfg.cap_add,
                         {"postgres": ["CHOWN", "SETUID", "SETGID"]})

    def test_privileges_cap_outside_dictionary_is_an_error(self):
        body = VALID_BODY.replace(
            "<execution>",
            '<privileges><service name="postgres" '
            'cap_add="CHOWN SYS_ADMIN"/></privileges><execution>')
        with self.assertRaises(ConfigError) as ctx:
            self._parse_text(body)
        self.assertIn("privileges.cap_unknown", self._codes(ctx))

    def test_minimal_valid(self):
        cfg = self._parse_text(VALID_BODY)
        self.assertEqual(cfg.oses, ["lin"])
        self.assertEqual(cfg.execution.timeout_minutes, 5)
        self.assertEqual(cfg.inputs, [])


if __name__ == "__main__":
    unittest.main()
