# motopuppu/__init__.py

import os
import datetime # datetime.datetime を使うためにインポート
import click
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
import logging
import subprocess # ローカル開発時のgitコマンド実行用にインポート

# .envファイルから環境変数を読み込む
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
    print("Loaded environment variables from .env")
else:
    print(f"Warning: .env file not found at {dotenv_path}")

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()

# ★★★ ファイル読み込みヘルパー関数は削除 ★★★

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

        if app.config['ENV'] == 'development' or app.debug: # デバッグモードでも開発用BPを有効にする
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
    # ▼▼▼ コンテキストプロセッサを修正 ▼▼▼
    @app.context_processor
    def inject_global_variables():
        commit_hash_short = 'N/A'
        source_info = "" # どこから情報を取得したかの補助情報

        # 1. Render 環境変数を試す (最優先)
        render_commit = os.environ.get('RENDER_GIT_COMMIT')
        if render_commit:
            commit_hash_short = render_commit[:7] # 短いハッシュ
            source_info = "(Render Build)"
        
        # 2. ローカル開発環境向けのフォールバック (Render環境変数がない場合)
        elif app.debug: 
            app.logger.info("RENDER_GIT_COMMIT not found, attempting to get info via git command (debug mode).")
            try:
                 # git rev-parse --short HEAD を実行してコミットハッシュを取得
                 commit_hash_short = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=app.root_path).decode('utf-8').strip()
                 source_info = "(local dev)" 
            except FileNotFoundError:
                 app.logger.warning("Git command not found. Cannot determine commit hash.")
                 commit_hash_short = "N/A"
                 source_info = "(local dev - git not found)"
            except subprocess.CalledProcessError:
                 app.logger.warning("Not a git repository or no commits yet.")
                 commit_hash_short = "N/A"
                 source_info = "(local dev - not a git repo?)"
            except Exception as e:
                 app.logger.error(f"Error getting git info locally: {e}")
                 commit_hash_short = "N/A"
                 source_info = "(local dev - error)"
        
        # 3. 上記いずれでも取得できなかった場合
        else:
            commit_hash_short = "N/A"
            source_info = "(unknown)"
            
        # 表示用文字列を組み立てる
        build_version_string = f"Commit: {commit_hash_short} {source_info}".strip()

        # テンプレートで使う変数を辞書で返す
        return {
            'current_year': datetime.datetime.now(datetime.timezone.utc).year,
            'build_version': build_version_string 
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
