# Orderly 合约做市机器人部署手册

> 基于 Hummingbot `feature_orderly` 分支，使用 `perpetual_market_making` 策略对接 Orderly Network 合约做市。

---

## 目录

1. [前置准备](#1-前置准备)
2. [Orderly 接口概览](#2-orderly-接口概览)
3. [认证方式](#3-认证方式)
4. [Connector 配置](#4-connector-配置)
5. [策略配置详解](#5-策略配置详解)
6. [本地部署（Conda）](#6-本地部署conda)
7. [Docker 部署](#7-docker-部署)
8. [启动与运行](#8-启动与运行)
9. [常见问题](#9-常见问题)

---

## 1. 前置准备

### 1.1 Orderly 账户注册

在进行做市之前，需要准备好以下凭证：

| 凭证 | 说明 |
|------|------|
| `account_id` | Orderly 账户 ID，通常是 EVM 钱包地址注册后生成的 hex 字符串 |
| `orderly_key` | ed25519 公钥，格式：`ed25519:BASE58_ENCODED_KEY` |
| `orderly_secret` | ed25519 私钥，格式：`ed25519:BASE58_ENCODED_KEY` |

**注册方式**：通过 [Orderly 官网](https://app.orderly.network) 连接 EVM 钱包，完成注册并生成 API Key。

### 1.2 充值 USDC

Orderly 合约的保证金币种为 **USDC**，请确保账户内有足够的 USDC 作为保证金。

---

## 2. Orderly 接口概览

### 2.1 环境地址

| 环境 | REST API | WebSocket (公共) | WebSocket (私有) |
|------|----------|------------------|------------------|
| **主网** | `https://api.orderly.org` | `wss://ws-evm.orderly.org/ws/stream` | `wss://ws-private-evm.orderly.org/v2/ws/private/stream` |
| **测试网** | `https://testnet-api.orderly.org` | `wss://testnet-ws-evm.orderly.org/ws/stream` | `wss://testnet-ws-private-evm.orderly.org/v2/ws/private/stream` |

### 2.2 公共接口（无需认证）

| 接口 | 路径 | 说明 |
|------|------|------|
| 市场信息 | `GET /v1/public/futures` | 所有合约行情、资金费率 |
| 交易规则 | `GET /v1/public/info` | 全部交易对参数（精度、最小量等） |
| 单交易对规则 | `GET /v1/public/info/{symbol}` | 指定 symbol 的交易规则 |
| 资金费率 | `GET /v1/public/funding_rates` | 全部合约当前资金费率 |
| 历史资金费率 | `GET /v1/public/funding_rate_history` | 历史资金费率记录 |
| 系统状态 | `GET /v1/public/system_info` | 健康检查 |

### 2.3 私有接口（需签名认证）

| 接口 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 订单簿 | GET | `/v1/orderbook/{symbol}` | 深度快照 |
| 下单 | POST | `/v1/order` | 创建单笔订单 |
| 批量下单 | POST | `/v1/batch-order` | 批量创建（1 req/s） |
| 撤单 | DELETE | `/v1/order` | 按 order_id 撤销 |
| 按客户端ID撤单 | DELETE | `/v1/client/order` | 按 client_order_id 撤销 |
| 批量撤单 | DELETE | `/v1/batch-order` | 批量撤销 |
| 全部撤单 | DELETE | `/v1/orders` | 撤销当前所有挂单 |
| 查询订单 | GET | `/v1/order/{order_id}` | 查询单笔订单状态 |
| 查询全部订单 | GET | `/v1/orders` | 列出订单 |
| 账户信息 | GET | `/v1/client/info` | 账户基本信息 |
| 账户余额 | GET | `/v1/client/holding` | 持仓余额 |
| 全部仓位 | GET | `/v1/positions` | 合约持仓 |
| 单仓位 | GET | `/v1/position/{symbol}` | 指定合约仓位 |
| 设置杠杆 | POST | `/v1/client/leverage` | 调整杠杆倍数 |
| 资金费历史 | GET | `/v1/funding_fee/history` | 资金费扣减记录 |

### 2.4 限频规则

| 分类 | 限制 |
|------|------|
| 全局 | 100 次 / 10 秒 |
| 交易接口（下单/撤单） | 10 次 / 秒 |
| 私有接口 | 20 次 / 秒 |
| 公共接口 | 50 次 / 秒 |
| 批量下单 | 1 次 / 秒 |
| 设置杠杆 | 5 次 / 60 秒 |

### 2.5 WebSocket 频道

**公共频道**（无需认证）：

| 频道名 | 说明 |
|--------|------|
| `orderbook` | 完整订单簿快照 |
| `orderbookupdate` | 订单簿增量更新 |
| `trade` | 成交记录 |
| `ticker` | 行情 ticker |
| `bbo` | 最优买卖价 |
| `markprice` | 标记价格 |
| `kline` | K 线 |

**私有频道**（需认证）：

| 频道名 | 说明 |
|--------|------|
| `executionreport` | 订单状态推送 |
| `position` | 仓位变化推送 |
| `balance` | 余额变化推送 |

---

## 3. 认证方式

Orderly 使用 **ed25519 椭圆曲线签名**对请求进行认证。

### 3.1 请求签名头

每次私有 REST 请求需附带以下 Header：

```
orderly-account-id:  <your_account_id>
orderly-key:         ed25519:<BASE58_ENCODED_PUBLIC_KEY>
orderly-timestamp:   <unix_milliseconds>
orderly-signature:   <BASE64_ENCODED_SIGNATURE>
```

### 3.2 签名内容

签名字符串格式：

```
{timestamp}{method}\n{path}\n{body_or_query}
```

使用 ed25519 私钥对上述字符串进行签名，然后 Base64 编码（**URL-safe 无填充**）。

### 3.3 WebSocket 认证

私有 WebSocket 连接时，订阅私有频道需要发送 auth message：

```json
{
  "id": "auth",
  "event": "auth",
  "params": {
    "orderly_key": "ed25519:...",
    "sign": "<BASE64_SIGNATURE>",
    "timestamp": 1234567890000
  }
}
```

---

## 4. Connector 配置

### 4.1 配置文件位置

```
conf/connectors/orderly_perpetual_testnet.yml   # 测试网
conf/connectors/orderly_perpetual.yml           # 主网（需手动创建）
```

### 4.2 配置字段说明

```yaml
connector: orderly_perpetual_testnet

# Orderly 账户 ID（通常是 EVM 钱包地址）
orderly_perpetual_testnet_account_id: <your_account_id>

# ed25519 公钥（Orderly 格式）
orderly_perpetual_testnet_api_key: <your_orderly_key>

# ed25519 私钥（Orderly 格式）
orderly_perpetual_testnet_api_secret: <your_orderly_secret>
```

> **注意**：Hummingbot 会对配置文件中的密钥进行加密存储（AES-128-CTR），请通过 `create` 或 `connect` 命令输入密钥，不要手动明文写入配置文件。

### 4.3 主网 Connector 配置

主网对应 connector 名称为 `orderly_perpetual`，配置文件路径：

```yaml
# conf/connectors/orderly_perpetual.yml
connector: orderly_perpetual

orderly_perpetual_account_id: <your_account_id>
orderly_perpetual_api_key: <your_orderly_key>
orderly_perpetual_api_secret: <your_orderly_secret>
```

---

## 5. 策略配置详解

策略文件路径：`conf/strategies/orderly_eth_usdc.yml`

```yaml
template_version: 6
strategy: perpetual_market_making

# 连接器名称：testnet 用 orderly_perpetual_testnet；主网用 orderly_perpetual
derivative: orderly_perpetual_testnet

# 交易对：格式为 BASE-QUOTE
# 测试网特殊交易对可加后缀，如 ETH-USDC_de1_dex_test
market: ETH-USDC

# 杠杆倍数
leverage: 5

# 仓位模式：One-way 单向
position_mode: One-way

# 第一档买/卖单相对中间价的百分比（0.1 = 0.1%）
bid_spread: 0.1
ask_spread: 0.1

# 双边各铺多少档订单（总挂单数 = order_levels × 2）
order_levels: 5

# 后续档位间的额外价差（百分比）
order_level_spread: 0.1

# 后续档位的订单量变化（0 = 每档相同）
order_level_amount: 0.0

# 基础每档下单量（ETH 数量）
order_amount: 0.01

# 定期撤单重挂的时间间隔（秒）
order_refresh_time: 15.0

# 当价格变动小于此百分比时不撤旧单（节省手续费）
order_refresh_tolerance_pct: 0.05

# 订单成交后重新挂单的等待时间（秒）
filled_order_delay: 60.0

# 止损：亏损达到以下百分比时触发市价止损平仓
stop_loss_spread: 2.0
stop_loss_slippage_buffer: 0.5
time_between_stop_loss_orders: 60.0

# 止盈：盈利达到以下百分比时触发止盈
long_profit_taking_spread: 1.5
short_profit_taking_spread: 1.5

# 价格保护区间（-1.0 = 禁用）
price_ceiling: -1.0
price_floor: -1.0

# 使用外部市场价格作为基准
price_source: external_market
price_type: mid_price
minimum_spread: -100.0

# 外部参考市场（使用 Binance 永续 ETH-USDT 中间价）
price_source_derivative: binance_perpetual
price_source_market: ETH-USDT
custom_api_update_interval: 5.0
```

### 5.1 关键参数调优建议

| 场景 | 推荐参数调整 |
|------|-------------|
| 低风险稳健做市 | `bid/ask_spread` 调高至 0.2-0.3%，`order_levels: 3` |
| 高频积极做市 | `order_refresh_time: 5`，`bid_spread: 0.05` |
| 控制仓位风险 | 开启 `stop_loss_spread`，调低 `leverage` |
| 测试新交易对 | `order_amount` 调至最小值（如 0.001 ETH） |

---

## 6. 本地部署（Conda）

### 6.1 环境安装

```bash
# 克隆仓库并切换到 orderly 分支
git clone https://github.com/your-org/hummingbot.git
cd hummingbot
git checkout feature_orderly

# 创建并激活 Conda 环境（环境名从 setup/environment.yml 自动读取，当前为 hummingbot_orderly）
make install

# 激活环境
conda activate hummingbot_orderly
```

### 6.2 配置 API 密钥

**方式一**：通过 Hummingbot 交互式命令行：

```bash
# 启动 Hummingbot
./bin/hummingbot_quickstart.py

# 进入后执行
>>> connect orderly_perpetual_testnet
```

按提示依次输入 `account_id`、`orderly_key`（公钥）、`orderly_secret`（私钥）。

**方式二**：直接使用已有加密配置启动策略：

```bash
./bin/hummingbot_quickstart.py --config-file-name orderly_eth_usdc.yml
```

### 6.3 常用 Makefile 命令

```bash
# 安装/更新 Conda 环境
make install

# 直接运行（自动使用 hummingbot_orderly 环境）
make run

# 带参数运行（例如指定策略文件和密码）
make run ARGS="--config-file-name orderly_eth_usdc.yml --config-password <password>"
```

### 6.4 无头模式后台运行

适合服务器长期运行（无交互界面）：

```bash
./bin/hummingbot_quickstart.py \
  --config-file-name orderly_eth_usdc.yml \
  --config-password <your_password> \
  --headless
```

> 无头模式下 MQTT 不是必须的，`mqtt_autostart: false` 时机器人可正常运行。

---

## 7. Docker 部署

> [!IMPORTANT]
> Orderly connector **不在官方 Docker 镜像中**，必须基于本项目代码**本地构建镜像**后才能使用。

### 7.1 构建本地镜像（必须）

```bash
# 构建包含 Orderly connector 的本地镜像
make build
# 等同于：
docker build -t hummingbot/hummingbot:orderly -f Dockerfile .
```

### 7.2 修改 docker-compose.yml 使用本地镜像

将 `docker-compose.yml` 中的 `image` 替换为本地构建的镜像：

```yaml
services:
  hummingbot:
    # 注释官方镜像，改用本地构建
    # image: hummingbot/hummingbot:latest
    image: hummingbot/hummingbot:orderly   # 本地构建的镜像
    # 或者直接指定 build
    # build:
    #   context: .
    #   dockerfile: Dockerfile
```

### 7.3 启动容器

```bash
# 初始化（选择是否包含 Gateway）
make setup

# 后台启动
make deploy

# 进入容器交互界面
docker attach hummingbot
```

### 7.4 关键 docker-compose 配置说明

```yaml
services:
  hummingbot:
    image: hummingbot/hummingbot:latest
    # 若使用本地构建，注释 image 并取消 build 注释：
    # build:
    #   context: .
    #   dockerfile: Dockerfile
    volumes:
      - ./conf:/home/hummingbot/conf          # 策略 & connector 配置
      - ./logs:/home/hummingbot/logs          # 日志输出
      - ./data:/home/hummingbot/data          # SQLite 数据库
      - ./scripts:/home/hummingbot/scripts    # 自定义脚本
    network_mode: host   # 使用宿主机网络（降低延迟）
    init: true           # 防止僵尸进程
    tty: true
    stdin_open: true
    # 无头模式直接启动策略（取消注释）：
    # command: hbot start orderly_eth_usdc --foreground
    # environment:
    #   - HBOT_PASSWORD=your_password
```

### 7.4 Docker 无头模式运行

修改 `docker-compose.yml` 取消 command 注释，然后重启：

```bash
docker compose down
make deploy

# 实时查看日志
docker logs -f hummingbot
```

---

## 8. 启动与运行

### 8.1 启动流程

```
1. 启动 Hummingbot
       ↓
2. 输入钱包密码（解密 API 密钥）
       ↓
3. 首次使用时连接 Connector：connect orderly_perpetual_testnet
       ↓
4. 启动策略：start --config orderly_eth_usdc.yml
       ↓
5. 查看运行状态：status
```

### 8.2 常用命令

```bash
# 查看策略运行状态（持仓、盈亏、挂单数）
status

# 停止策略（保留现有挂单）
stop

# 停止并撤销所有挂单
stop --force

# 查看成交历史
history

# 查看账户余额
balance
```

### 8.3 日志查看

```bash
# 本地运行
tail -f logs/hummingbot_logs_$(date +%Y-%m-%d).log

# Docker 运行
docker logs -f hummingbot
```

---

## 9. 常见问题

**Q: 认证失败 / Invalid Signature**
- 检查 `orderly_key` 和 `orderly_secret` 格式是否为 `ed25519:BASE58_KEY`
- 确认系统时间误差在 ±5 秒以内（签名包含时间戳验证）

**Q: 订单被拒绝 / MIN_NOTIONAL**
- 下单名义价值（price × size）过小，通常需要 > $10
- 增大 `order_amount` 或适当提高 `leverage`

**Q: 价格来源（Binance）断联**
- 检查网络，或将 `price_source` 改为 `mid_price` 临时使用 Orderly 自身盘口价

**Q: 测试网交易对找不到**
- Orderly 测试网部分交易对带有后缀，如 `ETH-USDC_de1_dex_test`
- 通过 API 查询可用列表：`GET https://testnet-api.orderly.org/v1/public/futures`

**Q: Docker 容器启动后立即退出**
- 检查 `HBOT_PASSWORD` 是否正确
- 通过 `docker logs hummingbot` 查看错误详情

---

## 附录：目录结构

```
hummingbot/
├── conf/
│   ├── connectors/
│   │   ├── orderly_perpetual.yml              # 主网 API 密钥（加密存储）
│   │   └── orderly_perpetual_testnet.yml      # 测试网 API 密钥（加密存储）
│   └── strategies/
│       ├── orderly_eth_usdc.yml               # ETH-USDC 做市策略
│       └── orderly_eth_usdc_de1_dex_test.yml  # 测试网专用策略
├── hummingbot/connector/derivative/
│   └── orderly_perpetual/
│       ├── orderly_perpetual_constants.py     # 接口地址、限频规则
│       ├── orderly_perpetual_auth.py          # ed25519 签名认证
│       ├── orderly_perpetual_derivative.py    # 核心连接器逻辑
│       └── orderly_swagger.yml               # Orderly API 文档
├── logs/                                      # 运行日志
├── data/                                      # SQLite 数据库
├── Makefile                                   # 快捷命令
└── docker-compose.yml                         # Docker 部署配置
```
