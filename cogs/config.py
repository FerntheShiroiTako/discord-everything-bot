"""
Per-server configuration surface: the /setup onboarding wizard and the /config
command hub. This cog only reads/writes utils.db.GuildSettings - the actual
automod/AI/logging behavior driven by those settings lives in their own cogs.
"""
import discord
from discord.ext import commands

import config as bot_config
from utils.checks import is_admin


def _member_is_admin(member: discord.Member) -> bool:
    if member.id in bot_config.OWNER_IDS:
        return True
    return bool(member.guild_permissions.manage_guild)


def _flag(value: bool) -> str:
    return "on" if value else "off"


async def _settings_embed(bot: commands.Bot, guild: discord.Guild) -> discord.Embed:
    settings = await bot.db.get_settings(guild.id)
    log_channel = guild.get_channel(settings.log_channel_id) if settings.log_channel_id else None
    ai_channel = guild.get_channel(settings.ai_channel_id) if settings.ai_channel_id else None

    embed = discord.Embed(title=f"Configuration for {guild.name}", color=discord.Color.blurple())
    embed.add_field(name="Log channel", value=log_channel.mention if log_channel else "not set", inline=True)
    embed.add_field(name="Prefix", value=f"`{bot_config.COMMAND_PREFIX}` (slash commands always work)", inline=True)

    embed.add_field(
        name="Automod",
        value=(
            f"Enabled: **{_flag(settings.automod_enabled)}**\n"
            f"Spam filter: **{_flag(settings.spam_filter_enabled)}**\n"
            f"Invite filter: **{_flag(settings.invite_filter_enabled)}**\n"
            f"Link filter: **{_flag(settings.link_filter_enabled)}**\n"
            f"Image moderation: **{_flag(settings.image_mod_enabled)}**"
            + ("" if bot_config.IMAGE_MOD_PROVIDER else " (no provider configured on the bot)")
            + f"\nBanned words: **{len(settings.banned_words)}**"
        ),
        inline=True,
    )
    embed.add_field(
        name="AI chatbot",
        value=(
            f"Provider: **{bot_config.AI_PROVIDER or 'not configured'}**\n"
            f"Channel mode: **{_flag(settings.ai_enabled)}**\n"
            f"Channel: {ai_channel.mention if ai_channel else 'not set'}\n"
            "(always responds to mentions/replies regardless)"
        ),
        inline=True,
    )
    embed.set_footer(text="/setup for a guided walkthrough, or the /config subcommands to adjust one thing at a time.")
    return embed


TOGGLE_FIELDS = [
    ("automod_enabled", "Automod", 2),
    ("invite_filter_enabled", "Invite filter", 2),
    ("spam_filter_enabled", "Spam filter", 2),
    ("link_filter_enabled", "Link filter", 2),
]


