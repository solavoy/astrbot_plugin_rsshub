"""List 域名分类纯函数单元测试。"""

from astrbot_plugin_rsshub.src.application.queries.list_domain_util import (
    feed_hostname,
)


def test_feed_hostname_lowercase_ignores_port_and_path():
    assert feed_hostname("https://RSSHub.app/v2ex/topics/latest") == "rsshub.app"
    assert feed_hostname("https://rss.gurify.com:8443/x") == "rss.gurify.com"
    assert feed_hostname("") == "未知域名"


def test_feed_hostname_handles_none_and_malformed():
    assert feed_hostname(None) == "未知域名"
    assert feed_hostname("not a url") == "未知域名"
    assert feed_hostname("http://localhost:8080/feed.xml") == "localhost"
