import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from research_code_quality.scanner import (
    DEFAULT_ROOTS,
    discover_python_files,
    parse_args,
    ratchet_violations,
    scan_repository,
    write_baseline,
)


class ScannerScopeTests(unittest.TestCase):
    def test_explicit_scopes_accept_multiple_repository_directories(self):
        args = parse_args(["--scope", "research_code_quality", "--scope", "tests"])

        self.assertEqual(args.scope, ["research_code_quality", "tests"])

    def test_explicit_package_scope_discovers_this_repository_code(self):
        repo_root = Path(__file__).resolve().parents[1]

        files = discover_python_files(
            repo_root,
            roots=("research_code_quality",),
            use_git=True,
        )

        self.assertIn(repo_root / "research_code_quality/scanner.py", files)

    def test_default_scopes_remain_compatible_with_downstream_repositories(self):
        self.assertEqual(DEFAULT_ROOTS, ("src", "scripts", "tests"))

    def test_ratchet_detects_only_increases_in_shared_metrics(self):
        repo_root = Path(__file__).resolve().parents[1]
        result = scan_repository(repo_root, roots=("research_code_quality",), use_git=True)

        self.assertEqual(
            ratchet_violations(result, {"metrics": {"python_files": result.python_files}}), []
        )
        self.assertEqual(
            ratchet_violations(result, {"metrics": {"python_files": result.python_files - 1}}),
            [f"python_files: {result.python_files} > baseline {result.python_files - 1}"],
        )

    def test_baseline_writer_emits_compact_json(self):
        repo_root = Path(__file__).resolve().parents[1]
        result = scan_repository(repo_root, roots=("research_code_quality",), use_git=True)

        with TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.json"
            write_baseline(path, result)
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["metrics"]["python_files"], result.python_files)
        self.assertNotIn("functions", payload)


if __name__ == "__main__":
    unittest.main()
