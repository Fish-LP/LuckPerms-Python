"""
LuckPerms Web Editor 会话管理器。

整合 Bytebin + Bytesocks，提供一键打开编辑器的完整流程：
1. 将当前权限数据上传到 bytebin
2. 向 bytesocks 申请 channel
3. 生成编辑器 URL（https://luckperms.net/editor/）
4. 通过 bytesocks 监听实时变更
5. 应用编辑器返回的变更
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
    """Web Editor 会话。

    典型使用流程::

        session = WebEditorSession(manager)
        url = await session.open()
        print(f"请在浏览器打开: {url}")
        # 用户编辑并保存后，session 自动调用 on_apply

    Args:
        get_payload: 获取当前权限数据的回调函数，返回 dict。
        apply_changes: 应用编辑器变更的回调函数，接收 dict。
        bytebin_url: 自定义 bytebin 端点。
        bytesocks_url: 自定义 bytesocks 端点。
    """

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
        self._closed = False

    async def open(self) -> str:
        """打开 Web Editor 会话，返回编辑器 URL。

        Return:
            完整的 Web Editor URL，可直接在浏览器中打开。
        """
        payload = self.get_payload()
        self._code = await self.bytebin.upload(payload)

        # 向 bytesocks 申请 channel（而非自己生成）
        self._socks = BytesocksClient(
            base_url=self.bytesocks_url or DEFAULT_BYTESOCKS_URL,
            on_apply=self._on_apply,
        )
        self._channel = await self._socks.create_channel()
        await self._socks.start()

        # 等待 WebSocket 握手完成，再发送 code
        await asyncio.sleep(1.0)
        await self._socks.send_code(self._code)

        url = f"{EDITOR_BASE_URL}/{self._code}#{self._channel}"
        log.info("Web Editor 会话已开启: %s", url)
        return url

    async def close(self) -> None:
        """关闭会话。"""
        self._closed = True
        if self._socks:
            await self._socks.stop()
            self._socks = None

    def _on_apply(self, data: dict) -> None:
        if self._closed:
            return
        log.info("正在应用 Web Editor 变更 ...")
        try:
            self.apply_changes(data)
            log.info("Web Editor 变更已应用")
        except Exception:
            log.exception("应用 Web Editor 变更失败")

    @property
    def is_active(self) -> bool:
        return self._socks is not None and self._socks.is_active