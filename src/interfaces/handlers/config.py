"""配置相关命令处理器（纯函数）"""

from __future__ import annotations

from astrbot.api.event import AstrMessageEvent

from ...infrastructure.config import validate_interval_value

SESSION_DEFAULT_KV_PREFIX = "rsshub_session_defaults_"
SESSION_DEFAULT_KEYS = {
    "interval",
    "notify",
    "send_mode",
    "length_limit",
    "display_author",
    "display_via",
    "display_title",
    "display_entry_tags",
    "style",
    "display_media",
    "title",
    "tags",
}
REMOVED_KEYS = {
    "translate",
    "translate_target_lang",
    "use_sub_config",
    "use_user_config",
    "ai_prompt",
}


async def handle_sub_set(
    event: AstrMessageEvent, sub_id: int, option: str, value: str, deps: dict
) -> dict:
    """修改订阅配置"""
    if sub_id <= 0 or not option:
        return {
            "plain": "用法: /sub_set <sub_id> <option> <value>\n示例: /sub_set 1 interval 30"
        }
    user_id = event.get_sender_id()
    option_key = option.strip().lower()
    if option_key in REMOVED_KEYS:
        return {"plain": f"选项 {option_key} 已移除。"}
    result = await deps["update_sub_cmd"].execute(
        sub_id=sub_id, user_id=user_id, **{option_key: value}
    )
    return {"plain": result.message}


async def handle_sub_set_user(
    event: AstrMessageEvent, key: str, value: str, deps: dict
) -> dict:
    """设置用户配置"""
    if not key or not value:
        result = await deps["get_user_settings_cmd"].execute(
            user_id=event.get_sender_id()
        )
        return {"plain": result.message}
    user_id = event.get_sender_id()
    result = await deps["set_user_settings_cmd"].execute(
        user_id=user_id,
        key=key.strip().lower(),
        value=value,
    )
    return {"plain": result.message}


async def handle_sub_get_user(event: AstrMessageEvent, key: str, deps: dict) -> dict:
    """获取用户配置"""
    user_id = event.get_sender_id()
    result = await deps["get_user_settings_cmd"].execute(
        user_id=user_id,
        key=key.strip().lower() if key else None,
    )
    return {"plain": result.message}


async def handle_sub_profile_set(
    event: AstrMessageEvent, args: str, deps: dict
) -> dict:
    """统一配置写入入口。

    用法:
    - /sub_profile set sub <sub_id> <option> <value>
    - /sub_profile set user <key> <value>
    """
    parts = [p.strip() for p in (args or "").split() if p.strip()]
    if not parts:
        return {
            "plain": (
                "用法:\n"
                "/sub_profile set sub <sub_id> <option> <value>\n"
                "/sub_profile set user <key> <value>"
            )
        }

    scope = parts[0].lower()
    if scope in {"sub", "subscription"}:
        if len(parts) < 4:
            return {"plain": "用法: /sub_profile set sub <sub_id> <option> <value>"}
        try:
            sub_id = int(parts[1])
        except ValueError:
            return {"plain": "订阅 ID 必须是数字"}
        option = parts[2]
        value = " ".join(parts[3:])
        return await handle_sub_set(event, sub_id, option, value, deps)

    if scope in {"user"}:
        if len(parts) < 3:
            return {"plain": "用法: /sub_profile set user <key> <value>"}
        key = parts[1]
        value = " ".join(parts[2:])
        return await handle_sub_set_user(event, key, value, deps)

    return {"plain": f"未知配置域: {scope}（支持: sub/user）"}


async def handle_sub_profile_get(
    event: AstrMessageEvent, args: str, deps: dict
) -> dict:
    """统一配置查询入口。

    用法:
    - /sub_profile get user [key]
    """
    parts = [p.strip() for p in (args or "").split() if p.strip()]
    if not parts:
        return await handle_sub_get_user(event, "", deps)

    scope = parts[0].lower()
    if scope in {"user"}:
        key = parts[1] if len(parts) >= 2 else ""
        return await handle_sub_get_user(event, key, deps)

    if scope in {"sub", "subscription"}:
        return {
            "plain": "当前暂不支持订阅级 get，请使用 /sub_list 查看订阅，再用 /sub_profile set sub ... 修改。"
        }

    return {"plain": f"未知配置域: {scope}（支持: user）"}


async def handle_sub_set_session(
    event: AstrMessageEvent, key: str, value: str, deps: dict, ctx
) -> dict:
    """设置会话默认配置"""
    if not key or not value:
        return {
            "plain": "用法: /sub_set_session <选项> <值>\n可用选项: interval, notify, send_mode, length_limit, display_title, display_media 等"
        }

    session_id = event.unified_msg_origin
    defaults = await _get_session_defaults(ctx, session_id)

    option_key = key.strip().lower()
    if option_key not in SESSION_DEFAULT_KEYS:
        return {"plain": f"未知选项: {option_key}"}

    parsed_value = value
    if option_key not in {"title", "tags"}:
        try:
            if option_key == "interval":
                parsed_value = validate_interval_value(
                    value,
                    allow_inherit=False,
                    field_name="interval",
                )
            else:
                parsed_value = int(value)
        except ValueError as exc:
            if option_key == "interval":
                return {"plain": str(exc)}
            return {"plain": f"选项 {option_key} 需要数字值"}

    defaults[option_key] = parsed_value
    await _set_session_defaults(ctx, session_id, defaults)
    return {"plain": f"会话默认配置已更新: {option_key} = {parsed_value}"}


async def handle_sub_get_session(
    event: AstrMessageEvent, key: str, deps: dict, ctx
) -> dict:
    """获取会话默认配置"""
    session_id = event.unified_msg_origin
    defaults = await _get_session_defaults(ctx, session_id)

    if not defaults:
        return {"plain": "当前会话未设置任何默认值\n新订阅将继承用户/全局配置"}

    option_key = key.strip().lower() if key else ""
    if option_key:
        return {"plain": f"{option_key} = {defaults.get(option_key, '未设置')}"}
    else:
        lines = ["会话默认配置:"]
        for k, v in defaults.items():
            lines.append(f"  {k} = {v}")
        return {"plain": "\n".join(lines)}


async def _get_session_defaults(ctx, session_id: str) -> dict:
    if not callable(getattr(ctx, "get_kv_data", None)):
        raise TypeError("当前插件上下文不支持会话默认配置存储")
    key = f"{SESSION_DEFAULT_KV_PREFIX}{session_id}"
    raw = await ctx.get_kv_data(key, {})
    if not isinstance(raw, dict):
        return {}
    return raw


async def _set_session_defaults(ctx, session_id: str, defaults: dict):
    if not callable(getattr(ctx, "put_kv_data", None)):
        raise TypeError("当前插件上下文不支持会话默认配置存储")
    key = f"{SESSION_DEFAULT_KV_PREFIX}{session_id}"
    await ctx.put_kv_data(key, defaults)
