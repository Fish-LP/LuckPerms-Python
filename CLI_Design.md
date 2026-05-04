
# 更新 CLI_Design.md，补充 verbose 和 tree

cli_design = '''# CLI 设计文档

参考 LuckPerms 官方 Minecraft 插件的 `/lp` 命令体系，为 LuckPermsAPI 实现一套完整的命令行接口。

## 设计目标

- **命令风格**：完全对标 `/lp` 子命令结构，降低 Minecraft 管理员迁移成本。
- **输出格式**：默认人类友好表格，支持 `--json` / `--yaml` 脚本化输出。
- **交互体验**：支持 `lp shell` 交互式 REPL，带历史记录和 Tab 补全。
- **数据目录**：通过 `--data-dir` 全局选项指定，默认 `./lp_data`。
- **自动持久化**：所有写操作自动调用 `save_all()`，无需手动同步。

## 命令总览

```
lp [--data-dir DIR] [--format {table,json,yaml}] <command> [args...]
```

### 用户管理 (lp user)

| 命令 | 说明 |
|---|---|
| `lp user <id> info` | 查看用户详情（ID、显示名、节点数、继承组） |
| `lp user <id> permission info` | 列出用户所有权限节点 |
| `lp user <id> permission set <node> [true/false] [--context k=v...] [--duration N]` | 设置权限节点 |
| `lp user <id> permission unset <node> [--context k=v...]` | 移除权限节点 |
| `lp user <id> permission check <node> [--context k=v...]` | 检查用户是否拥有某权限 |
| `lp user <id> parent info` | 列出用户继承的组 |
| `lp user <id> parent add <group>` | 将用户加入组 |
| `lp user <id> parent remove <group>` | 将用户移出组 |
| `lp user <id> promote <track>` | 沿轨道晋升 |
| `lp user <id> demote <track>` | 沿轨道降级 |
| `lp user create <id> [--display-name NAME]` | 创建用户 |
| `lp user delete <id>` | 删除用户 |
| `lp user list` | 列出所有用户 |

### 组管理 (lp group)

| 命令 | 说明 |
|---|---|
| `lp group <name> info` | 查看组详情 |
| `lp group <name> permission info` | 列出组权限节点 |
| `lp group <name> permission set <node> ...` | 设置组权限 |
| `lp group <name> permission unset <node> ...` | 移除组权限 |
| `lp group <name> parent info` | 列出父组 |
| `lp group <name> parent add <parent>` | 添加继承 |
| `lp group <name> parent remove <parent>` | 移除继承 |
| `lp group <name> setweight <n>` | 设置权重 |
| `lp group create <name> [--display-name NAME] [--weight N]` | 创建组 |
| `lp group delete <name>` | 删除组 |
| `lp group list` | 列出所有组 |

### 轨道管理 (lp track)

| 命令 | 说明 |
|---|---|
| `lp track <name> info` | 查看轨道详情 |
| `lp track <name> append <group>` | 追加组到轨道 |
| `lp track <name> insert <index> <group>` | 插入组 |
| `lp track <name> remove <group>` | 从轨道移除组 |
| `lp track create <name> [group1 group2 ...]` | 创建轨道 |
| `lp track delete <name>` | 删除轨道 |
| `lp track list` | 列出所有轨道 |

### 诊断与可视化 (lp verbose / lp tree)

| 命令 | 说明 |
|---|---|
| `lp verbose <user> [--filter <pattern>]` | 实时监听该用户的权限检查，打印每次检查的节点、上下文、结果、来源（自身/继承/通配）。按 `Ctrl+C` 停止。 |
| `lp verbose off` | 关闭所有 verbose 监听（若后台运行）。 |
| `lp tree <user\|group> [--depth N]` | 以树形结构展示权限继承链，每层显示组名、权重、节点数。支持限制递归深度。 |

#### lp verbose 详细设计

`lp verbose` 是权限排查利器，实现原理：

1. **拦截层**：`VerbosePermissionQuery` 继承/包装 `PermissionQuery`，重写 `check()` 方法。
2. **事件流**：每次 `check(user, node, context)` 被调用时，记录：
   - `timestamp` — 检查时间
   - `permission` — 被检查的权限字符串
   - `context` — 查询上下文
   - `result` — True / False / Undefined
   - `origin` — 结果来源：
     - `self` — 用户自身节点（weight=0）
     - `inherit:<group>` — 继承自某组（weight=N）
     - `wildcard:*` — 单段通配符匹配
     - `wildcard:**` — 多段通配符匹配
     - `default` — 无任何匹配，返回默认 False
   - `matched_node` — 实际命中的节点 key（如 `plugin.*`）
3. **输出格式**：实时打印一行，例如：

   ```
   [14:32:01] steve | plugin.chat | ctx={} | RESULT=true | origin=self | matched=plugin.chat
   [14:32:02] steve | plugin.banned | ctx={} | RESULT=false | origin=inherit:admin | matched=plugin.banned
   [14:32:03] steve | plugin.fly | ctx={world=creative} | RESULT=true | origin=inherit:vip | matched=plugin.fly
   ```

4. **过滤**：`--filter` 支持 glob 过滤权限字符串，仅打印匹配的节点。
5. **持久化**：支持 `--output file.json` 将 verbose 日志写入文件，供后续分析。

#### lp tree 详细设计

`lp tree` 展示权限继承的层级结构，实现原理：

1. **递归遍历**：从目标 User 或 Group 出发，BFS/DFS 遍历继承链。
2. **节点聚合**：在每个组层级上，汇总该组直接拥有的节点（不含继承节点，避免重复）。
3. **树形输出**：使用 `rich.Tree` 或 ASCII 树，例如：

   ```
   steve (user)
   └── default (group, weight=0)
       ├── plugin.chat = true
       └── plugin.spawn = true
   └── vip (group, weight=10) [via track:staff]
       ├── plugin.fly = true
       └── plugin.colorchat = true
   └── helper (group, weight=50)
       ├── plugin.kick = true
       ├── plugin.mute = true
       └── plugin.warn = true
   ```

4. **深度控制**：`--depth N` 限制递归层数，防止循环继承导致无限输出。
5. **权限溯源**：每个节点后标注 `[inherited from <group>]` 或 `[self]`，帮助管理员理解权限来源。

### 系统命令

| 命令 | 说明 |
|---|---|
| `lp editor` | 启动 Web Editor 并输出 URL |
| `lp check <user> <node> [--context k=v...]` | 快捷权限检查 |
| `lp sync` | 重新从磁盘加载数据 |
| `lp info` | 显示统计信息（用户数、组数、轨道数） |
| `lp shell` | 进入交互式 Shell |
| `lp export <file>` | 导出全部数据到 JSON/YAML |
| `lp import <file>` | 从 JSON/YAML 导入数据 |

## 输出格式

### 默认表格（rich.Table）

```
┌─────────┬─────────────┬────────┬─────────────────────────────┐
│ Node    │ Value       │ Expiry │ Context                     │
├─────────┼─────────────┼────────┼─────────────────────────────┤
│ plugin.*│ True        │ Never  │ {}                          │
│ plugin.b│ False       │ Never  │ {}                          │
│ plugin.f│ True        │ 1h     │ {"world": "creative"}       │
└─────────┴─────────────┴────────┴─────────────────────────────┘
```

### --json 输出

```json
{
  "user": {
    "id": "steve",
    "display_name": "Steve",
    "nodes": [...],
    "parents": ["default"]
  }
}
```

## 实现架构

```
luckperms/
├── cli/
│   ├── __init__.py      # 包导出
│   ├── main.py          # argparse 入口与全局选项
│   ├── formatters.py    # 表格/JSON/YAML 输出格式化
│   ├── verbose.py       # VerbosePermissionQuery 拦截器
│   ├── tree.py          # 继承树生成与渲染
│   ├── commands/
│   │   ├── __init__.py
│   │   ├── user.py      # lp user 子命令
│   │   ├── group.py     # lp group 子命令
│   │   ├── track.py     # lp track 子命令
│   │   ├── system.py    # lp editor / sync / info / check
│   │   └── shell.py     # lp shell 交互式 REPL
│   └── completer.py     # shell 模式下的 Tab 补全
```

## 依赖

- `click` 或 `argparse`：命令解析（优先 `argparse`，零依赖）
- `rich`：终端表格与彩色输出（可选依赖 `[cli]`）
- `prompt_toolkit`：交互式 Shell 补全（可选依赖 `[cli]`）

## pyproject.toml 配置

```toml
[project.optional-dependencies]
dev = ["pytest>=7.0", "pytest-cov", "pytest-asyncio"]
cli = ["rich>=13.0", "prompt_toolkit>=3.0"]

[project.scripts]
lp = "luckperms.cli.main:main"
```

## 使用示例

```bash
# 创建组并设置权限
lp group create admin --weight 100
lp group admin permission set plugin.* true
lp group admin permission set plugin.banned false

# 创建用户并加入组
lp user create steve --display-name Steve
lp user steve parent add admin

# 检查权限
lp check steve plugin.chat
lp user steve permission check plugin.chat --context world=creative

# 实时监听权限检查（排查问题）
lp verbose steve --filter "plugin.*"
# 输出：
# [14:32:01] steve | plugin.chat | ctx={} | RESULT=true | origin=self | matched=plugin.chat

# 查看权限继承树
lp tree steve --depth 3

# 启动编辑器
lp editor

# 交互式 Shell
lp shell
>>> user steve info
>>> group admin permission info
```
