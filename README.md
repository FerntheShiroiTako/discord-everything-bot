# Everything Bot

A Discord bot for a small server: moderation, automod, fun commands, web search, action logging, and an optional AI chatbot mode (OpenAI or xAI).

## Features

Moderation: kick, ban, unban, timeout/untimeout, warn/warnings/clearwarnings, purge, slowmode, lock/unlock.

Automod: spam/flood detection, mass-mention detection, Discord invite link filter, banned word filter, and an optional image moderation hook that calls a licensed third-party API (Sightengine or Hive) to auto-delete and ban on flagged explicit images. This is not a custom CSAM classifier — see the Image moderation and child safety section below for why, and what to actually enable.

Fun: 8ball, coinflip, dice roll, rock-paper-scissors, random meme, yes/no polls.

Web search: `/search` backed by the Tavily API.

AI chatbot: replies when mentioned, replied to, or in a designated channel. Works with OpenAI (ChatGPT models) or xAI (Grok models) — pick one via `AI_PROVIDER`.

Logging: every moderation action and a set of passive events (message edits/deletes, joins/leaves, bans) get posted as embeds to a channel you configure with `/config logchannel`.

Music: `/play` (search terms, a video link, or a playlist link), `/skip`, `/pause`, `/resume`, `/stop`, `/queue`, `/nowplaying`, `/volume`, `/shuffle`, `/loop` (off/track/queue), `/join`, `/leave`. Anyone in the same voice channel as the bot can control playback. Auto-disconnects after being idle or alone for a while. See the Music setup section below — it needs ffmpeg installed separately.

## Image moderation and child safety

Do not attempt to build or train a classifier that detects CSAM yourself — that would require possessing the material to test against, which is illegal, and a hobbyist model would be unreliable besides. This bot instead supports two things, and you should use both:

Discord's built-in Explicit Media Content Filter. Turn this on in Server Settings, Safety Setup. It runs platform-wide on every upload using PhotoDNA-based hash matching against known CSAM, integrated with NCMEC reporting, independent of any bot. This is the actual backstop and works even if the bot is offline.

