import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.core.date_formats import parse_collection_date, canonical_jalali


class CollectionDateFormatTests(unittest.TestCase):
    def test_jalali_input(self):
        self.assertEqual(parse_collection_date("1405.08.01", "jalali").isoformat(), "2026-10-23")
        self.assertEqual(canonical_jalali("1405.08.01", "jalali"), "1405.08.01")

    def test_gregorian_iso_input_is_normalized_for_existing_collectors(self):
        self.assertEqual(parse_collection_date("2026-10-23", "gregorian").isoformat(), "2026-10-23")
        self.assertEqual(canonical_jalali("2026-10-23", "gregorian"), "1405.08.01")

    def test_auto_detect_supports_jalali_and_gregorian(self):
        self.assertEqual(parse_collection_date("۱۴۰۵/۰۸/۰۱", "auto").isoformat(), "2026-10-23")
        self.assertEqual(parse_collection_date("2026/10/23", "auto").isoformat(), "2026-10-23")

    def test_custom_format(self):
        self.assertEqual(parse_collection_date("23/10/2026", "custom", "%d/%m/%Y").isoformat(), "2026-10-23")

    def test_custom_format_requires_year_month_day(self):
        with self.assertRaisesRegex(ValueError, "include %Y, %m and %d"):
            parse_collection_date("23/10/2026", "custom", "%d/%m/%y")

    def test_auto_rejects_ambiguous_numeric_dates(self):
        with self.assertRaisesRegex(ValueError, "Could not safely detect"):
            parse_collection_date("03/04/2026", "auto")

    def test_runner_imports_app_package_when_launched_outside_project_cwd(self):
        project_root = Path(__file__).resolve().parents[1]
        runner = project_root / "app" / "automation" / "collector_runner.py"
        code = (
            "import importlib.util; "
            f"spec=importlib.util.spec_from_file_location('standalone_collector_runner', {str(runner)!r}); "
            "module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); "
            "print(module.validate_date('1405.08.01')[0])"
        )
        with tempfile.TemporaryDirectory(prefix="structura-collector-cwd-") as tmp:
            env = {"PATH": os.environ.get("PATH", ""), "PYTHONNOUSERSITE": "1"}
            result = subprocess.run(
                [sys.executable, "-c", code], cwd=tmp, env=env,
                text=True, capture_output=True, timeout=15,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1405.08.01", result.stdout)

    def test_standalone_runner_completes_outside_project_cwd(self):
        project_root = Path(__file__).resolve().parents[1]
        runner = project_root / "app" / "automation" / "collector_runner.py"
        with tempfile.TemporaryDirectory(prefix="structura-runner-smoke-") as tmp:
            work = Path(tmp)
            (work / "config.json").write_text(
                '{"telegram_channels":[],"rubika_channels":[]}', encoding="utf-8"
            )
            # The test environment may omit optional production dependencies;
            # these stubs are sufficient because no channels are configured.
            (work / "emoji.py").write_text(
                "def emojize(text, language='alias'):\n    return text\n", encoding="utf-8"
            )
            (work / "jdatetime.py").write_text(
                "class date:\n"
                "    @classmethod\n    def today(cls): return cls()\n"
                "    @classmethod\n    def fromgregorian(cls, **kwargs): return cls()\n",
                encoding="utf-8",
            )
            env = {"PATH": os.environ.get("PATH", ""), "PYTHONNOUSERSITE": "1", "PYTHONPATH": str(work)}
            result = subprocess.run(
                [sys.executable, str(runner), "--platform", "rubika", "--start-date", "1405.08.01", "--end-date", "1405.08.01"],
                cwd=work, env=env, text=True, capture_output=True, timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("STRUCTURA_RESULT_JSON=", result.stdout)
        self.assertIn("No Rubika channels configured", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
