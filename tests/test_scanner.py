import unittest
from pathlib import Path

from research_dev_metrics.scanner import (
    DEFAULT_ROOTS,
    discover_python_files,
    parse_args,
)


class ScannerScopeTests(unittest.TestCase):
    def test_explicit_scopes_accept_multiple_repository_directories(self):
        args = parse_args(["--scope", "research_dev_metrics", "--scope", "tests"])

        self.assertEqual(args.scope, ["research_dev_metrics", "tests"])

    def test_explicit_package_scope_discovers_this_repository_code(self):
        repo_root = Path(__file__).resolve().parents[1]

        files = discover_python_files(
            repo_root,
            roots=("research_dev_metrics",),
            use_git=True,
        )

        self.assertIn(repo_root / "research_dev_metrics/scanner.py", files)

    def test_default_scopes_remain_compatible_with_downstream_repositories(self):
        self.assertEqual(DEFAULT_ROOTS, ("src", "scripts", "tests"))


if __name__ == "__main__":
    unittest.main()
