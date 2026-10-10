import os
import platform
import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = PROJECT_ROOT / "scripts" / "build_macos.py"
SPEC_FILE = PROJECT_ROOT / "CtripPlanDescriptionFilling.spec"
NATIVE_MACOS_ARCH = "arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "x86_64"


class MacOSPackagingTests(unittest.TestCase):
    def run_build_script(self, *args, env=None):
        command_env = os.environ.copy()
        command_env.pop("MACOS_CODESIGN_IDENTITY", None)
        command_env.pop("MACOS_NOTARY_PROFILE", None)
        if env:
            command_env.update(env)
        return subprocess.run(
            [sys.executable, str(BUILD_SCRIPT), *args],
            cwd=PROJECT_ROOT,
            env=command_env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_release_build_rejects_missing_developer_id_before_build(self):
        result = self.run_build_script("--release", "--dry-run")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MACOS_CODESIGN_IDENTITY", result.stderr)

    def test_release_build_rejects_development_certificate(self):
        result = self.run_build_script(
            "--release",
            "--dry-run",
            env={
                "MACOS_CODESIGN_IDENTITY": "Apple Development: Example (TEAMID)",
                "MACOS_NOTARY_PROFILE": "ctrip-notary",
            },
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Developer ID Application", result.stderr)

    def test_release_dry_run_contains_complete_gatekeeper_flow(self):
        result = self.run_build_script(
            "--release",
            "--dry-run",
            env={
                "MACOS_CODESIGN_IDENTITY": "Developer ID Application: Example (TEAMID)",
                "MACOS_NOTARY_PROFILE": "ctrip-notary",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PyInstaller --clean --noconfirm", result.stdout)
        self.assertIn("codesign --verify --deep --strict", result.stdout)
        self.assertIn("notarytool submit", result.stdout)
        self.assertIn("stapler staple", result.stdout)
        self.assertIn("stapler validate", result.stdout)
        self.assertIn("spctl --assess --type execute", result.stdout)
        self.assertGreaterEqual(result.stdout.count("ditto -c -k"), 2)
        self.assertIn(f"CtripPlanDescriptionFilling-macOS-{NATIVE_MACOS_ARCH}.zip", result.stdout)

    def test_spec_reads_macos_release_settings_from_environment(self):
        spec_text = SPEC_FILE.read_text(encoding="utf-8")

        self.assertIn("MACOS_CODESIGN_IDENTITY", spec_text)
        self.assertIn("MACOS_TARGET_ARCH", spec_text)
        self.assertIn("PYINSTALLER_STRICT_BUNDLE_CODESIGN_ERROR", spec_text)
        self.assertIn('"LSMinimumSystemVersion": "11.0"', spec_text)

    def test_spec_bundles_translation_ops_manual(self):
        spec_text = SPEC_FILE.read_text(encoding="utf-8")
        self.assertIn('PROJECT_ROOT / "docs" / "translation_ops_manual.md"), "docs")', spec_text)

    def test_spec_bundles_product_image_workspace_modules(self):
        spec_text = SPEC_FILE.read_text(encoding="utf-8")
        self.assertIn('"product_image_workspace"', spec_text)
        self.assertIn('"product_image_workspace_state"', spec_text)
        for module_name in (
            "workflow_common",
            "ctrip_transport",
            "docking_config",
            "translation_management",
            "product_edit",
            "product_images",
        ):
            self.assertIn(f'"{module_name}"', spec_text)

    def test_spec_explicitly_registers_workflow_common_as_pymodule(self):
        spec_text = SPEC_FILE.read_text(encoding="utf-8")
        self.assertIn('workflow_common_node = ("workflow_common"', spec_text)
        self.assertIn('raise FileNotFoundError', spec_text)

    def test_analysis_toc_includes_workflow_common_when_built(self):
        analysis_toc = PROJECT_ROOT / "build" / "CtripPlanDescriptionFilling" / "Analysis-00.toc"
        if not analysis_toc.exists():
            self.skipTest("PyInstaller build artifacts missing; run CtripPlanDescriptionFilling.spec first")
        self.assertIn("'workflow_common'", analysis_toc.read_text(encoding="utf-8"))

    def test_notarization_result_must_be_accepted(self):
        from scripts import build_macos

        validator = getattr(build_macos, "require_notary_accepted", None)
        self.assertIsNotNone(validator)
        with self.assertRaisesRegex(build_macos.PackagingError, "Invalid"):
            validator('{"id": "submission-id", "status": "Invalid"}')
        validator('{"id": "submission-id", "status": "Accepted"}')


if __name__ == "__main__":
    unittest.main()
