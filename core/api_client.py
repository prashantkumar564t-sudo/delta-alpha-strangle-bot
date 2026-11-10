import os
import time
import json
import hmac
import hashlib
import urllib.request
import urllib.parse
import urllib.error
from typing import Dict, Any, Optional

class DeltaApiClient:
    def __init__(self, api_key: str, api_secret: str, base_url: str):
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.base_url = base_url.rstrip("/")

    def _generate_signature(self, method: str, timestamp: str, path: str, query_string: str, payload_str: str) -> str:
        # Signature: method + timestamp + path + query_string + payload
        message = method + timestamp + path + query_string + payload_str
        return hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

    def request(self, method: str, full_path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        method = method.upper()
        parsed = urllib.parse.urlsplit(full_path)
        path = parsed.path
        query_string = f"?{parsed.query}" if parsed.query else ""
        full_url = f"{self.base_url}{path}{query_string}"

        timestamp = str(int(time.time()))
        payload_str = json.dumps(payload, separators=(',', ':')) if payload else ""

        signature = self._generate_signature(method, timestamp, path, query_string, payload_str)

        headers = {
            "api-key": self.api_key,
            "timestamp": timestamp,
            "signature": signature,
            "User-Agent": "DeltaStrangleBot/1.0",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        data_bytes = payload_str.encode("utf-8") if payload_str else None
        req = urllib.request.Request(full_url, data=data_bytes, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            print(f"[HTTP {e.code}] on {full_url}: {err_body}")
            try:
                return json.loads(err_body)
            except Exception:
                return {"success": False, "error": err_body}
        except Exception as e:
            print(f"[Network Error] {e}")
            return {"success": False, "error": str(e)}