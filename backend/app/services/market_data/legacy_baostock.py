"""旧数据源（Baostock）适配器 —— 默认不启用，仅作回滚通道。

保留原因：`KRONOS_MARKET_SOURCE_CHAIN=tdx_local,baostock` 时可在 TDX 服务
不可用的情况下自动降级，保证迁移可回滚（见设计文档 §7）。
Baostock 依赖按需安装：`pip install baostock==0.8.9`。
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .base import (
    MarketDataSource,
    MarketDataSourceError,
    MarketDataSourceUnavailable,
    SecurityNotFoundError,
)
from .code_utils import split_code

logger = logging.getLogger(__name__)

_FIELDS = "date,open,high,low,close,volume,amount"


def _market_prefix(code: str) -> str:
    """Baostock 代码前缀：sh./sz.（北交所暂不支持）。"""
    market, digits = split_code(code)
    if market == "bj":
        raise MarketDataSourceError(f"Baostock 不支持北交所代码: {code}")
    return f"{market}.{digits}"


class BaostockDataSource(MarketDataSource):
    """Baostock 数据源（保留的旧实现，仅用于回滚）。"""

    name = "baostock"

    def _query(self, code: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """执行一次 Baostock 日线查询并转换为标准结构。"""
        try:
            import baostock as bs
        except ImportError as exc:
            raise MarketDataSourceUnavailable(
                "Baostock 未安装（pip install baostock==0.8.9）"
            ) from exc

        login = bs.login()
        if getattr(login, "error_code", "1") != "0":
            raise MarketDataSourceUnavailable(f"Baostock 登录失败: {login.error_msg}")

        try:
            result = bs.query_history_k_data_plus(
                _market_prefix(code), _FIELDS,
                start_date=start_date, end_date=end_date, frequency="d",
            )
            if result is None:
                return []
            frame = result.get_data()
        finally:
            try:
                bs.logout()
            except Exception as exc:  # 登出失败不影响结果
                logger.debug("Baostock 登出异常: %s", exc)

        if frame is None or frame.empty:
            return []

        bars: List[Dict[str, Any]] = []
        for _, row in frame.iterrows():
            try:
                raw_volume = row.get("volume")
                bars.append({
                    "date": str(row["date"]).strip(),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": int(float(raw_volume))
                    if raw_volume not in (None, "") and str(raw_volume) != "nan" else 0,
                })
            except (ValueError, TypeError) as exc:
                logger.warning("跳过 Baostock 无效数据行: %s", exc)
        return bars

    def get_security(self, code: str) -> Dict[str, Any]:
        """用日线总数与首末日期近似元信息（Baostock 无等价接口）。"""
        end = datetime.now().strftime("%Y-%m-%d")
        bars = self._query(code, "1990-01-01", end)
        if not bars:
            raise SecurityNotFoundError(f"Baostock 无 {code} 日线数据")
        return {
            "market": split_code(code)[0],
            "code": split_code(code)[1],
            "bars": len(bars),
            "first_date": bars[0]["date"],
            "last_date": bars[-1]["date"],
        }

    def get_recent_bars(self, code: str, days: int) -> List[Dict[str, Any]]:
        """取最近 N 个交易日（按自然日放大 2 倍 + 缓冲）。"""
        days = max(1, int(days))
        end = datetime.now()
        start = end - timedelta(days=days * 2 + 10)
        bars = self._query(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        return bars[-days:] if bars else []

    def get_bars_range(self, code: str, start_date: Optional[str] = None,
                       end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """按闭区间查询。"""
        start = start_date or "1990-01-01"
        end = end_date or datetime.now().strftime("%Y-%m-%d")
        return self._query(code, start, end)

    def get_latest_bar(self, code: str) -> Optional[Dict[str, Any]]:
        """取最新一根日线。"""
        bars = self.get_recent_bars(code, 1)
        return bars[-1] if bars else None
