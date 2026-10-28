# 行情数据源迁移报告：Baostock → TDX 本地服务

> 完成时间 2026-10-29 · 目标服务 `http://127.0.0.1:8010/api/v1`（实测在线，`vipdoc_exists=true`）
> 单元测试 **42 passed** · 真实联调 **14/14 通过**

## 1. 结论速览

| 项 | 结果 |
|---|---|
| 原数据源 | Baostock —— 已停止调用（默认数据源链只含 `tdx_local`） |
| 新数据源 | 本地 TDX 行情服务，HTTP + `/api/v1` 统一信封 |
| 调用方改动 | **0 行**（`main.py` / `prediction_service.py` / 前端均未改） |
| 抽象层 | 保留并新增 `MarketDataSource` 抽象 + 适配器 + 工厂 |
| 契约变化 | 公共方法签名与日线字段完全一致；`get_stock_info` 新增 3 个可选键 |
| 回归风险 | 低：三级降级链 + Baostock 适配器保留可回滚 |

## 2. 替换范围

### 2.1 调用链（自上而下，🔒 为未改动节点）

```
前端 React 🔒
  ↓ GET /stock/{code}、/stock/{code}/history、/stock/{code}/actual、POST /predict
backend/main.py 🔒
  ↓ stock_service.validate_stock_code / get_stock_info / get_stock_data / get_stock_data_for_dates
backend/app/services/prediction_service.py 🔒
  ↓ stock_service.*（同上）、kronos_integration 🔒
backend/app/services/stock_service.py  ★ 重写为门面
  ↓ for source in self.sources: ...
backend/app/services/market_data/  ★ 新增
  ├─ base.py            抽象接口 + 异常体系
  ├─ code_utils.py      代码归一化 / 市场判定
  ├─ tdx_local.py       TDX 适配器（HTTP/信封/分页/重试/映射）
  ├─ legacy_baostock.py 旧数据源（默认不加载，回滚用）
  ├─ settings.py        环境变量配置
  └─ __init__.py        build_source_chain() 工厂
  ↓ HTTP
http://127.0.0.1:8010/api/v1/{health,securities,kline/daily}
```

### 2.2 文件变更清单

| 文件 | 变更 |
|---|---|
| `backend/app/services/market_data/base.py` | 新增（抽象层） |
| `backend/app/services/market_data/code_utils.py` | 新增 |
| `backend/app/services/market_data/tdx_local.py` | 新增（核心适配器） |
| `backend/app/services/market_data/legacy_baostock.py` | 新增（旧源适配，opt-in） |
| `backend/app/services/market_data/settings.py` | 新增（env 配置） |
| `backend/app/services/market_data/__init__.py` | 新增（工厂） |
| `backend/app/services/stock_service.py` | 重写（公共 API 不变，移除内联 baostock） |
| `backend/requirements.txt` | `baostock==0.8.9` → `requests>=2.31.0` |
| `backend/config.py` | `DATA_SOURCE: baostock → tdx_local`（2 行） |
| `backend/tests/conftest.py`、`test_market_data_tdx.py` | 新增（42 个用例） |
| `backend/scripts/verify_tdx_migration.py` | 新增（联调验证） |
| `docker-compose.yml` | 注入 `KRONOS_TDX_*` 环境变量 + `extra_hosts` |
| `README.md` | 数据源描述同步（5 处） |
| `main.py`、`prediction_service.py`、`frontend/**` | **未改动** |

## 3. 映射规则

### 3.1 日线（`GET /kline/daily` → `List[dict]`）

| 目标字段 | 类型 | 源字段 | 转换 |
|---|---|---|---|
| `date` | `str` | `items[].date` | 原样 `YYYY-MM-DD`；非字符串走 `strftime` |
| `open` | `float` | `items[].open` | `float()`；`None`/空/`NaN`/`"--"` → 丢整行 |
| `high` | `float` | `items[].high` | 同上 |
| `low` | `float` | `items[].low` | 同上 |
| `close` | `float` | `items[].close` | 同上 |
| `volume` | `int` | `items[].volume`（股） | `int(float())`；缺失/非法 → `0`（不丢行） |
| ~~`amount`~~ | — | `items[].amount`（元） | **不透传**：源为 float32，十亿级误差约 ±256 元 |

单位：价格源已 ÷100 为元，直接用；`volume` 源为**股**，与 Baostock 一致，无需换算。

### 3.2 元信息（`GET /securities/{code}` → `dict`）

| 目标字段 | 来源 | 规则 |
|---|---|---|
| `code` | 入参 | 归一化后 6 位数字 |
| `name` | 本地名称表 | `data/stock_names.json` > 内置表 > `股票{code}`（服务不提供名称） |
| `market` | `data.market` | `sh→上海`、`sz→深圳`、`bj→北京`（沿用原中文契约） |
| `industry` / `type` | — | 固定 `""`（等同原 Baostock 缺字段表现） |
| `bars` / `first_date` / `last_date` | 原样 | 新增可选键，旧消费方不受影响 |

