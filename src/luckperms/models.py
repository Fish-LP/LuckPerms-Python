"""
LuckPermsAPI 核心权限模型。

参考 LuckPerms 设计，实现 Node / PermissionHolder / User / Group / Track。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


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

    @property
    def is_meta(self) -> bool:
        """是否为元数据节点（prefix / suffix / displayname / weight）。"""
        return self.key.startswith(("prefix.", "suffix.", "displayname.", "weight."))

    @property
    def meta_type(self) -> Optional[Literal["prefix", "suffix", "displayname", "weight"]]:
        """返回元数据类型，非元数据节点返回 None。"""
        for prefix in ("prefix.", "suffix.", "displayname.", "weight."):
            if self.key.startswith(prefix):
                return prefix[:-1]  # type: ignore[return-value]
        return None

    @property
    def meta_value(self) -> Optional[str]:
        """提取元数据值。

        例如 ``prefix.100.&cAdmin`` → ``&cAdmin``，``weight.100`` → ``100``。
        """
        if not self.is_meta:
            return None
        parts = self.key.split(".", 2)
        if len(parts) >= 3:
            return parts[2]
        if len(parts) == 2:
            return parts[1]
        return None

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
        """从字典反序列化节点。

        Args:
            d: 节点字典。

        Return:
            Node 实例。
        """
        raw_ctx = d.get("context", {})
        context: dict[str, str] = {}
        if isinstance(raw_ctx, dict):
            for k, v in raw_ctx.items():
                if isinstance(v, list):
                    context[k] = v[0] if v else ""
                else:
                    context[k] = str(v)

        return cls(
            key=d["key"],
            value=d.get("value", True),
            context=context,
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
        self.transient_contexts: Dict[str, str] = {}

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

    def set_transient_context(self, key: str, value: str) -> None:
        """设置瞬态上下文（运行时有效，不持久化）。"""
        self.transient_contexts[key] = value

    def clear_transient_contexts(self) -> None:
        """清空所有瞬态上下文。"""
        self.transient_contexts.clear()

    def get_meta(self, meta_type: str) -> Optional[str]:
        """提取指定类型的最高优先级 meta 值。

        例如 ``get_meta("prefix")`` 返回优先级最高的 prefix 值。
        """
        candidates: List[Tuple[int, str]] = []
        for node in self._nodes:
            if node.meta_type == meta_type and node.value is True:
                parts = node.key.split(".")
                try:
                    priority = int(parts[1]) if len(parts) > 1 else 0
                except ValueError:
                    priority = 0
                candidates.append((priority, node.meta_value or ""))
        if not candidates:
            return None
        return max(candidates, key=lambda x: x[0])[1]

    def remove_nodes_by_prefix(self, prefix: str) -> int:
        """移除所有 key 以指定前缀开头的节点。Return: 移除数量。"""
        removed = 0
        new_nodes: List[Node] = []
        for n in self._nodes:
            if n.key.startswith(prefix):
                removed += 1
            else:
                new_nodes.append(n)
        self._nodes = new_nodes
        return removed

    def cleanup_expired_nodes(self) -> int:
        """清理所有已过期节点。Return: 清理数量。"""
        before = len(self._nodes)
        self._nodes = [n for n in self._nodes if not n.is_expired()]
        return before - len(self._nodes)

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

    @property
    def is_default(self) -> bool:
        """Return: 是否为默认状态用户（无需持久化）。
        
        默认状态判定：
        - 无自定义权限节点
        - 无瞬态上下文
        - 显示名称为默认值（等于唯一ID）
        - 继承组为空或仅包含 default
        """
        if self._nodes:
            return False
        if self.transient_contexts:
            return False
        if self.display_name != self.unique_id:
            return False
        parents = set(self._parents)
        return not parents or parents == {"default"}

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["type"] = "user"
        return d

    @classmethod
    def from_dict(cls, d: dict) -> User:
        # 兼容 Web Editor 的驼峰命名
        display = d.get("display_name") or d.get("displayName", "")
        u = cls(d["id"], display)
        u._nodes = [Node.from_dict(n) for n in d.get("nodes", [])]
        
        # FIX: Web Editor 用 group.xxx 节点表示继承，反向同步到 _parents
        parents = d.get("parents", [])
        u._parents = list(parents)
        for node in u._nodes:
            if node.key.startswith("group.") and node.value and not node.context:
                gname = node.key[6:]
                if gname not in u._parents:
                    u._parents.append(gname)
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
        self._weight = weight

    @property
    def weight(self) -> int:
        """组权重。优先从 ``weight.X`` 节点解析，否则回退构造时传入的值。"""
        for node in self._nodes:
            if node.key.startswith("weight.") and node.value is True:
                try:
                    return int(node.key.split(".")[1])
                except (IndexError, ValueError):
                    pass
        return self._weight

    @weight.setter
    def weight(self, value: int) -> None:
        self._weight = value
        # 同步更新/创建 weight 节点，确保 Web Editor 兼容
        self.remove_nodes_by_prefix("weight.")
        self.add_node(Node(f"weight.{value}", True))

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["type"] = "group"
        # 如果节点中已存在 weight 节点，不再重复输出 weight 字段
        if not any(n.key.startswith("weight.") for n in self._nodes):
            if self._weight:
                d["weight"] = self._weight
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Group:
        display = d.get("display_name") or d.get("displayName", "")
        g = cls(d["id"], display, d.get("weight", 0))
        g._nodes = [Node.from_dict(n) for n in d.get("nodes", [])]
        
        # FIX: 同 User，从 nodes 反向同步 parents
        parents = d.get("parents", [])
        g._parents = list(parents)
        for node in g._nodes:
            if node.key.startswith("group.") and node.value and not node.context:
                gname = node.key[6:]
                if gname not in g._parents:
                    g._parents.append(gname)
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