import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlencode, urlparse

import httpx


DEFAULT_ASSET_BASE_URL = "https://ark.cn-beijing.volcengineapi.com"
DEFAULT_ASSET_REGION = "cn-beijing"
DEFAULT_ASSET_SERVICE = "ark"
DEFAULT_ASSET_VERSION = "2024-01-01"
DEFAULT_ASSET_POLL_INTERVAL = 5.0
DEFAULT_ASSET_TIMEOUT = 60
ACTIVE_ASSET_STATUS = "active"
PROCESSING_ASSET_STATUSES = {"processing", "pending", "queued"}
FAILED_ASSET_STATUSES = {"failed", "error", "rejected"}


class AssetAPIError(RuntimeError):
    def __init__(self, message, status_code=None, action=None, response=None):
        super().__init__(message)
        self.status_code = status_code
        self.action = action
        self.response = response


def _clean_required_string(value, field_name):
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} is required.")
    return normalized


def _validate_http_url(value, field_name):
    normalized = _clean_required_string(value, field_name)
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must be a valid http or https URL.")
    return normalized


def _normalize_base_url(base_url):
    return str(base_url or DEFAULT_ASSET_BASE_URL).strip().rstrip("/") or DEFAULT_ASSET_BASE_URL


def _hash_sha256(data):
    return hashlib.sha256(data).hexdigest()


def _hmac_sha256(key, content):
    return hmac.new(key, content.encode("utf-8"), hashlib.sha256).digest()


def _signed_key(secret_access_key, date, region, service):
    date_key = _hmac_sha256(secret_access_key.encode("utf-8"), date)
    region_key = _hmac_sha256(date_key, region)
    service_key = _hmac_sha256(region_key, service)
    return _hmac_sha256(service_key, "request")


