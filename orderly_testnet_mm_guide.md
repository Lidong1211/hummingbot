# Orderly Network 测试网做市测试指南（从零开始）

本指南旨在帮助您从零开始在 Orderly Network 测试网（Testnet）上建立账户、获取测试资金，并配置好环境以进行做市商（Market Maker）测试。

---

## 一、 准备工作

在开始之前，请准备好以下工具：
1. **EVM 兼容钱包**：推荐使用 [MetaMask](https://metamask.io/)。
2. **测试网 RPC 配置**：Orderly 测试网通常运行在 **Arbitrum Sepolia** 或 **Optimism Sepolia**。本指南以 **Arbitrum Sepolia** 为例。

---

## 二、 步骤 1：配置钱包与测试网

1. 打开 MetaMask 钱包。
2. 添加 **Arbitrum Sepolia** 测试网：
   - 如果钱包中没有，可以访问 [Chainlist (Arbitrum Sepolia)](https://chainlist.org/?search=Arbitrum+Sepolia&testnets=true)，连接钱包并一键添加网络。
   - **网络参数参考**：
     - 网络名称：`Arbitrum Sepolia`
     - RPC URL：`https://sepolia-rollup.arbitrum.io/rpc`
     - 链 ID (Chain ID)：`421614`
     - 货币符号：`ETH`
     - 区块浏览器：`https://sepolia.arbiscan.io/`

---

## 三、 步骤 2：获取测试网主链代币 (Gas Faucet)

In 测试网上进行任何链上交互（如注册、存入资金）都需要消耗 Gas 代币（Arbitrum Sepolia 上的 ETH）。

您可以通过以下水龙头（Faucet）获取免费的测试 ETH（每天可领一次）：
1. **Alchemy Faucet**（需要注册 Alchemy 账号）: [Arbitrum Sepolia Faucet](https://faucet.trade/arbitrum-sepolia-eth-faucet) 或 [Sepolia Faucet](https://sepoliafaucet.com/)
2. **QuickNode Faucet**: [QuickNode Arbitrum Sepolia Faucet](https://faucet.quicknode.com/arbitrum/sepolia)
3. **Chainlink Faucet**: [Chainlink Faucets](https://faucets.chain.link/)

*输入您的钱包地址，通过人机验证后点击“Send Me ETH”即可。*

---

## 四、 步骤 3：注册 Orderly 账户并获取测试交易代币 (USDC)

Orderly 是一个共享结算的订单簿 DEX。您需要通过其前端或交互接口创建 Orderly 账号并存入测试 USDC 资产。

1. **访问 Orderly 官方测试网 Demo**：
   - 访问 [Orderly Testnet App / Portfolio](https://testnet.orderly.network/) (或由合作伙伴提供的测试网前端，如 [LogX Testnet](https://testnet.logx.trade/) / [Apex Testnet](https://testnet.apex.exchange/))。
2. **连接钱包**：
   - 点击 **Connect Wallet** 并选择 MetaMask，确保钱包网络已切换至 **Arbitrum Sepolia**。
3. **注册 & 开启交易账号 (Enable Trading)**：
   - 首次连接时，前端会提示您进行签名以创建 Orderly 账户（注册 `AccountId`）。
   - 这会调用 Orderly 的链上合约进行账户初始化，请在钱包中批准签名。
4. **获取测试 USDC (Mint Test USDC)**：
   - 账户激活后，在资金管理页面（Deposit/Portfolio）通常会有一个 **"Mint"** 或 **"Faucet"** 按钮，专门用于领取测试 USDC。
   - 点击 Mint，并在钱包中确认交易。您将获得一定数量的测试 USDC（例如 1,000 ~ 10,000 USDC）。
5. **存入资金 (Deposit)**：
   - 领到测试 USDC 后，在钱包中授权（Approve）并将 USDC **Deposit**（存入）到 Orderly 合约中。
   - 存入成功后，这些资金将从您的 Web3 钱包转移至 Orderly 的二层交易账户中，可以在页面上的“Available Balance”看到余额。

---

## 五、 步骤 4：生成做市需要的 API Key

做市程序（如 Hummingbot）不能直接使用您的钱包私钥去高频下单，而是需要使用 Orderly 的 **API Key**（包含交易权限，但不包含提币权限，以确保安全）。

1. **在前端生成 API Key**：
   - 在测试网前端的设置页面（Settings）或开发者选项（API Management）中。
   - 点击 **Create API Key**。
   - 按照钱包弹窗提示进行签名。
2. **记录 API 凭证**：
   - 签名成功后，系统会展示以下关键信息（**注意：仅展示一次，请妥善保存**）：
     - **Orderly Account ID (`account_id`)**：您的 Orderly 账号唯一标识。
     - **Orderly Order key (`order_key`)**：用于对订单请求进行签名的密钥。
     - **API Key**
     - **API Secret**
     - **Orderly Private Key** (如果适用)

---

## 六、 步骤 5：环境初始化（依赖安装与编译）

在运行 Hummingbot 之前，需要确保环境中的所有依赖库已正确安装，并且完成了 Cython 等性能相关扩展的编译：

1. **激活 Conda 环境**：
   ```bash
   conda activate hummingbot
   ```
2. **运行依赖安装脚本**：
   此脚本会更新所有 conda 依赖包并进行初始化配置：
   ```bash
   ./install
   ```
3. **编译项目**：
   Hummingbot 底层有很多 C 编译加速组件，需在首次运行或迁移新连接器后进行编译：
   ```bash
   ./compile
   ```
   *注：编译可能需要 1~3 分钟。*

---

## 七、 步骤 6：配置做市程序进行测试

有了测试资金 and API Key 之后，您可以选择使用 **Hummingbot** 或 **Python/TypeScript SDK** 来进行做市测试。

### 选项 A：使用 Hummingbot 进行做市（推荐）

1. **安装 Hummingbot**：
   - 参考项目官方文档或本地 Hummingbot 实例。
2. **连接 Orderly Connector**：
   - 启动 Hummingbot，输入以下命令连接 Orderly：
     ```bash
     connect orderly
     ```
   - 提示时，依次输入您在步骤 4 中记录的信息：
     - `orderly_api_key`
     - `orderly_api_secret`
     - `orderly_account_id`
     - 选择网络：`testnet`
3. **创建做市策略 (Pure Market Making)**：
   - 创建一个新的做市策略：
     ```bash
     create
     ```
   - 按照提示配置：
     - 交易对 (Market)：例如 `PERP_ETH_USDC` 或 `ETH-USDC`（根据测试网实际可用交易对填写）。
     - 双边挂单距离 (Bid/Ask spread)：例如 `0.1` (即 0.1%)。
     - 挂单金额 (Order amount)：例如 `0.1 ETH`。
4. **启动做市**：
   - 输入 `start` 启动机器人。
   - 观察机器人是否成功在测试网上挂单，并在 Demo 前端的“Open Orders”页面查看挂单状态。

### 选项 B：使用 Python SDK 进行基础下单测试

如果您想自己写代码做市，可以使用 Orderly 的 Python SDK 来快速验证 API 是否连通。

1. **安装依赖**：
   ```bash
   pip install httpx cryptography
   ```
2. **简易测试脚本**：
   ```python
   import time
   import httpx
   # 请根据 Orderly Network 开发者文档提供的加密库及签名方法
   # 构造包含签名 Header 的 HTTP 请求。
   
   # 测试网端点 (Base URL)
   BASE_URL = "https://testnet-api-evm.orderly.org" 
   
   # 示例：获取账户信息
   # 请参考官方文档将 API Key 与 签名放入 Headers
   headers = {
       "x-orderly-api-key": "YOUR_API_KEY",
       # "x-orderly-signature": "GENERATE_SIGNATURE",
       # "x-orderly-timestamp": str(int(time.time() * 1000))
   }
   
   # 详细签名算法及 API 参考：https://docs.orderly.network/
   ```

---

## 八、 常用测试网资源与链接

- **Orderly 开发者文档**: [https://docs.orderly.network/](https://docs.orderly.network/)
- **测试网 API 地址**: `https://testnet-api-evm.orderly.org`
- **测试网 Webhook / WS 地址**: `wss://testnet-ws-evm.orderly.org/ws/v2`
- **Arbitrum Sepolia 浏览器**: [https://sepolia.arbiscan.io/](https://sepolia.arbiscan.io/)
