"""行情数据层配置：环境变量驱动，带安全默认值。

所有配置均可用 `KRONOS_*` 环境变量覆盖，便于容器部署与灰度回滚。
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Tuple

BACKEND_DIR = Path(__file__).resolve().parents[3]
DEFAULT_NAMES_FILE = BACKEND_DIR / "data" / "stock_names.json"


def _env_str(key: str, default: str) -> str:
    """读取字符串型环境变量，空白视为未设置。"""
    value = os.environ.get(key, "").strip()
    return value or default


def _env_float(key: str, default: float) -> float:
    """读取浮点型环境变量，非法值回落默认值。"""
    try:
        return float(_env_str(key, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(key: str, default: int) -> int:
    """读取整型环境变量，非法值回落默认值。"""
    try:
        return int(float(_env_str(key, str(default))))
    except (TypeError, ValueError):
        return default


def _env_bool(key: str, default: bool) -> bool:
    """读取布尔型环境变量，支持 1/true/yes/on。"""
    raw = _env_str(key, "true" if default else "false").lower()
    return raw in ("1", "true", "yes", "y", "on")


@dataclass(frozen=True)
class MarketDataSettings:
    """行情数据层运行时配置。"""

    # 数据源优先级链，逗号分隔。默认只用本地 TDX 服务（已停用 Baostock）
    chain: Tuple[str, ...] = ("tdx_local",)
    # TDX 本地行情服务地址（注意与 Kronos 后端 8000 端口区分）
    tdx_base_url: str = "http://127.0.0.1:8010"
    tdx_api_prefix: str = "/api/v1"
    # 网络超时（秒）与重试次数（GET 幂等，允许有限重试）
    timeout: float = 10.0
    connect_timeout: float = 3.0
    max_retries: int = 1
    # 单页最大条数（服务端上限 5000）
    page_limit: int = 5000
    # 内存缓存有效期（秒）
    cache_ttl: float = 300.0
    # 数据源全失败时是否用合成数据兜底（默认关闭，避免"假数据出真预测"）
    allow_synthetic_fallback: bool = False
    # 证券名称映射文件（服务端不提供名称，可自行注入）
    names_file: Path = field(default=DEFAULT_NAMES_FILE)


def load_settings() -> MarketDataSettings:
    """从环境变量装载配置。"""
    raw_chain = _env_str("KRONOS_MARKET_SOURCE_CHAIN", "tdx_local")
    chain = tuple(item.strip().lower() for item in raw_chain.split(",") if item.strip())
    names_file = _env_str("KRONOS_STOCK_NAMES_FILE", str(DEFAULT_NAMES_FILE))

    return MarketDataSettings(
        chain=chain or ("tdx_local",),
        tdx_base_url=_env_str("KRONOS_TDX_BASE_URL", "http://127.0.0.1:8010").rstrip("/"),
        tdx_api_prefix=_env_str("KRONOS_TDX_API_PREFIX", "/api/v1"),
        timeout=_env_float("KRONOS_TDX_TIMEOUT", 10.0),
        connect_timeout=_env_float("KRONOS_TDX_CONNECT_TIMEOUT", 3.0),
        max_retries=_env_int("KRONOS_TDX_MAX_RETRIES", 1),
        page_limit=max(1, min(_env_int("KRONOS_TDX_PAGE_LIMIT", 5000), 5000)),
        cache_ttl=_env_float("KRONOS_MARKET_CACHE_TTL", 300.0),
        allow_synthetic_fallback=_env_bool("KRONOS_ALLOW_SYNTHETIC_FALLBACK", False),
        names_file=Path(names_file),
    )
