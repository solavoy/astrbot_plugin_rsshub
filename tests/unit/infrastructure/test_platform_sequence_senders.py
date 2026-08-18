from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from astrbot_plugin_rsshub.src.domain.entities.content_types import LayoutFragment
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.base_sender import (
    DefaultMessageSender,
)
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.factory import (
    get_sender_for_platform,
)
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.onebot_sender import (
    OneBotMessageSender,
)
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.qq_official_sender import (
    QQOfficialMessageSender,
)
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.telegram_sender import (
    TelegramMessageSender,
)
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.telegraph_client import (
    TelegraphClient,
)
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.types import (
    ChannelInfo,
    MediaVariant,
    MessageContext,
    PreparedMedia,
    SendRequest,
    SendResult,
)
from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.weixin_oc_sender import (
    WeixinOCMessageSender,
)


class _Plain:
    def __init__(self, text: str) -> None:
        self.text = text


class _Image:
    def __init__(self, file: str) -> None:
        self.file = file


class _Video:
    def __init__(self, file: str) -> None:
        self.file = file


class _Record:
    def __init__(self, file: str, text: str = "") -> None:
        self.file = file
        self.text = text


class _File:
    def __init__(self, name: str, file: str, url: str) -> None:
        self.name = name
        self.file = file
        self.url = url


class _Node:
    def __init__(self, content: list, name: str, uin: str = "0") -> None:
        self.content = content
        self.name = name
        self.uin = uin


class _Nodes:
    def __init__(self, nodes: list) -> None:
        self.nodes = nodes


def _patch_components(monkeypatch) -> None:
    module = sys.modules["astrbot.api.message_components"]
    monkeypatch.setattr(module, "Plain", _Plain, raising=False)
    monkeypatch.setattr(module, "Image", _Image, raising=False)
    monkeypatch.setattr(module, "Video", _Video, raising=False)
    monkeypatch.setattr(module, "Record", _Record, raising=False)
    monkeypatch.setattr(module, "File", _File, raising=False)


def _patch_onebot_sender_namespace(monkeypatch) -> None:
    """OneBot 发送器在模块层直接绑定 Node/Nodes/Plain，需在模块命名空间打桩。"""
    from astrbot_plugin_rsshub.src.infrastructure.messaging.senders import (
        onebot_sender,
    )

    monkeypatch.setattr(onebot_sender, "Node", _Node)
    monkeypatch.setattr(onebot_sender, "Nodes", _Nodes)
    monkeypatch.setattr(onebot_sender, "Plain", _Plain)
    module = sys.modules["astrbot.api.message_components"]
    monkeypatch.setattr(module, "Plain", _Plain, raising=False)
    monkeypatch.setattr(module, "Image", _Image, raising=False)
    monkeypatch.setattr(module, "Video", _Video, raising=False)
    monkeypatch.setattr(module, "Record", _Record, raising=False)
    monkeypatch.setattr(module, "File", _File, raising=False)


@pytest.fixture(autouse=True)
def _reset_sender_behavior():
    DefaultMessageSender.configure_runtime(timeout_seconds=30, proxy="")
    DefaultMessageSender.configure_behavior()
    yield
    DefaultMessageSender.configure_runtime(timeout_seconds=30, proxy="")
    DefaultMessageSender.configure_behavior()


def _request() -> SendRequest:
    return SendRequest(
        session_id="default:UserMessage:1",
        message="entry text",
        prepared_media=[
            PreparedMedia(
                media_type="image",
                original_url="https://example.com/1.jpg",
                local_path=Path("/tmp/1.jpg"),
            ),
            PreparedMedia(
                media_type="video",
                original_url="https://example.com/2.mp4",
                local_path=Path("/tmp/2.mp4"),
            ),
        ],
    )


@pytest.mark.asyncio
async def test_qq_official_plain_text_uses_single_send(monkeypatch):
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(session_id="default:UserMessage:1", message="entry text"),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert isinstance(calls[0][0], _Plain)
    assert calls[0][0].text == "entry text"


@pytest.mark.asyncio
async def test_qq_official_markdown_force_keeps_active_push_plain(monkeypatch):
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[dict] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(kwargs)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(session_id="default:UserMessage:1", message="**entry**"),
        context=MessageContext(
            platform_name="qq_official",
            sender_strategy={"markdown_mode": "force"},
        ),
    )

    assert result.ok is True
    assert calls == [{"use_markdown": False}]


