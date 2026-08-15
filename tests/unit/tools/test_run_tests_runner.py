"""tests/run_tests.py 轻量 runner 的行为测试。

验证 --category integration 委托 pytest 真正运行集成测试目录，
而不是静默通过（0 个测试、0 失败）。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_RUNNER_PATH = Path(__file__).resolve().parents[2] / "run_tests.py"


@pytest.fixture
def runner_module():
    """动态加载 tests/run_tests.py 作为模块。"""
    spec = importlib.util.spec_from_file_location(
        "rsshub_plugin_run_tests", _RUNNER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _patch_runner(runner_module, monkeypatch, returncode: int) -> dict:
    """把 runner 的 subprocess/sys 替换为可控替身，返回捕获的命令。"""
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = list(args)
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=returncode)

    import subprocess as real_subprocess

    fake_subprocess = SimpleNamespace(
        run=fake_run, CompletedProcess=real_subprocess.CompletedProcess
    )
    fake_sys = SimpleNamespace(executable=sys.executable, version=sys.version)
    monkeypatch.setattr(runner_module, "subprocess", fake_subprocess)
    monkeypatch.setattr(runner_module, "sys", fake_sys)
    return captured


def test_integration_category_delegates_to_pytest(runner_module, monkeypatch):
    """integration 类别必须通过 pytest 运行 tests/integration/ 目录。"""
    captured = _patch_runner(runner_module, monkeypatch, returncode=0)

    exit_code = runner_module.run_tests("integration", verbose=False)

    assert exit_code == 0
    assert captured["args"][:3] == [sys.executable, "-m", "pytest"]
    assert any("integration" in part for part in captured["args"])


def test_integration_category_maps_pytest_failure(runner_module, monkeypatch):
    """pytest 失败时 runner 应返回非零退出码，而不是 0。"""
    _patch_runner(runner_module, monkeypatch, returncode=1)

    exit_code = runner_module.run_tests("integration", verbose=False)

    assert exit_code == 1
