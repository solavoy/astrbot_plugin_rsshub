"""订阅与 List 两级关键词过滤服务单元测试。"""

from astrbot_plugin_rsshub.src.application.services.subscription_filter_service import (
    FilterResult,
    SubscriptionFilterService,
)


def test_exclude_wins_over_include():
    svc = SubscriptionFilterService()
    assert not svc.matches(
        text="Python 二手教程", sub_include=["python"], sub_exclude=["二手"]
    ).allowed


def test_layer_include_or_and_across_layers():
    svc = SubscriptionFilterService()
    r = svc.matches(
        text="Python 教程", sub_include=["python"], list_include=["linux"]
    )
    assert not r.allowed and "list include" in r.reason
    assert svc.matches(
        text="Python Linux 教程", sub_include=["python"], list_include=["linux"]
    ).allowed


def test_no_include_is_pass_through_when_no_exclude():
    svc = SubscriptionFilterService()
    assert svc.matches(text="任何内容", sub_include=[], sub_exclude=[]).allowed


def test_case_insensitive_substring():
    svc = SubscriptionFilterService()
    assert svc.matches(text="PythoN 教程", sub_include=["python"]).allowed
    assert not svc.matches(text="Python 教程", sub_exclude=["PYTHON"]).allowed


def test_exclude_at_subscription_level_wins():
    svc = SubscriptionFilterService()
    assert not svc.matches(
        text="xxx 广告 xxx", sub_include=["xxx"], sub_exclude=["广告"]
    ).allowed


def test_list_exclude_wins_over_list_include():
    svc = SubscriptionFilterService()
    assert not svc.matches(
        text="Python 水贴",
        sub_include=[],
        sub_exclude=[],
        list_include=["python"],
        list_exclude=["水贴"],
    ).allowed


def test_filter_result_reason_is_empty_when_allowed():
    svc = SubscriptionFilterService()
    r = svc.matches(text="python", sub_include=["python"])
    assert r.allowed and r.reason == ""
