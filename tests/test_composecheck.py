"""Tests for tdc.composecheck: pure unit checks on hand-built normalized
documents, fixture scans, and one docker-gated 'compose config' integration."""
import tempfile
import unittest
from pathlib import Path

from tdc import composebin, composecheck
from tdc.model import DEFAULT_REGISTRY_PREFIXES

FIXTURES = Path(__file__).parent / "fixtures"
DEMO_CFG = (FIXTURES / "demo_repo" / "test_docker_config" / "post_commit"
            / "postgres_integration")
BAD_CFG = (FIXTURES / "bad_repo" / "test_docker_config" / "post_commit"
           / "violations")


def valid_doc():
    """Hand-built equivalent of 'docker compose config --format json'."""
    return {
        "name": "demo-project",
        "services": {
            "tests": {
                "image": "proget.inc.elara.local/test-images/x-tests:1.2",
                "environment": {"MODE": "ci"},
                "healthcheck": {"test": ["CMD", "true"], "interval": "5s"},
                "volumes": [
                    {"type": "volume", "source": "data",
                     "target": "/var/lib/x", "volume": {}},
                ],
            },
        },
        "networks": {"default": {"name": "demo-project_default"}},
        "volumes": {"data": {"name": "demo-project_data"}},
    }


def codes(issues):
    return [i.code for i in issues]


