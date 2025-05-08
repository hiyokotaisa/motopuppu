# motopuppu/__init__.py

import os
import datetime # datetime.datetime を使うためにインポート
import click
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect # Flask-WTF導入時にコメント解除済み
import logging
import subprocess # ★ ローカル開発時のgitコマンド実行用にインポート ★

# .envファイルから環境変数を読み込む
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
    print("Loaded environment variables from .env")
else:
    print(f"Warning: .env file not found at {dotenv_path}")

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect() # Flask-WTF導入時にコメント解除済み

# --- ▼▼▼ ビルド情報読み込みヘルパー関数 ▼▼▼ ---
def get_build_info_from_files(app):
    """
    プロジェクトルートにある想定の .git_commit と .build_date ファイルから
    ビルド情報を読み込み、整形された文字列を返す。
    ファイルが見つからない場合は 'N/A' を含む文字列を返す。
    """
    commit = 'N/A'
    build_date = 'N/A'
    # Render環境などでの一般的なプロジェクトルートからの相対パス
    commit_file = '.git_commit' 
    date_file = '.build_date'
    
    try:
        # アプリケーションのルートディレクトリを取得 (例: /opt/render/project/src)
        # __file__ は __init__.py のパスなので、その親ディレクトリが motopuppu、さらにその親がプロジェクトルート
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        commit_file_path = os.path.join(base_dir, commit_file)
        date_file_path = os.path.join(base_dir, date_file)

        # コミットハッシュファイルの読み込み
        with open(commit_file_path, 'r') as f:
            commit = f.read().strip()
    except FileNotFoundError:
        # ファイルがない場合は警告ログを出す（エラーにはしない）
        app.logger.warning(f"Build info file not found: {commit_file_path}") 
    except Exception as e:
         # その他の読み込みエラー
         app.logger.error(f"Error reading {commit_file_path}: {e}")

    try:
        # ビルド日時ファイルの読み込み
        with open(date_file_path, 'r') as f:
            build_date = f.read().strip()
    except FileNotFoundError:
        app.logger.warning(f"Build info file not found: {date_file_path}")
    except Exception as e:
        app.logger.error(f"Error reading {date_file_path}: {e}")

    # 表示用文字列の組み立て
    return f"Commit: {commit} / Built: {build_date}"
# --- ▲▲▲ ヘルパー関数ここまで ▲▲▲ ---


