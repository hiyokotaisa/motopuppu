# motopuppu/views/auth.py
import uuid
import requests
import json
import os
from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for, current_app
)
# データベースモデルとdbオブジェクトをインポート
from .. import db
from ..models import User, Motorcycle # Userモデルなど必要なモデルをインポート (Motorcycleは直接使われていませんが、元のファイルにあったため残します)
# ヘルパー関数&デコレータ用にインポート
from functools import wraps

# 'auth' という名前でBlueprintオブジェクトを作成
auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

# --- ヘルパー関数 & デコレータ (get_current_user は miauth_callback で使うので先に定義) ---

def get_current_user():
    """
    セッションIDから現在のユーザーオブジェクトを取得する。
    DBにユーザーが存在しない場合はNoneを返し、セッションをクリアする。
    """
    user_id = session.get('user_id')
    if user_id is None:
        if 'user' in g: del g.user
        return None
    
    # gオブジェクトにユーザーがキャッシュされていればそれを使用し、IDも比較して整合性を確認
    if 'user' in g and g.user is not None and g.user.id == user_id:
        return g.user
    
    user = User.query.get(user_id)
    if user:
        g.user = user # 取得したユーザーをgオブジェクトにキャッシュ
        return g.user
    else:
        current_app.logger.warning(f"User ID {user_id} found in session, but no user in DB. Clearing session.")
        session.clear() # 無効なセッションなのでクリア
        if 'user' in g: del g.user
        return None

