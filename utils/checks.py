"""Reusable permission checks for hybrid commands."""
import discord
from discord.ext import commands

import config


def is_owner():
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.author.id in config.OWNER_IDS or await ctx.bot.is_owner(ctx.author):
            return True
        raise commands.NotOwner("Only the bot owner can use this command.")

    return commands.check(predicate)


def is_mod():
    """Requires Manage Messages/Kick/Timeout — the baseline for moderation commands."""

    async def predicate(ctx: commands.Context) -> bool:
        if ctx.author.id in config.OWNER_IDS:
            return True
        perms = ctx.author.guild_permissions if ctx.guild else None
        if perms and (perms.moderate_members or perms.kick_members or perms.manage_messages):
            return True
        raise commands.MissingPermissions(["moderate_members"])

    return commands.check(predicate)


def is_admin():
    """Requires Manage Guild — for configuration commands."""

    async def predicate(ctx: commands.Context) -> bool:
        if ctx.author.id in config.OWNER_IDS:
            return True
        perms = ctx.author.guild_permissions if ctx.guild else None
        if perms and perms.manage_guild:
            return True
        raise commands.MissingPermissions(["manage_guild"])

    return commands.check(predicate)


def bot_has_perms(**required: bool):
    async def predicate(ctx: commands.Context) -> bool:
        if not ctx.guild:
            return True
        me = ctx.guild.me
        missing = [name for name, needed in required.items() if needed and not getattr(me.guild_permissions, name, False)]
        if missing:
            raise commands.BotMissingPermissions(missing)
        return True

    return commands.check(predicate)
