"""
LuckPermsAPI 管理器单元测试。
"""
import os
import tempfile
import time

import pytest

from luckperms.manager import LuckPermsManager
from luckperms.models import Group, Node, User
from luckperms.storage import JSONBackend


class TestManager:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mgr = LuckPermsManager(self.tmpdir)

    def test_create_user(self):
        u = self.mgr.create_user("123", "Alice")
        assert u.unique_id == "123"
        assert self.mgr.get_user("123") is u

    def test_create_user_auto_default_group(self):
        """创建用户时若存在 default 组，应自动加入。"""
        self.mgr.create_group("default")
        u = self.mgr.create_user("1")
        assert "default" in u.parents

    def test_create_user_no_default_if_missing(self):
        """不存在 default 组时，创建用户不应报错。"""
        u = self.mgr.create_user("1")
        assert u.parents == []

    def test_create_duplicate_user(self):
        self.mgr.create_user("123")
        with pytest.raises(ValueError, match="已存在"):
            self.mgr.create_user("123")

    def test_delete_user(self):
        self.mgr.create_user("1", "Alice")
        assert self.mgr.delete_user("1") is True
        assert self.mgr.get_user("1") is None
        assert self.mgr.delete_user("1") is False

    def test_list_users(self):
        self.mgr.create_user("1")
        self.mgr.create_user("2")
        assert len(self.mgr.list_users()) == 2

    def test_create_group(self):
        g = self.mgr.create_group("admin", "管理员")
        assert g.name == "admin"
        assert self.mgr.get_group("admin") is g

    def test_create_group_with_weight(self):
        g = self.mgr.create_group("admin", weight=100)
        assert g.weight == 100

    def test_create_duplicate_group(self):
        self.mgr.create_group("admin")
        with pytest.raises(ValueError, match="已存在"):
            self.mgr.create_group("admin")

    def test_delete_group(self):
        self.mgr.create_group("admin")
        assert self.mgr.delete_group("admin") is True
        assert self.mgr.get_group("admin") is None
        assert self.mgr.delete_group("admin") is False

    def test_list_groups(self):
        self.mgr.create_group("a")
        self.mgr.create_group("b")
        assert len(self.mgr.list_groups()) == 2

    def test_user_add_group(self):
        self.mgr.create_group("admin")
        self.mgr.create_user("1")
        self.mgr.user_add_group("1", "admin")
        assert "admin" in self.mgr.get_user("1").parents

    def test_user_add_group_raises(self):
        self.mgr.create_user("1")
        with pytest.raises(KeyError):
            self.mgr.user_add_group("1", "nonexist")
        with pytest.raises(KeyError):
            self.mgr.user_add_group("999", "admin")

    def test_user_remove_group(self):
        self.mgr.create_group("admin")
        self.mgr.create_user("1")
        self.mgr.user_add_group("1", "admin")
        self.mgr.user_remove_group("1", "admin")
        assert "admin" not in self.mgr.get_user("1").parents

    def test_group_inherit(self):
        self.mgr.create_group("admin")
        self.mgr.create_group("mod")
        self.mgr.group_inherit("mod", "admin")
        assert "admin" in self.mgr.get_group("mod").parents

    def test_group_inherit_self_raises(self):
        self.mgr.create_group("admin")
        with pytest.raises(ValueError, match="不能继承自身"):
            self.mgr.group_inherit("admin", "admin")

    def test_group_inherit_cycle_detected(self):
        self.mgr.create_group("admin")
        self.mgr.create_group("mod")
        self.mgr.group_inherit("mod", "admin")
        with pytest.raises(ValueError, match="循环继承"):
            self.mgr.group_inherit("admin", "mod")

    def test_group_inherit_cycle_indirect(self):
        self.mgr.create_group("a")
        self.mgr.create_group("b")
        self.mgr.create_group("c")
        self.mgr.group_inherit("b", "a")
        self.mgr.group_inherit("c", "b")
        with pytest.raises(ValueError, match="循环继承"):
            self.mgr.group_inherit("a", "c")

    def test_group_remove_inherit(self):
        self.mgr.create_group("admin")
        self.mgr.create_group("mod")
        self.mgr.group_inherit("mod", "admin")
        self.mgr.group_remove_inherit("mod", "admin")
        assert "admin" not in self.mgr.get_group("mod").parents

    def test_permission_check(self):
        self.mgr.create_group("admin")
        self.mgr.group_add_node("admin", "plugin.*")
        self.mgr.create_user("1")
        self.mgr.user_add_group("1", "admin")
        assert self.mgr.check("1", "plugin.chat") is True

    def test_check_group(self):
        self.mgr.create_group("mod")
        self.mgr.group_add_node("mod", "kick", True)
        assert self.mgr.check_group("mod", "kick") is True
        assert self.mgr.check_group("mod", "ban") is False
        assert self.mgr.check_group("nonexist", "kick") is False

    def test_user_add_node_with_context(self):
        self.mgr.create_user("1")
        self.mgr.user_add_node("1", "perm", True, {"server": "s1"})
        assert self.mgr.check("1", "perm", {"server": "s1"}) is True
        assert self.mgr.check("1", "perm") is False

    def test_user_add_node_with_duration(self):
        self.mgr.create_user("1")
        self.mgr.user_add_node("1", "temp", True, duration=1)
        assert self.mgr.check("1", "temp") is True
        time.sleep(1.1)
        assert self.mgr.check("1", "temp") is False

    def test_group_add_node_with_context(self):
        self.mgr.create_group("admin")
        self.mgr.group_add_node("admin", "perm", True, {"world": "w1"})
        assert self.mgr.check_group("admin", "perm", {"world": "w1"}) is True
        assert self.mgr.check_group("admin", "perm") is False

    def test_track_promote_demote(self):
        self.mgr.create_group("member")
        self.mgr.create_group("mod")
        self.mgr.create_track("staff", ["member", "mod"])
        self.mgr.create_user("1")

        assert self.mgr.promote("1", "staff") == "member"
        assert self.mgr.promote("1", "staff") == "mod"
        assert self.mgr.promote("1", "staff") is None

        assert self.mgr.demote("1", "staff") == "member"
        assert self.mgr.demote("1", "staff") is None

    def test_track_demote_from_first_removes(self):
        self.mgr.create_group("member")
        self.mgr.create_track("staff", ["member"])
        self.mgr.create_user("1")
        self.mgr.promote("1", "staff")
        assert self.mgr.demote("1", "staff") is None
        assert "member" not in self.mgr.get_user("1").parents

    def test_promote_unknown_user_or_track(self):
        assert self.mgr.promote("999", "staff") is None
        self.mgr.create_user("1")
        assert self.mgr.promote("1", "nonexist") is None

    def test_create_track_duplicate(self):
        self.mgr.create_track("staff")
        with pytest.raises(ValueError, match="已存在"):
            self.mgr.create_track("staff")

    def test_delete_track(self):
        self.mgr.create_track("staff")
        assert self.mgr.delete_track("staff") is True
        assert self.mgr.get_track("staff") is None
        assert self.mgr.delete_track("staff") is False

    def test_delete_group_cleans_refs(self):
        self.mgr.create_group("admin")
        self.mgr.create_group("mod")
        self.mgr.group_inherit("mod", "admin")
        self.mgr.create_user("1")
        self.mgr.user_add_group("1", "admin")
        self.mgr.create_track("staff", ["admin"])

        self.mgr.delete_group("admin")

        assert "admin" not in self.mgr.get_user("1").parents
        assert "admin" not in self.mgr.get_group("mod").parents
        assert "admin" not in self.mgr.get_track("staff").groups

    def test_delete_group_cleans_other_groups_refs(self):
        self.mgr.create_group("admin")
        self.mgr.create_group("mod")
        self.mgr.group_inherit("mod", "admin")
        self.mgr.delete_group("admin")
        assert "admin" not in self.mgr.get_group("mod").parents

    def test_persistence(self):
        """保存后使用新管理器加载，数据应保持一致。"""
        self.mgr.create_group("admin")
        self.mgr.group_add_node("admin", "plugin.*")
        self.mgr.create_user("1", "Alice")
        self.mgr.user_add_group("1", "admin")
        self.mgr.user_add_node("1", "plugin.ban", False)
        self.mgr.create_track("staff", ["member", "admin"])
        self.mgr.save_all()

        mgr2 = LuckPermsManager(self.tmpdir)
        assert mgr2.check("1", "plugin.chat") is True
        assert mgr2.check("1", "plugin.ban") is False
        assert mgr2.get_user("1").display_name == "Alice"
        assert mgr2.get_track("staff").groups == ["member", "admin"]

    def test_persistence_json_backend(self):
        tmpdir = tempfile.mkdtemp()
        mgr = LuckPermsManager(tmpdir, backend=JSONBackend())
        mgr.create_user("1", "Bob")
        mgr.create_group("admin")
        mgr.user_add_group("1", "admin")
        mgr.save_all()

        assert os.path.exists(os.path.join(tmpdir, "users.json"))

        mgr2 = LuckPermsManager(tmpdir, backend=JSONBackend())
        assert mgr2.get_user("1").display_name == "Bob"
        assert "admin" in mgr2.get_user("1").parents

    def test_webeditor_roundtrip(self):
        self.mgr.create_group("admin")
        self.mgr.group_add_node("admin", "plugin.*")
        self.mgr.create_user("1", "Alice")
        self.mgr.user_add_group("1", "admin")
        self.mgr.user_add_node("1", "plugin.chat", False)
        self.mgr.create_track("staff", ["member", "admin"])

        payload = self.mgr.to_webeditor_payload()
        assert payload["metadata"]["plugin"] == "LuckPermsAPI"
        assert len(payload["users"]) == 1
        assert len(payload["groups"]) == 1
        assert len(payload["tracks"]) == 1

        # 重建新管理器并应用
        tmpdir2 = tempfile.mkdtemp()
        mgr2 = LuckPermsManager(tmpdir2)
        mgr2.apply_webeditor_changes(payload)
        assert mgr2.check("1", "plugin.other") is True
        assert mgr2.check("1", "plugin.chat") is False

    def test_webeditor_node_expiry_roundtrip(self):
        """WebEditor 中的过期时间（毫秒）往返正确。"""
        self.mgr.create_user("1")
        self.mgr.user_add_node("1", "temp", True, duration=3600)
        payload = self.mgr.to_webeditor_payload()
        node_data = payload["users"][0]["nodes"][0]
        assert "expiry" in node_data
        assert isinstance(node_data["expiry"], int)

        mgr2 = LuckPermsManager(tempfile.mkdtemp())
        mgr2.apply_webeditor_changes(payload)
        node = mgr2.get_user("1").nodes[0]
        assert node.key == "temp"
        assert node.expiry is not None
        assert node.expiry > time.time()

    def test_webeditor_group_weight_roundtrip(self):
        """WebEditor 中的 group weight 往返正确。"""
        self.mgr.create_group("admin", weight=100)
        payload = self.mgr.to_webeditor_payload()
        group_data = payload["groups"][0]
        assert group_data["weight"] == 100

        mgr2 = LuckPermsManager(tempfile.mkdtemp())
        mgr2.apply_webeditor_changes(payload)
        assert mgr2.get_group("admin").weight == 100
