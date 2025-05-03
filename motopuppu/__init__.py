# motopuppu/__init__.py
import os
import datetime
import click
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from flask_migrate import Migrate

# .envファイルから環境変数を読み込む
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
    print("Loaded environment variables from .env")
else:
    print(f"Warning: .env file not found at {dotenv_path}")

db = SQLAlchemy()
migrate = Migrate()

def create_app(config_name=None):
    """Flaskアプリケーションインスタンスを作成するファクトリ関数"""
    app = Flask(__name__, instance_relative_config=True)
    print(f"Instance path: {app.instance_path}")

    # --- 設定の読み込み ---
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-secret-key-replace-me'),
        SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URI', f"sqlite:///{os.path.join(app.instance_path, 'app.db')}"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 16)) * 1024 * 1024,
        MISSKEY_INSTANCE_URL=os.environ.get('MISSKEY_INSTANCE_URL', 'https://misskey.io'),
        LOCAL_ADMIN_USERNAME=os.environ.get('LOCAL_ADMIN_USERNAME'), # 設定自体は読み込むが使用しない
        LOCAL_ADMIN_PASSWORD=os.environ.get('LOCAL_ADMIN_PASSWORD'), # 設定自体は読み込むが使用しない
        ENV=os.environ.get('FLASK_ENV', 'production'),
        FUEL_ENTRIES_PER_PAGE = int(os.environ.get('FUEL_ENTRIES_PER_PAGE', 20)),
        MAINTENANCE_ENTRIES_PER_PAGE = int(os.environ.get('MAINTENANCE_ENTRIES_PER_PAGE', 20)),
    )
    print(f"Database URI: {app.config['SQLALCHEMY_DATABASE_URI']}")
    if app.config['SECRET_KEY'] == 'dev-secret-key-replace-me':
        print("Warning: SECRET_KEY is set to the default development value. Set it in .env!")

    # --- 拡張機能の初期化 ---
    db.init_app(app)
    migrate.init_app(app, db)
    # (他のFlask拡張機能もここで初期化)

    # --- ルート (Blueprints) の登録 ---
    try:
        from .views import auth, main, vehicle, fuel, maintenance
        app.register_blueprint(auth.auth_bp)
        app.register_blueprint(main.main_bp)
        app.register_blueprint(vehicle.vehicle_bp)
        app.register_blueprint(fuel.fuel_bp)
        app.register_blueprint(maintenance.maintenance_bp)
        print("Registered blueprints: auth, main, vehicle, fuel, maintenance")
    except ImportError as e:
        print(f"Error importing or registering blueprints: {e}")

    # --- テスト用ルート (任意) ---
    @app.route('/hello_world_test')
    def hello_world_test():
        key_status = "Set" if app.config.get('SECRET_KEY') != 'dev-secret-key-replace-me' else "Not Set or Default!"
        return f"Hello from Flask! SECRET_KEY Status: {key_status}"

    # --- コンテキストプロセッサ ---
    @app.context_processor
    def inject_current_year():
        return {'current_year': datetime.datetime.now().year}

    # --- アプリケーションコンテキスト (flask shell用) ---
    @app.shell_context_processor
    def make_shell_context():
        from .models import db, User, Motorcycle, FuelEntry, MaintenanceEntry, ConsumableLog, MaintenanceReminder, Attachment
        return {
            'db': db, 'User': User, 'Motorcycle': Motorcycle, 'FuelEntry': FuelEntry,
            'MaintenanceEntry': MaintenanceEntry, 'ConsumableLog': ConsumableLog,
            'MaintenanceReminder': MaintenanceReminder, 'Attachment': Attachment
        }

    # --- instanceフォルダの作成 (存在しない場合) ---
    try:
        os.makedirs(app.instance_path)
        print(f"Instance folder checked/created at: {app.instance_path}")
    except OSError:
        pass

    # --- ▼▼▼ DB初期化コマンド (管理者作成ロジック削除) ▼▼▼ ---
    @app.cli.command("init-db")
    def init_db_command():
        """データベーステーブルを作成します。(Flask-Migrate管理下では通常 flask db upgrade を使用)"""
        click.echo("Initializing the database tables via db.create_all()...")
        try:
            with app.app_context():
                from .models import db # dbオブジェクトのみ必要
                # db.drop_all() # 必要なら既存テーブルを削除
                # click.echo("Dropped existing tables.")
                db.create_all() # テーブルを作成
            click.echo("Database tables initialized successfully (if they didn't exist).")
        except Exception as e:
            try:
                # コンテキストが必要な場合があるため
                with app.app_context():
                     db.session.rollback()
            except Exception as rb_exc:
                 click.echo(f"Additionally, an error occurred during rollback: {rb_exc}", err=True)
            click.echo(f"Error initializing database tables: {e}", err=True)
            print(f"[ERROR] Error initializing database tables: {e}")
    # --- ▲▲▲ コマンドここまで ▲▲▲ ---

    # --- アプリケーションインスタンスを返す ---
    print("create_app finished.")
    return app