def login_required_custom(f):
    """自作のログイン必須デコレータ"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if get_current_user() is None:
            flash('このページにアクセスするにはログインが必要です。', 'warning')
            return redirect(url_for('auth.login_page', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

# --- MiAuth 認証フロー ---

@auth_bp.route('/login', methods=['GET'])
def login():
    """MiAuth認証を開始: Misskey認証ページへリダイレクトする"""
    miauth_session_id = str(uuid.uuid4())
    session['miauth_session_id'] = miauth_session_id # 認証開始時にFlaskセッションに保存
    misskey_instance_url = current_app.config.get('MISSKEY_INSTANCE_URL', 'https://misskey.io')
    app_name = current_app.config.get('MIAUTH_APP_NAME', 'motopuppu') # 設定からアプリ名を取得できるように変更
    permissions = current_app.config.get('MIAUTH_PERMISSIONS', 'read:account') # 設定からパーミッションを取得
    
    # コールバックURLは _external=True で完全なURLを生成
    callback_url = url_for('auth.miauth_callback', _external=True)
    
    from urllib.parse import urlencode
    params = {'name': app_name, 'permission': permissions, 'callback': callback_url}
    auth_url = f"{misskey_instance_url}/miauth/{miauth_session_id}?{urlencode(params)}"
    
    current_app.logger.info(f"Redirecting to MiAuth URL: {auth_url}")
    current_app.logger.debug(f"Session before redirect: {dict(session)}")
    return redirect(auth_url)

@auth_bp.route('/miauth/callback', methods=['GET'])
def miauth_callback():
    """MiAuthコールバック処理: /check エンドポイントを利用して認証を完了する"""
    # ★追加: 既にユーザーがログインしているか確認 (get_current_user を使用)
    if 'user_id' in session and get_current_user() is not None:
        current_app.logger.info(
            "User is already logged in (session['user_id'] exists via get_current_user). "
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

    # popせずにまずgetで確認
    expected_session_id_in_flask_session = session.get('miauth_session_id')

    if not expected_session_id_in_flask_session or expected_session_id_in_flask_session != received_session_id:
        # expected_session_id が None の場合、または一致しない場合
        # この時点でユーザーがログインしていれば、それは直前のリクエストで成功したとみなせる
        if 'user_id' in session and get_current_user() is not None:
            current_app.logger.warning(
                f"MiAuth session ID mismatch or missing in session, but user is now logged in. "
                f"Assuming this is a processed double callback. Expected in Flask session: {expected_session_id_in_flask_session}, Received: {received_session_id}. "
                f"SESSION DATA: {dict(session)}"
            )
            return redirect(url_for('main.dashboard'))

        flash('認証セッションが無効か、タイムアウトしました。もう一度お試しください。', 'error')
        current_app.logger.warning(
            f"MiAuth session ID mismatch or missing in Flask session. Expected: {expected_session_id_in_flask_session}, Received: {received_session_id}. "
            f"SESSION DATA: {dict(session)}"
        )
        return redirect(url_for('auth.login_page'))

    # session IDが期待通りであれば、ここで session から pop する
    # この pop は、このリクエストのコンテキスト内でのみ有効で、他の同時リクエストには影響しない可能性がある
    session.pop('miauth_session_id', None)
    current_app.logger.info(f"Popped 'miauth_session_id' from session after validation for received_session_id: {received_session_id}")

    misskey_instance_url = current_app.config.get('MISSKEY_INSTANCE_URL', 'https://misskey.io')
    check_url = f"{misskey_instance_url}/api/miauth/{received_session_id}/check"
    current_app.logger.info(f"Checking session with Misskey API: {check_url}")

    check_data = {} # check_dataを初期化して、エラーログで参照できるようにする
    try:
        check_response = requests.post(check_url, timeout=10)
        check_response.raise_for_status()
        check_data = check_response.json()
        current_app.logger.debug(f"Misskey /check response: {check_data}")

        if not check_data.get('ok') or not check_data.get('token') or not check_data.get('user'):
            error_detail = f"Misskey /check response was not 'ok' or missing 'token'/'user'. Response: {check_data}"
            current_app.logger.error(f"MiAuth check failed: {error_detail}")
            # flashメッセージはエラー詳細を本番では隠す
            flash_message_detail = error_detail if current_app.debug else "Details in server log."
            flash(f'Misskey MiAuth チェック応答の処理に失敗しました。({flash_message_detail})', 'error')
            # raise ValueErrorを継続するなら、このflashは表示される前にリダイレクトされる可能性がある
            # ここでは明示的にリダイレクトする方が制御しやすい
            # raise ValueError("Invalid response from MiAuth check endpoint.")
            return redirect(url_for('auth.login_page'))


        token = check_data['token']
        user_info = check_data['user']
        misskey_user_id = user_info.get('id')
        misskey_username = user_info.get('username')
        current_app.logger.info(f"MiAuth check successful. Token received (masked): {token[:5]}..., User ID: {misskey_user_id}, Username: {misskey_username}")
        if not misskey_user_id:
            # このケースは上のifでカバーされるはずだが念のため
            raise ValueError("Misskey User ID not found in check response user object.")

    except requests.exceptions.RequestException as e:
        flash(f'Misskey MiAuth チェック APIへのアクセスに失敗しました: {e}', 'error')
        current_app.logger.error(f"Misskey MiAuth /check request failed: {e}")
        return redirect(url_for('auth.login_page'))
    except (ValueError, KeyError, Exception) as e: # ValueErrorは上記で独自に発生させない場合はjson.JSONDecodeErrorなども含む
         current_app.logger.error(f"Failed to process MiAuth /check response: {e}. Check data received: {check_data}")
         flash(f'Misskey MiAuth チェック応答の処理に失敗しました。サーバーログを確認してください。 ({e})', 'error')
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
        # 既存ユーザーの場合、ユーザー名を最新に更新
        if user.misskey_username != misskey_username:
            user.misskey_username = misskey_username
            try:
                db.session.commit()
                current_app.logger.info(f"Username updated for user ID {user.id} to {misskey_username}")
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error updating username for {misskey_username}: {e}")
        current_app.logger.info(f"Existing user logged in: {user.misskey_username} (App User ID: {user.id})")

    # 既存のセッションをクリアしてから新しいユーザーIDを設定
    # これにより、miauth_session_idのような一時的な情報もクリアされる
    session.clear()
    session['user_id'] = user.id
    current_app.logger.info(f"User {user.misskey_username} (App User ID: {user.id}) successfully logged in. Session 'user_id' set. Redirecting to dashboard.")
    flash('ログインしました。', 'success')
    return redirect(url_for('main.dashboard'))

# --- ログアウト ---
@auth_bp.route('/logout')
def logout():
    """ログアウト処理"""
    user_id = session.pop('user_id', None) # session.pop はキーが存在しない場合にエラーを出さない
    # user_id = g.user.id if hasattr(g, 'user') and g.user else None # gから取るなら
    
    session.clear() # セッション全体をクリア
    if hasattr(g, 'user'): del g.user # gからもユーザー情報を削除

    if user_id: # user_idがNoneでない（＝実際にログアウト処理が行われた）場合のみログ出力
        current_app.logger.info(f"User logged out: App User ID={user_id}")
    else:
        current_app.logger.info("Logout called but no user was in session or g.")
        
    flash('ログアウトしました。', 'info')
    return redirect(url_for('main.index'))

# --- _loginページ表示 ---
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
             current_app.logger.warning(f"announcements.json not found at {announcement_file}")
    except FileNotFoundError:
         current_app.logger.error(f"announcements.json not found (FileNotFoundError) at {announcement_file}.")
    except PermissionError:
         current_app.logger.error(f"Permission denied when reading announcements.json at {announcement_file}.")
    except json.JSONDecodeError as e:
        current_app.logger.error(f"Failed to parse announcements.json: {e}")
    except Exception as e:
        current_app.logger.error(f"An unexpected error occurred loading announcements: {e}", exc_info=True)

    return render_template('login.html',
                           announcements=announcements,
                           build_version=build_version)

# --- 【開発用】ローカル管理者ログインは削除済み ---
# dev_auth.py に移管されている想定