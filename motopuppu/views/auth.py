# motopuppu/views/auth.py
import uuid
import requests
import json
import os
from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for, current_app
)
from .. import db
from ..models import User
from functools import wraps
from ..forms import DeleteAccountForm # DeleteAccountForm をインポート

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

def get_current_user():
    user_id = session.get('user_id')
    if user_id is None:
        if 'user' in g: del g.user
        return None
    if 'user' in g and hasattr(g.user, 'id') and g.user.id == user_id:
        return g.user
    
    user = db.session.get(User, user_id) # SQLAlchemy 2.0+ 互換の可能性を考慮
    if user:
        g.user = user
        return g.user
    else:
        current_app.logger.warning(f"User ID {user_id} found in session, but no user in DB. Clearing session.")
        session.clear()
        if 'user' in g: del g.user
        return None

@auth_bp.route('/login', methods=['GET'])
def login():
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
    if 'user_id' in session and get_current_user() is not None:
        current_app.logger.info(
            "User is already logged in (session['user_id'] exists). "
            "This might be a rapid double callback. Redirecting to dashboard."
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
        if 'user_id' in session and get_current_user() is not None:
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
        current_app.logger.info(f"MiAuth check successful. Token received (masked): {token[:5]}..., User ID: {misskey_user_id}, Username: {misskey_username}")

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

    user = db.session.scalar(db.select(User).filter_by(misskey_user_id=misskey_user_id)) # SQLAlchemy 2.0+
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
                current_app.logger.info(f"Username updated for user ID {user.id} to {misskey_username}")
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error updating username for {misskey_username}: {e}")
        current_app.logger.info(f"Existing user logged in: {user.misskey_username} (App User ID: {user.id})")

    session.clear()
    session['user_id'] = user.id
    # g.user の設定: MiAuthコールバック成功時にg.userを明示的に設定すると、
    # この直後のリダイレクト先での最初のリクエスト処理で get_current_user() を呼び出した際に、
    # DBアクセスなしでg.userからユーザー情報を取得できる可能性があります（リクエストサイクルによる）。
    # ただし、通常はリダイレクト後のリクエストではgコンテキストはリセットされるため、
    # get_current_user()内で再度DBから取得されることが多いです。
    # ここでの g.user = user の設定は、必須というよりは念のため、あるいは特定のケースでの最適化です。
    g.user = user 
    current_app.logger.info(f"User {user.misskey_username} (App User ID: {user.id}) successfully logged in. Session 'user_id' set. Redirecting to dashboard.")
    flash('ログインしました。', 'success')
    return redirect(url_for('main.dashboard'))

@auth_bp.route('/logout')
def logout():
    user_id_logged_out = session.pop('user_id', None) # ログ用に取得
    # g.user が存在すればクリア (もし使われていれば)
    if 'user' in g:
        del g.user
    session.clear() # セッション全体をクリア
    if user_id_logged_out:
        current_app.logger.info(f"User logged out: App User ID={user_id_logged_out}")
    flash('ログアウトしました。', 'info')
    return redirect(url_for('main.index')) # ログアウト後はトップページへ

@auth_bp.route('/login_page')
def login_page():
    if 'user_id' in session and get_current_user() is not None:
        return redirect(url_for('main.dashboard'))

    announcements_for_modal = []
    important_notice_content = None # 固定表示用お知らせ
    try:
        # announcements.json のパスを修正: current_app.root_path は motopuppu パッケージのパスを指す想定
        # プロジェクトルートに announcements.json がある場合、'..' が必要
        announcement_file = os.path.join(current_app.root_path, '..', 'announcements.json')
        if os.path.exists(announcement_file):
            with open(announcement_file, 'r', encoding='utf-8') as f:
                all_announcements_data = json.load(f)
                for item in all_announcements_data:
                    if item.get('active', False):
                        if item.get('id') == 1: # id:1 のお知らせを特定
                            important_notice_content = item # 固定表示用に保持
                        else:
                            announcements_for_modal.append(item) # モーダル用にリスト追加
        else:
             current_app.logger.warning(f"announcements.json not found at {announcement_file}")
    except Exception as e:
        current_app.logger.error(f"An unexpected error occurred loading announcements: {e}", exc_info=True)
        # エラーが発生した場合でも、テンプレート変数が未定義にならないように空の値を設定することも検討
        # announcements_for_modal = []
        # important_notice_content = None
        # (ただし、上記の初期化でカバーされている)

    return render_template('index.html', 
                           announcements=announcements_for_modal, # モーダル用のお知らせリスト
                           important_notice=important_notice_content) # 固定表示用のお知らせ

def login_required_custom(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if get_current_user() is None: # g.user がセットされていない、またはユーザーが存在しない場合
            flash('このページにアクセスするにはログインが必要です。', 'warning')
            return redirect(url_for('auth.login_page', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@auth_bp.route('/delete_account', methods=['GET', 'POST'])
@login_required_custom # ログイン必須
def delete_account():
    form = DeleteAccountForm()
    user_to_delete = g.user # @login_required_custom により g.user には現在のユーザーがセットされているはず

    if form.validate_on_submit():
        try:
            if user_to_delete:
                user_id_deleted = user_to_delete.id # ログ用にIDを保持
                user_name_deleted = user_to_delete.misskey_username # ログ用に名前を保持
                
                db.session.delete(user_to_delete)
                db.session.commit()
                
                if 'user' in g:
                    del g.user
                session.pop('user_id', None)
                session.clear()
                
                current_app.logger.info(f"User account deleted successfully: App User ID={user_id_deleted}, Username={user_name_deleted}")
                # ▼▼▼ 退会完了ページへリダイレクト ▼▼▼
                return redirect(url_for('auth.delete_account_complete'))
            else:
                flash('ユーザーが見つかりませんでした。操作をやり直してください。', 'error')
                current_app.logger.error(f"Attempt to delete account, but g.user was not available or invalid.")
                return redirect(url_for('main.dashboard'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error deleting user account (ID: {user_to_delete.id if user_to_delete else 'Unknown'}): {e}", exc_info=True)
            flash('アカウントの削除中にエラーが発生しました。しばらくしてからもう一度お試しいただくか、管理者にご連絡ください。', 'danger')
    
    elif request.method == 'POST' and not form.validate():
        flash('入力内容を確認してください。', 'warning')

    return render_template('auth/delete_account.html', title='アカウント削除', form=form, user_to_delete_name=user_to_delete.misskey_username if user_to_delete else "ユーザー")

# ▼▼▼ 退会完了ページ表示用のルートを追加 ▼▼▼
@auth_bp.route('/delete_account_complete')
def delete_account_complete():
    # このページはログインしていなくても表示される（セッションはクリアされているため）
    return render_template('auth/delete_account_complete.html', title="退会完了")
# ▲▲▲ 退会完了ページ表示用のルートを追加 ▲▲▲
