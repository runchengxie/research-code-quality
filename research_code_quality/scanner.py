"""Shared maintainability-metric scanning for research-workspace submodules.

This package extracts the common static-analysis algorithm that used to be
copied across ``alpha-research``, ``portfolio-backtester``, ``strategy-pipeline``
and ``quant-execution-engine`` (each had its own ``scripts/dev/maintainability_metrics.py``).

Each submodule keeps its own ``Metrics`` dataclass, ratchet budget and any
submodule-specific indicators (for example ``command_run_functions_over_150``).
This module only owns the stable part: discovering Python files, counting lines
and long lines, mapping function lengths via ``ast``, and counting C901
per-file ignores declared in ``pyproject.toml``.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

PYPROJECT_PATH = Path("pyproject.toml")
DEFAULT_ROOTS = ("src", "scripts", "tests")
RATCHET_METRICS = (
    "python_files",
    "python_lines",
    "long_lines_over_100",
    "functions_over_100",
    "functions_over_250",
    "functions_over_500",
    "c901_file_ignores",
    "files_over_800",
    "files_over_1200",
    "tests_over_1000",
)


@dataclass(frozen=True)
class FileMetric:
    path: str
    lines: int
    long_lines_over_100: int


@dataclass(frozen=True)
class FunctionMetric:
    path: str
    name: str
    start_line: int
    end_line: int
    lines: int


@dataclass
class ScanResult:
    """Base metrics computed identically across all submodules."""

    roots: list[str]
    python_files: int
    python_lines: int
    long_lines_over_100: int
    functions_over_100: int
    functions_over_250: int
    functions_over_500: int
    c901_file_ignores: int
    files_over_800: int
    files_over_1200: int
    tests_over_1000: int
    largest_files: list[FileMetric]
    largest_functions: list[FunctionMetric]
    functions: list[FunctionMetric]
    files: list[FileMetric]

    def to_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["thresholds"] = {
            "long_line_columns": 100,
            "large_function_lines": 100,
            "very_large_function_lines": 250,
            "huge_function_lines": 500,
            "large_file_lines": 800,
            "very_large_file_lines": 1200,
            "large_test_file_lines": 1000,
        }
        return payload


def ratchet_metrics(result: ScanResult) -> dict[str, int]:
    """Return the stable scalar metrics suitable for a committed baseline."""
    return {name: getattr(result, name) for name in RATCHET_METRICS}


def ratchet_violations(result: ScanResult, baseline: dict[str, object]) -> list[str]:
    """Return human-readable regressions against a baseline payload."""
    metrics = baseline.get("metrics", baseline)
    if not isinstance(metrics, dict):
        raise ValueError("baseline must contain a 'metrics' object")
    violations: list[str] = []
    current = ratchet_metrics(result)
    for name, value in current.items():
        previous = metrics.get(name)
        if previous is None:
            continue
        if not isinstance(previous, int):
            raise ValueError(f"baseline metric {name!r} must be an integer")
        if value > previous:
            violations.append(f"{name}: {value} > baseline {previous}")
    return violations


def load_baseline(path: Path) -> dict[str, object]:
    """Load a JSON baseline file."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("baseline must be a JSON object")
    return payload


def write_baseline(path: Path, result: ScanResult) -> None:
    """Write a compact, reviewable baseline containing only ratchet metrics."""
    payload = {
        "schema_version": 1,
        "roots": result.roots,
        "metrics": ratchet_metrics(result),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def find_repo_root(start: Path) -> Path:
    """Locate the repository root from ``start``.

    Uses ``git rev-parse --show-toplevel`` when available, then falls back to
    walking upward for a ``pyproject.toml``, and finally to the conventional
    ``parents[2]`` of a ``scripts/dev`` file. This replaces the submodule-local
    ``_run_git_ls_files`` / ``_find_repo_root`` helpers with one shared rule.
    """
    start = start.resolve()
    result = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.decode("utf-8").strip())
    candidate = start
    for _ in range(6):
        if (candidate / "pyproject.toml").exists():
            return candidate
        if candidate.parent == candidate:
            break
        candidate = candidate.parent
    return start.parents[1] if len(start.parents) > 1 else start


