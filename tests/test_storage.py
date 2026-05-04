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

    def test_file_names(self):
        tmpdir = tempfile.mkdtemp()
        storage = LuckPermsStorage(tmpdir)
        storage.save_all({}, {}, {})
        assert os.path.exists(os.path.join(tmpdir, "users.yml"))
        assert os.path.exists(os.path.join(tmpdir, "groups.yml"))
        assert os.path.exists(os.path.join(tmpdir, "tracks.yml"))

    def test_json_extension(self):
        tmpdir = tempfile.mkdtemp()
        storage = LuckPermsStorage(tmpdir, backend=JSONBackend())
        storage.save_users({})
        assert os.path.exists(os.path.join(tmpdir, "users.json"))