@pytest.mark.asyncio
async def test_qq_official_markdown_plain_sets_message_chain_flag_false(monkeypatch):
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[dict] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(kwargs)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(session_id="default:UserMessage:1", message="entry text"),
        context=MessageContext(
            platform_name="qq_official",
            sender_strategy={"markdown_mode": "plain"},
        ),
    )

    assert result.ok is True
    assert calls == [{"use_markdown": False}]


@pytest.mark.asyncio
async def test_qq_official_markdown_auto_keeps_active_push_plain(monkeypatch):
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[dict] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(kwargs)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(session_id="default:UserMessage:1", message="**entry**"),
        context=MessageContext(
            platform_name="qq_official",
            sender_strategy={"markdown_mode": "auto"},
        ),
    )

    assert result.ok is True
    assert calls == [{"use_markdown": False}]


@pytest.mark.asyncio
async def test_qq_official_multimedia_default_sends_one_text_first_chain(
    monkeypatch,
):
    """统一骨架：多媒体的默认路径是单条合链，正文在前、媒体在后（media_order image<video）。"""
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        _request(),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert [type(item) for item in calls[0]] == [_Plain, _Image, _Video]
    assert calls[0][0].text == "entry text"
    assert calls[0][1].file == "/tmp/1.jpg"
    assert calls[0][2].file == "/tmp/2.mp4"


@pytest.mark.asyncio
async def test_qq_official_multimedia_exceeding_threshold_degrades_to_files_then_text(
    monkeypatch,
):
    _patch_components(monkeypatch)
    DefaultMessageSender.configure_behavior(
        qq_official_media_threshold=1,
        qq_official_degrade_strategy="file_then_link",
    )
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        _request(),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert [type(chain[0]) for chain in calls] == [_File, _File, _Plain]
    assert calls[0][0].file == "/tmp/1.jpg"
    assert calls[1][0].file == "/tmp/2.mp4"
    assert calls[-1][0].text == "entry text"


@pytest.mark.asyncio
async def test_qq_official_single_image_and_text_share_one_chain(monkeypatch):
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="entry text",
            prepared_media=[
                PreparedMedia(
                    media_type="image",
                    original_url="https://example.com/1.jpg",
                    local_path=Path("/tmp/1.jpg"),
                )
            ],
        ),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert isinstance(calls[0][0], _Plain)
    assert calls[0][0].text == "entry text"
    assert isinstance(calls[0][1], _Image)


@pytest.mark.asyncio
async def test_qq_official_single_video_sends_one_text_first_chain(monkeypatch):
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="entry text",
            prepared_media=[
                PreparedMedia(
                    media_type="video",
                    original_url="https://example.com/2.mp4",
                    local_path=Path("/tmp/2.mp4"),
                )
            ],
        ),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert [type(item) for item in calls[0]] == [_Plain, _Video]
    assert calls[0][0].text == "entry text"
    assert calls[0][1].file == "/tmp/2.mp4"
    assert not any(isinstance(chain[0], _File) for chain in calls)


@pytest.mark.asyncio
async def test_qq_official_single_video_from_media_download_uses_video(monkeypatch):
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_prepare_media(media, timeout=30, proxy=""):
        assert media == [("video", "https://example.com/2.mp4")]
        return [
            PreparedMedia(
                media_type="video",
                original_url="https://example.com/2.mp4",
                local_path=Path("/tmp/2.mp4"),
            )
        ]

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "prepare_media", fake_prepare_media)
    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="entry text",
            media=[("video", "https://example.com/2.mp4")],
        ),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert [type(item) for item in calls[0]] == [_Plain, _Video]
    assert calls[0][0].text == "entry text"
    assert calls[0][1].file == "/tmp/2.mp4"
    assert not any(isinstance(chain[0], _File) for chain in calls)


@pytest.mark.asyncio
async def test_qq_official_ignores_layout_and_sends_message(monkeypatch):
    _patch_components(monkeypatch)
    DefaultMessageSender.configure_behavior(qq_official_media_threshold=0)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="fallback",
            layout=[
                LayoutFragment(
                    kind="image",
                    media_type="image",
                    url="https://example.com/1.jpg",
                ),
                LayoutFragment(kind="text", text="caption 1"),
                LayoutFragment(
                    kind="video",
                    media_type="video",
                    url="https://example.com/2.mp4",
                ),
                LayoutFragment(kind="text", text="caption 2"),
            ],
        ),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert isinstance(calls[0][0], _Plain)
    assert calls[0][0].text == "fallback"


