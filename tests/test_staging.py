"""Unit tests for tdc.staging (glob staging, slot filter, symlink safety).

tdc.slots is implemented separately; the slot-filter path is tested through
unittest.mock.patch, everything else uses source specs / slot_filter=False.
"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tdc import staging
from tdc.model import InputSpec, RunContext, Slot, TestConfig

FIXTURES = Path(__file__).parent / "fixtures"


def _write(root, rel, content=""):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


class StagingBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tdc-staging-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.staging = self.tmp / "staging"

    def ctx(self, artifacts_root=None):
        return RunContext(mode="local", slot=Slot("lin", "x64"),
                          repo_root=self.repo, artifacts_root=artifacts_root,
                          output_root=self.tmp / "out")

    def cfg(self, inputs):
        return TestConfig(name="t", dir=self.repo, inputs=inputs)

    def codes(self, issues):
        return [i.code for i in issues]


class TestValidateInputSpec(StagingBase):
    def test_dotdot_and_relative_dest_rejected(self):
        # mirrors bad_repo violations/test_cfg.xml: <artifact path="../../secrets/**" dest="../out"/>
        issues = staging.validate_input_spec(
            InputSpec("artifact", "../../secrets/**", "../out"))
        self.assertEqual(self.codes(issues),
                         ["inputs.path_escape", "inputs.path_escape"])

    def test_root_glob_source_rejected(self):
        # mirrors bad_repo violations/test_cfg.xml: <source path="**" dest="all/"/>
        issues = staging.validate_input_spec(InputSpec("source", "**", "all/"))
        self.assertEqual(self.codes(issues), ["inputs.source_root_glob"])

    def test_glob_meta_in_first_source_segment_rejected(self):
        issues = staging.validate_input_spec(
            InputSpec("source", "te*ts/data/**", "data/"))
        self.assertEqual(self.codes(issues), ["inputs.source_root_glob"])

    def test_absolute_path_rejected(self):
        issues = staging.validate_input_spec(
            InputSpec("source", "/etc/passwd", "x/"))
        self.assertIn("inputs.path_escape", self.codes(issues))

    def test_valid_specs_pass(self):
        self.assertEqual(staging.validate_input_spec(
            InputSpec("source", "tests/data/**", "data/")), [])
        self.assertEqual(staging.validate_input_spec(
            InputSpec("artifact", "packages/*.nupkg", "packages/")), [])


class TestResolveGlob(StagingBase):
    def test_sorted_files_only(self):
        _write(self.repo, "b.txt")
        _write(self.repo, "a.txt")
        (self.repo / "subdir").mkdir()
        got = staging.resolve_glob(self.repo, "*")
        self.assertEqual(got, [self.repo / "a.txt", self.repo / "b.txt"])

    def test_recursive_glob_matches_nested_files(self):
        _write(self.repo, "out/z.txt")
        _write(self.repo, "out/x/y.txt")
        got = staging.resolve_glob(self.repo, "out/**")
        self.assertEqual(got, [self.repo / "out/x/y.txt", self.repo / "out/z.txt"])


class TestStageInputs(StagingBase):
    def test_recursive_glob_preserves_structure_after_prefix(self):
        _write(self.repo, "tests/data/seed.sql", "select 1;")
        _write(self.repo, "tests/data/sub/extra.csv", "1,2")
        issues = staging.stage_inputs(
            self.cfg([InputSpec("source", "tests/data/**", "data/")]),
            self.ctx(), self.staging)
        self.assertEqual(issues, [])
        self.assertEqual((self.staging / "data/seed.sql").read_text(), "select 1;")
        self.assertTrue((self.staging / "data/sub/extra.csv").is_file())
        # nothing keeps the static prefix "tests/data"
        self.assertFalse((self.staging / "data/tests").exists())

    def test_demo_repo_fixture_source_spec(self):
        repo = FIXTURES / "demo_repo"
        cfg = TestConfig(name="postgres_integration", dir=repo,
                         inputs=[InputSpec("source", "tests/data/**", "data/")])
        ctx = RunContext(mode="local", slot=Slot("lin", "x64"), repo_root=repo,
                         artifacts_root=None, output_root=self.tmp / "out")
        issues = staging.stage_inputs(cfg, ctx, self.staging)
        self.assertEqual(issues, [])
        self.assertTrue((self.staging / "data/seed.sql").is_file())

    def test_zero_matches_errors_unless_optional(self):
        issues = staging.stage_inputs(
            self.cfg([InputSpec("source", "nosuch/**", "d/")]),
            self.ctx(), self.staging)
        self.assertEqual(self.codes(issues), ["inputs.zero_matches"])

        issues = staging.stage_inputs(
            self.cfg([InputSpec("source", "nosuch/**", "d/", optional=True)]),
            self.ctx(), self.staging)
        self.assertEqual(issues, [])

    def test_dest_collision_between_specs(self):
        _write(self.repo, "a/f.txt", "first")
        _write(self.repo, "b/f.txt", "second")
        issues = staging.stage_inputs(
            self.cfg([InputSpec("source", "a/*", "d/"),
                      InputSpec("source", "b/*", "d/")]),
            self.ctx(), self.staging)
        self.assertEqual(self.codes(issues), ["inputs.dest_collision"])
        # first spec won; the collision did not overwrite
        self.assertEqual((self.staging / "d/f.txt").read_text(), "first")

    def test_symlink_inside_stays_link_outside_removed(self):
        _write(self.repo, "data/file.txt", "payload")
        _write(self.tmp, "outside.txt", "secret")
        os.symlink("file.txt", str(self.repo / "data/link_in"))
        os.symlink(str(self.tmp / "outside.txt"),
                   str(self.repo / "data/link_out"))
        issues = staging.stage_inputs(
            self.cfg([InputSpec("source", "data/*", "d/")]),
            self.ctx(), self.staging)
        self.assertEqual(self.codes(issues), ["inputs.symlink_escape"])
        self.assertTrue(os.path.islink(str(self.staging / "d/link_in")))
        self.assertEqual((self.staging / "d/link_in").read_text(), "payload")
        self.assertFalse(os.path.lexists(str(self.staging / "d/link_out")))

    def test_artifact_without_artifacts_root(self):
        issues = staging.stage_inputs(
            self.cfg([InputSpec("artifact", "packages/*.nupkg", "p/")]),
            self.ctx(artifacts_root=None), self.staging)
        self.assertEqual(self.codes(issues), ["inputs.no_artifacts"])

    def test_slot_filter_via_mock(self):
        arts = self.tmp / "arts"
        _write(arts, "packages/pkg.lin.x64.nupkg")
        _write(arts, "packages/pkg.win.x64.nupkg")
        with mock.patch("tdc.slots.path_matches_slot",
                        side_effect=lambda rel, slot: ".lin." in rel) as pm:
            issues = staging.stage_inputs(
                self.cfg([InputSpec("artifact", "packages/*.nupkg", "p/")]),
                self.ctx(artifacts_root=arts), self.staging)
        self.assertEqual(self.codes(issues), ["inputs.slot_filtered"])
        self.assertEqual(issues[0].severity, "warning")
        self.assertIn("1 match(es)", issues[0].message)
        self.assertTrue((self.staging / "p/pkg.lin.x64.nupkg").is_file())
        self.assertFalse((self.staging / "p/pkg.win.x64.nupkg").exists())
        pm.assert_any_call("packages/pkg.lin.x64.nupkg", Slot("lin", "x64"))

    def test_slot_filter_off_stages_everything(self):
        arts = self.tmp / "arts"
        _write(arts, "packages/pkg.lin.x64.nupkg")
        _write(arts, "packages/pkg.win.x64.nupkg")
        with mock.patch("tdc.slots.path_matches_slot") as pm:
            issues = staging.stage_inputs(
                self.cfg([InputSpec("artifact", "packages/*.nupkg", "p/",
                                    slot_filter=False)]),
                self.ctx(artifacts_root=arts), self.staging)
        self.assertEqual(issues, [])
        pm.assert_not_called()
        self.assertTrue((self.staging / "p/pkg.lin.x64.nupkg").is_file())
        self.assertTrue((self.staging / "p/pkg.win.x64.nupkg").is_file())


if __name__ == "__main__":
    unittest.main()
