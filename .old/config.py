import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Настройки бота
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "suicidaldownloadbot")

# Пути и библиотеки
COOKIE_FILE = os.getenv("COOKIE_FILE", "cookiefile.txt")
VENV = os.getenv("VENV", "")
YT_DLP = VENV + "yt-dlp"

DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "DOWNLOADS")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Плюс-пользователи и прокси
PLUS_FILE = "plusids"
PLUS_USERS: set[int] = set()

USE_PROXY = "-proxy" in sys.argv or "--proxy" in sys.argv

# Кэш ссылок
URL_CACHE: dict[str, dict | str] = {}

SUPPORTED_DOMAINS = [
    "youtube.com", "youtu.be",
    "soundcloud.com",
    "spotify.com",
    "tiktok.com", "tiktokv.com",
    "instagram.com", "vk.com", "x.com", "twitter.com",
    "pinterest.com", "pin.it"
]

NAME = [
    "abyss", "acorn", "altar", "amber", "anchor", "anemone", "anvil", "arch", "artifact", "asteroid", 
    "atmosphere", "aurora", "avalanche", "beacon", "beam", "birch", "blaze", "bliss", "blossom", "boulder", 
    "brass", "breeze", "brine", "bronze", "brook", "cadence", "calm", "canyon", "canopy", "cascade", "cavern", 
    "cedar", "chasm", "chime", "cinder", "cliff", "clockwork", "cloud", "cloudscape", "coast", "comet", 
    "compass", "constellation", "copper", "coral", "cosmos", "crater", "creek", "crest", "crystal", "current", 
    "cypress", "dawn", "daybreak", "deluge", "desert", "dew", "diamond", "draft", "dragonfly", "dream", 
    "drizzle", "droplet", "dusk", "echo", "eclipse", "ember", "emerald", "equinox", "ether", "eternity", 
    "falcon", "feather", "fern", "firmament", "fjord", "flame", "flare", "fog", "forest", "frost", "galaxy", 
    "gale", "genesis", "ghost", "glacier", "glade", "glass", "gleam", "glimmer", "glint", "gloaming", "glow", 
    "granite", "grove", "gust", "hail", "halo", "harbor", "harmony", "haven", "haze", "horizon", "hum", "hush", 
    "ice", "iceberg", "illusion", "impulse", "infinity", "intuition", "iris", "ivory", "jade", "jasmine", 
    "jungle", "lagoon", "lake", "landscape", "lantern", "lavender", "leaf", "light", "lightning", "lily", 
    "linen", "loom", "lotus", "luster", "mantle", "marble", "meadow", "melody", "memory", "meteor", "midnight", 
    "mirage", "mirror", "mist", "monsoon", "monument", "moon", "moonlight", "moss", "mountain", "murmur", 
    "mystery", "nadir", "nebula", "nectar", "nightfall", "noon", "nostalgia", "oak", "oasis", "obsidian", 
    "ocean", "onyx", "opal", "oracle", "orb", "orbit", "orchid", "origin", "panorama", "peace", "peak", 
    "pearl", "pendulum", "petal", "phantom", "pine", "pitch", "plain", "planet", "plateau", "pollen", "pond", 
    "poplar", "portal", "prairie", "prism", "pulsar", "quartz", "quasar", "radiance", "rain", "ravine", 
    "ray", "redwood", "reef", "reflection", "refuge", "relic", "resonance", "reverie", "ridge", "ripple", 
    "river", "roar", "root", "ruby", "rumor", "rumble", "rustle", "sanctuary", "sapphire", "satin", "sea", 
    "seascape", "serenity", "shade", "shadow", "shimmer", "shore", "shroud", "silence", "silk", "silver", 
    "skyline", "snow", "sunbeam", "solitude", "soul", "spark", "spectrum", "sphere", "spire", "spirit", 
    "spiral", "squall", "starlight", "static", "steel", "stillness", "storm", "stratosphere", "stream", 
    "summit", "sun", "sundown", "sunrise", "sunset", "supernova", "talisman", "tapestry", "tempest", "thicket", 
    "threshold", "thunder", "tide", "torrent", "tower", "tundra", "twilight"
]