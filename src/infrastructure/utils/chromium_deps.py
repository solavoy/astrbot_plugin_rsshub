"""Chromium 系统依赖自动检测与安装。

在 python:3.12-slim 等精简 Debian 镜像中，CloakBrowser 下载的 Chrome 二进制
缺少大量系统库。该模块在插件启动时检测缺失的 .so 文件，并通过 apt-get 自动安装
对应的 Debian 包。
"""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Final

from ..utils.logger import get_logger

logger = get_logger()

# 标记文件：表示依赖已装好，避免重复 apt 操作
_MARKER_DIR: Final = "chromium_deps"
_MARKER_FILENAME: Final = ".deps_installed"

# Chromium 在 python:3.12-slim (Debian Bookworm) 上所需的 Debian 包
_CHROMIUM_DEBIAN_PACKAGES: Final[list[str]] = [
    "libnspr4",
    "libnss3",
    "libnss3-tools",
    "libatk1.0-0t64",
    "libatk-bridge2.0-0t64",
    "libcups2t64",
    "libdrm2",
    "libdbus-1-3",
    "libxkbcommon0",
    "libxcomposite1",
    "libxdamage1",
    "libxfixes3",
    "libxrandr2",
    "libgbm1",
    "libasound2t64",
    "libpango-1.0-0",
    "libcairo2",
    "libatspi2.0-0t64",
    "libwayland-client0",
    "libwayland-egl1",
    "libwayland-cursor0",
]

# 备选包名（Debian 11 Bullseye 用的旧名）
_CHROMIUM_DEBIAN_BULLSEYE_PACKAGES: Final[list[str]] = [
    "libnspr4",
    "libnss3",
    "libnss3-tools",
    "libatk1.0-0",
    "libatk-bridge2.0-0",
    "libcups2",
    "libdrm2",
    "libdbus-1-3",
    "libxkbcommon0",
    "libxcomposite1",
    "libxdamage1",
    "libxfixes3",
    "libxrandr2",
    "libgbm1",
    "libasound2",
    "libpango-1.0-0",
    "libcairo2",
    "libatspi2.0-0",
    "libwayland-client0",
    "libwayland-egl1",
    "libwayland-cursor0",
]

# 尝试用内置的安装工具（优先）
_INSTALL_TOOL_NAMES: Final[list[str]] = [
    "playwright install-deps chromium",
    "npx playwright install-deps chromium",
    "playwright install --with-deps chromium",
]


def _get_marker_dir() -> Path:
    """依赖标记文件存放目录。"""
    from ..utils.paths import get_plugin_cache_dir

    return get_plugin_cache_dir(_MARKER_DIR)


def _is_installed() -> bool:
    """检查依赖标记文件是否存在。"""
    marker = _get_marker_dir() / _MARKER_FILENAME
    return marker.exists()


def _mark_installed() -> None:
    """写入依赖安装完成标记。"""
    marker_dir = _get_marker_dir()
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / _MARKER_FILENAME).touch()
    logger.info("Chromium 系统依赖已标记为已安装")


def _detect_chrome_binary() -> str | None:
    """尝试定位 CloakBrowser 下载的 Chrome 二进制。"""
    # 标准的 CloakBrowser 存放位置
    home = os.path.expanduser("~")
    cloak_dir = Path(home) / ".cloakbrowser"
    if not cloak_dir.is_dir():
        return None

    for entry in sorted(cloak_dir.iterdir(), reverse=True):
        if entry.name.startswith("chromium-") or entry.name.startswith("chrome-"):
            chrome_path = entry / "chrome"
            if chrome_path.is_file():
                return str(chrome_path.resolve())

    # 也看看 /root/.cloakbrowser
    root_dir = Path("/root/.cloakbrowser")
    if root_dir.is_dir() and root_dir != cloak_dir:
        for entry in sorted(root_dir.iterdir(), reverse=True):
            if entry.name.startswith("chromium-") or entry.name.startswith("chrome-"):
                chrome_path = entry / "chrome"
                if chrome_path.is_file():
                    return str(chrome_path.resolve())

    # 尝试 which chrome
    chrome_in_path = shutil.which("chrome")
    if chrome_in_path:
        return chrome_in_path

    return None


