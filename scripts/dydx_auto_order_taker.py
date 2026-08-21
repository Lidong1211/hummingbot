import logging
import os
import random
from decimal import Decimal
from typing import Dict, List, Optional

from pydantic import Field

from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.data_type.common import MarketDict, OrderType, PositionAction, TradeType
from hummingbot.core.data_type.order_candidate import PerpetualOrderCandidate
from hummingbot.core.event.events import MarketOrderFailureEvent, OrderFilledEvent
from hummingbot.strategy.strategy_v2_base import StrategyV2Base, StrategyV2ConfigBase


class DydxAutoOrderTakerConfig(StrategyV2ConfigBase):
    script_file_name: str = os.path.basename(__file__)
    controllers_config: List[str] = []

    # 交易标的与连接器
    taker_connector: str = Field(default="dydx_v4_perpetual", description="画线账户连接器")
    trading_pair: str = Field(default="ETH-USD", description="本地做市交易对")

    # 外部参考行情 (若不填则直接对标盘口中值价进行打点)
    external_connector: Optional[str] = Field(default="binance_perpetual", description="外部参考行情源交易所")
    external_trading_pair: Optional[str] = Field(default="ETH-USDT", description="外部参考交易对")

    # 画线打点频率 (秒)
    paint_interval: float = Field(default=30.0, description="画线打点周期（秒）")
    # 随机打点抖动 (例如 0~5 秒随机浮动，模拟真实交易)
    interval_jitter: float = Field(default=5.0, description="打点周期随机波动秒数")

    # 单次吃单打点量
    trade_amount: Decimal = Field(default=Decimal("1.0"), description="单次画线成交数量")
    trade_amount_min: Decimal = Field(default=Decimal("0.5"), description="随机吃单量下限")
    trade_amount_max: Decimal = Field(default=Decimal("1.5"), description="随机吃单量上限")
    # 允许的最大单边净持仓 (达到此阈值后会自动对冲平仓归零)
    max_inventory_limit: Decimal = Field(default=Decimal("10.0"), description="最大单边持仓限制")

    # 价格允许偏离阈值 (百分比，例如 0.05 代表 5%)
    max_price_deviation_pct: Decimal = Field(default=Decimal("0.05"), description="允许的最大盘口价格偏离")

    def update_markets(self, markets: MarketDict) -> MarketDict:
        markets[self.taker_connector] = markets.get(self.taker_connector, set()) | {self.trading_pair}
        if self.external_connector and self.external_trading_pair:
            markets[self.external_connector] = markets.get(self.external_connector, set()) | {self.external_trading_pair}
        return markets


