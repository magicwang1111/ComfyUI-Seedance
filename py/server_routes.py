from .api import AssetAPIError
from .nodes import _asset_client, _create_asset_project_name
from .validation_sessions import ValidationSessionStore, build_callback_url


CREATE_VALIDATION_SESSION_ROUTE = "/seedance/assets/validation/session"
VALIDATION_CALLBACK_ROUTE = "/seedance/assets/validation/callback"
VALIDATION_STATUS_ROUTE = "/seedance/assets/validation/session/{session_id}"

VALIDATION_SESSIONS = ValidationSessionStore()
_ROUTES_REGISTERED = False


def _error_response(web, message, status):
    return web.json_response({"error": str(message)}, status=status)


def _extract_validation_result(result):
    if not isinstance(result, dict):
        raise ValueError("Ark validation API returned an invalid response.")
    byted_token = str(result.get("BytedToken") or "").strip()
    h5_link = str(result.get("H5Link") or "").strip()
    if not byted_token or not h5_link:
        raise ValueError("CreateVisualValidateSession did not return BytedToken and H5Link.")
    return byted_token, h5_link


def _extract_group_id(result):
    if not isinstance(result, dict):
        return ""
    return str(result.get("GroupId") or "").strip()


def register_server_routes(prompt_server_cls=None, session_store=None):
    global _ROUTES_REGISTERED
    if _ROUTES_REGISTERED:
        return True

    try:
        from aiohttp import web
    except Exception:
        return False

    if prompt_server_cls is None:
        try:
            from server import PromptServer as prompt_server_cls
        except Exception:
            return False

    prompt_server = getattr(prompt_server_cls, "instance", None)
    routes = getattr(prompt_server, "routes", None)
    if routes is None:
        return False

    store = session_store or VALIDATION_SESSIONS

    @routes.post(CREATE_VALIDATION_SESSION_ROUTE)
    async def create_validation_session(request):
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError("Request body must be a JSON object.")

            project_name = str(payload.get("project_name") or "").strip() or _create_asset_project_name()
            callback_base_url = str(payload.get("callback_url") or "").strip()
            session_id = store.new_session_id()
            callback_url = build_callback_url(callback_base_url, session_id)

            with _asset_client() as client:
                result = client.create_visual_validate_session(callback_url, project_name=project_name)

            byted_token, h5_link = _extract_validation_result(result)
            session = store.create(
                session_id=session_id,
                byted_token=byted_token,
                project_name=project_name,
                callback_url=callback_url,
                h5_link=h5_link,
            )
            return web.json_response(
                {
                    "session_id": session.session_id,
                    "h5_link": session.h5_link,
                    "status": session.status,
                    "expires_at": session.expires_at,
                }
            )
        except ValueError as exc:
            return _error_response(web, exc, 400)
        except AssetAPIError as exc:
            return _error_response(web, exc, exc.status_code or 502)
        except Exception as exc:
            return _error_response(web, exc, 500)

    @routes.get(VALIDATION_CALLBACK_ROUTE)
    async def validation_callback(request):
        session_id = str(request.rel_url.query.get("session_id") or "").strip()
        byted_token = str(request.rel_url.query.get("bytedToken") or "").strip()
        result_code = str(request.rel_url.query.get("resultCode") or "").strip()
        algorithm_code = str(request.rel_url.query.get("algorithmBaseRespCode") or "").strip()

        try:
            session = store.record_callback(
                session_id,
                byted_token,
                result_code,
                error=f"真人认证失败：resultCode={result_code or 'missing'}, algorithmBaseRespCode={algorithm_code or 'missing'}",
            )
        except KeyError:
            return web.Response(text="认证会话不存在或已过期。请返回 ComfyUI 重新创建认证。", status=404)
        except ValueError:
            return web.Response(text="认证回调校验失败。请返回 ComfyUI 重新创建认证。", status=400)

        if session.status == "verified":
            message = "真人认证已完成。现在可以关闭此页面并返回 ComfyUI。"
        else:
            message = "真人认证未通过。请关闭此页面并返回 ComfyUI 重新认证。"
        return web.Response(text=message, content_type="text/plain", charset="utf-8")

    @routes.get(VALIDATION_STATUS_ROUTE)
    async def validation_status(request):
        session_id = str(request.match_info.get("session_id") or "").strip()
        force_refresh = str(request.rel_url.query.get("refresh") or "").lower() in {"1", "true", "yes"}
        try:
            session = store.get(session_id)
        except KeyError:
            return _error_response(web, "Validation session not found or expired.", 404)

        query_error = ""
        should_query_group = not session.group_id and (session.status == "verified" or force_refresh)
        if should_query_group and session.status != "failed":
            try:
                with _asset_client() as client:
                    result = client.get_visual_validate_result(
                        session.byted_token,
                        project_name=session.project_name,
                    )
                group_id = _extract_group_id(result)
                if group_id:
                    store.mark_group_ready(session_id, group_id)
            except (AssetAPIError, ValueError) as exc:
                query_error = str(exc)

        response = store.public_state(session_id)
        if query_error:
            response["query_error"] = query_error
        return web.json_response(response)

    _ROUTES_REGISTERED = True
    return True
