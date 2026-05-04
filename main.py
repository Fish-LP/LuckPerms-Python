#!/usr/bin/env python3
"""
LuckPerms Web Editor 官方可视化编辑器演示入口。

一键生成本地权限数据，启动 Web Editor 会话，在浏览器中实时编辑。
编辑完成后点击 Save，变更自动通过 WebSocket 回传并应用到本地。

运行方式::

    python demo_webeditor.py

依赖::

    pip install -e ".[dev]"
"""
from __future__ import annotations

import asyncio
import os
import shutil
import signal
import sys
import tempfile
import webbrowser

from luckperms import LuckPermsManager, WebEditorSession


async def main() -> None:
    """
    主流程：构造示例数据 → 启动 Web Editor → 等待变更 → 自动应用。
    """
    # -------------------------------------------------
    # 1. 初始化管理器（使用全新临时目录，避免旧数据冲突）
    # -------------------------------------------------
    data_dir = os.path.join(tempfile.gettempdir(), "lp_webeditor_demo")
    # 若存在旧数据则清理，确保每次演示都是全新环境
    if os.path.exists(data_dir):
        shutil.rmtree(data_dir)
    os.makedirs(data_dir, exist_ok=True)

    mgr = LuckPermsManager(data_dir)
    print(f"[初始化] 数据目录: {data_dir}")

    # -------------------------------------------------
    # 2. 构造丰富的演示数据
    # -------------------------------------------------
    # 轨道：staff 晋升链
    mgr.create_group("default", "默认组")
    mgr.create_group("vip", "VIP 玩家", weight=10)
    mgr.create_group("helper", "助手", weight=50)
    mgr.create_group("mod", "版主", weight=100)
    mgr.create_group("admin", "管理员", weight=1000)

    mgr.create_track("staff", ["default", "vip", "helper", "mod", "admin"])

    # 组权限
    mgr.group_add_node("default", "plugin.chat", True)
    mgr.group_add_node("default", "plugin.spawn", True)

    mgr.group_add_node("vip", "plugin.fly", True)
    mgr.group_add_node("vip", "plugin.colorchat", True)

    mgr.group_add_node("helper", "plugin.kick", True)
    mgr.group_add_node("helper", "plugin.mute", True)
    mgr.group_add_node("helper", "plugin.warn", True)

    mgr.group_add_node("mod", "plugin.ban", True)
    mgr.group_add_node("mod", "plugin.unban", True)
    mgr.group_add_node("mod", "plugin.**.admin", True)   # 多段通配

    mgr.group_add_node("admin", "plugin.*", True)        # 单段通配
    mgr.group_add_node("admin", "plugin.banned", False)    # 显式拒绝覆盖通配

    # 继承链：mod -> helper -> vip -> default
    mgr.group_inherit("helper", "vip")
    mgr.group_inherit("mod", "helper")
    mgr.group_inherit("admin", "mod")

    # 创建用户
    mgr.create_user("steve", "Steve")
    mgr.create_user("alex", "Alex")
    mgr.create_user("notch", "Notch")

    # 分配组
    mgr.user_add_group("steve", "default")
    mgr.user_add_group("alex", "mod")
    mgr.user_add_group("notch", "admin")

    # 用户专属权限（带上下文）
    mgr.user_add_node("steve", "plugin.builder", True, {"world": "creative"})
    mgr.user_add_node("alex", "plugin.vanish", True, {"server": "lobby"})

    # 临时权限（1 小时后过期）
    mgr.user_add_node("notch", "plugin.debug", True, duration=3600)

    print("[数据] 已生成 5 个组、3 个用户、1 条晋升轨道")

    # -------------------------------------------------
    # 3. 定义 Web Editor 回调
    # -------------------------------------------------
    def get_payload() -> dict:
        """获取当前全量权限数据，用于上传到编辑器。"""
        return mgr.to_webeditor_payload()

    def apply_changes(payload: dict) -> None:
        """
        应用编辑器返回的变更，并立即持久化到本地文件。

        Args:
            payload: 编辑器回传的完整 users / groups / tracks 数据。
        """
        mgr.apply_webeditor_changes(payload)
        mgr.save_all()
        print("[同步] Web Editor 变更已应用并持久化")

    # -------------------------------------------------
    # 4. 启动 Web Editor 会话
    # -------------------------------------------------
    session = WebEditorSession(
        get_payload=get_payload,
        apply_changes=apply_changes,
    )

    url = await session.open()
    print(f"[会话] Web Editor URL: {url}")

    # 尝试自动打开浏览器（Linux/macOS/Windows 均兼容）
    try:
        webbrowser.open(url, new=2)
        print("[浏览器] 已尝试自动打开编辑器页面")
    except Exception:
        print("[浏览器] 自动打开失败，请手动复制上方 URL 到浏览器")

    # -------------------------------------------------
    # 5. 保持运行，等待 Ctrl+C 或 WebSocket 断开
    # -------------------------------------------------
    print("\\n[提示] 在浏览器中编辑权限，点击 Save 后变更会自动回传。")
    print("[提示] 按 Ctrl+C 停止程序。\\n")

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _on_signal(sig: int, frame) -> None:
        print(f"\\n[信号] 收到 {signal.Signals(sig).name}，正在关闭会话...")
        stop_event.set()

    # 注册信号处理（Windows 仅支持 SIGINT）
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, ValueError):
            signal.signal(sig, _on_signal)

    try:
        await stop_event.wait()
    finally:
        await session.close()
        print("[退出] 会话已关闭，数据保存在:", data_dir)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)