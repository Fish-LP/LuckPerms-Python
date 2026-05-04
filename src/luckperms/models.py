"""
LuckPermsAPI 核心权限模型。

参考 LuckPerms 设计，实现 Node / PermissionHolder / User / Group / Track。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Node:
    """权限节点。

    Args:
        key: 权限键，如 ``group.mute`` 或 ``plugin.*``。
        value: 权限值，True 为允许，False 为拒绝。
        context: 上下文集合，如 ``{"group_id": "123456"}``。
        expiry: 过期时间戳（秒），None 表示永不过期。
    """
    key: str
    value: bool = True
    context: Dict[str, str] = field(default_factory=dict)
    expiry: Optional[float] = None

    def is_expired(self) -> bool:
        """Return: 若已过期返回 True。"""
        if self.expiry is None:
            return False
        return time.time() > self.expiry

    def matches_context(self, ctx: Dict[str, str]) -> bool:
        """检查节点上下文是否匹配给定上下文。

        规则：节点上下文是查询上下文的子集（即节点要求的所有上下文键值对都必须满足）。
        """
        for k, v in self.context.items():
            if ctx.get(k) != v:
                return False
        return True

    def to_dict(self) -> dict:
        d: dict = {"key": self.key, "value": self.value}
        if self.context:
            d["context"] = self.context
        if self.expiry is not None:
            d["expiry"] = self.expiry
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Node:
        return cls(
            key=d["key"],
            value=d.get("value", True),
            context=d.get("context", {}),
            expiry=d.get("expiry"),
        )

    def __hash__(self) -> int:
        return hash((self.key, self.value, tuple(sorted(self.context.items()))))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Node):
            return NotImplemented
        return (
            self.key == other.key
            and self.value == other.value
            and self.context == other.context
        )


class PermissionHolder:
    """权限持有者抽象基类（User / Group 的基类）。"""

    def __init__(self, identifier: str, display_name: str = ""):
        self.identifier = identifier
        self.display_name = display_name or identifier
        self._nodes: List[Node] = []
        self._parents: List[str] = []  # 继承的组名

    @property
    def nodes(self) -> List[Node]:
        """Return: 当前直接持有的权限节点列表（副本）。"""
        return list(self._nodes)

    def set_nodes(self, nodes: List[Node]) -> None:
        """替换所有节点。"""
        self._nodes = list(nodes)

    def add_node(self, node: Node) -> None:
        """添加节点，若已存在相同 key+context 则替换。"""
        for i, existing in enumerate(self._nodes):
            if existing.key == node.key and existing.context == node.context:
                self._nodes[i] = node
                return
        self._nodes.append(node)

    def remove_node(self, key: str, context: Optional[Dict[str, str]] = None) -> bool:
        """移除匹配 key 和 context 的节点。"""
        ctx = context or {}
        for i, node in enumerate(self._nodes):
            if node.key == key and node.context == ctx:
                self._nodes.pop(i)
                return True
        return False

    def clear_nodes(self) -> None:
        """清空所有节点。"""
        self._nodes.clear()

    def add_parent(self, group_name: str) -> None:
        """添加父组（继承）。"""
        if group_name not in self._parents:
            self._parents.append(group_name)

    def remove_parent(self, group_name: str) -> None:
        """移除父组继承。"""
        if group_name in self._parents:
            self._parents.remove(group_name)

    @property
    def parents(self) -> List[str]:
        return list(self._parents)

    def to_dict(self) -> dict:
        return {
            "id": self.identifier,
            "display_name": self.display_name,
            "nodes": [n.to_dict() for n in self._nodes],
            "parents": list(self._parents),
        }

    @classmethod
    def from_dict(cls, d: dict) -> PermissionHolder:
        raise NotImplementedError("请使用 User.from_dict 或 Group.from_dict")


class User(PermissionHolder):
    """用户权限持有者。

    Args:
        unique_id: 用户唯一标识（如 QQ 号字符串）。
        display_name: 显示名称。
    """

    def __init__(self, unique_id: str, display_name: str = ""):
        super().__init__(unique_id, display_name)
        self.unique_id = unique_id

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["type"] = "user"
        return d

    @classmethod
    def from_dict(cls, d: dict) -> User:
        u = cls(d["id"], d.get("display_name", ""))
        u._nodes = [Node.from_dict(n) for n in d.get("nodes", [])]
        u._parents = d.get("parents", [])
        return u


class Group(PermissionHolder):
    """权限组。

    Args:
        name: 组名。
        display_name: 显示名称。
        weight: 组权重，数值越大优先级越高。
    """

    def __init__(self, name: str, display_name: str = "", weight: int = 0):
        super().__init__(name, display_name)
        self.name = name
        self.weight = weight

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["type"] = "group"
        if self.weight:
            d["weight"] = self.weight
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Group:
        g = cls(d["id"], d.get("display_name", ""), d.get("weight", 0))
        g._nodes = [Node.from_dict(n) for n in d.get("nodes", [])]
        g._parents = d.get("parents", [])
        return g


class Track:
    """晋升轨道（角色晋升路径）。

    Args:
        name: 轨道名称。
        groups: 按顺序排列的组名列表。
    """

    def __init__(self, name: str, groups: Optional[List[str]] = None):
        self.name = name
        self._groups: List[str] = list(groups or [])

    @property
    def groups(self) -> List[str]:
        return list(self._groups)

    def set_groups(self, groups: List[str]) -> None:
        self._groups = list(groups)

    def append_group(self, group_name: str) -> None:
        if group_name not in self._groups:
            self._groups.append(group_name)

    def remove_group(self, group_name: str) -> bool:
        if group_name in self._groups:
            self._groups.remove(group_name)
            return True
        return False

    def to_dict(self) -> dict:
        return {"name": self.name, "groups": list(self._groups)}

    @classmethod
    def from_dict(cls, d: dict) -> Track:
        return cls(d["name"], d.get("groups", []))
