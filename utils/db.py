"""Async SQLite layer. One connection pool-ish wrapper shared across cogs via bot.db."""
import json
import time
from dataclasses import dataclass, field

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id INTEGER PRIMARY KEY,
    log_channel_id INTEGER,
    mod_alert_channel_id INTEGER,
    automod_enabled INTEGER NOT NULL DEFAULT 1,
    image_mod_enabled INTEGER NOT NULL DEFAULT 0,
    invite_filter_enabled INTEGER NOT NULL DEFAULT 1,
    link_filter_enabled INTEGER NOT NULL DEFAULT 0,
    spam_filter_enabled INTEGER NOT NULL DEFAULT 1,
    banned_words TEXT NOT NULL DEFAULT '[]',
    ai_channel_id INTEGER,
    ai_enabled INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS warnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    moderator_id INTEGER NOT NULL,
    reason TEXT,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_warnings_guild_user ON warnings (guild_id, user_id);
"""

DEFAULTS = {
    "log_channel_id": None,
    "mod_alert_channel_id": None,
    "automod_enabled": True,
    "image_mod_enabled": False,
    "invite_filter_enabled": True,
    "link_filter_enabled": False,
    "spam_filter_enabled": True,
    "banned_words": [],
    "ai_channel_id": None,
    "ai_enabled": False,
}


@dataclass
class GuildSettings:
    guild_id: int
    log_channel_id: int | None = None
    mod_alert_channel_id: int | None = None
    automod_enabled: bool = True
    image_mod_enabled: bool = False
    invite_filter_enabled: bool = True
    link_filter_enabled: bool = False
    spam_filter_enabled: bool = True
    banned_words: list[str] = field(default_factory=list)
    ai_channel_id: int | None = None
    ai_enabled: bool = False


class Database:
    def __init__(self, path: str):
        self.path = path
        self._conn: aiosqlite.Connection | None = None
        self._cache: dict[int, GuildSettings] = {}

    async def connect(self):
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self):
        if self._conn:
            await self._conn.close()

    async def get_settings(self, guild_id: int, refresh: bool = False) -> GuildSettings:
        if not refresh and guild_id in self._cache:
            return self._cache[guild_id]

        async with self._conn.execute(
            "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()

        if row is None:
            await self._conn.execute(
                "INSERT INTO guild_settings (guild_id) VALUES (?)", (guild_id,)
            )
            await self._conn.commit()
            settings = GuildSettings(guild_id=guild_id)
        else:
            data = dict(row)
            data["banned_words"] = json.loads(data.get("banned_words") or "[]")
            data["automod_enabled"] = bool(data["automod_enabled"])
            data["image_mod_enabled"] = bool(data["image_mod_enabled"])
            data["invite_filter_enabled"] = bool(data["invite_filter_enabled"])
            data["link_filter_enabled"] = bool(data["link_filter_enabled"])
            data["spam_filter_enabled"] = bool(data["spam_filter_enabled"])
            data["ai_enabled"] = bool(data["ai_enabled"])
            settings = GuildSettings(**data)

        self._cache[guild_id] = settings
        return settings

    async def update_settings(self, guild_id: int, **fields):
        await self.get_settings(guild_id)  # ensure row exists

        columns = []
        values = []
        for key, value in fields.items():
            if key == "banned_words":
                value = json.dumps(value)
            elif isinstance(value, bool):
                value = int(value)
            columns.append(f"{key} = ?")
            values.append(value)
        values.append(guild_id)

        await self._conn.execute(
            f"UPDATE guild_settings SET {', '.join(columns)} WHERE guild_id = ?", values
        )
        await self._conn.commit()
        await self.get_settings(guild_id, refresh=True)

    async def add_warning(self, guild_id: int, user_id: int, moderator_id: int, reason: str) -> int:
        cur = await self._conn.execute(
            "INSERT INTO warnings (guild_id, user_id, moderator_id, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, moderator_id, reason, int(time.time())),
        )
        await self._conn.commit()
        return cur.lastrowid

    async def get_warnings(self, guild_id: int, user_id: int) -> list[aiosqlite.Row]:
        async with self._conn.execute(
            "SELECT * FROM warnings WHERE guild_id = ? AND user_id = ? ORDER BY created_at DESC",
            (guild_id, user_id),
        ) as cur:
            return await cur.fetchall()

    async def clear_warnings(self, guild_id: int, user_id: int) -> int:
        cur = await self._conn.execute(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        await self._conn.commit()
        return cur.rowcount
