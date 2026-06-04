from AlgorithmImports import *
from datetime import timedelta


class AlpacaPaperOptionsStarter(QCAlgorithm):
    """
    QuantConnect + Alpaca Paper starter.

    Goal:
    - Trade long single-leg SPY options only.
    - Use a $1,000 paper account.
    - Keep risk small: max one open option contract.
    - Prefer liquid 30-45 DTE call contracts on daily momentum breakouts.
    - Exit intraday with stop, target, time stop, or end-of-day flattening.

    Deploy with QuantConnect "Deploy Live" -> Brokerage: Alpaca -> Environment: Paper.
    """

    def initialize(self):
        self.set_start_date(2023, 1, 1)
        self.set_end_date(2026, 6, 1)
        self.set_cash(1000)
        self.set_brokerage_model(BrokerageName.ALPACA, AccountType.MARGIN)
        self.set_time_zone(TimeZones.NEW_YORK)

        self.underlyings = ["SPY"]
        self.symbols = {}
        self.option_symbols = {}
        self.fast_ema = {}
        self.slow_ema = {}
        self.rsi_indicators = {}
        self.daily_fast_ema = {}
        self.daily_slow_ema = {}
        self._latest_slice = None

        self.max_open_contracts = 1
        self.max_premium_pct = 0.08
        self.min_contract_mid = 0.35
        self.max_contract_mid = 0.90
        self.stop_loss_pct = 0.30
        self.take_profit_pct = 0.80
        self.max_hold_minutes = 300
        self.cooldown_days = 15
        self.min_dte = 30
        self.max_dte = 45
        self.target_otm_pct = 0.01
        self.max_spread_pct = 0.15
        self.min_signal_score = 0.80
        self.breakout_lookback_days = 20
        self.skip_log_interval = 50
        self.entry_order_timeout = timedelta(minutes=10)

        self.open_trade = None
        self.pending_entry = None
        self.last_entry_date = None
        self.last_exit_date = None
        self.skip_count = 0

        for ticker in self.underlyings:
            equity = self.add_equity(ticker, Resolution.MINUTE)
            equity.set_data_normalization_mode(DataNormalizationMode.RAW)
            self.symbols[ticker] = equity.symbol

            option = self.add_option(ticker, Resolution.MINUTE)
            option.set_filter(self._option_filter)
            self.option_symbols[ticker] = option.symbol

            self.fast_ema[ticker] = self.ema(equity.symbol, 12, Resolution.MINUTE)
            self.slow_ema[ticker] = self.ema(equity.symbol, 26, Resolution.MINUTE)
            self.rsi_indicators[ticker] = self.rsi(equity.symbol, 14, MovingAverageType.WILDERS, Resolution.MINUTE)
            self.daily_fast_ema[ticker] = self.ema(equity.symbol, 50, Resolution.DAILY)
            self.daily_slow_ema[ticker] = self.ema(equity.symbol, 200, Resolution.DAILY)

        self.set_warm_up(timedelta(days=220))
        self.schedule.on(
            self.date_rules.every_day("SPY"),
            self.time_rules.every(timedelta(minutes=10)),
            self.manage_positions,
        )

    def _option_filter(self, universe):
        return universe.include_weeklys().strikes(-12, 12).expiration(
            timedelta(days=self.min_dte),
            timedelta(days=self.max_dte),
        )

    def on_data(self, data):
        if self.is_warming_up:
            return
        self._latest_slice = data

    def manage_positions(self):
        if self.is_warming_up:
            return

        self.manage_pending_entry()
        if self.is_trade_time():
            self.manage_open_trade()

        if self.pending_entry is not None:
            return
        if self.open_trade is not None:
            return
        if self.last_entry_date == self.time.date():
            return
        if self.last_exit_date is not None and (self.time.date() - self.last_exit_date).days < self.cooldown_days:
            return
        if not self.is_entry_time():
            return

        candidate = self.find_best_contract()
        if candidate is None:
            return

        contract, ticker, direction, entry_price, reason = candidate
        if entry_price <= 0:
            return
        if self.contract_score(contract, direction, (float(contract.bid_price) + float(contract.ask_price)) / 2, self.securities[self.symbols[ticker]].price) < self.min_signal_score:
            return

        max_premium = self.portfolio.total_portfolio_value * self.max_premium_pct
        estimated_debit = entry_price * 100
        if estimated_debit > max_premium:
            self.skip_count += 1
            if self.skip_count % self.skip_log_interval == 1:
                self.debug(f"Skip {contract.symbol}: debit ${estimated_debit:.2f} > cap ${max_premium:.2f}")
            return

        ticket = self.limit_order(contract.symbol, 1, round(entry_price, 2), tag=reason)
        self.pending_entry = {
            "symbol": contract.symbol,
            "underlying": ticker,
            "direction": direction,
            "entry_price": entry_price,
            "ticket_id": ticket.order_id,
            "submitted_time": self.time,
        }
        self.last_entry_date = self.time.date()
        self.debug(f"ENTRY {direction} {contract.symbol} limit={entry_price:.2f} {reason}")

    def find_best_contract(self):
        if self._latest_slice is None:
            return None

        best = None
        for ticker in self.underlyings:
            signal = self.get_signal(ticker)
            if signal == "WAIT":
                continue

            chain = self._latest_slice.option_chains.get(self.option_symbols[ticker])
            if chain is None:
                continue

            contracts = [contract for contract in chain if contract.right == OptionRight.CALL]
            contracts = [contract for contract in contracts if self.min_dte <= (contract.expiry.date() - self.time.date()).days <= self.max_dte]
            contracts = [contract for contract in contracts if self.contract_is_tradeable(contract)]
            if not contracts:
                continue

            underlying_price = self.securities[self.symbols[ticker]].price
            selected = min(contracts, key=lambda contract: self.strike_distance(contract, signal, underlying_price))
            bid = float(selected.bid_price)
            ask = float(selected.ask_price)
            mid = (bid + ask) / 2
            entry_price = round(ask, 2)
            score = self.contract_score(selected, signal, mid, underlying_price)
            reason = f"{ticker} {signal} EMA/RSI setup score={score:.2f}"

            if best is None or score > best[4]:
                best = (selected, ticker, signal, entry_price, score, reason)

        if best is None:
            return None
        selected, ticker, signal, entry_price, _score, reason = best
        return selected, ticker, signal, entry_price, reason

    def get_signal(self, ticker):
        if not self.fast_ema[ticker].is_ready or not self.slow_ema[ticker].is_ready or not self.rsi_indicators[ticker].is_ready:
            return "WAIT"
        if not self.daily_fast_ema[ticker].is_ready or not self.daily_slow_ema[ticker].is_ready:
            return "WAIT"

        rsi = self.rsi_indicators[ticker].current.value
        daily_fast = self.daily_fast_ema[ticker].current.value
        daily_slow = self.daily_slow_ema[ticker].current.value
        price = self.securities[self.symbols[ticker]].price

        if price > daily_slow and daily_fast > daily_slow and 52 <= rsi <= 68 and self.is_daily_breakout(ticker):
            return "CALL"
        return "WAIT"

    def is_daily_breakout(self, ticker):
        history = self.history(self.symbols[ticker], self.breakout_lookback_days + 2, Resolution.DAILY)
        if history.empty:
            return False

        try:
            highs = history.loc[self.symbols[ticker]]["high"]
        except Exception:
            highs = history["high"]

        if len(highs) < self.breakout_lookback_days + 1:
            return False

        prior_high = max(highs.iloc[-self.breakout_lookback_days - 1:-1])
        current_price = self.securities[self.symbols[ticker]].price
        return current_price > prior_high

    def contract_is_tradeable(self, contract):
        bid = float(contract.bid_price)
        ask = float(contract.ask_price)
        if bid <= 0 or ask <= 0 or ask < bid:
            return False
        mid = (bid + ask) / 2
        if mid < self.min_contract_mid or mid > self.max_contract_mid:
            return False
        spread_pct = (ask - bid) / mid
        if spread_pct > self.max_spread_pct:
            return False
        return True

    def strike_distance(self, contract, signal, underlying_price):
        if underlying_price <= 0:
            return 999
        target_strike = underlying_price * (1 + self.target_otm_pct)
        return abs(float(contract.strike) - target_strike)

    def contract_score(self, contract, signal, mid, underlying_price):
        spread = (float(contract.ask_price) - float(contract.bid_price)) / mid if mid > 0 else 1
        dte = (contract.expiry.date() - self.time.date()).days
        strike_score = 1 - min(self.strike_distance(contract, signal, underlying_price) / max(underlying_price * 0.05, 1), 1)
        dte_score = 1 - min(abs(dte - 14) / 14, 1)
        spread_score = 1 - min(spread / self.max_spread_pct, 1)
        return (strike_score * 0.45) + (dte_score * 0.25) + (spread_score * 0.30)

    def is_trade_time(self):
        minutes = self.time.hour * 60 + self.time.minute
        return (10 * 60) <= minutes <= (15 * 60 + 30)

    def is_entry_time(self):
        minutes = self.time.hour * 60 + self.time.minute
        return (10 * 60 + 30) <= minutes <= (13 * 60 + 30)

    def manage_open_trade(self):
        if self.open_trade is None:
            return
        if self.open_trade.get("exit_order_id") is not None:
            return

        symbol = self.open_trade["symbol"]
        holding = self.portfolio[symbol]
        if not holding.invested:
            return

        entry = float(self.open_trade["entry_price"])
        current = float(holding.price)
        if entry <= 0 or current <= 0:
            return

        pnl_pct = (current / entry) - 1
        held_minutes = int((self.time - self.open_trade["entry_time"]).total_seconds() / 60)
        exit_reason = None
        if pnl_pct <= -self.stop_loss_pct:
            exit_reason = f"stop {pnl_pct:.1%}"
        elif pnl_pct >= self.take_profit_pct:
            exit_reason = f"target {pnl_pct:.1%}"
        elif self.time.hour == 15 and self.time.minute >= 20:
            exit_reason = "end of day"
        elif held_minutes >= self.max_hold_minutes:
            exit_reason = f"time stop {held_minutes}m"

        if exit_reason:
            quantity = int(holding.quantity)
            if quantity == 0:
                self.open_trade = None
                return
            trade = self.open_trade
            trade["exit_order_id"] = -1
            ticket = self.market_order(symbol, -quantity, tag=exit_reason)
            if self.open_trade is trade:
                self.open_trade["exit_order_id"] = ticket.order_id
            self.debug(f"EXIT SUBMITTED {symbol} {exit_reason}")

    def manage_pending_entry(self):
        if self.pending_entry is None:
            return

        if self.time - self.pending_entry["submitted_time"] <= self.entry_order_timeout:
            return

        ticket = self.transactions.get_order_ticket(self.pending_entry["ticket_id"])
        if ticket is not None:
            ticket.cancel("entry order timed out")
        self.debug(f"CANCEL STALE ENTRY {self.pending_entry['symbol']}")
        self.pending_entry = None

    def on_order_event(self, order_event):
        if order_event.status == OrderStatus.INVALID:
            self.debug(f"INVALID ORDER: {order_event}")
            if self.pending_entry is not None and order_event.order_id == self.pending_entry["ticket_id"]:
                self.pending_entry = None
            if self.open_trade is not None and order_event.order_id == self.open_trade.get("exit_order_id"):
                self.open_trade["exit_order_id"] = None
        elif order_event.status == OrderStatus.CANCELED:
            self.debug(f"CANCELED ORDER: {order_event}")
            if self.pending_entry is not None and order_event.order_id == self.pending_entry["ticket_id"]:
                self.pending_entry = None
        elif order_event.status == OrderStatus.FILLED:
            if self.pending_entry is not None and order_event.order_id == self.pending_entry["ticket_id"]:
                fill_price = float(order_event.fill_price)
                if fill_price <= 0:
                    fill_price = self.pending_entry["entry_price"]
                self.open_trade = {
                    "symbol": self.pending_entry["symbol"],
                    "underlying": self.pending_entry["underlying"],
                    "direction": self.pending_entry["direction"],
                    "entry_price": fill_price,
                    "entry_time": self.time,
                    "ticket_id": self.pending_entry["ticket_id"],
                    "exit_order_id": None,
                }
                self.debug(f"FILLED ENTRY {self.open_trade['symbol']} price={fill_price:.2f}")
                self.pending_entry = None
            elif self.open_trade is not None and order_event.symbol == self.open_trade["symbol"] and order_event.fill_quantity < 0:
                self.debug(f"FILLED EXIT {order_event.symbol} price={float(order_event.fill_price):.2f}")
                self.last_exit_date = self.time.date()
                self.open_trade = None

    def on_end_of_algorithm(self):
        if self.pending_entry is not None:
            ticket = self.transactions.get_order_ticket(self.pending_entry["ticket_id"])
            if ticket is not None:
                ticket.cancel("algorithm ended")
            self.pending_entry = None
        if self.open_trade is not None:
            self.debug(f"OPEN AT END {self.open_trade['symbol']}")
            self.open_trade = None
