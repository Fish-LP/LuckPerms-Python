"""
LuckPerms 原版配置项兼容。

参考原版 LuckPerms config.yml 中的关键配置项，
作为 PermissionQuery 的行为开关。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LuckPermsConfig:
    """LuckPerms 行为配置。

    当前为预留扩展点，后续可根据需要实现：
    - apply_bukkit_child_permissions: 是否应用 Bukkit 子权限
    - apply_implicit_wildcards: 是否应用隐式通配符
    - primary_group_calculation: 主组计算方式
    """

    apply_bukkit_child_permissions: bool = True
    apply_implicit_wildcards: bool = True
    primary_group_calculation: str = "stored"  # "stored" | "parents-by-weight"
