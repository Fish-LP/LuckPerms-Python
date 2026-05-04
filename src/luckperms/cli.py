#!/usr/bin/env python3
"""
LuckPermsAPI 交互式终端入口 (lp shell)。

提供类似 Minecraft /lp 命令的交互式 REPL，支持：
- 用户/组/轨道的 CRUD 与权限管理
- 权限检查 (check)
- Web Editor 一键启动 (editor)
- 手动应用 edits (applyedits)
- 实时权限监听 (verbose)
- 继承树可视化 (tree)
- Tab 自动补全与历史记录
- 富文本表格输出
- 命令前缀兼容: lp, /lp, 或无前缀

运行方式::

    python -m luckperms.cli
    # 或安装后
    lp

依赖::

    pip install rich prompt_toolkit
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shlex
import sys
import tempfile
from typing import Any, Optional

# 尝试导入可选依赖
try:
    from rich.console import Console
    from rich.table import Table
    from rich.tree import Tree as RichTree
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.document import Document
    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False

from .manager import LuckPermsManager
from .models import Group, Node, Track, User
from .webeditor import WebEditorSession


# ------------------------------------------------------------------
# 输出格式化
# ------------------------------------------------------------------
class Formatter:
    """兼容 rich 与纯文本的输出格式化器。"""

    def __init__(self, debug: bool = False) -> None:
        self.console = Console() if HAS_RICH else None
        self.debug = debug

    def print(self, text: str = "") -> None:
        if self.console:
            self.console.print(text)
        else:
            print(text)

    def error(self, text: str) -> None:
        if self.console:
            self.console.print(f"[red]✗ {text}[/red]")
        else:
            print(f"✗ {text}")

    def success(self, text: str) -> None:
        if self.console:
            self.console.print(f"[green]✓ {text}[/green]")
        else:
            print(f"✓ {text}")

    def info(self, text: str) -> None:
        if self.console:
            self.console.print(f"[cyan]ℹ {text}[/cyan]")
        else:
            print(f"ℹ {text}")

    def debug(self, text: str) -> None:
        if self.debug:
            if self.console:
                self.console.print(f"[dim]◆ {text}[/dim]")
            else:
                print(f"◆ {text}")

    def table_nodes(self, nodes: list[Node], title: str = "Nodes") -> None:
        if not nodes:
            self.print(f"  (无 {title})")
            return
        if self.console:
            table = Table(title=title, show_header=True, header_style="bold magenta")
            table.add_column("Key", style="cyan", no_wrap=True)
            table.add_column("Value", style="green")
            table.add_column("Context", style="yellow")
            table.add_column("Expiry", style="dim")
            import time
            for n in nodes:
                ctx = ", ".join(f"{k}={v}" for k, v in n.context.items()) or "-"
                exp = "Never" if n.expiry is None else f"{int(n.expiry - time.time())}s"
                val = "[green]True[/green]" if n.value else "[red]False[/red]"
                table.add_row(n.key, val, ctx, exp)
            self.console.print(table)
        else:
            self.print(f"--- {title} ---")
            for n in nodes:
                ctx = f" context={n.context}" if n.context else ""
                exp = f" expiry={n.expiry}" if n.expiry else ""
                self.print(f"  {n.key} = {n.value}{ctx}{exp}")

    def table_users(self, users: list[User]) -> None:
        if self.console:
            table = Table(title="Users", show_header=True, header_style="bold magenta")
            table.add_column("ID", style="cyan")
            table.add_column("Display Name", style="green")
            table.add_column("Groups", style="yellow")
            table.add_column("Nodes", style="dim")
            for u in users:
                groups = ", ".join(u.parents) or "-"
                table.add_row(u.unique_id, u.display_name, groups, str(len(u.nodes)))
            self.console.print(table)
        else:
            self.print("--- Users ---")
            for u in users:
                groups = ", ".join(u.parents) or "-"
                self.print(f"  {u.unique_id} | {u.display_name} | groups={groups} | nodes={len(u.nodes)}")

    def table_groups(self, groups: list[Group]) -> None:
        if self.console:
            table = Table(title="Groups", show_header=True, header_style="bold magenta")
            table.add_column("Name", style="cyan")
            table.add_column("Display Name", style="green")
            table.add_column("Weight", style="yellow")
            table.add_column("Parents", style="dim")
            table.add_column("Nodes", style="dim")
            for g in groups:
                parents = ", ".join(g.parents) or "-"
                table.add_row(g.name, g.display_name, str(g.weight), parents, str(len(g.nodes)))
            self.console.print(table)
        else:
            self.print("--- Groups ---")
            for g in groups:
                parents = ", ".join(g.parents) or "-"
                self.print(f"  {g.name} | {g.display_name} | weight={g.weight} | parents={parents} | nodes={len(g.nodes)}")

    def table_tracks(self, tracks: list[Track]) -> None:
        if self.console:
            table = Table(title="Tracks", show_header=True, header_style="bold magenta")
            table.add_column("Name", style="cyan")
            table.add_column("Groups", style="green")
            for t in tracks:
                table.add_row(t.name, " -> ".join(t.groups))
            self.console.print(table)
        else:
            self.print("--- Tracks ---")
            for t in tracks:
                self.print(f"  {t.name}: {' -> '.join(t.groups)}")

    def tree_holder(self, mgr: LuckPermsManager, holder_id: str, depth: int = 5) -> None:
        """以树形展示继承链。"""
        user = mgr.get_user(holder_id)
        group = mgr.get_group(holder_id)
        target = user or group
        if not target:
            self.error(f"持有者 '{holder_id}' 不存在")
            return

        if self.console:
            root_label = f"[bold]{holder_id}[/bold] ({"user" if user else "group"})"
            tree = RichTree(root_label)
            self._build_tree_rich(mgr, target, tree, depth, set())
            self.console.print(tree)
        else:
            self.print(f"{holder_id} ({"user" if user else "group"})")
            self._build_tree_plain(mgr, target, 0, depth, set())

    def _build_tree_rich(self, mgr: LuckPermsManager, target: Any, tree: Any, depth: int, visited: set[str]) -> None:
        if depth <= 0:
            return
        parents = getattr(target, "parents", [])
        for pname in parents:
            if pname in visited:
                continue
            visited.add(pname)
            g = mgr.get_group(pname)
            if not g:
                continue
            label = f"[cyan]{g.name}[/cyan] (weight={g.weight}, nodes={len(g.nodes)})"
            branch = tree.add(label)
            for n in g.nodes:
                val = "[green]T[/green]" if n.value else "[red]F[/red]"
                branch.add(f"{n.key} = {val}")
            self._build_tree_rich(mgr, g, branch, depth - 1, visited)

    def _build_tree_plain(self, mgr: LuckPermsManager, target: Any, indent: int, depth: int, visited: set[str]) -> None:
        if depth <= 0:
            return
        parents = getattr(target, "parents", [])
        prefix = "  " * indent
        for pname in parents:
            if pname in visited:
                self.print(f"{prefix}└── {pname} [循环引用，已省略]")
                continue
            visited.add(pname)
            g = mgr.get_group(pname)
            if not g:
                continue
            self.print(f"{prefix}└── {g.name} (weight={g.weight}, nodes={len(g.nodes)})")
            for n in g.nodes:
                val = "T" if n.value else "F"
                self.print(f"{prefix}    ├── {n.key} = {val}")
            self._build_tree_plain(mgr, g, indent + 1, depth - 1, visited)


# ------------------------------------------------------------------
# 自动补全
# ------------------------------------------------------------------
class LPCompleter(Completer):
    """LuckPerms 命令自动补全。"""

    COMMANDS = [
        "user ", "group ", "track ",
        "check ", "verbose ", "tree ",
        "editor", "applyedits ", "sync", "info", "help", "exit", "quit",
    ]

    USER_SUB = ["info", "permission", "parent", "promote", "demote", "create", "delete", "list"]
    PERM_SUB = ["set ", "unset ", "check ", "info"]
    PARENT_SUB = ["add ", "remove ", "info"]
    GROUP_SUB = ["info", "permission", "parent", "setweight", "create", "delete", "list"]
    TRACK_SUB = ["info", "append", "insert", "remove", "create", "delete", "list"]

    def __init__(self, mgr: LuckPermsManager) -> None:
        self.mgr = mgr

    def get_completions(self, document: Document, complete_event: Any) -> Any:
        text = document.text_before_cursor
        words = text.split()

        if words and words[0].lower() in ("lp", "/lp"):
            words = words[1:]
            text = " ".join(words)

        if not words:
            for cmd in self.COMMANDS:
                yield Completion(cmd, start_position=0)
            return

        if len(words) == 1 and not text.endswith(" "):
            for cmd in self.COMMANDS:
                if cmd.startswith(words[0]):
                    yield Completion(cmd, start_position=-len(words[0]))
            return

        cmd = words[0]
        if cmd in ("user", "verbose", "tree") and len(words) == 2 and not text.endswith(" "):
            for uid in self.mgr._users:
                if uid.startswith(words[1]):
                    yield Completion(uid, start_position=-len(words[1]))
            return
        if cmd == "group" and len(words) == 2 and not text.endswith(" "):
            for name in self.mgr._groups:
                if name.startswith(words[1]):
                    yield Completion(name, start_position=-len(words[1]))
            return
        if cmd == "track" and len(words) == 2 and not text.endswith(" "):
            for name in self.mgr._tracks:
                if name.startswith(words[1]):
                    yield Completion(name, start_position=-len(words[1]))
            return
        if cmd == "check" and len(words) == 2 and not text.endswith(" "):
            for uid in self.mgr._users:
                if uid.startswith(words[1]):
                    yield Completion(uid, start_position=-len(words[1]))
            return

        if cmd == "user" and len(words) >= 2:
            sub = words[2] if len(words) > 2 else ""
            if len(words) == 2 and text.endswith(" "):
                for s in self.USER_SUB:
                    yield Completion(s + " ", start_position=0)
                return
            if len(words) == 3 and not text.endswith(" "):
                for s in self.USER_SUB:
                    if s.startswith(sub):
                        yield Completion(s + " ", start_position=-len(sub))
                return

        if cmd == "group" and len(words) >= 2:
            sub = words[2] if len(words) > 2 else ""
            if len(words) == 2 and text.endswith(" "):
                for s in self.GROUP_SUB:
                    yield Completion(s + " ", start_position=0)
                return
            if len(words) == 3 and not text.endswith(" "):
                for s in self.GROUP_SUB:
                    if s.startswith(sub):
                        yield Completion(s + " ", start_position=-len(sub))
                return

        if cmd == "track" and len(words) >= 2:
            sub = words[2] if len(words) > 2 else ""
            if len(words) == 2 and text.endswith(" "):
                for s in self.TRACK_SUB:
                    yield Completion(s + " ", start_position=0)
                return
            if len(words) == 3 and not text.endswith(" "):
                for s in self.TRACK_SUB:
                    if s.startswith(sub):
                        yield Completion(s + " ", start_position=-len(sub))
                return


# ------------------------------------------------------------------
# 命令解析与执行
# ------------------------------------------------------------------
class LPCommand:
    """命令处理器。"""

    def __init__(self, mgr: LuckPermsManager, fmt: Formatter) -> None:
        self.mgr = mgr
        self.fmt = fmt
        self._verbose_user: Optional[str] = None

    def _strip_prefix(self, raw: str) -> str:
        """去掉可选前缀 lp / /lp，兼容原版命令习惯。"""
        raw = raw.strip()
        parts = raw.split(maxsplit=1)
        if parts and parts[0].lower() in ("lp", "/lp"):
            return parts[1] if len(parts) > 1 else ""
        return raw

    def _safe_split(self, raw: str) -> list[str]:
        """安全地分割命令，处理引号不匹配、反斜杠等异常输入。"""
        try:
            return shlex.split(raw)
        except ValueError as e:
            # 尝试清理后重试
            cleaned = raw.replace("\\", "")
            try:
                return shlex.split(cleaned)
            except ValueError:
                raise ValueError(f"命令解析失败（请检查引号/反斜杠是否匹配）: {e}")

    def execute(self, raw: str) -> bool:
        """执行单条命令。返回 False 表示退出 REPL。"""
        raw = self._strip_prefix(raw)
        if not raw:
            return True

        # 解析命令，捕获 shlex 异常
        try:
            parts = self._safe_split(raw)
        except ValueError as e:
            self.fmt.error(str(e))
            return True

        if not parts:
            return True

        cmd = parts[0].lower()
        args = parts[1:]

        try:
            if cmd in ("exit", "quit", "q"):
                self.fmt.info("再见！")
                return False
            if cmd in ("help", "?"):
                self._cmd_help()
            elif cmd == "info":
                self._cmd_info()
            elif cmd == "sync":
                self._cmd_sync()
            elif cmd == "editor":
                self._cmd_editor()
            elif cmd == "applyedits":
                self._cmd_applyedits(args)
            elif cmd == "check":
                self._cmd_check(args)
            elif cmd == "verbose":
                self._cmd_verbose(args)
            elif cmd == "tree":
                self._cmd_tree(args)
            elif cmd == "user":
                self._cmd_user(args)
            elif cmd == "group":
                self._cmd_group(args)
            elif cmd == "track":
                self._cmd_track(args)
            else:
                self.fmt.error(f"未知命令: {cmd}，输入 help 查看帮助")
        except Exception as e:
            self.fmt.error(str(e))
            if self.fmt.debug:
                import traceback
                for line in traceback.format_exc().split("\n"):
                    if line.strip():
                        self.fmt.error(f"  {line}")

        return True

    def _cmd_help(self) -> None:
        lines = [
            "LuckPerms 交互式终端",
            "",
            "命令前缀可选: lp, /lp, 或无前缀",
            "",
            "用户管理",
            "  user <id> info                          查看用户详情",
            "  user <id> permission info               列出用户权限",
            "  user <id> permission set <node> [T/F] [ctx...] [--duration N]",
            "                                          设置权限",
            "  user <id> permission unset <node> [ctx...]",
            "                                          移除权限",
            "  user <id> permission check <node> [ctx...]",
            "                                          检查权限",
            "  user <id> parent info                   列出继承组",
            "  user <id> parent add <group>            加入组",
            "  user <id> parent remove <group>         移出组",
            "  user <id> promote <track>               沿轨道晋升",
            "  user <id> demote <track>                沿轨道降级",
            "  user create <id> [--display-name NAME]  创建用户",
            "  user delete <id>                        删除用户",
            "  user list                               列出所有用户",
            "",
            "组管理",
            "  group <name> info                       查看组详情",
            "  group <name> permission ...             同 user permission",
            "  group <name> parent info/add/remove ... 继承管理",
            "  group <name> setweight <n>              设置权重",
            "  group create <name> [--display-name NAME] [--weight N]",
            "                                          创建组",
            "  group delete <name>                     删除组",
            "  group list                              列出所有组",
            "",
            "轨道管理",
            "  track <name> info                       查看轨道",
            "  track <name> append <group>             追加组",
            "  track <name> insert <idx> <group>       插入组",
            "  track <name> remove <group>             移除组",
            "  track create <name> [g1 g2 ...]         创建轨道",
            "  track delete <name>                     删除轨道",
            "  track list                              列出所有轨道",
            "",
            "系统",
            "  check <user> <node> [ctx...]            快捷权限检查",
            "  verbose <user>                          实时监听权限检查",
            "  verbose off                             关闭监听",
            "  tree <user|group> [--depth N]           继承树可视化",
            "  editor                                  启动 Web Editor",
            "  applyedits <code>                       应用 Web Editor 保存的 edits",
            "  sync                                    重新加载数据",
            "  info                                    统计信息",
            "  help                                    显示本帮助",
            "  exit / quit                             退出",
        ]
        for line in lines:
            self.fmt.print(line)

    def _cmd_info(self) -> None:
        self.fmt.print(f"数据目录: {self.mgr._data_dir}")
        self.fmt.print(f"用户数: {len(self.mgr._users)}")
        self.fmt.print(f"组数: {len(self.mgr._groups)}")
        self.fmt.print(f"轨道数: {len(self.mgr._tracks)}")

    def _cmd_sync(self) -> None:
        self.mgr._load_all()
        self.fmt.success("数据已从磁盘重新加载")

    def _cmd_editor(self) -> None:
        """启动 Web Editor（同步包装，内部驱动异步会话）。"""

        async def _run_editor() -> None:
            def get_payload() -> dict:
                p = self.mgr.to_webeditor_payload()
                self.fmt.debug(f"payload: holders={len(p.get('permissionHolders', []))} tracks={len(p.get('tracks', []))}")
                return p

            def apply_changes(payload: dict) -> None:
                self.fmt.debug("WebSocket 收到 apply，开始处理 ...")
                self.mgr.apply_webeditor_changes(payload)
                self.mgr.save_all()
                self.fmt.success("Web Editor 变更已应用并持久化")

            session = WebEditorSession(
                get_payload=get_payload,
                apply_changes=apply_changes,
            )
            try:
                url = await session.open()
                self.fmt.success(f"Web Editor 已启动: {url}")
                self.fmt.info("在浏览器中编辑并 Save 后，变更会自动回传")
                self.fmt.info("按 Ctrl+C 可中断此会话")
                while session.is_active:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                self.fmt.error(f"启动 Web Editor 失败: {e}")
                if self.fmt.debug:
                    import traceback
                    for line in traceback.format_exc().split("\n"):
                        if line.strip():
                            self.fmt.error(f"  {line}")
            finally:
                await session.close()

        try:
            asyncio.run(_run_editor())
        except KeyboardInterrupt:
            self.fmt.info("已中断 Web Editor 会话")

    def _cmd_applyedits(self, args: list[str]) -> None:
        """手动应用 Web Editor 保存后生成的 edits code。"""
        if not args:
            self.fmt.error("用法: applyedits <code>")
            self.fmt.info("在 Web Editor 中点击 Save 后，复制命令中的 code 执行")
            return

        code = args[0]
        self.fmt.debug(f"准备下载 edits: code={code}")

        async def _run() -> None:
            session = WebEditorSession(
                get_payload=lambda: {},
                apply_changes=lambda p: None,
            )
            try:
                self.fmt.debug("正在从 bytebin 下载 ...")
                payload = await session.bytebin.download(code)
                self.fmt.debug(f"下载完成，payload keys: {list(payload.keys())}")

                if "changes" in payload:
                    changes = payload.get("changes", [])
                    gdel = payload.get("groupDeletions", [])
                    tdel = payload.get("trackDeletions", [])
                    udel = payload.get("userDeletions", [])
                    self.fmt.debug(f"增量格式: changes={len(changes)} groupDel={gdel} trackDel={tdel} userDel={udel}")
                    for c in changes[:3]:
                        self.fmt.debug(f"  change type={c.get('type')} id={c.get('id')} nodes={len(c.get('nodes', []))}")
                else:
                    holders = payload.get("permissionHolders", [])
                    tracks = payload.get("tracks", [])
                    self.fmt.debug(f"全量格式: holders={len(holders)} tracks={len(tracks)}")

                self.fmt.debug("开始调用 apply_webeditor_changes ...")
                self.mgr.apply_webeditor_changes(payload)
                self.mgr.save_all()

                self.fmt.debug(f"应用后内存状态: users={len(self.mgr._users)} groups={len(self.mgr._groups)} tracks={len(self.mgr._tracks)}")
                self.fmt.success(f"已应用 edits: {code}")
                self.fmt.info("提示: 建议重新运行 editor 生成新的编辑器 URL")
            except Exception as e:
                self.fmt.error(f"应用 edits 失败: {e}")
                if self.fmt.debug:
                    import traceback
                    for line in traceback.format_exc().split("\n"):
                        if line.strip():
                            self.fmt.error(f"  {line}")

        try:
            asyncio.run(_run())
        except Exception as e:
            self.fmt.error(f"应用 edits 失败: {e}")
            if self.fmt.debug:
                import traceback
                for line in traceback.format_exc().split("\n"):
                    if line.strip():
                        self.fmt.error(f"  {line}")

    def _cmd_check(self, args: list[str]) -> None:
        if len(args) < 2:
            self.fmt.error("用法: check <user> <node> [ctx...]")
            return
        user_id, node = args[0], args[1]
        ctx = self._parse_context(args[2:])
        result = self.mgr.check(user_id, node, ctx)
        self.fmt.print(f"check({user_id}, {node}, {ctx}) = {result}")

    def _cmd_verbose(self, args: list[str]) -> None:
        if not args or args[0] == "off":
            self._verbose_user = None
            self.fmt.info("已关闭 verbose 监听")
            return
        user_id = args[0]
        if user_id not in self.mgr._users:
            self.fmt.error(f"用户 '{user_id}' 不存在")
            return
        self._verbose_user = user_id
        self.fmt.info(f"已开启 verbose 监听: {user_id}")

    def _cmd_tree(self, args: list[str]) -> None:
        if not args:
            self.fmt.error("用法: tree <user|group> [--depth N]")
            return
        holder_id = args[0]
        depth = 5
        for i, a in enumerate(args):
            if a == "--depth" and i + 1 < len(args):
                depth = int(args[i + 1])
        self.fmt.tree_holder(self.mgr, holder_id, depth)

    def _cmd_user(self, args: list[str]) -> None:
        if not args:
            self.fmt.error("用法: user <subcommand> ...")
            return

        # 全局子命令（不需要指定用户ID）
        if args[0] in ("create", "delete", "list"):
            sub = args[0]
            sub_args = args[1:]
            if sub == "create":
                if not sub_args:
                    self.fmt.error("用法: user create <id> [--display-name NAME]")
                    return
                uid = sub_args[0]
                display = self._pop_flag(sub_args[1:], "--display-name") or uid
                self.mgr.create_user(uid, display)
                self.fmt.success(f"创建用户: {uid}")
            elif sub == "delete":
                if not sub_args:
                    self.fmt.error("用法: user delete <id>")
                    return
                uid = sub_args[0]
                if self.mgr.delete_user(uid):
                    self.fmt.success(f"删除用户: {uid}")
                else:
                    self.fmt.error(f"用户不存在: {uid}")
            elif sub == "list":
                self.fmt.table_users(self.mgr.list_users())
            return

        # 针对特定用户的子命令
        uid = args[0]
        sub = args[1] if len(args) > 1 else "info"
        sub_args = args[2:]

        user = self.mgr.get_user(uid)
        if not user:
            self.fmt.error(f"用户不存在: {uid}")
            return

        if sub == "info":
            self.fmt.print(f"[User] {uid}")
            self.fmt.print(f"  Display Name: {user.display_name}")
            self.fmt.print(f"  Parents: {user.parents}")
            self.fmt.table_nodes(user.nodes, "Nodes")
        elif sub == "permission":
            self._cmd_permission(user, sub_args)
        elif sub == "parent":
            self._cmd_parent(user, sub_args)
        elif sub == "promote":
            if not sub_args:
                self.fmt.error("用法: user <id> promote <track>")
                return
            result = self.mgr.promote(uid, sub_args[0])
            if result:
                self.fmt.success(f"晋升至: {result}")
            else:
                self.fmt.error("晋升失败（已在最高级或轨道不存在）")
        elif sub == "demote":
            if not sub_args:
                self.fmt.error("用法: user <id> demote <track>")
                return
            result = self.mgr.demote(uid, sub_args[0])
            if result:
                self.fmt.success(f"降级至: {result}")
            else:
                self.fmt.error("降级失败（已移除或轨道不存在）")
        else:
            self.fmt.error(f"未知子命令: user {sub}")

    def _cmd_group(self, args: list[str]) -> None:
        if not args:
            self.fmt.error("用法: group <subcommand> ...")
            return

        # 全局子命令
        if args[0] in ("create", "delete", "list"):
            sub = args[0]
            sub_args = args[1:]
            if sub == "create":
                if not sub_args:
                    self.fmt.error("用法: group create <name> [--display-name NAME] [--weight N]")
                    return
                name = sub_args[0]
                display = self._pop_flag(sub_args[1:], "--display-name") or name
                weight = int(self._pop_flag(sub_args[1:], "--weight") or 0)
                self.mgr.create_group(name, display, weight)
                self.fmt.success(f"创建组: {name}")
            elif sub == "delete":
                if not sub_args:
                    self.fmt.error("用法: group delete <name>")
                    return
                name = sub_args[0]
                if self.mgr.delete_group(name):
                    self.fmt.success(f"删除组: {name}")
                else:
                    self.fmt.error(f"组不存在: {name}")
            elif sub == "list":
                self.fmt.table_groups(self.mgr.list_groups())
            return

        # 针对特定组的子命令
        name = args[0]
        sub = args[1] if len(args) > 1 else "info"
        sub_args = args[2:]

        group = self.mgr.get_group(name)
        if not group:
            self.fmt.error(f"组不存在: {name}")
            return

        if sub == "info":
            self.fmt.print(f"[Group] {name}")
            self.fmt.print(f"  Display Name: {group.display_name}")
            self.fmt.print(f"  Weight: {group.weight}")
            self.fmt.print(f"  Parents: {group.parents}")
            self.fmt.table_nodes(group.nodes, "Nodes")
        elif sub == "permission":
            self._cmd_permission(group, sub_args)
        elif sub == "parent":
            self._cmd_parent(group, sub_args)
        elif sub == "setweight":
            if not sub_args:
                self.fmt.error("用法: group <name> setweight <n>")
                return
            group.weight = int(sub_args[0])
            self.mgr.save_all()
            self.fmt.success(f"组 {name} 权重已设为 {group.weight}")
        else:
            self.fmt.error(f"未知子命令: group {sub}")

    def _cmd_track(self, args: list[str]) -> None:
        if not args:
            self.fmt.error("用法: track <subcommand> ...")
            return

        # 全局子命令
        if args[0] in ("create", "delete", "list"):
            sub = args[0]
            sub_args = args[1:]
            if sub == "create":
                if not sub_args:
                    self.fmt.error("用法: track create <name> [g1 g2 ...]")
                    return
                name = sub_args[0]
                groups = sub_args[1:]
                self.mgr.create_track(name, groups)
                self.fmt.success(f"创建轨道: {name}")
            elif sub == "delete":
                if not sub_args:
                    self.fmt.error("用法: track delete <name>")
                    return
                name = sub_args[0]
                if self.mgr.delete_track(name):
                    self.fmt.success(f"删除轨道: {name}")
                else:
                    self.fmt.error(f"轨道不存在: {name}")
            elif sub == "list":
                self.fmt.table_tracks(self.mgr.list_tracks())
            return

        # 针对特定轨道的子命令
        name = args[0]
        sub = args[1] if len(args) > 1 else "info"
        sub_args = args[2:]

        track = self.mgr.get_track(name)
        if not track:
            self.fmt.error(f"轨道不存在: {name}")
            return

        if sub == "info":
            self.fmt.print(f"[Track] {name}")
            self.fmt.table_tracks([track])
        elif sub == "append":
            if not sub_args:
                self.fmt.error("用法: track <name> append <group>")
                return
            track.append_group(sub_args[0])
            self.mgr.save_all()
            self.fmt.success(f"已追加 {sub_args[0]} 到轨道 {name}")
        elif sub == "insert":
            if len(sub_args) < 2:
                self.fmt.error("用法: track <name> insert <index> <group>")
                return
            idx = int(sub_args[0])
            gname = sub_args[1]
            track.groups.insert(idx, gname)
            self.mgr.save_all()
            self.fmt.success(f"已插入 {gname} 到位置 {idx}")
        elif sub == "remove":
            if not sub_args:
                self.fmt.error("用法: track <name> remove <group>")
                return
            if track.remove_group(sub_args[0]):
                self.mgr.save_all()
                self.fmt.success(f"已从轨道 {name} 移除 {sub_args[0]}")
            else:
                self.fmt.error(f"轨道中不存在该组: {sub_args[0]}")
        else:
            self.fmt.error(f"未知子命令: track {sub}")

    def _cmd_permission(self, holder: Any, args: list[str]) -> None:
        if not args:
            self.fmt.table_nodes(holder.nodes, "Nodes")
            return
        sub = args[0]
        sub_args = args[1:]

        if sub == "info":
            self.fmt.table_nodes(holder.nodes, "Nodes")
            return

        if sub in ("set", "unset", "check"):
            if not sub_args:
                self.fmt.error(f"用法: permission {sub} <node> ...")
                return
            node_key = sub_args[0]

        if sub == "set":
            value = True
            duration: Optional[int] = None
            filtered = []
            i = 0
            while i < len(sub_args[1:]):
                a = sub_args[1 + i]
                if a.lower() in ("true", "t", "1"):
                    value = True
                elif a.lower() in ("false", "f", "0"):
                    value = False
                elif a == "--duration" and i + 1 < len(sub_args[1:]):
                    duration = int(sub_args[1 + i + 1])
                    i += 1
                else:
                    filtered.append(a)
                i += 1
            ctx = self._parse_context(filtered)

            if isinstance(holder, User):
                self.mgr.user_add_node(holder.unique_id, node_key, value, ctx, duration)
            else:
                self.mgr.group_add_node(holder.name, node_key, value, ctx)
            self.fmt.success(f"设置权限: {node_key} = {value}")

        elif sub == "unset":
            ctx = self._parse_context(sub_args[1:])
            if isinstance(holder, User):
                ok = self.mgr.user_remove_node(holder.unique_id, node_key, ctx)
            else:
                ok = self.mgr.group_remove_node(holder.name, node_key, ctx)
            if ok:
                self.fmt.success(f"移除权限: {node_key}")
            else:
                self.fmt.error(f"权限不存在: {node_key}")

        elif sub == "check":
            ctx = self._parse_context(sub_args[1:])
            if isinstance(holder, User):
                result = self.mgr.check(holder.unique_id, node_key, ctx)
            else:
                result = self.mgr.check_group(holder.name, node_key, ctx)
            self.fmt.print(f"check({holder.name if isinstance(holder, Group) else holder.unique_id}, {node_key}, {ctx}) = {result}")

    def _cmd_parent(self, holder: Any, args: list[str]) -> None:
        if not args:
            self.fmt.print(f"Parents: {holder.parents}")
            return
        sub = args[0]
        sub_args = args[1:]

        if sub == "info":
            self.fmt.print(f"Parents: {holder.parents}")
        elif sub == "add":
            if not sub_args:
                self.fmt.error("用法: parent add <group>")
                return
            gname = sub_args[0]
            if isinstance(holder, User):
                self.mgr.user_add_group(holder.unique_id, gname)
            else:
                self.mgr.group_inherit(holder.name, gname)
            self.fmt.success(f"添加继承: {gname}")
        elif sub == "remove":
            if not sub_args:
                self.fmt.error("用法: parent remove <group>")
                return
            gname = sub_args[0]
            if isinstance(holder, User):
                self.mgr.user_remove_group(holder.unique_id, gname)
            else:
                self.mgr.group_remove_inherit(holder.name, gname)
            self.fmt.success(f"移除继承: {gname}")
        else:
            self.fmt.error(f"未知子命令: parent {sub}")

    @staticmethod
    def _parse_context(args: list[str]) -> dict[str, str]:
        ctx: dict[str, str] = {}
        for a in args:
            if "=" in a:
                k, v = a.split("=", 1)
                ctx[k] = v
        return ctx

    @staticmethod
    def _pop_flag(args: list[str], flag: str) -> Optional[str]:
        for i, a in enumerate(args):
            if a == flag and i + 1 < len(args):
                return args[i + 1]
        return None


# ------------------------------------------------------------------
# REPL 主循环
# ------------------------------------------------------------------
def run_shell(data_dir: str, debug: bool = False) -> None:
    """启动交互式 Shell。"""
    mgr = LuckPermsManager(data_dir)
    fmt = Formatter(debug=debug)
    cmd = LPCommand(mgr, fmt)

    fmt.print("LuckPermsAPI 交互式终端")
    fmt.print(f"数据目录: {data_dir}")
    fmt.print("命令前缀可选: lp, /lp, 或无前缀")
    if debug:
        fmt.print("调试模式已开启")
    fmt.print("输入 help 查看命令列表，exit 退出\n")

    if HAS_PROMPT_TOOLKIT:
        session: PromptSession[str] = PromptSession(
            "lp> ",
            completer=LPCompleter(mgr),
            complete_while_typing=True,
        )
        while True:
            try:
                text = session.prompt()
            except (EOFError, KeyboardInterrupt):
                fmt.print()
                break
            if not cmd.execute(text):
                break
    else:
        while True:
            try:
                text = input("lp> ")
            except (EOFError, KeyboardInterrupt):
                fmt.print()
                break
            if not cmd.execute(text):
                break


def main() -> None:
    parser = argparse.ArgumentParser(description="LuckPermsAPI CLI")
    parser.add_argument(
        "--data-dir",
        default=os.path.join(tempfile.gettempdir(), "lp_cli_data"),
        help="数据存储目录 (默认: /tmp/lp_cli_data)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="开启调试模式，显示详细日志",
    )
    parser.add_argument(
        "command",
        nargs="...",
        help="直接执行单条命令后退出（如: user list）",
    )
    args = parser.parse_args()

    # 设置 logging 级别
    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)

    os.makedirs(args.data_dir, exist_ok=True)

    if args.command:
        mgr = LuckPermsManager(args.data_dir)
        fmt = Formatter(debug=args.debug)
        cmd = LPCommand(mgr, fmt)
        cmd.execute(" ".join(args.command))
    else:
        run_shell(args.data_dir, debug=args.debug)


if __name__ == "__main__":
    main()