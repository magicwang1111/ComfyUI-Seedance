import importlib
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
COMFYUI_ROOT = REPO_ROOT.parent.parent
if str(COMFYUI_ROOT) not in sys.path:
    sys.path.insert(0, str(COMFYUI_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

validation_sessions = importlib.import_module("py.validation_sessions")


class MutableClock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


class ValidationSessionTests(unittest.TestCase):
    def test_callback_url_preserves_query_and_replaces_session_id(self):
        callback_url = validation_sessions.build_callback_url(
            "https://comfy.example.com/callback?source=seedance&session_id=old",
            "new-session",
        )
        self.assertEqual(
            callback_url,
            "https://comfy.example.com/callback?source=seedance&session_id=new-session",
        )

    def test_successful_callback_and_group_result_lifecycle(self):
        clock = MutableClock(1000)
        store = validation_sessions.ValidationSessionStore(ttl=1800, clock=clock)
        store.create(
            session_id="session-1",
            byted_token="token-1",
            project_name="default",
            callback_url="https://comfy.example.com/callback?session_id=session-1",
            h5_link="https://h5.example.com/session",
        )

        verified = store.record_callback("session-1", "token-1", "10000")
        self.assertEqual(verified.status, "verified")

        ready = store.mark_group_ready("session-1", "group-123")
        self.assertEqual(ready.status, "group_ready")
        self.assertEqual(ready.group_id, "group-123")

        public_state = store.public_state("session-1")
        self.assertNotIn("byted_token", public_state)
        self.assertNotIn("h5_link", public_state)

    def test_callback_rejects_mismatched_token(self):
        store = validation_sessions.ValidationSessionStore()
        store.create(
            session_id="session-1",
            byted_token="token-1",
            project_name="default",
            callback_url="https://comfy.example.com/callback?session_id=session-1",
            h5_link="https://h5.example.com/session",
        )

        with self.assertRaisesRegex(ValueError, "does not match"):
            store.record_callback("session-1", "different-token", "10000")

        with self.assertRaisesRegex(ValueError, "is required"):
            store.record_callback("session-1", "", "10000")

    def test_failed_callback_records_actionable_status(self):
        store = validation_sessions.ValidationSessionStore()
        store.create(
            session_id="session-1",
            byted_token="token-1",
            project_name="default",
            callback_url="https://comfy.example.com/callback?session_id=session-1",
            h5_link="https://h5.example.com/session",
        )

        failed = store.record_callback("session-1", "token-1", "10001", error="validation cancelled")
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.error, "validation cancelled")

    def test_expired_session_is_removed(self):
        clock = MutableClock(1000)
        store = validation_sessions.ValidationSessionStore(ttl=10, clock=clock)
        store.create(
            session_id="session-1",
            byted_token="token-1",
            project_name="default",
            callback_url="https://comfy.example.com/callback?session_id=session-1",
            h5_link="https://h5.example.com/session",
        )

        clock.value = 1010
        with self.assertRaises(KeyError):
            store.get("session-1")


if __name__ == "__main__":
    unittest.main()
