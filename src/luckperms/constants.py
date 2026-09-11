"""
LuckPermsAPI 共享常量。

集中管理跨模块复用的魔法值（版本、协议、前缀、存储文件名等），
避免在多处重复硬编码。
"""
from __future__ import annotations

# ------------------------------------------------------------------
# 版本与 Web Editor 协议
# ------------------------------------------------------------------
PLUGIN_VERSION = "5.4.0"
EDITOR_PROTOCOL_VERSION = 1

USER_AGENT = f"LuckPerms/{PLUGIN_VERSION}"
EDITOR_USER_AGENT = f"LuckPerms/{PLUGIN_VERSION}/editor"

DEFAULT_BYTEBIN_URL = "https://usercontent.luckperms.net"
DEFAULT_BYTESOCKS_URL = "https://usersockets.luckperms.net"
EDITOR_BASE_URL = "https://luckperms.net/editor"

# ------------------------------------------------------------------
# 数据模型
# ------------------------------------------------------------------
DEFAULT_GROUP_NAME = "default"
GROUP_NODE_PREFIX = "group."
WEIGHT_NODE_PREFIX = "weight."
META_PREFIXES = ("prefix.", "suffix.", "displayname.", WEIGHT_NODE_PREFIX)

# ------------------------------------------------------------------
# 查询引擎
# ------------------------------------------------------------------
# 继承优先级编码：priority = depth * STEP + (STEP - weight)
# 组 weight 需小于 STEP，否则会侵入继承深度位
NODE_PRIORITY_DEPTH_STEP = 10_000

# ------------------------------------------------------------------
# 存储
# ------------------------------------------------------------------
DATA_FILE_STEM = "luckperms"
