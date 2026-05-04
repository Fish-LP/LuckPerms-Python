"""
LuckPermsAPI —— Python 实现的 LuckPerms 风格权限系统。

核心组件：
- :class:`Node` — 权限节点（键、值、上下文、过期）
- :class:`User` / :class:`Group` — 权限持有者
- :class:`Track` — 晋升轨道
- :class:`PermissionQuery` — 上下文敏感查询引擎
- :class:`LuckPermsManager` — 统一管理层
- :class:`WebEditorSession` — Web Editor 集成

快速开始::

    from luckperms import LuckPermsManager

    mgr = LuckPermsManager("./lp_data")
    mgr.create_group("admin")
    mgr.group_add_node("admin", "plugin.*")
    mgr.create_user("123456")
    mgr.user_add_group("123456", "admin")

    assert mgr.check("123456", "plugin.chat") is True
"""
from .manager import LuckPermsManager
from .models import Group, Node, PermissionHolder, Track, User
from .query import PermissionQuery
from .storage import JSONBackend, StorageBackend, YAMLBackend
from .webeditor import BytebinClient, BytesocksClient, WebEditorSession

__version__ = "1.0.0"

__all__ = [
    "LuckPermsManager",
    "Group",
    "Node",
    "PermissionHolder",
    "Track",
    "User",
    "PermissionQuery",
    "StorageBackend",
    "YAMLBackend",
    "JSONBackend",
    "BytebinClient",
    "BytesocksClient",
    "WebEditorSession",
]
