"""python_security_floor: lock, constraint and bundle checks against real resolvers.

The lifecycle tests build throwaway environments with uv (and pip for the
Takahe-style requirements install), install real certifi/pip releases, and
run the role's inspector and filters on them. They need network access to
PyPI or a warm uv cache.
"""

import getpass
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from ansible.errors import AnsibleFilterError

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/python_security"
ROLE = ROOT / "roles/python_security_floor"
INSPECTOR = ROLE / "files/inspect_python_security.py"

spec = importlib.util.spec_from_file_location(
    "python_security", ROOT / "plugins/filter/python_security.py"
)
flt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flt)

DEFAULTS = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
FLOORS = DEFAULTS["python_security_floor_packages"]
ROOTS = DEFAULTS["python_security_floor_distrusted_roots"]
REQUIRES = DEFAULTS["python_security_floor_requires_python"]
# Published distrusted certificate fingerprint.
# pragma: allowlist nextline secret
G3 = "86A1ECBA089C4A8D3BBE2734C612BA341D813E043CF9E8A862CD5C57A36BBE6B"
UV = shutil.which("uv")


CERTIFI_FLOOR = "2026.10.19"


def version_tuple(version):
    return tuple(int(part) for part in version.split("."))


def violations(report):
    return flt.python_security_report_violations(report, FLOORS, ROOTS, REQUIRES)


def env_report(**packages):
    base = {
        "installed": True,
        "in_environment": True,
        "bundle": "/env/cacert.pem",
        "bundle_fingerprints": [],
    }
    return {
        "python_version": "3.12.5",
        "packages": {
            name: ({**base, **info} if info.get("installed", True) else info)
            for name, info in packages.items()
        },
    }


class LockFloorTests(unittest.TestCase):
    def test_stale_lock_reports_each_package_below_its_floor(self):
        problems = flt.uv_lock_floor_violations(
            (FIXTURES / "uv-lock-stale.txt").read_text(), FLOORS
        )
        self.assertEqual(
            problems,
            [
                "certifi 2026.7.22 is locked; 2026.10.19 or later is required",
                "pip 26.2.1 is locked; 26.2.2 or later is required",
            ],
        )

    def test_current_lock_passes(self):
        self.assertEqual(
            flt.uv_lock_floor_violations(
                (FIXTURES / "uv-lock-current.txt").read_text(), FLOORS
            ),
            [],
        )

    def test_absent_packages_are_ignored(self):
        self.assertEqual(
            flt.uv_lock_floor_violations(
                (FIXTURES / "uv-lock-without-certifi.txt").read_text(), FLOORS
            ),
            [],
        )

    def test_invalid_lock_is_an_error_not_a_pass(self):
        with self.assertRaises(AnsibleFilterError):
            flt.uv_lock_floor_violations("not = [toml", FLOORS)
        with self.assertRaises(AnsibleFilterError):
            flt.uv_lock_floor_violations("version = 1\n", FLOORS)

    def test_constraints_text(self):
        self.assertEqual(
            flt.python_security_constraints(FLOORS),
            "certifi>=2026.10.19\npip>=26.2.2\n",
        )


