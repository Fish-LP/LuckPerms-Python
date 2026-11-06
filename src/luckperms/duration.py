"""
时长（有效期）解析与格式化。

支持 LuckPerms 风格写法：

- 时间周期：``30m``、``12h``、``7d``、``1mo3d13h45m``
- 相对秒数：``3600``（不足 10 位的纯数字）
- unix 时间戳：``1482694200``（10 位及以上纯数字，按绝对时间处理）
- 永久：``permanent`` / ``forever`` / ``never``
"""

from __future__ import annotations

import re
import time
from typing import Optional

# 单位 → 秒数（"mo" 必须排在 "m" 之前参与匹配）
DURATION_UNITS: dict[str, int] = {
    "s": 1,
    "m": 60,
    "h": 3_600,
    "d": 86_400,
    "w": 604_800,
    "mo": 2_592_000,  # 30 天
    "y": 31_536_000,  # 365 天
}

PERMANENT_KEYWORDS = frozenset({"permanent", "forever", "never"})

# 10 位及以上纯数字视为绝对 unix 时间戳
_TIMESTAMP_THRESHOLD = 10**9

_TOKEN_RE = re.compile(r"(\d+)\s*(mo|s|m|h|d|w|y)")
_PERIOD_RE = re.compile(r"^(?:\d+\s*(?:mo|s|m|h|d|w|y)\s*)+$")


class DurationParseError(ValueError):
    """时长表达式解析失败。"""


def parse_duration(text: str, now: Optional[float] = None) -> Optional[int]:
    """将时长表达式解析为**相对秒数**。

    Args:
        text: 时长表达式，如 ``1d2h``、``3600``、``permanent``。
        now: 当前时间戳（便于测试注入）。

    Return:
        相对秒数；``None`` 表示永久。

    Raises:
        DurationParseError: 表达式非法或时长不为正。
    """
    if text is None:
        raise DurationParseError("时长不能为空")
    raw = str(text).strip().lower()
    if not raw:
        raise DurationParseError("时长不能为空")
    if raw in PERMANENT_KEYWORDS:
        return None

    if raw.isdigit():
        value = int(raw)
        if value >= _TIMESTAMP_THRESHOLD:
            current = now if now is not None else time.time()
            remaining = int(value - current)
            if remaining <= 0:
                raise DurationParseError(f"时间戳已过期: {text!r}")
            return remaining
        if value <= 0:
            raise DurationParseError("时长必须大于 0")
        return value

    if not _PERIOD_RE.match(raw):
        raise DurationParseError(f"无法解析时长: {text!r}")

    seconds = sum(
        int(amount) * DURATION_UNITS[unit] for amount, unit in _TOKEN_RE.findall(raw)
    )
    if seconds <= 0:
        raise DurationParseError("时长必须大于 0")
    return seconds


def format_duration(seconds: Optional[float]) -> str:
    """将剩余秒数格式化为可读文本（如 ``1d 2h 3m``）。"""
    if seconds is None:
        return "Never"
    total = int(seconds)
    if total <= 0:
        return "expired"
    parts: list[str] = []
    for unit, size in (("d", 86_400), ("h", 3_600), ("m", 60), ("s", 1)):
        if total >= size:
            amount, total = divmod(total, size)
            parts.append(f"{amount}{unit}")
    return " ".join(parts)
