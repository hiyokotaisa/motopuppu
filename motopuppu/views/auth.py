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
    # ★ get_current_user を使うように変更しても良いが、ここでは session の有無で判断
    if 'user_id' in session and get_current_user() is not None: # 念のためget_current_userも確認
        return redirect(url_for('main.dashboard'))
    # login.html テンプレートを表示
    return render_template('login.html')


# --- 【開発用】ローカル管理者ログイン ---
# !!! リリース前には必ずこのルートと関連機能、設定を削除してください !!!
@auth_bp.route('/local_login', methods=['POST'])
def local_login():
    """【開発用】ローカル管理者ログイン処理"""
    if current_app.config['ENV'] != 'development':
         flash('この機能は開発環境でのみ利用可能です。', 'error')
         current_app.logger.critical("Attempted to use local_login outside development environment!")
         return redirect(url_for('auth.login_page'))

    username = request.form.get('username')
    password = request.form.get('password')
    admin_user_env = current_app.config.get('LOCAL_ADMIN_USERNAME')
    admin_pass_env = current_app.config.get('LOCAL_ADMIN_PASSWORD')

    if not admin_user_env or not admin_pass_env:
        flash('【開発用】ローカル管理者ログインが設定されていません。', 'error')
        current_app.logger.error("Local admin credentials not found in config.")
        return redirect(url_for('auth.login_page'))

    if username == admin_user_env and password == admin_pass_env:
        admin_user = User.query.filter_by(misskey_user_id='local_admin', is_admin=True).first()
        if admin_user:
            session.clear()
            session['user_id'] = admin_user.id
            flash('ローカル管理者としてログインしました。(開発用)', 'warning')
            current_app.logger.warning(f"Local admin logged in: {admin_user.misskey_username} (App User ID: {admin_user.id})")
            return redirect(url_for('main.dashboard'))
        else:
            flash('【開発用】ローカル管理者ユーザーがデータベースに見つかりません。', 'error')
            current_app.logger.error("Local admin user 'local_admin' with is_admin=True not found in DB.")
            return redirect(url_for('auth.login_page'))
    else:
        flash('【開発用】ローカル管理者のユーザー名またはパスワードが違います。', 'error')
        current_app.logger.warning(f"Failed local admin login attempt for username: {username}")
        return redirect(url_for('auth.login_page'))


# --- ヘルパー関数 & デコレータ ---

# from flask import g # g は通常 Flask から直接インポートされる (ファイル上部で済)
# from functools import wraps # wraps もファイル上部でインポート済

# ▼▼▼ get_current_user 関数を修正 ▼▼▼
def get_current_user():
    """
    セッションIDから現在のユーザーオブジェクトを取得する。
    DBにユーザーが存在しない場合はNoneを返し、セッションをクリアする。
    """
    user_id = session.get('user_id')
    if user_id is None:
        # セッションに user_id がなければ未ログイン
        if 'user' in g: del g.user # gに古い情報が残らないように
        return None

    # gオブジェクトにキャッシュされていればそれを返す
    if 'user' in g:
        return g.user

    # セッションに user_id があるので、DBからユーザーを検索
    user = User.query.get(user_id) # DBから取得試行

    if user:
        # DBにユーザーが見つかった場合 -> ログイン中
        g.user = user # gオブジェクトにキャッシュ
        current_app.logger.debug(f"Current user fetched from DB: {g.user}")
        return g.user
    else:
        # DBにユーザーが見つからなかった場合 (不正/古いセッション)
        current_app.logger.warning(f"User ID {user_id} found in session, but no user in DB. Clearing session.")
        session.clear() # セッションをクリアしてログアウト状態にする
        if 'user' in g: del g.user # gに古い情報が残らないように
        return None     # 未ログインとして None を返す
# ▲▲▲ 修正ここまで ▲▲▲

def login_required_custom(f):
    """自作のログイン必須デコレータ"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # get_current_user() を呼び出して現在のユーザーを取得し、g.user に格納
        g.user = get_current_user() # 修正された get_current_user を使う
        if g.user is None:
            # ログインしていない場合はログインページへリダイレクト
            flash('このページにアクセスするにはログインが必要です。', 'warning')
            # nextパラメータに元のURLを渡しておくと、ログイン後に戻れて便利
            return redirect(url_for('auth.login_page', next=request.url))
        # ログイン済みの場合は元の関数を実行
        return f(*args, **kwargs)
    return decorated_function
