# motopuppu/__init__.py
import os
import datetime # datetime.datetime を使うためにインポート
import click
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from flask_migrate import Migrate
# from flask_wtf.csrf import CSRFProtect # Flask-WTF導入時にコメント解除

# .envファイルから環境変数を読み込む
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
    print("Loaded environment variables from .env") # 既存のprintは残す
else:
    print(f"Warning: .env file not found at {dotenv_path}") # 既存のprintは残す

db = SQLAlchemy()
migrate = Migrate()
# csrf = CSRFProtect() # Flask-WTF導入時にコメント解除

def create_app(config_name=None):
    """Flaskアプリケーションインスタンスを作成するファクトリ関数"""
    app = Flask(__name__, instance_relative_config=True)
    # print(f"Instance path: {app.instance_path}") # 必要であればコメント解除

    # --- 設定の読み込み ---
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-secret-key-replace-me'),
        SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URI', f"sqlite:///{os.path.join(app.instance_path, 'app.db')}"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 16)) * 1024 * 1024,
        MISSKEY_INSTANCE_URL=os.environ.get('MISSKEY_INSTANCE_URL', 'https://misskey.io'),
        LOCAL_ADMIN_USERNAME=os.environ.get('LOCAL_ADMIN_USERNAME'), # 使用しない
        LOCAL_ADMIN_PASSWORD=os.environ.get('LOCAL_ADMIN_PASSWORD'), # 使用しない
        # ▼▼▼ 元の形式で FLASK_ENV を読み込む ▼▼▼
        ENV=os.environ.get('FLASK_ENV', 'production'),
        # ▼▼▼ LOCAL_DEV_USER_ID を読み込む ▼▼▼
        LOCAL_DEV_USER_ID=os.environ.get('LOCAL_DEV_USER_ID'), # ローカル開発用ユーザーID
        FUEL_ENTRIES_PER_PAGE = int(os.environ.get('FUEL_ENTRIES_PER_PAGE', 20)),
        MAINTENANCE_ENTRIES_PER_PAGE = int(os.environ.get('MAINTENANCE_ENTRIES_PER_PAGE', 20)),
        NOTES_PER_PAGE = int(os.environ.get('NOTES_PER_PAGE', 20)),
    )
    # print(f"Database URI: {app.config['SQLALCHEMY_DATABASE_URI']}") # 必要であればコメント解除
    if app.config['SECRET_KEY'] == 'dev-secret-key-replace-me':
        print("Warning: SECRET_KEY is set to the default development value. Set it in .env!") # 既存のprintは残す
    # LOCAL_DEV_USER_ID 未設定のWarningは削除

    # --- 拡張機能の初期化 ---
    db.init_app(app)
    migrate.init_app(app, db)
    # csrf.init_app(app) # Flask-WTF導入時にコメント解除
    # (他のFlask拡張機能もここで初期化)

    # --- ルート (Blueprints) の登録 ---
    try:
        # ▼▼▼ dev_auth をインポートに追加 ▼▼▼
        from .views import auth, main, vehicle, fuel, maintenance, notes, dev_auth # dev_auth を追加
        app.register_blueprint(auth.auth_bp)
        app.register_blueprint(main.main_bp)
        app.register_blueprint(vehicle.vehicle_bp)
        app.register_blueprint(fuel.fuel_bp)
        app.register_blueprint(maintenance.maintenance_bp)
        app.register_blueprint(notes.notes_bp)
        # print("Registered blueprints: auth, main, vehicle, fuel, maintenance, notes") # 必要であればコメント解除

        # ▼▼▼ 開発環境の場合のみ dev_auth_bp を登録 ▼▼▼
        if app.config['ENV'] == 'development':
            app.register_blueprint(dev_auth.dev_auth_bp)
            # print("Registered development blueprint: dev_auth") # 登録ログは削除
        # ▲▲▲ ここまで変更 ▲▲▲

    except ImportError as e:
        print(f"Error importing or registering blueprints: {e}") # 既存のprintは残す

    # --- テスト用ルート (変更なし) ---
    @app.route('/hello_world_test')
    def hello_world_test():
        key_status = "Set" if app.config.get('SECRET_KEY') != 'dev-secret-key-replace-me' else "Not Set or Default!"
        return f"Hello from Flask! SECRET_KEY Status: {key_status}"

    # --- コンテキストプロセッサ (変更なし) ---
    @app.context_processor
    def inject_global_variables(): # 関数名を変更 (任意)
        commit_hash = os.environ.get('RENDER_GIT_COMMIT')
        display_version = commit_hash[:7] if commit_hash else 'local'
        return {
            'current_year': datetime.datetime.now().year,
            'app_version': display_version
            }

    # --- アプリケーションコンテキスト (変更なし) ---
    @app.shell_context_processor
    def make_shell_context():
        from .models import db, User, Motorcycle, FuelEntry, MaintenanceEntry, ConsumableLog, MaintenanceReminder, Attachment, GeneralNote
        return {
            'db': db, 'User': User, 'Motorcycle': Motorcycle, 'FuelEntry': FuelEntry,
            'MaintenanceEntry': MaintenanceEntry, 'ConsumableLog': ConsumableLog,
            'MaintenanceReminder': MaintenanceReminder, 'Attachment': Attachment,
            'GeneralNote': GeneralNote
        }

    # --- instanceフォルダの作成 (変更なし) ---
    try:
        os.makedirs(app.instance_path)
        # print(f"Instance folder checked/created at: {app.instance_path}") # 必要であればコメント解除
    except OSError:
        pass

    # --- DB初期化コマンド (変更なし) ---
    @app.cli.command("init-db")
    def init_db_command():
        """データベーステーブルを作成します。(Flask-Migrate管理下では通常 flask db upgrade を使用)"""
        click.echo("Initializing the database tables via db.create_all()...") # 既存のechoは残す
        try:
            with app.app_context():
                from .models import db
                db.create_all()
            click.echo("Database tables initialized successfully (if they didn't exist).") # 既存のechoは残す
        except Exception as e:
            try:
                with app.app_context(): db.session.rollback()
            except Exception as rb_exc: click.echo(f"Additionally, an error occurred during rollback: {rb_exc}", err=True) # 既存のechoは残す
            click.echo(f"Error initializing database tables: {e}", err=True) # 既存のechoは残す
            print(f"[ERROR] Error initializing database tables: {e}") # 既存のprintは残す
    # --- コマンドここまで ---

    # --- アプリケーションインスタンスを返す ---
    # print("create_app finished.") # 必要であればコメント解除
    return app