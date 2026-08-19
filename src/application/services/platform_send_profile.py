"""平台发送画像：当前统一「markdown 正文 + 媒体内联为 markdown 链接」。

为后续按平台差异化推送预留接缝：
- ``AbstractSendProfile`` 定义平台发送能力接口；
- ``profile_for_platform`` 目前返回统一画像（全部内联媒体），后续从配置加载
  按平台返回不同画像（例如飞书内联、部分平台走原生媒体组件）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformSendProfile(ABC):
    """平台发送能力画像（Strategy：按平台差异发送行为）。"""

    # 是否把媒体内联进 markdown 正文（图片 `![](url)`、其余为 `[type](url)`），
    # 而不是作为独立媒体组件下载发送。
    inline_media_as_markdown: bool = True

    @abstractmethod
    def build_inline_media_markdown(self, media: list[tuple[str, str]]) -> str:
        """把媒体渲染为 markdown 内联片段。"""


@dataclass(frozen=True)
class DefaultSendProfile(PlatformSendProfile):
    """统一画像：媒体一律内联为 markdown 链接。"""

    def build_inline_media_markdown(self, media: list[tuple[str, str]]) -> str:
        lines: list[str] = []
        for media_type, url in media:
            url = str(url or "").strip()
            if not url:
                continue
            if media_type == "image":
                lines.append(f"![图片]({url})")
            else:
                lines.append(f"[{media_type or '媒体'}]({url})")
        return "\n".join(lines)


_DEFAULT_PROFILE = DefaultSendProfile()


def profile_for_platform(platform: str = "") -> PlatformSendProfile:
    """解析平台发送画像。

    当前统一返回内联画像；后续从配置读取按平台差异化（如飞书内联、其余平台
    可按配置关闭内联改走原生媒体组件）。
    """
    return _DEFAULT_PROFILE


def build_inline_media_markdown(media: list[tuple[str, str]]) -> str:
    """便捷入口：按默认画像把媒体转 markdown 内联片段。"""
    return _DEFAULT_PROFILE.build_inline_media_markdown(media)
