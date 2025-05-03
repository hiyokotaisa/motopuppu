# motopuppu/__init__.py
import os
import datetime # datetimeモジュールをインポート (current_year用)
import click
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from flask_migrate import Migrate # ▼▼▼ 追加 ▼▼▼

# .envファイルから環境変数を読み込む
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
    print("Loaded environment variables from .env") # 読み込み確認用
else:
    print(f"Warning: .env file not found at {dotenv_path}")

# SQLAlchemy と Migrate オブジェクトをここでインスタンス化
db = SQLAlchemy()
migrate = Migrate() # ▼▼▼ 追加 ▼▼▼

def create_app(config_name=None):
    """Flaskアプリケーションインスタンスを作成するファクトリ関数"""
    app = Flask(__name__, instance_relative_config=True)
    print(f"Instance path: {app.instance_path}") # 確認用

    # --- 設定の読み込み ---
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-secret-key-replace-me'),
        SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URI', f"sqlite:///{os.path.join(app.instance_path, 'app.db')}"), # DBファイル名を app.db に
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 16)) * 1024 * 1024,
        MISSKEY_INSTANCE_URL=os.environ.get('MISSKEY_INSTANCE_URL', 'https://misskey.io'),
        LOCAL_ADMIN_USERNAME=os.environ.get('LOCAL_ADMIN_USERNAME'),
        LOCAL_ADMIN_PASSWORD=os.environ.get('LOCAL_ADMIN_PASSWORD'),
        ENV=os.environ.get('FLASK_ENV', 'production'),
        # 1ページあたりの表示件数
        FUEL_ENTRIES_PER_PAGE = int(os.environ.get('FUEL_ENTRIES_PER_PAGE', 20)),
        MAINTENANCE_ENTRIES_PER_PAGE = int(os.environ.get('MAINTENANCE_ENTRIES_PER_PAGE', 20)),
    )
    print(f"Database URI: {app.config['SQLALCHEMY_DATABASE_URI']}") # 確認用
    if app.config['SECRET_KEY'] == 'dev-secret-key-replace-me':
        print("Warning: SECRET_KEY is set to the default development value. Set it in .env!")

    # --- 拡張機能の初期化 ---
    db.init_app(app)
    migrate.init_app(app, db) # ▼▼▼ ここで app と db に関連付け ▼▼▼
    # (他のFlask拡張機能もここで初期化)

    # --- ルート (Blueprints) の登録 ---
    try:
        # views パッケージから各Blueprintをインポート
        from .views import auth
        from .views import main
        from .views import vehicle
        from .views import fuel
        from .views import maintenance
        # (後で他のBlueprintもインポート)

        # アプリケーションにBlueprintを登録
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
        """全てのテンプレートで 'current_year' 変数を使えるようにする"""
        return {'current_year': datetime.datetime.now().year}

    # --- アプリケーションコンテキスト (flask shell用) ---
    @app.shell_context_processor
    def make_shell_context():
        # シェルからアクセスしたいモデルやdbオブジェクトを返す
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

    # --- DB初期化コマンド (変更なし) ---
    @app.cli.command("init-db")
    def init_db_command():
        """データベーステーブルを作成します。また、ローカル管理者ユーザーが存在しない場合に作成します。"""
        click.echo("Initializing the database...")
        try:
            with app.app_context():
                from .models import User, db
                # db.drop_all()
                # click.echo("Dropped existing tables.")
                db.create_all()
                click.echo("Created database tables.")

                admin_misskey_id = 'local_admin'
                admin_username = app.config.get('LOCAL_ADMIN_USERNAME') or 'Admin'
                admin_password_set = app.config.get('LOCAL_ADMIN_PASSWORD')

                existing_admin = User.query.filter_by(misskey_user_id=admin_misskey_id).first()
                if not existing_admin:
                    if admin_password_set:
                        admin_user = User(misskey_user_id=admin_misskey_id, misskey_username=admin_username, is_admin=True)
                        db.session.add(admin_user)
                        db.session.commit()
                        click.echo(f"Created local admin user: {admin_username} (ID: {admin_misskey_id})")
                    else:
                        click.echo("Warning: LOCAL_ADMIN_PASSWORD not set in config, skipping admin creation.")
                else:
                    click.echo(f"Local admin user ({existing_admin.misskey_username}) already exists.")

            click.echo("Initialized the database successfully.")
        except Exception as e:
            try:
                with app.app_context():
                     db.session.rollback()
            except Exception as rb_exc:
                 click.echo(f"Additionally, an error occurred during rollback: {rb_exc}", err=True)
            click.echo(f"Error initializing database: {e}", err=True)
            print(f"[ERROR] Error initializing database: {e}")
    # --- コマンド定義ここまで ---

    # --- アプリケーションインスタンスを返す ---
    print("create_app finished.")
    return app