def _check_missing_libraries(chrome_path: str) -> list[str]:
    """用 ``ldd`` 检测缺失的 .so 文件，返回缺失的库名列表。

    Returns:
        缺失的库名列表（去重），例如 ``["libnspr4.so", "libnss3.so"]``
    """
    try:
        result = subprocess.run(
            ["ldd", chrome_path],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.debug("ldd 检测失败: %s", exc)
        return []

    missing: list[str] = []
    for line in result.stderr.split("\n") + result.stdout.split("\n"):
        if "not found" in line.lower() or "cannot open" in line.lower():
            # 提取 .so 文件名
            parts = line.strip().split()
            for part in parts:
                if part.endswith(".so") or ".so." in part:
                    soname = part.split("=>")[0].strip()
                    if soname not in missing:
                        missing.append(soname)
                    break
    return missing


def _run_apt_install(packages: list[str]) -> bool:
    """执行 ``apt-get install -y`` 安装指定包。

    Returns:
        ``True`` 安装成功，``False`` 失败。
    """
    if not packages:
        return True

    logger.info("正在安装 Chromium 系统依赖（%d 个包）...", len(packages))
    logger.debug("包列表: %s", " ".join(packages))

    try:
        # 先 apt-get update（slim 镜像没有本地包索引）
        logger.debug("更新包索引...")
        update_result = subprocess.run(
            ["apt-get", "update", "-qq"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if update_result.returncode != 0:
            logger.warning("apt-get update 失败: %s", update_result.stderr[:200])
            return False

        # apt-get install
        install_result = subprocess.run(
            ["apt-get", "install", "-y", "-qq"] + packages,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if install_result.returncode != 0:
            logger.warning(
                "apt-get install 失败: %s", install_result.stderr[:300]
            )
            return False

        logger.info("Chromium 系统依赖安装完成")
        return True

    except FileNotFoundError:
        logger.warning("系统 apt-get 不可用，非 Debian 环境？")
        return False
    except subprocess.TimeoutExpired:
        logger.warning("apt-get 操作超时")
        return False


async def ensure_chromium_deps() -> bool:
    """确保 Chromium 系统依赖已安装。

    如果已有标记文件，跳过检查。否则定位 Chrome 二进制，
    检测缺失库，通过 apt-get 安装对应包。

    Returns:
        ``True`` 依赖就绪或无需安装，``False`` 安装失败。
    """
    # 非 Linux 系统跳过
    if platform.system() != "Linux":
        return True

    # 已有标记文件，跳过
    if _is_installed():
        logger.debug("Chromium 依赖已安装（标记文件存在）")
        return True

    # 找 Chrome 二进制
    chrome_path = _detect_chrome_binary()
    if not chrome_path:
        logger.debug("未检测到 CloakBrowser Chrome 二进制，跳过依赖检查")
        return True

    # 检测缺失库
    missing = _check_missing_libraries(chrome_path)
    if not missing:
        logger.debug("Chromium 所有系统依赖已满足")
        _mark_installed()
        return True

    logger.info(
        "检测到 CloakBrowser Chrome 缺少 %d 个系统库，准备安装",
        len(missing),
    )

    # 在后台安装，不阻塞启动
    def _install():
        success = _run_apt_install(_CHROMIUM_DEBIAN_PACKAGES)
        if success:
            _mark_installed()

    await asyncio.to_thread(_install)

    # 安装后再验证
    if _is_installed():
        return True

    # 如果标记文件没写，可能是包名不匹配（Debian 版本不同）→ 试备选列表
    logger.info("尝试备选包名列表（Debian Bullseye 兼容）...")

    def _install_fallback():
        success = _run_apt_install(_CHROMIUM_DEBIAN_BULLSEYE_PACKAGES)
        if success:
            _mark_installed()

    await asyncio.to_thread(_install_fallback)

    return _is_installed()