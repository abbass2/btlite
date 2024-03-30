# $$_ Lines starting with # $$_* autogenerated by jup_mini. Do not modify these
# $$_code
# $$_ %%checkall

from dataclasses import dataclass, field
from sortedcontainers import SortedDict
import pyqstrat as pq

RuleType = Callable[[np.datetime64], list[Order]]
MarketSimType = Callable[[np.datetime64, list[Order]], list[pq.Trade]]

class OrderStatus(Enum):
    '''
    Enum for order status
    '''
    NEW
    OPEN
    PARTIALLY_FILLED
    FILLED
    CANCELLED


class TimeInForce(Enum):
    FOK = 1  # Fill or Kill
    GTC = 2  # Good till Cancelled
    DAY = 3  # Cancel at EOD


class ModificationType(Enum):
    OPEN
    CANCEL


@dataclass
class ModRequest:
    modification_type: ModificationType = ModificationType.OPEN
    request_time: np.datetime64


@dataclass(kw_only=True)
class Order:
    '''
    Args:
        contract: The contract this order is for
        timestamp: Time the order was placed
        qty:  Number of contracts or shares.  Use a negative quantity for sell orders
        reason_code: The reason this order was created. Default ''
        properties: Any order specific data we want to store.  Default None
        status: Status of the order, "open", "filled", etc. Default "open"
    '''
    contract: Contract
    timestamp: np.datetime64 = np.datetime64()
    qty: float = math.nan
    reason_code: str = ''
    time_in_force: TimeInForce = TimeInForce.FOK
    properties: SimpleNamespace = field(default_factory=SimpleNamespace)
    status: OrderStatus = OrderStatus.NEW

    def __post_init__(self) -> None:
        self.pending_modfication = ModRequest(ModificationType.OPEN, self.timestamp)
        
    def request_modification(mod_request: ModRequest) -> None:
        self.pending_modification = mod_request
        
    def fill(self, fill_qty: float = math.nan) -> None:
        assert_(self.status in [OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED], 
                f'cannot fill an order in status: {self.status}')
        if math.isnan(fill_qty): fill_qty = self.qty
        assert_(self.qty * fill_qty >= 0, f'order qty: {self.qty} cannot be opposite sign of {fill_qty}')
        assert_(abs(fill_qty) <= abs(self.qty), f'cannot fill qty: {fill_qty} larger than order qty: {self.qty}')
        self.qty -= fill_qty
        if math.isclose(self.qty, 0):
            self.status = OrderStatus.FILLED
        else:
            self.status = OrderStatus.PARTIALLY_FILLED
        self.pending_modification = None
        

def get_new_order_status(mod_type: ModificationType) -> OrderStatus:
    if mod_type == ModificationType.OPEN: return OrderStatus.OPEN
    if mod_type == ModificationType.CANCEL: return OrderStatus.CANCELLED
    pq.assert_(False, f'invalid mod_type: {mod_type}')
    return OrderStatus.CANCELLED  # keep mypy happy


