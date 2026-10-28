"""行情数据层：数据源抽象、适配器与工厂。

对外入口：`build_source_chain()` 按配置返回数据源链，
上层 `StockService` 只需遍历该链即可，新增数据源无需改动调用方。
"""
import logging
from typing import List

from .base import (
    InvalidSecurityCodeError,
    MarketDataSource,
    MarketDataSourceError,
    MarketDataSourceUnavailable,
    NoDataInRangeError,
    SecurityNotFoundError,
)
from .code_utils import market_to_cn, split_code, to_market_code
from .legacy_baostock import BaostockDataSource
from .settings import MarketDataSettings, load_settings
from .tdx_local import TdxLocalDataSource, map_bar

logger = logging.getLogger(__name__)

__all__ = [
    "MarketDataSource",
    "MarketDataSourceError",
    "MarketDataSourceUnavailable",
    "InvalidSecurityCodeError",
    "SecurityNotFoundError",
    "NoDataInRangeError",
    "TdxLocalDataSource",
    "BaostockDataSource",
    "build_source_chain",
    "load_settings",
    "MarketDataSettings",
    "map_bar",
    "split_code",
    "to_market_code",
    "market_to_cn",
]


def build_source_chain(settings: MarketDataSettings = None) -> List[MarketDataSource]:
    """按配置构建数据源链（顺序即优先级）。

    Args:
        settings: 数据层配置，缺省从环境变量装载

    Returns:
        数据源实例列表；未知名称会被跳过并告警
    """
    settings = settings or load_settings()
    chain: List[MarketDataSource] = []

    for name in settings.chain:
        if name == "tdx_local":
            chain.append(TdxLocalDataSource(
                base_url=settings.tdx_base_url,
                api_prefix=settings.tdx_api_prefix,
                timeout=settings.timeout,
                connect_timeout=settings.connect_timeout,
                max_retries=settings.max_retries,
                page_limit=settings.page_limit,
            ))
        elif name == "baostock":
            chain.append(BaostockDataSource())
        else:
            logger.warning("未知的数据源名称，已跳过: %s", name)

    if not chain:
        logger.error("数据源链为空，行情数据将不可用（请检查 KRONOS_MARKET_SOURCE_CHAIN）")
    else:
        logger.info("行情数据源链: %s", " -> ".join(src.name for src in chain))
    return chain
