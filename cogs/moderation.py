"""Core moderation commands: kick, ban, timeout, warn, purge, slowmode, lock."""
import logging
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import is_mod

log = logging.getLogger("bot.moderation")


async def _get_logging(bot: commands.Bot):
    return bot.get_cog("Logging")


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(description="Kick a member from the server.")
    @app_commands.describe(member="The member to kick", reason="Why they're being kicked")
    @is_mod()
    @commands.bot_has_permissions(kick_members=True)
    async def kick(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided"):
        if member.top_role >= ctx.author.top_role and ctx.author.id not in self.bot.owner_ids:
            return await ctx.reply("You can't kick someone with an equal or higher role than you.", ephemeral=True)
        await member.kick(reason=f"{ctx.author} ({ctx.author.id}): {reason}")
        await ctx.reply(f"Kicked {member.mention}. Reason: {reason}")
        logging_cog = await _get_logging(self.bot)
        if logging_cog:
            await logging_cog.log_action(
                ctx.guild,
                title="Member Kicked",
                color=discord.Color.orange(),
                fields={"User": f"{member} ({member.id})", "Moderator": str(ctx.author), "Reason": reason},
            )

    @commands.hybrid_command(description="Ban a member from the server.")
    @app_commands.describe(member="The member to ban", reason="Why they're being banned", delete_days="Days of message history to delete (0-7)")
    @is_mod()
    @commands.bot_has_permissions(ban_members=True)
    async def ban(self, ctx: commands.Context, member: discord.Member, delete_days: commands.Range[int, 0, 7] = 0, *, reason: str = "No reason provided"):
        if member.top_role >= ctx.author.top_role and ctx.author.id not in self.bot.owner_ids:
            return await ctx.reply("You can't ban someone with an equal or higher role than you.", ephemeral=True)
        await member.ban(reason=f"{ctx.author} ({ctx.author.id}): {reason}", delete_message_seconds=delete_days * 86400)
        await ctx.reply(f"Banned {member.mention}. Reason: {reason}")
        logging_cog = await _get_logging(self.bot)
        if logging_cog:
            await logging_cog.log_action(
                ctx.guild,
                title="Member Banned",
                color=discord.Color.red(),
                fields={"User": f"{member} ({member.id})", "Moderator": str(ctx.author), "Reason": reason},
            )

    @commands.hybrid_command(description="Unban a user by ID.")
    @app_commands.describe(user_id="The Discord user ID to unban", reason="Why they're being unbanned")
    @is_mod()
    @commands.bot_has_permissions(ban_members=True)
    async def unban(self, ctx: commands.Context, user_id: str, *, reason: str = "No reason provided"):
        try:
            user = await self.bot.fetch_user(int(user_id))
        except (ValueError, discord.NotFound):
            return await ctx.reply("That doesn't look like a valid user ID that's currently banned.", ephemeral=True)
        await ctx.guild.unban(user, reason=f"{ctx.author} ({ctx.author.id}): {reason}")
        await ctx.reply(f"Unbanned {user}.")
        logging_cog = await _get_logging(self.bot)
        if logging_cog:
            await logging_cog.log_action(
                ctx.guild,
                title="Member Unbanned",
                color=discord.Color.green(),
                fields={"User": f"{user} ({user.id})", "Moderator": str(ctx.author), "Reason": reason},
            )

    @commands.hybrid_command(description="Timeout (mute) a member for a duration in minutes.")
    @app_commands.describe(member="The member to time out", minutes="Duration in minutes (max 40320 = 28 days)", reason="Why they're being timed out")
    @is_mod()
    @commands.bot_has_permissions(moderate_members=True)
    async def timeout(self, ctx: commands.Context, member: discord.Member, minutes: commands.Range[int, 1, 40320], *, reason: str = "No reason provided"):
        if member.top_role >= ctx.author.top_role and ctx.author.id not in self.bot.owner_ids:
            return await ctx.reply("You can't time out someone with an equal or higher role than you.", ephemeral=True)
        await member.timeout(timedelta(minutes=minutes), reason=f"{ctx.author} ({ctx.author.id}): {reason}")
        await ctx.reply(f"Timed out {member.mention} for {minutes} minute(s). Reason: {reason}")
        logging_cog = await _get_logging(self.bot)
        if logging_cog:
            await logging_cog.log_action(
                ctx.guild,
                title="Member Timed Out",
                color=discord.Color.orange(),
                fields={"User": f"{member} ({member.id})", "Moderator": str(ctx.author), "Duration": f"{minutes} min", "Reason": reason},
            )

    @commands.hybrid_command(description="Remove an active timeout from a member.")
    @app_commands.describe(member="The member to remove the timeout from")
    @is_mod()
    @commands.bot_has_permissions(moderate_members=True)
    async def untimeout(self, ctx: commands.Context, member: discord.Member):
        await member.timeout(None, reason=f"Timeout removed by {ctx.author} ({ctx.author.id})")
        await ctx.reply(f"Removed timeout from {member.mention}.")
        logging_cog = await _get_logging(self.bot)
        if logging_cog:
            await logging_cog.log_action(
                ctx.guild,
                title="Timeout Removed",
                color=discord.Color.green(),
                fields={"User": f"{member} ({member.id})", "Moderator": str(ctx.author)},
            )

    @commands.hybrid_command(description="Warn a member. Warnings are stored and viewable with /warnings.")
    @app_commands.describe(member="The member to warn", reason="Why they're being warned")
    @is_mod()
    async def warn(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided"):
        warn_id = await self.bot.db.add_warning(ctx.guild.id, member.id, ctx.author.id, reason)
        await ctx.reply(f"Warned {member.mention} (warning #{warn_id}). Reason: {reason}")
        try:
            await member.send(f"You were warned in **{ctx.guild.name}**: {reason}")
        except discord.Forbidden:
            pass
        logging_cog = await _get_logging(self.bot)
        if logging_cog:
            await logging_cog.log_action(
                ctx.guild,
                title="Member Warned",
                color=discord.Color.gold(),
                fields={"User": f"{member} ({member.id})", "Moderator": str(ctx.author), "Reason": reason, "Warning ID": warn_id},
            )

    @commands.hybrid_command(description="List a member's warnings.")
    @app_commands.describe(member="The member to look up")
    @is_mod()
    async def warnings(self, ctx: commands.Context, member: discord.Member):
        rows = await self.bot.db.get_warnings(ctx.guild.id, member.id)
        if not rows:
            return await ctx.reply(f"{member.mention} has no warnings.")
        embed = discord.Embed(title=f"Warnings for {member}", color=discord.Color.gold())
        for row in rows[:25]:
            mod = ctx.guild.get_member(row["moderator_id"])
            embed.add_field(
                name=f"#{row['id']} - <t:{row['created_at']}:R>",
                value=f"By {mod.mention if mod else row['moderator_id']}: {row['reason']}",
                inline=False,
            )
        await ctx.reply(embed=embed)

    @commands.hybrid_command(description="Clear all warnings for a member.")
    @app_commands.describe(member="The member whose warnings should be cleared")
    @is_mod()
    async def clearwarnings(self, ctx: commands.Context, member: discord.Member):
        count = await self.bot.db.clear_warnings(ctx.guild.id, member.id)
        await ctx.reply(f"Cleared {count} warning(s) for {member.mention}.")
        logging_cog = await _get_logging(self.bot)
        if logging_cog:
            await logging_cog.log_action(
                ctx.guild,
                title="Warnings Cleared",
                color=discord.Color.green(),
                fields={"User": f"{member} ({member.id})", "Moderator": str(ctx.author), "Count": count},
            )

    @commands.hybrid_command(description="Bulk delete recent messages in this channel.")
    @app_commands.describe(amount="How many messages to delete (1-100)", member="Only delete messages from this member")
    @is_mod()
    @commands.bot_has_permissions(manage_messages=True)
    async def purge(self, ctx: commands.Context, amount: commands.Range[int, 1, 100], member: discord.Member = None):
        await ctx.defer(ephemeral=True)

        def check(msg: discord.Message) -> bool:
            return member is None or msg.author.id == member.id

        deleted = await ctx.channel.purge(limit=amount, check=check)
        await ctx.reply(f"Deleted {len(deleted)} message(s).", ephemeral=True)
        logging_cog = await _get_logging(self.bot)
        if logging_cog:
            await logging_cog.log_action(
                ctx.guild,
                title="Messages Purged",
                color=discord.Color.orange(),
                fields={
                    "Channel": ctx.channel.mention,
                    "Moderator": str(ctx.author),
                    "Count": len(deleted),
                    "Filtered To": str(member) if member else "everyone",
                },
            )

    @commands.hybrid_command(description="Set this channel's slowmode delay in seconds (0 to disable).")
    @app_commands.describe(seconds="Seconds between messages per user, 0-21600")
    @is_mod()
    @commands.bot_has_permissions(manage_channels=True)
    async def slowmode(self, ctx: commands.Context, seconds: commands.Range[int, 0, 21600]):
        await ctx.channel.edit(slowmode_delay=seconds)
        await ctx.reply(f"Slowmode set to {seconds} second(s) in {ctx.channel.mention}.")

    @commands.hybrid_command(description="Lock this channel so @everyone can't send messages.")
    @is_mod()
    @commands.bot_has_permissions(manage_roles=True)
    async def lock(self, ctx: commands.Context):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await ctx.reply(f"{ctx.channel.mention} is now locked.")
        logging_cog = await _get_logging(self.bot)
        if logging_cog:
            await logging_cog.log_action(
                ctx.guild,
                title="Channel Locked",
                color=discord.Color.orange(),
                fields={"Channel": ctx.channel.mention, "Moderator": str(ctx.author)},
            )

    @commands.hybrid_command(description="Unlock this channel so @everyone can send messages again.")
    @is_mod()
    @commands.bot_has_permissions(manage_roles=True)
    async def unlock(self, ctx: commands.Context):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = None
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await ctx.reply(f"{ctx.channel.mention} is now unlocked.")
        logging_cog = await _get_logging(self.bot)
        if logging_cog:
            await logging_cog.log_action(
                ctx.guild,
                title="Channel Unlocked",
                color=discord.Color.green(),
                fields={"Channel": ctx.channel.mention, "Moderator": str(ctx.author)},
            )

    @kick.error
    @ban.error
    @unban.error
    @timeout.error
    @untimeout.error
    @warn.error
    @warnings.error
    @clearwarnings.error
    @purge.error
    @slowmode.error
    @lock.error
    @unlock.error
    async def moderation_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("You don't have permission to do that.", ephemeral=True)
        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.reply(f"I'm missing permissions to do that: {', '.join(error.missing_permissions)}", ephemeral=True)
        elif isinstance(error, commands.MemberNotFound):
            await ctx.reply("Couldn't find that member.", ephemeral=True)
        else:
            log.exception("Error in moderation command", exc_info=error)
            await ctx.reply(f"Something went wrong: {error}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
