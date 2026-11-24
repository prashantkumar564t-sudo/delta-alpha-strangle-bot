import os


def load_env(env_path: str | None = None) -> None:
    """
    Lightweight built-in .env parser using only standard library.
    Parses key-value pairs, ignores empty lines and comments (#),
    supports UTF-8 and UTF-8-SIG (Windows BOM), and injects into os.environ.
    """
    if env_path is None:
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env_path = os.path.join(root_dir, ".env")

    if not os.path.exists(env_path):
        return

    content = ""
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            with open(env_path, "r", encoding=encoding) as f:
                content = f.read()
            break
        except UnicodeError:
            continue

    for line in content.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ[key.strip()] = val.strip().strip("'\"")


def setup_proxy() -> str | None:
    """
    Constructs and returns the configured proxy URL string if proxy variables are present.
    NOTE: Does NOT globally install the opener via urllib.request.install_opener()
    to prevent leaking public market data and Telegram alerts through the static proxy.
    Proxy routing is isolated exclusively inside DeltaApiClient for private authenticated calls.
    """
    proxy_host = os.getenv("PROXY_HOST", "").strip()
    proxy_port = os.getenv("PROXY_PORT", "").strip()
    proxy_user = os.getenv("PROXY_USER", "").strip()
    proxy_pass = os.getenv("PROXY_PASS", "").strip()

    if proxy_host and proxy_port:
        if proxy_user and proxy_pass:
            return f"http://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}"
        return f"http://{proxy_host}:{proxy_port}"

    return None


# Auto-load on import
load_env()
ACTIVE_PROXY = setup_proxy()

API_KEY = os.getenv("DELTA_API_KEY", "")
API_SECRET = os.getenv("DELTA_API_SECRET", "")
BASE_URL = os.getenv("DELTA_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
TARGET_LOTS = int(os.getenv("TARGET_LOTS", os.getenv("LOT_SIZE", "1000")))
MIN_TRADEABLE_LOTS = int(os.getenv("MIN_TRADEABLE_LOTS", "100"))
LOT_SIZE = TARGET_LOTS
DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", "40"))
DRY_RUN = os.getenv("DRY_RUN", "False").lower() in ("true", "1", "yes")

# Combo A Stop-Loss & Risk Management Parameters
SL_MULTIPLIER = float(os.getenv("SL_MULTIPLIER", "2.00"))
COST_TRAIL_MULTIPLIER = float(os.getenv("COST_TRAIL_MULTIPLIER", "1.00"))
HARD_KILL_SWITCH_USD = float(os.getenv("HARD_KILL_SWITCH_USD", "1185.00"))

# Telegram Notifications
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
