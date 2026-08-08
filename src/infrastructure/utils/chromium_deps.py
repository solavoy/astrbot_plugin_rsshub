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


def ensure_chromium_deps() -> bool:
    """检查 Chromium 系统依赖；若缺失则在后台启动安装。

    该函数只做快速的同步检测（毫秒级），发现缺失库时创建后台线程
    执行 apt-get 安装，**不阻塞调用方**。安装完成后会重新用 ldd 验证
    并写入标记文件；验证失败（包列表不全）会保留标记缺失，下次启动
    重新尝试。

    Returns:
        ``True`` 依赖已就绪或已发起后台安装（无需阻塞等待），
        ``False`` 仅当检测本身失败（无法判断）。
    """
    # 非 Linux 系统跳过
    if platform.system() != "Linux":
        return True

    # 已有标记文件，跳过
    if _is_installed():
        logger.debug("Chromium 依赖已安装（标记文件存在）")
        return True

    # 找 Chrome 二进制（同步、快速）
    chrome_path = _detect_chrome_binary()
    if not chrome_path:
        logger.debug("未检测到 CloakBrowser Chrome 二进制，跳过依赖检查")
        return True

    # 检测缺失库（同步、快速）
    missing = _check_missing_libraries(chrome_path)
    if not missing:
        logger.debug("Chromium 所有系统依赖已满足")
        _mark_installed()
        return True

    logger.info(
        "检测到 CloakBrowser Chrome 缺少 %d 个系统库，后台安装中",
        len(missing),
    )

    # 后台安装（线程池），不阻塞启动。安装后重新验证缺失库并写标记。
    def _install() -> None:
        _run_apt_install_with_verify(_CHROMIUM_DEBIAN_PACKAGES, chrome_path)

    def _install_fallback() -> None:
        _run_apt_install_with_verify(
            _CHROMIUM_DEBIAN_BULLSEYE_PACKAGES,
            chrome_path,
        )

    import threading

    try:
        threading.Thread(
            target=_install,
            name="chromium-deps-install",
            daemon=True,
        ).start()
    except Exception as exc:
        logger.warning("无法启动 Chromium 依赖后台安装: %s", exc)
        return False

    return True


def _run_apt_install_with_verify(packages: list[str], chrome_path: str) -> None:
    """安装依赖，安装成功后重新检测缺失库，确认后才写标记。

    安装后仍缺库（固定包列表未覆盖）时不写标记，保证下次启动重试。
    """
    if _run_apt_install(packages) and not _check_missing_libraries(chrome_path):
        _mark_installed()
    else:
        logger.warning(
            "Chromium 依赖安装后仍缺失系统库，标记不写入，下次启动将重试"
        )