"""从通达信本地数据生成证券名称映射（backend/data/stock_names.json）。

TDX 本地行情服务只提供行情、不提供名称，故名称映射由本脚本离线生成：
数据源为 `T0002/hq_cache/{shs,szs,bjs}.tnf`（50 字节头 + 360 字节/条，
名称字段为偏移 31 起的 32 字节 GBK），并只保留 `vipdoc/{sh,sz,bj}/lday`
中真实存在日线文件的代码，保证映射与可查询范围一致。

用法：
    python backend/scripts/build_stock_names.py
    python backend/scripts/build_stock_names.py --tdx-home D:/new_tdx --output backend/data/stock_names.json
"""
import argparse
import json
import os
from pathlib import Path
from typing import Dict, Tuple

BACKEND_DIR = Path(__file__).resolve().parents[1]

# tnf 文件格式常量
_TNF_HEADER_SIZE = 50
_TNF_RECORD_SIZE = 360
_TNF_CODE_OFFSET = 0
_TNF_CODE_SIZE = 6
_TNF_NAME_OFFSET = 31
_TNF_NAME_SIZE = 32

# 市场 -> tnf 文件名
_MARKET_FILES = {"sh": "shs.tnf", "sz": "szs.tnf", "bj": "bjs.tnf"}


def parse_tnf(path: Path) -> Dict[str, str]:
    """解析单个 tnf 名称表。

    Args:
        path: `shs.tnf` / `szs.tnf` / `bjs.tnf`

    Returns:
        `{6 位代码: 名称}`；文件缺失或过短返回空字典
    """
    if not path.exists():
        print(f"[WARN] 名称表不存在，跳过: {path}")
        return {}

    data = path.read_bytes()
    if len(data) <= _TNF_HEADER_SIZE:
        print(f"[WARN] 名称表为空，跳过: {path}")
        return {}

    total = (len(data) - _TNF_HEADER_SIZE) // _TNF_RECORD_SIZE
    names: Dict[str, str] = {}

    for index in range(total):
        start = _TNF_HEADER_SIZE + index * _TNF_RECORD_SIZE
        record = data[start:start + _TNF_RECORD_SIZE]
        code = record[_TNF_CODE_OFFSET:_TNF_CODE_OFFSET + _TNF_CODE_SIZE]
        if not code.isdigit():
            continue
        raw_name = record[_TNF_NAME_OFFSET:_TNF_NAME_OFFSET + _TNF_NAME_SIZE]
        name = raw_name.split(b"\x00")[0].decode("gbk", "ignore").strip()
        if name:
            names[code.decode("ascii")] = name

    print(f"[INFO] {path.name}: {total} 条记录，解析出 {len(names)} 个名称")
    return names


def list_vipdoc_codes(tdx_home: Path, market: str) -> set:
    """列出 `vipdoc/{market}/lday` 下真实存在的 6 位代码集合。"""
    lday = tdx_home / "vipdoc" / market / "lday"
    if not lday.is_dir():
        print(f"[WARN] 日线目录不存在，跳过: {lday}")
        return set()

    codes = set()
    for entry in lday.iterdir():
        if entry.suffix.lower() != ".day":
            continue
        stem = entry.stem  # 形如 sh600000
        digits = stem[2:] if stem[:2].lower() == market else stem
        if len(digits) == 6 and digits.isdigit():
            codes.add(digits)
    print(f"[INFO] vipdoc/{market}: {len(codes)} 个日线文件")
    return codes


def build_mapping(tdx_home: Path) -> Tuple[Dict[str, str], Dict[str, int]]:
    """生成名称映射。

    Returns:
        (映射字典, 各市场统计)

    键规则：
    - 主键为「市场+代码」（如 `sh600000`），解决沪深同码歧义；
    - 同一代码只存在于一个市场时，额外补一个裸 6 位键，便于手工维护；
      StockService 解析时优先取带前缀的键，裸键不会覆盖它。
    """
    hq_cache = tdx_home / "T0002" / "hq_cache"
    mapping: Dict[str, str] = {}
    stats: Dict[str, int] = {}

    per_market: Dict[str, Dict[str, str]] = {}
    for market, filename in _MARKET_FILES.items():
        names = parse_tnf(hq_cache / filename)
        codes = list_vipdoc_codes(tdx_home, market)
        if codes:
            names = {code: name for code, name in names.items() if code in codes}
        per_market[market] = names
        stats[market] = len(names)
        for code, name in names.items():
            mapping[f"{market}{code}"] = name

    # 统计每个代码出现过的市场数，仅对唯一市场补裸键
    code_markets: Dict[str, list] = {}
    for market, names in per_market.items():
        for code in names:
            code_markets.setdefault(code, []).append(market)

    for code, markets in code_markets.items():
        if len(markets) == 1:
            mapping[code] = per_market[markets[0]][code]

    return dict(sorted(mapping.items())), stats


def main() -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="生成证券名称映射 stock_names.json")
    parser.add_argument("--tdx-home", default=os.environ.get("TDX_HOME", "D:/new_tdx"),
                        help="通达信数据根目录（默认读 TDX_HOME 或 D:/new_tdx）")
    parser.add_argument("--output", default=str(BACKEND_DIR / "data" / "stock_names.json"),
                        help="输出文件路径")
    args = parser.parse_args()

    tdx_home = Path(args.tdx_home)
    if not tdx_home.is_dir():
        print(f"[ERROR] 通达信目录不存在: {tdx_home}")
        return 1

    mapping, stats = build_mapping(tdx_home)
    if not mapping:
        print("[ERROR] 未生成任何名称映射")
        return 1

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"[OK] 写入 {output}，共 {len(mapping)} 条"
          f"（sh={stats.get('sh', 0)}, sz={stats.get('sz', 0)}, bj={stats.get('bj', 0)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
