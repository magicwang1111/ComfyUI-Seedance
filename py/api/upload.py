import base64
import hashlib
import hmac
import mimetypes
import os
import posixpath
import secrets
import time
from email.utils import formatdate
from urllib.parse import quote, urlencode, urlparse

import httpx


DEFAULT_UPLOAD_API_URL = "https://tmpfiles.org/api/v1/upload"
DEFAULT_UPLOAD_TIMEOUT = 120
DEFAULT_OSS_SIGNED_URL_EXPIRES = 86400
TMPFILES_MAX_SIZE_BYTES = 100 * 1024 * 1024
IMAGE_DATA_URL_MAX_SIZE_BYTES = 30 * 1024 * 1024


def _normalize_tmpfiles_download_url(page_url):
    normalized = str(page_url or "").strip()
    if not normalized:
        raise ValueError("Upload service did not return a file URL.")

    parsed = urlparse(normalized)
    if parsed.netloc.lower() != "tmpfiles.org":
        return normalized

    path = parsed.path.strip("/")
    if not path:
        raise ValueError("Upload service returned an invalid tmpfiles URL.")

    if path.startswith("dl/"):
        return f"https://tmpfiles.org/{path}"

    return f"https://tmpfiles.org/dl/{path}"


def _normalize_oss_endpoint(endpoint):
    normalized = str(endpoint or "").strip()
    if not normalized:
        return ""

    parsed = urlparse(normalized if "://" in normalized else f"https://{normalized}")
    host = parsed.netloc or parsed.path
    return host.strip().strip("/")


def _clean_oss_config_value(value):
    return str(value or "").strip()


def is_oss_configured(config=None):
    if not isinstance(config, dict):
        return False

    required_keys = [
        "oss_endpoint",
        "oss_access_key_id",
        "oss_access_key_secret",
        "oss_bucket",
    ]
    return all(_clean_oss_config_value(config.get(key)) for key in required_keys)


def _quote_oss_key(object_key):
    return quote(str(object_key or "").lstrip("/"), safe="/-_.~")


def _build_oss_object_key(prefix, filename, now=None, token=None):
    normalized_prefix = str(prefix or "").strip().strip("/")
    normalized_name = os.path.basename(str(filename or "").strip())
    extension = os.path.splitext(normalized_name)[1].lower()
    if not extension:
        extension = ".bin"

    now = int(time.time() if now is None else now)
    token = str(token or secrets.token_hex(8)).lower()
    date_prefix = time.strftime("%Y/%m/%d", time.gmtime(now))
    object_name = f"{now}-{token}{extension}"

    parts = [part for part in [normalized_prefix, date_prefix, object_name] if part]
    return posixpath.join(*parts)


def _oss_canonical_resource(bucket, object_key):
    return f"/{str(bucket or '').strip()}/{str(object_key or '').lstrip('/')}"