class ReportTests(unittest.TestCase):
    def test_absent_packages_pass(self):
        self.assertEqual(
            violations(
                env_report(certifi={"installed": False}, pip={"installed": False})
            ),
            [],
        )

    def test_stale_pip_on_supported_python(self):
        self.assertEqual(
            violations(
                env_report(certifi={"version": "2026.10.19"}, pip={"version": "23.2.1"})
            ),
            ["pip 23.2.1 is installed; 26.2.2 or later is required"],
        )

    def test_stale_pip_on_python_outside_requires_python_is_reported_not_bypassed(self):
        report = env_report(
            certifi={"version": "2026.10.19"}, pip={"version": "23.2.1"}
        )
        report["python_version"] = "3.9.2"
        (problem,) = violations(report)
        self.assertIn("pip 26.2.2 requires Python >=3.10", problem)
        self.assertIn("runs 3.9.2; it cannot be updated in place", problem)

    def test_deferred_packages_are_skipped_only_when_named(self):
        report = env_report(
            certifi={"version": "2026.10.19"},
            pip={"version": "23.2.1", "bundle_fingerprints": [G3]},
        )
        self.assertEqual(
            flt.python_security_report_violations(
                report, FLOORS, ROOTS, REQUIRES, ["pip"]
            ),
            [],
        )
        self.assertEqual(
            len(
                flt.python_security_report_violations(
                    report, FLOORS, ROOTS, REQUIRES, []
                )
            ),
            2,
        )

    def test_deferral_needs_a_floor_release_that_supports_the_python(self):
        report = env_report(
            certifi={"version": "2026.10.19"}, pip={"version": "23.2.1"}
        )
        report["python_version"] = "3.9.2"
        (problem,) = flt.python_security_report_violations(
            report, FLOORS, ROOTS, REQUIRES, ["pip"]
        )
        self.assertIn("pip cannot be raised by the following install", problem)
        self.assertIn("pip 26.2.2 requires Python >=3.10", problem)
        report["python_version"] = "3.10.0"
        self.assertEqual(
            flt.python_security_report_violations(
                report, FLOORS, ROOTS, REQUIRES, ["pip"]
            ),
            [],
        )

    def test_unknown_version_fails(self):
        self.assertEqual(
            violations(env_report(certifi={"version": None}, pip={"installed": False})),
            ["certifi: installed version could not be read from its metadata"],
        )

    def test_distrusted_root_matched_by_fingerprint_only(self):
        bad = env_report(
            certifi={"version": "2026.10.19", "bundle_fingerprints": [G3.lower()]},
            pip={"installed": False},
        )
        self.assertEqual(
            violations(bad),
            [
                "certifi: bundle /env/cacert.pem contains distrusted root emSign ECC Root CA - G3"
            ],
        )
        # A custom CA that merely shares the name but not the key is not rejected.
        same_name = env_report(
            certifi={"version": "2026.10.19", "bundle_fingerprints": ["00" * 32]},
            pip={"installed": False},
        )
        self.assertEqual(violations(same_name), [])

    def test_distro_unbundled_certifi_needs_owner_and_system_store(self):
        distro = {
            "version": "2024.2.2",
            "in_environment": False,
            "module_file": "/usr/lib/python3/dist-packages/certifi/__init__.py",
            "distro_owner": "python3-certifi",
            "bundle": "/etc/ssl/certs/ca-certificates.crt",
        }
        self.assertEqual(
            violations(env_report(certifi=distro, pip={"installed": False})), []
        )
        for change in (
            {"distro_owner": None},
            {"distro_owner": "python3-other"},
            {"bundle": "/opt/custom/ca.pem"},
        ):
            (problem,) = violations(
                env_report(certifi={**distro, **change}, pip={"installed": False})
            )
            self.assertIn(
                "only a distribution package using the system store is accepted",
                problem,
            )

    def test_unreadable_bundle_and_inspection_errors_fail(self):
        self.assertTrue(
            violations(
                env_report(
                    certifi={"version": "2026.10.19", "bundle_error": "OSError: x"},
                    pip={"installed": False},
                )
            )
        )
        self.assertTrue(
            violations(
                env_report(
                    certifi={"error": "ImportError: x"}, pip={"installed": False}
                )
            )
        )


class ManagedBaseReportTests(unittest.TestCase):
    def report(self):
        info = {
            "installed": True,
            "in_environment": True,
            "version": "26.2.2",
            "module_file": "/managed/lib/python3.15/site-packages/pip/__init__.py",
            "bundle_module_file": "/managed/lib/python3.15/site-packages/pip/_vendor/certifi/__init__.py",
            "bundle": "/managed/lib/python3.15/site-packages/pip/_vendor/certifi/cacert.pem",
            "bundle_version": "2026.10.19",
            "module_origins": {"pip": "/managed/lib/pip/__init__.py"},
            "bundle_fingerprints": [],
        }
        return {
            "python_version": "3.15.1",
            "prefix": "/managed",
            "base_prefix": "/managed",
            "expected_base_prefix": "/managed",
            "executable": "/managed/bin/python3.15",
            "packages": {"pip": info, "certifi": {"installed": False}},
        }

    def check(self, report, deferred=None):
        return flt.python_security_report_violations(
            report, FLOORS, ROOTS, REQUIRES, deferred, {"python_version": "3.15.1"}
        )

    def test_verified_base_passes(self):
        self.assertEqual(self.check(self.report()), [])

    def test_managed_configuration_needs_both_floors_and_exact_patch(self):
        for floors, config in (
            ({"pip": "26.2.2"}, {"python_version": "3.15.1"}),
            (FLOORS, {"python_version": "3.15"}),
            (FLOORS, {"wrong": "3.15.1"}),
            (FLOORS, True),
        ):
            with self.subTest(floors=floors, config=config):
                with self.assertRaises(AnsibleFilterError):
                    flt.python_security_report_violations(
                        self.report(), floors, ROOTS, REQUIRES, [], config
                    )

    def test_wrong_base_venv_executable_and_patch_fail(self):
        for field, value in (
            ("prefix", "/venv"),
            ("base_prefix", "/other"),
            ("executable", "/managed-other/bin/python"),
            ("python_version", "3.15.0"),
        ):
            with self.subTest(field=field):
                report = self.report()
                report[field] = value
                self.assertTrue(self.check(report))

    def test_no_missing_pip_distro_exemption_or_deferral(self):
        report = self.report()
        report["packages"]["pip"] = {"installed": False}
        self.assertTrue(self.check(report))
        report = self.report()
        report["packages"]["pip"].update(
            in_environment=False,
            distro_owner="python3-pip",
            bundle="/etc/ssl/certs/ca-certificates.crt",
        )
        self.assertTrue(self.check(report))
        self.assertTrue(self.check(self.report(), ["pip"]))

    def test_external_origins_stale_vendor_and_distrusted_roots_fail(self):
        for field, value in (
            ("module_file", "/elsewhere/pip/__init__.py"),
            ("bundle_module_file", "/managed-other/certifi/__init__.py"),
            ("bundle", "/elsewhere/ca.pem"),
            ("version", "26.2.1"),
            ("bundle_version", "2026.7.22"),
            ("bundle_version", None),
            ("module_origins", {"pip._vendor.certifi.core": "/outside/core.py"}),
            ("module_origins", {}),
            ("bundle_fingerprints", [G3]),
        ):
            with self.subTest(field=field, value=value):
                report = self.report()
                report["packages"]["pip"][field] = value
                self.assertTrue(self.check(report))


