import os
from urllib.parse import urlparse

import httpx


DEFAULT_UPLOAD_API_URL = "https://tmpfiles.org/api/v1/upload"
DEFAULT_UPLOAD_TIMEOUT = 120
TMPFILES_MAX_SIZE_BYTES = 100 * 1024 * 1024


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
