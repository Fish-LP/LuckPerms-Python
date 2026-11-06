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
import tempfile
import time
from typing import TYPE_CHECKING, Any, Optional

# 尝试导入可选依赖
try:
    from rich.console import Console
    from rich.table import Table
    from rich.tree import Tree as RichTree

    HAS_RICH = True
except ImportError:
    HAS_RICH = False
if TYPE_CHECKING:
    from rich.console import Console
    from rich.table import Table
    from rich.tree import Tree as RichTree

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.document import Document

    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False
if TYPE_CHECKING:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.document import Document

from .constants import (
    CUSTOM_META_PREFIX,
    DEFAULT_TEMP_MODIFIER,
    GROUP_NODE_PREFIX,
    TEMP_MODIFIERS,
)
from .duration import DurationParseError, format_duration, parse_duration
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
        self._debug = debug

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
        if self._debug:
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
            for n in nodes:
                ctx = ", ".join(f"{k}={v}" for k, v in n.context.items()) or "-"
                exp = format_duration(
                    None if n.expiry is None else n.expiry - time.time()
                )
                val = "[green]True[/green]" if n.value else "[red]False[/red]"
                table.add_row(n.key, val, ctx, exp)
            self.console.print(table)
        else:
            self.print(f"--- {title} ---")
            for n in nodes:
                ctx = f" context={n.context}" if n.context else ""
                if n.expiry is None:
                    exp = ""
                else:
                    exp = f" expiry={format_duration(n.expiry - time.time())}"
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
                self.print(
                    f"  {u.unique_id} | {u.display_name} | groups={groups} | nodes={len(u.nodes)}"
                )

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
                table.add_row(
                    g.name, g.display_name, str(g.weight), parents, str(len(g.nodes))
                )
            self.console.print(table)
        else:
            self.print("--- Groups ---")
            for g in groups:
                parents = ", ".join(g.parents) or "-"
                self.print(
                    f"  {g.name} | {g.display_name} | weight={g.weight} | parents={parents} | nodes={len(g.nodes)}"
                )

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

    def tree_holder(
        self, mgr: LuckPermsManager, holder_id: str, depth: int = 5
    ) -> None:
        """以树形展示继承链。"""
        user = mgr.get_user(holder_id)
        group = mgr.get_group(holder_id)
        target = user or group
        if not target:
            self.error(f"持有者 '{holder_id}' 不存在")
            return

        # NOTE: 角色名先取出为变量，避免 f-string 内嵌同引号字符串（仅 Python 3.12+ 支持）
        role = "user" if user else "group"
        if self.console:
            root_label = f"[bold]{holder_id}[/bold] ({role})"
            tree = RichTree(root_label)
            self._build_tree_rich(mgr, target, tree, depth, set())
            self.console.print(tree)
        else:
            self.print(f"{holder_id} ({role})")
            self._build_tree_plain(mgr, target, 0, depth, set())

    def _build_tree_rich(
        self,
        mgr: LuckPermsManager,
        target: Any,
        tree: Any,
        depth: int,
        visited: set[str],
    ) -> None:
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

    def _build_tree_plain(
        self,
        mgr: LuckPermsManager,
        target: Any,
        indent: int,
        depth: int,
        visited: set[str],
    ) -> None:
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
            self.print(
                f"{prefix}└── {g.name} (weight={g.weight}, nodes={len(g.nodes)})"
            )
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
        "user ",
        "group ",
        "track ",
        "check ",
        "verbose ",
        "tree ",
        "editor",
        "applyedits ",
        "sync",
        "info",
        "help",
        "exit",
        "quit",
    ]

    USER_SUB = [
        "info",
        "permission",
        "parent",
        "meta",
        "promote",
        "demote",
        "showtracks",
        "clear",
        "create",
        "delete",
        "list",
    ]
    PERM_SUB = ["set ", "settemp ", "unset ", "unsettemp ", "check ", "clear", "info"]
    PARENT_SUB = [
        "add ",
        "addtemp ",
        "remove ",
        "removetemp ",
        "set ",
        "settrack ",
        "cleartrack ",
        "clear",
        "info",
    ]
    GROUP_SUB = [
        "info",
        "permission",
        "parent",
        "meta",
        "setweight",
        "setdisplayname",
        "listmembers",
        "clear",
        "create",
        "delete",
        "list",
    ]
    TRACK_SUB = [
        "info",
        "append",
        "insert",
        "remove",
        "clear",
        "rename",
        "create",
        "delete",
        "list",
    ]

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
        if (
            cmd in ("user", "verbose", "tree")
            and len(words) == 2
            and not text.endswith(" ")
        ):
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
            if self.fmt._debug:
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
            "时长格式: 30m / 12h / 7d / 1mo3d13h45m / 3600 / permanent",
            "",
            "用户管理",
            "  user <id> info                          查看用户详情",
            "  user <id> permission info               列出用户权限",
            "  user <id> permission set <node> [T/F] [ctx...] [--duration D]",
            "                                          设置权限（默认永久）",
            "  user <id> permission settemp <node> <T/F> <duration>",
            "                                          [--modifier accumulate|replace|deny] [ctx...]",
            "                                          设置临时权限",
            "  user <id> permission unset <node> [ctx...]",
            "                                          移除权限",
            "  user <id> permission unsettemp <node> [duration] [ctx...]",
            "                                          移除/缩短临时权限",
            "  user <id> permission clear              清空全部权限节点",
            "  user <id> permission check <node> [ctx...]",
            "                                          检查权限",
            "  user <id> parent info                   列出继承组（含临时）",
            "  user <id> parent add <group>            加入组",
            "  user <id> parent addtemp <group> <duration>",
            "                                          临时加入组",
            "  user <id> parent remove <group>         移出组",
            "  user <id> parent removetemp <group> [duration]",
            "                                          移除临时继承",
            "  user <id> parent set <group>            覆盖父组",
            "  user <id> parent clear                  清空父组（回到 default）",
            "  user <id> parent settrack <track> <index|group>",
            "                                          设置轨道位置",
            "  user <id> parent cleartrack <track>     清除轨道父组",
            "  user <id> meta info                     查看元数据",
            "  user <id> meta set <key> <value> [duration] [ctx...]",
            "                                          设置元数据",
            "  user <id> meta unset <key> [ctx...]     移除元数据",
            "  user <id> meta addprefix <priority> <prefix> [--duration D]",
            "  user <id> meta addsuffix <priority> <suffix> [--duration D]",
            "  user <id> meta setprefix [priority] <prefix>",
            "  user <id> meta setsuffix [priority] <suffix>",
            "  user <id> meta removeprefix <priority> [prefix]",
            "  user <id> meta removesuffix <priority> [suffix]",
            "  user <id> meta clear                    清空全部 meta 节点",
            "  user <id> showtracks                    查看轨道位置",
            "  user <id> clear                         清空节点与父组",
            "  user <id> promote <track>               沿轨道晋升",
            "  user <id> demote <track>                沿轨道降级",
            "  user create <id> [--display-name NAME]  创建用户",
            "  user delete <id>                        删除用户",
            "  user list                               列出所有用户",
            "",
            "组管理",
            "  group <name> info                       查看组详情",
            "  group <name> permission ...             同 user permission",
            "  group <name> parent ...                 继承管理（同 user parent）",
            "  group <name> meta ...                   元数据管理（同 user meta）",
            "  group <name> setweight <n>              设置权重",
            "  group <name> setdisplayname <name>      设置显示名",
            "  group <name> listmembers                列出直接成员",
            "  group <name> clear                      清空节点与父组",
            "  group create <name> [--display-name NAME] [--weight N]",
            "                                          创建组",
            "  group delete <name>                     删除组",
            "  group list                              列出所有组",
            "",
            "轨道管理",
            "  track <name> info                       查看轨道",
            "  track <name> append <group>             追加组",
            "  track <name> insert <group> <position>  插入组（兼容 <position> <group>）",
            "  track <name> remove <group>             移除组",
            "  track <name> clear                      清空轨道",
            "  track <name> rename <new name>          重命名轨道",
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
                self.fmt.debug(
                    f"payload: holders={len(p.get('permissionHolders', []))} tracks={len(p.get('tracks', []))}"
                )
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
                self.fmt.info(
                    "在浏览器中编辑并 Save 后，返回此终端执行 applyedits 命令应用更改"
                )
                while session.is_active:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                self.fmt.error(f"启动 Web Editor 失败: {e}")
                if self.fmt._debug:
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
                    self.fmt.debug(
                        f"增量格式: changes={len(changes)} groupDel={gdel} trackDel={tdel} userDel={udel}"
                    )
                    for c in changes[:3]:
                        self.fmt.debug(
                            f"  change type={c.get('type')} id={c.get('id')} nodes={len(c.get('nodes', []))}"
                        )
                else:
                    holders = payload.get("permissionHolders", [])
                    tracks = payload.get("tracks", [])
                    self.fmt.debug(
                        f"全量格式: holders={len(holders)} tracks={len(tracks)}"
                    )

                self.fmt.debug("开始调用 apply_webeditor_changes ...")
                self.mgr.apply_webeditor_changes(payload)
                self.mgr.save_all()

                self.fmt.debug(
                    f"应用后内存状态: users={len(self.mgr._users)} groups={len(self.mgr._groups)} tracks={len(self.mgr._tracks)}"
                )
                self.fmt.success(f"已应用 edits: {code}")
                self.fmt.info("提示: 建议重新运行 editor 生成新的编辑器 URL")
            except Exception as e:
                self.fmt.error(f"应用 edits 失败: {e}")
                if self.fmt._debug:
                    import traceback

                    for line in traceback.format_exc().split("\n"):
                        if line.strip():
                            self.fmt.error(f"  {line}")

        try:
            asyncio.run(_run())
        except Exception as e:
            self.fmt.error(f"应用 edits 失败: {e}")
            if self.fmt._debug:
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
            self.mgr.set_verbose(None)
            self.fmt.info("已关闭 verbose 监听")
            return
        user_id = args[0]
        if user_id not in self.mgr._users:
            self.fmt.error(f"用户 '{user_id}' 不存在")
            return
        self._verbose_user = user_id
        self.mgr.set_verbose(user_id, self._on_verbose_check)
        self.fmt.info(f"已开启 verbose 监听: {user_id}")

    def _on_verbose_check(
        self, user_id: str, permission: str, context: Any, result: bool
    ) -> None:
        """verbose 回调：打印每次权限检查的结果。"""
        flag = "ALLOW" if result else "DENY"
        ctx = f" {context}" if context else ""
        self.fmt.print(f"  [{flag}] {permission}{ctx}")

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
        elif sub == "meta":
            self._cmd_meta(user, sub_args)
        elif sub == "showtracks":
            tracks = self.mgr.user_show_tracks(uid)
            if not tracks:
                self.fmt.print("  用户不在任何轨道上")
            for track_name, position in tracks:
                self.fmt.print(f"  {track_name}: 第 {position} 级")
        elif sub == "clear":
            removed_nodes = self.mgr.clear_permissions(uid)
            removed_parents = self.mgr.clear_parents(uid)
            self.fmt.success(
                f"已清空用户 {uid}：权限节点 {removed_nodes} 个，父组 {removed_parents} 个"
            )
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
                    self.fmt.error(
                        "用法: group create <name> [--display-name NAME] [--weight N]"
                    )
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
        elif sub == "meta":
            self._cmd_meta(group, sub_args)
        elif sub == "setdisplayname":
            if not sub_args:
                self.fmt.error("用法: group <name> setdisplayname <name>")
                return
            self.mgr.set_group_display_name(name, sub_args[0])
            self.fmt.success(f"组 {name} 显示名已设为 {sub_args[0]}")
        elif sub == "listmembers":
            members = self.mgr.list_group_members(name)
            if not members:
                self.fmt.print("  (无成员)")
            for member in members:
                self.fmt.print(f"  {member}")
        elif sub == "clear":
            removed_nodes = self.mgr.clear_permissions(name, is_group=True)
            removed_parents = self.mgr.clear_parents(name, is_group=True)
            self.fmt.success(
                f"已清空组 {name}：权限节点 {removed_nodes} 个，父组 {removed_parents} 个"
            )
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
                self.fmt.error("用法: track <name> insert <group> <position>")
                return
            # 兼容历史写法 insert <position> <group>；原版顺序为 <group> <position>
            if sub_args[0].isdigit() and not sub_args[1].isdigit():
                gname, position_text = sub_args[1], sub_args[0]
            else:
                gname, position_text = sub_args[0], sub_args[1]
            if not position_text.isdigit():
                self.fmt.error(f"无效位置: {position_text}")
                return
            position = int(position_text)
            # NOTE: 不能直接 track.groups.insert(...)，groups 返回的是副本
            if track.insert_group(position, gname):
                self.mgr.save_all()
                self.fmt.success(f"已插入 {gname} 到位置 {position}")
            else:
                self.fmt.error(f"插入失败: 无效位置 {position}")
        elif sub == "remove":
            if not sub_args:
                self.fmt.error("用法: track <name> remove <group>")
                return
            if track.remove_group(sub_args[0]):
                self.mgr.save_all()
                self.fmt.success(f"已从轨道 {name} 移除 {sub_args[0]}")
            else:
                self.fmt.error(f"轨道中不存在该组: {sub_args[0]}")
        elif sub == "clear":
            removed = self.mgr.clear_track(name)
            self.fmt.success(f"已清空轨道 {name}（移除 {removed} 个组）")
        elif sub == "rename":
            if not sub_args:
                self.fmt.error("用法: track <name> rename <new name>")
                return
            self.mgr.rename_track(name, sub_args[0])
            self.fmt.success(f"轨道 {name} 已重命名为 {sub_args[0]}")
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

        is_group = isinstance(holder, Group)
        holder_id = holder.name if is_group else holder.unique_id

        if sub == "clear":
            removed = self.mgr.clear_permissions(holder_id, is_group)
            self.fmt.success(f"已清空权限节点（{removed} 个）")
            return

        if sub not in ("set", "settemp", "unset", "unsettemp", "check"):
            self.fmt.error(f"未知子命令: permission {sub}")
            return
        if not sub_args:
            self.fmt.error(f"用法: permission {sub} <node> ...")
            return

        node_key = sub_args[0]
        rest = sub_args[1:]

        if sub in ("set", "settemp"):
            try:
                value, duration, modifier, ctx_args = self._parse_node_options(
                    rest, require_duration=(sub == "settemp")
                )
            except DurationParseError as e:
                self.fmt.error(str(e))
                return
            ctx = self._parse_context(ctx_args)
            try:
                if is_group:
                    self.mgr.group_add_node(
                        holder_id, node_key, value, ctx, duration, modifier
                    )
                else:
                    self.mgr.user_add_node(
                        holder_id, node_key, value, ctx, duration, modifier
                    )
            except ValueError as e:
                self.fmt.error(str(e))
                return
            if duration is None:
                self.fmt.success(f"设置权限: {node_key} = {value}")
            else:
                self.fmt.success(
                    f"设置临时权限: {node_key} = {value}，"
                    f"有效期 {format_duration(duration)}"
                )
            return

        if sub == "unsettemp":
            try:
                reduce_seconds, ctx_args = self._parse_optional_duration(rest)
            except DurationParseError as e:
                self.fmt.error(str(e))
                return
            ctx = self._parse_context(ctx_args)
            self._reduce_temp_node(holder, node_key, ctx, reduce_seconds)
            return

        if sub == "unset":
            ctx = self._parse_context(rest)
            ok = (
                self.mgr.group_remove_node(holder_id, node_key, ctx)
                if is_group
                else self.mgr.user_remove_node(holder_id, node_key, ctx)
            )
            if ok:
                self.fmt.success(f"移除权限: {node_key}")
            else:
                self.fmt.error(f"权限不存在: {node_key}")
            return

        # check
        ctx = self._parse_context(rest)
        result = (
            self.mgr.check_group(holder_id, node_key, ctx)
            if is_group
            else self.mgr.check(holder_id, node_key, ctx)
        )
        self.fmt.print(f"check({holder_id}, {node_key}, {ctx}) = {result}")

    def _cmd_parent(self, holder: Any, args: list[str]) -> None:
        is_group = isinstance(holder, Group)
        holder_id = holder.name if is_group else holder.unique_id

        if not args:
            self._print_parents(holder)
            return
        sub = args[0]
        sub_args = args[1:]

        if sub == "info":
            self._print_parents(holder)
            return

        if sub in ("add", "addtemp"):
            if not sub_args:
                self.fmt.error(f"用法: parent {sub} <group> [duration]")
                return
            gname = sub_args[0]
            try:
                duration, modifier, ctx_args = self._parse_temp_options(
                    sub_args[1:], require_duration=(sub == "addtemp")
                )
            except DurationParseError as e:
                self.fmt.error(str(e))
                return
            ctx = self._parse_context(ctx_args)
            try:
                if is_group:
                    self.mgr.group_inherit(holder_id, gname, duration, ctx, modifier)
                else:
                    self.mgr.user_add_group(holder_id, gname, duration, ctx, modifier)
            except (KeyError, ValueError) as e:
                self.fmt.error(str(e))
                return
            if duration is None:
                self.fmt.success(f"添加继承: {gname}")
            else:
                self.fmt.success(
                    f"添加临时继承: {gname}，有效期 {format_duration(duration)}"
                )
            return

        if sub in ("remove", "removetemp"):
            if not sub_args:
                self.fmt.error(f"用法: parent {sub} <group>")
                return
            gname = sub_args[0]
            if sub == "removetemp":
                try:
                    reduce_seconds, ctx_args = self._parse_optional_duration(
                        sub_args[1:]
                    )
                except DurationParseError as e:
                    self.fmt.error(str(e))
                    return
                self._reduce_temp_node(
                    holder,
                    f"{GROUP_NODE_PREFIX}{gname}",
                    self._parse_context(ctx_args),
                    reduce_seconds,
                )
                return
            if is_group:
                self.mgr.group_remove_inherit(holder_id, gname)
            else:
                self.mgr.user_remove_group(holder_id, gname)
            self.fmt.success(f"移除继承: {gname}")
            return

        if sub == "set":
            if not sub_args:
                self.fmt.error("用法: parent set <group>")
                return
            gname = sub_args[0]
            self.mgr.clear_parents(holder_id, is_group, keep_default=False)
            if is_group:
                self.mgr.group_inherit(holder_id, gname)
            else:
                self.mgr.user_add_group(holder_id, gname)
            self.fmt.success(f"已设置父组: {gname}")
            return

        if sub == "clear":
            removed = self.mgr.clear_parents(holder_id, is_group)
            self.fmt.success(f"已清空父组（{removed} 个）")
            return

        if sub == "cleartrack":
            if not sub_args:
                self.fmt.error("用法: parent cleartrack <track>")
                return
            track = self.mgr.get_track(sub_args[0])
            if not track:
                self.fmt.error(f"轨道不存在: {sub_args[0]}")
                return
            for gname in track.groups:
                if is_group:
                    self.mgr.group_remove_inherit(holder_id, gname)
                else:
                    self.mgr.user_remove_group(holder_id, gname)
            self.fmt.success(f"已清除轨道 {track.name} 上的父组")
            return

        if sub == "settrack":
            if len(sub_args) < 2:
                self.fmt.error("用法: parent settrack <track> <index|group>")
                return
            track = self.mgr.get_track(sub_args[0])
            if not track:
                self.fmt.error(f"轨道不存在: {sub_args[0]}")
                return
            target = sub_args[1]
            groups = track.groups
            if target.isdigit():
                position = int(target)
                if position < 1 or position > len(groups):
                    self.fmt.error(f"轨道位置超出范围: {target}")
                    return
                gname = groups[position - 1]
            elif target in groups:
                gname = target
            else:
                self.fmt.error(f"组不在轨道中: {target}")
                return
            # 先清掉轨道上的旧组，再设置目标组
            for old in groups:
                if is_group:
                    self.mgr.group_remove_inherit(holder_id, old)
                else:
                    self.mgr.user_remove_group(holder_id, old)
            if is_group:
                self.mgr.group_inherit(holder_id, gname)
            else:
                self.mgr.user_add_group(holder_id, gname)
            self.fmt.success(f"已设置轨道 {track.name} 位置: {gname}")
            return

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

    def _parse_temp_options(
        self, args: list[str], require_duration: bool
    ) -> tuple[Optional[int], str, list[str]]:
        """解析 ``[duration] [--modifier M] [ctx...]``。

        Args:
            args: 待解析参数。
            require_duration: 为 True 时第一个位置参数视作 duration
                （``addtemp`` / ``settemp`` 语法）。

        Return:
            (duration, modifier, context_args)

        Raises:
            DurationParseError: duration 非法。
        """
        duration: Optional[int] = None
        modifier = DEFAULT_TEMP_MODIFIER
        ctx_args: list[str] = []
        i = 0
        while i < len(args):
            a = args[i]
            if a == "--duration" and i + 1 < len(args):
                duration = parse_duration(args[i + 1])
                i += 1
            elif a == "--modifier" and i + 1 < len(args):
                modifier = args[i + 1].lower()
                i += 1
            elif a.startswith("--") and a[2:].lower() in TEMP_MODIFIERS:
                modifier = a[2:].lower()
            elif (
                require_duration
                and duration is None
                and "=" not in a
                and not a.startswith("--")
            ):
                duration = parse_duration(a)
            else:
                ctx_args.append(a)
            i += 1
        return duration, modifier, ctx_args

    def _parse_node_options(
        self, args: list[str], require_duration: bool
    ) -> tuple[bool, Optional[int], str, list[str]]:
        """解析 ``[true|false] [duration] [--modifier M] [ctx...]``。

        Return:
            (value, duration, modifier, context_args)
        """
        value = True
        rest: list[str] = []
        for a in args:
            low = a.lower()
            if low in ("true", "t", "1"):
                value = True
            elif low in ("false", "f", "0"):
                value = False
            else:
                rest.append(a)
        duration, modifier, ctx_args = self._parse_temp_options(rest, require_duration)
        return value, duration, modifier, ctx_args

    @staticmethod
    def _parse_optional_duration(
        args: list[str],
    ) -> tuple[Optional[int], list[str]]:
        """解析可选的前置 duration 与上下文参数（``unsettemp`` 语法）。"""
        duration: Optional[int] = None
        ctx_args: list[str] = []
        for a in args:
            if duration is None and "=" not in a and not a.startswith("--"):
                duration = parse_duration(a)
            else:
                ctx_args.append(a)
        return duration, ctx_args

    def _reduce_temp_node(
        self,
        holder: Any,
        node_key: str,
        ctx: dict[str, str],
        reduce_seconds: Optional[int],
    ) -> None:
        """移除或缩短临时节点（``unsettemp`` 语义）。"""
        node = holder.get_node(node_key, ctx)
        if node is None or node.expiry is None:
            self.fmt.error(f"不存在临时权限: {node_key}")
            return
        if reduce_seconds is None:
            holder.remove_node(node_key, ctx)
            self.mgr.save_all()
            self.fmt.success(f"已移除临时权限: {node_key}")
            return
        new_expiry = node.expiry - reduce_seconds
        if new_expiry <= time.time():
            holder.remove_node(node_key, ctx)
            self.mgr.save_all()
            self.fmt.success(f"临时权限已耗尽并移除: {node_key}")
        else:
            holder.add_node(Node(node.key, node.value, node.context, new_expiry))
            self.mgr.save_all()
            self.fmt.success(
                f"临时权限剩余 {format_duration(new_expiry - time.time())}: {node_key}"
            )

    def _print_parents(self, holder: Any) -> None:
        self.fmt.print(f"Parents: {holder.parents}")
        temps = holder.temp_parents
        if temps:
            self.fmt.print(f"Temporary Parents: {temps}")

    def _print_meta(self, holder: Any) -> None:
        for meta_type in ("prefix", "suffix", "displayname", "weight"):
            value = holder.get_meta(meta_type)
            self.fmt.print(f"  {meta_type}: {value if value is not None else '-'}")
        custom: list[str] = []
        for node in holder.nodes:
            if node.key.startswith(CUSTOM_META_PREFIX):
                parts = node.key.split(".", 2)
                if len(parts) == 3:
                    custom.append(f"{parts[1]}={parts[2]}")
        if custom:
            self.fmt.print(f"  custom: {', '.join(custom)}")

    def _report_meta(self, node_key: str, duration: Optional[int]) -> None:
        if duration is None:
            self.fmt.success(f"已设置 meta: {node_key}")
        else:
            self.fmt.success(
                f"已设置临时 meta: {node_key}，有效期 {format_duration(duration)}"
            )

    def _cmd_meta(self, holder: Any, args: list[str]) -> None:
        is_group = isinstance(holder, Group)
        holder_id = holder.name if is_group else holder.unique_id

        if not args:
            self._print_meta(holder)
            return
        sub = args[0]
        sub_args = args[1:]

        if sub == "info":
            self._print_meta(holder)
            return

        if sub == "set":
            if len(sub_args) < 2:
                self.fmt.error("用法: meta set <key> <value> [duration] [ctx...]")
                return
            key, value = sub_args[0], sub_args[1]
            try:
                duration, modifier, ctx_args = self._parse_temp_options(
                    sub_args[2:], require_duration=True
                )
            except DurationParseError as e:
                self.fmt.error(str(e))
                return
            node_key = self.mgr.set_meta(
                holder_id,
                key,
                value,
                is_group=is_group,
                context=self._parse_context(ctx_args),
                duration=duration,
                modifier=modifier,
            )
            self._report_meta(node_key, duration)
            return

        if sub == "unset":
            if not sub_args:
                self.fmt.error("用法: meta unset <key> [ctx...]")
                return
            removed = self.mgr.unset_meta(
                holder_id,
                sub_args[0],
                is_group=is_group,
                context=self._parse_context(sub_args[1:]),
            )
            if removed:
                self.fmt.success(f"已移除 meta: {sub_args[0]}")
            else:
                self.fmt.error(f"meta 不存在: {sub_args[0]}")
            return

        if sub in ("addprefix", "addsuffix"):
            meta_type = "prefix" if sub == "addprefix" else "suffix"
            if len(sub_args) < 2 or not sub_args[0].isdigit():
                self.fmt.error(f"用法: meta {sub} <priority> <value> [--duration D]")
                return
            priority = int(sub_args[0])
            value = sub_args[1]
            try:
                duration, modifier, ctx_args = self._parse_temp_options(
                    sub_args[2:], require_duration=False
                )
            except DurationParseError as e:
                self.fmt.error(str(e))
                return
            node_key = self.mgr.set_meta(
                holder_id,
                meta_type,
                value,
                priority=priority,
                is_group=is_group,
                context=self._parse_context(ctx_args),
                duration=duration,
                modifier=modifier,
            )
            self._report_meta(node_key, duration)
            return

        if sub in ("setprefix", "setsuffix"):
            meta_type = "prefix" if sub == "setprefix" else "suffix"
            if not sub_args:
                self.fmt.error(f"用法: meta {sub} [priority] <value> [--duration D]")
                return
            if sub_args[0].isdigit() and len(sub_args) > 1:
                priority = int(sub_args[0])
                value = sub_args[1]
                rest = sub_args[2:]
            else:
                priority = 0
                value = sub_args[0]
                rest = sub_args[1:]
            try:
                duration, modifier, ctx_args = self._parse_temp_options(
                    rest, require_duration=False
                )
            except DurationParseError as e:
                self.fmt.error(str(e))
                return
            # set 语义：先清掉同类型旧节点
            self.mgr.unset_meta(holder_id, meta_type, is_group=is_group)
            node_key = self.mgr.set_meta(
                holder_id,
                meta_type,
                value,
                priority=priority,
                is_group=is_group,
                context=self._parse_context(ctx_args),
                duration=duration,
                modifier=modifier,
            )
            self._report_meta(node_key, duration)
            return

        if sub in ("removeprefix", "removesuffix"):
            meta_type = "prefix" if sub == "removeprefix" else "suffix"
            if not sub_args or not sub_args[0].isdigit():
                self.fmt.error(f"用法: meta {sub} <priority> [value]")
                return
            removed = self.mgr.unset_meta(
                holder_id,
                meta_type,
                priority=int(sub_args[0]),
                value=sub_args[1] if len(sub_args) > 1 else None,
                is_group=is_group,
            )
            if removed:
                self.fmt.success(f"已移除 {meta_type}（{removed} 个）")
            else:
                self.fmt.error(f"{meta_type} 不存在")
            return

        if sub == "clear":
            keep = [
                n
                for n in holder.nodes
                if not n.is_meta and not n.key.startswith(CUSTOM_META_PREFIX)
            ]
            removed = len(holder.nodes) - len(keep)
            holder.set_nodes(keep)
            self.mgr.save_all()
            self.fmt.success(f"已清空 meta 节点（{removed} 个）")
            return

        self.fmt.error(f"未知子命令: meta {sub}")


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
