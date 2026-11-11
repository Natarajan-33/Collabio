"""Supabase Storage for proof screenshots (private bucket `proofs`, backend-only access)."""

from typing import Protocol

import httpx

BUCKET = "proofs"


class StorageError(Exception):
    pass


class StoragePort(Protocol):
    async def upload(self, path: str, data: bytes, content_type: str) -> None: ...
    async def download(self, path: str) -> bytes: ...
    async def signed_url(self, path: str, ttl_s: int = 3600) -> str: ...


class Storage:
    def __init__(self, supabase_url: str, secret_key: str) -> None:
        if not secret_key:
            raise ValueError("SUPABASE_SECRET_KEY is required for storage")
        self._base = f"{supabase_url.rstrip('/')}/storage/v1"
        self._headers = {"Authorization": f"Bearer {secret_key}", "apikey": secret_key}
        self._http = httpx.AsyncClient(timeout=30)

    async def upload(self, path: str, data: bytes, content_type: str) -> None:
        r = await self._http.post(
            f"{self._base}/object/{BUCKET}/{path}",
            content=data,
            headers={**self._headers, "Content-Type": content_type, "x-upsert": "true"},
        )
        if r.status_code >= 300:
            raise StorageError(f"upload failed: {r.status_code} {r.text[:200]}")

    async def download(self, path: str) -> bytes:
        r = await self._http.get(f"{self._base}/object/{BUCKET}/{path}", headers=self._headers)
        if r.status_code >= 300:
            raise StorageError(f"download failed: {r.status_code}")
        return r.content

    async def signed_url(self, path: str, ttl_s: int = 3600) -> str:
        r = await self._http.post(
            f"{self._base}/object/sign/{BUCKET}/{path}",
            json={"expiresIn": ttl_s},
            headers=self._headers,
        )
        if r.status_code >= 300:
            raise StorageError(f"sign failed: {r.status_code}")
        return f"{self._base}{r.json()['signedURL']}"
