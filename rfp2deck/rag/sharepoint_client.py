from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse

import msal
import requests

from rfp2deck.core.config import settings

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"


@dataclass(frozen=True)
class SharePointAuthConfig:
    tenant_id: str
    client_id: str
    scopes: list[str]
    token_cache_path: Path


def _parse_scopes(value: str) -> list[str]:
    scopes = [s.strip() for s in value.split(",") if s.strip()]
    return scopes or ["Files.Read.All", "Sites.Read.All"]


def get_auth_config(
    tenant_id: Optional[str] = None,
    client_id: Optional[str] = None,
    scopes: Optional[Iterable[str]] = None,
) -> SharePointAuthConfig:
    tenant = tenant_id or settings.sp_tenant_id
    client = client_id or settings.sp_client_id
    if not tenant or not client:
        raise ValueError("Missing SharePoint tenant/client ID. Set SP_TENANT_ID and SP_CLIENT_ID.")
    if scopes is None:
        scopes = _parse_scopes(settings.sp_scopes)
    scope_list = list(scopes)
    cache_path = settings.data_dir / "sharepoint_token_cache.bin"
    return SharePointAuthConfig(
        tenant_id=tenant,
        client_id=client,
        scopes=scope_list,
        token_cache_path=cache_path,
    )


def _load_token_cache(path: Path) -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if path.exists():
        cache.deserialize(path.read_text(encoding="utf-8"))
    return cache


def _save_token_cache(cache: msal.SerializableTokenCache, path: Path) -> None:
    if cache.has_state_changed:
        path.write_text(cache.serialize(), encoding="utf-8")


def get_access_token(config: SharePointAuthConfig) -> str:
    cache = _load_token_cache(config.token_cache_path)
    app = msal.PublicClientApplication(
        client_id=config.client_id,
        authority=f"https://login.microsoftonline.com/{config.tenant_id}",
        token_cache=cache,
    )

    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(scopes=config.scopes, account=accounts[0])
        if result and "access_token" in result:
            _save_token_cache(cache, config.token_cache_path)
            return result["access_token"]

    flow = app.initiate_device_flow(scopes=config.scopes)
    if "user_code" not in flow:
        raise RuntimeError("Failed to start device-code flow.")
    print(flow["message"])
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError(f"Device-code auth failed: {result.get('error_description')}")
    _save_token_cache(cache, config.token_cache_path)
    return result["access_token"]


def _graph_get(url: str, token: str, params: Optional[dict] = None) -> dict:
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def _graph_get_paged(url: str, token: str, params: Optional[dict] = None) -> list[dict]:
    out: list[dict] = []
    next_url = url
    next_params = params
    while next_url:
        payload = _graph_get(next_url, token, params=next_params)
        out.extend(payload.get("value", []))
        next_url = payload.get("@odata.nextLink")
        next_params = None
    return out


def get_site_id(site_url: str, token: str) -> str:
    parsed = urlparse(site_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("site_url must be a full URL like https://contoso.sharepoint.com/sites/siteA")
    path = parsed.path
    site = _graph_get(f"{GRAPH_ROOT}/sites/{parsed.netloc}:{path}", token)
    return site["id"]


def get_drive_id(site_id: str, token: str, library_name: Optional[str] = None) -> str:
    if not library_name:
        drive = _graph_get(f"{GRAPH_ROOT}/sites/{site_id}/drive", token)
        return drive["id"]
    drives = _graph_get_paged(f"{GRAPH_ROOT}/sites/{site_id}/drives", token)
    for d in drives:
        if d.get("name") == library_name:
            return d["id"]
    available = ", ".join([d.get("name", "") for d in drives])
    raise ValueError(f"Drive '{library_name}' not found. Available: {available}")


def list_children(
    drive_id: str, token: str, folder_path: Optional[str] = None
) -> list[dict]:
    if folder_path:
        path = folder_path.strip("/")
        url = f"{GRAPH_ROOT}/drives/{drive_id}/root:/{path}:/children"
    else:
        url = f"{GRAPH_ROOT}/drives/{drive_id}/root/children"
    return _graph_get_paged(url, token)


def download_item(drive_id: str, item_id: str, token: str, out_path: Path) -> None:
    url = f"{GRAPH_ROOT}/drives/{drive_id}/items/{item_id}/content"
    with requests.get(url, headers={"Authorization": f"Bearer {token}"}, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        out_path.write_bytes(resp.content)


def walk_drive(
    drive_id: str,
    token: str,
    folder_path: Optional[str] = None,
) -> list[dict]:
    items: list[dict] = []
    queue = [folder_path or ""]
    while queue:
        current = queue.pop(0)
        children = list_children(drive_id, token, current or None)
        for child in children:
            if "folder" in child:
                child_path = child.get("parentReference", {}).get("path", "")
                child_name = child.get("name", "")
                if child_path.startswith("/drives/"):
                    child_path = child_path.split(":", 1)[-1].lstrip("/")
                next_path = "/".join([p for p in [child_path, child_name] if p])
                queue.append(next_path)
            else:
                items.append(child)
    return items
