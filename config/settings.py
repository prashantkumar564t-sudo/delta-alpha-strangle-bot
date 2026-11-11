import os
import urllib.request
from typing import Optional

def load_env(env_path: Optional[str] = None) -> None:
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

def setup_proxy() -> Optional[str]:
    """
    Configures and globally installs a urllib proxy opener if proxy variables are present.
    Routes all outbound urllib.request.urlopen() calls through the static proxy.
    Gracefully falls back to direct connection if variables are missing or empty.
    """
    proxy_host = os.getenv("PROXY_HOST", "").strip()
    proxy_port = os.getenv("PROXY_PORT", "").strip()
    proxy_user = os.getenv("PROXY_USER", "").strip()
    proxy_pass = os.getenv("PROXY_PASS", "").strip()

    if proxy_host and proxy_port:
        if proxy_user and proxy_pass:
            proxy_url = f"http://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}"
        else:
            proxy_url = f"http://{proxy_host}:{proxy_port}"

        proxy_handler = urllib.request.ProxyHandler({
            "http": proxy_url,
            "https": proxy_url
        })
        opener = urllib.request.build_opener(proxy_handler)
        urllib.request.install_opener(opener)
        return proxy_url

    return None

# Auto-load on import
load_env()
ACTIVE_PROXY = setup_proxy()

API_KEY = os.getenv("DELTA_API_KEY", "")
API_SECRET = os.getenv("DELTA_API_SECRET", "")
BASE_URL = os.getenv("DELTA_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
LOT_SIZE = int(os.getenv("LOT_SIZE", "1"))
