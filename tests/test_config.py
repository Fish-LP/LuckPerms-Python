"""
LuckPermsConfig 单元测试。
"""
from luckperms.config import LuckPermsConfig
from luckperms.query import PermissionQuery


class TestLuckPermsConfig:
    def test_default_values(self):
        cfg = LuckPermsConfig()
        assert cfg.apply_bukkit_child_permissions is True
        assert cfg.apply_implicit_wildcards is True
        assert cfg.primary_group_calculation == "stored"

    def test_custom_values(self):
        cfg = LuckPermsConfig(
            apply_bukkit_child_permissions=False,
            primary_group_calculation="parents-by-weight",
        )
        assert cfg.apply_bukkit_child_permissions is False
        assert cfg.apply_implicit_wildcards is True
        assert cfg.primary_group_calculation == "parents-by-weight"

    def test_query_uses_default_config(self):
        q = PermissionQuery({}, {})
        assert q._config.apply_bukkit_child_permissions is True

    def test_query_uses_custom_config(self):
        cfg = LuckPermsConfig(apply_implicit_wildcards=False)
        q = PermissionQuery({}, {}, config=cfg)
        assert q._config.apply_implicit_wildcards is False
