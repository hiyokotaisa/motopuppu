# motopuppu/__init__.py

import os
import datetime # datetime.datetime を使うためにインポート
import click
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect # Flask-WTF導入時にコメント解除済み

# --- logging モジュールをインポート ---
import logging

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

def create_app(config_name=None):
    """Flaskアプリケーションインスタンスを作成するファクトリ関数"""
    app = Flask(__name__, instance_relative_config=True)

    # --- 設定の読み込み ---
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-secret-key-replace-me'), # 本番環境では必ず.envで設定してください
        SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URI', f"sqlite:///{os.path.join(app.instance_path, 'app.db')}"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 16)) * 1024 * 1024,
        MISSKEY_INSTANCE_URL=os.environ.get('MISSKEY_INSTANCE_URL', 'https://misskey.io'),
        LOCAL_ADMIN_USERNAME=os.environ.get('LOCAL_ADMIN_USERNAME'), # 現在未使用
        LOCAL_ADMIN_PASSWORD=os.environ.get('LOCAL_ADMIN_PASSWORD'), # 現在未使用
        ENV=os.environ.get('FLASK_ENV', 'production'),
        LOCAL_DEV_USER_ID=os.environ.get('LOCAL_DEV_USER_ID'), # ローカル開発用ユーザーID
        FUEL_ENTRIES_PER_PAGE = int(os.environ.get('FUEL_ENTRIES_PER_PAGE', 20)),
        MAINTENANCE_ENTRIES_PER_PAGE = int(os.environ.get('MAINTENANCE_ENTRIES_PER_PAGE', 20)),
        NOTES_PER_PAGE = int(os.environ.get('NOTES_PER_PAGE', 20)),
        # Flask-WTF の CSRF 設定 (任意、デフォルトで有効)
        # WTF_CSRF_ENABLED = True
        # WTF_CSRF_TIME_LIMIT = 3600 # CSRFトークンの有効期限 (秒)
    )
    if app.config['SECRET_KEY'] == 'dev-secret-key-replace-me' and app.config['ENV'] != 'development':
        app.logger.warning("CRITICAL: SECRET_KEY is set to the default development value in a non-development environment. This is a security risk!")
    elif app.config['SECRET_KEY'] == 'dev-secret-key-replace-me':
        print("Warning: SECRET_KEY is set to the default development value. Set it in .env for production!")


    # --- ここからログ設定 ---
    log_level_name = os.environ.get('LOG_LEVEL', 'INFO').upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    app.logger.setLevel(log_level)

    if not app.logger.handlers:
        stream_handler = logging.StreamHandler()
        # formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]')
        # stream_handler.setFormatter(formatter)
        app.logger.addHandler(stream_handler)
    
    app.logger.info(f"Flask logger initialized. Application log level set to: {log_level_name} ({log_level})")
    # --- ログ設定ここまで ---

    # --- 拡張機能の初期化 ---
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app) # Flask-WTF導入時にコメント解除済み
    # (他のFlask拡張機能もここで初期化)

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
    @app.context_processor
    def inject_global_variables():
        commit_hash = os.environ.get('RENDER_GIT_COMMIT')
        display_version = commit_hash[:7] if commit_hash else 'local'
        return {
            'current_year': datetime.datetime.now(datetime.timezone.utc).year, # タイムゾーンを考慮
            'app_version': display_version
            }

    # --- アプリケーションコンテキスト ---
    @app.shell_context_processor
    def make_shell_context():
        from .models import db, User, Motorcycle, FuelEntry, MaintenanceEntry, MaintenanceReminder, GeneralNote, OdoResetLog # OdoResetLog を追加
        return {
            'db': db, 'User': User, 'Motorcycle': Motorcycle, 'FuelEntry': FuelEntry,
            'MaintenanceEntry': MaintenanceEntry, 'MaintenanceReminder': MaintenanceReminder,
            'GeneralNote': GeneralNote, 'OdoResetLog': OdoResetLog
            # 'ConsumableLog' と 'Attachment' はコメントアウトされていたため削除 (必要なら戻してください)
        }

    # --- instanceフォルダの作成 ---
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass # フォルダが既に存在する場合は何もしない

    # --- DB初期化コマンド ---
    @app.cli.command("init-db")
    def init_db_command():
        """データベーステーブルを作成します。(Flask-Migrate管理下では通常 flask db upgrade を使用)"""
        click.echo("Initializing the database tables via db.create_all()...")
        try:
            with app.app_context():
                # from .models import db # dbはグローバルスコープで定義済み
                db.create_all()
            click.echo("Database tables initialized successfully (if they didn't exist).")
        except Exception as e:
            try:
                with app.app_context(): db.session.rollback()
            except Exception as rb_exc: click.echo(f"Additionally, an error occurred during rollback: {rb_exc}", err=True)
            click.echo(f"Error initializing database tables: {e}", err=True)
            app.logger.error(f"[ERROR] Error initializing database tables: {e}", exc_info=True)

    return app