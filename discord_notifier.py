import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo


NY_TZ = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class DiscordNotifier:
    webhook_url: str = ""
    bot_token: str = ""
    channel_id: str = ""

    @classmethod
    def from_env(cls) -> "DiscordNotifier":
        return cls(
            webhook_url=(
                os.getenv("DISCORD_TRADE_WEBHOOK_URL")
                or os.getenv("DISCORD_WEBHOOK_URL")
                or ""
            ).strip(),
            bot_token=(os.getenv("DISCORD_TOKEN") or os.getenv("TOKEN") or "").strip(),
            channel_id=(
                os.getenv("DISCORD_TRADE_CHANNEL_ID")
                or os.getenv("DISCORD_CHANNEL_ID")
                or ""
            ).strip(),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url or (self.bot_token and self.channel_id))

    def send(self, content: str) -> None:
        if not self.enabled:
            return
        content = content.strip()
        if not content:
            return
        if len(content) > 1900:
            content = content[:1890] + "\n...[truncated]"

        try:
            if self.webhook_url:
                self._post_json(self.webhook_url, {"content": content})
            else:
                url = f"https://discord.com/api/v10/channels/{self.channel_id}/messages"
                self._post_json(url, {"content": content}, token=self.bot_token)
        except Exception as exc:
            logging.warning("Discord notification failed: %s", exc)

    def trade_entry(self, trade: dict) -> None:
        asset_type = str(trade.get("asset_type", "")).upper() or "TRADE"
        ticker = _clean_symbol(trade.get("ticker") or trade.get("symbol") or "UNKNOWN")
        direction = str(trade.get("direction", "")).upper()
        marker = _direction_marker(direction)
        order_id = trade.get("entry_order_id", "")
        score = _fmt_float(trade.get("score"), 2)
        now = datetime.now(NY_TZ).strftime("%Y-%m-%d %I:%M:%S %p ET")

        if asset_type == "OPTION":
            contracts = trade.get("contracts", "?")
            entry_price = _fmt_money(trade.get("entry_price"))
            cost = _fmt_money(trade.get("notional_cost"))
            symbol = _clean_symbol(trade.get("symbol", ticker))
            strike = _fmt_float(trade.get("strike"), 2)
            dte = trade.get("dte_at_entry", "?")
            self.send(
                f"{marker} **Opened Option Position**\n"
                f"{now}\n"
                f"{ticker} {direction} | `{symbol}`\n"
                f"Contracts: {contracts} | Entry: {entry_price} | Est. cost: {cost}\n"
                f"Strike: {strike} | DTE: {dte} | Score: {score}\n"
                f"Order: `{order_id}`"
            )
            return

        qty = trade.get("qty", "?")
        entry_price = _fmt_money(trade.get("entry_price"))
        self.send(
            f"{marker} **Opened Stock Position**\n"
            f"{now}\n"
            f"{ticker} {direction}\n"
            f"Qty: {qty} | Entry: {entry_price} | Score: {score}\n"
            f"Order: `{order_id}`"
        )

    def trade_exit(self, trade: dict) -> None:
        asset_type = str(trade.get("asset_type", "")).upper() or "TRADE"
        ticker = _clean_symbol(trade.get("ticker") or trade.get("symbol") or "UNKNOWN")
        direction = str(trade.get("direction", "")).upper()
        pnl = _fmt_money(trade.get("pnl"))
        marker = _pnl_marker(trade.get("pnl"))
        return_pct = _fmt_pct(trade.get("return_pct"))
        reason = trade.get("reason", "exit")
        order_id = trade.get("exit_order_id", "")
        held_days = trade.get("held_days", "?")
        now = datetime.now(NY_TZ).strftime("%Y-%m-%d %I:%M:%S %p ET")

        if asset_type == "OPTION":
            symbol = _clean_symbol(trade.get("symbol", ticker))
            contracts = trade.get("contracts", "?")
            self.send(
                f"{marker} **Closed Option Position**\n"
                f"{now}\n"
                f"{ticker} {direction} | `{symbol}`\n"
                f"Contracts: {contracts} | P/L: {pnl} ({return_pct})\n"
                f"Held: {held_days} day(s) | Reason: {reason}\n"
                f"Order: `{order_id}`"
            )
            return

        qty = trade.get("qty", "?")
        self.send(
            f"{marker} **Closed Stock Position**\n"
            f"{now}\n"
            f"{ticker} {direction}\n"
            f"Qty: {qty} | P/L: {pnl} ({return_pct})\n"
            f"Reason: {reason}\n"
            f"Order: `{order_id}`"
        )

    def order_submitted(self, action: str, symbol: str, qty: int, order_id: str, reason: str) -> None:
        now = datetime.now(NY_TZ).strftime("%Y-%m-%d %I:%M:%S %p ET")
        marker = _direction_marker(action)
        self.send(
            f"{marker} **{action} Submitted**\n"
            f"{now}\n"
            f"`{_clean_symbol(symbol)}` qty/contracts: {qty}\n"
            f"Reason: {reason}\n"
            f"Order: `{order_id}`"
        )

    def news_impact(self, alert: dict, mention_user_id: str = "") -> None:
        now = datetime.now(NY_TZ).strftime("%Y-%m-%d %I:%M:%S %p ET")
        mention = f"<@{mention_user_id}> " if mention_user_id else ""
        tickers = ", ".join(f"`{ticker}`" for ticker in alert.get("tickers", [])[:10]) or "`SPY`"
        bias = str(alert.get("bias", "watch")).upper()
        marker = _direction_marker("call" if "bull" in bias.lower() else "put" if "bear" in bias.lower() else "")
        headline = str(alert.get("headline", "News impact alert")).strip()
        evidence = str(alert.get("evidence", "")).strip()
        gex = str(alert.get("gex", "")).strip()
        source = str(alert.get("source", "")).strip()
        rule = str(alert.get("rule", "")).strip()
        content = (
            f"{mention}{marker} **News Impact Alert**\n"
            f"{now}\n"
            f"Bias: **{bias}** | Watch: {tickers}\n"
            f"{headline[:240]}\n"
        )
        if evidence:
            content += f"Read-through: {evidence[:420]}\n"
        if gex:
            content += f"InsiderFinance/GEX: {gex[:420]}\n"
        if rule or source:
            content += f"Rule: `{rule or 'news'}` | Source: {source[:160]}"
        self.send(content)

    @staticmethod
    def _post_json(url: str, payload: dict, token: str = "") -> None:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "quant-trading-bot/1.0",
        }
        if token:
            headers["Authorization"] = f"Bot {token}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                if response.status >= 300:
                    raise RuntimeError(f"Discord returned HTTP {response.status}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Discord returned HTTP {exc.code}: {detail}") from exc


def _fmt_money(value) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "$?"


def _fmt_float(value, digits: int) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "?"


def _fmt_pct(value) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "?%"


def _pnl_marker(value) -> str:
    try:
        return "🔵⬆️" if float(value) >= 0 else "🔴⬇️"
    except (TypeError, ValueError):
        return "🔵⬆️"


def _direction_marker(value) -> str:
    text = str(value or "").upper()
    if "PUT" in text or "SELL" in text or "SHORT" in text:
        return "🔴⬇️"
    return "🔵⬆️"


def _clean_symbol(value) -> str:
    text = str(value or "UNKNOWN").strip().upper()
    return "".join(ch for ch in text if ch.isalnum() or ch in {".", "-", "_"})
