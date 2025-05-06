# motopuppu/views/auth.py
import uuid
import requests
import json # json と os をインポート
import os
from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for, current_app
)
# データベースモデルとdbオブジェクトをインポート
from .. import db
from ..models import User # Userモデルなど必要なモデルをインポート (Motorcycleはここでは不要)
# ヘルパー関数&デコレータ用にインポート
from functools import wraps

# 'auth' という名前でBlueprintオブジェクトを作成
auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

# --- ヘルパー関数 (miauth_callback より前に定義が必要な場合があるため移動) ---
def get_current_user():
    """
    セッションIDから現在のユーザーオブジェクトを取得する。
    DBにユーザーが存在しない場合はNoneを返し、セッションをクリアする。
    """
    user_id = session.get('user_id')
    if user_id is None:
        if 'user' in g: del g.user
        return None
    if 'user' in g and hasattr(g.user, 'id') and g.user.id == user_id: # g.userがNoneでないこと、id属性を持つこと、IDが一致することを確認
        return g.user
    
    user = User.query.get(user_id) # SQLAlchemy 2.0+ では User.query.get(user_id) は非推奨の場合あり。db.session.get(User, user_id) を検討。
    if user:
        g.user = user
        return g.user
    else:
        current_app.logger.warning(f"User ID {user_id} found in session, but no user in DB. Clearing session.")
        session.clear()
        if 'user' in g: del g.user
        return None

# --- MiAuth 認証フロー ---

@auth_bp.route('/login', methods=['GET'])
def login():
    """MiAuth認証を開始: Misskey認証ページへリダイレクトする"""
    miauth_session_id = str(uuid.uuid4())
    session['miauth_session_id'] = miauth_session_id
    current_app.logger.debug(f"Session before redirect: {dict(session)}") # セッション内容をログ出力
    misskey_instance_url = current_app.config.get('MISSKEY_INSTANCE_URL', 'https://misskey.io')
    app_name = "motopuppu" # アプリケーション名を適切に設定
    # 必要なパーミッションを指定 (例: 'read:account')
    # Misskeyのドキュメントで利用可能なパーミッションを確認してください
    permissions = "read:account"
    # url_forでコールバックURLを動的に生成し、Misskeyに渡す
    # _external=True で絶対URLを生成
    callback_url = url_for('auth.miauth_callback', _external=True)

    from urllib.parse import urlencode # urlencodeをインポート
    # MiAuth認証URLの組み立て
    # permissionパラメータはカンマ区切りで複数指定可能
    params = {'name': app_name, 'permission': permissions, 'callback': callback_url}
    auth_url = f"{misskey_instance_url}/miauth/{miauth_session_id}?{urlencode(params)}"
    current_app.logger.info(f"Redirecting to MiAuth URL: {auth_url}")
    return redirect(auth_url)


