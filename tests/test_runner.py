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


def _proc(stdout="", returncode=0, stderr=""):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout,
                                 stderr=stderr)


class FakeExecute(object):
    """Records commands; answers `compose ps -q` and `docker wait`."""

    def __init__(self, wait_stdout="0\n", wait_exc=None, up_rc=0,
                 up_stderr="", on_up=None):
        # on_up имитирует контейнер: он пишет отчёты во время прогона, а не до
        # него — иначе фикстура расходится с реальностью (ядро чистит каталоги
        # перед стартом).
        self.on_up = on_up
        self.calls = []
        self.wait_stdout = wait_stdout
        self.wait_exc = wait_exc
        self.up_rc = up_rc
        self.up_stderr = up_stderr

    def __call__(self, cmd, **kw):
        cmd = list(cmd)
        self.calls.append((cmd, kw))
        if cmd[:2] == ["docker", "wait"]:
            if self.wait_exc is not None:
                raise self.wait_exc
            return _proc(self.wait_stdout)
        if len(cmd) >= 3 and cmd[-3:-1] == ["ps", "-q"]:
            return _proc("cid123\n")
        if cmd[-2:] == ["up", "-d"]:
            if self.on_up is not None and self.up_rc == 0:
                self.on_up()
            return _proc(returncode=self.up_rc, stderr=self.up_stderr)
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

    def _execute(self, **kw):
        """FakeExecute, который «пишет» отчёт в момент up, как контейнер."""
        kw.setdefault("on_up", self._seed_report)
        return FakeExecute(**kw)

    def _seed_report(self):
        report_dir = self.out / "_work" / "demo" / "output" / "junit"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "r.xml").write_text("<testsuite/>", encoding="utf-8")

    def test_happy_path_command_order_and_passed(self):
        execute = self._execute(wait_stdout="0\n")
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

    def test_env_local_overrides_only_in_local_mode(self):
        (self.cfg_dir / ".env.local").write_text("POSTGRES_USER=mine\n",
                                                 encoding="utf-8")
        self.mocks["parse_env_file"].side_effect = [
            {"POSTGRES_USER": "test"}, {"POSTGRES_USER": "mine"}]
        self.ctx.mode = "local"
        runner.run_config(self.cfg, self.ctx, self._execute(wait_stdout="0\n"))
        # .env.default прочитан, затем перекрыт .env.local
        self.assertEqual(self.mocks["parse_env_file"].call_count, 2)

    def test_env_local_ignored_in_ci_with_a_warning(self):
        (self.cfg_dir / ".env.local").write_text("POSTGRES_USER=mine\n",
                                                 encoding="utf-8")
        result = runner.run_config(self.cfg, self.ctx,
                                   self._execute(wait_stdout="0\n"))
        self.assertEqual(self.mocks["parse_env_file"].call_count, 1)
        self.assertIn("env.local_ignored", [i.code for i in result.issues])

    def test_stale_reports_from_previous_run_are_wiped(self):
        # На стенде: 331/7447 превратилось в 993/22341 за три прогона, а упавший
        # прогон рапортовал покрытие из чужих файлов.
        stale_work = self.out / "_work" / "demo" / "output" / "coverage"
        stale_work.mkdir(parents=True)
        (stale_work / "old.cobertura.xml").write_text(
            '<coverage lines-covered="999" lines-valid="999"/>', encoding="utf-8")
        stale_rep = self.out / "reports" / "demo" / "tests"
        stale_rep.mkdir(parents=True)
        (stale_rep / "old.trx").write_text("<TestRun/>", encoding="utf-8")

        runner.run_config(self.cfg, self.ctx, self._execute(wait_stdout="0\n"))

        self.assertFalse((stale_work / "old.cobertura.xml").exists())
        self.assertFalse((stale_rep / "old.trx").exists())
        # свежий отчёт при этом на месте
        self.assertTrue((self.out / "reports" / "demo" / "tests" / "junit"
                         / "r.xml").is_file())

    def test_up_failure_reports_the_reason(self):
        # "up failed (rc=1)" alone sends people digging; docker already said why
        stderr = ("time=... level=warning msg=...\n"
                  "Error response from daemon: pull access denied for "
                  "proget.inc.elara.local/main/library/postgres:18.1\n")
        execute = FakeExecute(up_rc=1, up_stderr=stderr)
        result = runner.run_config(self.cfg, self.ctx, execute)
        self.assertEqual(result.status, FAILED)
        self.assertIn("pull access denied", result.details)
        # full stderr kept as evidence next to the other infra files
        saved = (self.out / "reports" / "demo" / "_infra" / "up-stderr.txt")
        self.assertIn("Error response from daemon", saved.read_text())
        self.assertIn("down", execute.verbs())  # cleanup still runs

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

    def test_output_dir_is_writable_by_the_container(self):
        # container root runs under cap_drop: ALL -> no DAC_OVERRIDE, so a dir
        # owned by the (non-root) agent user must be world-writable or every
        # report is lost. Verified on the dev stand: touch -> Permission denied.
        runner.run_config(self.cfg, self.ctx, self._execute(wait_stdout="0\n"))
        mode = (self.out / "_work" / "demo" / "output").stat().st_mode
        self.assertEqual(mode & 0o777, 0o777)

    def test_cobertura_reports_emit_build_statistics(self):
        def seed():
            self._seed_report()
            cov_dir = self.out / "_work" / "demo" / "output" / "coverage"
            cov_dir.mkdir(parents=True, exist_ok=True)
            for name, covered in (("a.xml", 30), ("b.xml", 10)):
                (cov_dir / name).write_text(
                    '<coverage lines-covered="%d" lines-valid="100" '
                    'branches-covered="5" branches-valid="20"/>' % covered,
                    encoding="utf-8")
        self.cfg.reports.append(ReportSpec(type="coverage",
                                           format="cobertura",
                                           path="coverage/*.xml"))
        with mock.patch("tdc.runner.teamcity.build_statistic") as stat:
            runner.run_config(self.cfg, self.ctx,
                              self._execute(wait_stdout="0\n", on_up=seed))
        emitted = {c[0][0]: c[0][1] for c in stat.call_args_list}
        # counters summed across files, percentage derived from the totals
        self.assertEqual(emitted["CodeCoverageAbsLCovered"], 40)
        self.assertEqual(emitted["CodeCoverageAbsLTotal"], 200)
        self.assertEqual(emitted["CodeCoverageL"], 20.0)
        self.assertEqual(emitted["CodeCoverageB"], 25.0)  # (5+5)/(20+20)
        # cobertura has no TC importer -> no importData for it
        self.assertEqual([c[0][0] for c in self.import_data.call_args_list],
                         ["junit"])

    def test_duplicate_cobertura_counted_once(self):
        # VSTest writes the same report under results/<guid>/ and again into
        # the attachment dir; a wider glob catches both and used to double
        # every counter (seen with coverlet 8.0.1 on a real dotnet run).
        body = ('<coverage lines-covered="26" lines-valid="27" '
                'branches-covered="5" branches-valid="10"/>')

        def seed():
            self._seed_report()
            for sub in ("guid", "_host_2026_08_03/In/host"):
                d = self.out / "_work" / "demo" / "output" / "coverage" / sub
                d.mkdir(parents=True, exist_ok=True)
                (d / "coverage.cobertura.xml").write_text(body, encoding="utf-8")
        self.cfg.reports.append(ReportSpec(
            type="coverage", format="cobertura",
            path="coverage/**/coverage.cobertura.xml"))
        with mock.patch("tdc.runner.teamcity.build_statistic") as stat:
            runner.run_config(self.cfg, self.ctx,
                              self._execute(wait_stdout="0\n", on_up=seed))
        emitted = {c[0][0]: c[0][1] for c in stat.call_args_list}
        self.assertEqual(emitted["CodeCoverageAbsLCovered"], 26)  # not 52
        self.assertEqual(emitted["CodeCoverageAbsLTotal"], 27)
        self.assertEqual(emitted["CodeCoverageL"], 96.3)

    def test_malformed_cobertura_does_not_break_collection(self):
        def seed():
            self._seed_report()
            cov_dir = self.out / "_work" / "demo" / "output" / "coverage"
            cov_dir.mkdir(parents=True, exist_ok=True)
            (cov_dir / "broken.xml").write_text("<coverage", encoding="utf-8")
        self.cfg.reports.append(ReportSpec(type="coverage",
                                           format="cobertura",
                                           path="coverage/*.xml"))
        with mock.patch("tdc.runner.teamcity.build_statistic") as stat:
            result = runner.run_config(self.cfg, self.ctx,
                                       self._execute(wait_stdout="0\n", on_up=seed))
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
