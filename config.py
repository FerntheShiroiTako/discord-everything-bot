"""Central config loader. Everything comes from environment variables (.env)."""
import os
from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    val = os.getenv(name, "").strip()
    return int(val) if val else default


def _float(name: str, default: float) -> float:
    val = os.getenv(name, "").strip()
    return float(val) if val else default


DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "!")
OWNER_IDS = {int(x) for x in os.getenv("OWNER_IDS", "").split(",") if x.strip()}

# Your server's ID. When set, slash commands sync to this guild directly and
# show up within seconds. When blank, they sync globally instead, which works
# in every server the bot is in but can take up to an hour to propagate.
_guild_id = os.getenv("GUILD_ID", "").strip()
GUILD_ID = int(_guild_id) if _guild_id else None

DB_PATH = os.getenv("DB_PATH", os.path.join("data", "bot.db"))

# AI_PROVIDER is "openai", "xai", or "" to disable the chatbot cog entirely
AI_PROVIDER = os.getenv("AI_PROVIDER", "").strip().lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
XAI_API_KEY = os.getenv("XAI_API_KEY", "")
XAI_MODEL = os.getenv("XAI_MODEL", "grok-4")
AI_SYSTEM_PROMPT = os.getenv(
    "AI_SYSTEM_PROMPT",
    "You are a helpful, concise assistant chatting in a Discord server. Keep replies short unless asked for detail.",
)
AI_HISTORY_LENGTH = _int("AI_HISTORY_LENGTH", 10)
AI_MAX_TOKENS = _int("AI_MAX_TOKENS", 600)

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# IMAGE_MOD_PROVIDER is "sightengine", "hive", or "" to disable image moderation entirely
IMAGE_MOD_PROVIDER = os.getenv("IMAGE_MOD_PROVIDER", "").strip().lower()
SIGHTENGINE_API_USER = os.getenv("SIGHTENGINE_API_USER", "")
SIGHTENGINE_API_SECRET = os.getenv("SIGHTENGINE_API_SECRET", "")
HIVE_API_KEY = os.getenv("HIVE_API_KEY", "")
IMAGE_MOD_NUDITY_THRESHOLD = _float("IMAGE_MOD_NUDITY_THRESHOLD", 0.6)

AUTOMOD_MAX_MENTIONS = _int("AUTOMOD_MAX_MENTIONS", 6)
AUTOMOD_SPAM_MSG_COUNT = _int("AUTOMOD_SPAM_MSG_COUNT", 5)
AUTOMOD_SPAM_INTERVAL_SECS = _float("AUTOMOD_SPAM_INTERVAL_SECS", 5)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