def _git_tracked_python(repo_root: Path) -> set[str] | None:
    if not (repo_root / ".git").exists():
        return None
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return {path for path in result.stdout.decode("utf-8").split("\0") if path}


def _is_included_python_path(path: Path, roots: Sequence[str]) -> bool:
    return (
        path.suffix == ".py"
        and "__pycache__" not in path.parts
        and bool(path.parts)
        and path.parts[0] in roots
    )


def discover_python_files(
    repo_root: Path,
    roots: Sequence[str] = DEFAULT_ROOTS,
    use_git: bool = True,
) -> list[Path]:
    """Return sorted Python files under ``roots``.

    When ``use_git`` is true and ``repo_root`` is a git checkout, files are taken
    from ``git ls-files`` (respects ``.gitignore`` and includes untracked files).
    Set ``use_git=False`` for repos that intentionally scan the working tree with
    plain ``rglob`` (for example ``quant-execution-engine``).
    """
    if use_git:
        tracked = _git_tracked_python(repo_root)
        if tracked is not None:
            return sorted(
                repo_root / path
                for path in tracked
                if _is_included_python_path(Path(path), roots) and (repo_root / path).is_file()
            )
    files: list[Path] = []
    for root_name in roots:
        root = repo_root / root_name
        if root.exists():
            files.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    return sorted(files)


