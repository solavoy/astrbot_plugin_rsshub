"""List 批次聚合领域实体单元测试。"""

from astrbot_plugin_rsshub.src.domain.entities.list_entities import (
    LIST_CONTENT_MODE_FULL,
    LIST_CONTENT_MODE_TITLE_LINK,
    LIST_FULL_DELIVERY_AGGREGATE,
    LIST_FULL_DELIVERY_SPLIT,
    ListBatch,
    ListBatchPart,
    ListBatchPartItem,
    ListEntity,
    ListQueueItem,
    build_entry_key,
    normalize_keywords,
)


def test_normalize_keywords_dedups_case_insensitive_and_strips():
    assert normalize_keywords(["  Python ", "python", " AI ", "", "  ai  "]) == [
        "python",
        "ai",
    ]


def test_build_entry_key_falls_back_to_stable_fingerprint():
    assert build_entry_key(entry_guid="g-1", stable_fingerprint="sid:abc") == "g-1"
    assert build_entry_key(entry_guid="", stable_fingerprint="sid:abc") == "sid:abc"


def test_list_entity_defaults_and_mode_validation():
    lst = ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram")
    assert lst.state == 1 and lst.batch_size == 10 and lst.max_wait_minutes == 120
    assert lst.content_mode == "full" and lst.full_delivery_mode == "split"


def test_list_entity_constants_exist():
    assert LIST_CONTENT_MODE_TITLE_LINK == "title_link"
    assert LIST_CONTENT_MODE_FULL == "full"
    assert LIST_FULL_DELIVERY_SPLIT == "split"
    assert LIST_FULL_DELIVERY_AGGREGATE == "aggregate"


def test_queue_item_unique_key_is_entry_key_based():
    item = ListQueueItem(list_id=1, sub_id=2, feed_id=3, push_history_id=4, entry_key="k")
    assert item.entry_key == "k"
    assert item.state == "queued"


def test_batch_and_part_defaults():
    batch = ListBatch(list_id=1)
    assert batch.state == "preparing"
    assert batch.summary_status == "disabled"
    part = ListBatchPart(batch_id=1, sequence=0, kind="entry")
    assert part.state == "pending"
    part_item = ListBatchPartItem(batch_part_id=1, queue_item_id=2)
    assert part_item.id is None


def test_normalize_keywords_splits_string_input():
    # str 输入按逗号/换行拆分，而不是逐字符
    assert normalize_keywords("python, AI,  python") == ["python", "ai"]
    assert normalize_keywords("linux\npython") == ["linux", "python"]
    assert normalize_keywords("") == []
    assert normalize_keywords(None) == []
