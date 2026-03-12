from __future__ import annotations

import json
from typing import Any

from starlette.requests import Request
from starlette.responses import Response


def _stringify_detail(detail: Any) -> str:
    if detail is None:
        return ""
    if isinstance(detail, str):
        return detail.strip()
    try:
        return json.dumps(detail, ensure_ascii=False)
    except Exception:
        return str(detail).strip()


def _extract_response_detail(response: Response) -> str:
    body = getattr(response, "body", None)
    if body is None:
        return ""

    try:
        raw = body.tobytes() if isinstance(body, memoryview) else body
    except Exception:
        raw = body

    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="ignore").strip()
    else:
        text = str(raw).strip()
    if not text:
        return ""

    content_type = str(response.headers.get("content-type") or "").lower()
    if "json" not in content_type:
        return ""

    try:
        payload = json.loads(text)
    except Exception:
        return ""

    if not isinstance(payload, dict):
        return ""
    return _stringify_detail(payload.get("detail"))


async def _buffer_response_body(response: Response) -> tuple[Response, bytes]:
    body = getattr(response, "body", None)
    if body is not None:
        try:
            raw = body.tobytes() if isinstance(body, memoryview) else body
        except Exception:
            raw = body
        if isinstance(raw, bytes):
            return response, raw
        if isinstance(raw, str):
            return response, raw.encode("utf-8")
        return response, bytes(raw)

    chunks: list[bytes] = []
    body_iterator = getattr(response, "body_iterator", None)
    if body_iterator is not None:
        async for chunk in body_iterator:
            if isinstance(chunk, memoryview):
                chunks.append(chunk.tobytes())
            elif isinstance(chunk, bytes):
                chunks.append(chunk)
            else:
                chunks.append(str(chunk).encode("utf-8"))

    body_bytes = b"".join(chunks)
    rebuilt = Response(
        content=body_bytes,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
        background=response.background,
    )
    return rebuilt, body_bytes


def _extract_response_detail_from_body(response: Response, body: bytes) -> str:
    if not body:
        return ""

    try:
        text = body.decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""
    if not text:
        return ""

    content_type = str(response.headers.get("content-type") or "").lower()
    if "json" not in content_type:
        return ""

    try:
        payload = json.loads(text)
    except Exception:
        return ""

    if not isinstance(payload, dict):
        return ""
    return _stringify_detail(payload.get("detail"))


async def log_server_errors_middleware(logger, request: Request, call_next):
    method = str(request.method or "").upper() or "GET"
    path = str(request.url.path or "").strip() or "/"

    try:
        response = await call_next(request)
    except Exception as exc:
        logger.exception("[server-exception] method=%s path=%s error=%s", method, path, exc)
        raise

    status = int(getattr(response, "status_code", 0) or 0)
    if status >= 500:
        response, body = await _buffer_response_body(response)
        detail = _extract_response_detail_from_body(response, body) or _extract_response_detail(response)
        if detail:
            logger.error("[server-5xx] status=%s method=%s path=%s detail=%s", status, method, path, detail)
        else:
            logger.error("[server-5xx] status=%s method=%s path=%s", status, method, path)

    return response
