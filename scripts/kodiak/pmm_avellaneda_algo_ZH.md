# 加密永续合约在 1 秒更新延迟下的做市策略

## 介绍
对于加密货币永续合约的做市商而言，1 秒的订单更新延迟（Latency）是一个根本性的挑战。虽然高频交易（HFT）通常以微秒级运行，但在 1 秒延迟下，通过防御性报价（Defensive Positioning）、拓宽价差（Wider Spreads）和智能风险管理，做市依然是切实可行的。本指南针对 BTC-USD 或 ETH-USD 等单一交易对的 1 秒延迟限制，提供了一套切实可行的做市策略。

核心逻辑在于：**延迟类似于期权的“到期时间”**。当你挂出报价时，市场可能在订单更新窗口期内向不利方向移动（形成对你的不利成交，即 toxic flow），此时你承担的风险与延迟时间的平方根成正比。1 秒的延迟意味着你挂出的报价相当于给了交易者 1 秒的时间来“行权”。因此，你的价差（Spread）需要比高频竞争者拓宽 3-5 倍，才能维持盈利。

---

## 1. 针对 1 秒更新延迟的基础算法

基础策略结合了经典的 **Avellaneda-Stoikov 模型** 的数学严谨性，以及针对加密货币永续合约和延迟限制的实际调整。

### 核心算法组件

#### 预约价格（Reservation Price）计算
基于你的库存风险调整后的预约价格（公允价格）：
```
r = s - q · γ · σ² · τ
```
其中：
* `r` = 预约价格 (Reservation Price，即你调整后的公允价值)
* `s` = 当前市场中间价 (Mid-Price)
* `q` = 库存持仓量 (多头为正数 `+`，空头为负数 `-`)
* `γ` = 风险厌恶系数 (加密市场通常设为 5-10)
* `σ` = 年化波动率 (BTC 约为 40-60%，ETH 约为 50-80%)
* `τ` = 有效风险期 (永续合约通常使用 1-4 小时)

库存项引入了**非对称定价**：如果你累积了多头头寸（`q > 0`），你的预约价格就会向市场中间价下方偏移，使得你的卖单（Ask）更具吸引力，买单（Bid）吸引力降低，从而通过市场自然成交引导仓位回归中性。

#### 最佳价差（Optimal Spread）计算
平衡成交概率与单笔成交利润：
```
spread = γ · σ² · τ + (2/γ) · ln(1 + γ/κ) + latency_buffer
```
其中：
* `κ` = 订单到达密度 (流动性好的加密货币对通常为 50-200)
* `latency_buffer` = `σ · √(latency_seconds) · safety_factor`

对于 1 秒更新延迟，在 BTC 年化波动率 50% 的情况下：
```
latency_buffer = 0.50 · √(1) · 1.5 ≈ 0.75% (或 75 个基点)
```

这个**延迟缓冲（Latency Buffer）**非常关键——它补偿了在订单更新周期中价格波动导致的被动成交风险。安全因子（`safety_factor = 1.5`）为预期的价格波动提供了额外的缓冲垫。

#### 围绕预约价格挂单
```
bid_price = r - (spread / 2)
ask_price = r + (spread / 2)
```
同时强制限制最小价差：
```
actual_spread = max(calculated_spread, min_spread)
```
其中 `min_spread` 需确保扣除手续费后的基本盈利：
```
min_spread = 2 × max(maker_fee, taker_fee) + target_profit
```
例如在 Binance (Maker 费率 0.02%)：`min_spread ≥ 0.05%` (5 个基点)。

---

## 2. 结合库存感知（Inventory Awareness）的订单大小调整

动态调整挂单数量以加速均值回归：

```python
def calculate_order_sizes(base_size, inventory, target_inventory, max_inventory):
    deviation = (inventory - target_inventory) / max_inventory
    eta = -0.01  # 形状参数
    
    if deviation > 0:  # 多头库存
        bid_size = base_size * exp(eta * deviation)  # 减少买单大小
        ask_size = base_size  # 全额卖单以降低库存
    else:  # 空头库存
        bid_size = base_size  # 全额买单以补充库存
        ask_size = base_size * exp(-eta * deviation)  # 减少卖单大小
    
    return bid_size, ask_size
```

---

## 3. 针对 1 秒更新限制的更新周期管理

采用 **1 秒一次的批量更新**，而非高频的持续微调：

```python
def market_making_cycle():
    # 1. 收集当前状态 (WebSocket 数据更新时间 <50ms)
    mid_price = get_current_mid_price()
    inventory = get_current_position()
    volatility = calculate_rolling_volatility(window=200)
    
    # 2. 判断是否应该提供流动性 (防御性过滤)
    if not should_provide_liquidity(volatility, ROC_indicator, order_imbalance):
        cancel_all_orders()  # 耗时约 500-1000ms
        return
    
    # 3. 计算新报价
    reservation_price = calculate_reservation_price(mid_price, inventory, volatility)
    spread = calculate_optimal_spread(volatility, inventory, latency=1.0)
    bid_size, ask_size = calculate_order_sizes(BASE_SIZE, inventory)
    
    # 4. 替换报价 (单次批量 API 调用，耗时约 500-1000ms)
    new_bid = reservation_price - spread/2
    new_ask = reservation_price + spread/2
    
    replace_orders_atomic(
        cancel_orders=[existing_bid_id, existing_ask_id],
        new_orders=[
            {'side': 'buy', 'price': new_bid, 'size': bid_size},
            {'side': 'sell', 'price': new_ask, 'size': ask_size}
        ]
    )
```

---

## 4. BTC/ETH 永续合约的推荐参数起点

### 比特币 (BTC-USD 或 BTC-USDT):
* `γ` (风险厌恶度): 5-8
* `σ` (波动率): 0.45 (45% 年化，需根据最近的数据动态调整)
* `τ` (风险期): 2 小时 = 2 / 8760 年
* `κ` (流动性强度): 100-200
* `Min spread` (最小价差): 0.05% (5 bps)
* `Base size` (基础订单大小): 0.01-0.05 BTC (根据资金规模调整)
* `Max inventory` (最大库存上限): ±0.2 BTC (或总资金的 2-5%)

### 以太坊 (ETH-USD 或 ETH-USDT):
* `γ` (风险厌恶度): 5-10 (由于波动大，设得比 BTC 稍高)
* `σ` (波动率): 0.60 (60% 年化)
* `τ` (风险期): 2 小时
* `κ` (流动性强度): 80-150
* `Min spread` (最小价差): 0.06% (6 bps)
* `Base size` (基础订单大小): 0.1-0.5 ETH
* `Max inventory` (最大库存上限): ±2 ETH (或总资金的 2-5%)

上述参数将在 BTC 上产生大约 8-15 个基点的价差，在 ETH 上产生 10-20 个基点的价差。虽然这比高频做市商（HFT）宽了 3-5 倍，但对于普通零售和中型机构的流量，它们依然非常有竞争力。
