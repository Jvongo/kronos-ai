"""行情数据源迁移验证脚本（联调）。

对真实 TDX 本地行情服务逐场景断言：正常取数、契约字段、市场判定、
空数据、不存在证券、非法代码、服务不可用降级、缓存命中。

用法：
    python backend/scripts/verify_tdx_migration.py
    python backend/scripts/verify_tdx_migration.py --base-url http://127.0.0.1:8010
"""
import argparse
import asyncio
import sys
import time
import types
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 数据层验证不需要模型依赖（torch/transformers）；
# `app.services.__init__` 会连带导入 model_manager，故用轻量包占位绕开
if "app.services" not in sys.modules:
    _pkg = types.ModuleType("app.services")
    _pkg.__path__ = [str(BACKEND_DIR / "app" / "services")]
    sys.modules["app.services"] = _pkg

from app.services.market_data import TdxLocalDataSource  # noqa: E402
from app.services.stock_service import StockService  # noqa: E402

BAR_KEYS = {"date", "open", "high", "low", "close", "volume"}
results = []


def record(name: str, passed: bool, detail: str = "") -> None:
    """记录一条验证结果并即时打印。"""
    results.append((name, passed, detail))
    flag = "PASS" if passed else "FAIL"
    print(f"[{flag}] {name}" + (f" | {detail}" if detail else ""))


def check_bars(name: str, bars, min_len: int = 1) -> bool:
    """校验日线列表的结构契约与基本合理性。"""
    if not bars or len(bars) < min_len:
        record(name, False, f"条数不足：{len(bars) if bars else 0} < {min_len}")
        return False
    first, last = bars[0], bars[-1]
    problems = []
    if set(first) != BAR_KEYS:
        problems.append(f"字段不符: {sorted(first)}")
    if not isinstance(first["date"], str):
        problems.append("date 非字符串")
    if not isinstance(first["open"], float) or not isinstance(first["volume"], int):
        problems.append("open/volume 类型不符")
    if [b["date"] for b in bars] != sorted(b["date"] for b in bars):
        problems.append("未按日期升序")
    if any(b["close"] <= 0 for b in bars):
        problems.append("存在非正收盘价")
    record(name, not problems,
           f"{len(bars)} 条 {first['date']}~{last['date']} close={last['close']}"
           + (f" | {'; '.join(problems)}" if problems else ""))
    return not problems


