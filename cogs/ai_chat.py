"""
Chatbot cog backed by OpenAI (ChatGPT) or xAI (Grok). Both APIs are OpenAI
compatible, so a single client with a swapped base_url and key covers either
provider - see config.AI_PROVIDER.

The bot replies when it's mentioned, when a message is a reply to one of its
own messages, or in a designated channel (set with /ai setchannel). Short
per-channel history is kept in memory only, so it resets on restart.
"""
import logging
from collections import defaultdict, deque

import discord
from discord.ext import commands
from openai import AsyncOpenAI

import config

log = logging.getLogger("bot.ai_chat")


def _build_client() -> AsyncOpenAI | None:
    if config.AI_PROVIDER == "openai" and config.OPENAI_API_KEY:
        return AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    if config.AI_PROVIDER == "xai" and config.XAI_API_KEY:
        return AsyncOpenAI(api_key=config.XAI_API_KEY, base_url="https://api.x.ai/v1")
    return None


class AIChat(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.client = _build_client()
        self.model = config.OPENAI_MODEL if config.AI_PROVIDER == "openai" else config.XAI_MODEL
        self.history: dict[int, deque] = defaultdict(lambda: deque(maxlen=config.AI_HISTORY_LENGTH))

    def _should_respond(self, message: discord.Message, settings) -> bool:
        if self.bot.user in message.mentions:
            return True
        if message.reference and isinstance(message.reference.resolved, discord.Message):
            if message.reference.resolved.author.id == self.bot.user.id:
                return True
        if settings.ai_enabled and settings.ai_channel_id == message.channel.id:
            return True
        return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or self.client is None:
            return
        settings = await self.bot.db.get_settings(message.guild.id)
        if not self._should_respond(message, settings):
            return

        content = message.content
        for mention in message.mentions:
            content = content.replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
        content = content.strip()
        if not content:
            return

        async with message.channel.typing():
            reply = await self._ask(message.channel.id, message.author.display_name, content)

        if reply:
            for chunk_start in range(0, len(reply), 2000):
                await message.reply(reply[chunk_start:chunk_start + 2000], mention_author=False)

    async def _ask(self, channel_id: int, author_name: str, content: str) -> str | None:
        history = self.history[channel_id]
        history.append({"role": "user", "content": f"{author_name}: {content}"})

        messages = [{"role": "system", "content": config.AI_SYSTEM_PROMPT}] + list(history)

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=config.AI_MAX_TOKENS,
            )
        except Exception:
            log.exception("AI provider request failed")
            return "Sorry, I couldn't reach the AI provider just now."

        reply = response.choices[0].message.content
        history.append({"role": "assistant", "content": reply})
        return reply

    @commands.hybrid_group(description="Configure the AI chatbot for this server.")
    @commands.has_permissions(manage_guild=True)
    async def ai(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            settings = await self.bot.db.get_settings(ctx.guild.id)
            channel = ctx.guild.get_channel(settings.ai_channel_id) if settings.ai_channel_id else None
            await ctx.reply(
                f"AI chat: {'enabled' if settings.ai_enabled else 'disabled'} in "
                f"{channel.mention if channel else 'no channel set'}. "
                f"Provider: {config.AI_PROVIDER or 'not configured'}."
            )

    @ai.command(name="setchannel", description="Set the channel where the bot always responds without needing a mention.")
    async def ai_setchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        await self.bot.db.update_settings(ctx.guild.id, ai_channel_id=channel.id, ai_enabled=True)
        await ctx.reply(f"AI chat is now active in {channel.mention}. It'll also always respond to mentions/replies anywhere.")

    @ai.command(name="toggle", description="Enable or disable the always-on AI channel (mentions/replies still work).")
    async def ai_toggle(self, ctx: commands.Context, enabled: bool):
        await self.bot.db.update_settings(ctx.guild.id, ai_enabled=enabled)
        await ctx.reply(f"AI channel mode is now {'enabled' if enabled else 'disabled'}.")


async def setup(bot: commands.Bot):
    if _build_client() is None:
        log.warning("AI_PROVIDER not configured or missing API key - AIChat cog not loaded.")
        return
    await bot.add_cog(AIChat(bot))
