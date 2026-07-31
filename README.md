# research-dev-metrics

research-workspace 子模块共享的静态可维护性指标扫描算法。

## 背景

`alpha-research`、`portfolio-backtester`、`strategy-pipeline`、`quant-execution-engine`
四个子模块原本各自持有一份几乎相同的 `scripts/dev/maintainability_metrics.py`
（发现 Python 文件、用 `ast` 统计函数长度、读取 `pyproject.toml` 的
`per-file-ignores` 计数 C901 豁免等）。本仓抽取其中**稳定且跨仓一致**的部分，
避免同一算法在多处漂移。

## 设计边界

本仓只拥有跨仓一致的部分：

- 发现仓库内的 Python 文件（`discover_python_files`）
- 用 `ast` 统计每个函数的起止行与长度（`_function_metrics_for_file`）
- 读取 `pyproject.toml` 统计 C901 按文件忽略数量（`_c901_file_ignore_count`）
- 汇总为 `ScanResult`（`scan_repository`）

各子模块的专属部分**仍保留在本地**：

- `Metrics` dataclass（字段因仓而异，例如 strategy-pipeline 多 `src/script/test_files_over_750`）
- ratchet 预算（`DEFAULT_RATCHET_BUDGETS`，是治理值，必须本地冻结）
- `command_run_functions_over_150` 等子仓专属指标的路径前缀
- `to_payload` 里的 `thresholds` 细节

这样既能消除真重复，又不会用 `__getattr__` 之类的魔法去强行统一差异字段。

## 消费方式

子模块在 `pyproject.toml` 中把本仓作为 git 依赖加入 dev 组：

```toml
[project.optional-dependencies]
dev = [
    "research-dev-metrics = { git = \"https://github.com/runchengxie/research-dev-metrics.git\" }",
]
```

本地包装器只需：

```python
from research_dev_metrics.scanner import scan_repository

result = scan_repository(repo_root, roots, limit)
# 再补上本仓专属指标，组装出与原来一致的 Metrics 对象
```

## 校验

```bash
uv run --group dev ruff check .
uv run --group dev python -m research_dev_metrics.scanner --json
```
