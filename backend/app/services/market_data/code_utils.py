"""证券代码归一化与市场判定。

统一把用户输入的代码转成 `(market, digits)`，并生成带市场前缀的代码，
避免把裸代码交给服务端（服务端无前缀时按 sh→sz→bj 探测，
会把 `000001` 解析成上证指数而非平安银行）。
"""
import re
from typing import Tuple

from .base import InvalidSecurityCodeError

# 市场代码 -> 中文名（保持原有 StockService 返回契约）
MARKET_CN = {"sh": "上海", "sz": "深圳", "bj": "北京"}

# 可选市场前缀 + 6 位数字（大小写不敏感）
_CODE_PATTERN = re.compile(r"^(SH|SZ|BJ)?(\d{6})$", re.IGNORECASE)


def _infer_market(digits: str) -> str:
    """根据 6 位代码首位推导市场。

    规则（与迁移前「6 开头为沪、其余为深」等价并补全北交所）：
    - `92` 开头 -> bj（北交所新代码段，需先于单字符 `9` 判断）
    - `6` / `9` -> sh（沪主板/科创板、沪 B 股）
    - `0` / `2` / `3` -> sz（深主板、深 B 股、创业板）
    - `4` / `8` -> bj（新三板/北交所）
    - 其它 -> sz（兜底，与旧实现一致）
    """
    if digits.startswith("92"):
        return "bj"
    head = digits[0]
    if head in ("6", "9"):
        return "sh"
    if head in ("0", "2", "3"):
        return "sz"
    if head in ("4", "8"):
        return "bj"
    return "sz"


def split_code(raw: str) -> Tuple[str, str]:
    """拆分证券代码为 `(market, digits)`。

    Args:
        raw: `600000`、`sh600000`、`SH600000`、` bj830799 ` 等形式

    Returns:
        (小写市场码, 6 位数字)

    Raises:
        InvalidSecurityCodeError: 格式非法
    """
    if not isinstance(raw, str) or not raw.strip():
        raise InvalidSecurityCodeError(f"证券代码格式非法: {raw!r}")

    normalized = raw.strip().upper()
    matched = _CODE_PATTERN.match(normalized)
    if not matched:
        raise InvalidSecurityCodeError(f"证券代码格式非法: {raw!r}")

    prefix, digits = matched.group(1), matched.group(2)
    if prefix:
        return prefix.lower(), digits
    return _infer_market(digits), digits


def to_market_code(raw: str) -> str:
    """生成带市场前缀的代码，如 `sh600000`。"""
    market, digits = split_code(raw)
    return f"{market}{digits}"


def market_to_cn(market: str) -> str:
    """市场码转中文名；未知市场返回空串。"""
    if not market:
        return ""
    return MARKET_CN.get(str(market).strip().lower(), "")