@pytest.mark.asyncio
async def test_qq_official_original_style_file_fragment_uses_file_component(
    monkeypatch,
):
    _patch_components(monkeypatch)
    DefaultMessageSender.configure_behavior(qq_official_media_threshold=0)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="fallback",
            layout=[
                LayoutFragment(
                    kind="image",
                    media_type="image",
                    url="https://example.com/cover.jpg",
                ),
                LayoutFragment(kind="text", text="caption"),
                LayoutFragment(
                    kind="file",
                    media_type="file",
                    url="https://example.com/report.pdf",
                    name="report.pdf",
                ),
                LayoutFragment(kind="text", text="after file"),
            ],
        ),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert isinstance(calls[0][0], _Plain)
    assert calls[0][0].text == "fallback"


@pytest.mark.asyncio
async def test_qq_official_file_degrade_failure_continues_and_appends_url(
    monkeypatch,
):
    _patch_components(monkeypatch)
    DefaultMessageSender.configure_behavior(
        qq_official_media_threshold=1,
        qq_official_degrade_strategy="file_then_link",
    )
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        if isinstance(chain[0], _File) and chain[0].file == "/tmp/1.jpg":
            return SendResult(ok=False, transient=True, detail="file failed")
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        _request(),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert [type(chain[0]) for chain in calls] == [_File, _File, _Plain]
    assert "媒体原始链接:" in calls[-1][0].text
    assert "https://example.com/1.jpg" in calls[-1][0].text
    assert "https://example.com/2.mp4" not in calls[-1][0].text


@pytest.mark.asyncio
async def test_qq_official_media_threshold_link_only_degrade(monkeypatch):
    _patch_components(monkeypatch)
    DefaultMessageSender.configure_behavior(
        qq_official_media_threshold=1,
        qq_official_degrade_strategy="link_only",
    )
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        _request(),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert isinstance(calls[0][0], _Plain)
    assert "媒体原始链接:" in calls[0][0].text
    assert "https://example.com/1.jpg" in calls[0][0].text
    assert "https://example.com/2.mp4" in calls[0][0].text


@pytest.mark.asyncio
async def test_qq_official_original_style_multimedia_threshold_still_degrades(
    monkeypatch,
):
    _patch_components(monkeypatch)
    DefaultMessageSender.configure_behavior(
        qq_official_media_threshold=1,
        qq_official_degrade_strategy="file_then_link",
    )
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="fallback",
            prepared_media=[
                PreparedMedia(
                    media_type="image",
                    original_url="https://example.com/1.jpg",
                    local_path=Path("/tmp/1.jpg"),
                ),
                PreparedMedia(
                    media_type="video",
                    original_url="https://example.com/2.mp4",
                    local_path=Path("/tmp/2.mp4"),
                ),
            ],
            layout=[
                LayoutFragment(
                    kind="image",
                    media_type="image",
                    url="https://example.com/1.jpg",
                ),
                LayoutFragment(kind="text", text="caption 1"),
                LayoutFragment(
                    kind="video",
                    media_type="video",
                    url="https://example.com/2.mp4",
                ),
                LayoutFragment(kind="text", text="caption 2"),
            ],
        ),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert [type(chain[0]) for chain in calls] == [_File, _File, _Plain]
    assert calls[0][0].file == "/tmp/1.jpg"
    assert calls[1][0].file == "/tmp/2.mp4"
    # original layout 已移除：正文统一为 message
    assert calls[-1][0].text == "fallback"


# ------------------------------------------------------------------
# QQ Official 发送时刻失败降级（后置发送降级钩子）
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_qq_official_send_failure_degrades_via_file_and_counts_as_success(
    monkeypatch,
):
    """媒体预判可发但发送时刻被平台拒绝：单链 ok=False 后经文件候选降级送达 → ok=True。

    恢复已删除的 _counts_degraded_media_delivery_as_success 语义：QQ 官方把降级送达
    视为成功（ok=True），避免轮询循环把已送达消息当失败重复补推。
    """
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        if any(isinstance(item, (_Image, _Video)) for item in chain):
            return SendResult(ok=False, transient=False, detail="media rejected")
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        _request(),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    # 首条合链失败后，降级路径把每个失败媒体作为 File 候选重新送出
    assert isinstance(calls[0][0], _Plain)
    assert isinstance(calls[0][1], _Image)
    file_calls = [chain for chain in calls if isinstance(chain[0], _File)]
    assert {chain[0].file for chain in file_calls} == {"/tmp/1.jpg", "/tmp/2.mp4"}
    # 正文（含降级后失败链接）也重新送出
    assert any(isinstance(chain[0], _Plain) for chain in calls[1:])