def _relative_path(repo_root: Path, path: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def _function_metrics_for_file(repo_root: Path, path: Path, text: str) -> list[FunctionMetric]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    metrics: list[FunctionMetric] = []
    relative = _relative_path(repo_root, path)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end_line = getattr(node, "end_lineno", None)
        if end_line is None:
            continue
        metrics.append(
            FunctionMetric(
                path=relative,
                name=node.name,
                start_line=node.lineno,
                end_line=end_line,
                lines=end_line - node.lineno + 1,
            )
        )
    return metrics


def _c901_file_ignore_count(repo_root: Path) -> int:
    pyproject_path = repo_root / PYPROJECT_PATH
    if not pyproject_path.exists():
        return 0
    config = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    per_file = config.get("tool", {}).get("ruff", {}).get("lint", {}).get("per-file-ignores", {})
    return sum(1 for values in per_file.values() if "C901" in values)


def scan_repository(
    repo_root: Path,
    roots: Sequence[str] = DEFAULT_ROOTS,
    limit: int = 10,
    use_git: bool = True,
) -> ScanResult:
    """Run the shared static scan and return base metrics plus raw lists.

    Submodule wrappers should add their own indicators (for example
    ``command_run_functions_over_150``) to the returned ``ScanResult`` before
    assembling their submodule-specific ``Metrics`` dataclass.
    """
    files = discover_python_files(repo_root, roots, use_git=use_git)
    file_metrics: list[FileMetric] = []
    function_metrics: list[FunctionMetric] = []
    total_lines = 0
    total_long_lines = 0

    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()
        long_lines = sum(1 for line in lines if len(line) > 100)
        total_lines += len(lines)
        total_long_lines += long_lines
        file_metrics.append(
            FileMetric(
                path=_relative_path(repo_root, path),
                lines=len(lines),
                long_lines_over_100=long_lines,
            )
        )
        function_metrics.extend(_function_metrics_for_file(repo_root, path, text))

    return ScanResult(
        roots=list(roots),
        python_files=len(files),
        python_lines=total_lines,
        long_lines_over_100=total_long_lines,
        functions_over_100=sum(1 for item in function_metrics if item.lines > 100),
        functions_over_250=sum(1 for item in function_metrics if item.lines > 250),
        functions_over_500=sum(1 for item in function_metrics if item.lines > 500),
        c901_file_ignores=_c901_file_ignore_count(repo_root),
        files_over_800=sum(1 for item in file_metrics if item.lines > 800),
        files_over_1200=sum(1 for item in file_metrics if item.lines > 1200),
        tests_over_1000=sum(
            1 for item in file_metrics if item.lines > 1000 and item.path.startswith("tests/")
        ),
        largest_files=sorted(file_metrics, key=lambda item: item.lines, reverse=True)[:limit],
        largest_functions=sorted(
            function_metrics, key=lambda item: item.lines, reverse=True
        )[:limit],
        functions=function_metrics,
        files=file_metrics,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect static maintainability metrics for src, scripts, and tests.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="Print a markdown table suitable for maintenance docs.",
    )
    parser.add_argument(
        "--limit", type=int, default=10, help="Number of largest files/functions to include."
    )
    parser.add_argument(
        "--root", type=Path, default=None, help="Repository root. Defaults to auto-detection."
    )
    parser.add_argument(
        "--scope",
        action="append",
        help=(
            "Relative repository directory to include. May be repeated. "
            "Defaults to src, scripts, tests."
        ),
    )
    parser.add_argument(
        "--no-git",
        action="store_true",
        help="Scan the working tree with rglob instead of git ls-files.",
    )
    parser.add_argument(
        "--ratchet", action="store_true", help="Fail if maintainability debt exceeds budget."
    )
    parser.add_argument(
        "--baseline", type=Path, help="JSON baseline used by --ratchet."
    )
    parser.add_argument(
        "--write-baseline", type=Path, help="Write the current scalar metrics as a JSON baseline."
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Generic CLI entrypoint.

    Submodule wrappers may call this directly when they only need the base scan
    and their own formatting/budget logic, or they may reuse ``scan_repository``
    and assemble a richer ``Metrics`` object themselves.
    """
    args = parse_args(argv)
    roots = tuple(args.scope or DEFAULT_ROOTS)
    repo_root = args.root or find_repo_root(Path(__file__))
    result = scan_repository(
        repo_root.resolve(), roots, max(args.limit, 0), use_git=not args.no_git
    )
    if args.write_baseline:
        write_baseline(args.write_baseline, result)
    if args.ratchet:
        if args.baseline is None:
            print("--ratchet requires --baseline", file=sys.stderr)
            return 2
        try:
            violations = ratchet_violations(result, load_baseline(args.baseline))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            print(f"Unable to read baseline: {error}", file=sys.stderr)
            return 2
        if violations:
            print("Maintainability ratchet failed:", file=sys.stderr)
            for violation in violations:
                print(f"- {violation}", file=sys.stderr)
            return 1
    if args.json:
        json.dump(result.to_payload(), sys.stdout, indent=2, ensure_ascii=False)
        print()
    elif args.markdown:
        print(
            "\n".join(
                [
                    "| Metric | Value |",
                    "| --- | ---: |",
                    f"| Python files | {result.python_files} |",
                    f"| Python lines | {result.python_lines} |",
                    f"| Lines over 100 chars | {result.long_lines_over_100} |",
                    f"| Functions over 100 lines | {result.functions_over_100} |",
                    f"| Functions over 250 lines | {result.functions_over_250} |",
                    f"| Functions over 500 lines | {result.functions_over_500} |",
                    f"| C901 file ignores | {result.c901_file_ignores} |",
                    f"| Files over 800 lines | {result.files_over_800} |",
                    f"| Files over 1200 lines | {result.files_over_1200} |",
                    f"| Test files over 1000 lines | {result.tests_over_1000} |",
                ]
            )
        )
    else:
        print("Maintainability metrics:")
        for name in (
            "python_files",
            "python_lines",
            "long_lines_over_100",
            "functions_over_100",
            "functions_over_250",
            "functions_over_500",
            "c901_file_ignores",
            "files_over_800",
            "files_over_1200",
            "tests_over_1000",
        ):
            print(f"- {name}: {getattr(result, name)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
