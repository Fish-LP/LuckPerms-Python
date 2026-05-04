"""
LuckPerms Bytebin API 客户端。

用于上传/下载 Web Editor 的 GZIP 压缩 JSON 数据。
参考：https://github.com/lucko/bytebin
"""
from __future__ import annotations

import gzip
import json
import logging
from typing import Any, Dict

import aiohttp

log = logging.getLogger("luckperms.webeditor")

DEFAULT_BYTEBIN_URL = "https://bytebin.lucko.me"


class BytebinClient:
    """Bytebin 客户端。

    上传数据到 bytebin 获取 code，或根据 code 下载数据。

    Args:
        base_url: Bytebin 端点 URL。
    """

    def __init__(self, base_url: str = DEFAULT_BYTEBIN_URL):
        self.base_url = base_url.rstrip("/")

    async def upload(self, payload: dict[str, Any]) -> str:
        """上传数据到 bytebin，返回 code。

        Args:
            payload: 要上传的 JSON 数据。

        Return:
            bytebin 返回的 code。

        Raises:
            RuntimeError: 上传失败时。
        """
        json_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        compressed = gzip.compress(json_bytes)

        headers = {
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/post",
                data=compressed,
                headers=headers,
            ) as resp:
                if resp.status not in (200, 201):
                    text = await resp.text()
                    raise RuntimeError(
                        f"Bytebin 上传失败: HTTP {resp.status} - {text}"
                    )
                result = await resp.json()
                code = result.get("code") or result.get("id")
                if not code:
                    raise RuntimeError(f"Bytebin 返回无效响应: {result}")
                log.info("Bytebin 上传成功, code=%s", code)
                return code

    async def download(self, code: str) -> dict[str, Any]:
        """根据 code 从 bytebin 下载数据。

        Args:
            code: bytebin code。

        Return:
            解压后的 JSON 数据。

        Raises:
            RuntimeError: 下载失败时。
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.base_url}/{code}",
                headers={"Accept-Encoding": "gzip"},
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(
                        f"Bytebin 下载失败: HTTP {resp.status} - {text}"
                    )
                raw = await resp.read()
                try:
                    decompressed = gzip.decompress(raw)
                except Exception:
                    decompressed = raw
                return json.loads(decompressed.decode("utf-8"))