@pytest.mark.asyncio
async def test_qq_official_send_failure_returns_failure_when_nothing_deliverable(
    monkeypatch,
):
    """降级送达也全部失败时仍返回 ok=False，让轮询可以补推。"""
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=False, transient=False, detail="platform rejected")

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        _request(),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is False
    # 首条合链 + 两个 File 候选 + 正文均失败
    assert len(calls) == 4


@pytest.mark.asyncio
async def test_weixin_oc_plain_text_uses_single_send(monkeypatch):
    _patch_components(monkeypatch)
    sender = WeixinOCMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(session_id="default:UserMessage:1", message="entry text"),
        context=MessageContext(platform_name="weixin_oc"),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert isinstance(calls[0][0], _Plain)
    assert calls[0][0].text == "entry text"


@pytest.mark.asyncio
async def test_weixin_oc_sends_single_image_and_text_in_one_chain(monkeypatch):
    _patch_components(monkeypatch)
    sender = WeixinOCMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="entry text",
            prepared_media=[
                PreparedMedia(
                    media_type="image",
                    original_url="https://example.com/1.jpg",
                    local_path=Path("/tmp/1.jpg"),
                )
            ],
        ),
        context=MessageContext(platform_name="weixin_oc"),
    )

    # 统一骨架：正文在前、媒体在后单条链，不再媒体优先拆成两条。
    assert result.ok is True
    assert len(calls) == 1
    assert [type(item) for item in calls[0]] == [_Plain, _Image]
    assert calls[0][0].text == "entry text"
    assert calls[0][1].file == "/tmp/1.jpg"


@pytest.mark.asyncio
async def test_weixin_oc_multimedia_is_sent_in_single_chain(monkeypatch):
    _patch_components(monkeypatch)
    sender = WeixinOCMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        _request(),
        context=MessageContext(platform_name="weixin_oc"),
    )

    # 统一骨架：正文 → 媒体（按 media_order image<video）一条链，不再逐条拆发。
    assert result.ok is True
    assert len(calls) == 1
    assert [type(item) for item in calls[0]] == [_Plain, _Image, _Video]
    assert calls[0][0].text == "entry text"
    assert calls[0][1].file == "/tmp/1.jpg"
    assert calls[0][2].file == "/tmp/2.mp4"


@pytest.mark.asyncio
async def test_weixin_oc_ignores_layout_and_sends_message(monkeypatch):
    _patch_components(monkeypatch)
    sender = WeixinOCMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="fallback",
            layout=[
                LayoutFragment(kind="text", text="lead"),
                LayoutFragment(
                    kind="image",
                    media_type="image",
                    url="https://example.com/1.jpg",
                ),
                LayoutFragment(kind="text", text="caption"),
            ],
        ),
        context=MessageContext(platform_name="weixin_oc"),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert isinstance(calls[0][0], _Plain)
    assert calls[0][0].text == "fallback"


@pytest.mark.asyncio
async def test_weixin_oc_partial_media_failure_continues_and_appends_url(monkeypatch):
    _patch_components(monkeypatch)
    sender = WeixinOCMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="entry text",
            prepared_media=[
                PreparedMedia(
                    media_type="image",
                    original_url="https://example.com/1.jpg",
                    local_path=Path("/tmp/1.jpg"),
                ),
                PreparedMedia(
                    media_type="video",
                    original_url="https://example.com/2.mp4",
                    download_failed=True,
                ),
            ],
        ),
        context=MessageContext(platform_name="weixin_oc"),
    )

    # 统一失败路径：失败的媒体不再逐条重试，其原始链接并入正文（append_failed_links），
    # 健康媒体仍随正文一条链发出。
    assert result.ok is True
    assert len(calls) == 1
    assert [type(item) for item in calls[0]] == [_Plain, _Image]
    assert calls[0][0].text.startswith("entry text")
    assert "媒体原始链接:" in calls[0][0].text
    assert "https://example.com/2.mp4" in calls[0][0].text
    assert "https://example.com/1.jpg" not in calls[0][0].text
    assert calls[0][1].file == "/tmp/1.jpg"


