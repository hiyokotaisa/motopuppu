# motopuppu/views/auth.py
import uuid
import requests
import json
import os
from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for, current_app
)
from flask_login import login_user, logout_user, current_user
from .. import db
from ..models import User
from functools import wraps
from ..forms import DeleteAccountForm
from ..services import CryptoService
from .. import limiter

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

@auth_bp.route('/login', methods=['GET'])
@limiter.limit("10 per minute")
def login():
    # ▼▼▼【ここから修正】リダイレクト先をセッションに保存 ▼▼▼
    remember_me = request.args.get('remember') == '1'
    session['remember_me'] = remember_me

    # ログイン後のリダイレクト先をセッションに保存
    next_url = request.args.get('next')
    if next_url:
        session['next_url'] = next_url
        current_app.logger.info(f"Stored next_url in session: {next_url}")
    # ▲▲▲【修正はここまで】▲▲▲

    miauth_session_id = str(uuid.uuid4())
    session['miauth_session_id'] = miauth_session_id
    current_app.logger.debug(f"Session before redirect: {dict(session)}")
    misskey_instance_url = current_app.config.get('MISSKEY_INSTANCE_URL', 'https://misskey.io')
    app_name = "motopuppu"
    permissions = "read:account"
    callback_url = url_for('auth.miauth_callback', _external=True)

    from urllib.parse import urlencode
    params = {'name': app_name, 'permission': permissions, 'callback': callback_url}
    auth_url = f"{misskey_instance_url}/miauth/{miauth_session_id}?{urlencode(params)}"
    current_app.logger.info(f"Redirecting to MiAuth URL: {auth_url}")
    return redirect(auth_url)

