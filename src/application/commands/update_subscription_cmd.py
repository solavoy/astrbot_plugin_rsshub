"""
更新订阅选项命令

处理更新订阅配置选项的业务用例。
"""

from ...domain.repositories.subscription_repository import SubscriptionRepository
from ...infrastructure.config import validate_interval_value
from ..dto.result_dto import CommandResult
from ..dto.subscription_dto import SubscriptionDTO

REMOVED_OPTIONS = {
    "translate",
    "translate_target_lang",
    "use_sub_config",
    "ai_prompt",
    "handlers",
    "handlers_mode",
}
STRING_OPTIONS = {
    "title",
    "tags",
    "target_session",
    "platform_name",
}


class UpdateSubscriptionCommand:
    """
    更新订阅选项命令

    处理更新订阅配置选项的业务用例。
    """

    def __init__(self, subscription_repo: SubscriptionRepository):
        self._subscription_repo = subscription_repo

    async def execute(
        self,
        sub_id: int,
        user_id: str,
        **options,
    ) -> CommandResult:
        """
        执行更新命令

        Args:
            sub_id: 订阅 ID
            user_id: 用户 ID
            **options: 要更新的选项

        Returns:
            CommandResult: 命令执行结果
        """
        removed = sorted(REMOVED_OPTIONS.intersection(options))
        if removed:
            return CommandResult(
                success=False,
                message=("订阅选项已移除: " + ", ".join(removed)),
            )
        normalized_options = {}
        for key, value in options.items():
            if key in STRING_OPTIONS:
                normalized_options[key] = str(value or "").strip()
                continue
            if key == "interval":
                try:
                    normalized_options[key] = validate_interval_value(
                        value,
                        allow_inherit=True,
                        field_name="interval",
                    )
                except ValueError as exc:
                    return CommandResult(success=False, message=str(exc))
                continue
            normalized_options[key] = value

        subscription = await self._subscription_repo.update_options(
            sub_id, user_id, **normalized_options
        )
        if not subscription:
            return CommandResult(
                success=False,
                message=f"订阅不存在或无权修改 (ID: {sub_id})",
            )

        return CommandResult(
            success=True,
            message=f"已更新订阅选项 (ID: {sub_id})",
            data=SubscriptionDTO(
                id=subscription.id,
                user_id=subscription.user_id,
                feed_id=subscription.feed_id,
                title=subscription.title,
                tags=subscription.tags,
                target_session=subscription.target_session,
                platform_name=subscription.platform_name,
                state=subscription.state,
                created_at=subscription.created_at,
                updated_at=subscription.updated_at,
            ),
        )