def test_factory_maps_weixin_aliases_to_dedicated_sender():
    assert get_sender_for_platform("weixin_oc") is WeixinOCMessageSender
    assert get_sender_for_platform("wechat") is WeixinOCMessageSender


@pytest.mark.asyncio
async def test_telegram_large_local_image_is_sent_as_file(monkeypatch, tmp_path):
    """>10MB 本地图超出 photo 上限：走 MediaSendPlanner 候选改写，降级为 document/file 发送。"""
    _patch_components(monkeypatch)
    image_path = tmp_path / "large.jpg"
    image_path.write_bytes(b"0" * (10 * 1024 * 1024 + 1))
    sender = TelegramMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="telegram:UserMessage:1",
            message="entry text",
            prepared_media=[
                PreparedMedia(
                    media_type="image",
                    original_url="https://example.com/large.jpg",
                    local_path=image_path,
                )
            ],
        ),
        context=MessageContext(platform_name="telegram"),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert [type(item) for item in calls[0]] == [_Plain, _File]
    assert calls[0][1].file == str(image_path)


@pytest.mark.asyncio
async def test_telegram_native_send_is_text_first_chain(monkeypatch):
    _patch_components(monkeypatch)
    sender = TelegramMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="telegram:UserMessage:1",
            message="entry text",
            prepared_media=[
                PreparedMedia(
                    media_type="image",
                    original_url="https://example.com/1.jpg",
                    local_path=Path("/tmp/1.jpg"),
                )
            ],
        ),
        context=MessageContext(platform_name="telegram"),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert [type(item) for item in calls[0]] == [_Plain, _Image]
    assert calls[0][0].text == "entry text"
    assert calls[0][1].file == "/tmp/1.jpg"


@pytest.mark.asyncio
async def test_telegram_gif_over_photo_limit_stays_animation(monkeypatch, tmp_path):
    _patch_components(monkeypatch)
    gif_path = tmp_path / "animation.gif"
    gif_path.write_bytes(b"0" * (10 * 1024 * 1024 + 1))
    sender = TelegramMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="telegram:UserMessage:1",
            message="entry text",
            prepared_media=[
                PreparedMedia(
                    media_type="image",
                    original_url="https://example.com/animation.gif",
                    local_path=gif_path,
                    detected_suffix=".gif",
                )
            ],
        ),
        context=MessageContext(platform_name="telegram"),
    )

    assert result.ok is True
    assert len(calls) == 1
    # 正文在前、媒体在后
    assert isinstance(calls[0][0], _Plain)
    assert isinstance(calls[0][1], _Image)
    assert calls[0][1].file == str(gif_path)


@pytest.mark.asyncio
async def test_telegram_telegraph_uses_entry_title_and_plain_url(monkeypatch):
    _patch_components(monkeypatch)
    created: dict[str, object] = {}
    client_kwargs: dict[str, object] = {}

    async def fake_create_page(self, **kwargs):
        created.update(kwargs)
        return "https://telegra.ph/entry-title"

    original_init = TelegraphClient.__init__

    def fake_init(self, **kwargs):
        client_kwargs.update(kwargs)
        original_init(self, **kwargs)

    monkeypatch.setattr(TelegraphClient, "__init__", fake_init)
    monkeypatch.setattr(TelegraphClient, "create_media_page", fake_create_page)

    DefaultMessageSender.configure_runtime(
        timeout_seconds=30,
        proxy="socks5://127.0.0.1:7890",
    )
    sender = TelegramMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="telegram:UserMessage:1",
            message="Entry title\n\nBody text\n\nvia https://example.com/post | Feed",
            prepared_media=[
                PreparedMedia(
                    media_type="image",
                    original_url="https://example.com/1.webp",
                ),
                PreparedMedia(
                    media_type="image",
                    original_url="https://example.com/2.webp",
                ),
            ],
        ),
        context=MessageContext(
            platform_name="telegram",
            send_mode=0,
            entry_title="Entry title",
            entry_link="https://example.com/post",
            channel=ChannelInfo(title="Feed", link="https://example.com/feed"),
            sender_strategy={
                "enable_telegraph": True,
                "telegraph_token": "token",
                "telegraph_proxy": "http://tg-proxy:8080",
            },
        ),
    )

    assert result.ok is True
    assert created["title"] == "Entry title"
    assert created["media_urls"] == [
        "https://example.com/1.webp",
        "https://example.com/2.webp",
    ]
    # Telegraph 使用其专属代理，不继承通用 HTTP 代理（socks5 那条）。
    assert client_kwargs["proxy"] == "http://tg-proxy:8080"
    assert len(calls) == 1
    assert isinstance(calls[0][0], _Plain)
    assert "https://telegra.ph/entry-title" in calls[0][0].text
    assert "Telegraph:" not in calls[0][0].text


