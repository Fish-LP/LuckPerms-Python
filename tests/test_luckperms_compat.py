"""
兼容性对照测试：构造与原版 LuckPerms 相同的用户/组/权限结构，验证 check() 结果。
"""
import tempfile

import pytest

from luckperms.manager import LuckPermsManager
from luckperms.models import Group, Node, User
from luckperms.query import PermissionQuery


class TestLuckPermsCompatibility:
    def test_vanilla_inheritance_with_weight(self):
        """原版典型场景：三级继承链 + weight 排序。"""
        mgr = LuckPermsManager(tempfile.mkdtemp())
        mgr.create_group("default", weight=0)
        mgr.create_group("mod", weight=50)
        mgr.create_group("admin", weight=100)
        mgr.group_inherit("mod", "default")
        mgr.group_inherit("admin", "mod")

        mgr.create_user("steve")
        mgr.user_add_group("steve", "admin")

        mgr.group_add_node("default", "plugin.base", True)
        mgr.group_add_node("mod", "plugin.mod", True)
        mgr.group_add_node("admin", "plugin.admin", True)
        mgr.group_add_node("admin", "plugin.banned", False)

        assert mgr.check("steve", "plugin.base") is True
        assert mgr.check("steve", "plugin.mod") is True
        assert mgr.check("steve", "plugin.admin") is True
        assert mgr.check("steve", "plugin.banned") is False

    def test_weight_priority_overrides_lower(self):
        """高 weight 组的显式拒绝应覆盖低 weight 组的通配允许。"""
        mgr = LuckPermsManager(tempfile.mkdtemp())
        mgr.create_group("low", weight=1)
        mgr.create_group("high", weight=100)

        mgr.group_add_node("low", "plugin.*", True)
        mgr.group_add_node("high", "plugin.banned", False)

        mgr.create_user("alice")
        mgr.user_add_group("alice", "low")
        mgr.user_add_group("alice", "high")

        # high(weight=100) 的显式拒绝优先于 low(weight=1) 的通配允许
        assert mgr.check("alice", "plugin.banned") is False
        assert mgr.check("alice", "plugin.other") is True

    def test_explicit_deny_overrides_wildcard_inheritance(self):
        """用户自身显式拒绝优先于继承组的通配允许。"""
        mgr = LuckPermsManager(tempfile.mkdtemp())
        mgr.create_group("admin")
        mgr.group_add_node("admin", "plugin.**", True)

        mgr.create_user("bob")
        mgr.user_add_group("bob", "admin")
        mgr.user_add_node("bob", "plugin.banned", False)

        assert mgr.check("bob", "plugin.banned") is False
        assert mgr.check("bob", "plugin.other") is True

    def test_context_sensitive_permission(self):
        """上下文敏感权限检查。"""
        mgr = LuckPermsManager(tempfile.mkdtemp())
        mgr.create_user("charlie")
        mgr.user_add_node("charlie", "plugin.fly", True, {"world": "nether"})

        assert mgr.check("charlie", "plugin.fly", {"world": "nether"}) is True
        assert mgr.check("charlie", "plugin.fly", {"world": "overworld"}) is False
        assert mgr.check("charlie", "plugin.fly") is False

    def test_meta_node_roundtrip(self):
        """元数据节点在 weight property 和序列化间正确往返。"""
        mgr = LuckPermsManager(tempfile.mkdtemp())
        mgr.create_group("vip")
        mgr.get_group("vip").weight = 50
        mgr.get_group("vip").add_node(Node("prefix.50.&e[VIP]", True))

        assert mgr.get_group("vip").weight == 50
        assert mgr.get_group("vip").get_meta("prefix") == "&e[VIP]"

        # 持久化往返
        mgr.save_all()
        mgr2 = LuckPermsManager(mgr._data_dir)
        assert mgr2.get_group("vip").weight == 50
        assert mgr2.get_group("vip").get_meta("prefix") == "&e[VIP]"

    def test_transient_context_priority(self):
        """瞬态上下文优先级高于查询上下文。"""
        users = {}
        groups = {}
        q = PermissionQuery(users, groups)

        u = User("1")
        u.add_node(Node("plugin.cmd", True, {"server": "s1"}))
        u.set_transient_context("server", "s1")
        users["1"] = u

        assert q.check("1", "plugin.cmd") is True
        # 查询上下文覆盖瞬态上下文
        assert q.check("1", "plugin.cmd", {"server": "s2"}) is False

    def test_track_promote_with_multiple_groups(self):
        """Track 晋升：用户同时属于多个 track 组时的边界行为。"""
        mgr = LuckPermsManager(tempfile.mkdtemp())
        mgr.create_group("member")
        mgr.create_group("mod")
        mgr.create_group("admin")
        mgr.create_track("staff", ["member", "mod", "admin"])
        mgr.create_user("dave")

        # 异常状态：同时属于 member 和 mod
        mgr.user_add_group("dave", "member")
        mgr.user_add_group("dave", "mod")

        result = mgr.promote("dave", "staff")
        assert result == "admin"
        parents = mgr.get_user("dave").parents
        assert "member" not in parents
        assert "mod" not in parents
        assert "admin" in parents

    def test_track_demote_from_first_level(self):
        """Track 降级：从第一级降级应移除所有 track 组。"""
        mgr = LuckPermsManager(tempfile.mkdtemp())
        mgr.create_group("member")
        mgr.create_group("mod")
        mgr.create_track("staff", ["member", "mod"])
        mgr.create_user("eve")

        mgr.user_add_group("eve", "member")
        mgr.demote("eve", "staff")
        assert "member" not in mgr.get_user("eve").parents
        assert "mod" not in mgr.get_user("eve").parents
