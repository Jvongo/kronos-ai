# Kronos A股预测分析系统

基于Kronos金融大模型的A股日线预测分析系统

> **项目来源**：本项目基于 [raydez/kronos-ai](https://github.com/raydez/kronos-ai) 二次开发。
> **数据源**：行情数据已由 Baostock 替换为本地部署的 [Jvongo/tdx-local-api](https://github.com/Jvongo/tdx-local-api)（通达信本地行情 HTTP 服务），详见 [数据源改造说明](#-数据源改造说明)。

## 🎯 项目概述

本项目是一个基于Kronos金融大模型的A股股票预测分析系统，提供智能的股票走势预测功能。系统采用前后端分离架构，后端使用FastAPI构建RESTful API，前端使用现代化的Web界面。

## ✨ 核心功能

- 📊 **股票预测**: 基于Kronos模型的智能股票价格预测
- 📈 **多时间维度**: 支持3-10天的多维度预测
- 🔄 **实时数据**: 对接本地 TDX 行情服务（离线、只读）获取日线数据
- 🎨 **可视化界面**: 直观的Web界面展示预测结果
- 🔀 **模型切换**: 支持在不同Kronos模型间灵活切换（mini/small/base）
- 💾 **智能缓存**: 自动检测本地模型，按需下载
- 🚀 **高性能**: 异步处理，支持并发请求
- 📱 **响应式设计**: 适配各种设备屏幕

## 🏗️ 系统架构

```
kronos-ai/
├── backend/                          # 后端服务
│   ├── app/
│   │   ├── services/                 # 业务逻辑服务
│   │   │   ├── kronos_integration.py    # Kronos模型集成（加载/卸载/预测）
│   │   │   ├── model_manager.py         # 模型管理器（单例，支持切换）
│   │   │   ├── prediction_service.py    # 预测服务
│   │   │   └── stock_service.py         # 股票数据服务
│   │   └── utils/                    # 工具函数
│   ├── model/                        # Kronos模型定义
│   │   ├── kronos.py                 # Kronos模型实现
│   │   └── module.py                 # 模型模块
│   ├── main.py                       # FastAPI主应用
│   ├── config.py                     # 配置文件
│   ├── requirements.txt              # Python依赖
│   ├── Dockerfile                    # Docker配置
├── frontend/                         # 前端应用（React + TypeScript）
│   ├── src/
│   │   ├── components/              # React组件
│   │   │   ├── KLineChart.tsx          # K线图组件
│   │   │   ├── ModelStatus.tsx         # 模型状态和切换组件
│   │   │   ├── PlotlyKLineChart.tsx    # Plotly K线图
│   │   │   ├── PredictionForm.tsx      # 预测表单
│   │   │   └── PredictionTable.tsx     # 预测结果表格
│   │   ├── services/
│   │   │   └── api.ts               # API调用封装
│   │   ├── types/
│   │   │   └── index.ts             # TypeScript类型定义
│   │   ├── App.tsx                  # 主应用组件
│   │   ├── App.css
│   │   ├── index.tsx                # 入口文件
│   │   └── index.css
│   ├── package.json                 # npm依赖
│   ├── tsconfig.json                # TypeScript配置
│   ├── Dockerfile                   # Docker配置
├── docker-compose.yml               # Docker Compose配置
├── docker-start.sh                  # Docker启动脚本
├── docker-stop.sh                   # Docker停止脚本
├── start.sh                         # 启动脚本
├── stop.sh                          # 停止脚本
├── quick-start.sh                   # 快速启动脚本
└── README.md                        # 项目说明
```

### 核心模块说明

**后端核心模块**：
- `kronos_integration.py`: Kronos模型的底层集成，处理模型加载、卸载、预测等操作
- `model_manager.py`: 模型管理器（单例模式），提供统一的模型访问接口，支持模型切换
- `prediction_service.py`: 预测服务，协调股票数据和模型预测
- `stock_service.py`: 股票数据服务门面，数据源适配器见 `app/services/market_data/`（默认 TDX 本地服务）

**前端核心组件**：
- `ModelStatus.tsx`: 模型状态展示和切换界面，支持查看当前模型、切换模型、重新加载
- `PredictionForm.tsx`: 股票预测表单，用户输入股票代码和预测天数
- `KLineChart.tsx`: K线图可视化组件
- `api.ts`: 封装所有后端API调用

## 🚀 快速开始

### 环境要求

- Python 3.11+
- Node.js 14+ (可选，用于前端开发)
- macOS/Linux/Windows

### 安装步骤

1. **克隆项目**
```bash
git clone https://github.com/raydez/kronos-ai.git
cd kronos-ai
```

2. **设置后端环境**
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

3. **启动系统**
```bash
# 返回项目根目录
cd ..
# 使用启动脚本
./start.sh
```

或者手动启动：
```bash
# 启动后端
cd backend
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python main.py

# 启动前端（新终端）
cd frontend
python3 -m http.server 3000
```

4. **访问应用**
- 前端界面: http://localhost:3000
- API文档: http://localhost:8000/docs
- 健康检查: http://localhost:8000/health

### 停止系统

```bash
./stop.sh
```

## 📡 API接口

### 核心接口

| 接口 | 方法 | 描述 |
|------|------|------|
| `/predict` | POST | 股票预测 |
| `/stock/{code}` | GET | 获取股票信息 |
| `/stock/{code}/history` | GET | 获取历史数据 |
| `/batch-predict` | POST | 批量预测 |
| `/model/info` | GET | 获取模型信息 |
| `/model/available` | GET | 获取可用模型列表 |
| `/model/reload` | POST | 重新加载当前模型 |
| `/model/switch` | POST | 切换到指定模型 |
| `/health` | GET | 健康检查 |

### 请求示例

**股票预测**
```bash
curl -X POST "http://localhost:8000/predict" \
     -H "Content-Type: application/json" \
     -d '{"code": "600000", "prediction_days": 5}'
```

**获取股票信息**
```bash
curl -X GET "http://localhost:8000/stock/600000"
```

**获取可用模型列表**
```bash
curl -X GET "http://localhost:8000/model/available"
```

**切换模型**
```bash
curl -X POST "http://localhost:8000/model/switch" \
     -H "Content-Type: application/json" \
     -d '{"model_name": "kronos-base"}'
```

**重新加载模型**
```bash
curl -X POST "http://localhost:8000/model/reload"
```

## 🔧 技术栈

### 后端
- **FastAPI**: 高性能Web框架
- **Pydantic**: 数据验证和序列化
- **Pandas**: 数据处理
- **TDX 本地行情服务**: 股票数据源（HTTP，默认 `http://127.0.0.1:8010`）
- **Uvicorn**: ASGI服务器

### 前端
- **HTML5/CSS3/JavaScript**: 现代Web技术
- **响应式设计**: 适配各种设备

### 数据源
- **TDX 本地行情服务**: 主要股票数据源（[Jvongo/tdx-local-api](https://github.com/Jvongo/tdx-local-api)，`/api/v1`，默认 `http://127.0.0.1:8010`）
- **原数据源 Baostock**: 已停用，仅保留适配器作为回滚通道（默认不加载）

## 🔌 数据源改造说明

本章节记录本项目相对上游仓库 [raydez/kronos-ai](https://github.com/raydez/kronos-ai) 在行情数据层所做的替换与引入。

### 来源与对接对象

| 项 | 地址 / 说明 |
|---|---|
| 上游项目（二次开发基线） | <https://github.com/raydez/kronos-ai> |
| 本次采用的数据源项目 | <https://github.com/Jvongo/tdx-local-api> |
| 数据源形态 | 本地部署的 HTTP 服务，只读解析通达信 `vipdoc/**/lday/*.day`，无外网访问 |
| 接口基址 | `http://127.0.0.1:8010/api/v1`（容器内走 `http://host.docker.internal:8010`） |
| 接口文档 | 服务自带 Swagger：`http://127.0.0.1:8010/docs` |

### 替换内容

1. **停用 Baostock**：`requirements.txt` 移除 `baostock`，改引入 `requests`；`config.py` 的 `DATA_SOURCE` 由 `baostock` 改为 `tdx_local`。
2. **新增数据源抽象层** `backend/app/services/market_data/`：

| 文件 | 职责 |
|---|---|
| `base.py` | `MarketDataSource` 抽象接口 + 异常体系（不存在/区间无数据/不可用/代码非法） |
| `code_utils.py` | 证券代码归一化与市场判定（`sh/sz/bj` 前缀推导） |
| `tdx_local.py` | TDX 适配器：HTTP 调用、统一信封解析、分页、超时/5xx 重试、字段映射 |
| `legacy_baostock.py` | 旧数据源适配器（默认不加载，仅回滚用） |
| `settings.py` | 环境变量配置装载 |
| `__init__.py` | `build_source_chain()` 数据源链工厂 |

3. **`stock_service.py` 重写为门面层**：迁移阶段公共方法（`get_stock_info` / `get_stock_data` / `get_stock_data_for_dates` / `validate_stock_code` / `clear_cache`）签名与返回结构保持不变，调用方无需改动；后续为支持回测新增了 `get_history_ending_before()` 与 `get_trading_days()`，相关接口与前端配套调整见 [兼容性配套改动](#兼容性配套改动)。
4. **引入证券名称映射**：TDX 接口不返回名称，新增 `backend/data/stock_names.json`（18902 条），由 `backend/scripts/build_stock_names.py` 解析本地 `T0002/hq_cache/{shs,szs,bjs}.tnf` 生成；可预测代码覆盖率约 98.5%，未收录的回落为 `股票{code}`。
5. **新增验证资产**：`backend/tests/`（51 个用例，注入假 HTTP 客户端，不依赖网络）与 `backend/scripts/verify_tdx_migration.py`（对真实服务跑 15 个场景）。
6. **交易日历**：新增 `StockService.get_trading_days()`，以 `sh000001` 真实日线推导交易日，预测日期不再使用「只跳周末」的 `freq='B'`，国庆等休市日不会被生成。

### 接口与字段映射

| StockService 方法 | 对应 TDX 接口 |
|---|---|
| `get_stock_info(code)` | `GET /securities/{code}` |
| `get_stock_data(code, days)` | `GET /kline/daily`（闭区间 → 不足时按 `offset` 取尾部） |
| `get_stock_data_for_dates(code, start, end)` | `GET /kline/daily`（闭区间 + 分页） |
| `get_history_ending_before(code, end, days)` | 同上，窗口截止到指定日期之前（回测用） |

日线字段映射（返回给上层的结构保持不变）：

| 目标字段 | 类型 | 源字段 | 转换规则 |
|---|---|---|---|
| `date` | `str` | `items[].date` | 原样 `YYYY-MM-DD` |
| `open/high/low/close` | `float` | 同名 | `float()`；缺失或非法则丢弃该行 |
| `volume` | `int` | `items[].volume`（股） | `int()`；缺失按 `0`，不丢行 |
| ~~`amount`~~ | — | `items[].amount` | **不透传**：源为 float32，十亿级误差约 ±256 元 |

证券代码规则：显式前缀优先，无前缀按首位数字推导（`6/9→sh`、`0/2/3→sz`、`92/4/8→bj`）。**必须带前缀**——服务端无前缀时按 `sh→sz→bj` 探测，裸 `000001` 会命中上证指数而非平安银行。

### 异常处理与降级

| 场景 | 处理策略 | 对外表现 |
|---|---|---|
| 连接失败 / 超时 | 重试 1 次（可配），仍失败抛「数据源不可用」 | `info=None`、K 线 `[]` |
| `40401` 证券不存在 | 不重试 | `info=None`、`[]` |
| `40402` 区间无数据 | 不重试；`get_stock_data` 转 `offset` 取尾部 | `[]` |
| `40001` 参数非法 | 不重试，记录告警 | `[]` |
| `50001` / `50301` / 5xx | 重试后仍失败视为不可用 | `[]` |
| 响应非 JSON / 信封缺失 | 视为数据源异常 | `[]` |
| 行级脏数据 | 逐行丢弃并计数 | 返回其余有效行 |
| 全部数据源失败 | **不静默造数**，返回空 | 上层 404；如需合成兜底可显式开启开关 |

数据源降级链（三级，全部通过环境变量切换，无需改代码）：

```bash
# 1. 默认：本地 TDX 服务
KRONOS_MARKET_SOURCE_CHAIN=tdx_local

# 2. 回滚：TDX 不可用时降级到 Baostock（需自行 pip install baostock==0.8.9）
KRONOS_MARKET_SOURCE_CHAIN=tdx_local,baostock

# 3. 演示：允许合成行情兜底（默认关闭，避免"假数据出真预测"）
KRONOS_ALLOW_SYNTHETIC_FALLBACK=true
```

### 配置项

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `KRONOS_MARKET_SOURCE_CHAIN` | `tdx_local` | 数据源优先级链 |
| `KRONOS_TDX_BASE_URL` | `http://127.0.0.1:8010` | 服务地址（容器内用 `host.docker.internal`） |
| `KRONOS_TDX_API_PREFIX` | `/api/v1` | 路由前缀 |
| `KRONOS_TDX_TIMEOUT` / `_CONNECT_TIMEOUT` | `10` / `3` | 读 / 连接超时（秒） |
| `KRONOS_TDX_MAX_RETRIES` | `1` | 网络与 5xx 重试次数 |
| `KRONOS_TDX_PAGE_LIMIT` | `5000` | 单页条数上限 |
| `KRONOS_MARKET_CACHE_TTL` | `300` | 内存缓存有效期（秒） |
| `KRONOS_ALLOW_SYNTHETIC_FALLBACK` | `false` | 是否允许合成数据兜底 |
| `KRONOS_STOCK_NAMES_FILE` | `backend/data/stock_names.json` | 证券名称映射 |
| `KRONOS_MARKET_HOLIDAYS_FILE` | `backend/data/market_holidays.json` | 未来休市日（可选，超出本地数据范围时使用） |

### 启动数据源服务

数据源需独立部署，本项目通过 HTTP 调用：

```bash
# 参考 https://github.com/Jvongo/tdx-local-api 的说明启动（示例为 Docker）
docker run -d --name tdx-local-api -p 8010:8000 \
  -v /path/to/new_tdx:/data:ro \
  tdx-local-api

# 验证
curl -s http://127.0.0.1:8010/api/v1/health
```

### 兼容性配套改动

| 改动 | 说明 |
|---|---|
| `/stock/{code}/history` 支持 `end_date` | 指定后返回该日期之前的最近 N 根，回测时历史线不再因起始日过早而变空 |
| 预测输入窗口按起始日截断 | 填了「开始预测日期」时，模型输入截止到该日之前，避免「数值属于未来、日期贴在早期」的虚假跳空 |
| 预测日期使用真实交易日 | 由 `get_trading_days()` 生成，跳过周末与节假日 |

### 验证方式

```bash
# 单元测试（不依赖网络与服务）
cd backend && pytest tests -q        # 51 passed

# 对真实服务跑 15 个场景
python backend/scripts/verify_tdx_migration.py

# 重建名称映射（数据更新后）
python backend/scripts/build_stock_names.py
```

完整说明见 [`docs/market-data-migration.md`](docs/market-data-migration.md)（迁移报告）与 [`docs/design-tdx-market-data.md`](docs/design-tdx-market-data.md)（设计文档）。

## 📊 预测模型

### 可用模型

系统支持3个不同规格的Kronos模型，可根据需求灵活切换：

| 模型名称 | 参数规模 | 上下文长度 | 特点 | 适用场景 |
|---------|---------|-----------|------|---------|
| **kronos-mini** | 4.1M | 2048 | 轻量快速 | 快速预测、资源受限环境 |
| **kronos-small** | 24.7M | 512 | 平衡性能 | 日常使用（默认） |
| **kronos-base** | 85.6M | 1024 | 高精度 | 深度分析、精确预测 |

### 模型切换

**通过Web界面切换**：
1. 访问前端界面
2. 在"模型状态"卡片点击"切换模型"按钮
3. 选择目标模型
4. 系统会自动：
   - 卸载当前模型释放内存
   - 检查本地是否有模型缓存
   - 如无缓存则自动从HuggingFace下载
   - 加载新模型并更新界面

**通过API切换**：
```bash
curl -X POST "http://localhost:8000/model/switch" \
     -H "Content-Type: application/json" \
     -d '{"model_name": "kronos-base"}'
```

### 模型缓存

- **缓存位置**: `~/.cache/huggingface/hub`
- **自动管理**: 系统会自动检测本地缓存，避免重复下载
- **按需下载**: 首次使用某个模型时自动下载
- **资源优化**: 切换模型时自动卸载旧模型，节省内存

### 预测特性
- 支持1-10天多维度预测
- 提供置信度评估
- 包含开盘、最高、最低、收盘价格
- 基于历史数据和技术指标
- 准确率随模型规模提升（mini: ~75%, small: ~85%, base: ~90%）

## 💡 使用指南

### 模型切换功能详解

#### 什么时候需要切换模型？

- **需要快速预测**：切换到 `kronos-mini`（4.1M），速度最快
- **日常使用**：使用默认的 `kronos-small`（24.7M），平衡性能
- **需要高精度**：切换到 `kronos-base`（85.6M），准确率最高

#### 切换流程

1. **查看当前模型**
   - Web界面：查看"模型状态"卡片中的"当前模型"
   - API：访问 `/model/info` 端点

2. **选择目标模型**
   - Web界面：点击"切换模型"按钮，从下拉列表选择
   - API：调用 `/model/switch` 接口

3. **等待切换完成**
   - 如果本地有缓存：通常只需几秒
   - 如果需要下载：
     - `kronos-mini`: 约需下载 5-10MB
     - `kronos-small`: 约需下载 25-50MB
     - `kronos-base`: 约需下载 80-150MB

4. **验证切换结果**
   - 查看成功提示消息
   - 确认新模型已加载

#### 注意事项

⚠️ **首次使用某个模型时**：
- 系统会从 HuggingFace Hub 下载模型
- 需要稳定的网络连接
- 下载时间取决于网络速度和模型大小

⚠️ **切换过程中**：
- 旧模型会被自动卸载以释放内存
- 预测服务会短暂不可用
- 建议在系统空闲时进行切换

✅ **推荐做法**：
- 首次部署时预先下载所有模型
- 根据实际需求选择合适的模型
- 在非业务高峰期进行模型切换

#### 离线使用

如果需要在离线环境使用，可以预先下载所有模型：

```bash
# 方法1：通过API依次切换所有模型（会自动下载）
curl -X POST "http://localhost:8000/model/switch" -H "Content-Type: application/json" -d '{"model_name": "kronos-mini"}'
curl -X POST "http://localhost:8000/model/switch" -H "Content-Type: application/json" -d '{"model_name": "kronos-small"}'
curl -X POST "http://localhost:8000/model/switch" -H "Content-Type: application/json" -d '{"model_name": "kronos-base"}'

# 方法2：手动下载到缓存目录
# 下载后放置到 ~/.cache/huggingface/hub/
```

## 🛠️ 开发指南

### 项目结构说明

- `backend/app/models/`: Pydantic数据模型定义
- `backend/app/services/`: 核心业务逻辑
  - `model_manager.py`: Kronos模型管理（单例模式，支持模型切换）
  - `kronos_integration.py`: Kronos模型集成（加载、卸载、预测）
  - `stock_service.py`: 行情数据服务门面（数据源编排、名称解析、交易日历、缓存）
  - `market_data/`: 数据源抽象层与适配器（`tdx_local` / `legacy_baostock`）
  - `prediction_service.py`: 预测服务
- `backend/model/`: Kronos模型定义
  - `kronos.py`: Kronos模型实现
  - `module.py`: 模型模块
- `backend/data/`: 运行期数据（`stock_names.json` 名称映射入库，其余内容由 `.gitignore` 忽略）
- `backend/scripts/`: 运维脚本（`build_stock_names.py` 名称映射生成、`verify_tdx_migration.py` 联调验证）
- `backend/tests/`: 数据层单元测试（注入假 HTTP 客户端，不依赖网络）
- `backend/main.py`: FastAPI应用主入口
- `docs/`: 数据源迁移报告与设计文档
- `frontend/`: Web前端界面
  - `src/components/ModelStatus.tsx`: 模型状态和切换组件
  - `src/services/api.ts`: API调用封装

### 添加新功能

1. 在相应的service中添加业务逻辑
2. 在models中定义数据模型
3. 在main.py中添加API端点
4. 更新前端界面

### 运行测试

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/
```

## 🚀 部署指南

### Docker部署

前后端由 `docker-compose.yml` 编排，行情服务需单独部署（见 [启动数据源服务](#启动数据源服务)）。

```bash
# 启动（首次会自动构建镜像）
docker compose up -d --build

# 查看状态
docker compose ps

# 停止
docker compose down
```

| 服务 | 宿主机端口 | 说明 |
|---|---|---|
| backend | 8000 | FastAPI，行情地址走 `host.docker.internal:8010` |
| frontend | 3000 | nginx 静态站点 |
| tdx-local-api | 8010 | 外部依赖，需自行部署 |

## 🤝 贡献指南

1. Fork项目
2. 创建功能分支
3. 提交更改
4. 推送到分支
5. 创建Pull Request

## 📄 许可证

本项目采用MIT许可证

## 🙏 致谢

- [raydez/kronos-ai](https://github.com/raydez/kronos-ai)：本项目基于该项目二次开发
- [Jvongo/tdx-local-api](https://github.com/Jvongo/tdx-local-api)：提供本地 TDX 行情服务（日线与证券数据）
- Kronos团队提供的金融大模型
- FastAPI社区的技术支持

## ❓ 常见问题（FAQ）

### Q1: 应用启动时模型加载失败怎么办？
**A**: 应用会正常启动，但预测功能不可用。可以：
1. 点击"重新加载"按钮尝试重新加载
2. 检查网络连接是否正常
3. 查看后端日志了解具体错误

### Q2: 模型下载很慢或失败怎么办？
**A**: 可能的原因和解决方案：
- **网络问题**: 检查网络连接，考虑使用代理
- **HuggingFace访问受限**: 配置 HuggingFace 镜像源
- **磁盘空间不足**: 清理磁盘空间（每个模型需要几十到几百MB）

### Q3: 如何查看模型是从本地加载还是从网络下载？
**A**: 切换模型成功后，会显示详细信息：
- "从本地缓存加载" - 使用本地已有的模型
- "已从HuggingFace下载: Tokenizer、模型" - 从网络下载

### Q4: 切换模型会影响正在进行的预测吗？
**A**: 是的。切换模型时：
- 当前模型会被卸载
- 预测服务短暂不可用
- 建议在系统空闲时切换

### Q5: 三个模型该如何选择？
**A**: 根据需求选择：
- **kronos-mini**: 资源受限、需要快速响应时使用
- **kronos-small**: 日常使用的默认选择，性能和准确率平衡
- **kronos-base**: 需要最高准确率时使用，但消耗更多资源

### Q6: 模型缓存占用多少磁盘空间？
**A**: 每个模型的大小：
- kronos-mini: ~5-10MB
- kronos-small: ~25-50MB  
- kronos-base: ~80-150MB

全部下载约占用 200-300MB 磁盘空间。

### Q7: 可以删除不用的模型吗？
**A**: 可以手动删除 `~/.cache/huggingface/hub/` 目录下的对应模型文件夹。下次使用时会重新下载。

### Q8: 切换模型后预测结果会不同吗？
**A**: 是的。不同模型的预测结果可能有差异：
- 参数更大的模型（base）通常更准确
- 参数较小的模型（mini）响应更快但可能略不准确

### Q9: 支持自定义模型吗？
**A**: 当前版本支持三个预设的 Kronos 模型。如需添加自定义模型，需要：
1. 在 `backend/app/services/kronos_integration.py` 中添加模型配置
2. 确保模型格式与 Kronos 兼容

### Q10: 如何配置 HuggingFace Token？
**A**: 如果模型需要认证访问：
```bash
# 设置环境变量
export HUGGINGFACE_TOKEN="your_token_here"

# 或在代码中配置
# backend/app/services/kronos_integration.py
```

---

**注意**: 本系统仅用于学习和研究目的，不构成投资建议。股票投资有风险，入市需谨慎。