# ------------------------------------------------------------------
# GIF conversion regression
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_qq_official_gif_from_video_counts_as_single_image_with_text(monkeypatch):
    """转换 GIF（video + *.gif）在 QQ Official 中应与单图+文本合发。"""
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="entry text",
            prepared_media=[
                PreparedMedia(
                    media_type="video",
                    original_url="https://example.com/video.mp4",
                    local_path=Path("/tmp/video.gif"),
                )
            ],
        ),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert isinstance(calls[0][0], _Plain)
    assert calls[0][0].text == "entry text"
    assert isinstance(calls[0][1], _Image)


@pytest.mark.asyncio
async def test_qq_official_gif_oversize_selects_compressed_variant_candidate(
    monkeypatch,
):
    """主 GIF 变体超限时，候选改写（_apply_media_send_candidates）选中压缩 GIF 变体。

    这是统一骨架下压缩 GIF 与原始视频竞争的等价行为；旧的单视频回退链路已删除。
    """
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    prepared = PreparedMedia(
        media_type="image",
        original_url="https://example.com/video.mp4",
        local_path=Path("/tmp/video.gif"),
        detected_suffix=".gif",
    )
    prepared.variants = [
        MediaVariant(
            "gif",
            "image",
            Path("/tmp/video.gif"),
            suffix=".gif",
            size_bytes=11 * 1024 * 1024,
        ),
        MediaVariant(
            "compressed_gif",
            "image",
            Path("/tmp/video-small.gif"),
            suffix=".gif",
            size_bytes=5 * 1024 * 1024,
        ),
        MediaVariant(
            "original",
            "video",
            Path("/tmp/video.mp4"),
            suffix=".mp4",
            size_bytes=900 * 1024,
        ),
    ]

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="entry text",
            prepared_media=[prepared],
        ),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert [type(item) for item in calls[0]] == [_Plain, _Image]
    assert calls[0][0].text == "entry text"
    # 候选改写选中压缩 GIF（超限的 11MB 主 GIF 变体被跳过）
    assert calls[0][1].file == "/tmp/video-small.gif"


@pytest.mark.asyncio
async def test_qq_official_oversize_video_uses_link_only_candidate(
    monkeypatch,
    tmp_path,
):
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []
    video_path = tmp_path / "huge.mp4"
    video_path.write_bytes(b"0")

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    prepared = PreparedMedia(
        media_type="video",
        original_url="https://example.com/huge.mp4",
        local_path=video_path,
        detected_suffix=".mp4",
    )
    prepared.variants = [
        MediaVariant(
            "original",
            "video",
            video_path,
            suffix=".mp4",
            size_bytes=101 * 1024 * 1024,
        )
    ]

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="entry text",
            prepared_media=[prepared],
        ),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert [type(chain[0]) for chain in calls] == [_Plain]
    assert "媒体原始链接:" in calls[0][0].text
    assert "https://example.com/huge.mp4" in calls[0][0].text
    assert not any(isinstance(chain[0], _Video) for chain in calls)


@pytest.mark.asyncio
async def test_qq_official_oversize_image_uses_link_only_candidate(
    monkeypatch,
    tmp_path,
):
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []
    image_path = tmp_path / "huge.jpg"
    image_path.write_bytes(b"0")

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    prepared = PreparedMedia(
        media_type="image",
        original_url="https://example.com/huge.jpg",
        local_path=image_path,
        detected_suffix=".jpg",
    )
    prepared.variants = [
        MediaVariant(
            "primary",
            "image",
            image_path,
            suffix=".jpg",
            size_bytes=13 * 1024 * 1024,
        )
    ]

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="entry text",
            prepared_media=[prepared],
        ),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert [type(chain[0]) for chain in calls] == [_Plain]
    assert "媒体原始链接:" in calls[0][0].text
    assert "https://example.com/huge.jpg" in calls[0][0].text
    assert not any(isinstance(chain[0], (_Image, _File)) for chain in calls)


