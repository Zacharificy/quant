from AlgorithmImports import *
from datetime import timedelta


class AlpacaPaperStocksStarter(QCAlgorithm):
    """
    QuantConnect + Alpaca Paper starter for a small stock account.

    Goal:
    - Trade liquid stocks/ETFs instead of options.
    - Use a $1,000 paper account.
    - Hold at most two positions.
    - Buy only whole-share positions the account can afford.
    - Favor daily uptrends breaking out of a recent range.

    Deploy with QuantConnect "Deploy Live" -> Brokerage: Alpaca -> Environment: Paper.
    """

    def initialize(self):
        self.set_start_date(2023, 1, 1)
        self.set_end_date(2026, 6, 1)
        self.set_cash(1000)
        self.set_brokerage_model(BrokerageName.ALPACA, AccountType.MARGIN)
        self.set_time_zone(TimeZones.NEW_YORK)

        self.tickers = [
            "SPY",
            "QQQ",
            "IWM",
            "DIA",
            "AAPL",
            "MSFT",
            "NVDA",
            "AMD",
            "PLTR",
            "SOFI",
        ]

        self.symbols = {}
        self.fast_ema = {}
        self.slow_ema = {}
        self.rsi_indicators = {}
        self.atr_indicators = {}
        self.entry_prices = {}
        self.entry_dates = {}
        self.highest_prices = {}
        self.last_exit_dates = {}

        self.max_positions = 2
        self.position_pct = 0.45
        self.min_cash_buffer = 25
        self.breakout_lookback_days = 20
        self.cooldown_days = 7
        self.stop_atr_multiple = 2.5
        self.take_profit_atr_multiple = 4.0
        self.trailing_stop_atr_multiple = 2.0
        self.max_hold_days = 25
        self.min_score = 0.68

        for ticker in self.tickers:
            equity = self.add_equity(ticker, Resolution.DAILY)
            equity.set_data_normalization_mode(DataNormalizationMode.ADJUSTED)
            self.symbols[ticker] = equity.symbol
            self.fast_ema[ticker] = self.ema(equity.symbol, 50, Resolution.DAILY)
            self.slow_ema[ticker] = self.ema(equity.symbol, 200, Resolution.DAILY)
            self.rsi_indicators[ticker] = self.rsi(equity.symbol, 14, MovingAverageType.WILDERS, Resolution.DAILY)
            self.atr_indicators[ticker] = self.atr(equity.symbol, 14, MovingAverageType.WILDERS, Resolution.DAILY)

        self.set_warm_up(timedelta(days=230))
        self.schedule.on(
            self.date_rules.every_day("SPY"),
            self.time_rules.after_market_open("SPY", 35),
            self.trade_once_per_day,
        )

    def on_data(self, data):
        pass

    def trade_once_per_day(self):
        if self.is_warming_up:
            return

        self.manage_existing_positions()

        open_count = self.open_position_count()
        if open_count >= self.max_positions:
            return
        if not self.market_is_healthy():
            return

        candidate = self.find_best_stock()
        if candidate is None:
            return

        ticker, symbol, score = candidate
        price = self.securities[symbol].price
        if price <= 0:
            return

        target_cash = self.portfolio.total_portfolio_value * self.position_pct
        available_cash = max(0, self.portfolio.cash - self.min_cash_buffer)
        order_cash = min(target_cash, available_cash)
        quantity = int(order_cash / price)

        if quantity <= 0:
            self.debug(f"Skip {ticker}: price ${price:.2f} is too high for available cash ${available_cash:.2f}")
            return

        ticket = self.market_order(symbol, quantity, tag=f"{ticker} stock breakout score={score:.2f}")
        if ticket is None:
            return

        self.entry_prices[symbol] = price
        self.entry_dates[symbol] = self.time.date()
        self.highest_prices[symbol] = price
        self.debug(f"ENTRY STOCK {ticker} qty={quantity} price={price:.2f} score={score:.2f}")

    def manage_existing_positions(self):
        for ticker, symbol in self.symbols.items():
            holding = self.portfolio[symbol]
            if not holding.invested:
                continue

            price = self.securities[symbol].price
            entry = self.entry_prices.get(symbol, float(holding.average_price))
            previous_high = self.highest_prices.get(symbol, entry)
            self.highest_prices[symbol] = max(previous_high, price)
            highest = self.highest_prices[symbol]
            atr = self.atr_indicators[ticker].current.value if self.atr_indicators[ticker].is_ready else 0
            held_days = (self.time.date() - self.entry_dates.get(symbol, self.time.date())).days
            fast = self.fast_ema[ticker].current.value if self.fast_ema[ticker].is_ready else 0
            slow = self.slow_ema[ticker].current.value if self.slow_ema[ticker].is_ready else 0

            exit_reason = None
            if atr > 0 and price <= entry - (self.stop_atr_multiple * atr):
                exit_reason = "ATR stop"
            elif atr > 0 and highest > entry and price <= highest - (self.trailing_stop_atr_multiple * atr):
                exit_reason = "ATR trail"
            elif atr > 0 and price >= entry + (self.take_profit_atr_multiple * atr):
                exit_reason = "ATR target"
            elif held_days >= self.max_hold_days:
                exit_reason = f"time stop {held_days}d"
            elif fast > 0 and slow > 0 and fast < slow:
                exit_reason = "trend failed"

            if exit_reason:
                quantity = int(holding.quantity)
                if quantity > 0:
                    self.market_order(symbol, -quantity, tag=exit_reason)
                    self.last_exit_dates[ticker] = self.time.date()
                    self.debug(f"EXIT STOCK {ticker} qty={quantity} price={price:.2f} {exit_reason}")

    def find_best_stock(self):
        best = None
        for ticker, symbol in self.symbols.items():
            if self.portfolio[symbol].invested:
                continue
            if self.in_cooldown(ticker):
                continue
            if not self.indicators_ready(ticker):
                continue

            score = self.score_stock(ticker)
            if score < self.min_score:
                continue

            if best is None or score > best[2]:
                best = (ticker, symbol, score)
        return best

    def score_stock(self, ticker):
        symbol = self.symbols[ticker]
        price = self.securities[symbol].price
        fast = self.fast_ema[ticker].current.value
        slow = self.slow_ema[ticker].current.value
        rsi = self.rsi_indicators[ticker].current.value
        atr = self.atr_indicators[ticker].current.value

        if price <= 0 or slow <= 0 or atr <= 0:
            return 0
        if price <= slow or fast <= slow:
            return 0
        if rsi < 50 or rsi > 72:
            return 0
        if not self.is_daily_breakout(ticker):
            return 0

        trend_score = min((fast / slow - 1) / 0.08, 1)
        rsi_score = 1 - min(abs(rsi - 60) / 22, 1)
        atr_score = 1 - min((atr / price) / 0.08, 1)
        breakout_score = min((price / self.prior_high(ticker) - 1) / 0.03, 1)
        return (trend_score * 0.30) + (rsi_score * 0.25) + (atr_score * 0.20) + (breakout_score * 0.25)

    def market_is_healthy(self):
        for ticker in ["SPY", "QQQ"]:
            if ticker not in self.symbols or not self.indicators_ready(ticker):
                return False

            symbol = self.symbols[ticker]
            price = self.securities[symbol].price
            fast = self.fast_ema[ticker].current.value
            slow = self.slow_ema[ticker].current.value
            atr = self.atr_indicators[ticker].current.value

            if price <= fast or fast <= slow:
                return False
            if price > 0 and atr / price > 0.045:
                return False

        return True

    def is_daily_breakout(self, ticker):
        high = self.prior_high(ticker)
        if high <= 0:
            return False
        return self.securities[self.symbols[ticker]].price > high

    def prior_high(self, ticker):
        history = self.history(self.symbols[ticker], self.breakout_lookback_days + 1, Resolution.DAILY)
        if history.empty:
            return 0

        if "high" not in history.columns:
            return 0

        highs = history["high"]
        if len(highs) < self.breakout_lookback_days + 1:
            return 0

        return max(highs.iloc[-self.breakout_lookback_days - 1:-1])

    def indicators_ready(self, ticker):
        return (
            self.fast_ema[ticker].is_ready
            and self.slow_ema[ticker].is_ready
            and self.rsi_indicators[ticker].is_ready
            and self.atr_indicators[ticker].is_ready
        )

    def in_cooldown(self, ticker):
        last_exit = self.last_exit_dates.get(ticker)
        if last_exit is None:
            return False
        return (self.time.date() - last_exit).days < self.cooldown_days

    def open_position_count(self):
        count = 0
        for symbol in self.symbols.values():
            if self.portfolio[symbol].invested:
                count += 1
        return count

    def on_order_event(self, order_event):
        if order_event.status == OrderStatus.INVALID:
            self.debug(f"INVALID ORDER: {order_event}")
        elif order_event.status == OrderStatus.FILLED:
            if order_event.fill_quantity < 0:
                self.entry_prices.pop(order_event.symbol, None)
                self.entry_dates.pop(order_event.symbol, None)
                self.highest_prices.pop(order_event.symbol, None)