@unittest.skipUnless(UV, "uv is required for the lifecycle tests")
class LifecycleTests(unittest.TestCase):
    """Real environments, real resolvers, the role's own inspector."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="ops-library-python-security-"))
        cls.constraints = cls.tmp / "constraints.txt"
        cls.constraints.write_text(flt.python_security_constraints(FLOORS))
        capped = cls.tmp / "capped"
        (capped / "capped").mkdir(parents=True)
        (capped / "capped/__init__.py").write_text("")
        (capped / "pyproject.toml").write_text(
            '[project]\nname = "capped"\nversion = "0.1"\ndependencies = ["certifi<2026.8"]\n'
            '[build-system]\nrequires = ["setuptools>=61"]\nbuild-backend = "setuptools.build_meta"\n'
        )
        cls.capped = capped

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def venv(self, name, *packages, seed=False):
        path = self.tmp / name
        subprocess.run(
            [
                UV,
                "venv",
                "-q",
                "--python",
                "3.12",
                *(["--seed"] if seed else []),
                str(path),
            ],
            check=True,
        )
        if packages:
            self.uv_pip("install", "-q", *packages, venv=path)
        return path

    def uv_pip(self, *args, venv, check=True):
        return subprocess.run(
            [UV, "pip", *args[:1], "--python", str(venv / "bin/python"), *args[1:]],
            check=check,
            capture_output=True,
            text=True,
            cwd=self.tmp,
        )

    def inspect(self, venv):
        out = subprocess.run(
            [str(venv / "bin/python"), "-I", "-c", INSPECTOR.read_text()],
            check=True,
            capture_output=True,
            text=True,
            cwd=self.tmp,
        )
        return json.loads(out.stdout)

    def installed(self, venv, name):
        listing = json.loads(self.uv_pip("list", "--format", "json", venv=venv).stdout)
        return {p["name"].lower(): p["version"] for p in listing}.get(name)

    def test_inspector_flags_old_certifi_and_its_distrusted_root(self):
        venv = self.venv("old", "certifi==2026.7.22")
        report = self.inspect(venv)
        self.assertTrue(report["packages"]["certifi"]["in_environment"])
        self.assertFalse(report["packages"]["pip"]["installed"])
        self.assertEqual(
            violations(report),
            [
                "certifi 2026.7.22 is installed; 2026.10.19 or later is required",
                f"certifi: bundle {report['packages']['certifi']['bundle']} contains distrusted root emSign ECC Root CA - G3",
            ],
        )

    def test_inspector_reads_versions_without_importlib_metadata(self):
        # Python < 3.8 has no importlib.metadata; the inspector must not need it.
        venv = self.venv("nometadata", "certifi==2026.10.19")
        blocked = (
            "import sys; sys.modules['importlib.metadata'] = None\n"
            + INSPECTOR.read_text()
        )
        out = subprocess.run(
            [str(venv / "bin/python"), "-I", "-c", blocked],
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads(out.stdout)
        self.assertEqual(report["packages"]["certifi"]["version"], "2026.10.19")
        self.assertEqual(violations(report), [])

    def bundle(self, venv):
        (path,) = (venv / "lib").glob("python3.12/site-packages/certifi/cacert.pem")
        return path

    def test_trusted_certificate_block_is_fingerprinted(self):
        # OpenSSL loads TRUSTED CERTIFICATE blocks as trust anchors too.
        venv = self.venv("trusted", "certifi==2026.10.19")
        with self.bundle(venv).open("a") as handle:
            handle.write((FIXTURES / "emsign-ecc-g3-trusted.txt").read_text())
        (problem,) = violations(self.inspect(venv))
        self.assertTrue(
            problem.endswith("contains distrusted root emSign ECC Root CA - G3"),
            problem,
        )

    def test_noncanonical_encoding_of_a_distrusted_root_is_still_matched(self):
        # Fingerprints come from the certificates OpenSSL loads, not from the file bytes.
        venv = self.venv("noncanonical", "certifi==2026.10.19")
        with self.bundle(venv).open("a") as handle:
            handle.write(
                (FIXTURES / "emsign-ecc-g3-trusted-noncanonical.txt").read_text()
            )
        (problem,) = violations(self.inspect(venv))
        self.assertTrue(
            problem.endswith("contains distrusted root emSign ECC Root CA - G3"),
            problem,
        )

    def test_bundle_openssl_cannot_load_fails_closed(self):
        venv = self.venv("garbage", "certifi==2026.10.19")
        self.bundle(venv).write_text("not a certificate\n")
        (problem,) = violations(self.inspect(venv))
        self.assertIn("could not be read: SSLError", problem)

    def test_ambiguous_installed_version_fails_closed(self):
        venv = self.venv("ambiguous", "certifi==2026.10.19")
        (info,) = (venv / "lib").glob("python3.12/site-packages/certifi-*.dist-info")
        shutil.copytree(info, info.with_name("certifi-2026.7.22.dist-info"))
        self.assertEqual(
            violations(self.inspect(venv)),
            ["certifi: installed version could not be read from its metadata"],
        )

    def test_constrained_install_upgrades_installed_certifi_without_adding_pip(self):
        venv = self.venv("upgrade", "certifi==2026.7.22")
        self.uv_pip(
            "install",
            "-q",
            "--constraint",
            str(self.constraints),
            "requests",
            venv=venv,
        )
        # The constraint is a floor: the resolver may pick any newer release.
        self.assertGreaterEqual(
            version_tuple(self.installed(venv, "certifi")), version_tuple(CERTIFI_FLOOR)
        )
        self.assertIsNone(self.installed(venv, "pip"))
        self.assertEqual(violations(self.inspect(venv)), [])

    def test_constrained_install_against_a_cap_fails_before_changing_anything(self):
        venv = self.venv("capped-env", "certifi==2026.7.22")
        result = self.uv_pip(
            "install",
            "--constraint",
            str(self.constraints),
            str(self.capped),
            venv=venv,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No solution found", result.stderr)
        self.assertEqual(self.installed(venv, "certifi"), "2026.7.22")
        self.assertIsNone(self.installed(venv, "capped"))

    def test_force_reinstall_with_constraints_keeps_the_floor(self):
        venv = self.venv("reinstall", "certifi==2026.10.19", "idna")
        self.uv_pip(
            "install",
            "-q",
            "--constraint",
            str(self.constraints),
            "--force-reinstall",
            "idna",
            venv=venv,
        )
        self.assertEqual(self.installed(venv, "certifi"), "2026.10.19")

    def test_pip_requirements_install_with_constraint_upgrades_certifi_but_not_pip(
        self,
    ):
        # Takahe-style: a pip-managed venv with an old pip and an old certifi.
        venv = self.venv("pipvenv", seed=True)
        pip = [
            str(venv / "bin/python"),
            "-m",
            "pip",
            "--disable-pip-version-check",
            "-q",
        ]
        subprocess.run(
            [*pip, "install", "pip==23.2.1", "certifi==2023.11.17"], check=True
        )
        requirements = self.tmp / "requirements.txt"
        requirements.write_text("requests\n")
        subprocess.run([*pip, "install", "-r", str(requirements)], check=True)
        self.assertEqual(
            self.inspect(venv)["packages"]["certifi"]["version"], "2023.11.17"
        )
        subprocess.run(
            [*pip, "install", "-r", str(requirements), "-c", str(self.constraints)],
            check=True,
        )
        report = self.inspect(venv)
        self.assertGreaterEqual(
            version_tuple(report["packages"]["certifi"]["version"]),
            version_tuple(CERTIFI_FLOOR),
        )
        # pip is only upgraded when it is requested; the verify step catches it,
        # including the distrusted roots in pip 23.2.1's vendored bundle.
        problems = violations(report)
        self.assertEqual(
            problems[0], "pip 23.2.1 is installed; 26.2.2 or later is required"
        )
        self.assertEqual(
            sorted(p.rsplit("distrusted root ", 1)[1] for p in problems[1:]),
            ["AAA Certificate Services", "emSign ECC Root CA - G3"],
        )
        subprocess.run(
            [*pip, "install", "--upgrade", "pip", "-c", str(self.constraints)],
            check=True,
        )
        self.assertEqual(violations(self.inspect(venv)), [])


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook is required")
class CollectionLoaderTests(unittest.TestCase):
    """The role's tasks and the filters through the real collection loader (FQCN)."""

    def test_playbook(self):
        collections = subprocess.run(
            [str(ROOT / "scripts/checkout-collections-path.sh")],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        env = {**os.environ, "ANSIBLE_COLLECTIONS_PATH": collections}
        result = subprocess.run(
            [
                "ansible-playbook",
                "-i",
                "localhost,",
                "-c",
                "local",
                str(ROOT / "tests/test_python_security_floor.yml"),
            ],
            env=env,
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        self.assertEqual(
            result.returncode, 0, result.stdout[-4000:] + result.stderr[-2000:]
        )


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook is required")
class ManagedBaseRoleTests(unittest.TestCase):
    """Fast actual-role input/filter wiring; Linux covers the real interpreter."""

    def run_case(self, prefix=None, patch="3.15.1", deferred=None):
        with tempfile.TemporaryDirectory(prefix="managed-base-role-") as td:
            root = Path(td)
            expected = root / "runtime"
            python = expected / "bin/python"
            python.parent.mkdir(parents=True)
            marker = root / "inspected"
            report = ManagedBaseReportTests().report()
            report = json.loads(json.dumps(report).replace("/managed", str(expected)))
            python.write_text(
                "#!"
                + sys.executable
                + "\nfrom pathlib import Path\n"
                + f"Path({str(marker)!r}).touch()\nprint({json.dumps(report)!r})\n"
            )
            python.chmod(0o700)
            local = root / "collections/ansible_collections/local"
            local.mkdir(parents=True)
            (local / "ops_library").symlink_to(ROOT, target_is_directory=True)
            play = [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "tasks": [
                        {
                            "ansible.builtin.include_role": {
                                "name": "local.ops_library.python_security_floor",
                                "tasks_from": "verify.yml",
                            },
                            "vars": {
                                "python_security_floor_python": str(python),
                                "python_security_floor_user": getpass.getuser(),
                                "python_security_floor_label": "fixture managed base",
                                "python_security_floor_become": False,
                                "python_security_floor_managed_base_prefix": str(
                                    expected
                                )
                                if prefix is None
                                else prefix,
                                "python_security_floor_expected_python_version": patch,
                                "python_security_floor_deferred": deferred or [],
                            },
                        }
                    ],
                }
            ]
            path = root / "play.yml"
            path.write_text(yaml.safe_dump(play))
            env = {k: v for k, v in os.environ.items() if not k.startswith("ANSIBLE_")}
            env["ANSIBLE_COLLECTIONS_PATH"] = str(root / "collections")
            result = subprocess.run(
                ["ansible-playbook", "-i", "localhost,", str(path)],
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            return result, marker.exists()

    def test_managed_report_passes_through_actual_role_filter(self):
        result, inspected = self.run_case()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(inspected)

    def test_bad_managed_inputs_refused_before_inspection(self):
        for kwargs in (
            {"prefix": "relative/runtime"},
            {"patch": "3.15"},
            {"deferred": ["pip"]},
        ):
            with self.subTest(kwargs=kwargs):
                result, inspected = self.run_case(**kwargs)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertFalse(inspected)
                self.assertIn(
                    "Require explicit managed base qualification inputs", result.stdout
                )

    def test_managed_filter_argument_rejects_wrong_exact_patch(self):
        result, inspected = self.run_case(patch="3.15.0")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertTrue(inspected)
        self.assertIn("does not match the exact expected version", result.stdout)


if __name__ == "__main__":
    unittest.main()
