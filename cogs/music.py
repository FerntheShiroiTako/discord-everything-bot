"""
Voice/music playback: queue-based audio via yt-dlp + ffmpeg. Streams audio
directly (nothing is downloaded to disk).

This pulls audio from YouTube via yt-dlp, which is against YouTube's stated
Terms of Service around unauthorized access to media - a legal gray area
essentially every hobbyist Discord music bot operates in. Keep this to your
own private server, not a public/monetized bot. yt-dlp also needs periodic
updates (`pip install -U yt-dlp`) since YouTube regularly changes things
that break extraction.
"""
import asyncio
import logging
import random
import shutil
from collections import deque
from dataclasses import dataclass, replace
from typing import Literal

import discord
from discord.ext import commands
from yt_dlp import YoutubeDL

import config
from utils.checks import bot_has_perms

log = logging.getLogger("bot.music")

FFMPEG_BEFORE_OPTIONS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
FFMPEG_OPTIONS = "-vn"


@dataclass
class Track:
    title: str
    webpage_url: str
    duration: int | None
    requester_id: int
    stream_url: str | None = None


class LoopMode:
    OFF = "off"
    TRACK = "track"
    QUEUE = "queue"


def _blocking_flat_lookup(query: str) -> list[dict]:
    """Fast metadata-only lookup: a search term, a single video URL, or a playlist URL."""
    is_url = query.startswith("http://") or query.startswith("https://")
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "noplaylist": not (is_url and "list=" in query),
        "source_address": "0.0.0.0",
    }
    target = query if is_url else f"ytsearch1:{query}"
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(target, download=False)
    entries = info.get("entries") if isinstance(info, dict) else None
    if entries:
        return [e for e in entries if e]
    return [info] if info else []


def _blocking_resolve(webpage_url: str) -> dict:
    """Full extraction right before playback, so the stream URL is always fresh."""
    opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "source_address": "0.0.0.0",
    }
    with YoutubeDL(opts) as ydl:
        return ydl.extract_info(webpage_url, download=False)


def _track_from_entry(entry: dict, requester_id: int) -> Track | None:
    video_id = entry.get("id")
    webpage_url = entry.get("webpage_url") or entry.get("url")
    if not webpage_url or not webpage_url.startswith("http"):
        webpage_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else None
    if not webpage_url:
        return None
    return Track(
        title=entry.get("title") or "Unknown title",
        webpage_url=webpage_url,
        duration=entry.get("duration"),
        requester_id=requester_id,
    )


def _format_duration(seconds: int) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