def _oss_sign(secret_access_key, string_to_sign):
    digest = hmac.new(
        str(secret_access_key or "").encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def _build_oss_upload_headers(access_key_id, secret_access_key, bucket, object_key, content_type, date_header):
    canonical_resource = _oss_canonical_resource(bucket, object_key)
    string_to_sign = f"PUT\n\n{content_type}\n{date_header}\n{canonical_resource}"
    signature = _oss_sign(secret_access_key, string_to_sign)
    return {
        "Date": date_header,
        "Content-Type": content_type,
        "Authorization": f"OSS {access_key_id}:{signature}",
    }


def _build_oss_signed_get_url(endpoint, access_key_id, secret_access_key, bucket, object_key, expires_at):
    canonical_resource = _oss_canonical_resource(bucket, object_key)
    string_to_sign = f"GET\n\n\n{int(expires_at)}\n{canonical_resource}"
    signature = _oss_sign(secret_access_key, string_to_sign)
    base_url = f"https://{str(bucket).strip()}.{_normalize_oss_endpoint(endpoint)}/{_quote_oss_key(object_key)}"
    query = urlencode(
        {
            "OSSAccessKeyId": access_key_id,
            "Expires": int(expires_at),
            "Signature": signature,
        }
    )
    return f"{base_url}?{query}"


def upload_file_to_tmpfiles(file_path, timeout=DEFAULT_UPLOAD_TIMEOUT):
    normalized_path = os.path.abspath(os.fspath(file_path))
    if not os.path.exists(normalized_path):
        raise ValueError(f"Upload file does not exist: {normalized_path}")

    file_size = os.path.getsize(normalized_path)
    if file_size > TMPFILES_MAX_SIZE_BYTES:
        raise ValueError("Local media file exceeds tmpfiles.org's 100 MB upload limit.")

    filename = os.path.basename(normalized_path)
    with open(normalized_path, "rb") as handle:
        response = httpx.post(
            DEFAULT_UPLOAD_API_URL,
            files={"file": (filename, handle)},
            timeout=float(timeout),
        )

    try:
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ConnectionError(f"Temporary media upload failed: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError("Temporary media upload returned invalid JSON.") from exc

    if payload.get("status") != "success":
        raise ValueError(f"Temporary media upload failed: {payload}")

    page_url = payload.get("data", {}).get("url")
    return _normalize_tmpfiles_download_url(page_url)


def upload_file_to_oss(file_path, config, timeout=DEFAULT_UPLOAD_TIMEOUT):
    normalized_path = os.path.abspath(os.fspath(file_path))
    if not os.path.exists(normalized_path):
        raise ValueError(f"Upload file does not exist: {normalized_path}")

    if not is_oss_configured(config):
        raise ValueError("OSS upload is not configured.")

    endpoint = _normalize_oss_endpoint(config.get("oss_endpoint"))
    access_key_id = _clean_oss_config_value(config.get("oss_access_key_id"))
    secret_access_key = _clean_oss_config_value(config.get("oss_access_key_secret"))
    bucket = _clean_oss_config_value(config.get("oss_bucket"))
    prefix = _clean_oss_config_value(config.get("oss_prefix"))
    signed_url_expires = int(config.get("oss_signed_url_expires") or DEFAULT_OSS_SIGNED_URL_EXPIRES)
    if signed_url_expires <= 0:
        raise ValueError("oss_signed_url_expires must be greater than 0.")

    filename = os.path.basename(normalized_path)
    object_key = _build_oss_object_key(prefix, filename)
    content_type = mimetypes.guess_type(normalized_path)[0] or "application/octet-stream"
    date_header = formatdate(usegmt=True)
    headers = _build_oss_upload_headers(
        access_key_id,
        secret_access_key,
        bucket,
        object_key,
        content_type,
        date_header,
    )
    upload_url = f"https://{bucket}.{endpoint}/{_quote_oss_key(object_key)}"

    with open(normalized_path, "rb") as handle:
        response = httpx.put(
            upload_url,
            content=handle,
            headers=headers,
            timeout=float(timeout),
        )

    try:
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ConnectionError(f"OSS media upload failed: {exc}") from exc

    expires_at = int(time.time()) + signed_url_expires
    return _build_oss_signed_get_url(
        endpoint,
        access_key_id,
        secret_access_key,
        bucket,
        object_key,
        expires_at,
    )


def upload_file_to_public_url(file_path, timeout=DEFAULT_UPLOAD_TIMEOUT, public_upload_config=None):
    if is_oss_configured(public_upload_config):
        return upload_file_to_oss(file_path, public_upload_config, timeout=timeout)
    return upload_file_to_tmpfiles(file_path, timeout=timeout)


def file_to_data_url(file_path, default_mime_type="application/octet-stream", max_size_bytes=None):
    normalized_path = os.path.abspath(os.fspath(file_path))
    if not os.path.exists(normalized_path):
        raise ValueError(f"Data URL file does not exist: {normalized_path}")

    file_size = os.path.getsize(normalized_path)
    if max_size_bytes is not None and file_size > max_size_bytes:
        max_mb = max_size_bytes / (1024 * 1024)
        raise ValueError(f"Local media file exceeds the {max_mb:.0f} MB data URL limit.")

    mime_type = mimetypes.guess_type(normalized_path)[0] or default_mime_type
    with open(normalized_path, "rb") as handle:
        encoded = base64.b64encode(handle.read()).decode("ascii")

    return f"data:{mime_type};base64,{encoded}"
