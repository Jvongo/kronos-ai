"""行情数据源抽象层：统一接口与异常体系。

上层（StockService）只依赖本模块的抽象与异常，
新增数据源只需实现 `MarketDataSource` 并注册到数据源链。
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class MarketDataSourceError(Exception):
    """数据源错误基类。

    Args:
        message: 错误描述
        code: 数据源业务码（如 TDX 的 40001/40401/50001）
    """

    def __init__(self, message: str, code: Optional[int] = None):
        super().__init__(message)
        self.code = code


class InvalidSecurityCodeError(MarketDataSourceError):
    """证券代码非法（本地校验或服务端 40001）"""


class SecurityNotFoundError(MarketDataSourceError):
    """证券不存在或无数据（服务端 40401）"""


class NoDataInRangeError(MarketDataSourceError):
    """指定日期区间无数据（服务端 40402）"""


class MarketDataSourceUnavailable(MarketDataSourceError):
    """数据源不可用：连接失败、超时、5xx、响应格式异常"""


class MarketDataSource(ABC):
    """行情数据源统一接口。

    所有方法返回「与数据源无关」的标准结构：
    - `get_security` -> {"market", "code", "bars", "first_date", "last_date", ...}
    - K 线 -> {"date": "YYYY-MM-DD", "open": float, "high": float,
               "low": float, "close": float, "volume": int}

    失败语义：
    - 证券不存在 -> `SecurityNotFoundError`
    - 区间无数据 -> `NoDataInRangeError`（或直接返回空列表，实现可选）
    - 网络/服务异常 -> `MarketDataSourceUnavailable`
    """

    name: str = "base"

    @abstractmethod
    def get_security(self, code: str) -> Dict[str, Any]:
        """获取单只证券的元信息。"""

    @abstractmethod
    def get_recent_bars(self, code: str, days: int) -> List[Dict[str, Any]]:
        """获取最近 N 个交易日的日线（按日期升序）。"""

    @abstractmethod
    def get_bars_range(self, code: str, start_date: Optional[str] = None,
                       end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取闭区间 [start_date, end_date] 内的日线（按日期升序）。"""

    @abstractmethod
    def get_latest_bar(self, code: str) -> Optional[Dict[str, Any]]:
        """获取最新一根日线；无数据返回 None。"""

    def health(self) -> Dict[str, Any]:
        """探活，默认实现视为可用。"""
        return {"status": "ok", "source": self.name}