class GuildPlayer:
    """Per-guild playback state and the background task that drives the queue."""

    def __init__(self, cog: "Music", guild_id: int):
        self.cog = cog
        self.bot = cog.bot
        self.guild_id = guild_id
        self.voice_client: discord.VoiceClient | None = None
        self.text_channel: discord.abc.Messageable | None = None
        self.queue: deque[Track] = deque()
        self.current: Track | None = None
        self.loop_mode = LoopMode.OFF
        self.volume = config.MUSIC_DEFAULT_VOLUME / 100
        self._skip_flag = False
        self._track_added = asyncio.Event()
        self._next_event = asyncio.Event()
        self.alone_task: asyncio.Task | None = None
        self.task = self.bot.loop.create_task(self._player_loop())

    def add_track(self, track: Track):
        self.queue.append(track)
        self._track_added.set()

    def destroy(self):
        self.task.cancel()
        if self.alone_task and not self.alone_task.done():
            self.alone_task.cancel()

    def _after_playback(self, error: Exception | None):
        if error:
            log.error("Playback error in guild %s: %s", self.guild_id, error)
        self.bot.loop.call_soon_threadsafe(self._next_event.set)

    async def _wait_for_track(self) -> Track | None:
        while not self.queue:
            self._track_added.clear()
            try:
                await asyncio.wait_for(self._track_added.wait(), timeout=config.MUSIC_IDLE_TIMEOUT_SECS)
            except asyncio.TimeoutError:
                return None
        return self.queue.popleft()

    async def _player_loop(self):
        await self.bot.wait_until_ready()
        while True:
            try:
                self._next_event.clear()

                if self._skip_flag:
                    self._skip_flag = False
                    track = await self._wait_for_track()
                elif self.loop_mode == LoopMode.TRACK and self.current is not None:
                    track = self.current
                else:
                    if self.loop_mode == LoopMode.QUEUE and self.current is not None:
                        self.add_track(self.current)
                    track = await self._wait_for_track()

                if track is None:
                    await self.cog._cleanup(self.guild_id)
                    return

                try:
                    resolved = await self.cog.resolve_stream(track)
                except Exception:
                    log.exception("Failed to resolve stream for %s", track.webpage_url)
                    if self.text_channel:
                        await self.text_channel.send(f"Skipping **{track.title}** — couldn't load audio.")
                    continue

                if not self.voice_client or not self.voice_client.is_connected():
                    await self.cog._cleanup(self.guild_id)
                    return

                self.current = resolved
                source = discord.PCMVolumeTransformer(
                    discord.FFmpegPCMAudio(
                        resolved.stream_url,
                        executable=config.FFMPEG_PATH,
                        before_options=FFMPEG_BEFORE_OPTIONS,
                        options=FFMPEG_OPTIONS,
                    ),
                    volume=self.volume,
                )
                self.voice_client.play(source, after=self._after_playback)
                if self.text_channel:
                    suffix = f" ({_format_duration(resolved.duration)})" if resolved.duration else ""
                    await self.text_channel.send(f"Now playing **{resolved.title}**{suffix}")

                await self._next_event.wait()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Unexpected error in player loop for guild %s", self.guild_id)
                await asyncio.sleep(1)


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.players: dict[int, GuildPlayer] = {}

    def _get_player(self, guild_id: int) -> GuildPlayer:
        player = self.players.get(guild_id)
        if not player:
            player = GuildPlayer(self, guild_id)
            self.players[guild_id] = player
        return player

    def _control_check(self, ctx: commands.Context) -> bool:
        player = self.players.get(ctx.guild.id)
        if not player or not player.voice_client or not player.voice_client.is_connected():
            return False
        return bool(ctx.author.voice and ctx.author.voice.channel == player.voice_client.channel)

    async def resolve_stream(self, track: Track) -> Track:
        info = await self.bot.loop.run_in_executor(None, _blocking_resolve, track.webpage_url)
        return replace(track, stream_url=info["url"], duration=track.duration or info.get("duration"))

    async def _cleanup(self, guild_id: int):
        player = self.players.pop(guild_id, None)
        if not player:
            return
        if player.alone_task and not player.alone_task.done():
            player.alone_task.cancel()
        if player.voice_client:
            try:
                await player.voice_client.disconnect(force=True)
            except Exception:
                pass

    async def _leave(self, guild_id: int):
        player = self.players.get(guild_id)
        if player:
            player.task.cancel()
        await self._cleanup(guild_id)

    async def cog_unload(self):
        for guild_id in list(self.players.keys()):
            await self._leave(guild_id)

    async def _disconnect_if_still_alone(self, guild_id: int):
        await asyncio.sleep(config.MUSIC_IDLE_TIMEOUT_SECS)
        player = self.players.get(guild_id)
        if not player or not player.voice_client or not player.voice_client.is_connected():
            return
        non_bots = [m for m in player.voice_client.channel.members if not m.bot]
        if not non_bots:
            await self._leave(guild_id)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before, after):
        if member.bot:
            return
        player = self.players.get(member.guild.id)
        if not player or not player.voice_client or not player.voice_client.is_connected():
            return
        channel = player.voice_client.channel
        if channel not in (before.channel, after.channel):
            return

        non_bots = [m for m in channel.members if not m.bot]
        if non_bots:
            if player.alone_task and not player.alone_task.done():
                player.alone_task.cancel()
                player.alone_task = None
                if player.voice_client.is_paused():
                    player.voice_client.resume()
            return

        if player.voice_client.is_playing():
            player.voice_client.pause()
        if not (player.alone_task and not player.alone_task.done()):
            player.alone_task = self.bot.loop.create_task(self._disconnect_if_still_alone(member.guild.id))

    @commands.hybrid_command(description="Join your current voice channel.")
    @commands.guild_only()
    @bot_has_perms(connect=True, speak=True)
    async def join(self, ctx: commands.Context):
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.reply("Join a voice channel first.", ephemeral=True)
        player = self._get_player(ctx.guild.id)
        channel = ctx.author.voice.channel
        if player.voice_client and player.voice_client.is_connected():
            await player.voice_client.move_to(channel)
        else:
            player.voice_client = await channel.connect()
        player.text_channel = ctx.channel
        await ctx.reply(f"Joined {channel.mention}.")

    @commands.hybrid_command(description="Disconnect and clear the queue.")
    @commands.guild_only()
    async def leave(self, ctx: commands.Context):
        player = self.players.get(ctx.guild.id)
        if not player or not player.voice_client or not player.voice_client.is_connected():
            return await ctx.reply("I'm not in a voice channel.", ephemeral=True)
        await self._leave(ctx.guild.id)
        await ctx.reply("Disconnected.")

    @commands.hybrid_command(description="Play a song or add it to the queue (YouTube link, playlist link, or search terms).")
    @commands.guild_only()
    @bot_has_perms(connect=True, speak=True)
    async def play(self, ctx: commands.Context, *, query: str):
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.reply("Join a voice channel first.", ephemeral=True)
        await ctx.defer()
        player = self._get_player(ctx.guild.id)
        player.text_channel = ctx.channel

        if not player.voice_client or not player.voice_client.is_connected():
            player.voice_client = await ctx.author.voice.channel.connect()

        try:
            entries = await self.bot.loop.run_in_executor(None, _blocking_flat_lookup, query)
        except Exception:
            log.exception("yt-dlp lookup failed for query: %s", query)
            return await ctx.reply("Couldn't find anything for that.")

        if not entries:
            return await ctx.reply("Couldn't find anything for that.")

        available = config.MUSIC_MAX_QUEUE - len(player.queue)
        if available <= 0:
            return await ctx.reply("Queue is full.")

        cap = min(config.MUSIC_MAX_PLAYLIST_SIZE, available)
        truncated = len(entries) > cap
        entries = entries[:cap]

        tracks = [t for t in (_track_from_entry(e, ctx.author.id) for e in entries) if t]
        if not tracks:
            return await ctx.reply("Couldn't find anything playable there.")
        for track in tracks:
            player.add_track(track)

        if len(tracks) == 1:
            await ctx.reply(f"Queued **{tracks[0].title}**.")
        else:
            suffix = " (queue/playlist size limit reached)" if truncated else ""
            await ctx.reply(f"Queued **{len(tracks)}** tracks.{suffix}")

    @commands.hybrid_command(description="Skip the current track.")
    @commands.guild_only()
    async def skip(self, ctx: commands.Context):
        player = self.players.get(ctx.guild.id)
        if not player or not player.voice_client or not (player.voice_client.is_playing() or player.voice_client.is_paused()):
            return await ctx.reply("Nothing is playing.", ephemeral=True)
        if not self._control_check(ctx):
            return await ctx.reply("Join the voice channel to control playback.", ephemeral=True)
        player._skip_flag = True
        player.voice_client.stop()
        await ctx.reply("Skipped.")

    @commands.hybrid_command(description="Pause playback.")
    @commands.guild_only()
    async def pause(self, ctx: commands.Context):
        player = self.players.get(ctx.guild.id)
        if not player or not player.voice_client or not player.voice_client.is_playing():
            return await ctx.reply("Nothing is playing.", ephemeral=True)
        if not self._control_check(ctx):
            return await ctx.reply("Join the voice channel to control playback.", ephemeral=True)
        player.voice_client.pause()
        await ctx.reply("Paused.")

    @commands.hybrid_command(description="Resume playback.")
    @commands.guild_only()
    async def resume(self, ctx: commands.Context):
        player = self.players.get(ctx.guild.id)
        if not player or not player.voice_client or not player.voice_client.is_paused():
            return await ctx.reply("Nothing is paused.", ephemeral=True)
        if not self._control_check(ctx):
            return await ctx.reply("Join the voice channel to control playback.", ephemeral=True)
        player.voice_client.resume()
        await ctx.reply("Resumed.")

    @commands.hybrid_command(description="Stop playback and clear the queue (stays connected).")
    @commands.guild_only()
    async def stop(self, ctx: commands.Context):
        player = self.players.get(ctx.guild.id)
        if not player or not player.voice_client:
            return await ctx.reply("Nothing is playing.", ephemeral=True)
        if not self._control_check(ctx):
            return await ctx.reply("Join the voice channel to control playback.", ephemeral=True)
        player.queue.clear()
        player._skip_flag = True
        if player.voice_client.is_playing() or player.voice_client.is_paused():
            player.voice_client.stop()
        await ctx.reply("Stopped and cleared the queue.")

    @commands.hybrid_command(description="Shuffle the queue.")
    @commands.guild_only()
    async def shuffle(self, ctx: commands.Context):
        player = self.players.get(ctx.guild.id)
        if not player or len(player.queue) < 2:
            return await ctx.reply("Not enough in the queue to shuffle.", ephemeral=True)
        if not self._control_check(ctx):
            return await ctx.reply("Join the voice channel to control playback.", ephemeral=True)
        items = list(player.queue)
        random.shuffle(items)
        player.queue = deque(items)
        await ctx.reply("Queue shuffled.")

    @commands.hybrid_command(name="loop", description="Set loop mode: off, track, or queue.")
    @commands.guild_only()
    async def loop_cmd(self, ctx: commands.Context, mode: Literal["off", "track", "queue"]):
        player = self._get_player(ctx.guild.id)
        if not self._control_check(ctx):
            return await ctx.reply("Join the voice channel to control playback.", ephemeral=True)
        player.loop_mode = mode
        await ctx.reply(f"Loop mode set to **{mode}**.")

    @commands.hybrid_command(description="Set playback volume (0-200%).")
    @commands.guild_only()
    async def volume(self, ctx: commands.Context, percent: commands.Range[int, 0, 200]):
        player = self.players.get(ctx.guild.id)
        if not player or not player.voice_client:
            return await ctx.reply("I'm not playing anything.", ephemeral=True)
        if not self._control_check(ctx):
            return await ctx.reply("Join the voice channel to control playback.", ephemeral=True)
        player.volume = percent / 100
        if isinstance(player.voice_client.source, discord.PCMVolumeTransformer):
            player.voice_client.source.volume = player.volume
        await ctx.reply(f"Volume set to {percent}%.")

    @commands.hybrid_command(name="queue", description="Show the current queue.")
    @commands.guild_only()
    async def queue_cmd(self, ctx: commands.Context):
        player = self.players.get(ctx.guild.id)
        if not player or (not player.current and not player.queue):
            return await ctx.reply("Queue is empty.", ephemeral=True)
        lines = []
        if player.current:
            lines.append(f"**Now playing:** {player.current.title} (requested by <@{player.current.requester_id}>)")
        upcoming = list(player.queue)[:10]
        for i, track in enumerate(upcoming, 1):
            lines.append(f"{i}. {track.title} (<@{track.requester_id}>)")
        remaining = len(player.queue) - len(upcoming)
        if remaining > 0:
            lines.append(f"...and {remaining} more.")
        embed = discord.Embed(title="Queue", description="\n".join(lines), color=discord.Color.blurple())
        embed.set_footer(text=f"Loop: {player.loop_mode}")
        await ctx.reply(embed=embed)

    @commands.hybrid_command(description="Show the currently playing track.")
    @commands.guild_only()
    async def nowplaying(self, ctx: commands.Context):
        player = self.players.get(ctx.guild.id)
        if not player or not player.current:
            return await ctx.reply("Nothing is playing.", ephemeral=True)
        track = player.current
        dur = _format_duration(track.duration) if track.duration else "unknown length"
        await ctx.reply(f"**{track.title}** ({dur}) — requested by <@{track.requester_id}>")


async def setup(bot: commands.Bot):
    try:
        import nacl  # noqa: F401
    except ImportError:
        log.warning("PyNaCl is not installed - Music cog not loaded. Run: pip install -r requirements.txt")
        return
    if not shutil.which(config.FFMPEG_PATH):
        log.warning("ffmpeg not found (FFMPEG_PATH=%s) - Music cog not loaded.", config.FFMPEG_PATH)
        return
    await bot.add_cog(Music(bot))
