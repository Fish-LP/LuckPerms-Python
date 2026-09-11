"""
LuckPermsAPI 存储层单元测试。
"""
import json
import os
import tempfile
from pathlib import Path

import pytest
import yaml

from luckperms.storage import JSONBackend, LuckPermsStorage, YAMLBackend


class TestYAMLBackend:
    def test_save_and_load(self):
        tmpdir = tempfile.mkdtemp()
        path = Path(tmpdir) / "test.yml"
        backend = YAMLBackend()
        data = {"users": {"u1": {"id": "u1", "nodes": []}}}
        backend.save(path, data)
        assert path.exists()
        loaded = backend.load(path)
        assert loaded == data

    def test_load_missing_file(self):
        tmpdir = tempfile.mkdtemp()
        path = Path(tmpdir) / "missing.yml"
        backend = YAMLBackend()
        assert backend.load(path) == {}

    def test_load_empty_file(self):
        tmpdir = tempfile.mkdtemp()
        path = Path(tmpdir) / "empty.yml"
        path.write_text("")
        backend = YAMLBackend()
        assert backend.load(path) == {}

    def test_save_creates_parent_dirs(self):
        tmpdir = tempfile.mkdtemp()
        path = Path(tmpdir) / "sub" / "dir" / "test.yml"
        backend = YAMLBackend()
        backend.save(path, {"key": "value"})
        assert path.exists()


class TestJSONBackend:
    def test_save_and_load(self):
        tmpdir = tempfile.mkdtemp()
        path = Path(tmpdir) / "test.json"
        backend = JSONBackend()
        data = {"groups": {"g1": {"id": "g1", "nodes": []}}}
        backend.save(path, data)
        assert path.exists()
        loaded = backend.load(path)
        assert loaded == data

    def test_load_missing_file(self):
        tmpdir = tempfile.mkdtemp()
        path = Path(tmpdir) / "missing.json"
        backend = JSONBackend()
        assert backend.load(path) == {}

    def test_pretty_print(self):
        tmpdir = tempfile.mkdtemp()
        path = Path(tmpdir) / "test.json"
        backend = JSONBackend()
        backend.save(path, {"a": 1})
        content = path.read_text()
        assert "\"a\": 1" in content


class TestLuckPermsStorage:
    def test_users_roundtrip(self):
        tmpdir = tempfile.mkdtemp()
        storage = LuckPermsStorage(tmpdir)
        users = {"u1": {"id": "u1", "nodes": []}}
        storage.save_users(users)
        loaded = storage.load_users()
        assert loaded == users

    def test_groups_roundtrip(self):
        tmpdir = tempfile.mkdtemp()
        storage = LuckPermsStorage(tmpdir)
        groups = {"admin": {"id": "admin", "nodes": []}}
        storage.save_groups(groups)
        loaded = storage.load_groups()
        assert loaded == groups

    def test_tracks_roundtrip(self):
        tmpdir = tempfile.mkdtemp()
        storage = LuckPermsStorage(tmpdir)
        tracks = {"staff": {"name": "staff", "groups": ["a", "b"]}}
        storage.save_tracks(tracks)
        loaded = storage.load_tracks()
        assert loaded == tracks

    def test_load_all(self):
        tmpdir = tempfile.mkdtemp()
        storage = LuckPermsStorage(tmpdir)
        storage.save_users({"u1": {"id": "u1"}})
        storage.save_groups({"g1": {"id": "g1"}})
        storage.save_tracks({"t1": {"name": "t1"}})
        users, groups, tracks = storage.load_all()
        assert users == {"u1": {"id": "u1"}}
        assert groups == {"g1": {"id": "g1"}}
        assert tracks == {"t1": {"name": "t1"}}

    def test_single_file_layout(self):
        """默认使用单文件布局，不再生成旧版三文件。"""
        tmpdir = tempfile.mkdtemp()
        storage = LuckPermsStorage(tmpdir)
        storage.save_all({}, {}, {})
        assert os.path.exists(os.path.join(tmpdir, "luckperms.yml"))
        assert not os.path.exists(os.path.join(tmpdir, "users.yml"))
        assert not os.path.exists(os.path.join(tmpdir, "groups.yml"))
        assert not os.path.exists(os.path.join(tmpdir, "tracks.yml"))

    def test_json_extension(self):
        tmpdir = tempfile.mkdtemp()
        storage = LuckPermsStorage(tmpdir, backend=JSONBackend())
        storage.save_users({})
        assert os.path.exists(os.path.join(tmpdir, "luckperms.json"))

    def test_legacy_layout_auto_migration(self):
        """旧版三文件布局应自动迁移到单文件，旧文件保留。"""
        tmpdir = tempfile.mkdtemp()
        backend = YAMLBackend()
        backend.save(Path(tmpdir) / "users.yml", {"users": {"u1": {"id": "u1"}}})
        backend.save(Path(tmpdir) / "groups.yml", {"groups": {"g1": {"id": "g1"}}})
        backend.save(Path(tmpdir) / "tracks.yml", {"tracks": {"t1": {"name": "t1"}}})

        storage = LuckPermsStorage(tmpdir)
        users, groups, tracks = storage.load_all()
        assert users == {"u1": {"id": "u1"}}
        assert groups == {"g1": {"id": "g1"}}
        assert tracks == {"t1": {"name": "t1"}}
        # 已生成单文件；旧文件保留不删
        assert os.path.exists(os.path.join(tmpdir, "luckperms.yml"))
        assert os.path.exists(os.path.join(tmpdir, "users.yml"))

    def test_save_leaves_no_tmp_files(self):
        """原子写不应留下临时文件。"""
        tmpdir = tempfile.mkdtemp()
        storage = LuckPermsStorage(tmpdir)
        storage.save_all({"u1": {"id": "u1"}}, {}, {})
        leftovers = [f for f in os.listdir(tmpdir) if f.endswith(".tmp")]
        assert leftovers == []

    def test_invalid_yaml_raises_value_error(self):
        tmpdir = tempfile.mkdtemp()
        path = Path(tmpdir) / "bad.yml"
        path.write_text("users: [unclosed", encoding="utf-8")
        with pytest.raises(ValueError, match="解析失败"):
            YAMLBackend().load(path)

    def test_non_dict_top_level_raises(self):
        tmpdir = tempfile.mkdtemp()
        path = Path(tmpdir) / "list.yml"
        path.write_text("- a\n- b\n", encoding="utf-8")
        with pytest.raises(ValueError, match="格式无效"):
            YAMLBackend().load(path)
