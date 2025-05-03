# motopuppu/views/auth.py
import uuid
import requests
import json # json と os をインポート
import os
from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for, current_app
)
# from flask_login import login_user, logout_user, login_required # Flask-Loginを使う場合
# from werkzeug.security import check_password_hash # ローカル管理者用パスワード比較に使う場合

# データベースモデルとdbオブジェクトをインポート
from .. import db
from ..models import User, Motorcycle # Userモデルなど必要なモデルをインポート
# ヘルパー関数&デコレータ用にインポート
from functools import wraps

# 'auth' という名前でBlueprintオブジェクトを作成
auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

# --- MiAuth 認証フロー ---

@auth_bp.route('/login', methods=['GET'])
def login():
    """MiAuth認証を開始: Misskey認証ページへリダイレクトする"""
    miauth_session_id = str(uuid.uuid4())
    session['miauth_session_id'] = miauth_session_id
    misskey_instance_url = current_app.config.get('MISSKEY_INSTANCE_URL', 'https://misskey.io')
    app_name = "motopuppu"
    permissions = "read:account"
    callback_url = url_for('auth.miauth_callback', _external=True)
    from urllib.parse import urlencode
    params = {'name': app_name, 'permission': permissions, 'callback': callback_url}
    auth_url = f"{misskey_instance_url}/miauth/{miauth_session_id}?{urlencode(params)}"
    current_app.logger.info(f"Redirecting to MiAuth URL: {auth_url}")
    return redirect(auth_url)

@auth_bp.route('/miauth/callback', methods=['GET']) # GET で受け付ける
def miauth_callback():
    """MiAuthコールバック処理: /check エンドポイントを利用して認証を完了する"""
    current_app.logger.info("Received MiAuth callback GET request")
    received_session_id = request.args.get('session')
    if not received_session_id:
        flash('無効なコールバックリクエストです (セッションIDが見つかりません)。', 'error')
        current_app.logger.error(f"Invalid callback GET parameters received (session ID missing). Args: {request.args}")
        return redirect(url_for('auth.login_page'))

    current_app.logger.info(f"Callback session ID received: {received_session_id}")
    expected_session_id = session.pop('miauth_session_id', None)
    if not expected_session_id or expected_session_id != received_session_id:
        flash('認証セッションが無効か、タイムアウトしました。もう一度お試しください。', 'error')
        current_app.logger.warning(f"Session ID mismatch or missing. Expected: {expected_session_id}, Received: {received_session_id}")
        return redirect(url_for('auth.login_page'))

    misskey_instance_url = current_app.config.get('MISSKEY_INSTANCE_URL', 'https://misskey.io')
    check_url = f"{misskey_instance_url}/api/miauth/{received_session_id}/check"
    current_app.logger.info(f"Checking session with Misskey API: {check_url}")
    try:
        check_response = requests.post(check_url, timeout=10)
        check_response.raise_for_status()
        check_data = check_response.json()
        current_app.logger.debug(f"Misskey /check response: {check_data}")
        if not check_data.get('ok') or not check_data.get('token') or not check_data.get('user'):
            raise ValueError("Invalid response from MiAuth check endpoint.")
        token = check_data['token']
        user_info = check_data['user']
        misskey_user_id = user_info.get('id')
        misskey_username = user_info.get('username')
        current_app.logger.info(f"MiAuth check successful. Token received (masked): {token[:5]}..., User ID: {misskey_user_id}, Username: {misskey_username}")
        if not misskey_user_id:
            raise ValueError("Misskey User ID not found in check response user object.")
    except requests.exceptions.RequestException as e:
        flash(f'Misskey MiAuth チェック APIへのアクセスに失敗しました: {e}', 'error')
        current_app.logger.error(f"Misskey MiAuth /check request failed: {e}")
        return redirect(url_for('auth.login_page'))
    except (ValueError, KeyError, Exception) as e:
         flash(f'Misskey MiAuth チェック応答の処理に失敗しました: {e}', 'error')
         current_app.logger.error(f"Failed to process MiAuth /check response: {e}")
         return redirect(url_for('auth.login_page'))

    user = User.query.filter_by(misskey_user_id=misskey_user_id).first()
    if not user:
        user = User(misskey_user_id=misskey_user_id, misskey_username=misskey_username, is_admin=False)
        db.session.add(user)
        try:
            db.session.commit()
            flash(f'ようこそ、{misskey_username}さん！アカウントが作成されました。', 'success')
            current_app.logger.info(f"New user created: {misskey_username} (App User ID: {user.id})")
        except Exception as e:
            db.session.rollback()
            flash(f'ユーザーアカウントの作成中にエラーが発生しました。', 'error')
            current_app.logger.error(f"Database error creating user: {e}")
            return redirect(url_for('auth.login_page'))
    else:
        if user.misskey_username != misskey_username:
            user.misskey_username = misskey_username
            try: db.session.commit()
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error updating username for {misskey_username}: {e}")
        current_app.logger.info(f"Existing user logged in: {user.misskey_username} (App User ID: {user.id})")

    session.clear()
    session['user_id'] = user.id
    flash('ログインしました。', 'success')
    return redirect(url_for('main.dashboard'))


