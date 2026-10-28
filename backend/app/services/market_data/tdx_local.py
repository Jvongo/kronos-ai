"""TDX 本地行情服务适配器。

对接 TDX 本地行情服务（v1.0.0，`/api/v1`），负责：
- HTTP 调用、统一信封解析、超时/5xx 重试
- 业务码到异常体系的映射（40001/40401/40402/50001/50301）
- 字段映射与类型转换、脏数据逐行丢弃
- 分页拉取与「最近 N 根」策略（日期区间优先，offset 尾部兜底）

设计说明：本类方法均为同步实现（纯 IO + 纯映射），
由上层 StockService 通过 `asyncio.to_thread` 调用，避免阻塞事件循环。
"""
import logging
import math
import time
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional

import requests

from .base import (
    InvalidSecurityCodeError,
    MarketDataSource,
    MarketDataSourceError,
    MarketDataSourceUnavailable,
    NoDataInRangeError,
    SecurityNotFoundError,
)
from .code_utils import split_code
from .settings import load_settings

logger = logging.getLogger(__name__)

# 业务码 -> 异常类型
_CODE_TO_ERROR = {
    40001: InvalidSecurityCodeError,
    40401: SecurityNotFoundError,
    40402: NoDataInRangeError,
}
# 需要重试的业务码（服务端内部/数据目录问题）
_RETRYABLE_CODES = (50001, 50301)
# 单只证券最多翻页的条数上限，防御性保护
_MAX_TOTAL_BARS = 200_000
# 内部哨兵：表示该次请求可重试
_TRANSIENT = object()


def _to_float(value: Any, field_name: str) -> float:
    """转 float，拒绝 None/空串/NaN/非数值。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{field_name} 缺失")
    result = float(value)
    if math.isnan(result) or math.isinf(result):
        raise ValueError(f"{field_name} 非法: {value!r}")
    return result


def _to_volume(value: Any) -> int:
    """转成交量为整数股，缺失/非法按 0 处理（不因此丢整行）。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return 0
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0
    if math.isnan(result) or math.isinf(result):
        return 0
    return int(result)


def map_bar(raw: Dict[str, Any]) -> Dict[str, Any]:
    """把服务端日线对象映射为上层标准结构。

    Args:
        raw: `{"date","open","high","low","close","amount","volume"}`

    Returns:
        `{"date": str, "open": float, "high": float, "low": float,
          "close": float, "volume": int}`（不透传 amount，见设计文档 §4.1）

    Raises:
        ValueError: 日期缺失或任一价格非法（调用方应丢弃该行）
    """
    if not isinstance(raw, dict):
        raise ValueError(f"日线记录类型非法: {type(raw).__name__}")

    date_value = raw.get("date")
    if hasattr(date_value, "strftime"):
        date_str = date_value.strftime("%Y-%m-%d")
    else:
        date_str = str(date_value or "").strip().split("T")[0].split(" ")[0]
        if not date_str:
            raise ValueError("日线记录缺少 date")

    prices = {key: _to_float(raw.get(key), key) for key in ("open", "high", "low", "close")}

    return {
        "date": date_str,
        "open": prices["open"],
        "high": prices["high"],
        "low": prices["low"],
        "close": prices["close"],
        "volume": _to_volume(raw.get("volume")),
    }


