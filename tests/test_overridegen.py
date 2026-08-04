"""Unit tests for tdc.overridegen (pure, no docker)."""
import json
import tempfile
import unittest
from pathlib import Path

from tdc import overridegen
from tdc.model import (
    HARNESS_LABEL, INJECTED_ENV_NAMES, TEST_INPUT_MOUNT, TEST_OUTPUT_MOUNT,
    Execution, RunContext, Slot, TestConfig,
)

DOC = {"services": {"tests": {"image": "x"}, "postgres": {"image": "y"}}}


def make_cfg():
    cfg = TestConfig(name="demo", dir=Path("/repo/test_docker_config/post_commit/demo"))
    cfg.execution = Execution(main_service="tests", timeout_minutes=5)
    return cfg


def make_ctx(ci_env=None):
    return RunContext(
        mode="ci",
        slot=Slot("lin", "x64"),
        repo_root=Path("/repo"),
        artifacts_root=None,
        output_root=Path("/out"),
        build_id="42",
        ci_env=ci_env if ci_env is not None else
        {"BUILD_NUMBER": "42", "VCS_REVISION": "deadbeef"},
    )


class GenerateOverrideTest(unittest.TestCase):
    def setUp(self):
        self.staging = Path("/out/_work/demo/staging")
        self.output = Path("/out/_work/demo/output")
        self.override = overridegen.generate_override(
            DOC, make_cfg(), make_ctx(), self.staging, self.output)

    def test_covers_every_service(self):
        self.assertEqual(set(self.override["services"]),
                         {"tests", "postgres"})

    def test_volumes_input_ro_output_rw(self):
        for name in ("tests", "postgres"):
            volumes = self.override["services"][name]["volumes"]
            self.assertEqual(volumes, [
                {"type": "bind", "source": str(self.staging),
                 "target": TEST_INPUT_MOUNT, "read_only": True},
                {"type": "bind", "source": str(self.output),
                 "target": TEST_OUTPUT_MOUNT, "read_only": False},
            ])

    def test_injects_all_env_names(self):
        for name in ("tests", "postgres"):
            env = self.override["services"][name]["environment"]
            self.assertEqual(set(env), set(INJECTED_ENV_NAMES))
            self.assertEqual(env["TEST_INPUT"], TEST_INPUT_MOUNT)
            self.assertEqual(env["TEST_OUTPUT"], TEST_OUTPUT_MOUNT)
            self.assertEqual(env["TEST_OS"], "lin")
            self.assertEqual(env["TEST_ARCH"], "x64")
            self.assertEqual(env["TEST_CONFIG_NAME"], "demo")
            self.assertEqual(env["BUILD_NUMBER"], "42")
            self.assertEqual(env["VCS_REVISION"], "deadbeef")

    def test_missing_ci_vars_become_empty_strings(self):
        override = overridegen.generate_override(
            DOC, make_cfg(), make_ctx(ci_env={}), self.staging, self.output)
        env = override["services"]["tests"]["environment"]
        self.assertEqual(env["BUILD_NUMBER"], "")
        self.assertEqual(env["VCS_REVISION"], "")

    def test_limits_and_hardening(self):
        for name in ("tests", "postgres"):
            svc = self.override["services"][name]
            self.assertEqual(svc["pids_limit"], 512)
            self.assertEqual(svc["mem_limit"], "2g")
            self.assertEqual(svc["memswap_limit"], svc["mem_limit"])
            self.assertEqual(svc["cpus"], "2")
            self.assertEqual(svc["cap_drop"], ["ALL"])
            self.assertEqual(svc["security_opt"], ["no-new-privileges:true"])

    def test_cap_add_only_where_declared(self):
        cfg = make_cfg()
        cfg.cap_add = {"postgres": ["CHOWN", "SETUID"]}
        override = overridegen.generate_override(
            DOC, cfg, make_ctx(), self.staging, self.output)
        postgres = override["services"]["postgres"]
        self.assertEqual(postgres["cap_add"], ["CHOWN", "SETUID"])
        self.assertEqual(postgres["cap_drop"], ["ALL"])  # drop stays, add is on top
        self.assertNotIn("cap_add", override["services"]["tests"])

    def test_secrets_mounted_only_where_declared(self):
        from tdc.model import SecretSpec
        cfg = make_cfg()
        cfg.secrets = [SecretSpec("db_password", ["postgres"])]
        ctx = make_ctx(); ctx.secrets_dir = Path("/build/secrets")
        override = overridegen.generate_override(
            DOC, cfg, ctx, self.staging, self.output)
        targets = lambda n: [v["target"] for v in override["services"][n]["volumes"]]
        self.assertIn("/test/secrets", targets("postgres"))
        self.assertNotIn("/test/secrets", targets("tests"))
        mount = [v for v in override["services"]["postgres"]["volumes"]
                 if v["target"] == "/test/secrets"][0]
        self.assertTrue(mount["read_only"])

    def test_secrets_default_to_main_service(self):
        from tdc.model import SecretSpec
        cfg = make_cfg()
        cfg.secrets = [SecretSpec("api_key", [])]  # services= не указан
        ctx = make_ctx(); ctx.secrets_dir = Path("/build/secrets")
        override = overridegen.generate_override(
            DOC, cfg, ctx, self.staging, self.output)
        targets = lambda n: [v["target"] for v in override["services"][n]["volumes"]]
        self.assertIn("/test/secrets", targets("tests"))       # главный
        self.assertNotIn("/test/secrets", targets("postgres"))

    def test_no_secrets_dir_no_mount(self):
        from tdc.model import SecretSpec
        cfg = make_cfg()
        cfg.secrets = [SecretSpec("api_key", [])]
        override = overridegen.generate_override(
            DOC, cfg, make_ctx(), self.staging, self.output)
        for name in ("tests", "postgres"):
            self.assertNotIn("/test/secrets",
                             [v["target"] for v in
                              override["services"][name]["volumes"]])

    def test_harness_label(self):
        for name in ("tests", "postgres"):
            self.assertEqual(self.override["services"][name]["labels"],
                             {HARNESS_LABEL: "1"})

    def test_restart_no_only_on_non_main(self):
        self.assertEqual(self.override["services"]["postgres"]["restart"],
                         "no")
        self.assertNotIn("restart", self.override["services"]["tests"])

    def test_default_network_internal(self):
        self.assertEqual(self.override["networks"],
                         {"default": {"internal": True}})


class WriteOverrideTest(unittest.TestCase):
    def test_writes_json_and_returns_path(self):
        override = overridegen.generate_override(
            DOC, make_cfg(), make_ctx(),
            Path("/s"), Path("/o"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "docker-compose.harness.yml"
            returned = overridegen.write_override(override, path)
            self.assertEqual(returned, path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                             override)


if __name__ == "__main__":
    unittest.main()