An optional bot-level filter for general explicit/adult imagery, via Sightengine or Hive — both are established, licensed moderation API providers used by many Discord communities, with nudity/explicit classifiers and (in Hive's case) child-safety-specific models meant for platform moderation. Set `IMAGE_MOD_PROVIDER` and the matching API credentials in `.env`, then run `/automod images true` in the server to turn it on. Flagged images are deleted and the poster is banned automatically, with the action logged and a reminder to also use Discord's in-app Report Message action to escalate to Discord Trust & Safety.

## Music setup

Music streams audio from YouTube via `yt-dlp`, transcoded live through `ffmpeg` — nothing is downloaded to disk. This is a legal gray area (against YouTube's Terms of Service around unauthorized access to media) that essentially every hobbyist Discord music bot operates in; keep this to your own private server, not a public or monetized bot.

Requirements beyond `pip install -r requirements.txt` (which covers `PyNaCl` and `yt-dlp`):

- **ffmpeg** must be installed separately and on `PATH` — it's not a pip package. On the droplet: `sudo apt install ffmpeg`. On Windows for local dev, install via your package manager of choice and confirm `ffmpeg -version` works.
- On Linux, discord.py also needs **libopus** for voice: `sudo apt install libopus0`.

If either ffmpeg or `PyNaCl` is missing, the Music cog just logs a warning and doesn't load — no crash. `yt-dlp` breaks periodically when YouTube changes things; if playback suddenly stops working, try `pip install -U yt-dlp` first.

## Discord application setup

Create an application and bot user at the Discord Developer Portal.

Under Bot, enable the Server Members Intent and Message Content Intent (privileged intents) — both are required for automod and warnings to work correctly.

Copy the bot token; it goes in `DISCORD_TOKEN`.

Under OAuth2, URL Generator, select the `bot` and `applications.commands` scopes, then select these bot permissions: Kick Members, Ban Members, Moderate Members, Manage Messages, Manage Channels, Manage Roles, Read Message History, Send Messages, Embed Links, Attach Files, Add Reactions, Connect, Speak. Use the generated URL to invite the bot to your server. (Connect/Speak are only needed for the music feature.)

## Configuration reference

All configuration lives in `.env` (copy `.env.example` to `.env` and fill it in).

| Variable | Purpose |
| --- | --- |
| `DISCORD_TOKEN` | Bot token from the Developer Portal |
| `COMMAND_PREFIX` | Prefix for text commands (slash commands always work regardless) |
| `OWNER_IDS` | Comma-separated Discord user IDs with bot-owner override on role checks |
| `GUILD_ID` | Your server's ID; when set, slash commands sync to it instantly instead of the global sync (which can take up to an hour) |
| `AI_PROVIDER` | `openai`, `xai`, or blank to disable the chatbot cog |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | Used when `AI_PROVIDER=openai` |
| `XAI_API_KEY` / `XAI_MODEL` | Used when `AI_PROVIDER=xai` |
| `TAVILY_API_KEY` | Enables `/search`; leave blank to disable it |
| `IMAGE_MOD_PROVIDER` | `sightengine`, `hive`, or blank to disable image moderation |
| `SIGHTENGINE_API_USER` / `SIGHTENGINE_API_SECRET` | Used when `IMAGE_MOD_PROVIDER=sightengine` |
| `HIVE_API_KEY` | Used when `IMAGE_MOD_PROVIDER=hive` |
| `FFMPEG_PATH` | ffmpeg executable name/path for music playback; requires ffmpeg installed separately (see Music setup) |
| `MUSIC_MAX_QUEUE` / `MUSIC_MAX_PLAYLIST_SIZE` | Caps on queue length and per-playlist tracks added at once |
| `MUSIC_DEFAULT_VOLUME` | Starting volume percent (0-200) |
| `MUSIC_IDLE_TIMEOUT_SECS` | Auto-disconnect after this long idle or alone in the channel |

Per-server settings (log channel, which filters are on, banned words, AI channel) are stored in the SQLite database and set with in-Discord commands, not `.env` — see below.

## In-Discord setup after inviting the bot

Run these once per server, as an admin (Manage Server permission):

`/config logchannel #mod-log` to set where actions get logged.

`/automod toggle true` to turn on automod, then `/automod addword` for any banned words.

`/automod images true` if you configured `IMAGE_MOD_PROVIDER`.

`/ai setchannel #general` if you want the AI chatbot always-on in a channel; it'll also respond anywhere it's mentioned or replied to.

## Local development

Requires Python 3.11+.

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Fill in `.env`, then run:

```
python bot.py
```

## Deploying to the droplet

This follows the same layout as the other bots on `167.99.203.77` (see the ops guide) — this one slots in as bot4.

SSH in and clone the repo:

```
ssh root@167.99.203.77
mkdir -p /root/bots/bot4
cd /root/bots/bot4
git clone <your-repo-url> .
```

Set up the virtual environment:

```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate
```

Create the environment file:

```
cp .env.example .env
nano .env
```

Fill in the same variables as local development, save with Ctrl+X, Y, Enter.

Install and start the systemd service:

```
cp systemd/discord-bot4.service /etc/systemd/system/discord-bot4.service
sudo systemctl daemon-reload
sudo systemctl enable discord-bot4.service
sudo systemctl start discord-bot4.service
sudo systemctl status discord-bot4.service
```

## Updating

```
cd /root/bots/bot4
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
deactivate
sudo systemctl restart discord-bot4.service
```

## Logs and troubleshooting

Live logs: `sudo journalctl -u discord-bot4.service -f`

Last 30 lines: `sudo journalctl -u discord-bot4.service -n 30`

Rebuild the virtual environment if dependencies get into a bad state:

```
cd /root/bots/bot4
rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate
sudo systemctl restart discord-bot4.service
```

Never commit or paste actual bot tokens or API keys into this repo or its docs — keep them in `.env`, which is gitignored.
