"""
LuckPermsAPI CLI 自动化回归测试。

覆盖所有子命令、边界条件和异常路径。
运行::

    pytest tests/test_cli.py -v
"""

from __future__ import annotations

import tempfile

import pytest

from luckperms.cli import Formatter, LPCommand, LPCompleter
from luckperms.manager import LuckPermsManager
from luckperms.models import User

try:
    from prompt_toolkit.document import Document
except ImportError:
    pytest.skip("prompt_toolkit 未安装")


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
        if self._debug:
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
        self._run("user list")
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
        self._run("group list")
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

    def test_track_insert(self) -> None:
        self.mgr.create_group("a")
        self.mgr.create_group("b")
        self.mgr.create_track("t", ["a"])
        out = self._run("track t insert 0 b")
        assert any("SUCCESS:已插入 b 到位置 0" in o for o in out)
        assert self.mgr.get_track("t").groups == ["b", "a"]
        # 持久化验证
        mgr2 = LuckPermsManager(self.tmpdir)
        assert mgr2.get_track("t").groups == ["b", "a"]

    def test_track_insert_invalid_index(self) -> None:
        self.mgr.create_track("t", [])
        out = self._run("track t insert 5 x")
        assert any("ERROR:插入失败" in o for o in out)

    def test_track_list(self) -> None:
        self.mgr.create_track("t", [])
        out = self._run("track list")
        assert not any("ERROR" in o for o in out)

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

    def test_sync_clears_stale_memory(self) -> None:
        """sync 应彻底重载，磁盘上不存在的内存对象应被清除。"""
        self.mgr.create_user("real", "RealUser")
        self.mgr._users["ghost"] = User("ghost")
        self._run("sync")
        assert self.mgr.get_user("ghost") is None
        assert self.mgr.get_user("real") is not None

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

    def test_error_output_has_no_traceback_when_debug_off(self) -> None:
        """debug 关闭时错误不应泄漏 traceback。"""
        self.mgr.create_group("g")
        out = self._run("group g setweight abc")
        assert any("ERROR:" in o for o in out)
        assert not any("Traceback" in o for o in out)
        assert not any('File "' in o for o in out)

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

        doc = Document(text, len(text))
        return [c.text for c in self.completer.get_completions(doc, None)]

    def test_complete_user_id(self) -> None:

        results = self._complete("user s")
        assert any("steve" in r for r in results)

    def test_complete_group_name(self) -> None:

        results = self._complete("group a")
        assert any("admin" in r for r in results)

    def test_complete_subcommand(self) -> None:

        results = self._complete("user steve ")
        assert any("info" in r for r in results)
        assert any("permission" in r for r in results)