### 3.3 代码归一化（关键修正）

显式前缀优先；无前缀按首位数字推导，**绝不把裸代码交给服务端**：

| 首位 | 市场 | 示例 |
|---|---|---|
| `6` / `9`（`92` 除外） | sh | `600000 → sh600000` |
| `92` | bj | `920002 → bj920002` |
| `0` / `2` / `3` | sz | `000001 → sz000001` |
| `4` / `8` | bj | `830799 → bj830799` |
| 其它 | sz | 兜底，与旧实现一致 |

> 服务端无前缀时按 `sh→sz→bj` 探测，裸 `000001` 会命中**上证指数**。实测带前缀后 `000001` 正确落到深市平安银行（`bars=8478`, `first_date=1991-04-03`）。

## 4. 异常处理策略

| 场景 | 判定 | 策略 | 对外表现 |
|---|---|---|---|
| 连接失败 / DNS | `ConnectionError` | 重试 1 次（0.2s 退避）→ `MarketDataSourceUnavailable` | `info=None`、`bars=[]`，ERROR 日志含 URL |
| 超时 | 连接 3s / 读 10s（`KRONOS_TDX_*` 可调） | 同上（GET 幂等） | 同上 |
| `40401` 证券不存在 | HTTP 404 + 信封 code | 不重试，INFO | `info=None`、`bars=[]` |
| `40402` 区间无数据 | 同上 | 不重试；`get_stock_data` 转 offset 尾部兜底；区间查询直接 `[]` | `[]`（非异常） |
| `40001` 参数非法 | HTTP 400 | 不重试，WARNING（归一化后不应出现） | `[]` |
| `50001` 内部错误 | HTTP 500 | 重试 1 次 → 仍失败抛不可用 | `[]` |
| `50301` 目录不可用 | HTTP 503 | 探活告警，不阻塞起服 | 数据接口自然降级 |
| 非 JSON / 缺 `code` | `ValueError` / 结构校验 | 抛 `MarketDataSourceError` | `[]` |
| 行级脏数据 | 逐行 try/except | 丢该行 + WARNING 计数 | 返回其余有效行 |
| 数据陈旧（末根早于区间） | 区间查询命中 `40402` | 转 `offset = bars - N` 取"最近 N 根" | 正常返回历史 |
| 条数不足 `days` | `len < days` | 有多少返多少，由调用方判 `len<30` | `prediction_service` 报数据不足 |
| 全源失败 | 链遍历完 | 默认返回空，**不造数** | 上层 404，而非假数据出预测 |

**默认关闭合成数据**：旧 `_generate_fallback_data` 保留但仅当 `KRONOS_ALLOW_SYNTHETIC_FALLBACK=true` 生效，避免"假行情算真预测"。

## 5. 兼容性保底

| 级别 | 开关 | 行为 |
|---|---|---|
| 1（默认） | `KRONOS_MARKET_SOURCE_CHAIN=tdx_local` | 真实数据 |
| 2（回滚） | `KRONOS_MARKET_SOURCE_CHAIN=tdx_local,baostock` + `pip install baostock==0.8.9` | TDX 不可用自动降级 Baostock |
| 3（演示） | `KRONOS_ALLOW_SYNTHETIC_FALLBACK=true` | 合成数据兜底 |

回滚步骤（无需改代码）：改环境变量 → 重启 backend。若需完全退回旧实现，`stock_service.py` 的公共方法签名未变，替换数据源链即可。

配置项（全部支持环境变量）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `KRONOS_MARKET_SOURCE_CHAIN` | `tdx_local` | 数据源优先级链 |
| `KRONOS_TDX_BASE_URL` | `http://127.0.0.1:8010` | 服务地址（**宿主 8010，非 8000**） |
| `KRONOS_TDX_API_PREFIX` | `/api/v1` | 路由前缀 |
| `KRONOS_TDX_TIMEOUT` / `_CONNECT_TIMEOUT` | `10` / `3` | 秒 |
| `KRONOS_TDX_MAX_RETRIES` | `1` | 网络/5xx 重试次数 |
| `KRONOS_TDX_PAGE_LIMIT` | `5000` | 单页条数上限 |
| `KRONOS_MARKET_CACHE_TTL` | `300` | 内存缓存秒数 |
| `KRONOS_ALLOW_SYNTHETIC_FALLBACK` | `false` | 是否允许合成数据 |
| `KRONOS_STOCK_NAMES_FILE` | `backend/data/stock_names.json` | 名称映射 |

## 6. 验证方式与结果

### 6.1 单元测试（不依赖网络）

