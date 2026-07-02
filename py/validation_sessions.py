import copy
import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


DEFAULT_VALIDATION_SESSION_TTL = 30 * 60
SUCCESS_RESULT_CODE = "10000"


@dataclass
class ValidationSession:
    session_id: str
    byted_token: str
    project_name: str
    callback_url: str
    h5_link: str
    created_at: float
    expires_at: float
    status: str = "awaiting_user"
    result_code: str = ""
    group_id: str = ""
    error: str = ""


def build_callback_url(callback_url, session_id):
    normalized_url = str(callback_url or "").strip()
    parts = urlsplit(normalized_url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("callback_url must be a valid http or https URL.")

    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "session_id"]
    query.append(("session_id", str(session_id or "").strip()))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class ValidationSessionStore:
    def __init__(self, ttl=DEFAULT_VALIDATION_SESSION_TTL, clock=None):
        self.ttl = float(ttl)
        if self.ttl <= 0:
            raise ValueError("ttl must be greater than 0.")
        self._clock = clock or time.time
        self._sessions = {}
        self._lock = threading.RLock()

    def new_session_id(self):
        return secrets.token_urlsafe(24)

    def create(self, session_id, byted_token, project_name, callback_url, h5_link):
        now = self._clock()
        session = ValidationSession(
            session_id=str(session_id or "").strip(),
            byted_token=str(byted_token or "").strip(),
            project_name=str(project_name or "").strip(),
            callback_url=str(callback_url or "").strip(),
            h5_link=str(h5_link or "").strip(),
            created_at=now,
            expires_at=now + self.ttl,
        )
        if not session.session_id:
            raise ValueError("session_id is required.")
        if not session.byted_token:
            raise ValueError("byted_token is required.")
        if not session.project_name:
            raise ValueError("project_name is required.")
        if not session.h5_link:
            raise ValueError("h5_link is required.")

        with self._lock:
            self._remove_expired_locked(now)
            self._sessions[session.session_id] = session
        return copy.copy(session)

    def get(self, session_id):
        normalized_id = str(session_id or "").strip()
        now = self._clock()
        with self._lock:
            self._remove_expired_locked(now)
            session = self._sessions.get(normalized_id)
            if session is None:
                raise KeyError(normalized_id)
            return copy.copy(session)

    def record_callback(self, session_id, byted_token, result_code, error=""):
        normalized_token = str(byted_token or "").strip()
        normalized_code = str(result_code or "").strip()
        with self._lock:
            session = self._get_locked(session_id)
            if not normalized_token:
                raise ValueError("Callback BytedToken is required.")
            if not secrets.compare_digest(session.byted_token, normalized_token):
                raise ValueError("Callback BytedToken does not match this validation session.")

            session.result_code = normalized_code
            if normalized_code == SUCCESS_RESULT_CODE:
                session.status = "verified"
                session.error = ""
            else:
                session.status = "failed"
                session.error = str(error or f"Validation failed with resultCode={normalized_code or 'missing'}.")
            return copy.copy(session)

    def mark_group_ready(self, session_id, group_id):
        normalized_group_id = str(group_id or "").strip()
        if not normalized_group_id:
            raise ValueError("group_id is required.")

        with self._lock:
            session = self._get_locked(session_id)
            session.group_id = normalized_group_id
            session.status = "group_ready"
            session.error = ""
            return copy.copy(session)

    def public_state(self, session_id):
        session = self.get(session_id)
        return {
            "session_id": session.session_id,
            "project_name": session.project_name,
            "status": session.status,
            "result_code": session.result_code,
            "group_id": session.group_id,
            "error": session.error,
            "expires_at": session.expires_at,
        }

    def _get_locked(self, session_id):
        now = self._clock()
        self._remove_expired_locked(now)
        normalized_id = str(session_id or "").strip()
        session = self._sessions.get(normalized_id)
        if session is None:
            raise KeyError(normalized_id)
        return session

    def _remove_expired_locked(self, now):
        expired_ids = [session_id for session_id, session in self._sessions.items() if session.expires_at <= now]
        for session_id in expired_ids:
            del self._sessions[session_id]
