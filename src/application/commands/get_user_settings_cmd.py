"""获取用户设置命令

处理获取用户默认设置的业务用例。
"""

from __future__ import annotations

from ...domain.repositories.user_repository import UserRepository
from ..dto.result_dto import CommandResult


class GetUserSettingsCommand:
    """获取用户设置命令

    处理获取用户默认设置的业务用例。
    """

    def __init__(self, user_repo: UserRepository):
        self._user_repo = user_repo
        self._removed_keys = {
            "translate",
            "translate_target_lang",
            "use_user_config",
            "ai_prompt",
        }

    async def execute(
        self,
        user_id: str,
        key: str | None = None,
    ) -> CommandResult:
        """执行获取用户设置命令

        Args:
            user_id: 用户 ID
            key: 可选的单个配置项名称

        Returns:
            CommandResult: 命令执行结果
        """
        user = await self._user_repo.get_by_id(user_id)
        if not user:
            return CommandResult(
                success=False,
                message=f"用户不存在 (ID: {user_id})",
            )

        if key:
            if key in self._removed_keys:
                return CommandResult(
                    success=False,
                    message=f"配置项 {key} 已移除。",
                )
            # 获取单个配置项
            current_value = getattr(user, key, None)
            return CommandResult(
                success=True,
                message=f"{key} = {current_value if current_value is not None else '未设置'}",
            )

        # 获取所有配置
        settings_map = {
            "state": user.state,
            "interval": user.interval,
            "notify": user.notify,
            "send_mode": user.send_mode,
            "length_limit": user.length_limit,
            "display_author": user.display_author,
            "display_via": user.display_via,
            "display_title": user.display_title,
            "display_entry_tags": user.display_entry_tags,
            "display_media": user.display_media,
            "default_target_session": user.default_target_session,
        }

        lines = ["用户配置:"]
        for k, v in settings_map.items():
            lines.append(f"  {k} = {v if v is not None else '未设置'}")

        return CommandResult(
            success=True,
            message="\n".join(lines),
            data=settings_map,
        )
