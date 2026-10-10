import ast
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOMAINS = ("translation_management", "product_edit", "product_images", "docking_config")


class DomainImportBoundaryTests(unittest.TestCase):
    def test_domain_packages_do_not_import_app_or_each_other(self):
        for domain in DOMAINS:
            forbidden = {"app", *(name for name in DOMAINS if name != domain)}
            for path in (ROOT / domain).glob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                imported = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imported.update(alias.name.split(".", 1)[0] for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imported.add(node.module.split(".", 1)[0])
                self.assertFalse(imported & forbidden, f"{path}: {imported & forbidden}")

    def test_import_smoke_has_no_qapplication_or_worker_side_effect(self):
        code = """
import threading
from PyQt6.QtWidgets import QApplication
before = {thread.ident for thread in threading.enumerate()}
import workflow_common, ctrip_transport
import translation_management, product_edit, product_images, docking_config, app
after = {thread.ident for thread in threading.enumerate()}
assert QApplication.instance() is None
assert after == before, (before, after)
"""
        env = dict(os.environ)
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