@auth_bp.route('/miauth/callback', methods=['GET'])
def miauth_callback():
    # 既にユーザーがログインしているか確認 (get_current_user はDBアクセスを伴う可能性があるので注意)
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
    current_app.logger.debug(f"Session state at callback entry: {dict(session)}") # セッション状態をログ

    expected_session_id = session.get('miauth_session_id')

    if not expected_session_id or expected_session_id != received_session_id:
        if 'user_id' in session and get_current_user() is not None: # 念のため再度ログイン状態を確認
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

    # セッションIDが期待通りであれば、ここでセッションからpopする
    session.pop('miauth_session_id', None)
    current_app.logger.info(f"Popped 'miauth_session_id' from session after validation for received_session_id: {received_session_id}")

    misskey_instance_url = current_app.config.get('MISSKEY_INSTANCE_URL', 'https://misskey.io')
    check_url = f"{misskey_instance_url}/api/miauth/{received_session_id}/check"
    current_app.logger.info(f"Checking session with Misskey API: {check_url}")

    check_data = None # check_data を try ブロックの外で初期化
    try:
        check_response = requests.post(check_url, timeout=10) # Misskey APIにPOSTリクエスト
        check_response.raise_for_status()  # HTTPエラーがあれば例外を発生させる
        check_data = check_response.json() # レスポンスをJSONとしてパース
        current_app.logger.debug(f"Misskey /check response: {check_data}")

        # MiAuth /check 応答の検証
        if not check_data.get('ok') or not check_data.get('token') or not check_data.get('user'):
            current_app.logger.error(f"MiAuth /check response was not 'ok' or missing 'token'/'user'. Response: {check_data}")
            # ★★★ここからが重要な変更点★★★
            if isinstance(check_data, dict) and check_data.get('ok') is False:
                current_app.logger.warning(
                    f"MiAuth /check returned 'ok: False' for session {received_session_id}. "
                    "This might be due to a rapid double callback where the first succeeded. "
                    "Optimistically redirecting to dashboard, assuming the first callback logged the user in."
                )
                flash('認証処理が完了しました。ダッシュボードに遷移します。', 'info')
                return redirect(url_for('main.dashboard'))
            # ★★★ここまでが重要な変更点★★★
            # 上記の条件に当てはまらない場合は、通常のエラーとして処理
            raise ValueError(f"Invalid response from MiAuth check endpoint. Response: {check_data}")


        token = check_data['token']
        user_info = check_data['user']
        misskey_user_id = user_info.get('id')
        misskey_username = user_info.get('username')
        current_app.logger.info(f"MiAuth check successful. Token received (masked): {token[:5]}..., User ID: {misskey_user_id}, Username: {misskey_username}")

        if not misskey_user_id: # MisskeyユーザーIDが取得できなかった場合
            raise ValueError("Misskey User ID not found in check response user object.")

    except requests.exceptions.RequestException as e: # requestsライブラリ関連の例外
        flash(f'Misskey MiAuth チェック APIへのアクセスに失敗しました: {e}', 'error')
        current_app.logger.error(f"Misskey MiAuth /check request failed: {e}")
        return redirect(url_for('auth.login_page'))
    except (ValueError, KeyError, Exception) as e: # その他の予期せぬエラー
         current_app.logger.error(f"Failed to process MiAuth /check response or other error: {e}. Check data if available: {check_data if check_data is not None else 'Not available during this exception'}")
         flash(f'Misskey MiAuth 認証処理中に予期せぬエラーが発生しました。 ({e})', 'error')
         return redirect(url_for('auth.login_page'))

    # ユーザー情報をデータベースで検索または作成
    user = User.query.filter_by(misskey_user_id=misskey_user_id).first()
    if not user: # ユーザーが存在しない場合、新規作成
        user = User(misskey_user_id=misskey_user_id, misskey_username=misskey_username, is_admin=False) # is_adminは適切に設定
        db.session.add(user)
        try:
            db.session.commit()
            flash(f'ようこそ、{misskey_username}さん！アカウントが作成されました。', 'success')
            current_app.logger.info(f"New user created: {misskey_username} (App User ID: {user.id})")
        except Exception as e:
            db.session.rollback() # エラー発生時はロールバック
            flash(f'ユーザーアカウントの作成中にエラーが発生しました。', 'error')
            current_app.logger.error(f"Database error creating user: {e}")
            return redirect(url_for('auth.login_page'))
    else: # ユーザーが既に存在する場合
        # Misskeyのユーザー名が変更されている可能性を考慮して更新
        if user.misskey_username != misskey_username:
            user.misskey_username = misskey_username
            try:
                db.session.commit()
                current_app.logger.info(f"Username updated for user ID {user.id} to {misskey_username}")
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error updating username for {misskey_username}: {e}")
        current_app.logger.info(f"Existing user logged in: {user.misskey_username} (App User ID: {user.id})")

    # ログイン処理: FlaskセッションにユーザーIDを保存
    session.clear() # 既存のセッション情報をクリア (MiAuth関連のIDなどを確実に消すため)
    session['user_id'] = user.id # ユーザーIDをセッションに保存
    # g.user = user # gオブジェクトにもユーザー情報を格納 (get_current_userで利用)
    current_app.logger.info(f"User {user.misskey_username} (App User ID: {user.id}) successfully logged in. Session 'user_id' set. Redirecting to dashboard.")
    flash('ログインしました。', 'success')
    return redirect(url_for('main.dashboard')) # メインのダッシュボードなどにリダイレクト

# --- ログアウト ---
@auth_bp.route('/logout')
# @login_required_custom # ログイン必須にする場合
def logout():
    """ログアウト処理"""
    user_id = session.pop('user_id', None) # セッションからユーザーIDを削除
    # g.pop('user', None) # gオブジェクトからもユーザー情報を削除
    session.clear() #念のためセッション全体をクリア
    if user_id:
        current_app.logger.info(f"User logged out: App User ID={user_id}")
    flash('ログアウトしました。', 'info')
    return redirect(url_for('main.index')) # ログアウト後はトップページなどにリダイレクト


# --- ログインページ表示 ---
@auth_bp.route('/login_page')
def login_page():
    """ログインページを表示し、お知らせとバージョン情報を渡す"""
    if 'user_id' in session and get_current_user() is not None: # 既にログイン済みならダッシュボードへ
        return redirect(url_for('main.dashboard'))

    announcements = []
    build_version = os.environ.get('APP_VERSION', 'N/A') # Renderなら環境変数でバージョン管理可能
    try:
        # current_app.root_path は 'motopuppu' パッケージのディレクトリ
        # announcements.json はプロジェクトルートにある想定
        announcement_file = os.path.join(current_app.root_path, '..', 'announcements.json')
        if os.path.exists(announcement_file):
            with open(announcement_file, 'r', encoding='utf-8') as f:
                all_announcements = json.load(f)
                # 'active'がtrueのものだけをフィルタリング
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
        # exc_info=Trueでスタックトレースをログに出力
        current_app.logger.error(f"An unexpected error occurred loading announcements: {e}", exc_info=True)

    return render_template('login.html',
                           announcements=announcements,
                           build_version=build_version)


# --- login_required_custom デコレータ ---
def login_required_custom(f):
    """自作のログイン必須デコレータ"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if get_current_user() is None: # g.userを参照する代わりにget_current_user()の結果を直接評価
            flash('このページにアクセスするにはログインが必要です。', 'warning')
            # nextパラメータに現在のリクエストURLを渡すことで、ログイン後に元のページに戻れるようにする
            return redirect(url_for('auth.login_page', next=request.url))
        return f(*args, **kwargs)
    return decorated_function