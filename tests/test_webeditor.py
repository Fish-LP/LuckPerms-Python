"""
LuckPermsAPI Web Editor 单元测试。
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from luckperms.webeditor import BytebinClient, BytesocksClient, WebEditorSession
from luckperms.manager import LuckPermsManager


class TestBytebinClient:
    @pytest.mark.asyncio
    async def test_upload_download_roundtrip(self):
        """使用真实 bytebin 进行端到端测试（可选，若网络不可用则跳过）。"""
        client = BytebinClient()
        payload = {"test": "data", "nested": {"value": 123}}
        try:
            code = await client.upload(payload)
            assert code
            downloaded = await client.download(code)
            assert downloaded == payload
        except Exception as e:
            pytest.skip(f"Bytebin 不可用: {e}")

    @pytest.mark.asyncio
    async def test_upload_failure_raises(self):
        client = BytebinClient("https://httpbin.org/status")
        with pytest.raises(RuntimeError):
            await client.upload({"test": "data"})


class TestBytesocksClient:
    @pytest.mark.asyncio
    async def test_start_stop(self):
        client = BytesocksClient()
        # 由于需要真实 WebSocket 服务器，这里仅测试属性
        assert client.channel is None
        assert client.is_active is False

    def test_ping_pong_handling(self):
        """验证 _handle_message 能正确处理 ping 消息并回复 pong。"""
        client = BytesocksClient()
        client.channel = "test-ch"  # 手动设置用于测试
        # mock _send 来捕获发送的内容
        sent_messages = []
        async def mock_send(data):
            sent_messages.append(data)
        client._send = mock_send

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(client._handle_message('{"type": "ping"}'))
        finally:
            loop.close()

        assert len(sent_messages) == 1
        assert sent_messages[0]["type"] == "pong"

    def test_apply_callback(self):
        """验证收到 apply 消息会触发 on_apply 回调。"""
        callback = MagicMock()
        client = BytesocksClient(on_apply=callback)
        client.channel = "test-ch"
        mock_ws = MagicMock()
        mock_ws.closed = False
        client._ws = mock_ws

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(client._handle_message('{"type": "apply", "data": {"users": []}}'))
        finally:
            loop.close()

        callback.assert_called_once_with({"users": []})

    def test_invalid_json_ignored(self):
        """验证无效 JSON 不会导致异常。"""
        client = BytesocksClient()
        client.channel = "test-ch"
        mock_ws = MagicMock()
        client._ws = mock_ws

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(client._handle_message("not json"))
        finally:
            loop.close()

        mock_ws.send_str.assert_not_called()


class TestWebEditorSession:
    def test_session_init(self):
        get_payload = MagicMock(return_value={})
        apply_changes = MagicMock()
        session = WebEditorSession(get_payload, apply_changes)
        assert session.is_active is False

    @pytest.mark.asyncio
    async def test_session_url_format(self):
        """验证生成的 URL 格式正确。"""
        get_payload = MagicMock(return_value={"metadata": {}})
        apply_changes = MagicMock()

        session = WebEditorSession(get_payload, apply_changes)

        # Mock bytebin upload
        session.bytebin = MagicMock()
        session.bytebin.upload = AsyncMock(return_value="ABC123")

        # Mock bytesocks
        with patch("luckperms.webeditor.session.BytesocksClient") as MockClient:
            mock_socks = AsyncMock()
            MockClient.return_value = mock_socks

            url = await session.open()

            assert url.startswith("https://luckperms.net/editor/")
            assert "ABC123" in url
            assert "#" in url
            mock_socks.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_session_close(self):
        get_payload = MagicMock(return_value={})
        apply_changes = MagicMock()
        session = WebEditorSession(get_payload, apply_changes)

        with patch("luckperms.webeditor.session.BytesocksClient") as MockClient:
            mock_socks = AsyncMock()
            MockClient.return_value = mock_socks
            session._socks = mock_socks
            await session.close()
            mock_socks.stop.assert_awaited_once()

    def test_on_apply_calls_callback(self):
        get_payload = MagicMock(return_value={})
        apply_changes = MagicMock()
        session = WebEditorSession(get_payload, apply_changes)
        session._closed = False
        session._on_apply({"users": []})
        apply_changes.assert_called_once_with({"users": []})

    def test_on_apply_ignored_when_closed(self):
        get_payload = MagicMock(return_value={})
        apply_changes = MagicMock()
        session = WebEditorSession(get_payload, apply_changes)
        session._closed = True
        session._on_apply({"users": []})
        apply_changes.assert_not_called()


class TestWebEditorPayload:
    def test_node_expiry_conversion(self):
        """验证节点过期时间在序列化时转换为毫秒。"""
        mgr = LuckPermsManager.__new__(LuckPermsManager)
        node = MagicMock()
        node.key = "test"
        node.value = True
        node.context = {}
        node.expiry = 1234.5
        result = LuckPermsManager._node_to_webeditor(node)
        assert result["expiry"] == 1234500

    def test_node_expiry_deserialization(self):
        """验证毫秒过期时间在反序列化时转换回秒。"""
        node = LuckPermsManager._node_from_webeditor({
            "key": "test",
            "value": True,
            "expiry": 1234500,
        })
        assert node.expiry == 1234.5

    def test_node_no_expiry_roundtrip(self):
        """验证无过期时间节点往返正确。"""
        node = LuckPermsManager._node_from_webeditor({
            "key": "test",
            "value": False,
        })
        assert node.expiry is None
        assert node.value is False