@pytest.mark.asyncio
async def test_qq_official_original_style_gif_from_layout_matches_prepared(monkeypatch):
    """style=original 中 layout URL 命中转换后的 PreparedMedia 时按图片发送。"""
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    prepared = [
        PreparedMedia(
            media_type="video",
            original_url="https://example.com/video.gif",
            local_path=Path("/tmp/video.gif"),
        )
    ]

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="fallback",
            prepared_media=prepared,
            layout=[
                LayoutFragment(
                    kind="video",
                    media_type="video",
                    url="https://example.com/video.gif",
                ),
                LayoutFragment(kind="text", text="caption"),
            ],
        ),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert isinstance(calls[0][0], _Plain)
    assert calls[0][0].text == "fallback"
    assert isinstance(calls[0][1], _Image)


@pytest.mark.asyncio
async def test_qq_official_original_style_gif_from_downloaded_media(monkeypatch):
    """真实推送路径中 request.media 预下载成 GIF 后，original layout 也按图片发送。"""
    _patch_components(monkeypatch)
    sender = QQOfficialMessageSender()
    calls: list[list] = []

    async def fake_prepare_media(media, timeout=30, proxy=""):
        assert media == [("video", "https://example.com/video.mp4")]
        return [
            PreparedMedia(
                media_type="video",
                original_url="https://example.com/video.mp4",
                local_path=Path("/tmp/video.gif"),
            )
        ]

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "prepare_media", fake_prepare_media)
    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:UserMessage:1",
            message="fallback",
            media=[("video", "https://example.com/video.mp4")],
            layout=[
                LayoutFragment(
                    kind="video",
                    media_type="video",
                    url="https://example.com/video.mp4",
                ),
                LayoutFragment(kind="text", text="caption"),
            ],
        ),
        context=MessageContext(platform_name="qq_official"),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert isinstance(calls[0][0], _Plain)
    assert isinstance(calls[0][1], _Image)
    assert calls[0][1].file == "/tmp/video.gif"


# ------------------------------------------------------------------
# OneBot unified-skeleton regression
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_onebot_merged_forward_goes_through_skeleton_text_first(monkeypatch):
    """OneBot 经统一骨架 → 钩子：_send_chain 收到 [Nodes([...])]，节点顺序正文在前。"""
    _patch_components(monkeypatch)
    _patch_onebot_sender_namespace(monkeypatch)
    sender = OneBotMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:GroupMessage:1",
            message="entry text",
            prepared_media=[
                PreparedMedia(
                    media_type="image",
                    original_url="https://example.com/1.jpg",
                    local_path=Path("/tmp/1.jpg"),
                ),
                PreparedMedia(
                    media_type="video",
                    original_url="https://example.com/2.mp4",
                    local_path=Path("/tmp/2.mp4"),
                ),
            ],
        ),
        context=MessageContext(
            channel=ChannelInfo(title="Feed Title"),
            platform_name="aiocqhttp",
        ),
    )

    assert result.ok is True
    assert len(calls) == 1
    assert isinstance(calls[0][0], _Nodes)
    nodes = calls[0][0].nodes
    assert isinstance(nodes[0].content[0], _Plain)
    assert nodes[0].content[0].text == "entry text"
    assert isinstance(nodes[1].content[0], _Image)
    assert nodes[1].content[0].file == "/tmp/1.jpg"
    assert isinstance(nodes[2].content[0], _Video)
    assert nodes[2].content[0].file == "/tmp/2.mp4"