class DydxAutoOrderTaker(StrategyV2Base):
    """
    dYdX v4 合约自动吃单 / 自成交打点脚本 (Auto Order Taker)
    1. 实时监听本地 dYdX 盘口深度与外部参考价格行情；
    2. 定时根据目标点位以 Taker 方式吃掉盘口挂单，生成连续真实的 K 线成交记录与交易量；
    3. 内置仓位重平衡机制，防止单边累积过多敞口。
    """

    def __init__(self, connectors: Dict[str, ConnectorBase], config: DydxAutoOrderTakerConfig):
        super().__init__(connectors, config)
        self.config = config
        self._next_paint_timestamp = 0.0
        self._current_inventory = Decimal("0")
        self._total_trades_count = 0
        self._total_volume_quote = Decimal("0")

    def on_tick(self):
        if not self._is_all_connectors_ready():
            return

        if self.current_timestamp >= self._next_paint_timestamp:
            self._execute_kline_paint()
            # 设置下一次打点时间戳 (加入随机抖动)
            jitter = random.uniform(0, float(self.config.interval_jitter))
            self._next_paint_timestamp = self.current_timestamp + float(self.config.paint_interval) + jitter

    def _is_all_connectors_ready(self) -> bool:
        taker_conn = self.connectors.get(self.config.taker_connector)
        if not taker_conn or not taker_conn.ready:
            return False

        if self.config.external_connector and self.config.external_trading_pair:
            ext_conn = self.connectors.get(self.config.external_connector)
            if not ext_conn or not ext_conn.ready:
                return False
        return True

    def _get_target_price(self) -> Optional[Decimal]:
        """
        获取当前的目标参考价格：
        如果配置了外部交易所，则获取外部中值价；否则使用本地盘口中值价。
        """
        if self.config.external_connector and self.config.external_trading_pair:
            ext_conn = self.connectors.get(self.config.external_connector)
            if ext_conn:
                mid = ext_conn.get_mid_price(self.config.external_trading_pair)
                if mid and not mid.is_nan():
                    return mid

        taker_conn = self.connectors.get(self.config.taker_connector)
        return taker_conn.get_mid_price(self.config.trading_pair)

    def _execute_kline_paint(self):
        """
        核心画线逻辑：
        1. 检查当前持仓是否超限；
        2. 决定本次是 BUY 还是 SELL 打点；
        3. 向盘口发出吃单，促成真实成交。
        """
        taker_conn = self.connectors.get(self.config.taker_connector)
        target_price = self._get_target_price()

        best_bid = taker_conn.get_price(self.config.trading_pair, False)  # 买一价
        best_ask = taker_conn.get_price(self.config.trading_pair, True)   # 卖一价

        if best_bid.is_nan() or best_ask.is_nan() or target_price is None or target_price.is_nan():
            self.logger().warning("[AUTO_TAKER] 盘口或目标行情数据未就绪，跳过本次打点。")
            return

        self.logger().info(
            f"[AUTO_TAKER] 盘口状态: BestBid={best_bid:.4f}, BestAsk={best_ask:.4f}, TargetPrice={target_price:.4f} | "
            f"当前净持仓={self._current_inventory:.2f}"
        )

        # 1. 优先仓位重平衡 (如果净多头或净空头超过阈值，反向吃单平仓，随机平掉当前仓位的 80% ~ 100%)
        if abs(self._current_inventory) >= self.config.max_inventory_limit:
            rebalance_ratio = random.uniform(0.8, 1.0)
            target_rebalance_amount = abs(self._current_inventory) * Decimal(str(rebalance_ratio))
            trade_amount = taker_conn.quantize_order_amount(self.config.trading_pair, target_rebalance_amount)
            
            if self._current_inventory > 0:
                self.logger().info(f"[AUTO_TAKER REBALANCE] 仓位过多 ({self._current_inventory}) -> 主动卖出大比例平仓 {trade_amount}...")
                self._submit_taker_order(TradeType.SELL, best_bid, trade_amount)
            else:
                self.logger().info(f"[AUTO_TAKER REBALANCE] 空头过多 ({self._current_inventory}) -> 主动买入大比例平仓 {trade_amount}...")
                self._submit_taker_order(TradeType.BUY, best_ask, trade_amount)
            return

        # 2. 正常画线打点逻辑 (选择买入或卖出)
        # 生成随机抖动的吃单量
        random_amount = random.uniform(float(self.config.trade_amount_min), float(self.config.trade_amount_max))
        trade_amount = taker_conn.quantize_order_amount(self.config.trading_pair, Decimal(str(random_amount)))

        # 如果当前目标价格高于盘口中间价 -> 买入推升；否则 -> 卖出压低
        mid_price = (best_bid + best_ask) / Decimal("2")
        if target_price > mid_price:
            trade_type = TradeType.BUY
            order_price = best_ask
        elif target_price < mid_price:
            trade_type = TradeType.SELL
            order_price = best_bid
        else:
            # 价格居中时，随机双向打点
            trade_type = TradeType.BUY if random.random() > 0.5 else TradeType.SELL
            order_price = best_ask if trade_type == TradeType.BUY else best_bid

        self.logger().info(
            f"[AUTO_TAKER EXECUTE] >>> 发起画线成交: {trade_type.name} {trade_amount} @ {order_price} "
            f"(目标价={target_price:.4f})"
        )
        self._submit_taker_order(trade_type, order_price, trade_amount)

    def _submit_taker_order(self, trade_type: TradeType, price: Decimal, amount: Decimal):
        """
        提交市价单（MARKET Order）以 100% 触发 Taker 吃单撮合成交
        """
        try:
            if trade_type == TradeType.BUY:
                self.buy(
                    connector_name=self.config.taker_connector,
                    trading_pair=self.config.trading_pair,
                    amount=amount,
                    order_type=OrderType.MARKET,
                    price=price,
                    position_action=PositionAction.OPEN
                )
            else:
                self.sell(
                    connector_name=self.config.taker_connector,
                    trading_pair=self.config.trading_pair,
                    amount=amount,
                    order_type=OrderType.MARKET,
                    price=price,
                    position_action=PositionAction.OPEN
                )
        except Exception as e:
            self.logger().error(f"[AUTO_TAKER ERROR] 下单异常: {str(e)}", exc_info=True)

    def did_fill_order(self, event: OrderFilledEvent):
        """
        成交回执记录与持仓累加
        """
        self._total_trades_count += 1
        trade_vol = event.amount * event.price
        self._total_volume_quote += trade_vol

        if event.trade_type == TradeType.BUY:
            self._current_inventory += event.amount
        else:
            self._current_inventory -= event.amount

        msg = (
            f"[AUTO_TAKER SUCCESS] ✅ 成交完成! {event.trade_type.name} {event.amount} {event.trading_pair} @ "
            f"{event.price} (累计画线成交: {self._total_trades_count}笔, 总量: {self._total_volume_quote:.2f} USD, "
            f"当前净持仓: {self._current_inventory:.2f})"
        )
        self.log_with_clock(logging.INFO, msg)

    def did_fail_order(self, event: MarketOrderFailureEvent):
        self.logger().error(f"[AUTO_TAKER FAILED] ❌ 画线订单失败: {event.order_id}, 类型: {event.order_type}")
