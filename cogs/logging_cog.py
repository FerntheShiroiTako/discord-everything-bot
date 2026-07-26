"""
Central action/event logger.

Every other cog calls `Logging.log_action(...)` to post a formatted embed into
the guild's configured log channel. This cog also listens for raw Discord
events (message edits/deletes, member join/leave, bans) so the log channel
becomes a full audit trail without every other cog needing to hook them.
"""
import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

log = logging.getLogger("bot.logging")

COLOR_INFO = discord.Color.blurple()
COLOR_WARN = discord.Color.gold()
COLOR_DANGER = discord.Color.red()
COLOR_GOOD = discord.Color.green()


class Logging(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _log_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        settings = await self.bot.db.get_settings(guild.id)
        if not settings.log_channel_id:
            return None
        channel = guild.get_channel(settings.log_channel_id)
        return channel if isinstance(channel, discord.TextChannel) else None

    async def log_action(
        self,
        guild: discord.Guild,
        *,
        title: str,
        description: str = "",
        color: discord.Color = COLOR_INFO,
        fields: dict[str, str] | None = None,
        footer: str | None = None,
    ):
        channel = await self._log_channel(guild)
        if channel is None:
            return
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        for name, value in (fields or {}).items():
            embed.add_field(name=name, value=str(value)[:1024], inline=False)
        if footer:
            embed.set_footer(text=footer)
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            log.warning("Missing permission to send in log channel for guild %s", guild.id)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        await self.log_action(
            message.guild,
            title="Message Deleted",
            color=COLOR_WARN,
            fields={
                "Author": f"{message.author} ({message.author.id})",
                "Channel": message.channel.mention,
                "Content": message.content or "*[no text content]*",
            },
        )

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or not before.guild or before.content == after.content:
            return
        await self.log_action(
            before.guild,
            title="Message Edited",
            color=COLOR_INFO,
            fields={
                "Author": f"{before.author} ({before.author.id})",
                "Channel": before.channel.mention,
                "Before": before.content or "*[empty]*",
                "After": after.content or "*[empty]*",
                "Jump": after.jump_url,
            },
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self.log_action(
            member.guild,
            title="Member Joined",
            color=COLOR_GOOD,
            fields={
                "User": f"{member} ({member.id})",
                "Account Created": discord.utils.format_dt(member.created_at, "R"),
            },
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self.log_action(
            member.guild,
            title="Member Left",
            color=COLOR_WARN,
            fields={"User": f"{member} ({member.id})"},
        )

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        await self.log_action(
            guild,
            title="Member Banned",
            color=COLOR_DANGER,
            fields={"User": f"{user} ({user.id})"},
        )

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        await self.log_action(
            guild,
            title="Member Unbanned",
            color=COLOR_GOOD,
            fields={"User": f"{user} ({user.id})"},
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Logging(bot))
