# motopuppu/views/dev_auth.py
import os
from flask import (
    Blueprint, flash, redirect, session, url_for, current_app, abort
)
from ..models import User # Userモデルをインポート
from .. import db # dbオブジェクトはUserクエリに必要

# 'dev_auth' という名前でBlueprintオブジェクトを作成
# このBlueprintは開発環境でのみ登録される想定
dev_auth_bp = Blueprint('dev_auth', __name__, url_prefix='/dev')

@dev_auth_bp.route('/local_login', methods=['GET'])
def local_login():
    """
    開発環境用のローカルログイン処理。
    .env の LOCAL_DEV_USER_ID で指定されたユーザーでログインする。
    """
    # 開発環境以外からのアクセスは拒否
    if current_app.config.get('ENV') != 'development':
        current_app.logger.warning(f"Attempted access to /dev/local_login from non-development environment.")
        abort(404) # Not Found

    local_dev_user_id = current_app.config.get('LOCAL_DEV_USER_ID')

    if not local_dev_user_id:
        flash('ローカル開発用ログインが設定されていません (.envのLOCAL_DEV_USER_IDを確認してください)。', 'error')
        current_app.logger.error("LOCAL_DEV_USER_ID is not set in the environment variables for local login.")
        return redirect(url_for('auth.login_page'))

    try:
        user_id_int = int(local_dev_user_id)
        # SQLAlchemy 1.x スタイルの User.query.get(user_id_int) から
        # SQLAlchemy 2.0 スタイルの db.session.get(User, user_id_int) に変更
        user = db.session.get(User, user_id_int)
    except ValueError:
        flash(f'無効なユーザーID形式です: {local_dev_user_id}', 'error')
        current_app.logger.error(f"Invalid LOCAL_DEV_USER_ID format: {local_dev_user_id}")
        user = None
    except Exception as e: # db.session.get が他の例外を投げる可能性は低いが、念のため残す
        flash(f'ユーザー検索中にエラーが発生しました: {e}', 'error')
        current_app.logger.error(f"Error querying user by ID {local_dev_user_id} with db.session.get: {e}", exc_info=True)
        user = None

    if user:
        # 既存のセッションをクリアしてからログイン情報を設定
        session.clear()
        session['user_id'] = user.id
        flash(f'開発用アカウント ({user.misskey_username or f"User ID: {user.id}"}) でログインしました。', 'success')
        current_app.logger.info(f"Local development login successful for user ID: {user.id} (Username: {user.misskey_username})")
        return redirect(url_for('main.dashboard')) # ログイン後のリダイレクト先
    else:
        flash(f'指定された開発用ユーザーID ({local_dev_user_id}) がデータベースに見つかりません。', 'warning')
        current_app.logger.warning(f"Local development user ID {local_dev_user_id} not found in the database.")
        return redirect(url_for('auth.login_page'))