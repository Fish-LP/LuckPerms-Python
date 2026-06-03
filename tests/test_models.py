"""
LuckPermsAPI 模型单元测试。
"""
import time

import pytest

from luckperms.models import Group, Node, PermissionHolder, Track, User


class TestNode:
    def test_node_creation(self):
        n = Node("plugin.chat", True)
        assert n.key == "plugin.chat"
        assert n.value is True
        assert n.context == {}
        assert n.expiry is None

    def test_node_defaults(self):
        n = Node("test")
        assert n.value is True
        assert n.context == {}
        assert n.expiry is None

    def test_node_with_context(self):
        n = Node("group.mute", False, {"group_id": "123"})
        assert n.context == {"group_id": ["123"]}
        assert n.matches_context({"group_id": "123"}) is True
        assert n.matches_context({"group_id": "456"}) is False
        assert n.matches_context({}) is False

    def test_node_with_multivalue_context(self):
        n = Node("group.mute", False, {"group_id": ["123", "456"]})
        assert n.context == {"group_id": ["123", "456"]}
        assert n.matches_context({"group_id": "123"}) is True
        assert n.matches_context({"group_id": ["789", "456"]}) is True
        assert n.matches_context({"group_id": "789"}) is False

    def test_node_context_subset(self):
        """节点 context 是查询 context 的子集时才匹配。"""
        n = Node("perm", True, {"a": "1", "b": "2"})
        assert n.matches_context({"a": "1", "b": "2", "c": "3"}) is True
        assert n.matches_context({"a": "1"}) is False
        assert n.matches_context({"a": "1", "b": "3"}) is False

    def test_node_expiry(self):
        n = Node("temp", True, expiry=time.time() - 1)
        assert n.is_expired() is True
        n2 = Node("temp", True, expiry=time.time() + 3600)
        assert n2.is_expired() is False
        n3 = Node("perm")
        assert n3.is_expired() is False

    def test_node_serde(self):
        n = Node("a.b", False, {"k": "v"}, 1234567890.0)
        d = n.to_dict()
        assert d == {"key": "a.b", "value": False, "context": {"k": ["v"]}, "expiry": 1234567890.0}
        n2 = Node.from_dict(d)
        assert n == n2

    def test_node_serde_minimal(self):
        n = Node("simple")
        d = n.to_dict()
        assert "context" not in d
        assert "expiry" not in d
        n2 = Node.from_dict(d)
        assert n == n2

    def test_node_hash_eq(self):
        n1 = Node("a", True, {"k": "v"})
        n2 = Node("a", True, {"k": "v"})
        n3 = Node("a", True, {"k": "x"})
        assert n1 == n2
        assert hash(n1) == hash(n2)
        assert n1 != n3

    def test_node_eq_different_type(self):
        n = Node("a")
        assert n != "not a node"


class TestPermissionHolder:
    def test_holder_identifier(self):
        h = PermissionHolder("id123", "Display")
        assert h.identifier == "id123"
        assert h.display_name == "Display"

    def test_add_node_no_duplicate(self):
        h = PermissionHolder("1")
        h.add_node(Node("x", True))
        h.add_node(Node("x", False))
        assert len(h.nodes) == 1
        assert h.nodes[0].value is False

    def test_add_node_different_context(self):
        h = PermissionHolder("1")
        h.add_node(Node("x", True, {"ctx": "a"}))
        h.add_node(Node("x", False, {"ctx": "b"}))
        assert len(h.nodes) == 2

    def test_remove_node(self):
        h = PermissionHolder("1")
        h.add_node(Node("x"))
        assert h.remove_node("x") is True
        assert h.remove_node("x") is False

    def test_remove_node_with_context(self):
        h = PermissionHolder("1")
        h.add_node(Node("x", True, {"k": "v"}))
        assert h.remove_node("x") is False  # 不匹配 context
        assert h.remove_node("x", {"k": "v"}) is True

    def test_clear_nodes(self):
        h = PermissionHolder("1")
        h.add_node(Node("a"))
        h.add_node(Node("b"))
        h.clear_nodes()
        assert h.nodes == []

    def test_parents(self):
        h = PermissionHolder("1")
        h.add_parent("admin")
        h.add_parent("mod")
        h.add_parent("admin")  # 重复添加无效
        assert h.parents == ["admin", "mod"]
        h.remove_parent("admin")
        assert h.parents == ["mod"]

    def test_to_dict_abstract_raises(self):
        h = PermissionHolder("1")
        d = h.to_dict()
        assert d["id"] == "1"
        with pytest.raises(NotImplementedError):
            PermissionHolder.from_dict(d)


class TestUser:
    def test_user_creation(self):
        u = User("123456", "Alice")
        assert u.unique_id == "123456"
        assert u.display_name == "Alice"

    def test_user_default_display_name(self):
        u = User("123")
        assert u.display_name == "123"

    def test_add_remove_node(self):
        u = User("1")
        n = Node("plugin.admin")
        u.add_node(n)
        assert len(u.nodes) == 1
        assert u.remove_node("plugin.admin") is True
        assert u.remove_node("plugin.admin") is False

    def test_replace_node(self):
        u = User("1")
        u.add_node(Node("x", True))
        u.add_node(Node("x", False))
        assert len(u.nodes) == 1
        assert u.nodes[0].value is False

    def test_parents(self):
        u = User("1")
        u.add_parent("admin")
        u.add_parent("mod")
        assert u.parents == ["admin", "mod"]
        u.remove_parent("admin")
        assert u.parents == ["mod"]

    def test_serde(self):
        u = User("1", "Test")
        u.add_node(Node("a", True))
        u.add_parent("g1")
        d = u.to_dict()
        assert d["type"] == "user"
        u2 = User.from_dict(d)
        assert u2.unique_id == "1"
        assert u2.display_name == "Test"
        assert len(u2.nodes) == 1
        assert u2.parents == ["g1"]

    def test_serde_empty(self):
        u = User("1")
        d = u.to_dict()
        u2 = User.from_dict(d)
        assert u2.unique_id == "1"
        assert u2.nodes == []
        assert u2.parents == []


