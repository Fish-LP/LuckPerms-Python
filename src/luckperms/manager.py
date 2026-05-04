"""
LuckPermsAPI 权限管理器。

提供用户、组、轨道的 CRUD，权限查询，以及 Web Editor 数据序列化。
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

from .models import Group, Node, Track, User
from .query import PermissionQuery
from .storage import LuckPermsStorage, StorageBackend

log = logging.getLogger("luckperms")


class LuckPermsManager:
    """权限管理器。

    Args:
        data_dir: 数据目录路径。
        backend: 可选自定义存储后端。
    """

    def __init__(
        self,
        data_dir: Path | str,
        backend: Optional[StorageBackend] = None,
    ):
        self._storage = LuckPermsStorage(Path(data_dir), backend)
        self._users: Dict[str, User] = {}
        self._groups: Dict[str, Group] = {}
        self._tracks: Dict[str, Track] = {}
        self._query: Optional[PermissionQuery] = None
        self._load_all()

    # ==================== 加载 / 保存 ====================

    def _load_all(self) -> None:
        raw_users, raw_groups, raw_tracks = self._storage.load_all()
        self._users = {k: User.from_dict(v) for k, v in raw_users.items()}
        self._groups = {k: Group.from_dict(v) for k, v in raw_groups.items()}
        self._tracks = {k: Track.from_dict(v) for k, v in raw_tracks.items()}
        self._query = PermissionQuery(self._users, self._groups)
        log.info(
            "LuckPermsManager 已加载: %d users, %d groups, %d tracks",
            len(self._users), len(self._groups), len(self._tracks),
        )

    def save_all(self) -> None:
        raw_users = {k: v.to_dict() for k, v in self._users.items()}
        raw_groups = {k: v.to_dict() for k, v in self._groups.items()}
        raw_tracks = {k: v.to_dict() for k, v in self._tracks.items()}
        self._storage.save_all(raw_users, raw_groups, raw_tracks)
        log.debug("LuckPermsManager 数据已保存")

    # ==================== 用户管理 ====================

    def get_user(self, unique_id: str) -> Optional[User]:
        return self._users.get(unique_id)

    def create_user(self, unique_id: str, display_name: str = "") -> User:
        if unique_id in self._users:
            raise ValueError(f"用户 {unique_id} 已存在")
        user = User(unique_id, display_name)
        # 自动加入 default 组（若存在）
        if "default" in self._groups:
            user.add_parent("default")
        self._users[unique_id] = user
        self.save_all()
        return user

    def delete_user(self, unique_id: str) -> bool:
        if unique_id not in self._users:
            return False
        del self._users[unique_id]
        self.save_all()
        return True

    def list_users(self) -> List[User]:
        return list(self._users.values())

    # ==================== 组管理 ====================

    def get_group(self, name: str) -> Optional[Group]:
        return self._groups.get(name)

    def create_group(self, name: str, display_name: str = "", weight: int = 0) -> Group:
        if name in self._groups:
            raise ValueError(f"组 {name} 已存在")
        group = Group(name, display_name, weight)
        self._groups[name] = group
        self.save_all()
        return group

    def delete_group(self, name: str) -> bool:
        if name not in self._groups:
            return False
        # 清理所有用户的父组引用
        for user in self._users.values():
            user.remove_parent(name)
        # 清理所有组的父组引用
        for group in self._groups.values():
            group.remove_parent(name)
        # 清理轨道中的引用
        for track in self._tracks.values():
            track.remove_group(name)
        del self._groups[name]
        self.save_all()
        return True

    def list_groups(self) -> List[Group]:
        return list(self._groups.values())

    # ==================== 轨道管理 ====================

    def get_track(self, name: str) -> Optional[Track]:
        return self._tracks.get(name)

    def create_track(self, name: str, groups: Optional[List[str]] = None) -> Track:
        if name in self._tracks:
            raise ValueError(f"轨道 {name} 已存在")
        track = Track(name, groups)
        self._tracks[name] = track
        self.save_all()
        return track

    def delete_track(self, name: str) -> bool:
        if name not in self._tracks:
            return False
        del self._tracks[name]
        self.save_all()
        return True

    def list_tracks(self) -> List[Track]:
        return list(self._tracks.values())

    # ==================== 权限查询 ====================

    def check(
        self,
        user_id: str,
        permission: str,
        context: Optional[Dict[str, str]] = None,
    ) -> bool:
        if self._query is None:
            return False
        return self._query.check(user_id, permission, context)

    def check_group(
        self,
        group_name: str,
        permission: str,
        context: Optional[Dict[str, str]] = None,
    ) -> bool:
        if self._query is None:
            return False
        return self._query.check_group(group_name, permission, context)

    # ==================== 节点操作 ====================

    def user_add_node(
        self,
        user_id: str,
        key: str,
        value: bool = True,
        context: Optional[Dict[str, str]] = None,
        duration: Optional[int] = None,
    ) -> None:
        user = self._users.get(user_id)
        if user is None:
            raise KeyError(f"用户 {user_id} 不存在")
        expiry = time.time() + duration if duration else None
        node = Node(key=key, value=value, context=context or {}, expiry=expiry)
        user.add_node(node)
        self.save_all()

    def user_remove_node(
        self,
        user_id: str,
        key: str,
        context: Optional[Dict[str, str]] = None,
    ) -> bool:
        user = self._users.get(user_id)
        if user is None:
            return False
        result = user.remove_node(key, context)
        if result:
            self.save_all()
        return result

    def group_add_node(
        self,
        group_name: str,
        key: str,
        value: bool = True,
        context: Optional[Dict[str, str]] = None,
        duration: Optional[int] = None,
    ) -> None:
        group = self._groups.get(group_name)
        if group is None:
            raise KeyError(f"组 {group_name} 不存在")
        expiry = time.time() + duration if duration else None
        node = Node(key=key, value=value, context=context or {}, expiry=expiry)
        group.add_node(node)
        self.save_all()

    def group_remove_node(
        self,
        group_name: str,
        key: str,
        context: Optional[Dict[str, str]] = None,
    ) -> bool:
        group = self._groups.get(group_name)
        if group is None:
            return False
        result = group.remove_node(key, context)
        if result:
            self.save_all()
        return result

    # ==================== 继承管理 ====================

    def user_add_group(self, user_id: str, group_name: str) -> None:
        user = self._users.get(user_id)
        if user is None:
            raise KeyError(f"用户 {user_id} 不存在")
        if group_name not in self._groups:
            raise KeyError(f"组 {group_name} 不存在")
        user.add_parent(group_name)
        self.save_all()

    def user_remove_group(self, user_id: str, group_name: str) -> None:
        user = self._users.get(user_id)
        if user is None:
            raise KeyError(f"用户 {user_id} 不存在")
        user.remove_parent(group_name)
        self.save_all()

    def group_inherit(self, group_name: str, parent_name: str) -> None:
        group = self._groups.get(group_name)
        if group is None:
            raise KeyError(f"组 {group_name} 不存在")
        if parent_name not in self._groups:
            raise KeyError(f"父组 {parent_name} 不存在")
        if group_name == parent_name:
            raise ValueError("组不能继承自身")
        # 循环继承检测
        if self._would_create_cycle(group_name, parent_name):
            raise ValueError(f"继承 {group_name} -> {parent_name} 会导致循环继承")
        group.add_parent(parent_name)
        self.save_all()

    def _would_create_cycle(self, group_name: str, parent_name: str) -> bool:
        """检查组继承是否会导致循环。"""
        visited: set[str] = set()
        queue = [parent_name]
        while queue:
            current = queue.pop(0)
            if current == group_name:
                return True
            if current in visited:
                continue
            visited.add(current)
            g = self._groups.get(current)
            if g:
                queue.extend(g.parents)
        return False

    def group_remove_inherit(self, group_name: str, parent_name: str) -> None:
        group = self._groups.get(group_name)
        if group is None:
            raise KeyError(f"组 {group_name} 不存在")
        group.remove_parent(parent_name)
        self.save_all()

    # ==================== 轨道晋升 ====================

    def promote(self, user_id: str, track_name: str) -> Optional[str]:
        user = self._users.get(user_id)
        track = self._tracks.get(track_name)
        if user is None or track is None:
            return None
        groups = track.groups
        if not groups:
            return None
        current = None
        for gname in reversed(groups):
            if gname in user.parents:
                current = gname
                break
        if current is None:
            target = groups[0]
            user.add_parent(target)
            self.save_all()
            return target
        idx = groups.index(current)
        if idx + 1 < len(groups):
            user.remove_parent(current)
            target = groups[idx + 1]
            user.add_parent(target)
            self.save_all()
            return target
        return None

    def demote(self, user_id: str, track_name: str) -> Optional[str]:
        user = self._users.get(user_id)
        track = self._tracks.get(track_name)
        if user is None or track is None:
            return None
        groups = track.groups
        if not groups:
            return None
        current = None
        for gname in reversed(groups):
            if gname in user.parents:
                current = gname
                break
        if current is None:
            return None
        idx = groups.index(current)
        if idx > 0:
            user.remove_parent(current)
            target = groups[idx - 1]
            user.add_parent(target)
            self.save_all()
            return target
        user.remove_parent(current)
        self.save_all()
        return None

    # ==================== Web Editor 序列化 ====================

    def to_webeditor_payload(self) -> dict:
        """生成 LuckPerms Web Editor 兼容的数据载荷。"""
        users_list = []
        for user in self._users.values():
            users_list.append({
                "username": user.display_name or user.unique_id,
                "uniqueId": user.unique_id,
                "nodes": [self._node_to_webeditor(n) for n in user.nodes],
                "parents": [{"group": p} for p in user.parents],
            })

        groups_list = []
        for group in self._groups.values():
            gdata = {
                "name": group.name,
                "displayName": group.display_name or group.name,
                "nodes": [self._node_to_webeditor(n) for n in group.nodes],
                "parents": [{"group": p} for p in group.parents],
            }
            if group.weight:
                gdata["weight"] = group.weight
            groups_list.append(gdata)

        tracks_list = []
        for track in self._tracks.values():
            tracks_list.append({
                "name": track.name,
                "groups": list(track.groups),
            })

        return {
            "metadata": {
                "plugin": "LuckPermsAPI",
                "pluginVersion": "1.0.0",
                "editorVersion": "1",
            },
            "users": users_list,
            "groups": groups_list,
            "tracks": tracks_list,
        }

    def apply_webeditor_changes(self, payload: dict) -> None:
        """应用 Web Editor 返回的变更数据。

        Args:
            payload: Web Editor 返回的 JSON 数据。
        """
        new_users: Dict[str, User] = {}
        new_groups: Dict[str, Group] = {}
        new_tracks: Dict[str, Track] = {}

        for gdata in payload.get("groups", []):
            g = Group(gdata["name"], gdata.get("displayName", ""), gdata.get("weight", 0))
            for ndata in gdata.get("nodes", []):
                g.add_node(self._node_from_webeditor(ndata))
            for p in gdata.get("parents", []):
                g.add_parent(p.get("group", ""))
            new_groups[g.name] = g

        for udata in payload.get("users", []):
            uid = udata["uniqueId"]
            u = User(uid, udata.get("username", ""))
            for ndata in udata.get("nodes", []):
                u.add_node(self._node_from_webeditor(ndata))
            for p in udata.get("parents", []):
                pname = p.get("group", "")
                if pname:
                    u.add_parent(pname)
            new_users[uid] = u

        for tdata in payload.get("tracks", []):
            t = Track(tdata["name"], tdata.get("groups", []))
            new_tracks[t.name] = t

        self._users = new_users
        self._groups = new_groups
        self._tracks = new_tracks
        self._query = PermissionQuery(self._users, self._groups)
        self.save_all()
        log.info(
            "已应用 Web Editor 变更: %d users, %d groups, %d tracks",
            len(self._users), len(self._groups), len(self._tracks),
        )

    @staticmethod
    def _node_to_webeditor(node: Node) -> dict:
        d: dict = {"key": node.key, "value": node.value}
        if node.context:
            d["context"] = node.context
        if node.expiry is not None:
            d["expiry"] = int(node.expiry * 1000)
        return d

    @staticmethod
    def _node_from_webeditor(data: dict) -> Node:
        expiry = data.get("expiry")
        if expiry is not None:
            expiry = expiry / 1000.0
        return Node(
            key=data["key"],
            value=data.get("value", True),
            context=data.get("context", {}),
            expiry=expiry,
        )
