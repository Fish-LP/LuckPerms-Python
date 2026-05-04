"""
LuckPerms Bytesocks WebSocket 客户端。

实现与官方 bytesocks 协议的完整通信：
1. 先通过 HTTP GET /create 向服务端申请 channel key
2. 用返回的 key 建立 WebSocket 连接
3. 监听编辑器发来的变更请求（apply）
4. 推送数据更新

参考 https://github.com/lucko/bytesocks
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable, Optional

import aiohttp

log = logging.getLogger("luckperms.webeditor")

DEFAULT_BYTESOCKS_URL = "https://usersockets.luckperms.net"


class BytesocksClient:
    """Bytesocks WebSocket 客户端。

    负责与 LuckPerms Web Editor 的实时通信通道。

    Args:
        base_url: Bytesocks HTTP / WebSocket 基础 URL。
        on_apply: 收到变更时的回调函数。
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BYTESOCKS_URL,
        on_apply: Optional[Callable[[dict], None]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.on_apply = on_apply
        self.channel: Optional[str] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def create_channel(self) -> str:
        """向 bytesocks 服务端申请创建 channel，返回 key。

        Raises:
            RuntimeError: 创建失败。
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.base_url}/create",
                headers={"User-Agent": "LuckPermsAPI/1.0.0"},
                allow_redirects=False,
            ) as resp:
                if resp.status not in (200, 201, 302, 307, 308):
                    text = await resp.text()
                    raise RuntimeError(
                        f"Bytesocks 创建 channel 失败: HTTP {resp.status} - {text}"
                    )

                # 优先从 Location header 提取
                key: str | None = None
                location = resp.headers.get("Location")
                if location:
                    key = location.rstrip("/").split("/")[-1]

                if not key:
                    try:
                        result = await resp.json()
                        key = result.get("key")
                    except Exception:
                        pass

                if not key:
                    raise RuntimeError(
                        f"Bytesocks 返回无效响应: {await resp.text()}"
                    )

                self.channel = key
                log.info("Bytesocks channel 已创建: %s", key)
                return key

    async def start(self) -> None:
        """启动 WebSocket 连接（须先调用 create_channel）。"""
        if self._running:
            return
        if not self.channel:
            raise RuntimeError("须先调用 create_channel() 获取 channel key")
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """停止 WebSocket 连接。"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._ws:
            await self._ws.close()
            self._ws = None
        if self._session:
            await self._session.close()
            self._session = None

    async def _run(self) -> None:
        url = f"{self.base_url}/{self.channel}"
        self._session = aiohttp.ClientSession()

        try:
            async with self._session.ws_connect(url) as ws:
                self._ws = ws
                log.info("Bytesocks 已连接: %s", url)

                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await self._handle_message(msg.data)
                    elif msg.type in (
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        break
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("Bytesocks 连接异常: %s", e)
        finally:
            self._running = False
            log.info("Bytesocks 已断开")

    async def _handle_message(self, data: str) -> None:
        try:
            msg = json.loads(data)
        except json.JSONDecodeError:
            log.warning("收到无效 JSON: %s", data[:200])
            return

        msg_type = msg.get("type", "").lower()
        if msg_type == "ping":
            await self._send({"type": "pong"})
        elif msg_type == "apply":
            log.info("收到 Web Editor 变更请求")
            if self.on_apply:
                asyncio.get_running_loop().call_soon(
                    self.on_apply, msg.get("data", {})
                )
        elif msg_type == "putcode":
            log.debug("编辑器确认 code: %s", msg.get("code"))
        else:
            log.debug("收到未知消息类型: %s", msg_type)

    async def _send(self, data: dict) -> None:
        if self._ws and not self._ws.closed:
            await self._ws.send_str(json.dumps(data))

    async def send_code(self, code: str) -> None:
        """向编辑器发送 bytebin code。

        Args:
            code: bytebin 上传码。
        """
        await self._send({"type": "putcode", "code": code})

    async def send_ping(self) -> None:
        """发送心跳。"""
        await self._send({"type": "ping"})

    @property
    def is_active(self) -> bool:
        return self._running and self._ws is not None and not self._ws.closed