"""
LuckPermsAPI 查询引擎单元测试。
"""
import time

import pytest

from luckperms.models import Group, Node, User
from luckperms.query import PermissionQuery


class TestPermissionQuery:
    def setup_method(self):
        self.users = {}
        self.groups = {}
        self.q = PermissionQuery(self.users, self.groups)

    def test_simple_allow(self):
        u = User("1")
        u.add_node(Node("plugin.chat", True))
        self.users["1"] = u
        assert self.q.check("1", "plugin.chat") is True

    def test_simple_deny(self):
        u = User("1")
        u.add_node(Node("plugin.chat", False))
        self.users["1"] = u
        assert self.q.check("1", "plugin.chat") is False

    def test_wildcard_single(self):
        u = User("1")
        u.add_node(Node("plugin.*", True))
        self.users["1"] = u
        assert self.q.check("1", "plugin.chat") is True
        assert self.q.check("1", "plugin.a.b") is False  # 单星不匹配多级
        assert self.q.check("1", "other.chat") is False
        assert self.q.check("1", "plugin") is False  # 单星不匹配零段

    def test_wildcard_double(self):
        u = User("1")
        u.add_node(Node("plugin.**", True))
        self.users["1"] = u
        assert self.q.check("1", "plugin.chat") is True
        assert self.q.check("1", "plugin.a.b") is True
        assert self.q.check("1", "plugin") is True  # ** 匹配零段
        assert self.q.check("1", "other.chat") is False

    def test_wildcard_double_in_middle(self):
        u = User("1")
        u.add_node(Node("plugin.**.admin", True))
        self.users["1"] = u
        assert self.q.check("1", "plugin.admin") is True
        assert self.q.check("1", "plugin.x.admin") is True
        assert self.q.check("1", "plugin.a.b.admin") is True
        assert self.q.check("1", "plugin.admin.extra") is False
        assert self.q.check("1", "other.admin") is False

    def test_wildcard_mixed(self):
        u = User("1")
        u.add_node(Node("plugin.*.**.read", True))
        self.users["1"] = u
        assert self.q.check("1", "plugin.a.read") is True
        assert self.q.check("1", "plugin.a.b.read") is True
        assert self.q.check("1", "plugin.read") is False  # * 至少匹配一段
        assert self.q.check("1", "plugin.a.write") is False

    def test_group_inheritance(self):
        g = Group("admin")
        g.add_node(Node("plugin.*", True))
        self.groups["admin"] = g

        u = User("1")
        u.add_parent("admin")
        self.users["1"] = u

        assert self.q.check("1", "plugin.chat") is True

    def test_multi_level_inheritance(self):
        """多级继承链：mod -> admin -> superadmin"""
        superadmin = Group("superadmin")
        superadmin.add_node(Node("plugin.super", True))
        self.groups["superadmin"] = superadmin

        admin = Group("admin")
        admin.add_node(Node("plugin.admin", True))
        admin.add_parent("superadmin")
        self.groups["admin"] = admin

        mod = Group("mod")
        mod.add_node(Node("plugin.mod", True))
        mod.add_parent("admin")
        self.groups["mod"] = mod

        u = User("1")
        u.add_parent("mod")
        self.users["1"] = u

        assert self.q.check("1", "plugin.mod") is True
        assert self.q.check("1", "plugin.admin") is True
        assert self.q.check("1", "plugin.super") is True

    def test_context_match(self):
        u = User("1")
        u.add_node(Node("plugin.admin", True, {"group_id": "123"}))
        self.users["1"] = u

        assert self.q.check("1", "plugin.admin", {"group_id": "123"}) is True
        assert self.q.check("1", "plugin.admin", {"group_id": "456"}) is False
        assert self.q.check("1", "plugin.admin") is False

    def test_context_subset(self):
        """节点的 context 是查询 context 的子集即可匹配。"""
        u = User("1")
        u.add_node(Node("plugin.admin", True, {"server": "s1", "world": "w1"}))
        self.users["1"] = u

        assert self.q.check("1", "plugin.admin", {"server": "s1", "world": "w1"}) is True
        assert self.q.check("1", "plugin.admin", {"server": "s1", "world": "w1", "extra": "x"}) is True
        assert self.q.check("1", "plugin.admin", {"server": "s1"}) is False

    def test_explicit_deny_overrides_wildcard(self):
        u = User("1")
        u.add_node(Node("plugin.**", True))
        u.add_node(Node("plugin.chat", False))
        self.users["1"] = u

        assert self.q.check("1", "plugin.chat") is False
        assert self.q.check("1", "plugin.other") is True

    def test_weight_priority_over_false_first(self):
        """同优先级下，weight（继承深度）应优先于 false_first。

        用户自身的 True 应优先于继承组的 False。
        """
        admin = Group("admin")
        admin.add_node(Node("plugin.chat", False))
        self.groups["admin"] = admin

        u = User("1")
        u.add_node(Node("plugin.chat", True))
        u.add_parent("admin")
        self.users["1"] = u

        assert self.q.check("1", "plugin.chat") is True

    def test_inherited_deny_overrides_inherited_wildcard(self):
        """同 weight 下（同一继承层级），显式拒绝优先于通配允许。"""
        admin = Group("admin")
        admin.add_node(Node("plugin.**", True))
        self.groups["admin"] = admin

        mod = Group("mod")
        mod.add_node(Node("plugin.chat", False))
        mod.add_parent("admin")
        self.groups["mod"] = mod

        u = User("1")
        u.add_parent("mod")
        self.users["1"] = u

        # mod 的显式拒绝 (weight=0) 优先于 admin 的通配 (weight=1)
        assert self.q.check("1", "plugin.chat") is False
        assert self.q.check("1", "plugin.other") is True

    def test_expired_node_ignored(self):
        u = User("1")
        u.add_node(Node("plugin.old", True, expiry=time.time() - 1))
        self.users["1"] = u
        assert self.q.check("1", "plugin.old") is False

    def test_unknown_user(self):
        assert self.q.check("999", "anything") is False

    def test_group_check(self):
        g = Group("mod")
        g.add_node(Node("group.kick", True))
        self.groups["mod"] = g
        assert self.q.check_group("mod", "group.kick") is True
        assert self.q.check_group("mod", "group.ban") is False

    def test_group_check_with_inheritance(self):
        admin = Group("admin")
        admin.add_node(Node("admin.ban", True))
        self.groups["admin"] = admin

        mod = Group("mod")
        mod.add_parent("admin")
        self.groups["mod"] = mod

        assert self.q.check_group("mod", "admin.ban") is True

    def test_priority_exact_over_single_wildcard(self):
        u = User("1")
        u.add_node(Node("plugin.*", True))
        u.add_node(Node("plugin.chat", False))
        self.users["1"] = u
        assert self.q.check("1", "plugin.chat") is False

    def test_priority_single_over_double_wildcard(self):
        u = User("1")
        u.add_node(Node("plugin.**", True))
        u.add_node(Node("plugin.chat.*", False))
        self.users["1"] = u
        assert self.q.check("1", "plugin.chat.read") is False
        assert self.q.check("1", "plugin.other") is True

    def test_circular_inheritance(self):
        """循环继承不应导致死循环。"""
        a = Group("a")
        a.add_parent("b")
        self.groups["a"] = a

        b = Group("b")
        b.add_parent("a")
        self.groups["b"] = b

        u = User("1")
        u.add_parent("a")
        a.add_node(Node("perm", True))
        self.users["1"] = u

        assert self.q.check("1", "perm") is True

    def test_root_wildcard_star(self):
        """`*` 作为独立权限应匹配所有非空权限。"""
        u = User("1")
        u.add_node(Node("*", True))
        self.users["1"] = u
        assert self.q.check("1", "anything") is True
        assert self.q.check("1", "a.b.c") is True
        assert self.q.check("1", "plugin.chat") is True

    def test_root_wildcard_double_star(self):
        """`**` 作为独立权限应匹配所有非空权限。"""
        u = User("1")
        u.add_node(Node("**", True))
        self.users["1"] = u
        assert self.q.check("1", "anything") is True
        assert self.q.check("1", "a.b.c") is True

    def test_root_wildcard_priority(self):
        """精确匹配优先于 `*` 通配。"""
        u = User("1")
        u.add_node(Node("*", True))
        u.add_node(Node("plugin.chat", False))
        self.users["1"] = u
        assert self.q.check("1", "plugin.chat") is False
        assert self.q.check("1", "other") is True

    def test_star_vs_double_star_priority(self):
        """`*` 优先于 `**`。"""
        u = User("1")
        u.add_node(Node("**", False))
        u.add_node(Node("*", True))
        self.users["1"] = u
        assert self.q.check("1", "anything") is True  # * 优先

    def test_empty_permission_not_matched(self):
        """空权限不应被匹配。"""
        u = User("1")
        u.add_node(Node("*", True))
        self.users["1"] = u
        assert self.q.check("1", "") is False

    def test_weight_priority_over_depth(self):
        """高 weight 的远亲组应优先于低 weight 的近亲组（原版行为）。"""
        low = Group("low", weight=1)
        low.add_node(Node("perm", False))
        self.groups["low"] = low

        high = Group("high", weight=100)
        high.add_node(Node("perm", True))
        self.groups["high"] = high

        mid = Group("mid", weight=50)
        mid.add_parent("low")   # 近亲，但 low weight
        mid.add_parent("high")  # 远亲，但 high weight
        self.groups["mid"] = mid

        u = User("1")
        u.add_parent("mid")
        self.users["1"] = u

        # 原版行为: high(weight=100) 优先于 low(weight=1)
        assert self.q.check("1", "perm") is True

    def test_weight_same_depth_different_groups(self):
        """同深度下，高 weight 组优先。"""
        g1 = Group("g1", weight=10)
        g1.add_node(Node("perm", False))
        self.groups["g1"] = g1

        g2 = Group("g2", weight=50)
        g2.add_node(Node("perm", True))
        self.groups["g2"] = g2

        u = User("1")
        u.add_parent("g1")
        u.add_parent("g2")
        self.users["1"] = u

        # g2(weight=50) 优先于 g1(weight=10)
        assert self.q.check("1", "perm") is True

    def test_transient_context_overrides(self):
        """瞬态上下文无需查询参数即可生效。"""
        u = User("1")
        u.add_node(Node("plugin.fly", True, {"world": "nether"}))
        u.set_transient_context("world", "nether")
        self.users["1"] = u
        # 即使查询时不传 world 上下文，瞬态上下文也生效
        assert self.q.check("1", "plugin.fly") is True

    def test_transient_context_overridden_by_query(self):
        """查询上下文可覆盖瞬态上下文。"""
        u = User("1")
        u.add_node(Node("plugin.fly", True, {"world": "nether"}))
        u.set_transient_context("world", "overworld")
        self.users["1"] = u
        # 瞬态上下文为 overworld，不匹配 nether
        assert self.q.check("1", "plugin.fly") is False
        # 查询上下文覆盖瞬态上下文
        assert self.q.check("1", "plugin.fly", {"world": "nether"}) is True