class TestGroup:
    def test_group_creation(self):
        g = Group("admin", "管理员")
        assert g.name == "admin"
        assert g.display_name == "管理员"

    def test_group_default_display_name(self):
        g = Group("mod")
        assert g.display_name == "mod"

    def test_group_inherit(self):
        g = Group("mod")
        g.add_parent("admin")
        assert g.parents == ["admin"]
        g.remove_parent("admin")
        assert g.parents == []

    def test_group_nodes(self):
        g = Group("admin")
        g.add_node(Node("plugin.*", True))
        g.add_node(Node("plugin.ban", False))
        assert len(g.nodes) == 2
        g.remove_node("plugin.*")
        assert len(g.nodes) == 1

    def test_group_serde(self):
        g = Group("admin", "管理员")
        g.add_node(Node("a", True))
        g.add_parent("super")
        d = g.to_dict()
        assert d["type"] == "group"
        assert d["id"] == "admin"
        g2 = Group.from_dict(d)
        assert g2.name == "admin"
        assert g2.display_name == "管理员"
        assert len(g2.nodes) == 1
        assert g2.parents == ["super"]

    def test_group_weight(self):
        g = Group("admin", weight=100)
        assert g.weight == 100
        d = g.to_dict()
        assert d["weight"] == 100

    def test_group_weight_default_zero(self):
        g = Group("mod")
        assert g.weight == 0
        d = g.to_dict()
        assert "weight" not in d

    def test_group_weight_roundtrip(self):
        g = Group("vip", weight=50)
        d = g.to_dict()
        g2 = Group.from_dict(d)
        assert g2.weight == 50


class TestTrack:
    def test_track_creation(self):
        t = Track("staff", ["member", "mod", "admin"])
        assert t.groups == ["member", "mod", "admin"]

    def test_track_modify(self):
        t = Track("t")
        t.append_group("a")
        t.append_group("b")
        t.append_group("a")  # 重复无效
        assert t.groups == ["a", "b"]
        assert t.remove_group("a") is True
        assert t.groups == ["b"]
        assert t.remove_group("c") is False

    def test_track_set_groups(self):
        t = Track("t", ["a", "b"])
        t.set_groups(["c", "d"])
        assert t.groups == ["c", "d"]

    def test_track_serde(self):
        t = Track("staff", ["a", "b"])
        d = t.to_dict()
        assert d == {"name": "staff", "groups": ["a", "b"]}
        t2 = Track.from_dict(d)
        assert t2.name == "staff"
        assert t2.groups == ["a", "b"]

    def test_track_serde_empty(self):
        t = Track("empty")
        d = t.to_dict()
        t2 = Track.from_dict(d)
        assert t2.groups == []


class TestMetaNodes:
    def test_meta_weight_as_node(self):
        g = Group("admin")
        g.add_node(Node("weight.100", True))
        assert g.weight == 100

    def test_meta_prefix_priority(self):
        g = Group("admin")
        g.add_node(Node("prefix.50.&c[Mod]", True))
        g.add_node(Node("prefix.100.&4[Admin]", True))
        assert g.get_meta("prefix") == "&4[Admin]"

    def test_group_weight_node_sync(self):
        g = Group("vip")
        g.weight = 50
        assert any(n.key == "weight.50" for n in g.nodes)
        assert g.weight == 50

        g.weight = 100
        assert not any(n.key == "weight.50" for n in g.nodes)
        assert any(n.key == "weight.100" for n in g.nodes)
        assert g.weight == 100

    def test_group_weight_fallback(self):
        g = Group("mod", weight=10)
        assert g.weight == 10

    def test_group_to_dict_no_duplicate_weight(self):
        g = Group("admin")
        g.weight = 100
        d = g.to_dict()
        # 节点中有 weight.100，不应再输出 weight 字段
        assert "weight" not in d
        assert any(n["key"] == "weight.100" for n in d["nodes"])

    def test_node_is_meta(self):
        assert Node("prefix.100.&cAdmin").is_meta is True
        assert Node("suffix.50.&7Member").is_meta is True
        assert Node("displayname.Custom").is_meta is True
        assert Node("weight.100").is_meta is True
        assert Node("plugin.chat").is_meta is False

    def test_node_meta_type(self):
        assert Node("prefix.100.&cAdmin").meta_type == "prefix"
        assert Node("weight.100").meta_type == "weight"
        assert Node("plugin.chat").meta_type is None

    def test_node_meta_value(self):
        assert Node("prefix.100.&cAdmin").meta_value == "&cAdmin"
        assert Node("weight.100").meta_value == "100"
        assert Node("plugin.chat").meta_value is None

    def test_remove_nodes_by_prefix(self):
        h = PermissionHolder("1")
        h.add_node(Node("weight.10", True))
        h.add_node(Node("weight.20", True))
        h.add_node(Node("plugin.chat", True))
        removed = h.remove_nodes_by_prefix("weight.")
        assert removed == 2
        assert len(h.nodes) == 1
        assert h.nodes[0].key == "plugin.chat"

    def test_transient_context(self):
        u = User("1")
        u.set_transient_context("world", "nether")
        assert u.transient_contexts == {"world": "nether"}
        u.clear_transient_contexts()
        assert u.transient_contexts == {}
