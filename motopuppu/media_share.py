# motopuppu/media_share.py
"""Misskey Media Share API client.

See https://media-share.misskey.workers.dev/api/ for the API reference.
"""
from __future__ import annotations

import re
from typing import Any

import requests
from flask import current_app


ALBUM_URL_RE = re.compile(
    r'^https://media-share\.misskey\.workers\.dev/album/'
    r'([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})'
)


def extract_album_id(album_url: str | None) -> str | None:
    """media-share アルバムURLからUUIDを抜き出す。形式に合わなければ None。"""
    if not album_url:
        return None
    m = ALBUM_URL_RE.match(album_url.strip())
    return m.group(1) if m else None


def build_album_url(album_id: str) -> str:
    base = current_app.config.get('MEDIA_SHARE_BASE_URL', 'https://media-share.misskey.workers.dev').rstrip('/')
    return f"{base}/album/{album_id}"


class MediaShareError(Exception):
    """Media Share API 呼び出し時のエラー基底クラス。"""

    def __init__(self, message: str, *, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class MediaShareAuthError(MediaShareError):
    """認証エラー (401)。セッショントークン期限切れ or 未認証。"""


class MediaShareClient:
    """Misskey Media Share API クライアント (RPC風 POST全般)。"""

    DEFAULT_TIMEOUT = 10

    def __init__(self, token: str | None = None, base_url: str | None = None):
        self.token = token
        self.base_url = (base_url or current_app.config.get('MEDIA_SHARE_BASE_URL', 'https://media-share.misskey.workers.dev')).rstrip('/')

    def _post(self, path: str, body: dict | None = None, *, require_auth: bool = True) -> dict:
        url = f"{self.base_url}/api{path}"
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        elif require_auth:
            raise MediaShareAuthError('Media Share token is not set on this client.')

        try:
            resp = requests.post(url, json=body or {}, headers=headers, timeout=self.DEFAULT_TIMEOUT)
        except requests.RequestException as e:
            raise MediaShareError(f'Network error calling Media Share: {e}') from e

        # JSONを試みる (失敗してもエラーメッセージに含めるため握り潰す)
        try:
            data = resp.json()
        except ValueError:
            data = None

        if resp.status_code == 401:
            raise MediaShareAuthError('Media Share token expired or invalid.', status=401, payload=data)
        if resp.status_code >= 400:
            raise MediaShareError(
                f'Media Share API error ({resp.status_code}) at {path}',
                status=resp.status_code,
                payload=data,
            )
        return data or {}

    # --- 認証 ---

    def start_miauth(self, redirect_to: str) -> dict:
        """MiAuth開始。レスポンスに sessionId と authUrl (Misskey.io側) を含む想定。"""
        return self._post('/auth/startMiAuth', {'redirectTo': redirect_to}, require_auth=False)

    def finish_miauth(self, session_id: str) -> dict:
        """MiAuth完了。レスポンスに token を含む想定。"""
        return self._post('/auth/finishMiAuth', {'sessionId': session_id}, require_auth=False)

    def get_me(self) -> dict:
        """トークン疎通確認。401で MediaShareAuthError。"""
        return self._post('/auth/me', {})

    # --- アルバム ---

    def create_album(self, title: str, visibility: str = 'restricted', description: str | None = None) -> dict:
        body: dict[str, Any] = {'title': title, 'visibility': visibility}
        if description:
            body['description'] = description
        return self._post('/albums/create', body)

    def get_album(self, album_id: str) -> dict:
        """アルバム詳細 (Album object) を取得。"""
        return self._post('/albums/get', {'albumId': album_id})


def fetch_album_metadata(token: str, album_id: str) -> dict:
    """Albumメタデータ (title, mediaCount, coverMediaId) を取得して dict で返す。

    返却dict: {'title', 'media_count', 'cover_media_id', 'cover_url'}
    cover_url は coverMediaId が無い場合 None。
    """
    client = MediaShareClient(token=token)
    album = client.get_album(album_id)

    return {
        'title': album.get('title'),
        'media_count': album.get('mediaCount'),
        'cover_media_id': album.get('coverMediaId'),
        # Phase 2a ではカバー画像URL解決は未対応 (Phase 2b で MediaAsset.previewUrl を取得して埋める)
        'cover_url': None,
    }