```bash
cd backend && pytest tests -q      # 42 passed in 1.17s
```

覆盖：代码归一化 10 组 / 非法输入 6 组、字段映射与类型、`amount` 不透传、字符串价格、`volume=None`、坏价格抛错、日期区间参数、offset 尾部兜底、分页（2 页）、`40401` 不重试、`40001`、5xx 重试成功、重试耗尽、超时、连接失败、非 JSON、坏信封、脏行丢弃、探活、门面契约、市场中文名、名称兜底、全源不可用降级、链降级、合成数据开关、缓存 TTL/清理、`validate_stock_code` 不变。

### 6.2 真实服务联调

```bash
python backend/scripts/verify_tdx_migration.py     # 14/14 通过
```

| # | 场景 | 实测结果 |
|---|---|---|
| 0 | 服务探活 | `{'status':'ok','tdx_home':'/data','vipdoc_exists':True}` |
| 1 | 元信息映射 | `600000` → 上海/浦发银行，`bars=6414`，`industry=""` |
| 2 | 最近 5 日 | 5 条 `2026-10-21~2026-10-27`，`close=9.82` |
| 3 | 最近 60 日（预测输入） | 60 条 `2026-07-28~2026-10-27` |
| 4 | 跨市场同码 | `000001` → 深圳/平安银行（非上证指数） |
| 5 | 区间查询 | 5 条，与请求区间一致 |
| 6 | 空区间 | `[]`，无异常 |
| 7 | 不存在证券 `600001` | `info=None`，`bars=0` |
| 8 | 非法代码 `abc` | `info=None`，不崩 |
| 9 | 服务不可用（错误端口） | `[]`，耗时 2.01s |
| 10 | 快速失败 | 2.01s < 5s 阈值 |
| 11 | 缓存命中 | 首次 1 次请求，二次新增 0 次 |
| 12 | 合成数据默认关闭 | `allow_synthetic_fallback=False` |
| 13 | 模型输入兼容 | `pd.DataFrame` 装配 60 行，时间戳单调递增 |

### 6.3 契约一致性

| 检查项 | 旧实现（Baostock） | 新实现（TDX） | 一致 |
|---|---|---|---|
| 日线键集合 | `date,open,high,low,close,volume` | 同 | ✅ |
| `date` 类型 | `str`（`YYYY-MM-DD`） | `str` | ✅ |
| 排序 | 升序 | 升序 | ✅ |
| `market` 取值 | `上海/深圳` | `上海/深圳/北京` | ✅ 超集 |
| `get_stock_data` 语义 | 最近 N 个交易日 | 最近 N 根（区间优先 + offset 兜底） | ✅ |
| 失败返回 | 合成数据（静默） | `[]` / `None`（默认） + 开关可恢复旧行为 | ⚠ 见 §7 |

## 7. 已知限制

1. **证券名称**：TDX 服务无名称字段，未收录代码显示 `股票{code}`。内置 9 条常用名（含 `sh:000001` 上证指数歧义处理）；可向 `backend/data/stock_names.json` 注入 `{"600000":"浦发银行"}` 生效，无需改代码。
2. **不返回 `amount`**：源 float32 精度不足；模型侧已在 `kronos.py` 缺列时按 `volume × 均价` 自算，不影响。
3. **`validate_stock_code` 未扩展**：北交所代码仍被前置拦截（保持原行为）。若需支持，另行评估。
4. **失败不再静默造数**：这是与旧实现唯一的行为差异，属有意修正；如需旧行为，设 `KRONOS_ALLOW_SYNTHETIC_FALLBACK=true`。
5. **未做端到端 `/predict` 联调**：本机环境无 `torch`，模型侧无法加载；已验证其唯一数据依赖（≥30 条 OHLC + 可解析日期）成立。
6. **仓库未初始化 Git**：`H:\AIcoding\WorkBuddy\kronos-ai` 当前不是 git 仓库，本次改动未提交。如需纳入 Git Flow，需先确认是否 `git init`。

## 8. 代码评审记录

| 级别 | 问题 | 处理 |
|---|---|---|
| Critical | 无 | — |
| Major | 裸代码 `000001` 会被服务端解析为上证指数 | 已通过前缀推导修正，并有专项用例与联调断言 |
| Major | 旧逻辑失败时返回随机合成行情，污染预测 | 默认关闭，改为显式空返回 + 开关保留 |
| Minor | `_TRANSIENT` 哨兵定义在类后 | 已前移至模块常量区 |
| Minor | `stock_service` 存在未使用导入 | 已清理 |
| Minor | 缓存无 TTL，日终数据不刷新 | 已加 TTL（默认 300s） |
| 建议 | `app/services/__init__.py` 强依赖 torch，数据层无法单独导入 | 本次以测试/脚本内轻量占位规避，建议后续改为惰性导入 |