@auth_bp.route('/miauth/callback', methods=['GET'])
def miauth_callback():
    if current_user.is_authenticated:
        current_app.logger.info(
            "User is already logged in. This might be a rapid double callback. Redirecting to dashboard."
        )
        return redirect(url_for('main.dashboard'))

    current_app.logger.info("Received MiAuth callback GET request (user not yet logged in or new session)")
    received_session_id = request.args.get('session')

    if not received_session_id:
        flash('無効なコールバックリクエストです (セッションIDが見つかりません)。', 'error')
        current_app.logger.error(f"Invalid callback GET parameters received (session ID missing). Args: {request.args}")
        return redirect(url_for('auth.login_page'))

    current_app.logger.info(f"Callback session ID received: {received_session_id}")
    current_app.logger.debug(f"Session state at callback entry: {dict(session)}")

    expected_session_id = session.get('miauth_session_id')

    if not expected_session_id or expected_session_id != received_session_id:
        if current_user.is_authenticated:
            current_app.logger.warning(
                f"MiAuth session ID mismatch or missing in session, but user is now logged in. "
                f"Assuming this is a processed double callback. Expected in session: {expected_session_id}, Received: {received_session_id}. "
            )
            return redirect(url_for('main.dashboard'))

        flash('認証セッションが無効か、タイムアウトしました。もう一度お試しください。', 'error')
        current_app.logger.warning(
            f"MiAuth session ID mismatch or missing. Expected in session: {expected_session_id}, Received: {received_session_id}. "
        )
        return redirect(url_for('auth.login_page'))

    session.pop('miauth_session_id', None)
    current_app.logger.info(f"Popped 'miauth_session_id' from session after validation for received_session_id: {received_session_id}")

    misskey_instance_url = current_app.config.get('MISSKEY_INSTANCE_URL', 'https://misskey.io')
    check_url = f"{misskey_instance_url}/api/miauth/{received_session_id}/check"
    current_app.logger.info(f"Checking session with Misskey API: {check_url}")

    check_data = None
    try:
        check_response = requests.post(check_url, timeout=10)
        check_response.raise_for_status()
        check_data = check_response.json()
        current_app.logger.debug(f"Misskey /check response: {check_data}")

        if not check_data.get('ok') or not check_data.get('token') or not check_data.get('user'):
            current_app.logger.error(f"MiAuth /check response was not 'ok' or missing 'token'/'user'. Response: {check_data}")
            
            if isinstance(check_data, dict) and check_data.get('ok') is False:
                current_app.logger.warning(
                    f"MiAuth /check returned 'ok: False' for session {received_session_id}. "
                    "This might be due to a rapid double callback where the first succeeded. "
                    "Redirecting to login page with a suggestion to check if already logged in."
                )
                flash('認証結果の確認中に問題が発生しました。既にログインが完了しているか、再度お試しください。', 'warning')
                return redirect(url_for('auth.login_page'))
            
            raise ValueError(f"Invalid response from MiAuth check endpoint. Response: {check_data}")

        token = check_data['token']
        user_info = check_data['user']
        misskey_user_id = user_info.get('id')
        misskey_username = user_info.get('username')
        avatar_url = user_info.get('avatarUrl')
        current_app.logger.info(f"MiAuth check successful. Token received (masked): {token[:5]}..., User ID: {misskey_user_id}, Username: {misskey_username}, Avatar URL: {avatar_url}")

        if not misskey_user_id:
            raise ValueError("Misskey User ID not found in check response user object.")

    except requests.exceptions.RequestException as e:
        flash(f'Misskey MiAuth チェック APIへのアクセスに失敗しました: {e}', 'error')
        current_app.logger.error(f"Misskey MiAuth /check request failed: {e}")
        return redirect(url_for('auth.login_page'))
    except (ValueError, KeyError, Exception) as e:
        current_app.logger.error(f"Failed to process MiAuth /check response or other error: {e}. Check data if available: {check_data if check_data is not None else 'Not available during this exception'}")
        flash(f'Misskey MiAuth 認証処理中に予期せぬエラーが発生しました。 ({e})', 'error')
        return redirect(url_for('auth.login_page'))

    user = db.session.scalar(db.select(User).filter_by(misskey_user_id=misskey_user_id))
    
    try:
        crypto_service = CryptoService()
        encrypted_token = crypto_service.encrypt(token)
    except Exception as e:
        current_app.logger.error(f"Failed to initialize CryptoService or encrypt token for user {misskey_username}: {e}")
        flash('セキュリティトークンの処理中にエラーが発生しました。設定を確認してください。', 'danger')
        return redirect(url_for('main.index'))

    if not user:
        user = User(
            misskey_user_id=misskey_user_id,
            misskey_username=misskey_username,
            avatar_url=avatar_url,
            encrypted_misskey_api_token=encrypted_token,
            is_admin=False
        )
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
        needs_commit = False
        if user.misskey_username != misskey_username:
            user.misskey_username = misskey_username
            needs_commit = True
        if user.avatar_url != avatar_url:
            user.avatar_url = avatar_url
            needs_commit = True
        if user.encrypted_misskey_api_token != encrypted_token:
            user.encrypted_misskey_api_token = encrypted_token
            needs_commit = True
        
        if needs_commit:
            try:
                db.session.commit()
                current_app.logger.info(f"User info updated for user ID {user.id}")
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error updating user info for {misskey_username}: {e}")
        current_app.logger.info(f"Existing user logged in: {user.misskey_username} (App User ID: {user.id})")

    should_remember = session.pop('remember_me', False)
    login_user(user, remember=should_remember)
    current_app.logger.info(f"User {user.misskey_username} (ID: {user.id}) logged in via Flask-Login (Remember Me: {should_remember}).")
    flash('ログインしました。', 'success')
    
    # ▼▼▼【ここから修正】セッションからリダイレクト先を取得してリダイレクト ▼▼▼
    next_url = session.pop('next_url', None)
    if next_url:
        current_app.logger.info(f"Redirecting to stored next_url: {next_url}")
        return redirect(next_url)
    else:
        current_app.logger.info("No stored next_url, redirecting to dashboard.")
        return redirect(url_for('main.dashboard'))
    # ▲▲▲【修正はここまで】▲▲▲

@auth_bp.route('/logout')
def logout():
    if current_user.is_authenticated:
        current_app.logger.info(f"User logged out: App User ID={current_user.id}")
    logout_user()
    flash('ログアウトしました。', 'info')
    return redirect(url_for('main.index'))

@auth_bp.route('/login_page')
def login_page():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    announcements_for_modal = []
    important_notice_content = None
    try:
        announcement_file = os.path.join(current_app.root_path, '..', 'announcements.json')
        if os.path.exists(announcement_file):
            with open(announcement_file, 'r', encoding='utf-8') as f:
                all_announcements_data = json.load(f)
                for item in all_announcements_data:
                    if item.get('active', False):
                        if item.get('id') == 1:
                            important_notice_content = item
                        else:
                            announcements_for_modal.append(item)
        else:
                current_app.logger.warning(f"announcements.json not found at {announcement_file}")
    except Exception as e:
        current_app.logger.error(f"An unexpected error occurred loading announcements: {e}", exc_info=True)

    return render_template('index.html', 
                           announcements=announcements_for_modal,
                           important_notice=important_notice_content)

@auth_bp.route('/delete_account_complete')
def delete_account_complete():
    return render_template('auth/delete_account_complete.html', title="退会完了")