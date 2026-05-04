"""
LuckPerms Bytebin API 客户端。

用于上传/下载 Web Editor 的 GZIP 压缩 JSON 数据。
默认后端已迁移至官方 LuckPerms 托管节点。
参考：https://github.com/lucko/bytebin
"""
from __future__ import annotations

import gzip
import json
import logging
from typing import Any, Dict

import aiohttp

log = logging.getLogger("luckperms.webeditor")

DEFAULT_BYTEBIN_URL = "https://usercontent.luckperms.net"


class BytebinClient:
    """Bytebin 客户端。

    上传数据到 bytebin 获取 key，或根据 key 下载数据。

    Args:
        base_url: Bytebin 端点 URL。
    """

    def __init__(self, base_url: str = DEFAULT_BYTEBIN_URL):
        self.base_url = base_url.rstrip("/")

    async def upload(self, payload: dict[str, Any]) -> str:
        """上传数据到 bytebin，返回 key。

        Args:
            payload: 要上传的 JSON 数据。

        Return:
            bytebin 返回的 key。

        Raises:
            RuntimeError: 上传失败时。
        """
        json_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        compressed = gzip.compress(json_bytes)

        headers = {
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
            "User-Agent": "5.4.0",
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

                # 优先从 Location Header 提取 key，兼容 JSON 返回
                key: str | None = None
                location = resp.headers.get("Location")
                if location:
                    key = location.rstrip("/").split("/")[-1]

                if not key:
                    result = await resp.json()
                    key = (
                        result.get("key")
                        or result.get("code")
                        or result.get("id")
                    )

                if not key:
                    raise RuntimeError(
                        f"Bytebin 返回无效响应: {await resp.text()}"
                    )
                log.info("Bytebin 上传成功, key=%s", key)
                return key

    async def download(self, code: str) -> dict[str, Any]:
        """根据 key 从 bytebin 下载数据。

        Args:
            code: bytebin key。

        Return:
            解压后的 JSON 数据。

        Raises:
            RuntimeError: 下载失败时。
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.base_url}/{code}",
                headers={"User-Agent": "5.4.0"},
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