@dataclass
class Strategy:

    timestamps: np.ndarray
    rules: dict[str, RuleType]
    enabled_rules: SortedDict[np.datetime64, set[str]]
    globally_enabled_rules: set[str]
    market_sims: list[MarketSimType]
    live_orders: Order
    cancelled_orders: Order
    filled_orders: list[Order]
    trade_lag: np.timedelta64

    def __init__(self, initial_cash: float=1.e6, trade_lag: np.timedelta64=np.timedelta64(1, 'm')) -> None:
        self.timestamps = np.ndarray(0)
        self.rules = {}
        self.enabled_rules = SortedDict()
        self.globally_enabled_rules = set()
        self.market_sims = []
        self.live_orders = []
        self.cancelled_orders = []
        self.filled_orders = []
        self.trade_lag = np.timedelta64(1, 'm')
        self.account = Account(cash=initial_cash, positions={})

    def set_market_timestamps(self, timestamps: np.ndarray) -> None:
        '''
        Use either this or set_market_calendar
        '''
        self.timestamps = timestamps

    def set_market_calendar(self, start_date: np.datetime64, end_date: np.datetime64, calendar: str='NYSE', tz: str='US/Eastern', freq: str='1m') -> None:
        '''
        Closed on the left, i.e 9:30-15:59, not 9:31-16:00
        '''
        cal = mcal.get_calendar(calendar)
        pq.assert_(cal is not None)
        schedule = cal.schedule(start_date, end_date)
        timestamps = mcal.date_range(schedule, frequency=freq, closed='left', force_close=False).tz_localize(None).values
        if freq.endswith('m'):
            timestamps = timestamps.astype('M8[m]')
        elif freq.endswith('D'):
            timestamps = timestamps.astype('M8[D]')
        else:
            pq.assert_(False, 'unknown frequency: {freq}')
        self.timestamps = timestamps

    def add_rule(self, name: str, rule: RuleType) -> None:
        '''Rules are guaranteed to be run in the order in which they are added here'''
        self.rules[name] = rule

    def enable_rule(self, name: str, timestamps: np.ndarray | None) -> None:
        pq.assert_(timestamps.dtype == self.timestamps.dtype)
        if timestamps is None:
            self.globally_enabled_rules.add(name)
            return

        for timestamp in timestamps:
            rules_list = self.enabled_rules.get(timestamp)
            if rules_list is None:
                self.enabled_rules[timestamp] = {name}
            else:
                rules_list.add(name)

    def disable_rule(self, name: str) -> None:
        '''Call enable_rule if you want to disable for a few timestamps.'''
        self.globally_enabled_rules.remove(name)


    def add_market_sim(self, market_sim: MarketSimType) -> None:
        self.market_sims.append(market_sim)

    def get_current_equity(self, prices: dict[str, name]) -> float:
        equity: float = self.account.cash
        for name, qty in self.account.positions():
            price = prices.get(name)
            pq.assert_(price is not None, f'price missing for: {name}')
            multiplier = pq.Contract.get(name).multiplier
            mv = price * qty * multiplier
            equity += mv
        return equity

    def _apply_mod_requests(self, timestamp: np.datetime64) -> None:
        for order in self.live_orders:
            if order.pending_modification is not None:
                if (timestamp - pending_mod.request_time) >= self.trade_lag:
                    order.status = get_new_order_status(pending_mod.modification_type)
                    order.pending_mod = None
            
    def _expire_orders(self, timestamp: np.datetime64) -> None:
        for order in self.live_orders:
            if order.status in [OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED]:
                if order.time_in_force == pq.TimeInForce.FOK and (timestamp - order.timestamp) > self.trade_lag:
                    order.status = OrderStatus.CANCELLED
                    continue
                if order.time_in_force == pq.TimeInForce.DAY and timestamp.astype('M8[D]') > order.timestamp.astype('M8[D]'):
                    order.status = OrderStatus.CANCELLED
                    continue

    def _get_new_orders(self, timestamp: np.datetime64, rules: set[RuleType]) -> list[Order]:
        new_orders: list[Order] = []
        for rule_name in self.rules.keys()
            if rule_name in rules or rule_name in self.globally_enabled_rules:
                new_orders += rule(self, timestamp)


    def _update_order_lists(self) -> list[Order]:
        tmp: list[Order] = []
        ready_orders: list[Order] = []
        for order in self.live_orders:
            if order.status == OrderStatus.FILLED:
                self.filled_orders += order
                continue
            if order.status == OrderStatus.CANCELLED:
                self.cancelled_orders += order
                continue
            if order.status in [OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED]:
                ready_orders.append(order)
            tmp.append(order)

        self.live_orders = tmp
        return ready_orders

    def get_position(self, name: str) -> float:
        val = self.account.positions.get(name)
        if val is None: return 0.
        return val

 
    def run(self) -> None:
        while True:
            if len(self.rules) == 0: break  # no more rules to run
            timestamp, rule_list: list[RuleType] = self.rules.popitem(0)
            self.live_orders += self._get_new_orders(timestamp, rule_list)
            self._apply_mod_requests(timestamp)
            self._expire_orders(timestamp)
            ready_orders = self._update_order_lists(timestamp)

            for market_sim in self.market_sims:
                trades += market_sim(self, timestamp, ready_orders)

            for trade in trades:
                self.account.update_cash(-trade.qty * trade.contract.multiplier * trade.price)
                self.account.update_position(trade.contract.symbol, trade.qty)

            for trade in trades:
                for trade_callback in self.trade_callbacks:
                    trade_callback(self, timestamp, trade)


@dataclass
class Account:
    cash: float
    positions: defaultdict[str, int] = field(default_factory=lambda: defaultdict(int))

    def update_cash(self, add_amount: float) -> None:
        cash = self.cash
        cash += add_amount
        pq.assert_(cash >= 0., f'cash cannot go below 0')
        self.cash += add_amount

    def update_position(self, name: str, add_amount: int) -> None:
        self.positions[name] += add_amount

class EntryRule:
    def __init__(self, prices: dict[np.datetime64, float]) -> None:
        self.prices = prices

    def __call__(self, strategy: Strategy, timestamp: np.datetime64) -> list[Order]:
        curr_position = strategy.get_positions('AAPL')
        if curr_position != 0: return []
        curr_equity = strategy.get_current_equity()
        est_price = self.prices[timestamp]
        qty = np.floor((0.1 * curr_equity) / est_price)
        contract = pq.Contract.get('AAPL')
        return Order(contract, timestamp, qty, 'ENTER', TimeInForce.FOK)
    
    
class ExitRule:
    def __call__(self, strategy: Strategy, timestamp: np.datetime64) -> list[Order]:
        curr_position = strategy.get_positions('AAPL')
        if curr_position == 0: return []
        return Order(contract, timestamp, -curr_position, 'EOD', TimeInForce.GTC)
    
    
class MarketSim:
    def __init__(self, prices: dict[np.datetime64, float]) -> None:
        self.prices = prices

    def __call__(self, timestamp: np.datetime64, orders: list[Order]) -> list[pq.Trade]:
        trade_price = self.prices[timestamp]
        trades: list[pq.Trade] = []
        for order in orders:
            trade = pq.Trade(contract, order, timestamp, order.qty, trade_price)
            trades.append(trade)
        return trades

if __name__ == '__main__':
    np.random.seed(0)
    cal = mcal.get_calendar('NYSE')
    schedule = cal.schedule('2024-01-02')
    timestamps = mcal.date_range(schedule, frequency='1m', closed='left', force_close=False).tz_localize(None).values
    df = pd.DataFrame({'timestamp': timestamps})
    df['ret'] = np.random.normal(0, 0.001, len(timestamps))
    df['c'] = (1 + df.ret).cumprod() * 10.
    df['date'] = df.timestamp.values.astype('M8[D]')
    df['eod'] = (df.date != df.date.shift(-1))
    strategy = Strategy()
    strategy.set_timestamps(timestamps)
    strategy.add_rule('entry' EntryRule(prices))
    strategy.add_rule('exit', ExitRule())
    strategy.enable_rule('entry', df[df.c > 10.5].timestamp.values.astype('M8[m]')
    strategy.enable_rule('exit', df[df.eod].timestamp.values.astype('M8[m]'))
    strategy.run()
# $$_end_code
# $$_code
df.set_index('timestamp').c.plot()
# $$_end_code
