# 连接器架构：请求流程、身份验证和异步处理

本文档详细解释了 Hummingbot 连接器如何处理 API 请求、身份验证、速率限制（Throttling）以及异步操作。

## 目录
1. [高级架构](#高级架构)
2. [请求执行流程](#请求执行流程)
3. [身份验证流程](#身份验证流程)
4. [速率限制器（Throttler）机制](#速率限制器throttler机制)
5. [异步任务处理](#异步任务处理)
6. [订单管理流程](#订单管理流程)
7. [仓位管理流程](#仓位管理流程)

---

## 高级架构

```mermaid
graph TB
    subgraph "连接器层 (Connector Layer)"
        Connector[OrderlyPerpetualDerivative]
        Connector -->|创建| Factory[WebAssistantsFactory]
        Connector -->|创建| Throttler[AsyncThrottler]
        Connector -->|创建| Auth[OrderlyPerpetualAuth]
    end
    
    subgraph "Web 助手层 (Web Assistant Layer)"
        Factory -->|创建| RESTAssistant[RESTAssistant]
        Factory -->|提供| Throttler
        Factory -->|提供| Auth
        RESTAssistant -->|使用| RESTConnection[RESTConnection]
        RESTConnection -->|使用| AiohttpSession[aiohttp.ClientSession]
    end
    
    subgraph "限制器层 (Throttler Layer)"
        Throttler -->|管理| TaskLogs[TaskLog 列表]
        Throttler -->|创建| RequestContext[AsyncRequestContext]
        RequestContext -->|获取| Lock[asyncio.Lock]
    end
    
    subgraph "外部 API"
        AiohttpSession -->|HTTP 请求| API[Orderly Network API]
        API -->|HTTP 响应| AiohttpSession
    end
    
    Connector -->|调用| RESTAssistant
    RESTAssistant -->|通过其进行频控限速| Throttler
    RESTAssistant -->|通过其进行签名鉴权| Auth
```

---

## 请求执行流程

该图展示了从连接器方法调用到 API 响应的完整流程：

```mermaid
sequenceDiagram
    participant Connector as OrderlyPerpetualDerivative
    participant APIReq as _api_request()
    participant Factory as WebAssistantsFactory
    participant RESTAssist as RESTAssistant
    participant Throttler as AsyncThrottler
    participant Auth as OrderlyPerpetualAuth
    participant Conn as RESTConnection
    participant API as Orderly Network API
    
    Connector->>APIReq: _place_order() / _update_positions()
    APIReq->>Factory: get_rest_assistant()
    Factory->>RESTAssist: create RESTAssistant(connection, throttler, auth)
    Factory-->>APIReq: RESTAssistant 实例
    
    APIReq->>RESTAssist: execute_request(url, throttler_limit_id, ...)
    
    Note over RESTAssist: 构建 RESTRequest 对象
    RESTAssist->>RESTAssist: Create RESTRequest(method, url, params, data, headers)
    
    Note over RESTAssist,Throttler: 频控限速阶段 (Rate Limiting Phase)
    RESTAssist->>Throttler: execute_task(limit_id)
    Throttler->>Throttler: 获取 limit_id 对应的频率限制
    Throttler->>Throttler: 创建 AsyncRequestContext
    Throttler->>Throttler: acquire() - 检查容量
    alt 容量足够
        Throttler->>Throttler: 将任务记录到 TaskLogs
        Throttler-->>RESTAssist: 进入 Context (继续执行)
    else 超出容量
        Throttler->>Throttler: await asyncio.sleep(retry_interval)
        Throttler->>Throttler: 重新检查容量
        Throttler-->>RESTAssist: 等待直到有容量可用
    end
    
    Note over RESTAssist,Auth: 身份验证阶段 (Authentication Phase)
    RESTAssist->>RESTAssist: _pre_process_request() - 应用前置处理器
    RESTAssist->>Auth: rest_authenticate(request) [若 is_auth_required]
    Auth->>Auth: 生成时间戳
    Auth->>Auth: 创建规范化字符串 (timestamp + method + path + body/params)
    Auth->>Auth: 使用 ed25519 私钥进行签名
    Auth->>Auth: 创建认证 Headers (account-id, key, signature, timestamp)
    Auth-->>RESTAssist: 带有认证 Headers 的请求对象
    
    Note over RESTAssist,API: 网络请求阶段 (Network Request Phase)
    RESTAssist->>Conn: call(request)
    Conn->>API: 发送 HTTP 请求 (aiohttp)
    API-->>Conn: 返回 HTTP 响应
    Conn-->>RESTAssist: 返回 RESTResponse
    
    Note over RESTAssist: 后置处理阶段 (Post-processing Phase)
    RESTAssist->>RESTAssist: _post_process_response()
    RESTAssist-->>APIReq: 响应 JSON
    APIReq-->>Connector: 解析后的响应数据
```

---

## 身份验证流程

Orderly Network 详细的身份验证处理过程（基于 ed25519 签名）：

```mermaid
sequenceDiagram
    participant Connector as 实例方法
    participant APIReq as _api_request()
    participant RESTAssist as RESTAssistant
    participant Auth as OrderlyPerpetualAuth
    participant PrivateKey as Ed25519PrivateKey
    
    Connector->>APIReq: _api_request(path, is_auth_required=True)
    APIReq->>RESTAssist: execute_request(is_auth_required=True)
    
    RESTAssist->>Auth: rest_authenticate(request)
    
    Note over Auth: 提取请求组件
    Auth->>Auth: 提取 HTTP 方法 (GET/POST/PUT/DELETE)
    Auth->>Auth: 从 URL 中提取 path
    Auth->>Auth: 获取 params (query 参数) 或 data (body 主体)
    
    Note over Auth: 生成签名 (Signature)
    Auth->>Auth: 获取当前时间戳（毫秒级）
    alt GET/DELETE 请求
        Auth->>Auth: 将 params 拼接为 Query 字符串
        Auth->>Auth: message = timestamp + method + path + "?" + query_string
    else POST/PUT 请求
        Auth->>Auth: 直接使用 request.data (JSON 字符串)
        Auth->>Auth: message = timestamp + method + path + json_body
    end
    
    Auth->>PrivateKey: sign(message.encode('utf-8'))
    PrivateKey-->>Auth: signature_bytes
    Auth->>Auth: base64.encode(signature_bytes)
    
    Note over Auth: 创建 Headers
    Auth->>Auth: headers = {<br/>  "orderly-account-id": account_id,<br/>  "orderly-key": public_key,<br/>  "orderly-signature": base64_signature,<br/>  "orderly-timestamp": timestamp<br/>}
    
    Auth->>RESTAssist: request.headers.update(auth_headers)
    Auth-->>RESTAssist: 已完成签名的请求
    
    RESTAssist->>RESTAssist: 发送请求至 API
```

**身份验证核心要点：**
- **签名格式**：`{timestamp}{method}{path}{body_or_query}`
- **算法**：Ed25519 椭圆曲线密码学
- **必需的 Headers**：account-id, public key, signature (base64 格式), timestamp
- **时间戳窗口**：Orderly 会验证时间戳差异在 300 秒以内

---

## 速率限制器（Throttler）机制

Throttler 如何管理速率限制和任务排队：

```mermaid
stateDiagram-v2
    [*] --> RequestReceived: execute_task(limit_id)
    
    RequestReceived --> GetRateLimit: 获取频控配置
    GetRateLimit --> CreateContext: 创建 AsyncRequestContext
    
    CreateContext --> AcquireLock: 进入异步 Context
    AcquireLock --> FlushOldTasks: 获取 asyncio.Lock
    
    FlushOldTasks --> CheckCapacity: 清理过期的 TaskLogs
    CheckCapacity --> WithinCapacity: 检查当前容量是否足够
    
    WithinCapacity --> LogTask: 将 TaskLog 添加至列表
    LogTask --> ReleaseLock: 释放 lock
    ReleaseLock --> ExecuteRequest: 执行请求
    ExecuteRequest --> [*]
    
    CheckCapacity --> OverCapacity: 容量超出限制
    OverCapacity --> ReleaseLock2: 释放 lock
    ReleaseLock2 --> Wait: await asyncio.sleep(retry_interval)
    Wait --> AcquireLock: 重新尝试获取
    
    note right of CheckCapacity
        容量检查逻辑:
        - 统计时间窗口内的任务数
        - 与速率限制上限对比
        - 扣除安全余量缓冲 (5%)
        - 检查相关联的速率限制限制项
    end note
    
    note right of LogTask
        TaskLog 包含:
        - timestamp (时间戳)
        - rate_limit reference (频率限制参考)
        - weight (所占用的权重)
    end note
```

**频控组件结构：**

```mermaid
classDiagram
    class AsyncThrottler {
        -List[RateLimit] _rate_limits
        -Dict[str, RateLimit] _id_to_limit_map
        -List[TaskLog] _task_logs
        -asyncio.Lock _lock
        -float _retry_interval
        -float _safety_margin_pct
        +execute_task(limit_id) AsyncRequestContext
        +get_related_limits(limit_id) Tuple
    }
    
    class AsyncRequestContext {
        -List[TaskLog] _task_logs
        -RateLimit _rate_limit
        -List[Tuple[RateLimit, int]] _related_limits
        -asyncio.Lock _lock
        +acquire() async
        +within_capacity() bool
        +flush()
    }
    
    class RateLimit {
        +str limit_id
        +int limit
        +float time_interval
        +int weight
        +List[LinkedLimitWeightPair] linked_limits
    }
    
    class TaskLog {
        +float timestamp
        +RateLimit rate_limit
        +int weight
    }
    
    AsyncThrottler --> AsyncRequestContext : 创建
    AsyncRequestContext --> TaskLog : 记录至
    AsyncRequestContext --> RateLimit : 使用
    TaskLog --> RateLimit : 关联
```

**频率限制示例 (Orderly Network):**
```python
RateLimit(
    limit_id="/v1/order",
    limit=100,              # 每秒 100 次请求
    time_interval=1.0,      # 时间窗口 1 秒
    weight=1,               # 消耗 1 个单位
    linked_limits=[         # 同时也消耗 general（通用）限额
        LinkedLimitWeightPair(limit_id="general", weight=1)
    ]
)
```

---

## 异步任务处理

异步操作是如何协同工作的：

```mermaid
graph TB
    subgraph "主事件循环"
        EventLoop[asyncio 事件循环]
    end
    
    subgraph "连接器后台任务"
        StatusPolling[_status_polling_loop]
        OrderUpdate[_update_order_status]
        BalanceUpdate[_update_balances]
        PositionUpdate[_update_positions]
        UserStream[_user_stream_event_listener]
    end
    
    subgraph "请求执行任务"
        Request1[请求 1: 下单]
        Request2[请求 2: 获取仓位]
        Request3[请求 3: 撤单]
    end
    
    subgraph "频率限制器协同"
        Throttler[AsyncThrottler]
        Lock[asyncio.Lock]
        TaskLogs[(TaskLogs)]
    end
    
    EventLoop --> StatusPolling
    EventLoop --> UserStream
    EventLoop --> Request1
    EventLoop --> Request2
    EventLoop --> Request3
    
    StatusPolling --> OrderUpdate
    StatusPolling --> BalanceUpdate
    StatusPolling --> PositionUpdate
    
    Request1 --> Throttler
    Request2 --> Throttler
    Request3 --> Throttler
    
    Throttler --> Lock
    Throttler --> TaskLogs
    
    Lock -.->|串行化访问| TaskLogs
    
    style Lock fill:#ff9999
    style TaskLogs fill:#99ff99
```

**异步协同关键点：**

1. **Throttler 锁**：`asyncio.Lock` 确保同一时间只有一个任务能检查/修改 TaskLogs 记录。
2. **上下文管理器**：`async with throttler.execute_task()` 确保锁和容量资源的正常获取和释放。
3. **非阻塞式等待**：当频控超出容量时，任务会调用 `asyncio.sleep` 主动出让控制权，让其他协程任务运行。
4. **并发请求**：允许同时发出多个在途的 HTTP 请求，但 Throttler 会确保总频控不超过交易所限制。

**异步示例代码流程：**
```python
# 多个并发请求
async def place_order():
    async with throttler.execute_task("/v1/order"):  # 获取容量配额
        response = await rest_assistant.call(request)  # 非阻塞的 HTTP 请求
        return response

# 以下任务可以并发运行，Throttler 会确保它们符合限频要求
task1 = asyncio.create_task(place_order())
task2 = asyncio.create_task(get_positions())
task3 = asyncio.create_task(cancel_order())

results = await asyncio.gather(task1, task2, task3)
```

---

## 订单管理流程

下单与维护订单状态的完整生命周期：

```mermaid
sequenceDiagram
    participant Strategy as 交易策略 (Strategy)
    participant Connector as OrderlyPerpetualDerivative
    participant OrderTracker as 订单跟踪器 (OrderTracker)
    participant APIReq as _api_request()
    participant Throttler as AsyncThrottler
    participant Auth as OrderlyPerpetualAuth
    participant API as Orderly API
    
    Strategy->>Connector: place_order(trading_pair, amount, price)
    Connector->>Connector: 生成本地 client_order_id
    Connector->>OrderTracker: start_tracking_order(order_id, ...)
    OrderTracker->>OrderTracker: 创建 InFlightOrder 对象
    
    Connector->>Connector: _place_order(order_id, trading_pair, ...)
    Connector->>Connector: exchange_symbol_associated_to_pair()
    Connector->>Connector: 构建 order_params 字典
    
    Connector->>APIReq: _api_request(CREATE_ORDER_URL, POST, data=order_params, is_auth_required=True)
    
    Note over APIReq,Throttler: 频控检测
    APIReq->>Throttler: execute_task("/v1/order")
    Throttler-->>APIReq: 获取到频控额度
    
    Note over APIReq,Auth: 签名鉴权
    APIReq->>Auth: rest_authenticate(request)
    Auth-->>APIReq: 返回带鉴权头部的请求对象
    
    APIReq->>API: POST /v1/order
    API-->>APIReq: {success: true, data: {order_id: "12345"}}
    
    APIReq-->>Connector: 响应数据 (包含交易所返回的 order_id)
    Connector->>OrderTracker: 更新订单 (绑定交易所的 exchange_order_id)
    
    Note over Connector: 状态轮询循环 (Status Polling Loop)
    loop 每个 Tick 周期
        Connector->>Connector: _update_order_status()
        Connector->>APIReq: _api_request(GET_ORDER_URL, is_auth_required=True)
        APIReq->>API: GET /v1/order/{order_id}
        API-->>APIReq: 返回订单状态 (OPEN/FILLED/CANCELLED)
        APIReq-->>Connector: 封装成 OrderUpdate 对象
        Connector->>OrderTracker: process_order_update()
        OrderTracker->>Strategy: 派发订单状态变更事件
    end
    
    Note over Connector: WebSocket 实时更新 (备用路径)
    API->>Connector: WebSocket: 推送 executionreport 事件
    Connector->>Connector: _process_order_event()
    Connector->>OrderTracker: process_order_update()
    OrderTracker->>Strategy: 派发订单状态变更事件
```

**订单生命周期状态：**
- `PENDING_CREATE`：订单已在本地创建，等待交易所确认
- `OPEN`：订单已在挂在交易所深度图上
- `PARTIALLY_FILLED`：订单部分成交
- `FILLED`：订单完全成交
- `CANCELED`：订单已被撤销
- `FAILED`：订单下单失败

---

## 仓位管理流程

如何获取和更新仓位信息：

```mermaid
sequenceDiagram
    participant Connector as OrderlyPerpetualDerivative
    participant PerpetualTrading as PerpetualTrading
    participant APIReq as _api_request()
    participant Throttler as AsyncThrottler
    participant Auth as OrderlyPerpetualAuth
    participant API as Orderly API
    
    Note over Connector: 状态轮询循环
    loop 每个 Tick 周期
        Connector->>Connector: _status_polling_loop_fetch_updates()
        Connector->>Connector: _update_positions()
        
        Connector->>APIReq: _api_request(POSITIONS_URL, GET, is_auth_required=True)
        
        Note over APIReq,Throttler: 频控检测
        APIReq->>Throttler: execute_task("/v1/positions")
        Throttler-->>APIReq: 获取到频控配额
        
        Note over APIReq,Auth: 签名鉴权
        APIReq->>Auth: rest_authenticate(request)
        Auth-->>APIReq: 返回带鉴权头部的请求对象
        
        APIReq->>API: GET /v1/positions
        API-->>APIReq: {success: true, data: {rows: [{symbol, position_qty, ...}]}}
        
        APIReq-->>Connector: 返回仓位数据
        
        loop 遍历每个仓位
            Connector->>Connector: 解析仓位详细信息
            Connector->>Connector: trading_pair_associated_to_exchange_symbol()
            Connector->>Connector: 计算仓位方向 (LONG/SHORT)
            
            alt 仓位已存在
                Connector->>PerpetualTrading: get_position(trading_pair, side)
                Connector->>PerpetualTrading: update_position(...)
            else 属于新开仓位
                Connector->>PerpetualTrading: set_position(pos_key, Position(...))
            end
            
            alt 仓位数量为 0 (已平仓)
                Connector->>PerpetualTrading: remove_position(pos_key)
            end
        end
    end
    
    Note over Connector: WebSocket 实时更新 (备用路径)
    API->>Connector: WebSocket: 推送 position 事件
    Connector->>Connector: _process_position_event()
    Connector->>Connector: _update_positions()
    Connector->>PerpetualTrading: 更新持仓状态
```

**仓位更新步骤：**

1. **获取仓位**：GET `/v1/positions` 请求返回所有仓位列表。
2. **解析响应**：提取标的符号、仓位数量、开仓均价、未实现盈亏（uPnL）。
3. **符号转换**：将交易所的 symbol（例如 `PERP_BTC_USDC`）转换为 Hummingbot 的 trading pair（如 `BTC-USDC`）。
4. **判断方向**：仓位数量 > 0 时为多头 (LONG)，数量 < 0 时为空头 (SHORT)。
5. **更新状态**：更新本地已有仓位记录，或者新建仓位。
6. **清理 0 仓位**：如果仓位数量归零，则将其从跟踪列表中移除。

---

## 核心组件概述

### 1. **连接器** (`OrderlyPerpetualDerivative`)
- 继承自 `PerpetualDerivativePyBase`。
- 维护交易对、订单列表和仓位数据。
- 初始化 `WebAssistantsFactory` 并注入频控器（Throttler）和签名认证器（Auth）。
- 实现具体的下单、撤单、状态更新和仓位查询逻辑。

### 2. **WebAssistantsFactory**
- 工厂模式，用于创建 REST/WebSocket Assistant 助手实例。
- 负责向助手实例中注入 throttler，auth 模块及前置/后置过滤器。

### 3. **RESTAssistant**
- 对底层 RESTConnection 进一步包装，引入频率控制和认证签名。
- 应用前置过滤器（如填充 headers，同步时间戳）。
- 应用后置过滤器（如接口统一报错解析和 JSON 转化）。

### 4. **AsyncThrottler**
- 对应各个接口细分终点的速率限制管理。
- 使用滑动时间窗口记录并统计已发起的任务。
- 使用 `asyncio.Lock` 确保多协程环境下的线程安全。
- 提供异步 Context Manager 模式来阻塞/释放请求配额。

### 5. **OrderlyPerpetualAuth**
- 实现 `AuthBase` 鉴权接口。
- 利用 Ed25519 密钥算法生成加密签名。
- 构造请求参数/主体的标准规范化文本。
- 为所有的私有接口请求附加相应的鉴权 headers。

### 6. **RESTConnection**
- 最底层的 HTTP 客户端网络封装。
- 采用 `aiohttp.ClientSession`。
- 处理真实的网络 I/O 数据读写。

---

## 采用的异步模式 (Async Patterns)

1. **异步上下文管理器**：使用 `async with throttler.execute_task()` 规范化获取频控的资源周期。
2. **异步锁**：`asyncio.Lock` 避免多协程同时更改 TaskLogs 发生并发竞态冲突。
3. **异步睡眠**：频控超限时，利用非阻塞的挂起等待，出让事件循环时间。
4. **任务并行化**：利用 `asyncio.gather()` 支持在途的多个接口并发调用。
5. **后台轮询任务**：状态心跳、行情及账户数据拉取以独立后台协程运行。
6. **WebSocket 异步流**：异步迭代器用于接收实时的流式推送事件。

---

## 频率限制策略

频率限制器使用 **滑动窗口 (Sliding Window)** 计数法：

1. **任务日志**：每次成功发送请求都会将执行时刻及权重计入 TaskLogs。
2. **容量检查**：发送前，剔除时间窗口之外的过期记录，并对比当前时间窗口内的请求额度。
3. **超限等待**：如果数量达到配置阈值，休眠一小段时间后重新检查。
4. **安全余量**：应用 5% 的安全容错缓冲比例，确保在大并发时不会因微小网络延迟导致踩线被限流。

---

## 错误处理

1. **网络连接错误**：由底层 Connection 捕获并按规则进行指数退避重试。
2. **频率限制限制 (429)**：Throttler 拦截，休眠等待后自动进行重试。
3. **签名验证失败**：抛出至 Connector 层，一般标识为凭证/签名失效错误。
4. **API 业务报错**：响应被解析后，抛出特定带有具体 code 的 `IOError` 异常。
5. **超时报错**：使用 `wait_for` 设定最大时限进行超时中断保护。
