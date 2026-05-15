"""
LuckPermsAPI CLI 自动化回归测试。

覆盖所有子命令、边界条件和异常路径。
运行::

    pytest tests/test_cli.py -v
"""
from __future__ import annotations

import os
import tempfile
from typing import Any

import pytest

from luckperms.cli import Formatter, LPCommand, LPCompleter
from luckperms.manager import LuckPermsManager
from luckperms.models import Group, Node, User


class CaptureFormatter(Formatter):
    """捕获所有输出到列表，便于断言。强制禁用 rich 确保输出可捕获。"""

    def __init__(self, debug: bool = False) -> None:
        super().__init__(debug=debug)
        self.outputs: list[str] = []
        self.console = None  # 强制禁用 rich，所有输出走纯文本路径

    def print(self, text: str = "") -> None:
        self.outputs.append(str(text))

    def error(self, text: str) -> None:
        self.outputs.append(f"ERROR:{text}")

    def success(self, text: str) -> None:
        self.outputs.append(f"SUCCESS:{text}")

    def info(self, text: str) -> None:
        self.outputs.append(f"INFO:{text}")

    def debug(self, text: str) -> None:
        if self.debug:
            self.outputs.append(f"DEBUG:{text}")


class TestCLIBase:
    """基础 CLI 测试（数据构造与查看）。"""

    def setup_method(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.mgr = LuckPermsManager(self.tmpdir)
        self.fmt = CaptureFormatter(debug=False)
        self.cmd = LPCommand(self.mgr, self.fmt)

    def teardown_method(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run(self, command: str) -> list[str]:
        """执行命令并返回捕获的输出。"""
        self.fmt.outputs.clear()
        self.cmd.execute(command)
        return list(self.fmt.outputs)

    # ---------------------------------------------------------------
    # 1. 前缀兼容性
    # ---------------------------------------------------------------
    def test_prefix_none(self) -> None:
        out = self._run("user create alice")
        assert any("SUCCESS:创建用户" in o for o in out)

    def test_prefix_lp(self) -> None:
        out = self._run("lp user create bob")
        assert any("SUCCESS:创建用户" in o for o in out)

    def test_prefix_slashed_lp(self) -> None:
        out = self._run("/lp user create charlie")
        assert any("SUCCESS:创建用户" in o for o in out)

    # ---------------------------------------------------------------
    # 2. User CRUD
    # ---------------------------------------------------------------
    def test_user_create(self) -> None:
        out = self._run("user create u1 --display-name UserOne")
        assert any("SUCCESS:创建用户: u1" in o for o in out)
        assert self.mgr.get_user("u1").display_name == "UserOne"

    def test_user_create_duplicate(self) -> None:
        self.mgr.create_user("u1")
        out = self._run("user create u1")
        assert any("ERROR:用户 'u1' 已存在" in o for o in out)

    def test_user_delete(self) -> None:
        self.mgr.create_user("u1")
        out = self._run("user delete u1")
        assert any("SUCCESS:删除用户: u1" in o for o in out)
        assert self.mgr.get_user("u1") is None

    def test_user_delete_nonexist(self) -> None:
        out = self._run("user delete nobody")
        assert any("ERROR:用户不存在: nobody" in o for o in out)

    def test_user_list(self) -> None:
        self.mgr.create_user("a")
        self.mgr.create_user("b")
        out = self._run("user list")
        assert len(self.mgr.list_users()) == 2

    def test_user_info(self) -> None:
        self.mgr.create_user("steve", "Steve")
        self.mgr.user_add_node("steve", "plugin.chat", True)
        out = self._run("user steve info")
        assert any("Steve" in o for o in out)

    # ---------------------------------------------------------------
    # 3. Group CRUD
    # ---------------------------------------------------------------
    def test_group_create(self) -> None:
        out = self._run("group create admin --display-name 管理员 --weight 100")
        assert any("SUCCESS:创建组: admin" in o for o in out)
        g = self.mgr.get_group("admin")
        assert g.display_name == "管理员"
        assert g.weight == 100

    def test_group_create_duplicate(self) -> None:
        self.mgr.create_group("admin")
        out = self._run("group create admin")
        assert any("ERROR:组 'admin' 已存在" in o for o in out)

    def test_group_delete_cleans_refs(self) -> None:
        self.mgr.create_group("admin")
        self.mgr.create_group("mod")
        self.mgr.group_inherit("mod", "admin")
        self.mgr.create_user("u1")
        self.mgr.user_add_group("u1", "admin")

        out = self._run("group delete admin")
        assert any("SUCCESS:删除组: admin" in o for o in out)
        assert "admin" not in self.mgr.get_user("u1").parents
        assert "admin" not in self.mgr.get_group("mod").parents

    def test_group_list(self) -> None:
        self.mgr.create_group("a")
        self.mgr.create_group("b")
        out = self._run("group list")
        assert len(self.mgr.list_groups()) == 2

    # ---------------------------------------------------------------
    # 4. 权限管理
    # ---------------------------------------------------------------
    def test_permission_set_and_check(self) -> None:
        self.mgr.create_user("u1")
        out = self._run("user u1 permission set plugin.chat true")
        assert any("SUCCESS:设置权限" in o for o in out)

        out = self._run("user u1 permission check plugin.chat")
        assert any("True" in o for o in out)

    def test_permission_unset(self) -> None:
        self.mgr.create_user("u1")
        self.mgr.user_add_node("u1", "plugin.chat", True)
        out = self._run("user u1 permission unset plugin.chat")
        assert any("SUCCESS:移除权限" in o for o in out)

    def test_permission_with_context(self) -> None:
        self.mgr.create_user("u1")
        out = self._run("user u1 permission set plugin.fly true world=nether")
        assert any("SUCCESS" in o for o in out)

        out = self._run("check u1 plugin.fly")
        assert any("False" in o for o in out)  # 无上下文不匹配

        out = self._run("check u1 plugin.fly world=nether")
        assert any("True" in o for o in out)

    def test_permission_with_duration(self) -> None:
        self.mgr.create_user("u1")
        out = self._run("user u1 permission set plugin.temp true --duration 3600")
        assert any("SUCCESS" in o for o in out)
        assert self.mgr.get_user("u1").nodes[0].expiry is not None

    def test_group_permission(self) -> None:
        self.mgr.create_group("admin")
        out = self._run("group admin permission set plugin.* true")
        assert any("SUCCESS" in o for o in out)
        assert self.mgr.check_group("admin", "plugin.anything") is True

    # ---------------------------------------------------------------
    # 5. 继承链管理
    # ---------------------------------------------------------------
    def test_parent_add_and_remove(self) -> None:
        self.mgr.create_group("admin")
        self.mgr.create_user("u1")
        out = self._run("user u1 parent add admin")
        assert any("SUCCESS:添加继承" in o for o in out)
        assert "admin" in self.mgr.get_user("u1").parents

        out = self._run("user u1 parent remove admin")
        assert any("SUCCESS:移除继承" in o for o in out)
        assert "admin" not in self.mgr.get_user("u1").parents

    def test_group_inherit(self) -> None:
        self.mgr.create_group("admin")
        self.mgr.create_group("mod")
        out = self._run("group mod parent add admin")
        assert any("SUCCESS:添加继承" in o for o in out)
        assert "admin" in self.mgr.get_group("mod").parents

    def test_cycle_inherit_detected(self) -> None:
        self.mgr.create_group("a")
        self.mgr.create_group("b")
        self.mgr.group_inherit("b", "a")
        out = self._run("group a parent add b")
        assert any("ERROR:循环继承" in o for o in out)

    def test_self_inherit_rejected(self) -> None:
        self.mgr.create_group("a")
        out = self._run("group a parent add a")
        assert any("ERROR:不能继承自身" in o for o in out)

    # ---------------------------------------------------------------
    # 6. 权限查询引擎（通配符与优先级）
    # ---------------------------------------------------------------
    def test_wildcard_single(self) -> None:
        self.mgr.create_group("g")
        self.mgr.group_add_node("g", "plugin.*", True)
        self.mgr.create_user("u1")
        self.mgr.user_add_group("u1", "g")
        assert self.mgr.check("u1", "plugin.chat") is True
        assert self.mgr.check("u1", "plugin.a.b") is False

    def test_wildcard_double(self) -> None:
        self.mgr.create_group("g")
        self.mgr.group_add_node("g", "plugin.**", True)
        self.mgr.create_user("u1")
        self.mgr.user_add_group("u1", "g")
        assert self.mgr.check("u1", "plugin") is True
        assert self.mgr.check("u1", "plugin.a.b.c") is True

    def test_explicit_deny_overrides_wildcard(self) -> None:
        self.mgr.create_group("g")
        self.mgr.group_add_node("g", "plugin.*", True)
        self.mgr.create_user("u1")
        self.mgr.user_add_group("u1", "g")
        self.mgr.user_add_node("u1", "plugin.banned", False)
        assert self.mgr.check("u1", "plugin.banned") is False
        assert self.mgr.check("u1", "plugin.other") is True

    def test_inherited_priority(self) -> None:
        """用户自身 True 优先于继承组 False。"""
        self.mgr.create_group("admin")
        self.mgr.group_add_node("admin", "plugin.x", False)
        self.mgr.create_user("u1")
        self.mgr.user_add_node("u1", "plugin.x", True)
        self.mgr.user_add_group("u1", "admin")
        assert self.mgr.check("u1", "plugin.x") is True

    # ---------------------------------------------------------------
    # 7. 轨道晋升/降级
    # ---------------------------------------------------------------
    def test_track_promote_demote(self) -> None:
        self.mgr.create_group("member")
        self.mgr.create_group("mod")
        self.mgr.create_group("admin")
        self.mgr.create_track("staff", ["member", "mod", "admin"])
        self.mgr.create_user("u1")

        out = self._run("user u1 promote staff")
        assert any("SUCCESS:晋升至: member" in o for o in out)
        assert "member" in self.mgr.get_user("u1").parents

        out = self._run("user u1 promote staff")
        assert any("SUCCESS:晋升至: mod" in o for o in out)

        out = self._run("user u1 promote staff")
        assert any("SUCCESS:晋升至: admin" in o for o in out)

        out = self._run("user u1 promote staff")
        assert any("ERROR:晋升失败" in o for o in out)

        out = self._run("user u1 demote staff")
        assert any("SUCCESS:降级至: mod" in o for o in out)

        out = self._run("user u1 demote staff")
        assert any("SUCCESS:降级至: member" in o for o in out)

        out = self._run("user u1 demote staff")
        assert any("ERROR:降级失败" in o for o in out)
        assert "member" not in self.mgr.get_user("u1").parents

    # ---------------------------------------------------------------
    # 8. 轨道 CRUD
    # ---------------------------------------------------------------
    def test_track_create_and_info(self) -> None:
        self.mgr.create_group("a")
        self.mgr.create_group("b")
        out = self._run("track create t a b")
        assert any("SUCCESS:创建轨道: t" in o for o in out)
        assert self.mgr.get_track("t").groups == ["a", "b"]

    def test_track_append_remove(self) -> None:
        self.mgr.create_group("a")
        self.mgr.create_group("b")
        self.mgr.create_group("c")
        self.mgr.create_track("t", ["a"])

        out = self._run("track t append b")
        assert any("SUCCESS" in o for o in out)
        assert "b" in self.mgr.get_track("t").groups

        out = self._run("track t remove b")
        assert any("SUCCESS" in o for o in out)
        assert "b" not in self.mgr.get_track("t").groups

    def test_track_delete(self) -> None:
        self.mgr.create_track("t")
        out = self._run("track delete t")
        assert any("SUCCESS:删除轨道: t" in o for o in out)
        assert self.mgr.get_track("t") is None

    # ---------------------------------------------------------------
    # 9. Tree 命令
    # ---------------------------------------------------------------
    def test_tree_user(self) -> None:
        self.mgr.create_group("g1")
        self.mgr.create_group("g2")
        self.mgr.group_inherit("g2", "g1")
        self.mgr.create_user("u1")
        self.mgr.user_add_group("u1", "g2")
        out = self._run("tree u1")
        # 至少应包含 g1 和 g2 的信息
        assert any("g1" in o or "g2" in o for o in out)

    def test_tree_group(self) -> None:
        self.mgr.create_group("a")
        self.mgr.create_group("b")
        self.mgr.group_inherit("b", "a")
        out = self._run("tree b")
        assert any("a" in o for o in out)

    def test_tree_nonexist(self) -> None:
        out = self._run("tree nobody")
        assert any("ERROR:持有者 'nobody' 不存在" in o for o in out)

    # ---------------------------------------------------------------
    # 10. 系统命令
    # ---------------------------------------------------------------
    def test_info(self) -> None:
        self.mgr.create_user("a")
        self.mgr.create_group("g")
        out = self._run("info")
        assert any("用户数: 1" in o for o in out)
        assert any("组数: 1" in o for o in out)

    def test_sync(self) -> None:
        self.mgr.create_user("a")
        # 加一个自定义节点，使该用户不再是默认用户，确保会被持久化
        self.mgr.user_add_node("a", "test.sync", True)
        self.mgr.save_all()
        # 在内存中删除，但磁盘还在
        del self.mgr._users["a"]
        out = self._run("sync")
        assert any("SUCCESS" in o for o in out)
        assert self.mgr.get_user("a") is not None

    def test_sync_drops_default_user(self) -> None:
        """默认用户被内存删除后，sync 不会从磁盘恢复（因为从未写入磁盘）。"""
        self.mgr.create_user("a")
        self.mgr.save_all()
        assert "a" not in self.mgr._storage.load_users()  # 确认未写入
        del self.mgr._users["a"]
        self._run("sync")
        assert self.mgr.get_user("a") is None

    def test_help(self) -> None:
        out = self._run("help")
        assert any("user" in o.lower() for o in out)

    def test_exit(self) -> None:
        result = self.cmd.execute("exit")
        assert result is False

    # ---------------------------------------------------------------
    # 11. 快捷 check 命令
    # ---------------------------------------------------------------
    def test_check_command(self) -> None:
        self.mgr.create_user("u1")
        self.mgr.user_add_node("u1", "plugin.x", True)
        out = self._run("check u1 plugin.x")
        assert any("True" in o for o in out)

    def test_check_with_context(self) -> None:
        self.mgr.create_user("u1")
        self.mgr.user_add_node("u1", "plugin.x", True, {"world": "w1"})
        out = self._run("check u1 plugin.x world=w1")
        assert any("True" in o for o in out)

    # ---------------------------------------------------------------
    # 12. 权重管理
    # ---------------------------------------------------------------
    def test_setweight(self) -> None:
        self.mgr.create_group("admin")
        out = self._run("group admin setweight 999")
        assert any("SUCCESS" in o for o in out)
        assert self.mgr.get_group("admin").weight == 999

    # ---------------------------------------------------------------
    # 13. 异常与边界
    # ---------------------------------------------------------------
    def test_unknown_command(self) -> None:
        out = self._run("foobar")
        assert any("ERROR:未知命令" in o for o in out)

    def test_empty_command(self) -> None:
        out = self._run("")
        assert out == []

    def test_permission_unset_nonexist(self) -> None:
        self.mgr.create_user("u1")
        out = self._run("user u1 permission unset nonexist")
        assert any("ERROR:权限不存在" in o for o in out)

    def test_promote_unknown_track(self) -> None:
        self.mgr.create_user("u1")
        out = self._run("user u1 promote ghost")
        assert any("ERROR:晋升失败" in o for o in out)

    def test_verbose_off_when_not_on(self) -> None:
        out = self._run("verbose off")
        assert any("INFO:已关闭" in o for o in out)

    def test_verbose_nonexist_user(self) -> None:
        out = self._run("verbose nobody")
        assert any("ERROR:用户 'nobody' 不存在" in o for o in out)


class TestCLIDebugMode:
    """调试模式测试。"""

    def setup_method(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.mgr = LuckPermsManager(self.tmpdir)
        self.fmt = CaptureFormatter(debug=True)
        self.cmd = LPCommand(self.mgr, self.fmt)

    def teardown_method(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run(self, command: str) -> list[str]:
        self.fmt.outputs.clear()
        self.cmd.execute(command)
        return list(self.fmt.outputs)

    def test_debug_shows_detail(self) -> None:
        self.mgr.create_user("u1")
        out = self._run("user u1 info")
        # debug=True 时 formatter 会输出更多内容，但至少应有用户数据
        assert any("u1" in o for o in out)


class TestCLITabCompletion:
    """Tab 补全逻辑测试（不依赖 prompt_toolkit）。"""

    def setup_method(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.mgr = LuckPermsManager(self.tmpdir)
        self.mgr.create_user("steve")
        self.mgr.create_group("admin")
        self.mgr.create_track("staff")
        self.completer = LPCompleter(self.mgr)

    def teardown_method(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _complete(self, text: str) -> list[str]:
        from prompt_toolkit.document import Document
        doc = Document(text, len(text))
        return [c.text for c in self.completer.get_completions(doc, None)]

    def test_complete_user_id(self) -> None:
        try:
            from prompt_toolkit.document import Document
        except ImportError:
            pytest.skip("prompt_toolkit 未安装")

        results = self._complete("user s")
        assert any("steve" in r for r in results)

    def test_complete_group_name(self) -> None:
        try:
            from prompt_toolkit.document import Document
        except ImportError:
            pytest.skip("prompt_toolkit 未安装")

        results = self._complete("group a")
        assert any("admin" in r for r in results)

    def test_complete_subcommand(self) -> None:
        try:
            from prompt_toolkit.document import Document
        except ImportError:
            pytest.skip("prompt_toolkit 未安装")

        results = self._complete("user steve ")
        assert any("info" in r for r in results)
        assert any("permission" in r for r in results)