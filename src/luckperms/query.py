"""
LuckPermsAPI 权限查询引擎。

实现上下文敏感的权限检查，支持：
- 节点通配符（* 单段, ** 多段）
- 上下文匹配
- 组继承
- 过期节点自动过滤
- True/False 优先级（显式 False 覆盖通配符 True）
"""
from __future__ import annotations

import heapq
import re
from typing import Dict, List, Optional, Set, Tuple

from .config import LuckPermsConfig
from .models import Group, Node, User


class PermissionQuery:
    """权限查询器。

    Args:
        users: 用户字典 {unique_id: User}。
        groups: 组字典 {name: Group}。
    """

    def __init__(
        self,
        users: Dict[str, User],
        groups: Dict[str, Group],
        config: LuckPermsConfig | None = None,
    ):
        self._users = users
        self._groups = groups
        self._config = config or LuckPermsConfig()

    def check(
        self,
        holder_id: str,
        permission: str,
        context: Optional[Dict[str, str]] = None,
    ) -> bool:
        """检查持有者是否拥有指定权限。

        Args:
            holder_id: 用户唯一 ID。
            permission: 权限字符串。
            context: 查询上下文，如 ``{"group_id": "123456"}``。

        Return:
            若显式允许返回 True，显式拒绝或无任何匹配返回 False。
        """
        user = self._users.get(holder_id)
        if user is None:
            return False

        # 瞬态上下文覆盖查询上下文
        ctx = dict(user.transient_contexts)
        if context:
            ctx.update(context)
        all_nodes = self._collect_nodes(user, ctx)
        result = self._resolve(permission, all_nodes)
        return result if result is not None else False

    def check_group(
        self,
        group_name: str,
        permission: str,
        context: Optional[Dict[str, str]] = None,
    ) -> bool:
        """检查组权限。"""
        group = self._groups.get(group_name)
        if group is None:
            return False
        ctx = dict(group.transient_contexts)
        if context:
            ctx.update(context)
        all_nodes = self._collect_group_nodes(group, ctx)
        result = self._resolve(permission, all_nodes)
        return result if result is not None else False

    def _collect_nodes(
        self, user: User, ctx: Dict[str, str]
    ) -> List[Tuple[Node, int]]:
        """收集用户及其继承组的所有有效节点，附带优先级权重。

        优先级规则（与原版 LuckPerms 一致）：
        - 用户自身节点 priority=0（最高优先级）
        - 继承组节点按组 Weight 从高到低排序
        - 同 Weight 按继承深度（BFS 层级）排序，层级越近越优先
        """
        nodes: List[Tuple[Node, int]] = []

        # 用户自身节点（最高优先级）
        for node in user.nodes:
            if not node.is_expired() and node.matches_context(ctx):
                nodes.append((node, 0))

        # 继承组节点：按 weight 优先的堆遍历
        visited: Set[str] = set()
        queue: List[Tuple[int, int, str]] = []
        for pname in user.parents:
            g = self._groups.get(pname)
            if g:
                heapq.heappush(queue, (1, -g.weight, pname))

        while queue:
            depth, neg_w, gname = heapq.heappop(queue)
            if gname in visited:
                continue
            visited.add(gname)
            group = self._groups.get(gname)
            if not group:
                continue

            # depth 越小越优先，同 depth 下 weight 越大越优先
            priority = depth * 10000 + (10000 - group.weight)
            for node in group.nodes:
                if not node.is_expired() and node.matches_context(ctx):
                    nodes.append((node, priority))

            for parent_name in group.parents:
                pg = self._groups.get(parent_name)
                if pg and parent_name not in visited:
                    heapq.heappush(queue, (depth + 1, -pg.weight, parent_name))

        return nodes

    def _collect_group_nodes(
        self, group: Group, ctx: Dict[str, str]
    ) -> List[Tuple[Node, int]]:
        """收集组及其父组的所有有效节点。"""
        nodes: List[Tuple[Node, int]] = []
        visited: Set[str] = set()
        queue: List[Tuple[int, int, str]] = []
        heapq.heappush(queue, (0, -group.weight, group.name))

        while queue:
            depth, neg_w, gname = heapq.heappop(queue)
            if gname in visited:
                continue
            visited.add(gname)
            g = self._groups.get(gname)
            if g is None:
                continue

            priority = depth * 10000 + (10000 - g.weight)
            for node in g.nodes:
                if not node.is_expired() and node.matches_context(ctx):
                    nodes.append((node, priority))

            for parent_name in g.parents:
                pg = self._groups.get(parent_name)
                if pg and parent_name not in visited:
                    heapq.heappush(queue, (depth + 1, -pg.weight, parent_name))

        return nodes

    def _resolve(self, permission: str, nodes: List[Tuple[Node, int]]) -> Optional[bool]:
        """解析权限值。

        优先级（从高到低）：
        1. 精确匹配 (match_priority=0)
        2. 单段通配符 * (match_priority=1)
        3. 多段通配符 ** (match_priority=2)
        4. 同匹配优先级中，继承优先级越小越优先（用户自身 > 高 weight 组 > 低 weight 组）
        5. 同优先级同 weight，False 优先于 True（显式拒绝优先）
        """
        candidates: List[Tuple[int, int, int, Node]] = []

        for node, priority in nodes:
            match_p = self._match_priority(node.key, permission)
            if match_p < 0:
                continue
            false_first = 0 if node.value is False else 1
            candidates.append((match_p, priority, false_first, node))

        if not candidates:
            return None

        # 排序: match_p 越小越优先 -> priority 越小越优先 -> False 优先于 True
        candidates.sort(key=lambda x: (x[0], x[1], x[2]))
        return candidates[0][3].value

    @staticmethod
    def _match_priority(pattern: str, permission: str) -> int:
        """返回匹配优先级，-1 表示不匹配。

        优先级数值：
        0 = 精确匹配
        1 = 单段通配 * 匹配
        2 = 多段通配 ** 匹配
        """
        if pattern == permission:
            return 0

        if "*" not in pattern:
            return -1

        # 独立通配符：匹配所有非空权限
        if pattern == "*":
            return 1 if permission else -1
        if pattern == "**":
            return 2 if permission else -1

        p_parts = pattern.split(".")
        s_parts = permission.split(".")

        # 快速路径：仅含 *（不含 **）时，段数必须相同
        if "**" not in pattern:
            if len(p_parts) != len(s_parts):
                return -1
            for pp, sp in zip(p_parts, s_parts):
                if pp != "*" and pp != sp:
                    return -1
            return 1

        # 含 **，使用动态规划匹配
        if PermissionQuery._match_wildcard_dp(p_parts, s_parts):
            return 2
        return -1

    @staticmethod
    def _match_wildcard_dp(pattern_parts: list[str], string_parts: list[str]) -> bool:
        """动态规划匹配含 ** 的通配符模式。

        ** 可匹配零段、一段或多段。
        *  匹配恰好一段。
        """
        m, n = len(pattern_parts), len(string_parts)
        dp = [[False] * (n + 1) for _ in range(m + 1)]
        dp[0][0] = True

        # pattern 开头的 ** 可以匹配空
        for i in range(1, m + 1):
            if pattern_parts[i - 1] == "**":
                dp[i][0] = dp[i - 1][0]

        for i in range(1, m + 1):
            for j in range(1, n + 1):
                pp = pattern_parts[i - 1]
                if pp == "**":
                    # ** 匹配空 (dp[i-1][j])、再扩展一段 (dp[i][j-1])
                    dp[i][j] = dp[i - 1][j] or dp[i][j - 1]
                elif pp == "*":
                    dp[i][j] = dp[i - 1][j - 1]
                else:
                    dp[i][j] = dp[i - 1][j - 1] and pp == string_parts[j - 1]

        return dp[m][n]