class TestCLITemporaryCommands:
    """临时权限、meta、清理类命令的 CLI 测试。"""

    def setup_method(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.mgr = LuckPermsManager(self.tmpdir)
        self.mgr.create_group("default")
        self.mgr.create_group("vip")
        self.mgr.group_add_node("vip", "plugin.vip", True)
        self.mgr.create_user("u1", "User One")
        self.fmt = CaptureFormatter(debug=False)
        self.cmd = LPCommand(self.mgr, self.fmt)

    def teardown_method(self) -> None:
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run(self, command: str) -> list[str]:
        self.fmt.outputs.clear()
        self.cmd.execute(command)
        return list(self.fmt.outputs)

    # ---------------------------------------------------------------
    # 临时权限
    # ---------------------------------------------------------------
    def test_settemp_command(self) -> None:
        out = self._run("user u1 permission settemp plugin.a true 1h")
        assert any("SUCCESS:设置临时权限" in o for o in out)
        node = self.mgr.get_user("u1").get_node("plugin.a")
        assert node is not None and node.expiry is not None

    def test_settemp_with_modifier_flag(self) -> None:
        assert any(
            "SUCCESS" in o
            for o in self._run("user u1 permission settemp plugin.a true 1h --deny")
        )
        out = self._run("user u1 permission settemp plugin.a true 1h --deny")
        assert any("ERROR" in o for o in out)

    def test_settemp_invalid_duration(self) -> None:
        out = self._run("user u1 permission settemp plugin.a true nonsense")
        assert any("ERROR" in o for o in out)
        assert self.mgr.get_user("u1").get_node("plugin.a") is None

    def test_unsettemp_command(self) -> None:
        self._run("user u1 permission settemp plugin.a true 1h")
        out = self._run("user u1 permission unsettemp plugin.a")
        assert any("SUCCESS:已移除临时权限" in o for o in out)
        assert self.mgr.get_user("u1").get_node("plugin.a") is None

    def test_unsettemp_reduce_duration(self) -> None:
        self._run("user u1 permission settemp plugin.a true 2h")
        out = self._run("user u1 permission unsettemp plugin.a 30m")
        assert any("SUCCESS:临时权限剩余" in o for o in out)

    def test_permission_clear_command(self) -> None:
        self.mgr.user_add_node("u1", "plugin.x", True)
        out = self._run("user u1 permission clear")
        assert any("SUCCESS:已清空权限节点" in o for o in out)
        assert self.mgr.get_user("u1").nodes == []

    def test_group_settemp_command(self) -> None:
        out = self._run("group vip permission settemp plugin.g true 30m")
        assert any("SUCCESS:设置临时权限" in o for o in out)
        assert self.mgr.get_group("vip").get_node("plugin.g").expiry is not None

    # ---------------------------------------------------------------
    # 临时继承
    # ---------------------------------------------------------------
    def test_addtemp_parent(self) -> None:
        out = self._run("user u1 parent addtemp vip 1d")
        assert any("SUCCESS:添加临时继承" in o for o in out)
        assert self.mgr.check("u1", "plugin.vip") is True

    def test_removetemp_parent(self) -> None:
        self._run("user u1 parent addtemp vip 1d")
        out = self._run("user u1 parent removetemp vip")
        assert any("SUCCESS:已移除临时权限" in o for o in out)
        assert self.mgr.check("u1", "plugin.vip") is False

    def test_parent_set_and_clear(self) -> None:
        out = self._run("user u1 parent set vip")
        assert any("SUCCESS:已设置父组" in o for o in out)
        assert "vip" in self.mgr.get_user("u1").parents

        out = self._run("user u1 parent clear")
        assert any("SUCCESS:已清空父组" in o for o in out)
        assert self.mgr.get_user("u1").parents == ["default"]

    def test_parent_settrack(self) -> None:
        self.mgr.create_track("staff", ["default", "vip"])
        out = self._run("user u1 parent settrack staff 2")
        assert any("SUCCESS:已设置轨道" in o for o in out)
        assert "vip" in self.mgr.get_user("u1").parents

    def test_parent_cleartrack(self) -> None:
        self.mgr.create_track("staff", ["default", "vip"])
        self._run("user u1 parent add vip")
        out = self._run("user u1 parent cleartrack staff")
        assert any("SUCCESS:已清除轨道" in o for o in out)
        assert "vip" not in self.mgr.get_user("u1").parents

    # ---------------------------------------------------------------
    # meta
    # ---------------------------------------------------------------
    def test_meta_addprefix_and_info(self) -> None:
        out = self._run("user u1 meta addprefix 100 &cAdmin")
        assert any("SUCCESS:已设置 meta" in o for o in out)
        out = self._run("user u1 meta info")
        assert any("&cAdmin" in o for o in out)

    def test_meta_set_and_unset_custom(self) -> None:
        out = self._run("user u1 meta set home world")
        assert any("SUCCESS:已设置 meta" in o for o in out)
        out = self._run("user u1 meta unset home")
        assert any("SUCCESS:已移除 meta" in o for o in out)

    def test_meta_settemp(self) -> None:
        out = self._run("user u1 meta set home world 1h")
        assert any("SUCCESS:已设置临时 meta" in o for o in out)
        assert self.mgr.get_user("u1").get_node("meta.home.world").expiry is not None

    def test_meta_setprefix_replaces(self) -> None:
        self._run("user u1 meta addprefix 1 Old")
        self._run("user u1 meta setprefix 2 New")
        assert self.mgr.get_meta("u1", "prefix") == "New"

    def test_meta_removeprefix(self) -> None:
        self._run("user u1 meta addprefix 5 X")
        out = self._run("user u1 meta removeprefix 5")
        assert any("SUCCESS:已移除 prefix" in o for o in out)
        assert self.mgr.get_meta("u1", "prefix") is None

    def test_meta_clear(self) -> None:
        self._run("user u1 meta addprefix 1 A")
        self._run("user u1 meta addsuffix 1 B")
        out = self._run("user u1 meta clear")
        assert any("SUCCESS:已清空 meta 节点" in o for o in out)
        assert self.mgr.get_meta("u1", "prefix") is None

    # ---------------------------------------------------------------
    # 组与轨道
    # ---------------------------------------------------------------
    def test_group_listmembers(self) -> None:
        out = self._run("group vip listmembers")
        assert any("(无成员)" in o for o in out)
        self._run("user u1 parent add vip")
        out = self._run("group vip listmembers")
        assert any("u1" in o for o in out)

    def test_group_setdisplayname(self) -> None:
        out = self._run("group vip setdisplayname VIP组")
        assert any("SUCCESS" in o for o in out)
        assert self.mgr.get_group("vip").get_meta("displayname") == "VIP组"

    def test_group_clear(self) -> None:
        self.mgr.group_add_node("vip", "plugin.x", True)
        out = self._run("group vip clear")
        assert any("SUCCESS:已清空组" in o for o in out)
        assert self.mgr.get_group("vip").nodes == []

    def test_user_showtracks(self) -> None:
        self.mgr.create_track("staff", ["default", "vip"])
        out = self._run("user u1 showtracks")
        assert any("staff" in o for o in out)

    def test_user_clear(self) -> None:
        self.mgr.user_add_node("u1", "plugin.x", True)
        self._run("user u1 parent add vip")
        out = self._run("user u1 clear")
        assert any("SUCCESS:已清空用户" in o for o in out)
        assert self.mgr.get_user("u1").nodes == []

    def test_track_clear_and_rename(self) -> None:
        self.mgr.create_track("t", ["default", "vip"])
        out = self._run("track t clear")
        assert any("SUCCESS:已清空轨道" in o for o in out)
        out = self._run("track t rename team")
        assert any("SUCCESS:轨道 t 已重命名为 team" in o for o in out)

    def test_track_insert_new_order(self) -> None:
        self.mgr.create_track("t", ["default"])
        out = self._run("track t insert vip 1")
        assert any("SUCCESS:已插入 vip 到位置 1" in o for o in out)
        assert self.mgr.get_track("t").groups == ["default", "vip"]

    # ---------------------------------------------------------------
    # verbose
    # ---------------------------------------------------------------
    def test_verbose_listen_and_off(self) -> None:
        out = self._run("verbose u1")
        assert any("已开启 verbose 监听" in o for o in out)
        self.mgr.check("u1", "plugin.zzz")
        assert any("[DENY]" in o for o in self.fmt.outputs)
        out = self._run("verbose off")
        assert any("已关闭" in o for o in out)