# --- ログアウト ---

@auth_bp.route('/logout')
def logout():
    """ログアウト処理"""
    user_id = session.pop('user_id', None)
    session.clear()
    if user_id:
        current_app.logger.info(f"User logged out: App User ID={user_id}")
    flash('ログアウトしました。', 'info')
    return redirect(url_for('main.index'))

# --- ログインページ表示 ---

@auth_bp.route('/login_page')
def login_page():
    """ログインページを表示し、お知らせとバージョン情報を渡す"""
    if 'user_id' in session and get_current_user() is not None:
        return redirect(url_for('main.dashboard'))

    # お知らせとバージョン情報の読み込み (デバッグプリントは削除済み)
    announcements = []
    build_version = os.environ.get('APP_VERSION', 'N/A')
    try:
        announcement_file = os.path.join(current_app.root_path, '..', 'announcements.json')
        if os.path.exists(announcement_file):
            with open(announcement_file, 'r', encoding='utf-8') as f:
                all_announcements = json.load(f)
                announcements = [a for a in all_announcements if a.get('active', False)]
        else:
             current_app.logger.warning("announcements.json not found.")
    except FileNotFoundError:
         current_app.logger.error("announcements.json not found (FileNotFoundError).")
    except PermissionError:
         current_app.logger.error("Permission denied when reading announcements.json.")
    except json.JSONDecodeError as e:
        current_app.logger.error(f"Failed to parse announcements.json: {e}")
    except Exception as e:
        current_app.logger.error(f"An unexpected error occurred loading announcements: {e}", exc_info=True)

    return render_template('login.html',
                           announcements=announcements,
                           build_version=build_version)

# --- 【開発用】ローカル管理者ログインは削除済み ---


# --- ヘルパー関数 & デコレータ ---

def get_current_user():
    """
    セッションIDから現在のユーザーオブジェクトを取得する。
    DBにユーザーが存在しない場合はNoneを返し、セッションをクリアする。
    """
    user_id = session.get('user_id')
    if user_id is None:
        if 'user' in g: del g.user
        return None
    if 'user' in g:
        return g.user
    user = User.query.get(user_id)
    if user:
        g.user = user
        # current_app.logger.debug(f"Current user fetched from DB: {g.user}") # デバッグ時以外はコメントアウト推奨
        return g.user
    else:
        current_app.logger.warning(f"User ID {user_id} found in session, but no user in DB. Clearing session.")
        session.clear()
        if 'user' in g: del g.user
        return None

def login_required_custom(f):
    """自作のログイン必須デコレータ"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        g.user = get_current_user()
        if g.user is None:
            flash('このページにアクセスするにはログインが必要です。', 'warning')
            return redirect(url_for('auth.login_page', next=request.url))
        return f(*args, **kwargs)
    return decorated_function