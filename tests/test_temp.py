"""
临时权限（有效期）、清理与元数据的 manager 测试。
"""

import tempfile
import time

import pytest

from luckperms.manager import LuckPermsManager


class TestTempPermissions:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mgr = LuckPermsManager(self.tmpdir)
        self.mgr.create_group("vip")
        self.mgr.group_add_node("vip", "plugin.vip", True)
        self.mgr.create_user("u1", "User One")

    def test_temp_node_has_expiry(self):
        self.mgr.user_add_node("u1", "plugin.temp", True, duration=3_600)
        node = self.mgr.get_user("u1").get_node("plugin.temp")
        assert node is not None
        assert node.expiry is not None
        assert node.expiry > time.time()

    def test_expired_node_not_effective(self):
        self.mgr.user_add_node("u1", "plugin.temp", True, duration=3_600)
        node = self.mgr.get_user("u1").get_node("plugin.temp")
        node.expiry = time.time() - 1
        assert self.mgr.check("u1", "plugin.temp") is False

    def test_group_add_node_duration(self):
        self.mgr.group_add_node("vip", "plugin.tempplug", True, duration=60)
        node = self.mgr.get_group("vip").get_node("plugin.tempplug")
        assert node is not None and node.expiry is not None

    def test_modifier_accumulate(self):
        self.mgr.user_add_node("u1", "plugin.a", True, duration=100)
        first = self.mgr.get_user("u1").get_node("plugin.a").expiry
        self.mgr.user_add_node(
            "u1", "plugin.a", True, duration=100, modifier="accumulate"
        )
        second = self.mgr.get_user("u1").get_node("plugin.a").expiry
        assert second > first + 90

    def test_modifier_replace_keeps_longest(self):
        self.mgr.user_add_node("u1", "plugin.b", True, duration=1_000)
        first = self.mgr.get_user("u1").get_node("plugin.b").expiry
        self.mgr.user_add_node("u1", "plugin.b", True, duration=10, modifier="replace")
        assert self.mgr.get_user("u1").get_node("plugin.b").expiry == first

    def test_modifier_deny_raises(self):
        self.mgr.user_add_node("u1", "plugin.c", True, duration=100)
        with pytest.raises(ValueError, match="deny"):
            self.mgr.user_add_node(
                "u1", "plugin.c", True, duration=100, modifier="deny"
            )

    def test_unknown_modifier_rejected(self):
        with pytest.raises(ValueError, match="未知的临时修饰符"):
            self.mgr.user_add_node(
                "u1", "plugin.d", True, duration=10, modifier="bogus"
            )

    def test_permanent_node_has_no_expiry(self):
        self.mgr.user_add_node("u1", "plugin.perm", True)
        assert self.mgr.get_user("u1").get_node("plugin.perm").expiry is None


class TestTempInheritance:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mgr = LuckPermsManager(self.tmpdir)
        self.mgr.create_group("vip")
        self.mgr.group_add_node("vip", "plugin.vip", True)
        self.mgr.create_user("u1", "User One")

    def test_temp_parent_effective(self):
        self.mgr.user_add_group("u1", "vip", duration=3_600)
        assert "vip" in self.mgr.get_user("u1").temp_parents
        assert self.mgr.check("u1", "plugin.vip") is True

    def test_expired_temp_parent_not_effective(self):
        self.mgr.user_add_group("u1", "vip", duration=3_600)
        user = self.mgr.get_user("u1")
        user.get_node("group.vip").expiry = time.time() - 1
        assert self.mgr.check("u1", "plugin.vip") is False

    def test_remove_group_clears_temp(self):
        self.mgr.user_add_group("u1", "vip", duration=3_600)
        self.mgr.user_remove_group("u1", "vip")
        assert self.mgr.get_user("u1").temp_parents == []
        assert self.mgr.check("u1", "plugin.vip") is False

    def test_group_temp_inherit(self):
        self.mgr.create_group("parent")
        self.mgr.group_add_node("parent", "plugin.parent", True)
        self.mgr.group_inherit("vip", "parent", duration=3_600)
        assert self.mgr.check_group("vip", "plugin.parent") is True
        self.mgr.group_remove_inherit("vip", "parent")
        assert self.mgr.check_group("vip", "plugin.parent") is False

    def test_temp_parent_persisted(self):
        self.mgr.user_add_group("u1", "vip", duration=3_600)
        mgr2 = LuckPermsManager(self.tmpdir)
        assert "vip" in mgr2.get_user("u1").temp_parents

    def test_delete_group_cleans_temp_refs(self):
        self.mgr.user_add_group("u1", "vip", duration=3_600)
        self.mgr.delete_group("vip")
        assert self.mgr.get_user("u1").temp_parents == []


