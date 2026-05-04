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
from typing import Any, Dict, List, Optional

from .models import Group, Node, Track, User
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
        self._load_all()

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    def _load_all(self) -> None:
        raw_users, raw_groups, raw_tracks = self._storage.load_all()
        for uid, d in raw_users.items():
            self._users[uid] = User.from_dict(d)
        for name, d in raw_groups.items():
            self._groups[name] = Group.from_dict(d)
        for name, d in raw_tracks.items():
            self._tracks[name] = Track.from_dict(d)
        self._query = PermissionQuery(self._users, self._groups)
        log.debug("loaded from disk: users=%d groups=%d tracks=%d", len(self._users), len(self._groups), len(self._tracks))

    def _save_all(self) -> None:
        users = {uid: u.to_dict() for uid, u in self._users.items()}
        groups = {name: g.to_dict() for name, g in self._groups.items()}
        tracks = {name: t.to_dict() for name, t in self._tracks.items()}
        self._storage.save_all(users, groups, tracks)
        log.debug("saved to disk: users=%d groups=%d tracks=%d", len(users), len(groups), len(tracks))

    @staticmethod
    def _node_to_webeditor(node: Node) -> dict[str, Any]:
        """将 Node 序列化为 Web Editor 兼容格式（expiry 转毫秒）。"""
        d: dict[str, Any] = {
            "key": node.key,
            "value": node.value,
        }
        if node.context:
            d["context"] = dict(node.context)
        if node.expiry is not None:
            d["expiry"] = int(node.expiry * 1000)
        return d

    @staticmethod
    def _node_from_webeditor(data: dict[str, Any]) -> Node:
        """从 Web Editor 格式反序列化 Node（expiry 毫秒转秒）。"""
        expiry = data.get("expiry")
        if expiry is not None:
            expiry = expiry / 1000.0
        return Node(
            key=data["key"],
            value=data.get("value", True),
            context=data.get("context", {}),
            expiry=expiry,
        )

    def _clean_group_refs(self, name: str) -> None:
        """删除组后清理所有引用。"""
        for u in self._users.values():
            if name in u.parents:
                u.remove_parent(name)
        for g in self._groups.values():
            if name in g.parents:
                g.remove_parent(name)
        for t in self._tracks.values():
            if name in t.groups:
                t.remove_group(name)

    # ------------------------------------------------------------------
    # User CRUD
    # ------------------------------------------------------------------
    def create_user(self, unique_id: str, display_name: Optional[str] = None) -> User:
        if unique_id in self._users:
            raise ValueError(f"用户 '{unique_id}' 已存在")
        user = User(unique_id, display_name or unique_id)
        if "default" in self._groups:
            user.add_parent("default")
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

    # ------------------------------------------------------------------
    # 节点与继承管理
    # ------------------------------------------------------------------
    def user_add_node(
        self,
        unique_id: str,
        key: str,
        value: bool = True,
        context: Optional[Dict[str, str]] = None,
        duration: Optional[int] = None,
    ) -> None:
        user = self._users[unique_id]
        expiry = time.time() + duration if duration else None
        user.add_node(Node(key, value, context or {}, expiry))
        self._save_all()

    def user_remove_node(self, unique_id: str, key: str, context: Optional[Dict[str, str]] = None) -> bool:
        user = self._users[unique_id]
        result = user.remove_node(key, context)
        self._save_all()
        return result

    def group_add_node(
        self,
        name: str,
        key: str,
        value: bool = True,
        context: Optional[Dict[str, str]] = None,
    ) -> None:
        group = self._groups[name]
        group.add_node(Node(key, value, context or {}))
        self._save_all()

    def group_remove_node(self, name: str, key: str, context: Optional[Dict[str, str]] = None) -> bool:
        group = self._groups[name]
        result = group.remove_node(key, context)
        self._save_all()
        return result

    def user_add_group(self, unique_id: str, group_name: str) -> None:
        if group_name not in self._groups:
            raise KeyError(f"组 '{group_name}' 不存在")
        if unique_id not in self._users:
            raise KeyError(f"用户 '{unique_id}' 不存在")
        self._users[unique_id].add_parent(group_name)
        self._save_all()

    def user_remove_group(self, unique_id: str, group_name: str) -> None:
        user = self._users[unique_id]
        user.remove_parent(group_name)
        self._save_all()

    def group_inherit(self, name: str, parent_name: str) -> None:
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

        self._groups[name].add_parent(parent_name)
        self._save_all()

    def group_remove_inherit(self, name: str, parent_name: str) -> None:
        self._groups[name].remove_parent(parent_name)
        self._save_all()

    # ------------------------------------------------------------------
    # 权限查询
    # ------------------------------------------------------------------
    def check(
        self,
        unique_id: str,
        permission: str,
        context: Optional[Dict[str, str]] = None,
    ) -> bool:
        return self._query.check(unique_id, permission, context)

    def check_group(
        self,
        name: str,
        permission: str,
        context: Optional[Dict[str, str]] = None,
    ) -> bool:
        return self._query.check_group(name, permission, context)

    # ------------------------------------------------------------------
    # 晋升轨道
    # ------------------------------------------------------------------
    def promote(self, unique_id: str, track_name: str) -> Optional[str]:
        user = self._users.get(unique_id)
        track = self._tracks.get(track_name)
        if not user or not track:
            return None

        current_idx = -1
        for i, gname in enumerate(track.groups):
            if gname in user.parents:
                current_idx = i
                break

        next_idx = current_idx + 1
        if next_idx >= len(track.groups):
            return None

        next_group = track.groups[next_idx]
        if current_idx >= 0:
            user.remove_parent(track.groups[current_idx])
        user.add_parent(next_group)
        self._save_all()
        return next_group

    def demote(self, unique_id: str, track_name: str) -> Optional[str]:
        user = self._users.get(unique_id)
        track = self._tracks.get(track_name)
        if not user or not track:
            return None

        current_idx = -1
        for i, gname in enumerate(track.groups):
            if gname in user.parents:
                current_idx = i
                break

        if current_idx <= 0:
            # 在第一级或不在轨道上，直接移除当前所在组（如果在轨道上）
            if current_idx == 0:
                user.remove_parent(track.groups[current_idx])
                self._save_all()
            return None

        prev_group = track.groups[current_idx - 1]
        user.remove_parent(track.groups[current_idx])
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
            holder: dict[str, Any] = {
                "type": "user",
                "id": user.unique_id,
                "displayName": user.display_name,
                "nodes": [self._node_to_webeditor(n) for n in user.nodes],
                "parents": list(user.parents),
            }
            permission_holders.append(holder)

        for group in self._groups.values():
            holder: dict[str, Any] = {
                "type": "group",
                "id": group.name,
                "displayName": group.display_name,
                "nodes": [self._node_to_webeditor(n) for n in group.nodes],
                "parents": list(group.parents),
            }
            if group.weight != 0:
                holder["weight"] = group.weight
            permission_holders.append(holder)

        tracks = []
        for track in self._tracks.values():
            tracks.append({
                "type": "track",
                "id": track.name,
                "groups": list(track.groups),
            })

        # 收集所有已知权限和上下文
        known_perms: set[str] = set()
        potential_ctxs: dict[str, set[str]] = {}
        for holder in list(self._users.values()) + list(self._groups.values()):
            for node in holder.nodes:
                known_perms.add(node.key)
                for k, v in node.context.items():
                    potential_ctxs.setdefault(k, set()).add(v)

        payload: dict[str, Any] = {
            "metadata": {
                "commandAlias": "lp",
                "uploader": {
                    "name": "Console",
                    "uuid": str(uuid.uuid4()),
                },
                "time": int(time.time() * 1000),
                "pluginVersion": "LuckPermsAPI/1.0.0",
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
        """应用增量变更（Web Editor Save 后的实际格式）。"""
        changes = payload.get("changes", [])
        group_deletions = payload.get("groupDeletions", [])
        track_deletions = payload.get("trackDeletions", [])
        user_deletions = payload.get("userDeletions", [])

        log.debug("[apply_delta] changes=%d groupDel=%s trackDel=%s userDel=%s",
                  len(changes), group_deletions, track_deletions, user_deletions)

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

            # 转换节点 expiry（毫秒 -> 秒）
            nodes = []
            for n in change.get("nodes", []):
                node_dict = dict(n)
                if "expiry" in node_dict and node_dict["expiry"] is not None:
                    node_dict["expiry"] = node_dict["expiry"] / 1000.0
                nodes.append(node_dict)

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
                log.debug("[apply_delta] upserted group: %s (nodes=%d parents=%s)", g.name, len(g.nodes), g.parents)

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
                log.debug("[apply_delta] upserted user: %s (nodes=%d parents=%s)", u.unique_id, len(u.nodes), u.parents)

            elif ctype == "track":
                d = {
                    "name": cid,
                    "groups": change.get("groups", []),
                }
                t = Track.from_dict(d)
                self._tracks[t.name] = t
                log.debug("[apply_delta] upserted track: %s (groups=%d)", t.name, len(t.groups))

        self._query = PermissionQuery(self._users, self._groups)
        self._save_all()
        log.info("[apply_delta] applied: users=%d groups=%d tracks=%d",
                 len(self._users), len(self._groups), len(self._tracks))

    def _apply_full_changes(self, payload: dict[str, Any]) -> None:
        """应用全量变更（旧版 / 直接上传格式）。"""
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
                nodes = []
                for n in h.get("nodes", []):
                    node_dict = dict(n)
                    if "expiry" in node_dict and node_dict["expiry"] is not None:
                        node_dict["expiry"] = node_dict["expiry"] / 1000.0
                    nodes.append(node_dict)
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
                nodes = []
                for n in h.get("nodes", []):
                    node_dict = dict(n)
                    if "expiry" in node_dict and node_dict["expiry"] is not None:
                        node_dict["expiry"] = node_dict["expiry"] / 1000.0
                    nodes.append(node_dict)
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
        log.info("[apply_full] applied: users=%d groups=%d tracks=%d",
                 len(self._users), len(self._groups), len(self._tracks))