@pytest.mark.asyncio
async def test_onebot_napcat_always_streams_upload_before_send(monkeypatch):
    """napcat_stream_mode=always：发送前经 _stream_upload_nodes 上传本地视频。"""
    _patch_components(monkeypatch)
    _patch_onebot_sender_namespace(monkeypatch)
    sender = OneBotMessageSender()
    calls: list[list] = []
    stream_calls: list[tuple] = []

    async def fake_stream(bot_client, nodes):
        stream_calls.append((bot_client, nodes))
        # 模拟流式上传后返回新节点
        return [_Node(node.content, node.name, node.uin) for node in nodes]

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)
    monkeypatch.setattr(sender, "_stream_upload_nodes", fake_stream)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:GroupMessage:1",
            message="entry text",
            prepared_media=[
                PreparedMedia(
                    media_type="video",
                    original_url="https://example.com/2.mp4",
                    local_path=Path("/tmp/2.mp4"),
                )
            ],
        ),
        context=MessageContext(
            channel=ChannelInfo(title="Feed Title"),
            platform_name="aiocqhttp",
            sender_strategy={"napcat_stream_mode": "always"},
            event=SimpleNamespace(bot=object()),
        ),
    )

    assert result.ok is True
    assert len(stream_calls) == 1
    assert stream_calls[0][0] is not None
    assert len(calls) == 1
    Nodes = calls[0][0]
    assert isinstance(Nodes, _Nodes)
    nodes = Nodes.nodes
    assert isinstance(nodes[0].content[0], _Plain)
    assert isinstance(nodes[1].content[0], _Video)


@pytest.mark.asyncio
async def test_onebot_napcat_fallback_streams_upload_after_failure(
    monkeypatch, tmp_path
):
    """napcat_stream_mode=fallback：合并转发失败且有本地视频时，经流式上传重试。"""
    _patch_components(monkeypatch)
    _patch_onebot_sender_namespace(monkeypatch)
    sender = OneBotMessageSender()
    calls: list[list] = []
    stream_calls: list[tuple] = []
    video_path = tmp_path / "local.mp4"
    video_path.write_bytes(b"0")

    async def fake_stream(bot_client, nodes):
        stream_calls.append((bot_client, nodes))
        streamed = []
        for node in nodes:
            content = [
                _Video(f"streamed:{comp.file}")
                if isinstance(comp, _Video)
                else comp
                for comp in node.content
            ]
            streamed.append(_Node(content, node.name, node.uin))
        return streamed

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        if len(calls) == 1:
            return SendResult(ok=False, detail="forward failed")
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)
    monkeypatch.setattr(sender, "_stream_upload_nodes", fake_stream)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:GroupMessage:1",
            message="entry text",
            prepared_media=[
                PreparedMedia(
                    media_type="video",
                    original_url="https://example.com/2.mp4",
                    local_path=video_path,
                )
            ],
        ),
        context=MessageContext(
            channel=ChannelInfo(title="Feed Title"),
            platform_name="aiocqhttp",
            sender_strategy={"napcat_stream_mode": "fallback"},
            event=SimpleNamespace(bot=object()),
        ),
    )

    assert result.ok is True
    assert len(stream_calls) == 1
    assert len(calls) == 2
    streamed = calls[1][0].nodes
    assert isinstance(streamed[0].content[0], _Plain)
    assert isinstance(streamed[1].content[0], _Video)
    assert streamed[1].content[0].file == f"streamed:{video_path}"


@pytest.mark.asyncio
async def test_onebot_url_only_media_degrades_to_link_only(monkeypatch):
    """URL-only 媒体（无本地文件）候选仅有 link，经 _apply_first_send_candidates 降级为链接文本。"""
    _patch_components(monkeypatch)
    _patch_onebot_sender_namespace(monkeypatch)
    sender = OneBotMessageSender()
    calls: list[list] = []

    async def fake_send_chain(session_id: str, chain: list, **kwargs):
        calls.append(chain)
        return SendResult(ok=True)

    monkeypatch.setattr(sender, "_send_chain", fake_send_chain)

    result = await sender.send_to_user(
        SendRequest(
            session_id="default:GroupMessage:1",
            message="entry text",
            prepared_media=[
                PreparedMedia(
                    media_type="video",
                    original_url="https://example.com/2.mp4",
                )
            ],
        ),
        context=MessageContext(
            channel=ChannelInfo(title="Feed Title"),
            platform_name="aiocqhttp",
        ),
    )

    assert result.ok is True
    assert len(calls) == 1
    Nodes = calls[0][0]
    assert isinstance(Nodes, _Nodes)
    nodes = Nodes.nodes
    # 媒体降级为链接：只剩一个文本节点，无视频节点。
    assert len(nodes) == 1
    assert isinstance(nodes[0].content[0], _Plain)
    assert nodes[0].content[0].text.startswith("entry text")
    assert "媒体原始链接:" in nodes[0].content[0].text
    assert "https://example.com/2.mp4" in nodes[0].content[0].text
