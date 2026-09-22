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
    "cogs.config",
    "cogs.moderation",
    "cogs.automod",
    "cogs.fun",
    "cogs.utility",
    "cogs.ai_chat",
    "cogs.web_search",
    "cogs.music",
]
# leave while you still can on god please leave its not worth it

WELCOME_MESSAGE = (
    "Thanks for adding me! Run **/setup** in this server to walk through the essentials "
    "(log channel, automod, AI chat) in one go, or **/config** any time after to fine-tune things."
)


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

        # Global sync makes commands work in every server the bot is in, present
        # or future - this is what "any server" support depends on. It can take
        # up to an hour to propagate after the command set changes, but that's a
        # one-time cost per change, not a startup cost.
        try:
            synced = await self.tree.sync()
            log.info("Synced %d application commands globally (can take up to an hour to appear for new commands)", len(synced))
        except discord.HTTPException:
            log.exception("Global command sync failed")

        # GUILD_ID is optional and dev-only: it additionally pushes an instant
        # copy of the same commands to one home guild so you see changes right
        # away while iterating, without touching global availability elsewhere.
        if config.GUILD_ID:
            guild = discord.Object(id=config.GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            try:
                synced = await self.tree.sync(guild=guild)
                log.info("Synced %d application commands to guild %s (instant)", len(synced), config.GUILD_ID)
            except discord.Forbidden:
                log.error(
                    "Guild command sync failed with 403 Forbidden - the bot's server invite is missing the "
                    "'applications.commands' OAuth2 scope. Fix: Discord Developer Portal > OAuth2 > URL Generator, "
                    "check both 'bot' and 'applications.commands', then open the generated URL to re-authorize it "
                    "for this server (no need to remove the bot first). Global command sync already succeeded, so "
                    "every other server the bot is in is unaffected."
                )

    async def close(self):
        await self.db.close()
        await super().close()

    async def on_ready(self):
        log.info("Logged in as %s (%s)", self.user, self.user.id)
        await self.change_presence(activity=discord.Game(name=f"{config.COMMAND_PREFIX}help"))

    async def on_guild_join(self, guild: discord.Guild):
        log.info("Joined guild %s (%s)", guild.name, guild.id)
        await self.db.get_settings(guild.id)  # create its settings row up front

        target = guild.system_channel
        if target is None or not target.permissions_for(guild.me).send_messages:
            target = next(
                (c for c in guild.text_channels if c.permissions_for(guild.me).send_messages),
                None,
            )
        if target:
            try:
                await target.send(WELCOME_MESSAGE)
            except discord.Forbidden:
                pass

    async def on_guild_remove(self, guild: discord.Guild):
        log.info("Removed from guild %s (%s)", guild.name, guild.id)
        self.db.drop_cache(guild.id)


async def main():
    if not config.DISCORD_TOKEN:
        log.error("DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in.")
        return
    bot = EverythingBot()
    async with bot:
        await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
