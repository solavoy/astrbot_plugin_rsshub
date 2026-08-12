"""用户仓库实现

基于 SQLModel/SQLAlchemy 实现 UserRepository 接口。
负责用户实体的持久化操作。
"""

from __future__ import annotations

from sqlmodel import select

from ...domain.entities.user import User
from ...domain.repositories.user_repository import UserRepository
from ..utils import get_logger
from .database import get_database
from .models import UserORM

logger = get_logger()


class UserRepositoryImpl:
    """用户仓库实现类"""

    async def get_by_id(self, user_id: str) -> User | None:
        """根据ID获取用户"""
        db = get_database()
        async with db.get_session() as session:
            orm = await session.get(UserORM, user_id)
            return self._to_entity(orm) if orm else None

    async def get_or_create(self, user_id: str) -> User:
        """获取或创建用户"""
        db = get_database()
        async with db.get_session() as session:
            orm = await session.get(UserORM, user_id)
            if not orm:
                orm = UserORM(id=user_id)
                session.add(orm)
                await session.commit()
                await session.refresh(orm)
                logger.info("创建新用户: %s", user_id)
            return self._to_entity(orm)

    async def save(self, user: User) -> User:
        """保存用户"""
        db = get_database()
        async with db.get_session() as session:
            orm = await session.get(UserORM, user.id)
            if orm is None:
                orm = self._to_orm(user)
                session.add(orm)
            else:
                updated_orm = self._to_orm(user)
                orm.state = updated_orm.state
                orm.interval = updated_orm.interval
                orm.notify = updated_orm.notify
                orm.send_mode = updated_orm.send_mode
                orm.length_limit = updated_orm.length_limit
                orm.display_author = updated_orm.display_author
                orm.display_via = updated_orm.display_via
                orm.display_title = updated_orm.display_title
                orm.display_entry_tags = updated_orm.display_entry_tags
                orm.display_media = updated_orm.display_media
                orm.default_target_session = updated_orm.default_target_session
                orm.needs_binding_notice = updated_orm.needs_binding_notice
                orm.created_at = updated_orm.created_at
                orm.updated_at = updated_orm.updated_at
            await session.commit()
            await session.refresh(orm)
            return self._to_entity(orm)

    async def get_all(self, limit: int = 100, offset: int = 0) -> list[User]:
        """获取所有用户"""
        db = get_database()
        async with db.get_session() as session:
            stmt = select(UserORM).offset(offset).limit(limit)
            result = await session.execute(stmt)
            orms = result.scalars().all()
            return [self._to_entity(orm) for orm in orms]

    async def update_defaults(self, user_id: str, **kwargs) -> User | None:
        """更新用户默认配置"""
        db = get_database()
        async with db.get_session() as session:
            orm = await session.get(UserORM, user_id)
            if not orm:
                return None
            for key, value in kwargs.items():
                if hasattr(orm, key):
                    setattr(orm, key, value)
            session.add(orm)
            await session.commit()
            await session.refresh(orm)
            return self._to_entity(orm)

    async def delete(self, user_id: str) -> bool:
        """删除用户"""
        db = get_database()
        async with db.get_session() as session:
            orm = await session.get(UserORM, user_id)
            if not orm:
                return False
            await session.delete(orm)
            await session.commit()
            return True

    @staticmethod
    def _to_entity(orm: UserORM) -> User:
        """将 ORM 模型转换为领域实体"""
        return User(
            id=orm.id,
            state=orm.state,
            interval=orm.interval,
            notify=orm.notify,
            send_mode=orm.send_mode,
            length_limit=orm.length_limit,
            display_author=orm.display_author,
            display_via=orm.display_via,
            display_title=orm.display_title,
            display_entry_tags=orm.display_entry_tags,
            display_media=orm.display_media,
            default_target_session=orm.default_target_session,
            needs_binding_notice=orm.needs_binding_notice,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    @staticmethod
    def _to_orm(user: User) -> UserORM:
        """将领域实体转换为 ORM 模型"""
        return UserORM(
            id=user.id,
            state=user.state,
            interval=user.interval,
            notify=user.notify,
            send_mode=user.send_mode,
            length_limit=user.length_limit,
            display_author=user.display_author,
            display_via=user.display_via,
            display_title=user.display_title,
            display_entry_tags=user.display_entry_tags,
            display_media=user.display_media,
            default_target_session=user.default_target_session,
            needs_binding_notice=user.needs_binding_notice,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )


# 提供 get 方法获取单例
_user_repo_instance: UserRepositoryImpl | None = None


def get_user_repository() -> UserRepository:
    """获取用户仓库实例"""
    global _user_repo_instance
    if _user_repo_instance is None:
        _user_repo_instance = UserRepositoryImpl()
    return _user_repo_instance
