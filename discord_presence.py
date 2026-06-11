import asyncio
import json
import logging
import os
from pathlib import Path
import threading

from discord_notifier import DiscordNotifier
from pretrade_research import format_research_summary


def _enabled() -> bool:
    value = os.getenv("DISCORD_SHOW_ONLINE", "true")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def start_discord_presence() -> None:
    token = (os.getenv("DISCORD_TOKEN") or os.getenv("TOKEN") or "").strip()
    if not _enabled():
        logging.info("Discord presence disabled by DISCORD_SHOW_ONLINE.")
        return
    if not token:
        logging.warning("Discord presence not started: set DISCORD_TOKEN or TOKEN in Railway Variables.")
        return

    thread = threading.Thread(target=_run_presence_client, args=(token,), name="discord-presence", daemon=True)
    thread.start()
    logging.info("Discord presence thread started.")


def _run_presence_client(token: str) -> None:
    try:
        import discord
        from discord import app_commands
    except Exception as exc:
        logging.warning("Discord online presence disabled because discord.py is unavailable: %s", exc)
        return

    intents = discord.Intents.none()
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)
    notifier = DiscordNotifier.from_env()

    @tree.command(name="researchplan", description="Show the bot's ticker research and next-session plan.")
    async def researchplan(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(build_research_plan_message(), ephemeral=True)

    @client.event
    async def on_ready():
        logging.info("Discord presence online as %s", client.user)
        await update_profit_presence(client, discord)
        await sync_research_command(tree)
        if env_enabled("DISCORD_ANNOUNCE_ONLINE", False):
            notifier.send(f"**Trading bot is online**\nLogged in as `{client.user}`.")
        if not getattr(client, "_presence_loop_started", False):
            client._presence_loop_started = True
            client.loop.create_task(presence_loop(client, discord))

    try:
        asyncio.run(client.start(token))
    except Exception as exc:
        logging.exception("Discord presence client stopped: %s", exc)


async def presence_loop(client, discord_module) -> None:
    interval = max(60, int(float(os.getenv("DISCORD_STATUS_REFRESH_SECONDS", "300"))))
    while not client.is_closed():
        await asyncio.sleep(interval)
        await update_profit_presence(client, discord_module)


async def update_profit_presence(client, discord_module) -> None:
    try:
        pnl = all_time_pnl()
        marker = "🔵" if pnl >= 0 else "🔴"
        label = f"{marker} All-time P/L {format_money(pnl)}"
        activity = discord_module.Activity(type=discord_module.ActivityType.watching, name=label[:120])
        await client.change_presence(status=discord_module.Status.online, activity=activity)
    except Exception as exc:
        logging.warning("Could not set Discord P/L presence: %s", exc)


async def sync_research_command(tree) -> None:
    if not env_enabled("DISCORD_ENABLE_RESEARCH_COMMAND", True):
        logging.info("Discord /researchplan command disabled.")
        return
    try:
        guild_id = (os.getenv("DISCORD_COMMAND_GUILD_ID") or os.getenv("GUILD_ID") or "").strip()
        if guild_id:
            import discord

            guild = discord.Object(id=int(guild_id))
            tree.copy_global_to(guild=guild)
            synced = await tree.sync(guild=guild)
            logging.info("Synced %d Discord guild command(s) for %s.", len(synced), guild_id)
            return
        synced = await tree.sync()
        logging.info("Synced %d Discord global command(s).", len(synced))
    except Exception as exc:
        logging.exception("Discord command sync failed: %s", exc)


def env_enabled(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_research_plan_message() -> str:
    payload = read_json_env_path("BOT_TICKER_RESEARCH_PATH", "ticker_research.json")
    state = read_json_env_path("BOT_STATE_PATH", "alpaca_stock_bot_state.json")
    if not payload:
        return (
            "**Research plan**\n"
            "No ticker research file exists yet. It should appear after the overnight research loop runs, "
            "or after `python pretrade_research.py` is run locally."
        )

    lines = ["**Research plan**"]
    lines.append(f"All-time P/L: `{format_money(all_time_pnl())}`")
    lines.append(format_research_summary(payload, max_tickers=8, include_news=True))

    scan = state.get("last_option_scan") if isinstance(state, dict) else {}
    best_scan = (scan or {}).get("best")
    if best_scan:
        lines.append("")
        lines.append(
            "**Latest live scan** "
            f"`{best_scan.get('ticker')}` `{best_scan.get('direction')}` score `{float(best_scan.get('score', 0.0)):.2f}`"
        )

    text = "\n".join(lines)
    if len(text) > 1900:
        text = text[:1850].rstrip() + "\n...trimmed"
    return text


def read_json_env_path(env_name: str, default: str) -> dict:
    path = Path(os.getenv(env_name, default))
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        return payload if isinstance(payload, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logging.info("Could not read %s at %s: %s", env_name, path, exc)
        return {}


def all_time_pnl() -> float:
    state = read_json_env_path("BOT_STATE_PATH", "alpaca_stock_bot_state.json")
    trade_history = state.get("trade_history") if isinstance(state, dict) else {}
    trades = (trade_history or {}).get("closed_trades") or []
    total = 0.0
    for trade in trades:
        try:
            total += float(trade.get("pnl", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
    return total


def format_money(value: float) -> str:
    sign = "+" if value >= 0 else "-"
    return f"{sign}${abs(value):,.2f}"
