# motopuppu/utils/view_helpers.py
"""ビュー関数で共通利用するヘルパーユーティリティ"""

from urllib.parse import urlparse
from flask import request
from flask_login import current_user
from ..models import Motorcycle


def get_motorcycle_or_404(vehicle_id):
    """
    指定されたIDの車両を取得し、ログインユーザーの所有でなければ404を返す。
    複数のビューで共通利用するヘルパー関数。
    """
    return Motorcycle.query.filter_by(id=vehicle_id, user_id=current_user.id).first_or_404()


def safe_redirect_url(fallback_url):
    """
    request.referrer を安全に検証し、自ドメインのリダイレクト先URLを返す。
    オープンリダイレクト攻撃を防止するため、referrer が外部ドメインの場合や
    不正な形式の場合はフォールバックURLを返す。
    
    Args:
        fallback_url: referrer が無効な場合に返すフォールバックURL
        
    Returns:
        str: 安全なリダイレクト先URL
    """
    referrer = request.referrer
    if not referrer:
        return fallback_url
    
    try:
        parsed = urlparse(referrer)
        # スキームが http/https 以外は拒否
        if parsed.scheme not in ('http', 'https'):
            return fallback_url
        # ホスト名が request.host と一致するか検証
        if parsed.netloc and parsed.netloc != request.host:
            return fallback_url
        return referrer
    except Exception:
        return fallback_url
