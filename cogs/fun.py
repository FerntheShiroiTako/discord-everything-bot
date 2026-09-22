"""Lightweight fun/engagement commands."""
import random

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

EIGHT_BALL_RESPONSES = [
    "It is certain.", "Without a doubt.", "Yes, definitely.", "You may rely on it.",
    "As I see it, yes.", "Most likely.", "Outlook good.", "Signs point to yes.",
    "Reply hazy, try again.", "Ask again later.", "Better not tell you now.",
    "Cannot predict now.", "Concentrate and ask again.", "Don't count on it.",
    "My reply is no.", "My sources say no.", "Outlook not so good.", "Very doubtful.",
]

MEME_SUBREDDIT = "memes"


class Fun(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: aiohttp.ClientSession | None = None

    async def cog_load(self):
        self.session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self.session:
            await self.session.close()

    @commands.hybrid_command(description="Ask the magic 8-ball a question.")
    @app_commands.describe(question="What do you want to ask?")
    async def eightball(self, ctx: commands.Context, *, question: str):
        await ctx.reply(f"🎱 {random.choice(EIGHT_BALL_RESPONSES)}")

    @commands.hybrid_command(description="Flip a coin.")
    async def coinflip(self, ctx: commands.Context):
        await ctx.reply(f"🪙 {random.choice(['Heads', 'Tails'])}!")

    @commands.hybrid_command(description="Roll one or more dice, e.g. 2d6.")
    @app_commands.describe(dice="Format NdN, e.g. 2d6 for two six-sided dice")
    async def roll(self, ctx: commands.Context, dice: str = "1d6"):
        try:
            count_str, sides_str = dice.lower().split("d")
            count, sides = int(count_str), int(sides_str)
            if not (1 <= count <= 100 and 2 <= sides <= 1000):
                raise ValueError
        except ValueError:
            return await ctx.reply("Use the format `NdN`, like `2d6` (max 100 dice, 1000 sides).", ephemeral=True)
        rolls = [random.randint(1, sides) for _ in range(count)]
        await ctx.reply(f"🎲 {', '.join(map(str, rolls))} (total: {sum(rolls)})")

    @commands.hybrid_command(description="Play rock, paper, scissors against the bot.")
    @app_commands.describe(choice="rock, paper, or scissors")
    @app_commands.choices(choice=[
        app_commands.Choice(name="Rock", value="rock"),
        app_commands.Choice(name="Paper", value="paper"),
        app_commands.Choice(name="Scissors", value="scissors"),
    ])
    async def rps(self, ctx: commands.Context, choice: str):
        bot_choice = random.choice(["rock", "paper", "scissors"])
        beats = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
        if choice == bot_choice:
            result = "It's a tie!"
        elif beats[choice] == bot_choice:
            result = "You win!"
        else:
            result = "I win!"
        await ctx.reply(f"You chose **{choice}**, I chose **{bot_choice}**. {result}")

    @commands.hybrid_command(description="Get a random meme.")
    async def meme(self, ctx: commands.Context):
        await ctx.defer()
        try:
            async with self.session.get(f"https://meme-api.com/gimme/{MEME_SUBREDDIT}", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
        except Exception:
            return await ctx.reply("Couldn't fetch a meme right now, try again in a bit.")
        if data.get("nsfw"):
            return await ctx.reply("Got an NSFW result, try again.")
        embed = discord.Embed(title=data.get("title", "meme"), color=discord.Color.random())
        embed.set_image(url=data.get("url"))
        embed.set_footer(text=f"r/{data.get('subreddit', MEME_SUBREDDIT)}")
        await ctx.reply(embed=embed)

    @commands.hybrid_command(description="Start a simple yes/no poll.")
    @app_commands.describe(question="The poll question")
    async def poll(self, ctx: commands.Context, *, question: str):
        embed = discord.Embed(title="📊 Poll", description=question, color=discord.Color.blurple())
        embed.set_footer(text=f"Started by {ctx.author}")
        message = await ctx.channel.send(embed=embed)
        await message.add_reaction("👍")
        await message.add_reaction("👎")
        if ctx.interaction:
            await ctx.reply("Poll posted.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Fun(bot))
