"""
Automatic moderation: spam/mention flooding, invite links, banned words, and
an optional image moderation hook for explicit content.

Image moderation is NOT a custom CSAM classifier - that is neither safe nor
legal for a hobby project to build, since it would require possessing illegal
material to train or test against. Instead this cog can call a vetted,
licensed third-party moderation API (Sightengine or Hive) that offers
nudity/explicit and child-safety-specific classifiers built for exactly this
purpose. If IMAGE_MOD_PROVIDER is unset, this feature is skipped entirely and
you should rely on Discord's own built-in Explicit Media Content Filter
(Server Settings, Safety Setup), which runs platform-wide with NCMEC-integrated
hash matching regardless of any bot. Enable that regardless of what you decide
here - it is the actual backstop.
"""
import logging
import re
import time
from collections import defaultdict, deque

import aiohttp
import discord
from discord.ext import commands

import config
from utils.checks import is_admin

log = logging.getLogger("bot.automod")

INVITE_RE = re.compile(r"(discord\.gg|discordapp\.com/invite|discord\.com/invite)/\S+", re.IGNORECASE)
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")


class Automod(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: aiohttp.ClientSession | None = None
        self._recent_messages: dict[tuple[int, int], deque] = defaultdict(deque)

    async def cog_load(self):
        self.session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self.session:
            await self.session.close()

    async def _logging_cog(self):
        return self.bot.get_cog("Logging")

    async def _alert(self, guild: discord.Guild, **kwargs):
        logging_cog = await self._logging_cog()
        if logging_cog:
            await logging_cog.log_action(guild, **kwargs)

    def _is_exempt(self, message: discord.Message) -> bool:
        if message.author.bot:
            return True
        if not message.guild:
            return True
        perms = message.author.guild_permissions
        return perms.manage_messages or perms.administrator

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if self._is_exempt(message):
            return

        settings = await self.bot.db.get_settings(message.guild.id)
        if not settings.automod_enabled:
            return

        if await self._check_spam(message, settings):
            return
        if await self._check_invites(message, settings):
            return
        if await self._check_banned_words(message, settings):
            return
        if await self._check_mentions(message, settings):
            return
        await self._check_images(message, settings)

    async def _delete_and_warn(self, message: discord.Message, reason: str):
        try:
            await message.delete()
        except discord.NotFound:
            pass
        try:
            await message.channel.send(
                f"{message.author.mention}, your message was removed: {reason}", delete_after=8
            )
        except discord.Forbidden:
            pass

    async def _check_spam(self, message: discord.Message, settings) -> bool:
        if not settings.spam_filter_enabled:
            return False
        key = (message.guild.id, message.author.id)
        history = self._recent_messages[key]
        now = time.monotonic()
        history.append(now)
        while history and now - history[0] > config.AUTOMOD_SPAM_INTERVAL_SECS:
            history.popleft()
        if len(history) >= config.AUTOMOD_SPAM_MSG_COUNT:
            history.clear()
            await self._delete_and_warn(message, "sending messages too quickly")
            await self._alert(
                message.guild,
                title="Automod: Spam Detected",
                color=discord.Color.gold(),
                fields={"User": f"{message.author} ({message.author.id})", "Channel": message.channel.mention},
            )
            return True
        return False

    async def _check_mentions(self, message: discord.Message, settings) -> bool:
        total_mentions = len(message.mentions) + len(message.role_mentions)
        if total_mentions >= config.AUTOMOD_MAX_MENTIONS:
            await self._delete_and_warn(message, "mass mentioning")
            await self._alert(
                message.guild,
                title="Automod: Mass Mention",
                color=discord.Color.gold(),
                fields={
                    "User": f"{message.author} ({message.author.id})",
                    "Channel": message.channel.mention,
                    "Mentions": total_mentions,
                },
            )
            return True
        return False

    async def _check_invites(self, message: discord.Message, settings) -> bool:
        if not settings.invite_filter_enabled:
            return False
        if INVITE_RE.search(message.content):
            await self._delete_and_warn(message, "posting a Discord invite link")
            await self._alert(
                message.guild,
                title="Automod: Invite Link Removed",
                color=discord.Color.gold(),
                fields={
                    "User": f"{message.author} ({message.author.id})",
                    "Channel": message.channel.mention,
                    "Content": message.content,
                },
            )
            return True
        return False

    async def _check_banned_words(self, message: discord.Message, settings) -> bool:
        if not settings.banned_words:
            return False
        content_lower = message.content.lower()
        for word in settings.banned_words:
            if word.lower() in content_lower:
                await self._delete_and_warn(message, "using a banned word")
                await self._alert(
                    message.guild,
                    title="Automod: Banned Word",
                    color=discord.Color.gold(),
                    fields={
                        "User": f"{message.author} ({message.author.id})",
                        "Channel": message.channel.mention,
                        "Matched": word,
                    },
                )
                return True
        return False

    async def _check_images(self, message: discord.Message, settings):
        if not settings.image_mod_enabled or not config.IMAGE_MOD_PROVIDER:
            return
        for attachment in message.attachments:
            if not attachment.filename.lower().endswith(IMAGE_EXTENSIONS):
                continue
            try:
                flagged, detail = await self._moderate_image(attachment.url)
            except Exception:
                log.exception("Image moderation API call failed")
                continue
            if flagged:
                try:
                    await message.delete()
                except discord.NotFound:
                    pass
                try:
                    await message.author.ban(
                        reason=f"Automod: image flagged by {config.IMAGE_MOD_PROVIDER} ({detail})"
                    )
                except discord.Forbidden:
                    log.warning("Missing permission to ban after image flag in guild %s", message.guild.id)
                await self._alert(
                    message.guild,
                    title="Automod: Explicit Image Flagged - User Banned",
                    color=discord.Color.red(),
                    fields={
                        "User": f"{message.author} ({message.author.id})",
                        "Channel": message.channel.mention,
                        "Detail": detail,
                    },
                    footer="Consider also using Discord's built-in Report Message action to escalate to Discord Trust & Safety.",
                )
                return

    async def _moderate_image(self, url: str) -> tuple[bool, str]:
        """Returns (flagged, detail). Raises on API/network failure."""
        if config.IMAGE_MOD_PROVIDER == "sightengine":
            return await self._moderate_sightengine(url)
        if config.IMAGE_MOD_PROVIDER == "hive":
            return await self._moderate_hive(url)
        return False, "no provider configured"

    async def _moderate_sightengine(self, url: str) -> tuple[bool, str]:
        params = {
            "url": url,
            "models": "nudity-2.1,offensive",
            "api_user": config.SIGHTENGINE_API_USER,
            "api_secret": config.SIGHTENGINE_API_SECRET,
        }
        async with self.session.get("https://api.sightengine.com/1.0/check.json", params=params) as resp:
            data = await resp.json()
        nudity = data.get("nudity", {})
        score = max(nudity.get("sexual_activity", 0), nudity.get("sexual_display", 0), nudity.get("erotica", 0))
        flagged = score >= config.IMAGE_MOD_NUDITY_THRESHOLD
        return flagged, f"nudity score {score:.2f}"

    async def _moderate_hive(self, url: str) -> tuple[bool, str]:
        headers = {"Authorization": f"Token {config.HIVE_API_KEY}"}
        payload = {"url": url}
        async with self.session.post(
            "https://api.thehive.ai/api/v2/task/sync", headers=headers, data=payload
        ) as resp:
            data = await resp.json()
        try:
            classes = data["status"][0]["response"]["output"][0]["classes"]
        except (KeyError, IndexError):
            return False, "unrecognized API response"
        scores = {c["class"]: c["score"] for c in classes}
        explicit_score = max(scores.get("general_nsfw", 0), scores.get("yes_sexual_activity", 0), scores.get("yes_undressed", 0))
        flagged = explicit_score >= config.IMAGE_MOD_NUDITY_THRESHOLD
        return flagged, f"explicit score {explicit_score:.2f}"

    @commands.hybrid_group(description="Configure automod for this server.")
    @is_admin()
    async def automod(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            settings = await self.bot.db.get_settings(ctx.guild.id)
            embed = discord.Embed(title="Automod Settings", color=discord.Color.blurple())
            embed.add_field(name="Enabled", value=settings.automod_enabled)
            embed.add_field(name="Spam Filter", value=settings.spam_filter_enabled)
            embed.add_field(name="Invite Filter", value=settings.invite_filter_enabled)
            embed.add_field(name="Link Filter", value=settings.link_filter_enabled)
            embed.add_field(name="Image Moderation", value=settings.image_mod_enabled)
            embed.add_field(name="Banned Words", value=str(len(settings.banned_words)))
            await ctx.reply(embed=embed)

    @automod.command(name="toggle", description="Enable or disable automod entirely.")
    @is_admin()
    async def automod_toggle(self, ctx: commands.Context, enabled: bool):
        await self.bot.db.update_settings(ctx.guild.id, automod_enabled=enabled)
        await ctx.reply(f"Automod is now {'enabled' if enabled else 'disabled'}.")

    @automod.command(name="images", description="Enable or disable image moderation (requires IMAGE_MOD_PROVIDER configured).")
    @is_admin()
    async def automod_images(self, ctx: commands.Context, enabled: bool):
        if enabled and not config.IMAGE_MOD_PROVIDER:
            return await ctx.reply(
                "No image moderation provider is configured on the bot (IMAGE_MOD_PROVIDER in .env). "
                "Set that up first, and make sure Discord's own Explicit Media Content Filter is enabled "
                "in Server Settings > Safety Setup.",
                ephemeral=True,
            )
        await self.bot.db.update_settings(ctx.guild.id, image_mod_enabled=enabled)
        await ctx.reply(f"Image moderation is now {'enabled' if enabled else 'disabled'}.")

    @automod.command(name="addword", description="Add a word/phrase to the banned words list.")
    @is_admin()
    async def automod_addword(self, ctx: commands.Context, *, word: str):
        settings = await self.bot.db.get_settings(ctx.guild.id)
        words = settings.banned_words
        if word.lower() in [w.lower() for w in words]:
            return await ctx.reply("That word is already banned.", ephemeral=True)
        words.append(word)
        await self.bot.db.update_settings(ctx.guild.id, banned_words=words)
        await ctx.reply(f"Added `{word}` to the banned words list.", ephemeral=True)

    @automod.command(name="removeword", description="Remove a word/phrase from the banned words list.")
    @is_admin()
    async def automod_removeword(self, ctx: commands.Context, *, word: str):
        settings = await self.bot.db.get_settings(ctx.guild.id)
        words = [w for w in settings.banned_words if w.lower() != word.lower()]
        await self.bot.db.update_settings(ctx.guild.id, banned_words=words)
        await ctx.reply(f"Removed `{word}` from the banned words list.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Automod(bot))
