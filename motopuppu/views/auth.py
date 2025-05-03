# motopuppu/views/auth.py
import uuid
import requests
from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for, current_app
)
# from flask_login import login_user, logout_user, login_required # Flask-Loginを使う場合
# from werkzeug.security import check_password_hash # ローカル管理者用パスワード比較に使う場合 (今回は直接比較)

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
    # 1. 一意のセッションIDを生成
    miauth_session_id = str(uuid.uuid4())
    # 2. セッションIDをFlaskのセッションに一時的に保存
    session['miauth_session_id'] = miauth_session_id
    # 3. MiAuth URLを構築
    misskey_instance_url = current_app.config.get('MISSKEY_INSTANCE_URL', 'https://misskey.io')
    app_name = "motopuppu"
    permissions = "read:account"
    callback_url = url_for('auth.miauth_callback', _external=True)
    from urllib.parse import urlencode
    params = {'name': app_name, 'permission': permissions, 'callback': callback_url}
    auth_url = f"{misskey_instance_url}/miauth/{miauth_session_id}?{urlencode(params)}"
    # 4. Misskey認証ページへリダイレクト
    current_app.logger.info(f"Redirecting to MiAuth URL: {auth_url}")
    return redirect(auth_url)

@auth_bp.route('/miauth/callback', methods=['POST'])
def miauth_callback():
    """MiAuthコールバック処理: MisskeyからのPOSTリクエストを受け取る"""
    current_app.logger.info("Received MiAuth callback POST request")
    data = request.get_json()
    if not data or 'session' not in data or 'token' not in data:
        flash('無効なコールバックリクエストです。', 'error')
        current_app.logger.error("Invalid callback data received.")
        return redirect(url_for('auth.login_page'))

    received_session_id = data['session']
    token = data['token']
    current_app.logger.info(f"Callback session: {received_session_id}, Token received (masked): {token[:5]}...")

    expected_session_id = session.pop('miauth_session_id', None)
    if not expected_session_id or expected_session_id != received_session_id:
        flash('認証セッションが無効か、タイムアウトしました。もう一度お試しください。', 'error')
        current_app.logger.warning(f"Session ID mismatch or missing. Expected: {expected_session_id}, Received: {received_session_id}")
        return redirect(url_for('auth.login_page'))

    misskey_instance_url = current_app.config.get('MISSKEY_INSTANCE_URL', 'https://misskey.io')
    try:
        headers = {'Authorization': f'Bearer {token}'}
        user_info_response = requests.post(f"{misskey_instance_url}/api/i", headers=headers, json={}, timeout=10)
        user_info_response.raise_for_status()
        user_info = user_info_response.json()
        current_app.logger.info(f"Misskey user info received: ID={user_info.get('id')}, Username={user_info.get('username')}")

        misskey_user_id = user_info.get('id')
        misskey_username = user_info.get('username')
        if not misskey_user_id: raise ValueError("Misskey User ID not found in API response.")

    except requests.exceptions.RequestException as e:
        flash(f'Misskey APIへのアクセスに失敗しました: {e}', 'error')
        current_app.logger.error(f"Misskey API request failed: {e}")
        return redirect(url_for('auth.login_page'))
    except (ValueError, KeyError, Exception) as e:
         flash(f'Misskeyユーザー情報の取得または処理に失敗しました: {e}', 'error')
         current_app.logger.error(f"Failed to process Misskey user info: {e}")
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
            try:
                db.session.commit()
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
    """ログインページを表示する"""
    # 既にログイン済みの場合はダッシュボードへリダイレクト
    if 'user_id' in session and get_current_user() is not None:
        return redirect(url_for('main.dashboard'))
    # login.html テンプレートを表示
    return render_template('login.html')


# --- 【開発用】ローカル管理者ログイン ---
# ▼▼▼ このセクション全体を削除しました ▼▼▼
# @auth_bp.route('/local_login', methods=['POST'])
# def local_login():
#     ... (関数の中身全体) ...
# ▲▲▲ 削除ここまで ▲▲▲


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
        current_app.logger.debug(f"Current user fetched from DB: {g.user}")
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
