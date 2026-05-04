# LuckPermsAPI

Python 实现的 [LuckPerms](https://luckperms.net/) 风格权限管理系统，完整支持 [Web Editor](https://luckperms.net/editor) 可视化编辑。

## 特性

- **纯 Python 库** — 零框架依赖，可在任何 Python 3.10+ 项目中使用
- **用户/组/轨道** — 完整的 CRUD，支持上下文绑定、过期时间、继承链
- **上下文敏感权限** — 支持 `{"group_id": "123456"}` 等上下文约束
- **通配符系统** — `*` 单段匹配，`**` 多段匹配
- **Web Editor 集成** — 一键打开浏览器编辑器，实时同步变更
- **YAML/JSON 持久化** — 可替换为自定义存储后端

## 安装

```bash
pip install -e .
# 或带测试依赖
pip install -e ".[dev]"
```

## 快速开始

```python
from luckperms_api import LuckPermsManager

# 初始化管理器（数据自动保存到 ./lp_data/）
mgr = LuckPermsManager("./lp_data")

# 创建组和权限
mgr.create_group("admin", "管理员")
mgr.group_add_node("admin", "plugin.*")

# 创建用户并加入组
mgr.create_user("123456", "Alice")
mgr.user_add_group("123456", "admin")

# 权限检查
assert mgr.check("123456", "plugin.chat") is True
assert mgr.check("123456", "plugin.admin", {"group_id": "789"}) is True

# 显式拒绝覆盖通配符
mgr.user_add_node("123456", "plugin.banned", False)
assert mgr.check("123456", "plugin.banned") is False
```

## Web Editor 使用

```python
import asyncio
from luckperms_api import LuckPermsManager, WebEditorSession

mgr = LuckPermsManager("./lp_data")

async def main():
    session = WebEditorSession(
        get_payload=mgr.to_webeditor_payload,
        apply_changes=mgr.apply_webeditor_changes,
    )
    url = await session.open()
    print(f"打开浏览器访问: {url}")
    # 用户在编辑器中修改并 Save 后，变更自动应用
    # await session.close()

asyncio.run(main())
```

## 数据文件

```
lp_data/
├── users.yml      # 用户权限数据
├── groups.yml     # 组权限数据
└── tracks.yml     # 晋升轨道数据
```

## 架构

```
luckperms_api/
├── __init__.py           # 包导出
├── models.py             # Node / User / Group / Track / PermissionHolder
├── query.py              # PermissionQuery（通配符、继承、上下文）
├── storage.py            # StorageBackend / YAMLBackend / JSONBackend
├── manager.py            # LuckPermsManager（CRUD + Web Editor 序列化）
└── webeditor/
    ├── bytebin.py        # Bytebin HTTP API
    ├── websocket.py      # Bytesocks WebSocket
    └── session.py        # WebEditorSession
```

## 测试

```bash
pytest tests/ -v
```

## 参考

- [LuckPerms Wiki](https://luckperms.net/wiki/Home)
- [LuckPerms Web Editor](https://luckperms.net/wiki/Web-Editor)
- [LuckPerms-Mirai](https://github.com/Karlatemp/LuckPerms-Mirai/)
