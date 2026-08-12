"""
订阅关系领域实体

代表用户与Feed之间的订阅关系，包含推送配置选项。
不包含任何 ORM 或持久化逻辑。
"""

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from ...shared.constants import INHERIT_VALUE


class Subscription(BaseModel):
    """
    订阅关系领域实体

    代表用户与Feed之间的订阅关系，包含推送配置选项。
    """

    model_config = ConfigDict(populate_by_name=True)

    id: int | None = Field(default=None, description="数据库ID")
    state: int = Field(default=1, description="订阅状态: 0=停用, 1=启用")

    user_id: str = Field(..., description="用户ID")
    feed_id: int = Field(..., description="FeedID")

    title: str = Field(default="", max_length=1024, description="订阅标题")
    tags: str = Field(default="", max_length=255, description="标签")
    target_session: str | None = Field(
        default=None, max_length=255, description="推送目标会话(unified_msg_origin)"
    )
    platform_name: str | None = Field(
        default=None, max_length=64, description="平台类型名(如 telegram, aiocqhttp)"
    )

    interval: int = Field(default=INHERIT_VALUE, description="监控间隔（分钟）")
    next_check_time: datetime | None = Field(default=None, description="下次检查时间")

    notify: int = Field(default=INHERIT_VALUE, description="是否通知")
    send_mode: int = Field(
        default=INHERIT_VALUE,
        description="发送模式: -100=继承, -1=仅链接, 0=自动, 1=直接发送",
    )
    length_limit: int = Field(default=INHERIT_VALUE, description="长度限制")
    display_author: int = Field(default=INHERIT_VALUE, description="显示作者")
    display_via: int = Field(default=INHERIT_VALUE, description="显示来源")
    display_title: int = Field(default=INHERIT_VALUE, description="显示标题")
    display_entry_tags: int = Field(default=INHERIT_VALUE, description="显示标签")
    display_media: int = Field(default=INHERIT_VALUE, description="显示媒体")

    list_id: int | None = Field(default=None, description="所属 List ID")
    include_keywords: list[str] | None = Field(default=None, description="订阅关注词")
    exclude_keywords: list[str] | None = Field(default=None, description="订阅屏蔽词")

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), description="创建时间"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), description="更新时间"
    )

    def is_active(self) -> bool:
        """检查订阅是否启用"""
        return self.state == 1

    def enable(self) -> "Subscription":
        """启用订阅"""
        self.state = 1
        self.updated_at = datetime.now(timezone.utc)
        return self

    def disable(self) -> "Subscription":
        """禁用订阅"""
        self.state = 0
        self.updated_at = datetime.now(timezone.utc)
        return self

    def set_target_session(self, session: str) -> "Subscription":
        """设置推送目标会话"""
        self.target_session = session
        self.updated_at = datetime.now(timezone.utc)
        return self

    def get_effective_option(self, key: str) -> int | str | None:
        """
        获取生效的配置选项值（不处理继承逻辑，仅返回自身值）

        完整的继承解析应由应用层负责。

        Args:
            key: 选项名称

        Returns:
            选项值，如果为继承值则返回None
        """
        if not hasattr(self, key):
            return None
        value = getattr(self, key)
        if value == INHERIT_VALUE:
            return None
        return value
