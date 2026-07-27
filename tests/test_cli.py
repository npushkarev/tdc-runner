"""Smoke tests for tdc.cli (no docker: lower modules mocked)."""
import contextlib
import io
import unittest
from pathlib import Path
from unittest import mock

from tdc import cli
from tdc.model import Execution, ReportSpec, TestConfig

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _parsed_cfg(path):
    cfg = TestConfig(name="", dir=Path("."))
    cfg.oses = ["lin"]
    cfg.arches = ["x64"]
    cfg.reports = [ReportSpec(type="tests", format="junit",
                              path="junit/*.xml")]
    cfg.execution = Execution(main_service="tests", timeout_minutes=10)
    return cfg


class CliValidateSmokeTest(unittest.TestCase):
    def _main(self, argv):
        with mock.patch("tdc.runner.composecheck.list_compose_files",
                        return_value=[]), \
             mock.patch("tdc.runner.xmlcfg.parse_test_cfg",
                        side_effect=_parsed_cfg), \
             mock.patch("tdc.cli.envfile.parse_env_file",
                        return_value={}), \
             mock.patch("tdc.cli.envfile.check_reserved",
                        return_value=[]), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            rc = cli.main(argv)
        return rc, out.getvalue()

    def test_validate_demo_repo_no_docker_ok(self):
        rc, out = self._main(["validate", "--repo",
                              str(FIXTURES / "demo_repo"), "--no-docker"])
        self.assertEqual(rc, 0)
        self.assertIn("postgres_integration", out)

    def test_validate_bad_repo_exits_1(self):
        rc, out = self._main(["validate", "--repo",
                              str(FIXTURES / "bad_repo"), "--no-docker"])
        self.assertEqual(rc, 1)
        self.assertIn("config.bad_name", out)


if __name__ == "__main__":
    unittest.main()
