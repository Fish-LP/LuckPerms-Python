"""
LuckPermsAPI 持久化存储。

默认使用单文件布局 ``luckperms.{ext}``（原子写入，保证 users/groups/tracks 整体一致），
同时兼容旧版三文件布局（users/groups/tracks），首次加载时自动迁移。
接口抽象便于替换为数据库等高级后端。
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, TextIO

import yaml

from .constants import DATA_FILE_STEM

log = logging.getLogger("luckperms.storage")


def _ensure_dict(data: Any, path: Path) -> dict[str, Any]:
    """校验数据文件顶层为字典。"""
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"数据文件格式无效（顶层应为字典）: {path}")
    return data


def _atomic_write(path: Path, writer: Callable[[TextIO], None]) -> None:
    """原子写入：先写同目录临时文件，成功后替换目标文件。

    Args:
        path: 目标文件路径。
        writer: 接收已打开文本句柄的写入函数。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            writer(f)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


class StorageBackend(Protocol):
    """存储后端协议。"""

    extension: str

    def load(self, path: Path) -> dict[str, Any]:
        ...

    def save(self, path: Path, data: dict[str, Any]) -> None:
        ...


class YAMLBackend:
    """YAML 存储后端。"""

    extension = "yml"

    def load(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError(f"数据文件解析失败（YAML 语法错误）: {path}") from e
        return _ensure_dict(data, path)

    def save(self, path: Path, data: dict[str, Any]) -> None:
        def _write(f: TextIO) -> None:
            yaml.dump(
                data, f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            )

        _atomic_write(path, _write)


class JSONBackend:
    """JSON 存储后端。"""

    extension = "json"

    def load(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"数据文件解析失败（JSON 语法错误）: {path}") from e
        return _ensure_dict(data, path)

    def save(self, path: Path, data: dict[str, Any]) -> None:
        def _write(f: TextIO) -> None:
            json.dump(data, f, ensure_ascii=False, indent=2)

        _atomic_write(path, _write)


class LuckPermsStorage:
    """LuckPerms 统一存储管理器。

    采用单文件布局 ``luckperms.{ext}``，一次原子写入保证 users/groups/tracks
    整体一致。首次加载时若检测到旧版三文件布局（users/groups/tracks），
    会自动迁移到单文件，旧文件保留不删。

    Args:
        data_dir: 数据目录路径。
        backend: 存储后端，默认 YAMLBackend。
    """

    def __init__(
        self,
        data_dir: Path | str,
        backend: Optional[StorageBackend] = None,
    ):
        self._data_dir = Path(data_dir)
        self._backend = backend or YAMLBackend()
        ext = self._backend.extension
        self._data_path = self._data_dir / f"{DATA_FILE_STEM}.{ext}"
        # 旧版三文件布局（仅用于兼容读取与迁移）
        self._legacy_paths = {
            "users": self._data_dir / f"users.{ext}",
            "groups": self._data_dir / f"groups.{ext}",
            "tracks": self._data_dir / f"tracks.{ext}",
        }

    @property
    def data_path(self) -> Path:
        """单文件数据路径。"""
        return self._data_path

    def load_all(self) -> tuple[dict, dict, dict]:
        """加载 users / groups / tracks 三份数据。

        单文件存在时直接读取；否则回退读取旧版三文件布局，
        并在发现旧数据时自动迁移为单文件（旧文件保留）。

        Return:
            (users, groups, tracks) 三元组。
        """
        if self._data_path.exists():
            data = self._backend.load(self._data_path)
            return (
                data.get("users", {}),
                data.get("groups", {}),
                data.get("tracks", {}),
            )

        users = self._backend.load(self._legacy_paths["users"]).get("users", {})
        groups = self._backend.load(self._legacy_paths["groups"]).get("groups", {})
        tracks = self._backend.load(self._legacy_paths["tracks"]).get("tracks", {})

        if users or groups or tracks:
            self.save_all(users, groups, tracks)
            log.info(
                "检测到旧版三文件布局，已自动迁移到单文件: %s（旧文件已保留，可手动删除）",
                self._data_path,
            )
        return users, groups, tracks

    def save_all(
        self,
        users: dict[str, dict],
        groups: dict[str, dict],
        tracks: dict[str, dict],
    ) -> None:
        """原子写入单文件，一次性保存全部数据。"""
        self._backend.save(
            self._data_path,
            {"users": users, "groups": groups, "tracks": tracks},
        )

    # ------------------------------------------------------------------
    # 兼容旧版按类型读写 API（内部基于单文件实现）
    # ------------------------------------------------------------------
    def load_users(self) -> dict[str, dict]:
        return self.load_all()[0]

    def save_users(self, users: dict[str, dict]) -> None:
        _, groups, tracks = self.load_all()
        self.save_all(users, groups, tracks)

    def load_groups(self) -> dict[str, dict]:
        return self.load_all()[1]

    def save_groups(self, groups: dict[str, dict]) -> None:
        users, _, tracks = self.load_all()
        self.save_all(users, groups, tracks)

    def load_tracks(self) -> dict[str, dict]:
        return self.load_all()[2]

    def save_tracks(self, tracks: dict[str, dict]) -> None:
        users, groups, _ = self.load_all()
        self.save_all(users, groups, tracks)
