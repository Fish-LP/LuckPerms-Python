# LuckPermsAPI

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-206%20passed-brightgreen)](tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Python 实现的 [LuckPerms](https://luckperms.net/) 风格权限管理系统，完整支持 [Web Editor](https://luckperms.net/editor) 可视化编辑，与原版 Java 版 LuckPerms v5.4+ **核心权限解析结果逐条一致**。

## 特性

- **纯 Python 库** — 零框架依赖，可在任何 Python 3.10+ 项目中使用
- **用户/组/轨道** — 完整的 CRUD，支持上下文绑定、过期时间、继承链
- **上下文敏感权限** — 支持 `{"world": "nether"}` 等上下文约束，支持瞬态上下文（运行时动态附加）
- **通配符系统** — `*` 单段匹配，`**` 多段匹配，优先级与原版一致
- **原版兼容 Weight 排序** — 继承优先级按组 Weight 从高到低排序，同 Weight 按继承深度排序
- **元数据节点** — `prefix` / `suffix` / `displayname` / `weight` 作为权限节点，与原版 Web Editor 格式兼容
- **过期节点自动清理** — 保存时自动清理过期节点，Web Editor 中过滤过期数据
- **Web Editor 集成** — 一键打开浏览器编辑器，实时同步变更
- **交互式 CLI** — 内置 `lp` 命令行工具，支持 Tab 补全、继承树可视化、权限监听
- **YAML/JSON 持久化** — 可替换为自定义存储后端

## 安装

### 从 PyPI 安装（推荐）

```bash
pip install LuckPermsAPI
```

### 带 CLI 支持（富文本界面 + Tab 补全）

```bash
pip install "luckperms-python[cli]"
```

### 源码安装（开发模式）

```bash
git clone https://github.com/Fish-LP/LuckPerms-Python.git
cd LuckPerms-Python
pip install -e ".[dev]"
```

## 快速开始

```python
from luckperms import LuckPermsManager

# 初始化管理器（数据自动保存到 ./lp_data/）
mgr = LuckPermsManager("./lp_data")

# 创建组和权限
mgr.create_group("admin", "管理员", weight=100)
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

### 上下文与临时权限

```python
# 上下文权限：仅在 nether 世界可以 fly
mgr.user_add_node("123456", "plugin.fly", True, {"world": "nether"})
assert mgr.check("123456", "plugin.fly", {"world": "nether"}) is True
assert mgr.check("123456", "plugin.fly", {"world": "overworld"}) is False

# 临时权限：2 秒后自动过期
mgr.user_add_node("123456", "plugin.temp", True, duration=2)
```

### 继承链与 Track 晋升

```python
# 构建继承链: default <- vip <- mod <- admin
mgr.create_group("default", weight=0)
mgr.create_group("vip", weight=50)
mgr.create_group("mod", weight=100)
mgr.create_group("admin", weight=200)

mgr.group_inherit("vip", "default")
mgr.group_inherit("mod", "vip")
mgr.group_inherit("admin", "mod")

# 创建晋升轨道
mgr.create_track("staff", ["default", "vip", "mod", "admin"])

# 用户沿轨道晋升
mgr.promote("123456", "staff")   # -> default
mgr.promote("123456", "staff")   # -> vip
mgr.demote("123456", "staff")    # -> default
```

## CLI 使用

安装 CLI 依赖后，直接使用 `lp` 命令进入交互式终端：

```bash
# 进入交互式 Shell
lp

# 或指定数据目录
lp --data-dir ./my_data

# 或直接执行单条命令
lp user create alice --display-name Alice
lp group create admin --weight 100
lp user alice permission set plugin.* true
lp check alice plugin.chat
```

### CLI 命令速查

| 命令                                             | 说明            |
| ------------------------------------------------ | --------------- |
| `user <id> info`                                 | 查看用户详情    |
| `user <id> permission set <node> [T/F] [ctx...]` | 设置权限        |
| `user <id> parent add <group>`                   | 加入组          |
| `user <id> promote <track>`                      | 沿轨道晋升      |
| `group <name> info`                              | 查看组详情      |
| `group <name> setweight <n>`                     | 设置权重        |
| `track <name> info`                              | 查看轨道        |
| `check <user> <node> [ctx...]`                   | 快捷权限检查    |
| `tree <user|group> [--depth N]`                  | 继承树可视化    |
| `editor`                                         | 启动 Web Editor |
| `sync`                                           | 重新加载数据    |

## Web Editor 集成

```python
import asyncio
from luckperms import LuckPermsManager, WebEditorSession

mgr = LuckPermsManager("./lp_data")

async def main():
    session = WebEditorSession(
        get_payload=mgr.to_webeditor_payload,
        apply_changes=mgr.apply_webeditor_changes,
    )
    url = await session.open()
    print(f"打开浏览器访问: {url}")
    # 用户在编辑器中修改并 Save 后，变更自动应用并持久化
    # await session.close()

asyncio.run(main())
```

生成的 URL 格式：`https://luckperms.net/editor/<bytebin-code>#<bytesocks-channel>`

## 项目结构

```
luckperms/
├── __init__.py           # 包导出
├── models.py             # Node / User / Group / Track / PermissionHolder
├── query.py              # PermissionQuery（通配符、继承、上下文、Weight 排序）
├── storage.py            # StorageBackend / YAMLBackend / JSONBackend
├── manager.py            # LuckPermsManager（CRUD + Web Editor 序列化）
├── config.py             # LuckPermsConfig（原版配置项兼容）
├── cli.py                # 交互式 REPL 与命令解析
└── webeditor/
    ├── bytebin.py        # Bytebin HTTP API
    ├── websocket.py      # Bytesocks WebSocket
    └── session.py        # WebEditorSession
```

## 开发

### 运行测试

```bash
pytest tests/ -v
```

### 带覆盖率报告

```bash
pytest tests/ -v --cov=src/luckperms --cov-report=term-missing
```

### 代码风格（pre-commit）

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

## 兼容性

与原版 LuckPerms Java 版核心行为对齐，已通过 206 项自动化测试验证：

- ✅ 节点模型与 CRUD
- ✅ 通配符解析（`*` / `**`）与优先级
- ✅ 上下文敏感检查（子集匹配）
- ✅ 显式拒绝覆盖通配符
- ✅ 继承优先级与 Weight 排序
- ✅ 元数据节点（prefix / suffix / weight）
- ✅ 瞬态上下文（Transient Contexts）
- ✅ Track 晋升/降级边界行为
- ✅ Web Editor 增量/全量变更协议
- ✅ 过期节点自动清理

详见 [`对齐状态确认书.md`](对齐状态确认书.md)。

## 许可证

MIT License © Fish-LP
