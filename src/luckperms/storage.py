"""
LuckPermsAPI 持久化存储。

使用 YAML/JSON 作为后端，接口抽象便于替换为数据库等高级后端。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

import yaml


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
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def save(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(
                data, f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            )


class JSONBackend:
    """JSON 存储后端。"""

    extension = "json"

    def load(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


class LuckPermsStorage:
    """LuckPerms 统一存储管理器。

    管理 users.{ext}, groups.{ext}, tracks.{ext} 三个数据文件。

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
        self._users_path = self._data_dir / f"users.{ext}"
        self._groups_path = self._data_dir / f"groups.{ext}"
        self._tracks_path = self._data_dir / f"tracks.{ext}"

    def load_users(self) -> dict[str, dict]:
        return self._backend.load(self._users_path).get("users", {})

    def save_users(self, users: dict[str, dict]) -> None:
        self._backend.save(self._users_path, {"users": users})

    def load_groups(self) -> dict[str, dict]:
        return self._backend.load(self._groups_path).get("groups", {})

    def save_groups(self, groups: dict[str, dict]) -> None:
        self._backend.save(self._groups_path, {"groups": groups})

    def load_tracks(self) -> dict[str, dict]:
        return self._backend.load(self._tracks_path).get("tracks", {})

    def save_tracks(self, tracks: dict[str, dict]) -> None:
        self._backend.save(self._tracks_path, {"tracks": tracks})

    def load_all(self) -> tuple[dict, dict, dict]:
        return self.load_users(), self.load_groups(), self.load_tracks()

    def save_all(
        self,
        users: dict[str, dict],
        groups: dict[str, dict],
        tracks: dict[str, dict],
    ) -> None:
        self.save_users(users)
        self.save_groups(groups)
        self.save_tracks(tracks)
