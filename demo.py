#!/usr/bin/env python3
"""
LuckPerms-Python 功能演示脚本。

展示与原版 LuckPerms 风格一致的权限管理系统核心能力：
- 用户/组/轨道的 CRUD
- 上下文敏感权限（世界、服务器等维度）
- 通配符系统（* 单段, ** 多段）
- 继承链与权重优先级
- 显式拒绝覆盖
- 临时权限（过期时间）
- 晋升轨道（promote/demote）
- YAML/JSON 持久化
- Web Editor 序列化兼容

运行方式::

    python demo.py

依赖::

    pip install -e .
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

from luckperms import LuckPermsManager


def print_section(title: str) -> None:
    print(f"\n{'=' * 50}")
    print(f"  {title}")
    print(f"{'=' * 50}")


def print_result(desc: str, result: bool) -> None:
    icon = "✅" if result else "❌"
    print(f"  {icon} {desc}: {result}")


def main() -> None:
    # 使用临时目录作为数据存储，演示结束后自动清理
    data_dir = Path(tempfile.gettempdir()) / "luckperms_demo"
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    print("LuckPerms-Python 功能演示")
    print(f"数据目录: {data_dir}")

    mgr = LuckPermsManager(data_dir)

    # ================================================================
    # 1. 基础实体创建
    # ================================================================
    print_section("1. 基础实体创建")

    # 创建组（带权重）
    mgr.create_group("default", "默认组", weight=0)
    mgr.create_group("vip", "VIP", weight=50)
    mgr.create_group("mod", "版主", weight=100)
    mgr.create_group("admin", "管理员", weight=200)

    # 设置组权限
    mgr.group_add_node("default", "plugin.chat", True)
    mgr.group_add_node("default", "plugin.spawn", True)
    mgr.group_add_node("vip", "plugin.fly", True)
    mgr.group_add_node("mod", "plugin.kick", True)
    mgr.group_add_node("admin", "plugin.*", True)      # 通配符：允许所有 plugin 权限
    mgr.group_add_node("admin", "plugin.ban", False)   # 显式拒绝覆盖通配符

    # 构建继承链: mod -> admin 是错误的，应该是 mod 继承 vip, vip 继承 default
    # 正确的继承链: default <- vip <- mod <- admin
    mgr.group_inherit("vip", "default")
    mgr.group_inherit("mod", "vip")
    mgr.group_inherit("admin", "mod")

    # 创建晋升轨道
    mgr.create_track("staff", ["default", "vip", "mod", "admin"])

    # 创建用户
    mgr.create_user("u_alice", "Alice")
    mgr.create_user("u_bob", "Bob")
    mgr.create_user("u_charlie", "Charlie")

    print("  已创建 4 个组、1 条轨道、3 个用户")
    print(f"  组列表: {[g.name for g in mgr.list_groups()]}")
    print(f"  用户列表: {[u.unique_id for u in mgr.list_users()]}")

    # ================================================================
    # 2. 用户加入组与权限检查
    # ================================================================
    print_section("2. 用户加入组与权限检查")

    mgr.user_add_group("u_alice", "default")
    mgr.user_add_group("u_bob", "vip")
    mgr.user_add_group("u_charlie", "admin")

    print("  Alice -> default")
    print("  Bob -> vip")
    print("  Charlie -> admin")

    # Alice (default) 检查
    print_result("Alice 可以 chat", mgr.check("u_alice", "plugin.chat"))
    print_result("Alice 可以 fly", mgr.check("u_alice", "plugin.fly"))

    # Bob (vip, 继承 default) 检查
    print_result("Bob 可以 chat (继承 default)", mgr.check("u_bob", "plugin.chat"))
    print_result("Bob 可以 fly (vip 权限)", mgr.check("u_bob", "plugin.fly"))
    print_result("Bob 可以 kick (无权限)", mgr.check("u_bob", "plugin.kick"))

    # Charlie (admin, 继承 mod->vip->default) 检查
    print_result("Charlie 可以 chat (多级继承)", mgr.check("u_charlie", "plugin.chat"))
    print_result("Charlie 可以 kick (继承 mod)", mgr.check("u_charlie", "plugin.kick"))
    print_result("Charlie 可以 fly (继承 vip)", mgr.check("u_charlie", "plugin.fly"))

    # ================================================================
    # 3. 通配符系统
    # ================================================================
    print_section("3. 通配符系统")

    # admin 组已有 plugin.* = True
    print_result("admin 通配 plugin.anything", mgr.check("u_charlie", "plugin.anything"))
    print_result("admin 通配 plugin.admin", mgr.check("u_charlie", "plugin.admin"))

    # 显式拒绝覆盖通配符
    print_result("admin 显式拒绝 plugin.ban", mgr.check("u_charlie", "plugin.ban") is False)

    # 测试 ** 多段通配符
    mgr.group_add_node("admin", "server.**.status", True)
    print_result("** 匹配 server.status", mgr.check("u_charlie", "server.status"))
    print_result("** 匹配 server.world.nether.status", mgr.check("u_charlie", "server.world.nether.status"))

    # 测试 * 单段通配符（不匹配多级）
    mgr.group_add_node("mod", "cmd.*", True)
    print_result("* 匹配 cmd.help", mgr.check("u_bob", "cmd.help"))
    print_result("* 不匹配 cmd.group.add", mgr.check("u_bob", "cmd.group.add") is False)

    # ================================================================
    # 4. 上下文敏感权限
    # ================================================================
    print_section("4. 上下文敏感权限")

    # 给 Bob 添加世界上下文权限：仅在 nether 世界可以 fly
    mgr.user_add_node("u_bob", "plugin.fly", True, {"world": "nether"})

    print("  Bob 的 plugin.fly 权限绑定 world=nether")
    print_result("Bob 在 nether 可以 fly", mgr.check("u_bob", "plugin.fly", {"world": "nether"}))
    print_result("Bob 在 overworld 不能 fly", mgr.check("u_bob", "plugin.fly", {"world": "overworld"}) is False)
    print_result("Bob 无上下文不能 fly (上下文不匹配)", mgr.check("u_bob", "plugin.fly") is False)

    # 多上下文：需要同时满足 server 和 world
    mgr.user_add_node("u_alice", "plugin.gm", True, {"server": "s1", "world": "w1"})
    print("  Alice 的 plugin.gm 需要 server=s1 + world=w1")
    print_result("Alice 在 s1+w1 可以 gm", mgr.check("u_alice", "plugin.gm", {"server": "s1", "world": "w1"}))
    print_result("Alice 在 s1+w2 不能 gm", mgr.check("u_alice", "plugin.gm", {"server": "s1", "world": "w2"}) is False)

    # ================================================================
    # 5. 临时权限（过期时间）
    # ================================================================
    print_section("5. 临时权限（过期时间）")

    mgr.user_add_node("u_alice", "plugin.temp", True, duration=2)  # 2 秒后过期
    print("  Alice 获得 plugin.temp，有效期 2 秒")
    print_result("Alice 立即检查 temp", mgr.check("u_alice", "plugin.temp"))

    print("  等待 2.5 秒...")
    time.sleep(2.5)
    print_result("Alice 过期后检查 temp", mgr.check("u_alice", "plugin.temp") is False)

    # ================================================================
    # 6. 继承树可视化（CLI 风格文本输出）
    # ================================================================
    print_section("6. 继承树")

    def print_tree(holder_id: str, depth: int = 3) -> None:
        user = mgr.get_user(holder_id)
        group = mgr.get_group(holder_id)
        target = user or group
        if not target:
            print(f"  持有者 '{holder_id}' 不存在")
            return

        print(f"  \n  {holder_id} ({'user' if user else 'group'})")
        visited: set[str] = set()
        queue = [(p, 1) for p in target.parents]
        while queue:
            name, level = queue.pop(0)
            if name in visited:
                print(f"  {'  ' * level}└── {name} [循环引用，已省略]")
                continue
            visited.add(name)
            g = mgr.get_group(name)
            if not g:
                continue
            print(f"  {'  ' * level}└── {g.name} (weight={g.weight}, nodes={len(g.nodes)})")
            for n in g.nodes:
                val = "T" if n.value else "F"
                print(f"  {'  ' * (level + 1)}├── {n.key} = {val}")
            if level < depth:
                queue.extend((p, level + 1) for p in g.parents)

    print_tree("u_charlie")

    # ================================================================
    # 7. 晋升轨道（Track）
    # ================================================================
    print_section("7. 晋升轨道 (Track)")

    # 创建一个新用户，沿 staff 轨道晋升
    mgr.create_user("u_newbie", "Newbie")
    print("  Newbie 初始无组")

    result = mgr.promote("u_newbie", "staff")
    print(f"  promote -> {result} | 当前组: {mgr.get_user('u_newbie').parents}")

    result = mgr.promote("u_newbie", "staff")
    print(f"  promote -> {result} | 当前组: {mgr.get_user('u_newbie').parents}")

    result = mgr.promote("u_newbie", "staff")
    print(f"  promote -> {result} | 当前组: {mgr.get_user('u_newbie').parents}")

    result = mgr.promote("u_newbie", "staff")
    print(f"  promote -> {result} (已到最高级) | 当前组: {mgr.get_user('u_newbie').parents}")

    result = mgr.demote("u_newbie", "staff")
    print(f"  demote -> {result} | 当前组: {mgr.get_user('u_newbie').parents}")

    result = mgr.demote("u_newbie", "staff")
    print(f"  demote -> {result} | 当前组: {mgr.get_user('u_newbie').parents}")

    result = mgr.demote("u_newbie", "staff")
    print(f"  demote -> {result} (已移除所有轨道组) | 当前组: {mgr.get_user('u_newbie').parents}")

    # ================================================================
    # 8. Web Editor 序列化兼容
    # ================================================================
    print_section("8. Web Editor 序列化兼容")

    payload = mgr.to_webeditor_payload()
    meta = payload["metadata"]
    holders = payload["permissionHolders"]
    tracks = payload["tracks"]

    print(f"  元数据:")
    print(f"    pluginVersion: {meta['pluginVersion']}")
    print(f"    platform: {meta['platform']}")
    print(f"    commandAlias: {meta['commandAlias']}")
    print(f"  权限持有者: {len(holders)} 个")
    print(f"    - 用户: {sum(1 for h in holders if h['type'] == 'user')}")
    print(f"    - 组:   {sum(1 for h in holders if h['type'] == 'group')}")
    print(f"  轨道: {len(tracks)} 条")
    print(f"  已知权限: {len(payload['knownPermissions'])} 个")
    print(f"  潜在上下文: {list(payload['potentialContexts'].keys())}")

    # 验证序列化/反序列化一致性
    print("  验证 payload 往返一致性...")
    mgr2 = LuckPermsManager(data_dir / "roundtrip")
    mgr2.apply_webeditor_changes(payload)

    print_result("Charlie 往返后仍可 chat", mgr2.check("u_charlie", "plugin.chat"))
    print_result("Charlie 往返后仍拒绝 ban", mgr2.check("u_charlie", "plugin.ban") is False)
    print_result("Newbie 往返后保留 default", mgr2.get_user("u_newbie").parents == ["default"])

    # ================================================================
    # 9. 持久化验证
    # ================================================================
    print_section("9. 持久化验证")

    mgr.save_all()
    print(f"  数据文件已保存到: {data_dir}")
    for f in sorted(data_dir.iterdir()):
        if f.is_file():
            print(f"    - {f.name} ({f.stat().st_size} bytes)")

    # 新建管理器实例加载数据
    mgr3 = LuckPermsManager(data_dir)
    print("  新实例加载数据完成")
    print_result("Alice 加载后仍可 chat", mgr3.check("u_alice", "plugin.chat"))
    print_result("Bob 加载后仍受上下文限制", mgr3.check("u_bob", "plugin.fly", {"world": "nether"}))

    # ================================================================
    # 清理
    # ================================================================
    print_section("演示结束")
    print(f"  数据目录保留供查看: {data_dir}")
    print("  如需清理，请手动删除该目录。")


if __name__ == "__main__":
    main()