"""设置用户设置命令

处理设置用户默认配置的业务用例。
"""

from __future__ import annotations

from typing import Any

from ...domain.repositories.user_repository import UserRepository
from ...infrastructure.config import MAX_INTERVAL_MINUTES, validate_interval_value
from ...shared.constants import INHERIT_VALUE
from ..dto.result_dto import CommandResult

# 设置选项的合法值范围
VALID_SETTINGS = {
    "state": (-1, 1),
    "interval": (1, MAX_INTERVAL_MINUTES),  # 分钟
    "notify": (0, 1),
    "send_mode": (-1, 1),  # -1=仅链接, 0=自动, 1=直接发送
    "length_limit": (0, 10000),
    "display_author": (-1, 1),
    "display_via": (-2, 1),
    "display_title": (-1, 1),
    "display_entry_tags": (-1, 1),
    "style": (0, 1),
    "display_media": (-1, 1),
}
INHERITABLE_SETTINGS = set(VALID_SETTINGS) - {"state"}
STRING_SETTINGS = {"default_target_session"}
REMOVED_SETTINGS = {
    "translate",
    "translate_target_lang",
    "use_user_config",
    "ai_prompt",
}


class SetUserSettingsCommand:
    """设置用户设置命令

    处理设置用户默认配置的业务用例。
    """

    def __init__(self, user_repo: UserRepository):
        self._user_repo = user_repo

    async def execute(
        self,
        user_id: str,
        key: str | None = None,
        value: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> CommandResult:
        """执行设置用户设置命令

        Args:
            user_id: 用户 ID
            key: 单个设置项名称（与 settings 二选一）
            value: 单个设置值（与 settings 二选一）
            settings: 批量设置字典（优先）

        Returns:
            CommandResult: 命令执行结果
        """
        # 获取或创建用户
        user = await self._user_repo.get_by_id(user_id)
        if not user:
            from ...domain.entities.user import User

            user = User(id=user_id)

        changes = []

        def _set_one(option_key: str, raw_value: Any) -> CommandResult | None:
            option_key = option_key.strip().lower()
            parsed_value: int | str

            if option_key in REMOVED_SETTINGS:
                return CommandResult(
                    success=False,
                    message=f"选项 {option_key} 已移除。",
                )

            if (
                option_key not in VALID_SETTINGS
                and option_key not in STRING_SETTINGS
            ):
                return CommandResult(
                    success=False,
                    message=f"未知配置项: {option_key}",
                )

            if option_key in STRING_SETTINGS:
                parsed_value = str(raw_value).strip() or None
            else:
                try:
                    parsed_value = int(raw_value)
                except (ValueError, TypeError):
                    return CommandResult(
                        success=False,
                        message=f"选项 {option_key} 需要数字值",
                    )

                if option_key in INHERITABLE_SETTINGS and parsed_value == INHERIT_VALUE:
                    pass
                elif option_key == "interval":
                    try:
                        parsed_value = validate_interval_value(
                            parsed_value,
                            allow_inherit=True,
                            field_name="interval",
                        )
                    except ValueError as exc:
                        return CommandResult(success=False, message=str(exc))
                elif option_key in VALID_SETTINGS:
                    min_val, max_val = VALID_SETTINGS[option_key]
                    if not min_val <= parsed_value <= max_val:
                        return CommandResult(
                            success=False,
                            message=f"{option_key} 的值 {parsed_value} 超出范围 [{min_val}, {max_val}]",
                        )
                    if option_key == "state" and parsed_value == 0:
                        return CommandResult(
                            success=False,
                            message="state 只支持 -1(已封禁) 或 1(用户)",
                        )

            old_value = getattr(user, option_key, None)
            setattr(user, option_key, parsed_value)

            def fmt(val):
                if val is None:
                    return "未设置"
                if isinstance(val, bool) or val in (0, 1, -100, -1, -2):
                    val_map = {
                        0: "禁用",
                        1: "启用",
                        -100: "继承",
                        -1: "禁用",
                        -2: "不显示",
                    }
                    return val_map.get(val, str(val))
                return str(val)

            changes.append(f"{option_key}: {fmt(old_value)} → {fmt(parsed_value)}")
            return None

        if settings:
            for k, v in settings.items():
                err = _set_one(k, v)
                if err:
                    return err
        elif key is not None and value is not None:
            err = _set_one(key, value)
            if err:
                return err
        else:
            return CommandResult(
                success=False, message="请提供 key/value 或 settings 字典"
            )

        await self._user_repo.save(user)
        return CommandResult(
            success=True,
            message="用户配置已更新:\n" + "\n".join(changes),
        )
