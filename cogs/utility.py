"""General utility commands: ping and info. Server configuration lives in cogs/config.py."""
import time

import discord
from discord.ext import commands


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


async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))