async def main(base_url: str) -> int:
    """执行全部验证场景。"""
    settings_source = TdxLocalDataSource(base_url=base_url, max_retries=0)
    service = StockService(sources=[settings_source], cache_ttl=300)

    # 0. 探活
    try:
        health = settings_source.health()
        record("0. 服务探活 /health", health.get("vipdoc_exists") is True, str(health))
    except Exception as exc:
        record("0. 服务探活 /health", False, f"服务不可达: {exc}")
        print("\n服务不可达，后续场景跳过。请确认 TDX 本地服务已启动（默认 8010 端口）。")
        return 1

    # 1. 元信息映射
    info = await service.get_stock_info("600000")
    record("1. 元信息映射 600000",
           bool(info) and info["market"] == "上海" and info["name"] == "浦发银行"
           and info["industry"] == "" and info["type"] == "",
           str(info))

    # 2. 最近 5 日
    bars5 = await service.get_stock_data("600000", days=5)
    check_bars("2. 最近 5 个交易日", bars5, 5)

    # 3. 预测所需 60 日（prediction_service 要求 >= 30）
    bars60 = await service.get_stock_data("600000", days=60)
    check_bars("3. 最近 60 个交易日（预测输入）", bars60, 30)

    # 4. 跨市场同码判定：000001 必须命中深市平安银行
    info_sz = await service.get_stock_info("000001")
    record("4. 000001 判定为深市平安银行",
           bool(info_sz) and info_sz["market"] == "深圳" and info_sz["name"] == "平安银行",
           str(info_sz))

    # 5. 区间查询（用于预测对比）
    if bars5:
        start, end = bars5[0]["date"], bars5[-1]["date"]
        ranged = await service.get_stock_data_for_dates("600000", start, end)
        check_bars(f"5. 区间查询 {start}~{end}", ranged, 1)

    # 6. 空区间 -> 空列表（不抛异常）
    empty = await service.get_stock_data_for_dates("600000", "1990-01-01", "1990-12-31")
    record("6. 空区间返回空列表", empty == [], f"len={len(empty)}")

    # 7. 不存在的证券 -> info None / bars []
    not_found_info = await service.get_stock_info("600001")
    not_found_bars = await service.get_stock_data("600001", days=5)
    record("7. 不存在证券降级", not_found_info is None and not_found_bars == [],
           f"info={not_found_info} bars={len(not_found_bars)}")

    # 8. 非法代码 -> 不崩
    illegal_info = await service.get_stock_info("abc")
    record("8. 非法代码降级", illegal_info is None, f"info={illegal_info}")

    # 9. 服务不可用 -> 降级为空（模拟错误端口）
    down = TdxLocalDataSource(base_url="http://127.0.0.1:9", max_retries=0, timeout=2)
    down_service = StockService(sources=[down], cache_ttl=1)
    started = time.time()
    down_bars = await down_service.get_stock_data("600000", days=5)
    elapsed = time.time() - started
    record("9. 服务不可用降级为空", down_bars == [], f"len={len(down_bars)} 耗时 {elapsed:.2f}s")

    # 10. 超时策略生效（不可用地址应在超时+重试窗口内返回）
    record("10. 不可用地址快速失败", elapsed < 5.0, f"{elapsed:.2f}s < 5.0s")

    # 11. 缓存命中（第二次调用不产生网络请求）
    class CountingHttp:
        """统计请求次数的 HTTP 包装器。"""

        def __init__(self, inner):
            self.inner = inner
            self.count = 0

        def get(self, url, params=None, timeout=None):
            self.count += 1
            return self.inner.get(url, params=params, timeout=timeout)

    import requests

    counting = CountingHttp(requests)
    cached_source = TdxLocalDataSource(base_url=base_url, http=counting, max_retries=0)
    cached_service = StockService(sources=[cached_source], cache_ttl=300)
    await cached_service.get_stock_data("600036", days=5)
    first_count = counting.count
    await cached_service.get_stock_data("600036", days=5)
    record("11. 缓存命中", counting.count == first_count,
           f"首次 {first_count} 次请求，二次新增 {counting.count - first_count} 次")

    # 12. 空数据源的显式失败（不静默造数）
    record("12. 默认不启用合成数据", cached_service._allow_synthetic is False,
           f"allow_synthetic_fallback={cached_service._allow_synthetic}")

    # 13. 下游模型输入兼容（kronos_integration 的 DataFrame 装配方式）
    if bars60:
        import pandas as pd

        frame = pd.DataFrame(bars60)
        frame["timestamps"] = pd.to_datetime(frame["date"])
        compatible = (
            len(frame) == len(bars60)
            and frame["timestamps"].is_monotonic_increasing
            and {"open", "high", "low", "close"}.issubset(frame.columns)
        )
        record("13. 模型输入 DataFrame 兼容", compatible,
               f"rows={len(frame)} 时间戳递增={frame['timestamps'].is_monotonic_increasing}")
    else:
        record("13. 模型输入 DataFrame 兼容", False, "缺少日线数据")

    # 14. 证券名称映射（backend/data/stock_names.json 注入后生效）
    name_map = service._load_names()
    samples = {"600519": "贵州茅台", "300750": "宁德时代", "688981": "中芯国际"}
    resolved = {code: (await service.get_stock_info(code))["name"] for code in samples}
    name_ok = len(name_map) > 9000 and resolved == samples
    record("14. 名称映射生效", name_ok, f"映射 {len(name_map)} 条，抽样 {resolved}")

    # 汇总
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n===== 验证汇总: {passed}/{total} 通过 =====")
    failed = [name for name, ok, _ in results if not ok]
    if failed:
        print("失败项: " + ", ".join(failed))
    return 0 if passed == total else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="行情数据源迁移验证")
    parser.add_argument("--base-url", default=None, help="TDX 服务地址，默认读环境变量或 8010")
    args = parser.parse_args()
    source_default = TdxLocalDataSource().base_url if not args.base_url else args.base_url
    sys.exit(asyncio.run(main(source_default)))
