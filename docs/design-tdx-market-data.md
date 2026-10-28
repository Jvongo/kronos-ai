# 行情数据源替换设计：Baostock → TDX 本地服务

> 版本 v1.0 · 2026-10-29 · 目标服务 `http://127.0.0.1:8010/api/v1`（TDX 本地行情服务 v1.0.0）

## 1. 目标与硬约束

| 项 | 要求 |
|---|---|
| 数据来源 | 停止调用 Baostock，改调本地 TDX HTTP 服务（只读、无外网） |
| 抽象层 | 保留数据源接口抽象层，新增适配器接入，不改调用方 |
| 调用方 | `main.py`（4 个接口）、`prediction_service.py`、`frontend` 一律零改动 |
| 返回契约 | `StockService` 公共方法与返回结构（键名/类型/语义）完全不变 |
| 可回滚 | 保留 Baostock 适配器代码，仅以开关形式启用 |

## 2. 替换范围

### 2.1 调用链（自下而上）

```
frontend (React)                       ← 不改
   │ GET /stock/{code}、/stock/{code}/history、/stock/{code}/actual、POST /predict
   ▼
backend/main.py                        ← 不改（仅消费 stock_service 公共方法）
   │
   ├── stock_service.validate_stock_code(code)        ← 不改（纯本地校验）
   ├── stock_service.get_stock_info(code)             ┐
   ├── stock_service.get_stock_data(code, days)       ├ 公共 API 签名/返回不变
   ├── stock_service.get_stock_data_for_dates(...)    ┘
   ▼
backend/app/services/stock_service.py  ← 重写为「门面 + 数据源编排」
   │  原：内联 baostock 调用（_fetch_*_from_baostock）
   ▼
backend/app/services/market_data/      ← 新增抽象层与适配器
   ├── base.py            MarketDataSource 抽象 + 异常体系
   ├── code_utils.py      代码归一化 / 市场判定（sh→sz→bj 前缀推导）
   ├── tdx_local.py       TDX 适配器（HTTP、分页、重试、字段映射）
   └── legacy_baostock.py 旧数据源适配器（默认不加载，仅回滚用）
```

### 2.2 受影响文件清单

| 文件 | 动作 |
|---|---|
| `backend/app/services/market_data/*.py` | 新增 4 个模块 |
| `backend/app/services/stock_service.py` | 重写（公共 API 不变，删除内联 baostock 逻辑） |
| `backend/config.py` | 更新 `DATA_SOURCE` 常量（详细参数集中在 `market_data/settings.py`） |
| `backend/requirements.txt` | 移除 `baostock`，新增 `requests` |
| `docker-compose.yml` | 注入 `KRONOS_TDX_BASE_URL` + `extra_hosts`（容器内访问宿主服务） |
| `backend/tests/test_*.py` | 新增单测 |
| `backend/scripts/verify_tdx_migration.py` | 新增联调验证脚本 |
| `backend/scripts/build_stock_names.py` | 新增名称映射生成脚本 |
| `backend/data/stock_names.json` | 新增名称映射数据（已入库） |
| `backend/main.py` / `prediction_service.py` / `frontend/**` | **零改动** |

## 3. 接口契约对照

| StockService 方法 | 底层 TDX 接口 | 说明 |
|---|---|---|
| `get_stock_info(code)` | `GET /securities/{code}` | 元信息 + 本地名称表兜底 |
| `get_stock_data(code, days)` | `GET /kline/daily`（闭区间）→ 兜底 `offset` 取尾部 | 取最近 `days` 个交易日 |
| `get_stock_data_for_dates(code,s,e)` | `GET /kline/daily`（闭区间 + 分页） | 对比实际走势用 |
| `validate_stock_code(code)` | 纯本地 | 保持原实现 |
| `clear_cache()` | — | 清内存缓存 |

## 4. 字段映射与类型转换

### 4.1 K 线（`/kline/daily` → `List[dict]`）

| 目标键（契约） | 类型 | 源字段 | 转换规则 |
|---|---|---|---|
| `date` | `str` | `items[].date`（`YYYY-MM-DD`） | 已是字符串，原样；非字符串用 `strftime('%Y-%m-%d')` 兜底 |
| `open` | `float` | `items[].open` | `float()`，`None`/非数值 → 整行丢弃 |
| `high` | `float` | `items[].high` | 同上 |
| `low` | `float` | `items[].low` | 同上 |
| `close` | `float` | `items[].close` | 同上 |
| `volume` | `int` | `items[].volume`（股） | `int(float(x))`，缺失/NaN → `0` |
| ~~`amount`~~ | — | `items[].amount`（元，float32 有 ±256 量化误差） | **不透传**，避免影响契约；模型侧缺省按 `volume × 均价` 自算 |

单位/精度：价格源已 `÷100` 为元，直接使用；`volume` 源为**股**（界面"手"×100），与 Baostock 同为股，无需换算。

### 4.2 元信息（`/securities/{code}` → `Dict`）

| 目标键 | 类型 | 来源 | 规则 |
|---|---|---|---|
| `code` | `str` | 请求入参归一化后的 6 位代码 | 保持调用方传入的裸代码风格 |
| `name` | `str` | 本地名称表（可选 JSON）→ 内置表 → `股票{code}` | 服务不提供名称，见 §9 限制 |
| `market` | `str` | `data.market`（`sh/sz/bj`） | `sh→上海`、`sz→深圳`、`bj→北京`（保持原中文契约） |
| `industry` | `str` | — | 固定 `""`（原 Baostock 字段缺失时的等价表现） |
| `type` | `str` | — | 固定 `""` |
| `bars` / `first_date` / `last_date` | 增补 | 原样 | 新增可选键，不影响旧消费方 |

