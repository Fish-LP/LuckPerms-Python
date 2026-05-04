# AGENTS

此文件用于记录和管理本仓库中与 Copilot/VS Code 自定义 Agent 相关的说明、模板与使用规范。

`LuckPermsAPI` 是一个纯 Python 实现的 LuckPerms 风格权限管理系统，支持 Web Editor 可视化编辑。本仓库的 Agent 配置围绕核心模型、查询引擎、存储层、Web Editor 集成和 CLI 命令层五个维度展开。

> 若后续需要新增或调整 Agent，请在本文件中补充条目，并同步创建对应的 `.instructions.md` 或 `.prompt.md` 配置文件。

## 目录

1. [概述](#概述)
2. [当前 Agent 列表](#当前-agent-列表)
3. [定义规范](#定义规范)
4. [Agent 详情](#agent-详情)
5. [维护建议](#维护建议)

## 概述

`AGENTS.md` 主要用于：

- 记录项目内自定义 Agent 的用途、范围与约定。
- 说明如何在仓库中新增、修改或清理 Agent 配置。
- 为开发者/维护者提供统一的 Agent 文档入口。
- 加速 Copilot/VS Code 理解 LuckPermsAPI 的架构分层（模型层、查询层、存储层、Web Editor 层、CLI 层）。

## 当前 Agent 列表

| Agent 名称 | 目标/用途 | 对应文件 | 触发场景 |
|---|---|---|---|
| `LuckPermsCore` | 理解核心模型与权限查询 | `AGENTS.md` | 设计 Node / User / Group / Track，理解权限检查流程 |
| `LuckPermsQuery` | 查询引擎与通配符语义 | `AGENTS.md` | 实现通配符匹配、上下文过滤、继承链解析 |
| `LuckPermsStorage` | 持久化与存储后端 | `AGENTS.md` | 自定义存储后端、数据迁移、序列化 |
| `LuckPermsWebEditor` | Web Editor 协议集成 | `AGENTS.md` | 接入 Bytebin/Bytesocks、打开编辑器、应用变更 |
| `LuckPermsCLI` | 命令行接口设计与实现 | `AGENTS.md` | 编写 lp 风格命令、子命令解析、交互式 Shell |

## 定义规范

建议在项目根目录或相关功能目录中，使用以下文件形式记录和定义 Agent：

- `AGENTS.md`：仓库层面的 Agent 文档与说明索引。
- `*.instructions.md`：Agent 的行为指令、设计说明、使用场景等。
- `*.prompt.md`：专门用于 prompt 文本或交互说明。

## Agent 详情

### Agent: LuckPermsCore

**目标**：帮助开发者快速理解 LuckPermsAPI 的核心模型、权限持有者和生命周期管理。

**触发场景**：

- 查询 `Node` / `User` / `Group` / `Track` 的字段含义和使用方式。
- 理解 `PermissionHolder` 的继承机制（节点管理、父组绑定）。
- 了解 `LuckPermsManager` 的 CRUD 流程和自动持久化策略。
- 设计新的权限节点或上下文约束。

**关键指令摘要**：

- `Node` 是原子权限单元，包含 `key`（支持 `*` 单段和 `**` 多段通配）、`value`（True/False）、`context`（键值对上下文）、`expiry`（过期时间戳）。
- `PermissionHolder` 是 `User` 和 `Group` 的抽象基类，管理 `_nodes` 列表和 `_parents` 继承链。
- `User` 通过 `unique_id` 标识，`Group` 通过 `name` 标识；两者均支持 `add_node` / `remove_node` / `add_parent` / `remove_parent`。
- `Track` 实现角色晋升路径（`promote` / `demote`），按 `groups` 列表顺序切换。
- `LuckPermsManager` 自动加载 `users.{ext}` / `groups.{ext}` / `tracks.{ext}`，任何修改后调用 `save_all()` 持久化。

**对应文件/路径**：

- `luckperms_api/models.py` — `Node` / `User` / `Group` / `Track` / `PermissionHolder`
- `luckperms_api/manager.py` — `LuckPermsManager`

---

### Agent: LuckPermsQuery

**目标**：指导开发者正确使用权限查询引擎，掌握通配符语义和上下文匹配。

**触发场景**：

- 需要检查用户是否拥有某权限（带或不带上下文）。
- 理解 `*` 与 `**` 的匹配差异。
- 处理显式拒绝（False）覆盖通配符允许（True）的优先级问题。
- 调试继承链中的权限冲突。

**关键指令摘要**：

- `PermissionQuery` 是查询引擎，持有 `users` 和 `groups` 字典引用。
- `check(user_id, permission, context)` 的查询流程：
  1. 收集用户自身节点 + BFS 遍历继承组节点。
  2. 过滤过期节点和上下文不匹配的节点。
  3. 按匹配优先级排序：精确匹配(0) > 单段通配*(1) > 多段通配**(2)。
  4. 同优先级下，weight 越小越优先（继承层级越近）。
  5. 同优先级同 weight，False 优先于 True（显式拒绝优先）。
- `*` 只匹配单段（`plugin.*` 匹配 `plugin.chat`，不匹配 `plugin.a.b`）。
- `**` 匹配任意多段（`plugin.**` 匹配 `plugin`、`plugin.chat`、`plugin.a.b.c`）。
- 上下文匹配规则：节点的 context 必须是查询 context 的子集（节点要求的所有键值对都必须满足）。

**对应文件/路径**：

- `luckperms_api/query.py` — `PermissionQuery`

---

### Agent: LuckPermsStorage

**目标**：帮助开发者自定义持久化后端，理解数据序列化和存储格式。

**触发场景**：

- 需要替换 YAML/JSON 为数据库（SQLite、Redis、MongoDB）。
- 理解数据文件结构和迁移策略。
- 实现自定义 `StorageBackend`。

**关键指令摘要**：

- `StorageBackend` 是协议类，定义 `extension: str`、`load(path: Path) -> dict`、`save(path: Path, data: dict)`。
- `YAMLBackend` 和 `JSONBackend` 是内置实现，分别生成 `.yml` 和 `.json` 文件。
- `LuckPermsStorage` 管理三个文件：`users.{ext}`、`groups.{ext}`、`tracks.{ext}`。
- 数据格式：每个文件顶层键为 `"users"` / `"groups"` / `"tracks"`，值为 `{id: holder_dict}` 字典。
- 自定义后端只需实现 `StorageBackend` 协议，在 `LuckPermsManager(data_dir, backend=MyBackend())` 中注入。

**对应文件/路径**：

- `luckperms_api/storage.py` — `StorageBackend` / `YAMLBackend` / `JSONBackend` / `LuckPermsStorage`

---

### Agent: LuckPermsWebEditor

**目标**：帮助开发者集成 LuckPerms 官方 Web Editor，实现可视化权限管理。

**触发场景**：

- 需要一键打开浏览器编辑器。
- 理解 Bytebin + Bytesocks 的双通道通信协议。
- 处理编辑器返回的变更数据并应用到本地。
- 调试 WebSocket 连接或数据同步问题。

**关键指令摘要**：

- Web Editor 通信分为两层：
  1. **Bytebin（HTTP）**：将权限数据 GZIP 压缩后 POST 到 `https://usercontent.luckperms.net/post`，服务端返回 `Location` Header 或 JSON `key`。
  2. **Bytesocks（WebSocket）**：先 HTTP GET `https://usersockets.luckperms.net/create` 申请 channel key，再连接 `wss://usersockets.luckperms.net/{key}`，发送 `putcode` 消息，监听 `apply` 变更请求。
- 编辑器 URL 格式：`https://luckperms.net/editor/{code}#{channel}`。
- `WebEditorSession` 整合流程：`open()` → 上传数据 → 申请 channel → 生成 URL → 启动 WebSocket → 等待变更。
- 收到 `apply` 消息后，调用 `apply_changes(payload)` 重建全部 users/groups/tracks 并持久化。
- `BytebinClient` 支持自定义端点（自建 bytebin 服务）。
- `BytesocksClient` 支持 `on_apply` 回调，自动处理 ping/pong 心跳。

**对应文件/路径**：

- `luckperms_api/webeditor/session.py` — `WebEditorSession`
- `luckperms_api/webeditor/bytebin.py` — `BytebinClient`
- `luckperms_api/webeditor/websocket.py` — `BytesocksClient`

---

### Agent: LuckPermsCLI

**目标**：指导开发者实现 `lp` 风格的命令行接口，支持子命令解析、交互式 Shell 和脚本化调用。

**触发场景**：

- 需要为 LuckPermsAPI 添加命令行入口（类似 Minecraft 中 `/lp` 命令）。
- 设计 `lp user`、`lp group`、`lp track`、`lp editor` 等子命令体系。
- 实现命令补全、权限检查输出格式化、批量操作。
- 将 CLI 与 `LuckPermsManager` 集成，支持 `--data-dir` 指定存储路径。

**关键指令摘要**：

- CLI 参考 Minecraft LuckPerms 插件的 `/lp` 命令结构，核心子命令：
  - `lp user <id> info` — 查看用户详情（节点、继承组、上下文）。
  - `lp user <id> permission set <node> [true/false] [context...]` — 设置/移除权限节点。
  - `lp user <id> parent add/remove <group>` — 管理用户所属组。
  - `lp user <id> promote/demote <track>` — 沿轨道晋升/降级。
  - `lp group <name> info` — 查看组详情。
  - `lp group <name> permission set <node> ...` — 设置组权限。
  - `lp group <name> inherit <parent>` — 设置组继承关系。
  - `lp track <name> info/append/insert/remove` — 轨道管理。
  - `lp editor` — 一键启动 Web Editor 会话并输出 URL。
  - `lp check <user> <node> [context...]` — 检查用户是否拥有某权限。
  - `lp sync` — 强制重新加载磁盘数据。
  - `lp info` — 显示系统统计信息。
- **诊断命令**：
  - `lp verbose <user> [--filter <pattern>]` — 实时拦截并打印该用户的权限检查调用，显示每次检查的节点、上下文、结果、来源（自身节点/继承组/通配符匹配）。通过 `VerbosePermissionQuery` 包装 `PermissionQuery` 实现拦截，支持 `--filter` glob 过滤和 `--output` 日志导出。
  - `lp tree <user|group> [--depth N]` — 以树形结构递归展示权限继承链，每层显示组名、权重、直接节点数。使用 BFS/DFS 遍历，支持 `--depth` 限制递归深度，避免循环继承导致无限输出。节点后标注 `[self]` 或 `[inherited from <group>]` 帮助溯源。
- `lp shell` — 进入交互式 REPL，支持 Tab 补全和历史记录。
- 命令解析使用 `argparse` 或 `click`，支持嵌套子命令。
- 所有写操作自动调用 `mgr.save_all()` 持久化。
- 输出使用表格或树形格式化（参考 `rich` 库），支持 `--json` 脚本化输出。

**对应文件/路径**：

- `luckperms/cli.py` — CLI 入口与命令解析（计划中）
- `luckperms/cli/verbose.py` — `VerbosePermissionQuery` 拦截器（计划中）
- `luckperms/cli/tree.py` — 继承树生成与渲染（计划中）
- `luckperms/manager.py` — `LuckPermsManager`（CRUD 数据源）

## 维护建议

- 当新增或变更自定义 Agent 文件时，务必在本文件中同步更新说明。
- 本仓库 Agent 统一以 `AGENTS.md` 作为索引页面，各模块详细指令可拆分到对应目录的 `.instructions.md`。
- 定期检查是否存在过时 Agent 配置并移除无效条目。
- 新增 Agent 时，优先覆盖 LuckPermsAPI 的核心分层（模型层、查询层、存储层、Web Editor 层、CLI 层），避免过度细分导致维护成本上升。