class SetupView(discord.ui.View):
    def __init__(self, bot: commands.Bot, guild: discord.Guild, settings):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild = guild
        self.message: discord.Message | None = None
        self._build_items(settings)

    def _build_items(self, settings):
        self.clear_items()

        log_select = discord.ui.ChannelSelect(
            placeholder="Choose a log channel",
            channel_types=[discord.ChannelType.text],
            row=0,
        )

        async def on_log_channel(interaction: discord.Interaction):
            await self.bot.db.update_settings(self.guild.id, log_channel_id=log_select.values[0].id)
            await self._refresh(interaction)

        log_select.callback = on_log_channel
        self.add_item(log_select)

        if bot_config.AI_PROVIDER:
            ai_select = discord.ui.ChannelSelect(
                placeholder="Choose an AI chat channel (optional)",
                channel_types=[discord.ChannelType.text],
                row=1,
            )

            async def on_ai_channel(interaction: discord.Interaction):
                await self.bot.db.update_settings(
                    self.guild.id, ai_channel_id=ai_select.values[0].id, ai_enabled=True
                )
                await self._refresh(interaction)

            ai_select.callback = on_ai_channel
            self.add_item(ai_select)

        for field, label, row in TOGGLE_FIELDS:
            self.add_item(self._toggle_button(field, label, row, getattr(settings, field)))
        if bot_config.IMAGE_MOD_PROVIDER:
            self.add_item(self._toggle_button("image_mod_enabled", "Image moderation", 3, settings.image_mod_enabled))

        done = discord.ui.Button(label="Done", style=discord.ButtonStyle.primary, row=4)
        done.callback = self._on_done
        self.add_item(done)

    def _toggle_button(self, field: str, label: str, row: int, enabled: bool) -> discord.ui.Button:
        button = discord.ui.Button(
            label=f"{label}: {'on' if enabled else 'off'}",
            style=discord.ButtonStyle.success if enabled else discord.ButtonStyle.secondary,
            custom_id=field,
            row=row,
        )

        async def callback(interaction: discord.Interaction):
            settings = await self.bot.db.get_settings(self.guild.id)
            new_value = not getattr(settings, field)
            await self.bot.db.update_settings(self.guild.id, **{field: new_value})
            settings = await self.bot.db.get_settings(self.guild.id)
            self._build_items(settings)
            await self._refresh(interaction)

        button.callback = callback
        return button

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if isinstance(interaction.user, discord.Member) and _member_is_admin(interaction.user):
            return True
        await interaction.response.send_message("Only server admins can use this.", ephemeral=True)
        return False

    async def _refresh(self, interaction: discord.Interaction):
        embed = await _settings_embed(self.bot, self.guild)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_done(self, interaction: discord.Interaction):
        for item in self.children:
            item.disabled = True
        embed = await _settings_embed(self.bot, self.guild)
        embed.set_footer(text="Setup complete. Use /config any time to change these later.")
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class Config(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(description="Guided setup wizard: log channel, automod, and AI chat in one go.")
    @is_admin()
    async def setup(self, ctx: commands.Context):
        settings = await self.bot.db.get_settings(ctx.guild.id)  # ensure a row exists
        view = SetupView(self.bot, ctx.guild, settings)
        embed = await _settings_embed(self.bot, ctx.guild)
        embed.description = "Pick a log channel and AI channel below, and click the toggles to turn features on or off."
        view.message = await ctx.reply(embed=embed, view=view, ephemeral=True)

    # ---- /config ----------------------------------------------------

    @commands.hybrid_group(description="View or change this server's configuration.")
    @is_admin()
    async def config(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.reply(embed=await _settings_embed(self.bot, ctx.guild))

    @config.command(name="show", description="Show the full current configuration.")
    @is_admin()
    async def config_show(self, ctx: commands.Context):
        await ctx.reply(embed=await _settings_embed(self.bot, ctx.guild))

    @config.command(name="logchannel", description="Set the channel where the bot logs its actions.")
    @is_admin()
    async def config_logchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        await self.bot.db.update_settings(ctx.guild.id, log_channel_id=channel.id)
        await ctx.reply(f"Log channel set to {channel.mention}.")

    @config.command(name="reset", description="Reset this server's configuration back to defaults.")
    @is_admin()
    async def config_reset(self, ctx: commands.Context):
        await self.bot.db.reset_settings(ctx.guild.id)
        await ctx.reply("This server's configuration has been reset to defaults. Warnings were not affected.")

    # ---- /config automod ---------------------------------------------

    @config.group(name="automod", description="Configure automod for this server.")
    @is_admin()
    async def config_automod(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.reply(embed=await _settings_embed(self.bot, ctx.guild))

    @config_automod.command(name="toggle", description="Enable or disable automod entirely.")
    @is_admin()
    async def automod_toggle(self, ctx: commands.Context, enabled: bool):
        await self.bot.db.update_settings(ctx.guild.id, automod_enabled=enabled)
        await ctx.reply(f"Automod is now {'enabled' if enabled else 'disabled'}.")

    @config_automod.command(name="links", description="Enable or disable the general link filter (blocks all URLs, not just Discord invites).")
    @is_admin()
    async def automod_links(self, ctx: commands.Context, enabled: bool):
        await self.bot.db.update_settings(ctx.guild.id, link_filter_enabled=enabled)
        await ctx.reply(f"Link filter is now {'enabled' if enabled else 'disabled'}.")

    @config_automod.command(name="invites", description="Enable or disable the Discord invite link filter.")
    @is_admin()
    async def automod_invites(self, ctx: commands.Context, enabled: bool):
        await self.bot.db.update_settings(ctx.guild.id, invite_filter_enabled=enabled)
        await ctx.reply(f"Invite filter is now {'enabled' if enabled else 'disabled'}.")

    @config_automod.command(name="spam", description="Enable or disable the spam/flood filter.")
    @is_admin()
    async def automod_spam(self, ctx: commands.Context, enabled: bool):
        await self.bot.db.update_settings(ctx.guild.id, spam_filter_enabled=enabled)
        await ctx.reply(f"Spam filter is now {'enabled' if enabled else 'disabled'}.")

    @config_automod.command(name="images", description="Enable or disable image moderation (requires IMAGE_MOD_PROVIDER configured).")
    @is_admin()
    async def automod_images(self, ctx: commands.Context, enabled: bool):
        if enabled and not bot_config.IMAGE_MOD_PROVIDER:
            return await ctx.reply(
                "No image moderation provider is configured on the bot (IMAGE_MOD_PROVIDER in .env). "
                "Set that up first, and make sure Discord's own Explicit Media Content Filter is enabled "
                "in Server Settings > Safety Setup.",
                ephemeral=True,
            )
        await self.bot.db.update_settings(ctx.guild.id, image_mod_enabled=enabled)
        await ctx.reply(f"Image moderation is now {'enabled' if enabled else 'disabled'}.")

    @config_automod.command(name="addword", description="Add a word/phrase to the banned words list.")
    @is_admin()
    async def automod_addword(self, ctx: commands.Context, *, word: str):
        settings = await self.bot.db.get_settings(ctx.guild.id)
        words = settings.banned_words
        if word.lower() in [w.lower() for w in words]:
            return await ctx.reply("That word is already banned.", ephemeral=True)
        words.append(word)
        await self.bot.db.update_settings(ctx.guild.id, banned_words=words)
        await ctx.reply(f"Added `{word}` to the banned words list.", ephemeral=True)

    @config_automod.command(name="removeword", description="Remove a word/phrase from the banned words list.")
    @is_admin()
    async def automod_removeword(self, ctx: commands.Context, *, word: str):
        settings = await self.bot.db.get_settings(ctx.guild.id)
        words = [w for w in settings.banned_words if w.lower() != word.lower()]
        await self.bot.db.update_settings(ctx.guild.id, banned_words=words)
        await ctx.reply(f"Removed `{word}` from the banned words list.", ephemeral=True)

    @config_automod.command(name="listwords", description="List all banned words/phrases.")
    @is_admin()
    async def automod_listwords(self, ctx: commands.Context):
        settings = await self.bot.db.get_settings(ctx.guild.id)
        if not settings.banned_words:
            return await ctx.reply("No banned words configured.", ephemeral=True)
        await ctx.reply("Banned words: " + ", ".join(f"`{w}`" for w in settings.banned_words), ephemeral=True)

    # ---- /config ai -----------------------------------------------------

    @config.group(name="ai", description="Configure the AI chatbot for this server.")
    @is_admin()
    async def config_ai(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.reply(embed=await _settings_embed(self.bot, ctx.guild))

    @config_ai.command(name="setchannel", description="Set the channel where the bot always responds without needing a mention.")
    @is_admin()
    async def ai_setchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        if not bot_config.AI_PROVIDER:
            return await ctx.reply(
                "No AI provider is configured on the bot (AI_PROVIDER in .env). Set that up first.",
                ephemeral=True,
            )
        await self.bot.db.update_settings(ctx.guild.id, ai_channel_id=channel.id, ai_enabled=True)
        await ctx.reply(f"AI chat is now active in {channel.mention}. It'll also always respond to mentions/replies anywhere.")

    @config_ai.command(name="toggle", description="Enable or disable the always-on AI channel (mentions/replies still work).")
    @is_admin()
    async def ai_toggle(self, ctx: commands.Context, enabled: bool):
        await self.bot.db.update_settings(ctx.guild.id, ai_enabled=enabled)
        await ctx.reply(f"AI channel mode is now {'enabled' if enabled else 'disabled'}.")

    @setup.error
    @config.error
    @config_show.error
    @config_logchannel.error
    @config_reset.error
    @config_automod.error
    @automod_toggle.error
    @automod_links.error
    @automod_invites.error
    @automod_spam.error
    @automod_images.error
    @automod_addword.error
    @automod_removeword.error
    @automod_listwords.error
    @config_ai.error
    @ai_setchannel.error
    @ai_toggle.error
    async def config_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("You need the Manage Server permission to do that.", ephemeral=True)
        else:
            raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(Config(bot))
