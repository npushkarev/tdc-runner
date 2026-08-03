"""Unit tests for tdc.runner.

Sibling modules (xmlcfg, envfile, staging, composecheck) are developed in
parallel and mocked here per their docstring signatures. No docker: all
lifecycle commands go through a recording fake execute.
"""
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from tdc import runner
from tdc.model import (
    Execution, ReportSpec, RunContext, Slot, TestConfig, ValidationIssue,
    PASSED, FAILED, ERROR,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _proc(stdout="", returncode=0):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout,
                                 stderr="")


class FakeExecute(object):
    """Records commands; answers `compose ps -q` and `docker wait`."""

    def __init__(self, wait_stdout="0\n", wait_exc=None):
        self.calls = []
        self.wait_stdout = wait_stdout
        self.wait_exc = wait_exc

    def __call__(self, cmd, **kw):
        cmd = list(cmd)
        self.calls.append((cmd, kw))
        if cmd[:2] == ["docker", "wait"]:
            if self.wait_exc is not None:
                raise self.wait_exc
            return _proc(self.wait_stdout)
        if len(cmd) >= 3 and cmd[-3:-1] == ["ps", "-q"]:
            return _proc("cid123\n")
        if cmd[-3:] == ["logs", "--no-color", "-t"]:
            return _proc("LOGLINE\n")
        if cmd[-2:] == ["ps", "-a"]:
            return _proc("PSLINE\n")
        return _proc()

    def verbs(self):
        out = []
        for cmd, _kw in self.calls:
            if cmd[:2] == ["docker", "wait"]:
                out.append("wait")
            elif cmd[-1:] == ["pull"]:
                out.append("pull")
            elif cmd[-2:] == ["up", "-d"]:
                out.append("up")
            elif len(cmd) >= 3 and cmd[-3:-1] == ["ps", "-q"]:
                out.append("ps-q")
            elif cmd[-3:] == ["logs", "--no-color", "-t"]:
                out.append("logs")
            elif cmd[-2:] == ["ps", "-a"]:
                out.append("ps-a")
            elif cmd[-3:] == ["down", "-v", "--remove-orphans"]:
                out.append("down")
            else:
                out.append("other")
        return out


class ScanConfigsTest(unittest.TestCase):
    def test_demo_repo_one_dir(self):
        dirs = runner.scan_configs(FIXTURES / "demo_repo")
        self.assertEqual([d.name for d in dirs], ["postgres_integration"])

    def test_bad_repo_two_dirs(self):
        dirs = runner.scan_configs(FIXTURES / "bad_repo")
        self.assertEqual([d.name for d in dirs], ["Bad_Name", "violations"])

    def test_missing_root_empty(self):
        self.assertEqual(runner.scan_configs(FIXTURES / "no_such_repo"), [])


class LoadConfigTest(unittest.TestCase):
    def test_bad_name_flagged(self):
        config_dir = (FIXTURES / "bad_repo" / "test_docker_config"
                      / "post_commit" / "Bad_Name")
        parsed = TestConfig(name="", dir=Path("."))
        with mock.patch("tdc.runner.composecheck.list_compose_files",
                        return_value=[]), \
             mock.patch("tdc.runner.xmlcfg.parse_test_cfg",
                        return_value=parsed):
            cfg, issues = runner.load_config(config_dir)
        self.assertIn("config.bad_name", [i.code for i in issues])
        self.assertIs(cfg, parsed)
        self.assertEqual(cfg.name, "Bad_Name")
        self.assertEqual(cfg.dir, config_dir)


class RunConfigTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.cfg_dir = self.tmp / "cfg" / "demo"
        self.cfg_dir.mkdir(parents=True)
        self.out = self.tmp / "out"
        self.cfg = TestConfig(name="demo", dir=self.cfg_dir)
        self.cfg.oses = ["lin"]
        self.cfg.arches = ["x64"]
        self.cfg.reports = [ReportSpec(type="tests", format="junit",
                                       path="junit/*.xml")]
        self.cfg.execution = Execution(main_service="tests",
                                       timeout_minutes=5)
        self.ctx = RunContext(
            mode="ci", slot=Slot("lin", "x64"),
            repo_root=FIXTURES / "demo_repo",
            artifacts_root=None, output_root=self.out, build_id="7",
            ci_env={"BUILD_NUMBER": "7", "VCS_REVISION": "deadbeef"})
        # sibling modules under parallel development -> mock per docstring
        patches = {
            "tdc.runner.envfile.parse_env_file":
                dict(return_value={"POSTGRES_USER": "test"}),
            "tdc.runner.envfile.check_reserved": dict(return_value=[]),
            "tdc.runner.envfile.merge_env":
                dict(side_effect=lambda d, ci: dict(d, **ci)),
            "tdc.runner.envfile.render_env_file":
                dict(return_value="POSTGRES_USER=test\n"),
            "tdc.runner.composecheck.normalize_compose":
                dict(return_value={"services": {"tests": {},
                                                "postgres": {}}}),
            "tdc.runner.composecheck.check_compose": dict(return_value=[]),
            "tdc.runner.staging.validate_input_spec": dict(return_value=[]),
            "tdc.runner.staging.stage_inputs": dict(return_value=[]),
        }
        self.mocks = {}
        for target, kwargs in patches.items():
            patcher = mock.patch(target, **kwargs)
            self.mocks[target.rsplit(".", 1)[1]] = patcher.start()
            self.addCleanup(patcher.stop)
        import_patcher = mock.patch("tdc.runner.teamcity.import_data")
        self.import_data = import_patcher.start()
        self.addCleanup(import_patcher.stop)

    def _seed_report(self):
        report_dir = self.out / "_work" / "demo" / "output" / "junit"
        report_dir.mkdir(parents=True)
        (report_dir / "r.xml").write_text("<testsuite/>", encoding="utf-8")

    def test_happy_path_command_order_and_passed(self):
        self._seed_report()
        execute = FakeExecute(wait_stdout="0\n")
        result = runner.run_config(self.cfg, self.ctx, execute)
        self.assertEqual(execute.verbs(),
                         ["pull", "up", "ps-q", "wait", "logs", "ps-a",
                          "down"])
        self.assertEqual(result.status, PASSED)
        # timeout enforced on docker wait only
        wait_kw = execute.calls[3][1]
        self.assertEqual(wait_kw.get("timeout"), 5 * 60)
        # report copied under reports/<cfg>/<type>/ and imported
        dest = self.out / "reports" / "demo" / "tests" / "junit" / "r.xml"
        self.assertTrue(dest.is_file())
        self.import_data.assert_called_once_with("junit", str(dest))
        # infra evidence collected before down
        infra = self.out / "reports" / "demo" / "_infra"
        self.assertEqual((infra / "compose-logs.txt").read_text(), "LOGLINE\n")
        self.assertTrue((infra / "compose-ps.txt").is_file())

    def test_nonzero_wait_exit_failed(self):
        execute = FakeExecute(wait_stdout="1\n")
        result = runner.run_config(self.cfg, self.ctx, execute)
        self.assertEqual(result.status, FAILED)
        self.assertIn("down", execute.verbs())

    def test_validation_error_no_docker_commands(self):
        self.mocks["check_compose"].return_value = [ValidationIssue(
            "error", "compose.build_forbidden", "service tests: build")]
        execute = FakeExecute()
        result = runner.run_config(self.cfg, self.ctx, execute)
        self.assertEqual(result.status, ERROR)
        self.assertEqual(execute.calls, [])
        self.assertIn("compose.build_forbidden",
                      [i.code for i in result.issues])

    def test_wait_timeout_failed_and_down_still_runs(self):
        execute = FakeExecute(wait_exc=subprocess.TimeoutExpired(
            cmd="docker wait", timeout=300))
        result = runner.run_config(self.cfg, self.ctx, execute)
        self.assertEqual(result.status, FAILED)
        self.assertIn("timeout", result.details)
        self.assertIn("down", execute.verbs())

    def test_cobertura_reports_emit_build_statistics(self):
        self._seed_report()
        cov_dir = self.out / "_work" / "demo" / "output" / "coverage"
        cov_dir.mkdir(parents=True)
        for name, covered in (("a.xml", 30), ("b.xml", 10)):
            (cov_dir / name).write_text(
                '<coverage lines-covered="%d" lines-valid="100" '
                'branches-covered="5" branches-valid="20"/>' % covered,
                encoding="utf-8")
        self.cfg.reports.append(ReportSpec(type="coverage",
                                           format="cobertura",
                                           path="coverage/*.xml"))
        with mock.patch("tdc.runner.teamcity.build_statistic") as stat:
            runner.run_config(self.cfg, self.ctx, FakeExecute(wait_stdout="0\n"))
        emitted = {c[0][0]: c[0][1] for c in stat.call_args_list}
        # counters summed across files, percentage derived from the totals
        self.assertEqual(emitted["CodeCoverageAbsLCovered"], 40)
        self.assertEqual(emitted["CodeCoverageAbsLTotal"], 200)
        self.assertEqual(emitted["CodeCoverageL"], 20.0)
        self.assertEqual(emitted["CodeCoverageB"], 25.0)  # (5+5)/(20+20)
        # cobertura has no TC importer -> no importData for it
        self.assertEqual([c[0][0] for c in self.import_data.call_args_list],
                         ["junit"])

    def test_malformed_cobertura_does_not_break_collection(self):
        self._seed_report()
        cov_dir = self.out / "_work" / "demo" / "output" / "coverage"
        cov_dir.mkdir(parents=True)
        (cov_dir / "broken.xml").write_text("<coverage", encoding="utf-8")
        self.cfg.reports.append(ReportSpec(type="coverage",
                                           format="cobertura",
                                           path="coverage/*.xml"))
        with mock.patch("tdc.runner.teamcity.build_statistic") as stat:
            result = runner.run_config(self.cfg, self.ctx,
                                       FakeExecute(wait_stdout="0\n"))
        self.assertEqual(result.status, PASSED)
        stat.assert_not_called()
        self.assertTrue((self.out / "reports" / "demo" / "coverage"
                         / "coverage" / "broken.xml").is_file())

    def test_dry_run_no_docker_commands(self):
        self.ctx.dry_run = True
        execute = FakeExecute()
        result = runner.run_config(self.cfg, self.ctx, execute)
        self.assertEqual(result.status, PASSED)
        self.assertEqual(result.details, "dry-run")
        self.assertEqual(execute.calls, [])


if __name__ == "__main__":
    unittest.main()