class TdxLocalDataSource(MarketDataSource):
    """TDX 本地行情服务数据源。"""

    name = "tdx_local"

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_prefix: Optional[str] = None,
        timeout: Optional[float] = None,
        connect_timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        page_limit: int = 5000,
        http: Any = None,
        today_provider: Optional[Callable[[], date]] = None,
        sleep: Optional[Callable[[float], None]] = None,
    ):
        """初始化适配器。

        Args:
            base_url: 服务地址，缺省读环境变量 `KRONOS_TDX_BASE_URL`
            api_prefix: 路由前缀，缺省 `/api/v1`
            timeout: 读超时秒数
            connect_timeout: 连接超时秒数
            max_retries: 失败重试次数（仅对网络/5xx 生效）
            page_limit: 单页条数（1~5000）
            http: 注入的 HTTP 客户端（默认 requests，测试可替换）
            today_provider: 注入的"今天"函数（便于测试固定日期）
            sleep: 注入的 sleep 函数（测试可消除重试等待）
        """
        settings = load_settings()
        self.base_url = (base_url or settings.tdx_base_url).rstrip("/")
        self.api_prefix = (api_prefix or settings.tdx_api_prefix).rstrip("/")
        self.timeout = settings.timeout if timeout is None else float(timeout)
        self.connect_timeout = (
            settings.connect_timeout if connect_timeout is None else float(connect_timeout)
        )
        self.max_retries = max(0, settings.max_retries if max_retries is None else int(max_retries))
        self.page_limit = max(1, min(int(page_limit), 5000))
        self.http = http or requests
        self._today = today_provider or date.today
        self._sleep = sleep or time.sleep

    # ------------------------------------------------------------------ #
    # 底层 HTTP
    # ------------------------------------------------------------------ #
    def _request(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """带重试与信封解析的 GET 请求。

        Args:
            path: 相对路由，如 `/kline/daily`
            params: 查询参数

        Returns:
            信封中的 `data` 字段

        Raises:
            InvalidSecurityCodeError / SecurityNotFoundError / NoDataInRangeError:
                服务端返回对应业务码（不重试）
            MarketDataSourceUnavailable: 网络异常、5xx 或重试耗尽
            MarketDataSourceError: 响应格式非法
        """
        url = f"{self.base_url}{self.api_prefix}{path}"
        attempts = self.max_retries + 1
        last_error = ""

        for attempt in range(attempts):
            try:
                response = self.http.get(
                    url, params=params or {}, timeout=(self.connect_timeout, self.timeout)
                )
            except requests.exceptions.Timeout as exc:
                last_error = f"请求超时: {exc}"
            except requests.exceptions.ConnectionError as exc:
                last_error = f"连接失败: {exc}"
            except requests.exceptions.RequestException as exc:
                last_error = f"请求异常: {exc}"
            else:
                payload = self._parse_envelope(response, url)
                if payload is not _TRANSIENT:
                    return payload
                last_error = f"服务端错误: HTTP {response.status_code}"

            if attempt < attempts - 1:
                logger.warning("行情服务调用失败，第 %s 次重试: %s | %s",
                               attempt + 1, url, last_error)
                self._sleep(0.2 * (attempt + 1))

        raise MarketDataSourceUnavailable(f"{last_error}（{url}）")

    def _parse_envelope(self, response: Any, url: str) -> Any:
        """解析统一信封，返回 data 或抛出对应异常。"""
        try:
            payload = response.json()
        except ValueError as exc:
            raise MarketDataSourceError(f"响应不是合法 JSON: {exc}（{url}）") from exc

        if not isinstance(payload, dict) or "code" not in payload:
            raise MarketDataSourceError(f"响应信封格式非法: {payload!r}（{url}）")

        code = payload.get("code")
        message = payload.get("message", "")

        if code == 0:
            return payload.get("data")

        error_cls = _CODE_TO_ERROR.get(code)
        if error_cls is not None:
            raise error_cls(f"{message or '请求失败'}(code={code})", code=code)

        if code in _RETRYABLE_CODES or int(response.status_code or 0) >= 500:
            return _TRANSIENT

        raise MarketDataSourceError(f"未识别的业务码 {code}: {message}（{url}）")

    # ------------------------------------------------------------------ #
    # 接口实现
    # ------------------------------------------------------------------ #
    def get_security(self, code: str) -> Dict[str, Any]:
        """获取证券元信息。"""
        market, digits = split_code(code)
        data = self._request(f"/securities/{market}{digits}")
        if not isinstance(data, dict):
            raise MarketDataSourceError(f"证券元信息格式非法: {data!r}")
        return data

    def get_bars_range(self, code: str, start_date: Optional[str] = None,
                       end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """按闭区间分页拉取日线；区间无数据返回空列表。"""
        market, digits = split_code(code)
        full_code = f"{market}{digits}"

        bars: List[Dict[str, Any]] = []
        offset = 0
        skipped = 0

        while offset <= _MAX_TOTAL_BARS:
            params: Dict[str, Any] = {
                "code": full_code,
                "limit": self.page_limit,
                "offset": offset,
            }
            if start_date:
                params["start_date"] = start_date
            if end_date:
                params["end_date"] = end_date

            try:
                data = self._request("/kline/daily", params)
            except NoDataInRangeError:
                # 区间无数据或 offset 越界：视为正常结束
                break

            page = (data or {}).get("items") or []
            for raw in page:
                try:
                    bars.append(map_bar(raw))
                except (ValueError, TypeError) as exc:
                    skipped += 1
                    logger.warning("跳过无效日线记录 %s[%s]: %s", full_code, offset, exc)

            if len(page) < self.page_limit:
                break
            offset += self.page_limit

        if skipped:
            logger.warning("%s 本次拉取共丢弃 %s 条脏数据", full_code, skipped)
        return bars

    def get_recent_bars(self, code: str, days: int) -> List[Dict[str, Any]]:
        """获取最近 N 个交易日的日线。

        策略：先按日期区间（含缓冲）查询；若不足 N 根（数据陈旧/区间无数据），
        改用 `offset = bars - N` 从尾部精确取，确保"最近 N 根"而非"最近 N 天"。
        """
        days = max(1, int(days))
        market, digits = split_code(code)
        full_code = f"{market}{digits}"

        today = self._today()
        start = today - timedelta(days=max(days * 2 + 10, 30))

        bars = self.get_bars_range(code, start.isoformat(), today.isoformat())
        if len(bars) >= days:
            return bars[-days:]

        # 兜底：按总条数从尾部精确取
        try:
            meta = self.get_security(code)
        except MarketDataSourceError as exc:
            logger.info("%s 元信息获取失败，跳过 offset 兜底: %s", full_code, exc)
            return bars

        total = int(meta.get("bars") or 0)
        if total <= 0:
            return bars

        need = min(days, self.page_limit)
        params = {"code": full_code, "limit": need, "offset": max(0, total - need)}
        try:
            data = self._request("/kline/daily", params)
        except NoDataInRangeError:
            return bars

        tail: List[Dict[str, Any]] = []
        for raw in (data or {}).get("items") or []:
            try:
                tail.append(map_bar(raw))
            except (ValueError, TypeError) as exc:
                logger.warning("跳过无效日线记录 %s: %s", full_code, exc)
        return tail[-days:] if tail else bars

    def get_latest_bar(self, code: str) -> Optional[Dict[str, Any]]:
        """获取最新一根日线。"""
        market, digits = split_code(code)
        data = self._request("/kline/daily/latest", {"code": f"{market}{digits}"})
        if not isinstance(data, dict):
            return None
        return map_bar(data)

    def health(self) -> Dict[str, Any]:
        """探活。"""
        data = self._request("/health")
        return data if isinstance(data, dict) else {"status": "unknown"}