## 5. 证券代码归一化（关键陷阱）

规则：**显式前缀优先；无前缀时按首位数字推导市场**，绝不打给服务端裸码。

| 首位 | 判定 | 例 |
|---|---|---|
| `6` | `sh` | `600000 → sh600000` |
| `9`（`92` 除外） | `sh`（沪 B 股） | `900901 → sh900901` |
| `92` | `bj` | `920002 → bj920002` |
| `0` / `2` / `3` | `sz` | `000001 → sz000001`、`300750 → sz300750`、`200002 → sz200002` |
| `4` / `8` | `bj` | `830799 → bj830799` |

> ⚠ **必须带前缀**：服务端无前缀时按 `sh→sz→bj` 探测，裸 `000001` 会命中**上证指数**而非平安银行。旧逻辑（`6` 开头 → 沪，否则深）等价于上表前两类，因此前缀推导既修正陷阱又保持行为一致。

## 6. 异常场景处理矩阵

| 场景 | 识别方式 | 处理策略 | 对外表现 |
|---|---|---|---|
| 连接失败 / DNS | `requests.ConnectionError` | 重试 1 次（0.2s 退避）→ 抛 `MarketDataSourceUnavailable` | `get_stock_info → None`；K 线 → `[]`；日志 ERROR 含 URL |
| 超时 | `ConnectTimeout` 3s / `ReadTimeout` 10s（可配） | 同上（GET 幂等，允许重试） | 同上 |
| `code=40401` 证券不存在 | HTTP 404 + 信封 `code` | 不重试，WARNING | `info → None`、bars → `[]` |
| `code=40402` 区间无数据 | HTTP 404 + 信封 `code` | 不重试；`get_stock_data` 转入 **offset 尾部兜底**；区间查询直接 `[]` | `[]`（非异常） |
| `code=40001` 参数非法 | HTTP 400 | 不重试，ERROR（属我方 bug，归一化后不应出现） | `[]` |
| `code=50001` 服务内部错误 | HTTP 500 | 重试 1 次 → 仍失败抛不可用 | `[]` |
| `code=50301` 数据目录不可用 | HTTP 503（仅 `/health`） | 启动/探活时 WARNING，不阻塞起服 | 数据接口自然降级为 `[]` |
| 信封格式异常（非 JSON / 缺 `code`） | `json.JSONDecodeError` / `KeyError` | 视为不可用，抛 `MarketDataSourceError` | 同上 |
| 行级脏数据（`null`、字符串 `"--"`、`NaN`） | 逐行 try/except | 丢该行，WARNING 计数，不中断整体 | 返回其余有效行 |
| 数据陈旧（末根早于请求区间） | 区间查询命中 `40402` | 转 offset 尾部兜底，取"最近 N 根"而非"最近 N 天" | 正常返回历史数据 |
| 返回条数不足 `days` | `len < days` | 有多少返多少（与旧逻辑 `tail(days)` 一致），由调用方判 `len<30` | 由 `prediction_service` 报数据不足 |

**不做静默造数**：旧的 `_generate_fallback_data`（随机模拟行情）默认**关闭**，仅当 `KRONOS_ALLOW_SYNTHETIC_FALLBACK=true` 时作为最终兜底，避免"用假数据算出真预测"。

## 7. 兼容性保底方案（三级）

1. **一级（默认）**：`tdx_local` 适配器，真实数据。
2. **二级（可选回滚）**：`KRONOS_MARKET_SOURCE_CHAIN=tdx_local,baostock` → TDX 不可用时自动降级到 Baostock（`legacy_baostock.py`，按需 `pip install baostock`）。
3. **三级（显式开启）**：`KRONOS_ALLOW_SYNTHETIC_FALLBACK=true` → 合成数据，仅用于 UI/联调演示。

编排层按 `chain` 顺序调用，任一数据源返回非空即短路返回；全部失败按第 6 节策略降级。

## 8. 缓存

内存缓存保留（键 `{code}:{days}` / `{code}:{start}:{end}`），新增 **TTL 300s**（`KRONOS_MARKET_CACHE_TTL`）以支持日终数据刷新；`clear_cache()` 语义不变。

## 9. 已知限制（不在本次范围）

- TDX 本地服务**不提供证券名称**，已通过 `backend/scripts/build_stock_names.py` 解析本地 `*.tnf` 生成 `backend/data/stock_names.json`（18902 条，可预测代码覆盖 98.5%）；未收录代码回落为 `股票{code}`。
- `amount` 源为 float32（十亿级误差 ±256 元），故不透传给上层。
- `validate_stock_code` 仍只放行沪深主板/创业板/科创板，北交所代码会被前置拦截（保持原行为，不扩展）。
- 本仓库当前**未初始化 git**，本次改动未提交；如需纳入 Git Flow 需先确认初始化仓库。

## 10. 验证方式

1. `pytest backend/tests -q` — 单测（FakeHttp 注入，不依赖网络与服务）。
2. `python backend/scripts/verify_tdx_migration.py` — 对真实服务逐场景断言（正常/空区间/不存在/超时/映射/兼容）。
3. 端到端：`curl /stock/600000/history?days=5`、`POST /predict` 对比字段。