class TestClearAndMeta:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mgr = LuckPermsManager(self.tmpdir)
        self.mgr.create_group("default")
        self.mgr.create_group("admin")
        self.mgr.create_user("u1", "User One")

    def test_clear_permissions(self):
        self.mgr.user_add_node("u1", "a.b", True)
        self.mgr.user_add_node("u1", "a.c", True)
        assert self.mgr.clear_permissions("u1") == 2
        assert self.mgr.get_user("u1").nodes == []

    def test_clear_parents_restores_default(self):
        self.mgr.user_add_group("u1", "admin")
        self.mgr.clear_parents("u1")
        assert self.mgr.get_user("u1").parents == ["default"]

    def test_clear_parents_removes_temp(self):
        self.mgr.user_add_group("u1", "admin", duration=3_600)
        self.mgr.clear_parents("u1")
        assert self.mgr.get_user("u1").temp_parents == []

    def test_group_clear(self):
        self.mgr.group_add_node("admin", "a.b", True)
        self.mgr.group_inherit("admin", "default")
        self.mgr.clear_permissions("admin", is_group=True)
        self.mgr.clear_parents("admin", is_group=True)
        assert self.mgr.get_group("admin").nodes == []
        assert self.mgr.get_group("admin").parents == []

    def test_clear_unknown_holder_raises(self):
        with pytest.raises(KeyError):
            self.mgr.clear_permissions("nobody")

    def test_set_meta_prefix(self):
        key = self.mgr.set_meta("u1", "prefix", "&cAdmin", priority=100)
        assert key == "prefix.100.&cAdmin"
        assert self.mgr.get_meta("u1", "prefix") == "&cAdmin"

    def test_set_meta_custom_key(self):
        key = self.mgr.set_meta("u1", "home", "world")
        assert key == "meta.home.world"
        assert self.mgr.get_meta("u1", "home") == "world"

    def test_set_meta_displayname_and_weight(self):
        assert (
            self.mgr.set_meta("admin", "displayname", "管理员", is_group=True)
            == "displayname.管理员"
        )
        assert (
            self.mgr.set_meta("admin", "weight", "100", is_group=True) == "weight.100"
        )
        assert self.mgr.get_group("admin").weight == 100

    def test_set_group_display_name(self):
        self.mgr.set_group_display_name("admin", "管理组")
        assert self.mgr.get_group("admin").get_meta("displayname") == "管理组"

    def test_unset_meta(self):
        self.mgr.set_meta("u1", "suffix", "&7[User]", priority=1)
        assert self.mgr.unset_meta("u1", "suffix") == 1
        assert self.mgr.get_meta("u1", "suffix") is None

    def test_unset_custom_meta(self):
        self.mgr.set_meta("u1", "home", "world")
        assert self.mgr.unset_meta("u1", "home") == 1
        assert self.mgr.get_meta("u1", "home") is None

    def test_meta_with_duration(self):
        self.mgr.set_meta("u1", "prefix", "&aTemp", priority=5, duration=3_600)
        node = self.mgr.get_user("u1").get_node("prefix.5.&aTemp")
        assert node is not None and node.expiry is not None

    def test_list_group_members(self):
        self.mgr.user_add_group("u1", "admin")
        self.mgr.create_user("u2", "User Two")
        self.mgr.user_add_group("u2", "admin", duration=3_600)
        assert self.mgr.list_group_members("admin") == ["u1", "u2"]

    def test_list_group_members_unknown_group(self):
        with pytest.raises(KeyError):
            self.mgr.list_group_members("nobody")

    def test_user_show_tracks(self):
        self.mgr.create_track("staff", ["default", "admin"])
        assert self.mgr.user_show_tracks("u1") == [("staff", 1)]

    def test_track_clear_and_rename(self):
        self.mgr.create_track("staff", ["default", "admin"])
        assert self.mgr.clear_track("staff") == 2
        assert self.mgr.get_track("staff").groups == []
        self.mgr.rename_track("staff", "team")
        assert self.mgr.get_track("team") is not None
        assert self.mgr.get_track("staff") is None

    def test_rename_track_duplicate_rejected(self):
        self.mgr.create_track("a", [])
        self.mgr.create_track("b", [])
        with pytest.raises(ValueError, match="已存在"):
            self.mgr.rename_track("a", "b")


class TestVerboseCallback:
    """权限检查监听（verbose）回调测试。"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mgr = LuckPermsManager(self.tmpdir)
        self.mgr.create_user("u1", "User One")
        self.events: list[tuple[str, bool]] = []

    def test_callback_invoked_for_target_user(self):
        self.mgr.set_verbose(
            "u1", lambda uid, perm, ctx, res: self.events.append((perm, res))
        )
        self.mgr.check("u1", "plugin.x")
        assert self.events == [("plugin.x", False)]

    def test_callback_not_invoked_for_other_user(self):
        self.mgr.create_user("u2", "User Two")
        self.mgr.set_verbose(
            "u1", lambda uid, perm, ctx, res: self.events.append((perm, res))
        )
        self.mgr.check("u2", "plugin.x")
        assert self.events == []

    def test_disable_verbose(self):
        self.mgr.set_verbose(
            "u1", lambda uid, perm, ctx, res: self.events.append((perm, res))
        )
        self.mgr.set_verbose(None)
        self.mgr.check("u1", "plugin.x")
        assert self.events == []
