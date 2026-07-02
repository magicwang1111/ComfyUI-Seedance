import asyncio
import importlib
import json
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
COMFYUI_ROOT = REPO_ROOT.parent.parent
if str(COMFYUI_ROOT) not in sys.path:
    sys.path.insert(0, str(COMFYUI_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

server_routes = importlib.import_module("py.server_routes")
validation_sessions = importlib.import_module("py.validation_sessions")


class FakeRoutes:
    def __init__(self):
        self.handlers = {}

    def get(self, path):
        return self._register("GET", path)

    def post(self, path):
        return self._register("POST", path)

    def _register(self, method, path):
        def decorator(handler):
            self.handlers[(method, path)] = handler
            return handler

        return decorator


class FakeRequest:
    def __init__(self, payload=None, query=None, match_info=None):
        self._payload = payload
        self.rel_url = SimpleNamespace(query=query or {})
        self.match_info = match_info or {}

    async def json(self):
        return self._payload


class FakeValidationClient:
    def create_visual_validate_session(self, callback_url, project_name="default"):
        self.callback_url = callback_url
        self.project_name = project_name
        return {
            "BytedToken": "token-123",
            "H5Link": "https://h5.example.com/validate",
        }

    def get_visual_validate_result(self, byted_token, project_name="default"):
        return {"GroupId": "group-123"}


class ServerRouteTests(unittest.TestCase):
    def test_validation_route_flow_returns_group_id_without_exposing_token(self):
        routes = FakeRoutes()
        prompt_server_cls = SimpleNamespace(instance=SimpleNamespace(routes=routes))
        store = validation_sessions.ValidationSessionStore()
        client = FakeValidationClient()

        @contextmanager
        def fake_asset_client():
            yield client

        with mock.patch.object(server_routes, "_ROUTES_REGISTERED", False):
            with mock.patch.object(server_routes, "_asset_client", fake_asset_client):
                registered = server_routes.register_server_routes(
                    prompt_server_cls=prompt_server_cls,
                    session_store=store,
                )
                self.assertTrue(registered)

                create_response = asyncio.run(
                    routes.handlers[("POST", server_routes.CREATE_VALIDATION_SESSION_ROUTE)](
                        FakeRequest(
                            payload={
                                "project_name": "default",
                                "callback_url": "https://comfy.example.com/seedance/assets/validation/callback",
                            }
                        )
                    )
                )
                created = json.loads(create_response.body)
                session_id = created["session_id"]
                self.assertNotIn("token", json.dumps(created).lower())

                callback_response = asyncio.run(
                    routes.handlers[("GET", server_routes.VALIDATION_CALLBACK_ROUTE)](
                        FakeRequest(
                            query={
                                "session_id": session_id,
                                "bytedToken": "token-123",
                                "resultCode": "10000",
                            }
                        )
                    )
                )
                self.assertEqual(callback_response.status, 200)

                status_response = asyncio.run(
                    routes.handlers[("GET", server_routes.VALIDATION_STATUS_ROUTE)](
                        FakeRequest(match_info={"session_id": session_id})
                    )
                )
                status = json.loads(status_response.body)
                self.assertEqual(status["status"], "group_ready")
                self.assertEqual(status["group_id"], "group-123")
                self.assertNotIn("token", json.dumps(status).lower())


if __name__ == "__main__":
    unittest.main()
