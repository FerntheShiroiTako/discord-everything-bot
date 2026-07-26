"""Entry point. Loads config, connects the database, loads cogs, and starts the bot."""
import asyncio
import logging
import sys

import discord
from discord.ext import commands

import config
from utils.db import Database

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("bot")

INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.members = True

# Cogs that are always loaded, and cogs that only load themselves if their
# own config.py checks pass (they log a warning and no-op otherwise).
EXTENSIONS = [
    "cogs.logging_cog",
    "cogs.moderation",
    "cogs.automod",
    "cogs.fun",
    "cogs.utility",
    "cogs.ai_chat",
    "cogs.web_search",
]


class EverythingBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned_or(config.COMMAND_PREFIX),
            intents=INTENTS,
            owner_ids=config.OWNER_IDS or None,
            help_command=commands.DefaultHelpCommand(),
        )
        self.db = Database(config.DB_PATH)

    async def setup_hook(self):
        await self.db.connect()
        for extension in EXTENSIONS:
            try:
                await self.load_extension(extension)
                log.info("Loaded extension %s", extension)
            except Exception:
                log.exception("Failed to load extension %s", extension)

        if config.GUILD_ID:
            guild = discord.Object(id=config.GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d application commands to guild %s (instant)", len(synced), config.GUILD_ID)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d application commands globally (can take up to an hour to appear)", len(synced))

    async def close(self):
        await self.db.close()
        await super().close()

    async def on_ready(self):
        log.info("Logged in as %s (%s)", self.user, self.user.id)
        await self.change_presence(activity=discord.Game(name=f"{config.COMMAND_PREFIX}help"))


async def main():
    if not config.DISCORD_TOKEN:
        log.error("DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in.")
        return
    bot = EverythingBot()
    async with bot:
        await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
