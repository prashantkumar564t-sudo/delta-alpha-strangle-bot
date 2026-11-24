from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


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


class DeltaApiClient:
    def __init__(self, api_key: str, api_secret: str, base_url: str):
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.base_url = base_url.rstrip("/")
        self.proxy_url = setup_proxy()

        # 1. Direct Opener (Default local internet, 0 KB proxy bandwidth)
        self.direct_opener = urllib.request.build_opener()

        # 2. Isolated Proxy Opener (Exclusively for authenticated private orders/positions)
        if self.proxy_url:
            proxy_handler = urllib.request.ProxyHandler(
                {
                    "http": self.proxy_url,
                    "https": self.proxy_url,
                }
            )
            self.proxy_opener = urllib.request.build_opener(proxy_handler)
            self.has_proxy = True
        else:
            self.proxy_opener = self.direct_opener
            self.has_proxy = False

    def _generate_signature(self, method: str, timestamp: str, path: str, query_string: str, payload_str: str) -> str:
        # Signature: method + timestamp + path + query_string + payload
        message = method + timestamp + path + query_string + payload_str
        return hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def request_public(
        self,
        method: str,
        full_path: str,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> dict[str, Any]:
        """
        Routes public market data (/v2/tickers, /v2/products) directly over default local internet.
        Consumes 0 KB proxy bandwidth, decompresses gzip in-memory, and includes 3-attempt retry loop.
        """
        method = method.upper()
        parsed = urllib.parse.urlsplit(full_path)
        path = parsed.path
        query_string = f"?{parsed.query}" if parsed.query else ""
        full_url = f"{self.base_url}{path}{query_string}"

        headers = {
            "User-Agent": "DeltaStrangleBot/1.0",
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        }
        req = urllib.request.Request(full_url, headers=headers, method=method)

        for attempt in range(1, max_retries + 1):
            try:
                with self.direct_opener.open(req, timeout=15) as response:
                    content = response.read()
                    if response.headers.get("Content-Encoding") == "gzip":
                        content = gzip.decompress(content)
                    return json.loads(content.decode("utf-8"))
            except urllib.error.HTTPError as e:
                err_body = e.read()
                try:
                    if e.headers.get("Content-Encoding") == "gzip":
                        err_body = gzip.decompress(err_body)
                    parsed_err = json.loads(err_body.decode("utf-8"))
                except Exception:
                    parsed_err = {"success": False, "error": str(err_body), "http_code": e.code}

                if e.code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    time.sleep(retry_delay * attempt)
                    continue
                return parsed_err
            except Exception as e:
                if attempt < max_retries:
                    time.sleep(retry_delay * attempt)
                    continue
                return {"success": False, "error": str(e)}

        return {"success": False, "error": "Max retries exceeded"}

    def request_private(
        self,
        method: str,
        full_path: str,
        payload: dict[str, Any] | None = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> dict[str, Any]:
        """
        Routes authenticated orders, positions, and brackets strictly through the Static IP Proxy.
        Enforces Delta HMAC-SHA256 signature and includes a 3-attempt retry wrapper for transient errors.
        """
        method = method.upper()
        parsed = urllib.parse.urlsplit(full_path)
        path = parsed.path
        query_string = f"?{parsed.query}" if parsed.query else ""
        full_url = f"{self.base_url}{path}{query_string}"

        for attempt in range(1, max_retries + 1):
            timestamp = str(int(time.time()))
            payload_str = json.dumps(payload, separators=(",", ":")) if payload else ""
            signature = self._generate_signature(method, timestamp, path, query_string, payload_str)

            headers = {
                "api-key": self.api_key,
                "timestamp": timestamp,
                "signature": signature,
                "User-Agent": "DeltaStrangleBot/1.0",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            data_bytes = payload_str.encode("utf-8") if payload_str else None
            req = urllib.request.Request(full_url, data=data_bytes, headers=headers, method=method)

            try:
                with self.proxy_opener.open(req, timeout=15) as response:
                    raw = response.read().decode("utf-8")
                    return json.loads(raw)
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="replace")
                # Retry on rate limit (429) or transient gateway errors (502, 503, 504)
                if e.code in (429, 502, 503, 504) and attempt < max_retries:
                    time.sleep(retry_delay * attempt)
                    continue
                try:
                    return json.loads(err_body)
                except Exception:
                    return {"success": False, "error": err_body, "http_code": e.code}
            except Exception as e:
                if attempt < max_retries:
                    time.sleep(retry_delay * attempt)
                    continue
                return {"success": False, "error": str(e)}

        return {"success": False, "error": "Max retries exceeded"}

    def request(
        self,
        method: str,
        full_path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Backward-compatible dispatcher:
        Automatically routes public market data endpoints (/v2/products, /v2/tickers) to request_public
        and all authenticated endpoints (/v2/orders*, /v2/positions, /v2/wallet*) to request_private.
        """
        parsed = urllib.parse.urlsplit(full_path)
        path = parsed.path
        public_endpoints = (
            "/v2/products",
            "/v2/tickers",
            "/v2/l2orderbook",
            "/v2/orderbook",
            "/v2/indices",
            "/v2/underlying-prices",
            "/v2/settlement-prices",
            "/v2/assets",
            "/v2/depth",
        )
        if method == "GET" and path.startswith(public_endpoints):
            return self.request_public(method, full_path)
        return self.request_private(method, full_path, payload)
