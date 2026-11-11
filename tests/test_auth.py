import urllib.request
import urllib.error
import hmac
import hashlib
import time
import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

ENV_PATH = os.path.join(ROOT_DIR, ".env")

# .env loading (Pure Standard Library)
if os.path.exists(ENV_PATH):
    for enc in ["utf-8-sig", "utf-8"]:
        try:
            with open(ENV_PATH, "r", encoding=enc) as f:
                content = f.read()
            break
        except UnicodeError:
            continue
    for line in content.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip().strip("'\"")

from core.api_client import setup_proxy

BASE_URL = os.getenv("DELTA_BASE_URL", "https://cdn-ind.testnet.deltaex.org").strip().rstrip("/")
API_KEY = os.getenv("DELTA_API_KEY", "").strip()
API_SECRET = os.getenv("DELTA_API_SECRET", "").strip()

def run_test():
    proxy_url = setup_proxy()
    if proxy_url:
        print(f"[*] Proxy Enabled: {os.getenv('PROXY_HOST')}:{os.getenv('PROXY_PORT')}")
    else:
        print("[*] Direct connection (No proxy configured)")

    method = 'GET'
    timestamp = str(int(time.time()))
    path = '/v2/wallet/balances'
    query_string = ''
    payload = ''
    
    # Official Delta signing logic
    signature_data = method + timestamp + path + query_string + payload
    signature = hmac.new(
        API_SECRET.encode('utf-8'),
        signature_data.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    req_headers = {
        'api-key': API_KEY,
        'timestamp': timestamp,
        'signature': signature,
        'User-Agent': 'python-rest-client',
        'Content-Type': 'application/json'
    }

    url = f"{BASE_URL}{path}"
    print(f"Connecting to: {url}")

    req = urllib.request.Request(url, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            res = json.loads(response.read().decode('utf-8'))
            print("\n[SUCCESS] Demo Account Authenticated!")
            print(f"Response: {res.get('success')}")
            for item in res.get('result', []):
                if float(item.get('balance', 0)) > 0:
                    print(f" - Asset: {item.get('asset_symbol')} | Balance: {item.get('available_balance')}")
    except urllib.error.HTTPError as e:
        print(f"\n[FAILED] HTTP {e.code}: {e.read().decode('utf-8')}")
    except Exception as e:
        print(f"\n[ERROR] {e}")

if __name__ == "__main__":
    run_test()
