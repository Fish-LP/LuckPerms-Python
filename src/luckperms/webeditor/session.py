"""
LuckPerms Web Editor 会话管理器（官方协议兼容版）。

修复要点：
1. 先 create_channel -> 生成含 socket 的 payload -> bytebin upload
2. URL 格式: https://luckperms.net/editor/{code}
3. WebSocket 消息使用 msg+signature 外层帧
4. 支持 hello / change-request / ping 完整生命周期
5. change-request 自动回复 accepted -> 应用 -> applied + newSessionCode
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

from .bytebin import BytebinClient
from .websocket import BytesocksClient

log = logging.getLogger("luckperms.webeditor")

EDITOR_BASE_URL = "https://luckperms.net/editor"
DEFAULT_BYTESOCKS_URL = "https://usersockets.luckperms.net"


class WebEditorSession:
    """Web Editor 会话（官方协议兼容）。"""

    def __init__(
        self,
        get_payload: Callable[[], dict],
        apply_changes: Callable[[dict], None],
        bytebin_url: Optional[str] = None,
        bytesocks_url: Optional[str] = None,
    ):
        self.get_payload = get_payload
        self.apply_changes = apply_changes
        self.bytebin = (
            BytebinClient(bytebin_url) if bytebin_url else BytebinClient()
        )
        self.bytesocks_url = bytesocks_url
        self._socks: Optional[BytesocksClient] = None
        self._code: Optional[str] = None
        self._channel: Optional[str] = None
        self._closed = True

    async def open(self) -> str:
        """打开 Web Editor 会话，返回编辑器 URL。

        官方流程：
        1. 申请 bytesocks channel 并启动 WebSocket 监听
        2. 将 socket{channelId, publicKey} 注入 payload
        3. GZIP 压缩上传 bytebin 获取 code
        4. 返回 https://luckperms.net/editor/{code}
        """
        if self._socks is not None:
            await self.close()

        # 1. 先申请 bytesocks channel 并启动 WebSocket 监听
        self._socks = BytesocksClient(
            base_url=self.bytesocks_url or DEFAULT_BYTESOCKS_URL,
            on_hello=self._on_hello,
            on_connected=self._on_connected,
            on_change_request=self._on_change_request,
        )
        self._channel = await self._socks.create_channel()
        await self._socks.start()

        # 2. 生成 payload 并注入 socket 信息
        payload = self.get_payload()
        payload["socket"] = {
            "protocolVersion": 1,
            "channelId": self._channel,
            "publicKey": "",
        }

        # 3. 上传 bytebin
        self._code = await self.bytebin.upload(payload)

        self._closed = False
        url = f"{EDITOR_BASE_URL}/{self._code}"
        log.info("Web Editor 会话已开启: %s (channel=%s)", url, self._channel)
        return url

    async def close(self) -> None:
        """关闭会话并彻底清理资源。"""
        self._closed = True
        self._code = None
        self._channel = None
        if self._socks:
            await self._socks.stop()
            self._socks = None
        log.info("Web Editor 会话已关闭")

    async def apply_edits(self, code: str) -> None:
        """手动应用 edits（兼容 /lp applyedits <code>）。"""
        log.info("正在下载并应用 edits: %s", code)
        payload = await self.bytebin.download(code)
        self.apply_changes(payload)
        log.info("Edits 已应用")

    # ------------------------------------------------------------------
    # WebSocket 回调
    # ------------------------------------------------------------------
    async def _on_hello(self, nonce: str) -> None:
        log.debug("Web Editor 握手: nonce=%s", nonce)

    async def _on_connected(self) -> None:
        log.info("Web Editor 前端已连接")

    async def _on_change_request(self, code: str) -> None:
        """处理编辑器保存请求（change-request）。"""
        if self._closed or self._socks is None:
            return
        log.info("收到 change-request: code=%s", code)

        try:
            # 1. 发送 accepted
            await self._socks.send_change_response("accepted")

            # 2. 下载并应用变更
            await self.apply_edits(code)

            # 3. 生成跟进会话（重新上传当前数据 + 相同 channel）
            new_payload = self.get_payload()
            new_payload["socket"] = {
                "protocolVersion": 1,
                "channelId": self._channel,
                "publicKey": "",
            }
            new_code = await self.bytebin.upload(new_payload)

            # 4. 发送 applied + newSessionCode
            await self._socks.send_change_response("applied", new_code)
            self._code = new_code
            log.info("已推送新 session code: %s", new_code)
        except Exception:
            log.exception("处理 change-request 失败")

    @property
    def is_active(self) -> bool:
        return not self._closed and self._socks is not None and self._socks.is_active