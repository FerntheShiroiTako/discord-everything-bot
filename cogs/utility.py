"""General utility commands: ping, info, and server configuration."""
import time

import discord
from discord.ext import commands

from utils.checks import is_admin


class Utility(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(description="Check the bot's latency.")
    async def ping(self, ctx: commands.Context):
        start = time.perf_counter()
        message = await ctx.reply("Pinging...")
        elapsed_ms = (time.perf_counter() - start) * 1000
        await message.edit(content=f"Pong! Message latency: {elapsed_ms:.0f}ms, gateway: {self.bot.latency * 1000:.0f}ms")

    @commands.hybrid_command(description="Show information about this server.")
    async def serverinfo(self, ctx: commands.Context):
        guild = ctx.guild
        embed = discord.Embed(title=guild.name, color=discord.Color.blurple())
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="Members", value=guild.member_count)
        embed.add_field(name="Created", value=discord.utils.format_dt(guild.created_at, "R"))
        embed.add_field(name="Owner", value=str(guild.owner))
        embed.add_field(name="Channels", value=len(guild.channels))
        embed.add_field(name="Roles", value=len(guild.roles))
        embed.add_field(name="Boosts", value=guild.premium_subscription_count)
        await ctx.reply(embed=embed)

    @commands.hybrid_command(description="Show information about a user.")
    async def userinfo(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        embed = discord.Embed(title=str(member), color=member.color)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Joined Server", value=discord.utils.format_dt(member.joined_at, "R"))
        embed.add_field(name="Account Created", value=discord.utils.format_dt(member.created_at, "R"))
        roles = [r.mention for r in member.roles if r != ctx.guild.default_role]
        embed.add_field(name="Roles", value=", ".join(roles) if roles else "None", inline=False)
        await ctx.reply(embed=embed)

    @commands.hybrid_group(description="Configure the bot for this server.")
    @is_admin()
    async def config(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            settings = await self.bot.db.get_settings(ctx.guild.id)
            log_channel = ctx.guild.get_channel(settings.log_channel_id) if settings.log_channel_id else None
            await ctx.reply(f"Log channel: {log_channel.mention if log_channel else 'not set'}")

    @config.command(name="logchannel", description="Set the channel where the bot logs its actions.")
    async def config_logchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        await self.bot.db.update_settings(ctx.guild.id, log_channel_id=channel.id)
        await ctx.reply(f"Log channel set to {channel.mention}.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))