def create_app(config_name=None):
    """Flaskアプリケーションインスタンスを作成するファクトリ関数"""
    app = Flask(__name__, instance_relative_config=True)

    # --- 設定の読み込み ---
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-secret-key-replace-me'), 
        SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URI', f"sqlite:///{os.path.join(app.instance_path, 'app.db')}"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 16)) * 1024 * 1024,
        MISSKEY_INSTANCE_URL=os.environ.get('MISSKEY_INSTANCE_URL', 'https://misskey.io'),
        LOCAL_ADMIN_USERNAME=os.environ.get('LOCAL_ADMIN_USERNAME'), 
        LOCAL_ADMIN_PASSWORD=os.environ.get('LOCAL_ADMIN_PASSWORD'), 
        ENV=os.environ.get('FLASK_ENV', 'production'),
        LOCAL_DEV_USER_ID=os.environ.get('LOCAL_DEV_USER_ID'), 
        FUEL_ENTRIES_PER_PAGE = int(os.environ.get('FUEL_ENTRIES_PER_PAGE', 20)),
        MAINTENANCE_ENTRIES_PER_PAGE = int(os.environ.get('MAINTENANCE_ENTRIES_PER_PAGE', 20)),
        NOTES_PER_PAGE = int(os.environ.get('NOTES_PER_PAGE', 20)),
    )
    if app.config['SECRET_KEY'] == 'dev-secret-key-replace-me' and app.config['ENV'] != 'development':
        app.logger.warning("CRITICAL: SECRET_KEY is set to the default development value in a non-development environment. This is a security risk!")
    elif app.config['SECRET_KEY'] == 'dev-secret-key-replace-me':
        print("Warning: SECRET_KEY is set to the default development value. Set it in .env for production!")

    # --- ログ設定 ---
    log_level_name = os.environ.get('LOG_LEVEL', 'INFO').upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    app.logger.setLevel(log_level)

    if not app.logger.handlers:
        stream_handler = logging.StreamHandler()
        app.logger.addHandler(stream_handler)
    
    app.logger.info(f"Flask logger initialized. Application log level set to: {log_level_name} ({log_level})")

    # --- 拡張機能の初期化 ---
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app) 

    # --- ルート (Blueprints) の登録 ---
    try:
        from .views import auth, main, vehicle, fuel, maintenance, notes, dev_auth
        app.register_blueprint(auth.auth_bp)
        app.register_blueprint(main.main_bp)
        app.register_blueprint(vehicle.vehicle_bp)
        app.register_blueprint(fuel.fuel_bp)
        app.register_blueprint(maintenance.maintenance_bp)
        app.register_blueprint(notes.notes_bp)

        if app.config['ENV'] == 'development':
            app.register_blueprint(dev_auth.dev_auth_bp)
            app.logger.info("Registered development blueprint: dev_auth")

    except ImportError as e:
        app.logger.error(f"Error importing or registering blueprints: {e}", exc_info=True)
        print(f"Error importing or registering blueprints: {e}")

    # --- テスト用ルート ---
    @app.route('/hello_world_test')
    def hello_world_test():
        key_status = "Set" if app.config.get('SECRET_KEY') != 'dev-secret-key-replace-me' else "Not Set or Default!"
        return f"Hello from Flask! SECRET_KEY Status: {key_status}"

    # --- コンテキストプロセッサ ---
    # ▼▼▼ 既存のコンテキストプロセッサを修正 ▼▼▼
    @app.context_processor
    def inject_global_variables():
        # まずファイルからビルド情報を取得試行
        build_info = get_build_info_from_files(app)

        # --- ローカル開発環境向けのフォールバック (ファイルがない場合) ---
        # Render環境以外 (例: ローカル) でファイルが見つからず 'N/A' が含まれ、
        # かつデバッグモードが有効な場合にGitコマンドを試す
        if 'N/A' in build_info and app.debug: 
            app.logger.info("Build info files not found, attempting to get info via git command (debug mode).")
            try:
                 # git rev-parse --short HEAD を実行してコミットハッシュを取得
                 commit = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=app.root_path).decode('utf-8').strip()
                 # ローカルのビルド時間は正確ではないので固定文字列など
                 build_info = f"Commit: {commit} / Built: (local dev)" 
            except FileNotFoundError:
                 app.logger.warning("Git command not found. Cannot determine commit hash.")
                 build_info = "Commit: N/A / Built: (local dev - git not found)" # gitコマンドが見つからない場合
            except subprocess.CalledProcessError:
                 app.logger.warning("Not a git repository or no commits yet.")
                 build_info = "Commit: N/A / Built: (local dev - not a git repo?)" # gitリポジトリでない場合
            except Exception as e:
                 app.logger.error(f"Error getting git info locally: {e}")
                 build_info = "Commit: N/A / Built: (local dev - error)" # その他のエラー
        # --- フォールバックここまで ---
        
        # テンプレートで使う変数を辞書で返す
        return {
            'current_year': datetime.datetime.now(datetime.timezone.utc).year,
            'build_version': build_info # ファイル or git or 'N/A' が入る
            # 'app_version' は削除 (build_version に統合)
        }
    # --- ▲▲▲ 修正ここまで ▲▲▲ ---

    # --- アプリケーションコンテキスト ---
    @app.shell_context_processor
    def make_shell_context():
        from .models import db, User, Motorcycle, FuelEntry, MaintenanceEntry, MaintenanceReminder, GeneralNote, OdoResetLog 
        return {
            'db': db, 'User': User, 'Motorcycle': Motorcycle, 'FuelEntry': FuelEntry,
            'MaintenanceEntry': MaintenanceEntry, 'MaintenanceReminder': MaintenanceReminder,
            'GeneralNote': GeneralNote, 'OdoResetLog': OdoResetLog
        }

    # --- instanceフォルダの作成 ---
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass 

    # --- DB初期化コマンド ---
    @app.cli.command("init-db")
    def init_db_command():
        """データベーステーブルを作成します。(Flask-Migrate管理下では通常 flask db upgrade を使用)"""
        click.echo("Initializing the database tables via db.create_all()...")
        try:
            with app.app_context():
                db.create_all()
            click.echo("Database tables initialized successfully (if they didn't exist).")
        except Exception as e:
            try:
                with app.app_context(): db.session.rollback()
            except Exception as rb_exc: click.echo(f"Additionally, an error occurred during rollback: {rb_exc}", err=True)
            click.echo(f"Error initializing database tables: {e}", err=True)
            app.logger.error(f"[ERROR] Error initializing database tables: {e}", exc_info=True)

    return app
