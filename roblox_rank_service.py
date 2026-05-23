from __future__ import annotations

import os
from typing import Any

import aiohttp
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()


def getenv(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return v.strip()


SERVICE_SECRET = getenv("ROBLOX_SERVICE_SECRET")
OPENCLOUD_API_KEY = getenv("ROBLOX_OPENCLOUD_API_KEY")
GROUP_ID = int(getenv("ROBLOX_GROUP_ID", "34438615") or "34438615")
PORT = int(getenv("PORT", "8080") or "8080")


async def _request_json(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    async with session.request(method, url, headers=headers, json=json, timeout=30) as resp:
        text = await resp.text()
        if resp.status // 100 != 2:
            raise web.HTTPBadGateway(text=f"Roblox API {method} {url} failed {resp.status}: {text}")
        if not text:
            return {}
        return await resp.json()


def _require_secret(request: web.Request) -> None:
    if not SERVICE_SECRET:
        raise web.HTTPInternalServerError(text="ROBLOX_SERVICE_SECRET is not configured on this service.")
    if request.headers.get("X-Secret-Key") != SERVICE_SECRET:
        raise web.HTTPUnauthorized(text="Invalid X-Secret-Key")


def _headers() -> dict[str, str]:
    if not OPENCLOUD_API_KEY:
        raise web.HTTPInternalServerError(text="ROBLOX_OPENCLOUD_API_KEY is not configured.")
    return {"x-api-key": OPENCLOUD_API_KEY, "Content-Type": "application/json"}


async def health(_: web.Request) -> web.Response:
    return web.json_response({"ok": True, "groupId": GROUP_ID})


async def ranks(request: web.Request) -> web.Response:
    _require_secret(request)
    headers = _headers()
    url = f"https://apis.roblox.com/cloud/v2/groups/{GROUP_ID}/roles"
    async with aiohttp.ClientSession() as session:
        data = await _request_json(session, "GET", url, headers=headers)

    roles = []
    for role in data.get("groupRoles", []) or data.get("roles", []) or []:
        role_name = role.get("displayName") or role.get("name")
        role_path = str(role.get("path") or "")
        role_id = role.get("id")
        if not role_id and role_path.startswith(f"groups/{GROUP_ID}/roles/"):
            role_id = role_path.rsplit("/", 1)[-1]
        roles.append({
            "id": int(role_id) if role_id is not None and str(role_id).isdigit() else role_id,
            "roleId": int(role_id) if role_id is not None and str(role_id).isdigit() else role_id,
            "name": role_name,
            "rank": role.get("rank"),
        })

    return web.json_response({"roles": roles})


async def set_rank(request: web.Request) -> web.Response:
    _require_secret(request)
    body = await request.json()
    user_id = int(body.get("robloxId") or 0)
    group_id = int(body.get("groupId") or GROUP_ID)
    role_id = body.get("roleId")
    if not user_id or not role_id:
        raise web.HTTPBadRequest(text="robloxId and roleId are required.")

    headers = _headers()
    list_url = f"https://apis.roblox.com/cloud/v2/groups/{group_id}/memberships?maxPageSize=100&filter=user%3Dusers%2F{user_id}"
    async with aiohttp.ClientSession() as session:
        memberships = await _request_json(session, "GET", list_url, headers=headers)
        items = memberships.get("groupMemberships", []) or memberships.get("memberships", []) or []
        if not items:
            raise web.HTTPNotFound(text=f"No membership found for user {user_id} in group {group_id}.")

        membership_path = str(items[0].get("path") or "")
        if not membership_path:
            raise web.HTTPBadGateway(text="Membership path missing in Open Cloud response.")

        update_url = f"https://apis.roblox.com/cloud/v2/{membership_path}:assignRole"
        await _request_json(
            session,
            "POST",
            update_url,
            headers=headers,
            json={"role": f"groups/{group_id}/roles/{int(role_id)}"},
        )

    return web.json_response({"ok": True, "robloxId": user_id, "groupId": group_id, "roleId": int(role_id)})


app = web.Application()
app.add_routes([
    web.get("/health", health),
    web.get("/ranks", ranks),
    web.post("/set-rank", set_rank),
])

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=PORT)
