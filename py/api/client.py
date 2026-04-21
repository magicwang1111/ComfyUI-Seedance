import json

import httpx


DEFAULT_BASE_URL = "https://aihubmix.com"


class VideoAPIError(Exception):
    def __init__(self, status_code, status=None, message=None, payload=None):
        self.status_code = status_code
        self.status = status
        self.message = message or "Unknown API error."
        self.payload = payload
        super().__init__(self.__str__())

    def __str__(self):
        status_label = self.status or "ERROR"
        return f"Video API request failed with {self.status_code} {status_label}: {self.message}"

    @classmethod
    def from_response(cls, response):
        payload = None
        message = None
        status = None

        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            payload = None

        if isinstance(payload, dict):
            error_payload = payload.get("error")
            if isinstance(error_payload, dict):
                message = error_payload.get("message") or json.dumps(error_payload, ensure_ascii=False)
                status = error_payload.get("type") or payload.get("status")
            elif error_payload:
                message = str(error_payload)
                status = payload.get("status")

            if not message:
                message = payload.get("message") or payload.get("detail")
            if not status:
                status = payload.get("status")

        if not message:
            message = response.text.strip() or "Unknown API error."

        return cls(response.status_code, status=status, message=message, payload=payload)


class Client:
    def __init__(self, api_key, timeout=60, base_url=DEFAULT_BASE_URL, poll_interval=15.0):
        api_key = (api_key or "").strip()
        if not api_key:
            raise ValueError("api_key is required.")

        self.api_key = api_key
        self.timeout = timeout
        self.base_url = self.normalize_base_url(base_url)
        self.poll_interval = float(poll_interval)

        timeout_config = httpx.Timeout(connect=10.0, read=timeout, write=timeout, pool=timeout)
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout_config,
            headers=self.build_headers(self.api_key),
        )

    @staticmethod
    def normalize_base_url(base_url):
        normalized = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        if normalized.endswith("/v1"):
            normalized = normalized[:-3].rstrip("/")
        return normalized or DEFAULT_BASE_URL

    @staticmethod
    def build_headers(api_key):
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

    def request(self, method, path, **kwargs):
        if "json" in kwargs and isinstance(kwargs["json"], dict):
            print(f"[ComfyUI-Seedance] {method} {path} payload keys={list(kwargs['json'].keys())}")

        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"Video API request timed out after {self.timeout}s while waiting for {method} {path}.") from exc
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Video API request failed for {method} {path}: {exc}") from exc

        if response.status_code != 200:
            raise VideoAPIError.from_response(response)

        return response.json()

    def download_to_file(self, path, file_path):
        try:
            with self._client.stream("GET", path) as response:
                if response.status_code != 200:
                    raise VideoAPIError.from_response(response)

                with open(file_path, "wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"Video download timed out after {self.timeout}s while waiting for GET {path}.") from exc
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Video download failed for GET {path}: {exc}") from exc

    def absolute_url(self, path):
        if isinstance(path, str) and path.startswith(("http://", "https://")):
            return path
        normalized_path = path if str(path).startswith("/") else f"/{path}"
        return f"{self.base_url}{normalized_path}"

    def close(self):
        self._client.close()
