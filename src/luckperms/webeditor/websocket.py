"""
LuckPerms Bytesocks WebSocket 客户端（官方协议兼容版）。

修复要点：
1. create_channel 严格检查 HTTP 201
2. 所有消息使用 {"msg": "...", "signature": "..."} 外层帧
3. 支持 hello / connected / change-request / ping 消息类型
4. 自动回复 hello-reply（state=trusted）和 pong
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
    """Bytesocks WebSocket 客户端（官方协议兼容）。"""

    def __init__(
        self,
        base_url: str = DEFAULT_BYTESOCKS_URL,
        on_hello: Optional[Callable[[str], None]] = None,
        on_connected: Optional[Callable[[], None]] = None,
        on_change_request: Optional[Callable[[str], None]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.on_hello = on_hello
        self.on_connected = on_connected
        self.on_change_request = on_change_request
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
                headers={"User-Agent": "LuckPerms/5.4.0"},
                allow_redirects=False,
            ) as resp:
                # FIX: 官方严格返回 201
                if resp.status != 201:
                    text = await resp.text()
                    raise RuntimeError(
                        f"Bytesocks 创建 channel 失败: HTTP {resp.status} - {text}"
                    )

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
                    raise RuntimeError(f"Bytesocks 返回无效响应: {await resp.text()}")

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
        """WebSocket 主循环。"""
        # FIX: 根据 http/https 推导 ws/wss
        if self.base_url.startswith("https://"):
            ws_url = "wss://" + self.base_url[8:]
        elif self.base_url.startswith("http://"):
            ws_url = "ws://" + self.base_url[7:]
        else:
            ws_url = self.base_url

        url = f"{ws_url}/{self.channel}"
        self._session = aiohttp.ClientSession()

        try:
            async with self._session.ws_connect(url) as ws:
                self._ws = ws
                log.info("Bytesocks 已连接: %s", url)

                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await self._handle_message(msg.data)
                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("Bytesocks 连接异常: %s", e)
        finally:
            self._running = False
            log.info("Bytesocks 已断开")

    async def _handle_message(self, data: str) -> None:
        """解析外层帧 msg + signature，分发消息类型。"""
        try:
            frame = json.loads(data)
        except json.JSONDecodeError:
            log.warning("收到无效 JSON: %s", data[:200])
            return

        inner_msg = frame.get("msg", "")
        # signature = frame.get("signature", "")  # 简化版暂不验签
        if not inner_msg:
            log.warning("收到空消息帧")
            return

        try:
            msg = json.loads(inner_msg)
        except json.JSONDecodeError:
            log.warning("收到无效内层消息: %s", inner_msg[:200])
            return

        msg_type = msg.get("type", "").lower()
        log.debug("收到消息: type=%s", msg_type)

        if msg_type == "hello":
            nonce = msg.get("nonce", "")
            # FIX: 自动回复 hello-reply 建立信任（简化版）
            await self._send({"type": "hello-reply", "nonce": nonce, "state": "trusted"})
            if self.on_hello:
                try:
                    await self.on_hello(nonce)
                except Exception:
                    log.exception("on_hello 回调异常")

        elif msg_type == "connected":
            if self.on_connected:
                try:
                    await self.on_connected()
                except Exception:
                    log.exception("on_connected 回调异常")

        elif msg_type == "change-request":
            code = msg.get("code", "")
            if self.on_change_request:
                try:
                    await self.on_change_request(code)
                except Exception:
                    log.exception("on_change_request 回调异常")

        elif msg_type == "ping":
            await self._send({"type": "pong"})

        else:
            log.debug("收到未知消息类型: %s", msg_type)

    async def _send(self, data: dict) -> None:
        """发送外层帧消息。"""
        if self._ws is None or self._ws.closed:
            return
        inner = json.dumps(data)
        frame = {"msg": inner, "signature": ""}  # 简化：空签名
        await self._ws.send_str(json.dumps(frame))

    async def send_change_response(self, state: str, new_session_code: Optional[str] = None) -> None:
        """发送 change-response（change-request 的回执）。"""
        payload: dict = {"type": "change-response", "state": state}
        if new_session_code:
            payload["newSessionCode"] = new_session_code
        await self._send(payload)

    @property
    def is_active(self) -> bool:
        return self._running and self._ws is not None and not self._ws.closed