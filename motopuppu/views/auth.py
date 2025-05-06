# motopuppu/views/auth.py
import uuid
import requests
import json
import os
from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for, current_app
)
from .. import db
from ..models import User # Userモデルなど必要なモデルをインポート
from functools import wraps

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

@auth_bp.route('/login', methods=['GET'])
def login():
    """MiAuth認証を開始: Misskey認証ページへリダイレクトする"""
    miauth_session_id = str(uuid.uuid4())
    # ★重要: Flaskセッションに保存するキー名を変更 (以前のmiauth_session_idと区別)
    session['miauth_pending_session_id'] = miauth_session_id 
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
    """MiAuthコールバック処理: /check エンドポイントを利用して認証を完了する"""
    current_app.logger.info("Received MiAuth callback GET request")
    received_session_id = request.args.get('session')

    if not received_session_id:
        flash('無効なコールバックリクエストです (セッションIDが見つかりません)。', 'error')
        current_app.logger.error(f"Invalid callback GET parameters received (session ID missing). Args: {request.args}")
        return redirect(url_for('auth.login_page'))

    current_app.logger.info(f"Callback session ID received: {received_session_id}")

    # --- 二重処理防止チェック ---
    # 'miauth_processed_flag_for_{session_id}' のようなキーで処理済みか確認
    processed_flag_key = f'miauth_processed_flag_for_{received_session_id}'
    if session.get(processed_flag_key):
        current_app.logger.info(f"MiAuth session {received_session_id} has already been processed. Redirecting to dashboard.")
        # 既に処理済みであれば、ユーザーIDがセッションにあるはずなので、ダッシュボードへ
        if 'user_id' in session and get_current_user() is not None:
            return redirect(url_for('main.dashboard'))
        else:
            # 何らかの理由でuser_idがない場合はログインページへ（安全策）
            flash('セッションエラーが発生しました。再度ログインしてください。', 'warning')
            current_app.logger.warning(f"MiAuth session {received_session_id} was marked processed, but no user_id in session.")
            return redirect(url_for('auth.login_page'))
    # --- 二重処理防止チェックここまで ---

    # ★重要: Flaskセッションから期待されるIDを取得する際のキー名を変更
    expected_session_id = session.pop('miauth_pending_session_id', None) 
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
        current_app.logger.debug(f"Misskey /check response: {check_data}") # このDEBUGログは重要
        if not check_data.get('ok') or not check_data.get('token') or not check_data.get('user'):
            # Misskeyが {'ok': False} を返した場合、ここに来る
            current_app.logger.error(f"MiAuth check failed or returned invalid data from Misskey. Response: {check_data}")
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
    except ValueError as e: # エラーメッセージを具体的に変更
         flash(f'Misskey MiAuth チェック応答の処理に失敗しました。Misskeyからの応答内容を確認してください。 ({e})', 'error')
         current_app.logger.error(f"Failed to process MiAuth /check response: {e}. Check data: {check_data if 'check_data' in locals() else 'N/A'}")
         return redirect(url_for('auth.login_page'))
    except Exception as e: # その他の予期せぬエラー
         flash(f'MiAuth処理中に予期せぬエラーが発生しました: {e}', 'error')
         current_app.logger.error(f"Unexpected error during MiAuth processing: {e}", exc_info=True)
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
            user.misskey_username = misskey_username # ユーザー名を更新
            try:
                db.session.commit()
                current_app.logger.info(f"Username updated for existing user: {user.misskey_username}")
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error updating username for {misskey_username}: {e}")
        current_app.logger.info(f"Existing user logged in: {user.misskey_username} (App User ID: {user.id})")

    # 既存のセッションをクリアしてから新しいユーザーIDを設定
    # session.clear() # ここでクリアすると processed_flag_key も消えるので注意
    # 代わりに、関連するキーのみを削除するか、user_id設定後にフラグを立てる
    
    # まず古いユーザーIDがあれば削除 (安全のため)
    session.pop('user_id', None) 
    # 他の関連しそうな古いセッション情報もここでクリアできるが、今回はuser_idのみ

    session['user_id'] = user.id
    # --- 処理済みフラグを立てる ---
    session[processed_flag_key] = True 
    # 処理済みフラグの有効期限を設定することも検討可能 (例: session.permanent = True とし、app.permanent_session_lifetimeを設定)
    # しかし、MiAuthセッションID自体が短命なので、Flaskセッションのデフォルト有効期限で十分かもしれない。

    flash('ログインしました。', 'success')
    current_app.logger.info(f"User {user.misskey_username} (App User ID: {user.id}) successfully logged in. Redirecting to dashboard.")
    return redirect(url_for('main.dashboard'))

# (login_page, logout, get_current_user, login_required_custom は変更なし)
# ... (以降のコードは変更なし) ...

@auth_bp.route('/logout')
def logout():
    """ログアウト処理"""
    user_id = session.pop('user_id', None)
    # ログアウト時に処理済みフラグもクリアする (念のため)
    # すべての miauth_processed_flag_for_ を探して消すのは大変なので、
    # user_id が消えれば、次回の processed_flag_key チェックで login_page にリダイレクトされるはず。
    # session.clear() を使うのがシンプルだが、他のセッション情報も消える。
    # 今回は user_id がなければログインページに戻るので、これで十分。
    
    # もし特定のキーパターンで削除したい場合は以下のようなループ（ただし非効率）
    # keys_to_delete = [key for key in session if key.startswith('miauth_processed_flag_for_')]
    # for key in keys_to_delete:
    #     session.pop(key, None)

    if user_id:
        current_app.logger.info(f"User logged out: App User ID={user_id}")
    flash('ログアウトしました。', 'info')
    return redirect(url_for('main.index'))

@auth_bp.route('/login_page')
def login_page():
    """ログインページを表示し、お知らせとバージョン情報を渡す"""
    if 'user_id' in session and get_current_user() is not None:
        return redirect(url_for('main.dashboard'))

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

def get_current_user():
    user_id = session.get('user_id')
    if user_id is None:
        if 'user' in g: del g.user
        return None
    if 'user' in g and g.user is not None and g.user.id == user_id:
        return g.user
    
    user = User.query.get(user_id)
    if user:
        g.user = user
        return g.user
    else:
        current_app.logger.warning(f"User ID {user_id} found in session, but no user in DB. Clearing relevant session keys.")
        session.pop('user_id', None)
        # processed_flag もクリアすべきだが、キーが動的なのでここでは user_id のみクリア
        if 'user' in g: del g.user
        return None

def login_required_custom(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if get_current_user() is None:
            flash('このページにアクセスするにはログインが必要です。', 'warning')
            return redirect(url_for('auth.login_page', next=request.url))
        return f(*args, **kwargs)
    return decorated_function
