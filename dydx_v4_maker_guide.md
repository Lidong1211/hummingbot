# dYdX v4 永续合约做市机器人部署与使用文档

本文档详细介绍了如何在本地和 Docker 环境下部署并运行基于 Hummingbot 的 **dYdX v4 永续合约做市机器人（Perpetual Market Making）**，包括做市策略原理、底层接口交互机制、配置文件详解以及常见问题处理。

---

## 目录
1. [项目与策略概述](#1-项目与策略概述)
2. [dYdX v4 连接器与接口架构](#2-dydx-v4-连接器与接口架构)
3. [环境要求与网络配置](#3-环境要求与网络配置)
4. [本地环境部署与运行](#4-本地环境部署与运行)
5. [Docker 环境部署与运行](#5-docker-环境部署与运行)
6. [配置文件详解](#6-配置文件详解)
7. [日常运维与状态监控](#7-日常运维与状态监控)
8. [常见问题与排查 (FAQ)](#8-常见问题与排查-faq)

---

## 1. 项目与策略概述

### 1.1 永续合约做市策略原理 (`perpetual_market_making`)
永续合约做市策略的核心逻辑是在指定交易对的订单簿两侧持续挂出买单（Bid）和卖单（Ask），赚取买卖价差（Spread）。

- **挂单网格（Multi-levels）**：支持单档或多档阶梯挂单（如双边各 5 档，以一定的价差和数量步长向外铺单）。
- **挂单刷新（Order Refresh）**：根据设定的时间间隔（`order_refresh_time`）和价格变动容忍阈值（`order_refresh_tolerance_pct`）动态撤单重挂。
- **成交后延迟（Filled Order Delay）**：单边订单完全成交后，暂停一定时间再重新补单，防止行情剧烈波动时被连续单边吃单。
- **仓位管理与风控（Risk Management）**：
  - **动态止盈（Profit Taking）**：持有多头/空头仓位达到指定盈利点（`long/short_profit_taking_spread`）时，主动挂减仓平仓单。
  - **动态止损（Stop Loss）**：亏损达到指定比例（`stop_loss_spread`）时自动市价/限价滑点平仓止损。
  - **价格上下限（Price Ceiling & Floor）**：超出价格保护区间后限制单边挂单。

---

## 2. dYdX v4 连接器与接口架构

dYdX v4 基于 Cosmos-SDK（dYdX Chain），Hummingbot 的连接器（`dydx_v4_perpetual`）采用 **混合通信架构**：

```
+-------------------------------------------------------------+
|                      Hummingbot Core                        |
+------------------------------+------------------------------+
                               |
       +-----------------------+-----------------------+
       | (REST / WebSocket)                            | (gRPC / Cosmos Tx)
       v                                               v
+-----------------------------+                 +-----------------------------+
|     dYdX Indexer API        |                 |   dYdX Node (Validator)     |
| (行情/订单簿/账户历史/WS推送) |                 |    (gRPC 交易广播与账户查询)  |
+-----------------------------+                 +-----------------------------+
```

### 2.1 核心接口与通道定义
- **Indexer REST / WS 接口**：
  - `GET /v4/perpetualMarkets`: 获取交易对规格、最小变动价位、杠杆规则等。
  - `GET /v4/orderbooks/perpetualMarket`: 订单簿快照。
  - `GET /v4/time`: 服务器时间同步。
  - `WS v4_orderbook / v4_trades`: 实时订单簿深度与逐笔成交推送。
  - `WS v4_subaccounts`: 账户持仓、保证金、成交更新推送。
- **Validator gRPC 接口（链上交易交互）**：
  - **查询接口**：`cosmos.auth.v1beta1.QueryStub`（查询链上 Account Number 与 Sequence 序列号）。
  - **交易广播**：`cosmos.tx.v1beta1.ServiceStub.BroadcastTx`（同步广播已签名的挂单/撤单交易）。
  - **数据封装**：
    - 挂单：`dydxprotocol.clob.tx_pb2.MsgPlaceOrder`（短效订单 Short-Term Order 默认有效期约 20 个区块）。
    - 撤单：`dydxprotocol.clob.tx_pb2.MsgCancelOrder`。

---

## 3. 环境要求与网络配置

### 3.1 网络与节点配置（常量文件：`dydx_v4_perpetual_constants.py`）
根据实际环境（本地私有链节点 vs 官方测试网 vs 主网），确认以下节点配置：

```python
# hummingbot/connector/derivative/dydx_v4_perpetual/dydx_v4_perpetual_constants.py

# gRPC 节点 (用于签名广播交易与 Sequence 账户查询)
DYDX_V4_AERIAL_CONFIG_URL = '127.0.0.1:9090'        # 本地节点常用 9090，主网可配对应 gRPC 端口
DYDX_V4_QUERY_AERIAL_CONFIG_URL = '127.0.0.1:9090'
DYDX_V4_GRPC_INSECURE = True                        # 本地/私网 plaintext 设为 True；主网开启 TLS 设为 False
CHAIN_ID = 'localdydxprotocol'                      # 链 ID (主网为 dydx-mainnet-1)

# Indexer 与 WebSocket 地址
DYDX_V4_INDEXER_REST_BASE_URL = "http://127.0.0.1:3002"
DYDX_V4_WS_URL = "ws://127.0.0.1:3003/v4/ws"
```

---

## 4. 本地环境部署与运行

### 4.1 依赖安装与编译

1. **环境准备（Conda 环境）**
   ```bash
   # 安装 Conda 依赖并编译 C/Cython 拓展
   make install
   
   # 或者针对 dYdX 特殊依赖环境：
   make install DYDX=1
   ```

2. **激活 Conda 环境**
   ```bash
   conda activate hummingbot
   ```

3. **编译 Cython 扩展模块（如修改过策略/连接器 Cython 代码）**
   ```bash
   python setup.py build_ext --inplace
   ```

### 4.2 配置连接器与 API 凭证
在 `conf/connectors/dydx_v4_perpetual.yml` 中配置钱包助记词与链上地址：

```yaml
dydx_v4_perpetual_secret_phrase: "your twelve or twenty four word mnemonic phrase ..."
dydx_v4_perpetual_chain_address: "dydx1..."
```

### 4.3 启动运行

**方式 A：通过 Quickstart 脚本快速启动（推荐后台/自动化）**
```bash
./bin/hummingbot_quickstart.py --config dydx_ddt_usd.yml --wallet-password "your_password"
```

**方式 B：通过 CLI 交互式客户端启动**
```bash
bin/hummingbot.py
```
在客户端控制台中：
```text
connect dydx_v4_perpetual
import dydx_ddt_usd.yml
start
```

---

## 5. Docker 环境部署与运行

### 5.1 构建 Docker 镜像
```bash
docker build -t hummingbot/hummingbot:latest -f Dockerfile .
```

### 5.2 使用 Docker Compose 运行
项目已提供 `docker-compose.yml`，可以通过卷挂载方式直接复用本地的配置文件、策略和日志目录。

```bash
# 启动容器
docker compose up -d

# 查看运行日志
docker compose logs -f hummingbot

# 进入 CLI 交互控制台
docker attach hummingbot
```

### 5.3 独立容器运行（直接执行指定策略）
```bash
docker run -it --rm \
  --name dydx_maker \
  --network host \
  -v $(pwd)/conf:/home/hummingbot/conf \
  -v $(pwd)/logs:/home/hummingbot/logs \
  -v $(pwd)/data:/home/hummingbot/data \
  hummingbot/hummingbot:latest \
  ./bin/hummingbot_quickstart.py --config conf_dydx_v4_perp_mm.yml --wallet-password "your_password"
```

---

## 6. 配置文件详解

### 6.1 策略配置文件模板 (`conf/strategies/conf_dydx_v4_perp_mm.yml`)

```yaml
template_version: 6
strategy: perpetual_market_making

# 1. 交易连接器与市场标的
derivative: dydx_v4_perpetual
market: ETH-USD                     # 交易标的 (如 ETH-USD, DDT-USD)

# 2. 杠杆与仓位模式
leverage: 5                         # 杠杆倍数
position_mode: One-way              # 仓位模式 (One-way 单向持仓)

# 3. 基础挂单价差与网格配置
bid_spread: 0.3                     # 第一档买单距离中值价的百分比 (0.3%)
ask_spread: 0.3                     # 第一档卖单距离中值价的百分比 (0.3%)
order_levels: 5                     # 双边挂单档位数 (总计 10 笔订单)
order_level_spread: 0.3             # 随后每档阶梯递增价差 (0.3%)
order_level_amount: 0.0             # 随后每档数量递增量 (0 表示每档数量相同)
order_amount: 0.006                 # 基础每档挂单数量

# 4. 挂单刷新机制
order_refresh_time: 30.0            # 挂单刷新周期 (秒)
order_refresh_tolerance_pct: 0.1   # 价格变动容忍度 (变动小于 0.1% 不撤销旧单)
filled_order_delay: 10.0            # 订单完全成交后，重新铺单的等待时间 (秒)

# 5. 仓位止盈止损与风控保护
stop_loss_spread: 2.0               # 仓位亏损 2.0% 时触发止损
stop_loss_slippage_buffer: 0.5      # 止损单滑点容忍百分比 (0.5%)
time_between_stop_loss_orders: 60.0 # 止损单未成交时的重试间隔 (秒)
long_profit_taking_spread: 1.5      # 多单盈利 1.5% 时主动挂减仓单止盈
short_profit_taking_spread: 1.5     # 空单盈利 1.5% 时主动挂减仓单止盈

# 6. 价格上下限过滤
price_ceiling: -1.0                 # 做市上限价格 (-1.0 表示不启用)
price_floor: -1.0                   # 做市下限价格 (-1.0 表示不启用)

# 7. 价格源与深度优化
order_optimization_enabled: false   # 是否启用抢一档 (Jump Order Book)
price_source: current_market        # 价格定价基准 (当前市场订单簿)
price_type: mid_price               # 定价点 (中值价 mid_price / last_price)
```

---

## 7. 日常运维与状态监控

### 7.1 CLI 常用指令
- `status`：查看当前策略运行状态、订单簿价差、挂单详情、当前持仓与盈亏。
- `history`：查看历史成交记录、做市收益与手续费支出。
- `config`：查看或在线调整策略参数。
- `stop`：优雅停止策略并自动撤回盘口所有活跃挂单。

### 7.2 日志排查
所有日志默认保存在 `./logs/` 目录下：
- `logs/logs_conf_dydx_v4_perp_mm.log`：策略主要生命周期与订单状态日志。
- `logs/hummingbot_quickstart.log`：启动器日志。

---

## 8. 常见问题与排查 (FAQ)

### Q1: 提示 `account sequence mismatch` 错误？
- **原因**：Cosmos 链上交易需要严格按 Sequence 递增执行。如果本地并发广播或在外部钱包进行了交易，会导致 Sequence 不一致。
- **机制**：连接器在 `dydx_v4_data_source.py` 中实现了自动检测机制。一旦检测到 Sequence 不匹配，会自动触发 `initialize_trading_account()` 重新查询最新链上状态并自愈。

### Q2: 报错 `Stateful order does not exist`？
- **原因**：dYdX 短效订单（Short-term Orders）有效期默认受限于区块高度（通常 20 个区块后自动由链上丢弃/过期）。
- **处理**：撤单时若订单已在链上失效并被丢弃，连接器会捕获该错误并视为已取消状态，属正常现象。

### Q3: 为什么挂单量被拒绝 / 提示精度错误？
- **原因**：dYdX v4 针对不同交易对有严格的 `stepBaseQuantums`（最小数量步长）和 `subticksPerTick`（最小价格步长）。
- **排查**：检查 `order_amount` 是否低于标的允许的最小下单量，以及保证金是否满足维持杠杆要求。