class AssetClient:
    def __init__(
        self,
        access_key_id,
        secret_access_key,
        base_url=DEFAULT_ASSET_BASE_URL,
        region=DEFAULT_ASSET_REGION,
        service=DEFAULT_ASSET_SERVICE,
        timeout=DEFAULT_ASSET_TIMEOUT,
        poll_interval=DEFAULT_ASSET_POLL_INTERVAL,
        transport=None,
    ):
        self.access_key_id = _clean_required_string(access_key_id, "access_key_id")
        self.secret_access_key = _clean_required_string(secret_access_key, "secret_access_key")
        self.base_url = _normalize_base_url(base_url)
        self.region = _clean_required_string(region, "region")
        self.service = _clean_required_string(service, "service")
        self.poll_interval = float(poll_interval)
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def close(self):
        self._client.close()

    def _signed_headers(self, method, path, query_string, body_bytes, content_type):
        parsed = urlparse(self.base_url)
        host = parsed.netloc
        request_date = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        auth_date = request_date[:8]
        payload_hash = _hash_sha256(body_bytes)
        signed_headers = ["host", "x-content-sha256", "x-date", "content-type"]
        canonical_headers = "\n".join(
            [
                f"host:{host}",
                f"x-content-sha256:{payload_hash}",
                f"x-date:{request_date}",
                f"content-type:{content_type}",
            ]
        )
        canonical_request = "\n".join(
            [
                method,
                path,
                query_string,
                canonical_headers + "\n",
                ";".join(signed_headers),
                payload_hash,
            ]
        )
        credential_scope = f"{auth_date}/{self.region}/{self.service}/request"
        string_to_sign = "\n".join(
            [
                "HMAC-SHA256",
                request_date,
                credential_scope,
                _hash_sha256(canonical_request.encode("utf-8")),
            ]
        )
        signature = hmac.new(
            _signed_key(self.secret_access_key, auth_date, self.region, self.service),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        authorization = (
            f"HMAC-SHA256 Credential={self.access_key_id}/{credential_scope}, "
            f"SignedHeaders={';'.join(signed_headers)}, Signature={signature}"
        )
        return {
            "Authorization": authorization,
            "Content-Type": content_type,
            "Host": host,
            "X-Content-Sha256": payload_hash,
            "X-Date": request_date,
        }

    def request(self, action, payload):
        action = _clean_required_string(action, "action")
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise ValueError("asset API payload must be a dictionary.")

        body_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        params = {"Action": action, "Version": DEFAULT_ASSET_VERSION}
        query_string = urlencode(params, quote_via=quote)
        path = "/"
        content_type = "application/json; charset=utf-8"
        headers = self._signed_headers("POST", path, query_string, body_bytes, content_type)
        url = f"{self.base_url}{path}?{query_string}"

        try:
            response = self._client.post(url, content=body_bytes, headers=headers)
        except httpx.HTTPError as exc:
            raise AssetAPIError(f"Asset API request failed for {action}: {exc}", action=action) from exc

        try:
            response_payload = response.json()
        except ValueError as exc:
            if response.status_code >= 400:
                raise AssetAPIError(
                    f"Asset API request failed for {action} with HTTP {response.status_code}: {response.text}",
                    status_code=response.status_code,
                    action=action,
                    response=response.text,
                ) from exc
            raise AssetAPIError(f"Asset API returned invalid JSON for {action}.", action=action) from exc

        if response.status_code >= 400:
            raise AssetAPIError(
                f"Asset API request failed for {action} with HTTP {response.status_code}: {response_payload}",
                status_code=response.status_code,
                action=action,
                response=response_payload,
            )

        metadata = response_payload.get("ResponseMetadata") if isinstance(response_payload, dict) else None
        if isinstance(metadata, dict) and metadata.get("Error"):
            error_payload = metadata["Error"]
            message = error_payload.get("Message") or json.dumps(error_payload, ensure_ascii=False)
            raise AssetAPIError(
                f"Asset API request failed for {action}: {message}",
                action=action,
                response=response_payload,
            )

        if isinstance(response_payload, dict) and isinstance(response_payload.get("Result"), dict):
            return response_payload["Result"]
        return response_payload

    def create_asset(self, group_id, source_url, asset_type="Image", project_name="default", name=""):
        payload = {
            "GroupId": _clean_required_string(group_id, "group_id"),
            "URL": _validate_http_url(source_url, "source_url"),
            "AssetType": _clean_required_string(asset_type, "asset_type"),
            "ProjectName": _clean_required_string(project_name or "default", "project_name"),
        }
        if str(name or "").strip():
            payload["Name"] = str(name).strip()
        return self.request("CreateAsset", payload)

    def get_asset(self, asset_id, project_name="default"):
        return self.request(
            "GetAsset",
            {
                "Id": _clean_required_string(asset_id, "asset_id"),
                "ProjectName": _clean_required_string(project_name or "default", "project_name"),
            },
        )

    def wait_for_asset_active(self, asset_id, project_name="default"):
        while True:
            asset_info = self.get_asset(asset_id, project_name=project_name)
            status = str(asset_info.get("Status", "")).strip()
            normalized_status = status.lower()

            if normalized_status == ACTIVE_ASSET_STATUS:
                return asset_info

            if normalized_status in FAILED_ASSET_STATUSES:
                raise RuntimeError(describe_asset_failure(asset_id, asset_info))

            if normalized_status and normalized_status not in PROCESSING_ASSET_STATUSES:
                raise RuntimeError(f"Unexpected asset status for {asset_id}: {status}.")

            time.sleep(self.poll_interval)


def asset_uri_from_id(asset_id):
    return f"asset://{_clean_required_string(asset_id, 'asset_id')}"


def describe_asset_failure(asset_id, asset_info):
    error_payload = asset_info.get("Error") if isinstance(asset_info, dict) else None
    if isinstance(error_payload, dict):
        code = str(error_payload.get("Code") or "").strip()
        message = str(error_payload.get("Message") or "").strip()
        if code == "FaceMismatch":
            return (
                f"Asset {asset_id} failed: FaceMismatch - face consistency verification failed. "
                "The uploaded image does not match the verified person in this Asset Group. "
                "Use an image of the same person for this group, or pass backgrounds/products as normal reference images instead."
            )
        if code or message:
            return f"Asset {asset_id} failed: {code or 'AssetError'} - {message or asset_info}"

    return f"Asset {asset_id} failed moderation or processing: {asset_info}"
