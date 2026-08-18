"""微信 Official Account 消息发送器。

微信官方号已并入统一发送管线（正文→媒体→尾一条链），不再媒体优先拆发；
本类为空壳，继承 `DefaultMessageSender` 的全部行为。
"""

from __future__ import annotations

from .base_sender import DefaultMessageSender


class WeixinOCMessageSender(DefaultMessageSender):
    """微信 Official Account 发送器（走统一骨架）。"""