class CheckComposeTest(unittest.TestCase):
    def check(self, doc, main_service="tests"):
        return composecheck.check_compose(doc, main_service,
                                          DEFAULT_REGISTRY_PREFIXES)

    def test_valid_doc_no_issues(self):
        self.assertEqual([], self.check(valid_doc()))

    FORBIDDEN = {
        "build": ({"context": "."}, "compose.build_forbidden"),
        "ports": (["8080:80"], "compose.ports_forbidden"),
        "privileged": (True, "compose.privilege_forbidden"),
        "cap_add": (["SYS_ADMIN"], "compose.privilege_forbidden"),
        "devices": (["/dev/kvm:/dev/kvm"], "compose.privilege_forbidden"),
        "security_opt": (["seccomp=unconfined"], "compose.privilege_forbidden"),
        "sysctls": ({"net.core.somaxconn": "1024"},
                    "compose.privilege_forbidden"),
        "network_mode": ("host", "compose.host_namespace"),
        "pid": ("host", "compose.host_namespace"),
        "ipc": ("host", "compose.host_namespace"),
        "uts": ("host", "compose.host_namespace"),
        "userns_mode": ("host", "compose.host_namespace"),
        "cgroup_parent": ("system.slice", "compose.host_namespace"),
        "extends": ({"file": "../other.yml", "service": "x"},
                    "compose.extends_forbidden"),
        "volumes_from": (["helper"], "compose.volumes_from_forbidden"),
        "secrets": ([{"source": "s"}], "compose.secrets_forbidden"),
        "configs": ([{"source": "c"}], "compose.secrets_forbidden"),
        "logging": ({"driver": "syslog"}, "compose.logging_forbidden"),
        "dns": (["10.0.0.1"], "compose.dns_forbidden"),
        "extra_hosts": (["host.internal:10.0.0.1"], "compose.dns_forbidden"),
        "restart": ("always", "compose.restart_forbidden"),
        "container_name": ("fixed-tests",
                           "compose.container_name_forbidden"),
    }

    def test_forbidden_keys_get_specific_codes(self):
        for key in sorted(self.FORBIDDEN):
            value, expected = self.FORBIDDEN[key]
            with self.subTest(key=key):
                doc = valid_doc()
                doc["services"]["tests"][key] = value
                got = codes(self.check(doc))
                self.assertIn(expected, got)
                self.assertNotIn("compose.key_forbidden", got)

    def test_unknown_key_generic_code(self):
        doc = valid_doc()
        doc["services"]["tests"]["runtime"] = "nvidia"
        issues = self.check(doc)
        self.assertEqual(["compose.key_forbidden"], codes(issues))
        self.assertEqual("error", issues[0].severity)
        self.assertIn("tests", issues[0].message)
        self.assertIn("runtime", issues[0].message)

    def test_image_missing(self):
        doc = valid_doc()
        del doc["services"]["tests"]["image"]
        self.assertEqual(["compose.image_required"], codes(self.check(doc)))

    def test_image_without_tag(self):
        doc = valid_doc()
        doc["services"]["tests"]["image"] = "proget.inc.elara.local/x/y"
        self.assertEqual(["compose.image_tag"], codes(self.check(doc)))

    def test_image_latest_tag(self):
        doc = valid_doc()
        doc["services"]["tests"]["image"] = \
            "proget.inc.elara.local/x/y:latest"
        self.assertEqual(["compose.image_tag"], codes(self.check(doc)))

    def test_image_foreign_registry(self):
        doc = valid_doc()
        doc["services"]["tests"]["image"] = "docker.io/library/alpine:3.19"
        self.assertEqual(["compose.image_registry"], codes(self.check(doc)))

    def test_bind_mount_docker_sock(self):
        doc = valid_doc()
        doc["services"]["tests"]["volumes"].append(
            {"type": "bind", "source": "/var/run/docker.sock",
             "target": "/var/run/docker.sock", "bind": {}})
        issues = self.check(doc)
        self.assertEqual(["compose.bind_mount"], codes(issues))
        self.assertIn("docker.sock", issues[0].message)

    def test_bind_mount_plain(self):
        doc = valid_doc()
        doc["services"]["tests"]["volumes"].append(
            {"type": "bind", "source": "/home/u/src", "target": "/app/src",
             "bind": {"create_host_path": True}})
        self.assertEqual(["compose.bind_mount"], codes(self.check(doc)))

    def test_reserved_mount_target(self):
        doc = valid_doc()
        doc["services"]["tests"]["volumes"].append(
            {"type": "volume", "source": "cache", "target": "/test/x",
             "volume": {}})
        doc["volumes"]["cache"] = {"name": "demo-project_cache"}
        self.assertEqual(["compose.reserved_mount"], codes(self.check(doc)))

    def test_volume_driver_opts(self):
        doc = valid_doc()
        doc["volumes"]["data"] = {
            "driver_opts": {"type": "none", "device": "/etc", "o": "bind"}}
        self.assertEqual(["compose.volume_opts"], codes(self.check(doc)))

    def test_main_service_missing(self):
        issues = self.check(valid_doc(), main_service="absent")
        self.assertEqual(["compose.main_service"], codes(issues))

    def test_env_file_foreign(self):
        doc = valid_doc()
        doc["services"]["tests"]["env_file"] = [
            {"path": "/somewhere/else/vars.env"}]
        self.assertEqual(["compose.env_file_foreign"], codes(self.check(doc)))

    def test_env_file_local_ok(self):
        doc = valid_doc()
        doc["services"]["tests"]["env_file"] = [str(DEMO_CFG / ".env")]
        issues = composecheck.check_compose(
            doc, "tests", DEFAULT_REGISTRY_PREFIXES, config_dir=DEMO_CFG)
        self.assertEqual([], issues)


class ListComposeFilesTest(unittest.TestCase):
    def test_extra_override_flagged(self):
        issues = composecheck.list_compose_files(BAD_CFG)
        self.assertEqual(["compose.extra_file"], codes(issues))
        self.assertIn("docker-compose.override.yml", issues[0].message)

    def test_clean_config_dir(self):
        self.assertEqual([], composecheck.list_compose_files(DEMO_CFG))


COMPOSE_BIN, COMPOSE_SOURCE = composebin.resolve()


@unittest.skipUnless(COMPOSE_BIN, "no compose available: %s" % COMPOSE_SOURCE)
class NormalizeComposeIntegrationTest(unittest.TestCase):
    def test_normalize_then_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("POSTGRES_USER=t\nPOSTGRES_PASSWORD=t\n",
                                encoding="utf-8")
            doc = composecheck.normalize_compose(
                DEMO_CFG, env_file, COMPOSE_BIN)
        self.assertIsInstance(doc, dict)
        self.assertEqual({"postgres", "tests"},
                         set(doc.get("services", {})))
        issues = composecheck.check_compose(
            doc, "tests", DEFAULT_REGISTRY_PREFIXES, config_dir=DEMO_CFG)
        self.assertEqual([], issues)


if __name__ == "__main__":
    unittest.main()
