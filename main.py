from AlgorithmImports import *
from datetime import timedelta


class AlpacaPaperOptionsStarter(QCAlgorithm):
    """
    QuantConnect + Alpaca Paper starter.

    Goal:
    - Trade long single-leg SPY/QQQ options only.
    - Use a $1,000 paper account.
    - Keep risk small: max one open option contract.
    - Prefer liquid 21-45 DTE contracts close to 30 delta.
    - Exit with stop, target, time stop, or signal flip.

    Deploy with QuantConnect "Deploy Live" -> Brokerage: Alpaca -> Environment: Paper.
    """

    def initialize(self):
        self.set_start_date(2023, 1, 1)
        self.set_end_date(2026, 6, 1)
        self.set_cash(1000)
        self.set_brokerage_model(BrokerageName.ALPACA, AccountType.MARGIN)
        self.set_time_zone(TimeZones.NEW_YORK)

        self.underlyings = ["SPY", "QQQ"]
        self.symbols = {}
        self.option_symbols = {}
        self.fast_ema = {}
        self.slow_ema = {}
        self.rsi_indicators = {}

        self.max_open_contracts = 1
        self.max_premium_pct = 0.15
        self.max_contract_mid = 1.50
        self.stop_loss_pct = 0.30
        self.take_profit_pct = 0.50
        self.max_hold_days = 5
        self.min_dte = 21
        self.max_dte = 45
        self.target_delta = 0.30
        self.max_spread_pct = 0.20

        self.open_trade = None
        self.last_entry_date = None

        for ticker in self.underlyings:
            equity = self.add_equity(ticker, Resolution.MINUTE)
            equity.set_data_normalization_mode(DataNormalizationMode.RAW)
            self.symbols[ticker] = equity.symbol

            option = self.add_option(ticker, Resolution.MINUTE)
            option.set_filter(self._option_filter)
            try:
                option.price_model = OptionPriceModels.crank_nicolson_fd()
            except Exception:
                pass
            self.option_symbols[ticker] = option.symbol

            self.fast_ema[ticker] = self.ema(equity.symbol, 12, Resolution.MINUTE)
            self.slow_ema[ticker] = self.ema(equity.symbol, 26, Resolution.MINUTE)
            self.rsi_indicators[ticker] = self.rsi(equity.symbol, 14, MovingAverageType.WILDERS, Resolution.MINUTE)

        self.set_warm_up(timedelta(days=5))
        self.schedule.on(
            self.date_rules.every_day("SPY"),
            self.time_rules.every(timedelta(minutes=15)),
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

        self.manage_open_trade()

        if self.open_trade is not None:
            return
        if self.last_entry_date == self.time.date():
            return
        if self.time.hour < 10 or self.time.hour > 15:
            return

        candidate = self.find_best_contract()
        if candidate is None:
            return

        contract, ticker, direction, entry_price, reason = candidate
        if entry_price <= 0:
            return

        max_premium = min(self.portfolio.total_portfolio_value * self.max_premium_pct, 150)
        estimated_debit = entry_price * 100
        if estimated_debit > max_premium:
            self.debug(f"Skip {contract.symbol}: debit ${estimated_debit:.2f} > cap ${max_premium:.2f}")
            return

        ticket = self.limit_order(contract.symbol, 1, round(entry_price, 2), tag=reason)
        self.open_trade = {
            "symbol": contract.symbol,
            "underlying": ticker,
            "direction": direction,
            "entry_price": entry_price,
            "entry_time": self.time,
            "ticket_id": ticket.order_id,
        }
        self.last_entry_date = self.time.date()
        self.debug(f"ENTRY {direction} {contract.symbol} limit={entry_price:.2f} {reason}")

    def find_best_contract(self):
        data = getattr(self, "_latest_slice", None)
        if data is None:
            return None

        best = None
        for ticker in self.underlyings:
            signal = self.get_signal(ticker)
            if signal == "WAIT":
                continue

            chain = data.option_chains.get(self.option_symbols[ticker])
            if chain is None:
                continue

            right = OptionRight.CALL if signal == "CALL" else OptionRight.PUT
            contracts = [contract for contract in chain if contract.right == right]
            contracts = [contract for contract in contracts if self.min_dte <= (contract.expiry.date() - self.time.date()).days <= self.max_dte]
            contracts = [contract for contract in contracts if self.contract_is_tradeable(contract)]
            if not contracts:
                continue

            selected = min(contracts, key=lambda contract: self.delta_distance(contract))
            bid = float(selected.bid_price)
            ask = float(selected.ask_price)
            mid = (bid + ask) / 2
            entry_price = round(ask, 2)
            score = self.contract_score(selected, signal, mid)
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

        fast = self.fast_ema[ticker].current.value
        slow = self.slow_ema[ticker].current.value
        rsi = self.rsi_indicators[ticker].current.value

        if fast > slow and 50 <= rsi <= 68:
            return "CALL"
        if fast < slow and 32 <= rsi <= 50:
            return "PUT"
        return "WAIT"

    def contract_is_tradeable(self, contract):
        bid = float(contract.bid_price)
        ask = float(contract.ask_price)
        if bid <= 0 or ask <= 0 or ask < bid:
            return False
        mid = (bid + ask) / 2
        if mid <= 0 or mid > self.max_contract_mid:
            return False
        spread_pct = (ask - bid) / mid
        if spread_pct > self.max_spread_pct:
            return False
        return True

    def delta_distance(self, contract):
        delta = self.safe_delta(contract)
        if delta is None:
            return 999
        return abs(abs(delta) - self.target_delta)

    def contract_score(self, contract, signal, mid):
        spread = (float(contract.ask_price) - float(contract.bid_price)) / mid if mid > 0 else 1
        dte = (contract.expiry.date() - self.time.date()).days
        delta = self.safe_delta(contract)
        delta_score = 1 - min(abs(abs(delta or 0) - self.target_delta), 0.50)
        dte_score = 1 - min(abs(dte - 30) / 30, 1)
        spread_score = 1 - min(spread / self.max_spread_pct, 1)
        return (delta_score * 0.45) + (dte_score * 0.25) + (spread_score * 0.30)

    def safe_delta(self, contract):
        try:
            return float(contract.greeks.delta)
        except Exception:
            return None

    def manage_open_trade(self):
        if self.open_trade is None:
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
        held_days = (self.time - self.open_trade["entry_time"]).days
        signal = self.get_signal(str(self.open_trade["underlying"]))
        direction = self.open_trade["direction"]

        exit_reason = None
        if pnl_pct <= -self.stop_loss_pct:
            exit_reason = f"stop {pnl_pct:.1%}"
        elif pnl_pct >= self.take_profit_pct:
            exit_reason = f"target {pnl_pct:.1%}"
        elif held_days >= self.max_hold_days:
            exit_reason = f"time stop {held_days}d"
        elif direction == "CALL" and signal == "PUT":
            exit_reason = "signal flipped bearish"
        elif direction == "PUT" and signal == "CALL":
            exit_reason = "signal flipped bullish"

        if exit_reason:
            self.liquidate(symbol, tag=exit_reason)
            self.debug(f"EXIT {symbol} {exit_reason}")
            self.open_trade = None

    def on_order_event(self, order_event):
        if order_event.status == OrderStatus.INVALID:
            self.debug(f"INVALID ORDER: {order_event}")
            self.open_trade = None
        elif order_event.status == OrderStatus.CANCELED:
            self.debug(f"CANCELED ORDER: {order_event}")
            self.open_trade = None
