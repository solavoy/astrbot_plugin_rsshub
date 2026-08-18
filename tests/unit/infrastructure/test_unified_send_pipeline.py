"""统一发送管线测试：多平台对同一组件输入产出同一顺序（正文→媒体→尾）。

覆盖「全部平台走同一管线」的回归：正文在前、媒体依次在后这一顺序不变量
由 MessageChainFormatter 统一保证，与具体 sender 实现无关；各平台 sender
都并入 DefaultMessageSender.send_to_user 骨架，最终都消费这条 chain。

测试环境中 astrbot.api.message_components 被 conftest 以 MagicMock 替换，
因此用 Plain/Image/Video 的 return_value 同一性断言链内组件顺序与存在性。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from astrbot.api.message_components import Image, Plain, Video

from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.types import (
    PreparedMedia,
)
from astrbot_plugin_rsshub.src.infrastructure.pipeline import MessageChainFormatter


@pytest.mark.parametrize(
    "platform",
    ["", "telegram", "onebot", "qq_official", "weixin_oc", "lark"],
)
def test_chain_order_is_text_then_media_then_tails(platform):
    Plain.reset_mock()
    formatter = MessageChainFormatter()
    components = formatter.build_components(
        prepared_media=[
            PreparedMedia(
                media_type="image",
                original_url="https://e.com/a.jpg",
                local_path=Path("/tmp/a.jpg"),
            ),
            PreparedMedia(
                media_type="video",
                original_url="https://e.com/b.mp4",
                local_path=Path("/tmp/b.mp4"),
            ),
        ],
        text="文章正文",
        failed_urls=[],
        platform=platform,
    )
    chain = formatter.build_chain_from_components(components, platform=platform)
    # 顺序固定：第一个组件必须是正文 Plain（正文在前）
    assert chain[0] is Plain.return_value
    assert Plain.call_args.args[0] == "文章正文"
    # 且每个媒体的本地路径都出现在链中（未被丢弃）
    assert any(item is Image.return_value for item in chain)
    assert any(item is Video.return_value for item in chain)
    # 一条链：正文 + 图片 + 视频，无多余拆发
    assert len(chain) == 3
