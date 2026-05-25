from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from sersflow.client.exceptions import SersflowApiError


def _extract_detail(resp: httpx.Response) -> Any:
    ctype = (resp.headers.get("content-type") or "").lower()
    if "application/json" in ctype:
        try:
            body = resp.json()
        except json.JSONDecodeError:
            return resp.text
        if isinstance(body, dict) and "detail" in body:
            return body["detail"]
        return body
    return resp.text


def raise_for_response(resp: httpx.Response) -> None:
    if 200 <= resp.status_code < 300:
        return
    raise SersflowApiError(
        status_code=resp.status_code,
        detail=_extract_detail(resp),
        text=resp.text,
    )


def request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: Any | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    r = client.request(method, path, params=params, json=json_body, headers=headers)
    raise_for_response(r)
    if not r.content:
        return None
    return r.json()


def request_text(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: Any | None = None,
    headers: dict[str, str] | None = None,
) -> str:
    r = client.request(method, path, params=params, json=json_body, headers=headers)
    raise_for_response(r)
    return r.text


def request_bytes(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: Any | None = None,
    headers: dict[str, str] | None = None,
) -> bytes:
    r = client.request(method, path, params=params, json=json_body, headers=headers)
    raise_for_response(r)
    return r.content


def stream_response_to_file(
    client: httpx.Client,
    method: str,
    path: str,
    dest: Path | str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> None:
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with client.stream(method, path, params=params, headers=headers) as r:
        raise_for_response(r)
        with dest_path.open("wb") as out:
            for chunk in r.iter_bytes():
                out.write(chunk)


def request_multipart_upload(
    client: httpx.Client,
    path: str,
    *,
    file_field: str,
    paths: list[Path | str],
    upload_names: list[str] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> httpx.Response:
    files: list[tuple[str, tuple[str, Any, str | None]]] = []
    handles: list[Any] = []
    try:
        if upload_names is not None and len(upload_names) != len(paths):
            raise ValueError("upload_names must have the same length as paths")

        for idx, p in enumerate(paths):
            pp = Path(p)
            fh = pp.open("rb")
            handles.append(fh)
            up_name = upload_names[idx] if upload_names is not None else pp.name
            files.append(
                (
                    file_field,
                    (up_name, fh, "application/octet-stream"),
                )
            )
        r = client.post(path, files=files, headers=extra_headers)
        return r
    finally:
        for fh in handles:
            try:
                fh.close()
            except Exception:
                pass
