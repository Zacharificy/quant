import asyncio
import logging
import os
import threading

from discord_notifier import DiscordNotifier


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
    except Exception as exc:
        logging.warning("Discord online presence disabled because discord.py is unavailable: %s", exc)
        return

    intents = discord.Intents.none()
    client = discord.Client(intents=intents)
    notifier = DiscordNotifier.from_env()

    @client.event
    async def on_ready():
        logging.info("Discord presence online as %s", client.user)
        try:
            activity = discord.Activity(type=discord.ActivityType.watching, name="paper trades")
            await client.change_presence(status=discord.Status.online, activity=activity)
        except Exception as exc:
            logging.warning("Could not set Discord presence: %s", exc)
        notifier.send(f"**Trading bot is online**\nLogged in as `{client.user}`.")

    try:
        asyncio.run(client.start(token))
    except Exception as exc:
        logging.exception("Discord presence client stopped: %s", exc)
