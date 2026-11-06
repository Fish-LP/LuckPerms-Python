"""
LuckPermsAPI 统一管理层。

提供 User / Group / Track 的 CRUD、权限检查、持久化，
以及官方 Web Editor 兼容的序列化/反序列化。
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .constants import (
    CUSTOM_META_PREFIX,
    DEFAULT_GROUP_NAME,
    DEFAULT_TEMP_MODIFIER,
    GROUP_NODE_PREFIX,
    PLUGIN_VERSION,
    TEMP_MODIFIERS,
    WEIGHT_NODE_PREFIX,
)
from .models import Group, Node, PermissionHolder, Track, User
from .query import PermissionQuery
from .storage import LuckPermsStorage, StorageBackend, YAMLBackend

log = logging.getLogger("luckperms.manager")


class LuckPermsManager:
    """LuckPerms 统一管理层。

    Args:
        data_dir: 数据目录路径。
        backend: 存储后端，默认 YAMLBackend。
    """

    def __init__(
        self,
        data_dir: Path | str,
        backend: Optional[StorageBackend] = None,
    ):
        self._data_dir = Path(data_dir)
        self._storage = LuckPermsStorage(self._data_dir, backend or YAMLBackend())
        self._users: Dict[str, User] = {}
        self._groups: Dict[str, Group] = {}
        self._tracks: Dict[str, Track] = {}
        self._query: PermissionQuery = PermissionQuery(self._users, self._groups)
        self._verbose_user: Optional[str] = None
        self._verbose_callback: Optional[
            Callable[[str, str, Optional[Dict[str, Any]], bool], None]
        ] = None
        self._load_all()

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    def _load_all(self) -> None:
        # 彻底重载：先清空内存，避免磁盘上已删除的实体在 sync 后残留
        self._users.clear()
        self._groups.clear()
        self._tracks.clear()
        raw_users, raw_groups, raw_tracks = self._storage.load_all()
        for uid, d in raw_users.items():
            self._users[uid] = User.from_dict(d)
        for name, d in raw_groups.items():
            self._groups[name] = Group.from_dict(d)
        for name, d in raw_tracks.items():
            self._tracks[name] = Track.from_dict(d)
        self._query = PermissionQuery(self._users, self._groups)
        log.debug(
            "loaded from disk: users=%d groups=%d tracks=%d",
            len(self._users),
            len(self._groups),
            len(self._tracks),
        )

    def _save_all(self) -> None:
        # 自动清理所有过期节点
        for u in self._users.values():
            u.cleanup_expired_nodes()
        for g in self._groups.values():
            g.cleanup_expired_nodes()

        # 过滤默认用户，不持久化以节省存储空间
        users = {uid: u.to_dict() for uid, u in self._users.items() if not u.is_default}
        groups = {name: g.to_dict() for name, g in self._groups.items()}
        tracks = {name: t.to_dict() for name, t in self._tracks.items()}
        self._storage.save_all(users, groups, tracks)
        log.debug(
            "saved to disk: users=%d(default_skipped=%d) groups=%d tracks=%d",
            len(users),
            len(self._users) - len(users),
            len(groups),
            len(tracks),
        )

    @staticmethod
    def _node_to_webeditor(node: Node) -> dict[str, Any]:
        """将 Node 序列化为 Web Editor 兼容格式（expiry 为秒）。"""
        d: dict[str, Any] = {
            "type": "permission",  # FIX: 添加 type 字段
            "key": node.key,
            "value": node.value,
        }
        if node.context:
            d["context"] = {k: list(v) for k, v in node.context.items()}
        if node.expiry is not None:
            d["expiry"] = int(node.expiry)  # FIX: 官方使用秒级时间戳，不要 *1000
        return d

    @staticmethod
    def _node_from_webeditor(data: dict[str, Any]) -> Node:
        """从 Web Editor 格式反序列化 Node（expiry 为秒）。"""
        expiry = data.get("expiry")
        context = Node.normalize_context(data.get("context", {}))

        # FIX: 防止 Web Editor 把 value 传成 "" 或其他非布尔值
        raw_value = data.get("value", True)
        if isinstance(raw_value, bool):
            value = raw_value
        elif isinstance(raw_value, str):
            value = raw_value.lower() in ("true", "t", "1", "yes", "on")
        else:
            value = bool(raw_value)

        return Node(
            key=data["key"],
            value=value,
            context=context,
            expiry=expiry,
        )

    def _clean_group_refs(self, name: str) -> None:
        """删除组后清理所有引用（含临时继承节点）。"""
        for u in self._users.values():
            if name in u.parents:
                u.remove_parent(name)
            u.remove_temp_parent(name)
        for g in self._groups.values():
            if name in g.parents:
                g.remove_parent(name)
            g.remove_temp_parent(name)
        for t in self._tracks.values():
            if name in t.groups:
                t.remove_group(name)

    def _get_holder(self, holder_id: str, is_group: bool = False) -> PermissionHolder:
        """按 ID / 组名获取权限持有者。

        Raises:
            KeyError: 持有者不存在。
        """
        holder: Optional[PermissionHolder]
        holder = self._groups.get(holder_id) if is_group else self._users.get(holder_id)
        if holder is None:
            raise KeyError(f"{'组' if is_group else '用户'} '{holder_id}' 不存在")
        return holder

    def _resolve_temp_expiry(
        self,
        holder: PermissionHolder,
        key: str,
        context: Optional[Dict[str, Any]],
        duration: int,
        modifier: str,
    ) -> float:
        """按临时修饰符计算节点的过期时间戳。

        Args:
            holder: 权限持有者。
            key: 节点 key。
            context: 上下文。
            duration: 相对秒数（必须为正）。
            modifier: ``accumulate`` / ``replace`` / ``deny``。

        Return:
            过期时间戳（秒）。

        Raises:
            ValueError: modifier 非法，或 ``deny`` 模式下已存在临时节点。
        """
        if modifier not in TEMP_MODIFIERS:
            raise ValueError(
                f"未知的临时修饰符: {modifier}（可选: {', '.join(TEMP_MODIFIERS)}）"
            )

        now = time.time()
        new_expiry = now + duration
        existing = holder.get_node(key, context)
        existing_expiry = existing.expiry if existing is not None else None

        if existing_expiry is None:
            return new_expiry
        if modifier == "accumulate":
            return max(now, existing_expiry) + duration
        if modifier == "replace":
            return max(existing_expiry, new_expiry)
        raise ValueError(f"节点已存在临时值（deny 模式）: {key}")

    # ------------------------------------------------------------------
    # User CRUD
    # ------------------------------------------------------------------
    def create_user(self, unique_id: str, display_name: Optional[str] = None) -> User:
        if unique_id in self._users:
            raise ValueError(f"用户 '{unique_id}' 已存在")
        user = User(unique_id, display_name or unique_id)
        if DEFAULT_GROUP_NAME in self._groups:
            user.add_parent(DEFAULT_GROUP_NAME)
        self._users[unique_id] = user
        self._save_all()
        return user

    def get_user(self, unique_id: str) -> Optional[User]:
        return self._users.get(unique_id)

    def delete_user(self, unique_id: str) -> bool:
        if unique_id not in self._users:
            return False
        del self._users[unique_id]
        self._save_all()
        return True

    def list_users(self) -> List[User]:
        return list(self._users.values())

    # ------------------------------------------------------------------
    # Group CRUD
    # ------------------------------------------------------------------
    def create_group(
        self,
        name: str,
        display_name: Optional[str] = None,
        weight: int = 0,
    ) -> Group:
        if name in self._groups:
            raise ValueError(f"组 '{name}' 已存在")
        group = Group(name, display_name or name, weight=weight)
        self._groups[name] = group
        self._save_all()
        return group

    def get_group(self, name: str) -> Optional[Group]:
        return self._groups.get(name)

    def delete_group(self, name: str) -> bool:
        if name not in self._groups:
            return False
        del self._groups[name]
        self._clean_group_refs(name)
        self._save_all()
        return True

    def list_groups(self) -> List[Group]:
        return list(self._groups.values())

    # ------------------------------------------------------------------
    # Track CRUD
    # ------------------------------------------------------------------
    def create_track(self, name: str, groups: Optional[List[str]] = None) -> Track:
        if name in self._tracks:
            raise ValueError(f"轨道 '{name}' 已存在")
        track = Track(name, groups or [])
        self._tracks[name] = track
        self._save_all()
        return track

    def get_track(self, name: str) -> Optional[Track]:
        return self._tracks.get(name)

    def delete_track(self, name: str) -> bool:
        if name not in self._tracks:
            return False
        del self._tracks[name]
        self._save_all()
        return True

    def list_tracks(self) -> List[Track]:
        return list(self._tracks.values())

    # ------------------------------------------------------------------
    # 节点与继承管理
    # ------------------------------------------------------------------
    def user_add_node(
        self,
        unique_id: str,
        key: str,
        value: bool = True,
        context: Optional[Dict[str, Any]] = None,
        duration: Optional[int] = None,
        modifier: str = DEFAULT_TEMP_MODIFIER,
    ) -> None:
        """为用户添加权限节点；``duration`` 为 None 时永久有效。"""
        user = self._users[unique_id]
        expiry = (
            self._resolve_temp_expiry(user, key, context, duration, modifier)
            if duration is not None
            else None
        )
        user.add_node(Node(key, value, context or {}, expiry))
        self._save_all()

    def user_remove_node(
        self, unique_id: str, key: str, context: Optional[Dict[str, Any]] = None
    ) -> bool:
        user = self._users[unique_id]
        result = user.remove_node(key, context)
        self._save_all()
        return result

    def group_add_node(
        self,
        name: str,
        key: str,
        value: bool = True,
        context: Optional[Dict[str, Any]] = None,
        duration: Optional[int] = None,
        modifier: str = DEFAULT_TEMP_MODIFIER,
    ) -> None:
        """为组添加权限节点；``duration`` 为 None 时永久有效。"""
        group = self._groups[name]
        expiry = (
            self._resolve_temp_expiry(group, key, context, duration, modifier)
            if duration is not None
            else None
        )
        group.add_node(Node(key, value, context or {}, expiry))
        self._save_all()

    def group_remove_node(
        self, name: str, key: str, context: Optional[Dict[str, Any]] = None
    ) -> bool:
        group = self._groups[name]
        result = group.remove_node(key, context)
        self._save_all()
        return result

    def user_add_group(
        self,
        unique_id: str,
        group_name: str,
        duration: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None,
        modifier: str = DEFAULT_TEMP_MODIFIER,
    ) -> None:
        """为用户添加父组；``duration`` 指定时添加临时继承。"""
        if group_name not in self._groups:
            raise KeyError(f"组 '{group_name}' 不存在")
        if unique_id not in self._users:
            raise KeyError(f"用户 '{unique_id}' 不存在")
        user = self._users[unique_id]
        if duration is None:
            user.add_parent(group_name)
        else:
            key = f"{GROUP_NODE_PREFIX}{group_name}"
            expiry = self._resolve_temp_expiry(user, key, context, duration, modifier)
            user.add_temp_parent(group_name, expiry, context)
        self._save_all()

    def user_remove_group(self, unique_id: str, group_name: str) -> None:
        """移除用户父组（同时清理永久与临时继承）。"""
        user = self._users[unique_id]
        user.remove_parent(group_name)
        user.remove_temp_parent(group_name)
        self._save_all()

    def group_inherit(
        self,
        name: str,
        parent_name: str,
        duration: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None,
        modifier: str = DEFAULT_TEMP_MODIFIER,
    ) -> None:
        """为组添加继承；``duration`` 指定时添加临时继承。"""
        if name == parent_name:
            raise ValueError("不能继承自身")
        if name not in self._groups or parent_name not in self._groups:
            raise KeyError("组不存在")

        # 循环继承检测
        visited: set[str] = set()
        queue = [parent_name]
        while queue:
            cur = queue.pop(0)
            if cur == name:
                raise ValueError("循环继承")
            if cur in visited:
                continue
            visited.add(cur)
            g = self._groups.get(cur)
            if g:
                queue.extend(g.parents)

        group = self._groups[name]
        if duration is None:
            group.add_parent(parent_name)
        else:
            key = f"{GROUP_NODE_PREFIX}{parent_name}"
            expiry = self._resolve_temp_expiry(group, key, context, duration, modifier)
            group.add_temp_parent(parent_name, expiry, context)
        self._save_all()

    def group_remove_inherit(self, name: str, parent_name: str) -> None:
        """移除组继承（同时清理永久与临时继承）。"""
        group = self._groups[name]
        group.remove_parent(parent_name)
        group.remove_temp_parent(parent_name)
        self._save_all()

    # ------------------------------------------------------------------
    # 清理 / 元数据 / 组与轨道辅助
    # ------------------------------------------------------------------
    def clear_permissions(self, holder_id: str, is_group: bool = False) -> int:
        """清空持有者的所有权限节点。Return: 移除的节点数。"""
        holder = self._get_holder(holder_id, is_group)
        removed = len(holder.nodes)
        holder.clear_nodes()
        self._save_all()
        return removed

    def clear_parents(
        self,
        holder_id: str,
        is_group: bool = False,
        keep_default: bool = True,
    ) -> int:
        """清空持有者的所有父组（含临时继承节点）。

        Args:
            holder_id: 用户 ID 或组名。
            is_group: 是否为组。
            keep_default: 用户是否重新加回 default 组（原版行为）。

        Return:
            移除的父组数量（含临时继承节点）。
        """
        holder = self._get_holder(holder_id, is_group)
        removed = len(holder.parents)
        holder.clear_parents()
        removed += holder.remove_nodes_by_prefix(GROUP_NODE_PREFIX)
        if keep_default and not is_group and DEFAULT_GROUP_NAME in self._groups:
            holder.add_parent(DEFAULT_GROUP_NAME)
        self._save_all()
        return removed

    def get_meta(
        self, holder_id: str, meta_type: str, is_group: bool = False
    ) -> Optional[str]:
        """读取持有者的元数据值。"""
        return self._get_holder(holder_id, is_group).get_meta(meta_type)

    def set_meta(
        self,
        holder_id: str,
        meta_type: str,
        value: str,
        priority: int = 0,
        is_group: bool = False,
        context: Optional[Dict[str, Any]] = None,
        duration: Optional[int] = None,
        modifier: str = DEFAULT_TEMP_MODIFIER,
    ) -> str:
        """设置元数据节点。Return: 节点 key。

        Args:
            holder_id: 用户 ID 或组名。
            meta_type: ``prefix`` / ``suffix`` / ``displayname`` / ``weight`` 或自定义 key。
            value: 元数据值。
            priority: 优先级（prefix / suffix 生效）。
            is_group: 是否为组。
            context: 上下文。
            duration: 相对秒数；None 永久。
            modifier: 临时修饰符。
        """
        holder = self._get_holder(holder_id, is_group)
        key = self.meta_node_key(meta_type, value, priority)
        expiry = (
            self._resolve_temp_expiry(holder, key, context, duration, modifier)
            if duration is not None
            else None
        )
        holder.add_node(Node(key, True, context or {}, expiry))
        self._save_all()
        return key

    def unset_meta(
        self,
        holder_id: str,
        meta_type: str,
        priority: Optional[int] = None,
        value: Optional[str] = None,
        is_group: bool = False,
        context: Optional[Dict[str, Any]] = None,
    ) -> int:
        """移除元数据节点。Return: 移除数量。

        prefix / suffix 在未指定 priority 与 value 时移除该类型全部节点。
        """
        holder = self._get_holder(holder_id, is_group)
        if meta_type in ("prefix", "suffix") and (priority is None or value is None):
            removed = holder.remove_nodes_by_prefix(f"{meta_type}.")
        elif (
            meta_type not in ("prefix", "suffix", "displayname", "weight")
            and value is None
        ):
            removed = holder.remove_nodes_by_prefix(f"{CUSTOM_META_PREFIX}{meta_type}.")
        else:
            key = self.meta_node_key(meta_type, value or "", priority or 0)
            removed = 1 if holder.remove_node(key, context) else 0
        self._save_all()
        return removed

    @staticmethod
    def meta_node_key(meta_type: str, value: str, priority: int = 0) -> str:
        """构造元数据节点 key（与原版格式一致）。"""
        if meta_type in ("prefix", "suffix"):
            return f"{meta_type}.{priority}.{value}"
        if meta_type in ("displayname", "weight"):
            return f"{meta_type}.{value}"
        return f"{CUSTOM_META_PREFIX}{meta_type}.{value}"

    def list_group_members(self, name: str) -> List[str]:
        """列出直接继承该组的用户 ID（含临时继承）。"""
        if name not in self._groups:
            raise KeyError(f"组 '{name}' 不存在")
        members: List[str] = []
        for uid, user in self._users.items():
            if name in user.parents or name in user.temp_parents:
                members.append(uid)
        return sorted(members)

    def set_group_display_name(self, name: str, display_name: str) -> None:
        """设置组显示名（写入 displayname 节点，兼容 Web Editor）。"""
        self.set_meta(name, "displayname", display_name, is_group=True)

    def clear_track(self, name: str) -> int:
        """清空轨道中的组。Return: 移除数量。"""
        track = self._tracks.get(name)
        if track is None:
            raise KeyError(f"轨道 '{name}' 不存在")
        removed = len(track.groups)
        track.set_groups([])
        self._save_all()
        return removed

    def rename_track(self, name: str, new_name: str) -> None:
        """重命名轨道。"""
        if name not in self._tracks:
            raise KeyError(f"轨道 '{name}' 不存在")
        if new_name in self._tracks:
            raise ValueError(f"轨道 '{new_name}' 已存在")
        track = self._tracks.pop(name)
        track.name = new_name
        self._tracks[new_name] = track
        self._save_all()

    def user_show_tracks(self, unique_id: str) -> List[tuple[str, int]]:
        """返回用户在各轨道中的位置 ``[(轨道名, 1 起始的序号)]``。"""
        user = self._users.get(unique_id)
        if user is None:
            raise KeyError(f"用户 '{unique_id}' 不存在")
        result: List[tuple[str, int]] = []
        for name, track in self._tracks.items():
            indices = [i for i, g in enumerate(track.groups) if g in user.parents]
            if indices:
                result.append((name, max(indices) + 1))
        return result

    # ------------------------------------------------------------------
    # 权限查询
    # ------------------------------------------------------------------
    def check(
        self,
        unique_id: str,
        permission: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """检查持有者是否拥有指定权限。

        NOTE: 会创建临时用户对象

        Args:
            holder_id: 用户唯一 ID。
            permission: 权限字符串。
            context: 查询上下文，如 ``{"group_id": "123456"}``。

        Return:
            若显式允许返回 True，显式拒绝或无任何匹配返回 False。
        """

        user = self._users.get(unique_id)
        if user is None:
            # 为未持久化的用户创建临时默认用户对象
            # 使其能继承 default 组权限，同时不占用存储空间
            user = User(unique_id, unique_id)
            if DEFAULT_GROUP_NAME in self._groups:
                user.add_parent(DEFAULT_GROUP_NAME)
        result = self._query.check_user(user, permission, context)
        if self._verbose_user == unique_id and self._verbose_callback is not None:
            self._verbose_callback(unique_id, permission, context, result)
        return result

    def check_group(
        self,
        name: str,
        permission: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        return self._query.check_group(name, permission, context)

    def set_verbose(
        self,
        unique_id: Optional[str],
        callback: Optional[
            Callable[[str, str, Optional[Dict[str, Any]], bool], None]
        ] = None,
    ) -> None:
        """开启/关闭权限检查监听（verbose）。

        Args:
            unique_id: 监听的目标用户 ID；None 表示关闭。
            callback: 每次检查后调用
                ``callback(user_id, permission, context, result)``。
        """
        self._verbose_user = unique_id
        self._verbose_callback = callback

    # ------------------------------------------------------------------
    # 晋升轨道
    # ------------------------------------------------------------------
    def promote(self, unique_id: str, track_name: str) -> Optional[str]:
        user = self._users.get(unique_id)
        track = self._tracks.get(track_name)
        if not user or not track:
            return None

        # 找到用户在 track 中的所有组
        current_indices = [
            i for i, gname in enumerate(track.groups) if gname in user.parents
        ]

        if not current_indices:
            # 不在轨道上，加入第一级
            if track.groups:
                user.add_parent(track.groups[0])
                self._save_all()
                return track.groups[0]
            return None

        current_max = max(current_indices)
        next_idx = current_max + 1
        if next_idx >= len(track.groups):
            return None  # 已在最高级

        # 清理轨道上所有旧组（原版行为）
        for idx in current_indices:
            user.remove_parent(track.groups[idx])

        user.add_parent(track.groups[next_idx])
        self._save_all()
        return track.groups[next_idx]

    def demote(self, unique_id: str, track_name: str) -> Optional[str]:
        user = self._users.get(unique_id)
        track = self._tracks.get(track_name)
        if not user or not track:
            return None

        # 找到用户在 track 中的所有组
        current_indices = [
            i for i, gname in enumerate(track.groups) if gname in user.parents
        ]
        if not current_indices:
            return None

        current_max = max(current_indices)

        # 清理轨道上所有旧组
        for idx in current_indices:
            user.remove_parent(track.groups[idx])

        if current_max <= 0:
            # 在第一级或以下，降级后移除所有轨道组（已完成清理）
            self._save_all()
            return None

        prev_group = track.groups[current_max - 1]
        user.add_parent(prev_group)
        self._save_all()
        return prev_group

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def save_all(self) -> None:
        self._save_all()

    # ------------------------------------------------------------------
    # Web Editor 序列化（官方格式兼容）
    # ------------------------------------------------------------------
    def to_webeditor_payload(self) -> dict[str, Any]:
        """生成官方 Web Editor 兼容的 payload。"""
        permission_holders: list[dict[str, Any]] = []

        for user in self._users.values():
            if user.is_default:
                continue
            holder: dict[str, Any] = {
                "type": "user",
                "id": user.unique_id,
                "displayName": user.display_name,
                "nodes": [
                    self._node_to_webeditor(n) for n in user.nodes if not n.is_expired()
                ],
                "parents": list(user.parents),
            }
            permission_holders.append(holder)

        for group in self._groups.values():
            holder: dict[str, Any] = {
                "type": "group",
                "id": group.name,
                "displayName": group.display_name,
                "nodes": [
                    self._node_to_webeditor(n)
                    for n in group.nodes
                    if not n.is_expired()
                ],
                "parents": list(group.parents),
            }
            # 如果节点中已含 weight 节点，不再重复输出 weight 字段
            has_weight_node = any(
                n.key.startswith(WEIGHT_NODE_PREFIX) for n in group.nodes
            )
            if not has_weight_node and group.weight != 0:
                holder["weight"] = group.weight
            permission_holders.append(holder)

        tracks = []
        for track in self._tracks.values():
            tracks.append(
                {
                    "type": "track",
                    "id": track.name,
                    "groups": list(track.groups),
                }
            )

        # 收集所有已知权限和上下文
        known_perms: set[str] = set()
        potential_ctxs: dict[str, set[str]] = {}
        holders = list(self._users.values()) + list(self._groups.values())
        holder_obj: Group | User
        for holder_obj in holders:
            for node in holder_obj.nodes:
                known_perms.add(node.key)
                for k, v in node.context.items():
                    s = potential_ctxs.setdefault(k, set())
                    if isinstance(v, (list, tuple, set)):
                        s.update(str(x) for x in v)
                    else:
                        s.add(str(v))

        payload: dict[str, Any] = {
            "metadata": {
                "commandAlias": "lp",
                "uploader": {
                    "name": "Console",
                    "uuid": str(uuid.uuid4()),
                },
                "time": int(time.time() * 1000),
                "pluginVersion": PLUGIN_VERSION,
                "platform": "Python",
            },
            "permissionHolders": permission_holders,
            "tracks": tracks,
            "knownPermissions": sorted(known_perms),
            "potentialContexts": {k: sorted(v) for k, v in potential_ctxs.items()},
        }
        return payload

    def apply_webeditor_changes(self, payload: dict[str, Any]) -> None:
        """应用官方 Web Editor 返回的变更 payload。

        支持两种格式：
        1. 全量格式: {permissionHolders: [...], tracks: [...]}
        2. 增量格式: {sessionId, changes: [...], groupDeletions, trackDeletions, userDeletions}

        Args:
            payload: 官方格式的权限数据。
        """
        log.debug("[apply_webeditor_changes] payload keys: %s", list(payload.keys()))

        # 判断是增量格式还是全量格式
        if "changes" in payload:
            self._apply_delta_changes(payload)
        else:
            self._apply_full_changes(payload)

    def _apply_delta_changes(self, payload: dict[str, Any]) -> None:
        """应用增量变更（Web Editor Save 后的实际格式）。

        Args:
            payload: 官方 Web Editor 返回的增量数据。
        """
        changes = payload.get("changes", [])
        group_deletions = payload.get("groupDeletions", [])
        track_deletions = payload.get("trackDeletions", [])
        user_deletions = payload.get("userDeletions", [])

        log.debug(
            "[apply_delta] changes=%d groupDel=%s trackDel=%s userDel=%s",
            len(changes),
            group_deletions,
            track_deletions,
            user_deletions,
        )

        # 1. 处理删除
        for gid in group_deletions:
            if gid in self._groups:
                del self._groups[gid]
                self._clean_group_refs(gid)
                log.debug("[apply_delta] deleted group: %s", gid)

        for tid in track_deletions:
            if tid in self._tracks:
                del self._tracks[tid]
                log.debug("[apply_delta] deleted track: %s", tid)

        for uid in user_deletions:
            if uid in self._users:
                del self._users[uid]
                log.debug("[apply_delta] deleted user: %s", uid)

        # 2. 处理变更（新增/更新）
        for change in changes:
            ctype = change.get("type")
            cid = change.get("id")
            if not ctype or not cid:
                log.warning("[apply_delta] skip invalid change: %s", change)
                continue

            # FIX: 使用 _node_from_webeditor 统一转换 context（兼容 list 值）
            nodes = []
            for n in change.get("nodes", []):
                node = self._node_from_webeditor(n)
                nodes.append(
                    {
                        "key": node.key,
                        "value": node.value,
                        "context": node.context,
                        "expiry": node.expiry,
                    }
                )

            if ctype == "group":
                d = {
                    "type": "group",
                    "id": cid,
                    "displayName": change.get("displayName", cid),
                    "weight": change.get("weight", 0),
                    "nodes": nodes,
                    "parents": change.get("parents", []),
                }
                g = Group.from_dict(d)
                self._groups[g.name] = g
                log.debug(
                    "[apply_delta] upserted group: %s (nodes=%d parents=%s)",
                    g.name,
                    len(g.nodes),
                    g.parents,
                )

            elif ctype == "user":
                d = {
                    "type": "user",
                    "id": cid,
                    "displayName": change.get("displayName", cid),
                    "nodes": nodes,
                    "parents": change.get("parents", []),
                }
                u = User.from_dict(d)
                self._users[u.unique_id] = u
                log.debug(
                    "[apply_delta] upserted user: %s (nodes=%d parents=%s)",
                    u.unique_id,
                    len(u.nodes),
                    u.parents,
                )

            elif ctype == "track":
                d = {
                    "name": cid,
                    "groups": change.get("groups", []),
                }
                t = Track.from_dict(d)
                self._tracks[t.name] = t
                log.debug(
                    "[apply_delta] upserted track: %s (groups=%d)",
                    t.name,
                    len(t.groups),
                )

        self._query = PermissionQuery(self._users, self._groups)
        self._save_all()
        log.info(
            "[apply_delta] applied: users=%d groups=%d tracks=%d",
            len(self._users),
            len(self._groups),
            len(self._tracks),
        )

    def _apply_full_changes(self, payload: dict[str, Any]) -> None:
        """应用全量变更（旧版 / 直接上传格式）。

        Args:
            payload: 官方格式的全量权限数据。
        """
        # 清空现有数据
        self._users.clear()
        self._groups.clear()
        self._tracks.clear()

        holders = payload.get("permissionHolders", [])
        tracks_raw = payload.get("tracks", [])

        log.debug("[apply_full] holders=%d tracks=%d", len(holders), len(tracks_raw))

        # 第一轮：提取组
        for h in holders:
            if h.get("type") == "group":
                # FIX: 统一转换节点，兼容 Web Editor 的 list context
                nodes = []
                for n in h.get("nodes", []):
                    node = self._node_from_webeditor(n)
                    nodes.append(
                        {
                            "key": node.key,
                            "value": node.value,
                            "context": node.context,
                            "expiry": node.expiry,
                        }
                    )
                d = {
                    "type": "group",
                    "id": h["id"],
                    "displayName": h.get("displayName", h["id"]),
                    "weight": h.get("weight", 0),
                    "nodes": nodes,
                    "parents": h.get("parents", []),
                }
                g = Group.from_dict(d)
                self._groups[g.name] = g

        # 第二轮：提取用户
        for h in holders:
            if h.get("type") == "user":
                # FIX: 统一转换节点，兼容 Web Editor 的 list context
                nodes = []
                for n in h.get("nodes", []):
                    node = self._node_from_webeditor(n)
                    nodes.append(
                        {
                            "key": node.key,
                            "value": node.value,
                            "context": node.context,
                            "expiry": node.expiry,
                        }
                    )
                d = {
                    "type": "user",
                    "id": h["id"],
                    "displayName": h.get("displayName", h["id"]),
                    "nodes": nodes,
                    "parents": h.get("parents", []),
                }
                u = User.from_dict(d)
                self._users[u.unique_id] = u

        # 解析轨道
        for t in tracks_raw:
            d = {
                "name": t.get("id", t.get("name", "")),
                "groups": t.get("groups", []),
            }
            track = Track.from_dict(d)
            self._tracks[track.name] = track

        self._query = PermissionQuery(self._users, self._groups)
        self._save_all()
        log.info(
            "[apply_full] applied: users=%d groups=%d tracks=%d",
            len(self._users),
            len(self._groups),
            len(self._tracks),
        )
