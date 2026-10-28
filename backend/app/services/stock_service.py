"""股票数据服务（门面层）。

职责：对外暴露稳定的行情获取契约，内部按「数据源链」编排，
调用方（`main.py` / `prediction_service.py`）无需感知底层数据源。

公共契约（与迁移前保持一致，调用方零改动）：
- `get_stock_info(code) -> Optional[dict]`
- `get_stock_data(code, days) -> List[dict]`（最近 N 个交易日）
- `get_stock_data_for_dates(code, start, end) -> List[dict]`
- `validate_stock_code(code) -> bool`
- `clear_cache() -> None`

日线元素结构：`{"date": "YYYY-MM-DD", "open": float, "high": float,
"low": float, "close": float, "volume": int}`
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from .market_data import (
    InvalidSecurityCodeError,
    MarketDataSettings,
    MarketDataSource,
    MarketDataSourceError,
    SecurityNotFoundError,
    build_source_chain,
    load_settings,
    market_to_cn,
    split_code,
)

logger = logging.getLogger(__name__)

# 内置证券名称表（键为「市场:代码」，解决 000001 在沪深两市同名问题）
_BUILTIN_NAMES: Dict[str, str] = {
    "sh:600000": "浦发银行",
    "sh:600036": "招商银行",
    "sh:600519": "贵州茅台",
    "sh:600276": "恒瑞医药",
    "sh:000001": "上证指数",
    "sz:000001": "平安银行",
    "sz:000002": "万科A",
    "sz:000858": "五粮液",
    "sz:002415": "海康威视",
}

# 交易日历参考标的（上证指数，日线覆盖最长，用于推导真实交易日）
_CALENDAR_INDEX = "sh000001"

# 合成数据兜底时的基准价（仅 KRONOS_ALLOW_SYNTHETIC_FALLBACK=true 时使用）
_SYNTHETIC_BASE_PRICES: Dict[str, float] = {
    "600519": 1500.0,
    "000858": 150.0,
    "600036": 40.0,
    "000001": 15.0,
    "600000": 10.0,
    "000002": 20.0,
}


def _parse_trade_date(value: str) -> datetime:
    """解析交易日期字符串。

    Args:
        value: `YYYY-MM-DD` 或 `YYYYMMDD`

    Returns:
        datetime 对象

    Raises:
        ValueError: 格式非法
    """
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"日期格式非法: {value!r}，应为 YYYY-MM-DD 或 YYYYMMDD")


class StockService:
    """股票数据服务门面。"""

    def __init__(
        self,
        sources: Optional[Sequence[MarketDataSource]] = None,
        cache_ttl: Optional[float] = None,
        allow_synthetic_fallback: Optional[bool] = None,
        settings: Optional[MarketDataSettings] = None,
    ):
        """初始化服务。

        Args:
            sources: 数据源链（按优先级），缺省按配置构建
            cache_ttl: 内存缓存有效期（秒）
            allow_synthetic_fallback: 数据源全失败时是否用合成数据兜底
            settings: 数据层配置，缺省从环境变量装载
        """
        self._settings = settings or load_settings()
        self.sources: List[MarketDataSource] = (
            list(sources) if sources is not None else build_source_chain(self._settings)
        )
        self._cache_ttl = float(
            self._settings.cache_ttl if cache_ttl is None else cache_ttl
        )
        self._allow_synthetic = (
            self._settings.allow_synthetic_fallback
            if allow_synthetic_fallback is None else bool(allow_synthetic_fallback)
        )
        # 缓存：key -> (写入时刻, 数据)
        self._cache: Dict[str, Any] = {}
        self._clock = time.monotonic
        self._names: Optional[Dict[str, str]] = None
        self._holidays: Optional[set] = None

        # 兼容旧属性：历史代码可能引用本地缓存目录
        self.cache_dir = Path(__file__).parent.parent.parent / "data" / "cache"
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.debug("缓存目录创建失败（忽略）: %s", exc)

    # ------------------------------------------------------------------ #
    # 公共接口
    # ------------------------------------------------------------------ #
    async def get_stock_info(self, code: str) -> Optional[Dict[str, Any]]:
        """获取股票基本信息。

        Args:
            code: 6 位代码，可带 sh/sz/bj 前缀

        Returns:
            成功返回 `{code, name, market, industry, type, bars, first_date, last_date}`；
            证券不存在或数据源不可用返回 None
        """
        cache_key = f"info:{code}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        for source in self.sources:
            try:
                meta = await asyncio.to_thread(source.get_security, code)
            except (SecurityNotFoundError, InvalidSecurityCodeError) as exc:
                logger.info("证券 %s 不存在或代码非法（%s）: %s", code, source.name, exc)
                return None
            except MarketDataSourceError as exc:
                logger.warning("数据源 %s 获取 %s 元信息失败: %s", source.name, code, exc)
                continue

            info = self._build_stock_info(code, meta)
            self._cache_set(cache_key, info)
            return info

        logger.error("所有数据源均无法获取 %s 元信息", code)
        return None

    async def get_stock_data(self, code: str, days: int = 30) -> List[Dict[str, Any]]:
        """获取最近 N 个交易日的日线数据。

        Args:
            code: 股票代码
            days: 需要的交易日数量

        Returns:
            按日期升序的日线列表；无数据/数据源不可用返回空列表
        """
        cache_key = f"bars:{code}:{days}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.debug("使用缓存数据 %s", cache_key)
            return cached

        for source in self.sources:
            try:
                bars = await asyncio.to_thread(source.get_recent_bars, code, days)
            except (SecurityNotFoundError, InvalidSecurityCodeError) as exc:
                logger.info("证券 %s 不存在或代码非法（%s）: %s", code, source.name, exc)
                return []
            except MarketDataSourceError as exc:
                logger.warning("数据源 %s 获取 %s 日线失败: %s", source.name, code, exc)
                continue

            if bars:
                self._cache_set(cache_key, bars)
                logger.info("%s 从 %s 获取 %s 条日线", code, source.name, len(bars))
                return bars

        if self._allow_synthetic:
            logger.warning("行情数据源全部失败，按开关启用合成数据兜底: %s", code)
            return self._generate_fallback_data(code, days)

        logger.error("所有数据源均无 %s 的日线数据", code)
        return []

    async def get_stock_data_for_dates(
        self, code: str, start_date: str, end_date: str
    ) -> List[Dict[str, Any]]:
        """获取指定闭区间内的日线数据（用于对比预测与实际）。

        Returns:
            按日期升序的日线列表；区间无数据返回空列表
        """
        cache_key = f"range:{code}:{start_date}:{end_date}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        for source in self.sources:
            try:
                bars = await asyncio.to_thread(
                    source.get_bars_range, code, start_date, end_date
                )
            except (SecurityNotFoundError, InvalidSecurityCodeError) as exc:
                logger.info("证券 %s 不存在或代码非法（%s）: %s", code, source.name, exc)
                return []
            except MarketDataSourceError as exc:
                logger.warning("数据源 %s 获取 %s 区间数据失败: %s", source.name, code, exc)
                continue

            if bars:
                self._cache_set(cache_key, bars)
                return bars

        logger.info("%s 在 %s ~ %s 区间无数据", code, start_date, end_date)
        return []

    async def get_history_ending_before(
        self, code: str, end_date: str, days: int = 60
    ) -> List[Dict[str, Any]]:
        """获取「截止指定日期（不含当日）」的最近 N 个交易日数据。

        用于回测：指定预测起始日时，模型输入必须截止到该日之前，
        否则预测数值属于「今天之后」而日期标签贴在早期，会出现虚假跳空。

        Args:
            code: 股票代码
            end_date: 截止日期（不含），`YYYY-MM-DD` 或 `YYYYMMDD`
            days: 需要的交易日数量

        Returns:
            按日期升序的日线列表；不足或无数据时返回已取到的部分（可能为空）

        Raises:
            ValueError: 日期格式非法
        """
        cutoff = _parse_trade_date(end_date)
        days = max(1, int(days))

        # 日历日缓冲：交易日约为日历日的 2/3，留 3 倍余量
        start = cutoff - timedelta(days=max(days * 3, 120))
        bars = await self.get_stock_data_for_dates(
            code,
            start.strftime("%Y-%m-%d"),
            (cutoff - timedelta(days=1)).strftime("%Y-%m-%d"),
        )

        cutoff_str = cutoff.strftime("%Y-%m-%d")
        bars = [bar for bar in bars if str(bar.get("date", "")) < cutoff_str]
        return bars[-days:]

    async def get_trading_days(self, start_date: str, count: int) -> List[str]:
        """返回从 start_date（含）起的 count 个真实交易日。

        以参考指数（上证指数）的真实日线为准，因此会自动跳过周末与法定节假日；
        超出本地行情数据末尾（未来日期）时，退化为「工作日 − 休市文件中的日期」。

        Args:
            start_date: 起始日期，`YYYY-MM-DD` 或 `YYYYMMDD`
            count: 需要的交易日数量（1~60）

        Returns:
            升序日期字符串列表，长度尽量为 count

        Raises:
            ValueError: 日期格式非法
        """
        cutoff = _parse_trade_date(start_date).date()
        count = max(1, min(int(count), 60))

        window_start = cutoff - timedelta(days=10)
        window_end = cutoff + timedelta(days=count * 3 + 40)
        bars = await self.get_stock_data_for_dates(
            _CALENDAR_INDEX, window_start.isoformat(), window_end.isoformat()
        )

        cutoff_str = cutoff.isoformat()
        days = [
            str(bar.get("date", "")) for bar in bars
            if str(bar.get("date", "")) >= cutoff_str
        ][:count]
        if len(days) >= count:
            return days

        # 数据未覆盖（未来日期）：按工作日补齐，跳过休市文件中登记的日期
        holidays = self._load_holidays()
        cursor = (_parse_trade_date(days[-1]).date() + timedelta(days=1)) if days else cutoff
        limit = cutoff + timedelta(days=count * 3 + 60)
        while len(days) < count and cursor <= limit:
            if cursor.weekday() < 5 and cursor.isoformat() not in holidays:
                days.append(cursor.isoformat())
            cursor += timedelta(days=1)

        logger.info("交易日历：数据仅覆盖到 %s，后续日期按工作日+休市文件推算",
                    days[len(days) - 1] if days else "无")
        return days[:count]

    async def validate_stock_code(self, code: str) -> bool:
        """验证股票代码格式（保持迁移前实现不变）。"""
        if not code or len(code) != 6:
            return False

        if not code.isdigit():
            return False

        code_int = int(code)

        # 上海主板：600000-604999, 科创板：688000-688999
        if 600000 <= code_int <= 604999 or 688000 <= code_int <= 688999:
            return True

        # 深圳主板：000001-002999, 创业板：300000-300999, 301000-301999
        if (1 <= code_int <= 2999 or
                300000 <= code_int <= 300999 or
                301000 <= code_int <= 301999):
            return True

        return False

    def clear_cache(self) -> None:
        """清空内存缓存。"""
        self._cache.clear()
        logger.info("股票数据缓存已清空")

    def _load_holidays(self) -> set:
        """加载休市日历（可选文件，缺失时返回空集合）。"""
        if self._holidays is not None:
            return self._holidays

        self._holidays = set()
        path = self._settings.holidays_file
        try:
            if path and Path(path).exists():
                with open(path, "r", encoding="utf-8") as handle:
                    raw = json.load(handle)
                if isinstance(raw, list):
                    self._holidays = {str(item).strip() for item in raw if str(item).strip()}
                    logger.info("已加载休市日历 %s 条: %s", len(self._holidays), path)
        except (OSError, ValueError) as exc:
            logger.warning("休市日历加载失败（已忽略）: %s", exc)
        return self._holidays

    def get_source_status(self) -> List[Dict[str, Any]]:
        """探活所有数据源，返回状态列表（供运维/验证脚本使用）。"""
        status = []
        for source in self.sources:
            try:
                info = source.health()
                status.append({"source": source.name, "available": True, "detail": info})
            except Exception as exc:  # 探活失败不应影响服务
                status.append({"source": source.name, "available": False,
                               "detail": str(exc)})
        return status

    # ------------------------------------------------------------------ #
    # 内部工具
    # ------------------------------------------------------------------ #
    def _build_stock_info(self, code: str, meta: Dict[str, Any]) -> Dict[str, Any]:
        """把数据源元信息转换为对外契约结构。"""
        market = str(meta.get("market") or "").strip().lower()
        try:
            digits = split_code(code)[1]
        except InvalidSecurityCodeError:
            digits = str(code).strip()
        if not market:
            market = "sh" if digits.startswith("6") else "sz"

        return {
            "code": digits,
            "name": self._resolve_name(market, digits),
            "market": market_to_cn(market) or ("上海" if market == "sh" else "深圳"),
            "industry": "",
            "type": "",
            "bars": meta.get("bars"),
            "first_date": meta.get("first_date"),
            "last_date": meta.get("last_date"),
        }

    def _resolve_name(self, market: str, digits: str) -> str:
        """解析证券名称：外部映射文件 > 内置表 > 通用占位名。"""
        overrides = self._load_names()

        for key in (f"{market}{digits}", f"{market}:{digits}", digits):
            if key in overrides:
                return overrides[key]

        builtin = _BUILTIN_NAMES.get(f"{market}:{digits}")
        if builtin:
            return builtin
        return f"股票{digits}"

    def _load_names(self) -> Dict[str, str]:
        """加载外部名称映射（可选，失败时静默降级）。"""
        if self._names is not None:
            return self._names

        self._names = {}
        path = self._settings.names_file
        try:
            if path and Path(path).exists():
                with open(path, "r", encoding="utf-8") as handle:
                    raw = json.load(handle)
                if isinstance(raw, dict):
                    self._names = {str(k): str(v) for k, v in raw.items()}
                    logger.info("已加载证券名称映射 %s 条: %s", len(self._names), path)
        except (OSError, ValueError) as exc:
            logger.warning("证券名称映射加载失败（已忽略）: %s", exc)
        return self._names

    def _cache_get(self, key: str) -> Optional[Any]:
        """读缓存，过期则清除并返回 None。"""
        entry = self._cache.get(key)
        if not entry:
            return None
        stored_at, value = entry
        if self._clock() - stored_at > self._cache_ttl:
            self._cache.pop(key, None)
            return None
        return value

    def _cache_set(self, key: str, value: Any) -> None:
        """写缓存，记录写入时刻。"""
        self._cache[key] = (self._clock(), value)

    def _generate_fallback_data(self, code: str, days: int) -> List[Dict[str, Any]]:
        """生成合成行情数据（默认关闭，仅演示/联调用）。

        Args:
            code: 股票代码
            days: 生成的交易日数量

        Returns:
            与真实数据同结构的日线列表（date 为 YYYY-MM-DD 字符串）
        """
        logger.warning("为 %s 生成 %s 天合成数据（非真实行情）", code, days)

        current_date = datetime.now() - timedelta(days=days)
        base_price = _SYNTHETIC_BASE_PRICES.get(code, 10.0)
        data: List[Dict[str, Any]] = []

        for i in range(days):
            if current_date.weekday() < 5:  # 仅工作日
                price_change = (i % 7 - 3) * 0.02
                trend = i * 0.001
                open_price = base_price * (1 + price_change + trend)
                close_price = open_price * (1 + np.random.normal(0, 0.01))
                high_price = max(open_price, close_price) * (1 + abs(np.random.normal(0, 0.005)))
                low_price = min(open_price, close_price) * (1 - abs(np.random.normal(0, 0.005)))

                data.append({
                    "date": current_date.strftime("%Y-%m-%d"),
                    "open": round(open_price, 2),
                    "high": round(high_price, 2),
                    "low": round(low_price, 2),
                    "close": round(close_price, 2),
                    "volume": int(np.random.randint(1000000, 10000000)),
                })
                base_price = close_price

            current_date += timedelta(days=1)

        return data


# 全局股票服务实例
stock_service = StockService()
