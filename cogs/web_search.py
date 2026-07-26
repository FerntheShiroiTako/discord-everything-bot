"""Web search via the Tavily API."""
import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import config

log = logging.getLogger("bot.web_search")

TAVILY_ENDPOINT = "https://api.tavily.com/search"


class WebSearch(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: aiohttp.ClientSession | None = None

    async def cog_load(self):
        self.session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self.session:
            await self.session.close()

    @commands.hybrid_command(description="Search the web.")
    @app_commands.describe(query="What do you want to search for?")
    async def search(self, ctx: commands.Context, *, query: str):
        await ctx.defer()
        headers = {"Authorization": f"Bearer {config.TAVILY_API_KEY}"}
        payload = {"query": query, "max_results": 5}

        try:
            async with self.session.post(TAVILY_ENDPOINT, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    log.warning("Tavily search returned status %s", resp.status)
                    return await ctx.reply("Search failed, try again in a bit.")
                data = await resp.json()
        except Exception:
            log.exception("Tavily search request failed")
            return await ctx.reply("Search failed, try again in a bit.")

        results = data.get("results", [])
        if not results:
            return await ctx.reply(f"No results for **{query}**.")

        embed = discord.Embed(title=f"Search results for: {query}", color=discord.Color.blurple())
        for item in results[:5]:
            title = item.get("title", "Untitled")
            url = item.get("url", "")
            content = item.get("content", "")
            embed.add_field(name=title, value=f"{content}\n{url}"[:1024], inline=False)
        await ctx.reply(embed=embed)


async def setup(bot: commands.Bot):
    if not config.TAVILY_API_KEY:
        logging.getLogger("bot.web_search").warning("TAVILY_API_KEY not set - WebSearch cog not loaded.")
        return
    await bot.add_cog(WebSearch(bot))
