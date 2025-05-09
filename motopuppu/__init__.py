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

def create_app(config_name=None):
    """Flaskアプリケーションインスタンスを作成するファクトリ関数"""
    app = Flask(__name__, instance_relative_config=True)

    # --- 設定の読み込み ---
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-secret-key-replace-me'),
        SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URI', f"sqlite:///{os.path.join(app.instance_path, 'app.db')}"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 16)) * 1024 * 1024,
        MISSKEY_INSTANCE_URL=os.environ.get('MISSKEY_INSTANCE_URL', 'https://misskey.io'), # Misskey URL設定
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
        # フォーマッターを設定する場合 (任意)
        # formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        # stream_handler.setFormatter(formatter)
        app.logger.addHandler(stream_handler)

    app.logger.info(f"Flask logger initialized. Application log level set to: {log_level_name} ({log_level})")

    # --- 拡張機能の初期化 ---
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    # --- ルート (Blueprints) の登録 ---
    try:
        from .views import auth, main, vehicle, fuel, maintenance, notes, dev_auth
        from .views import achievements as achievements_view 

        app.register_blueprint(auth.auth_bp)
        app.register_blueprint(main.main_bp)
        app.register_blueprint(vehicle.vehicle_bp)
        app.register_blueprint(fuel.fuel_bp)
        app.register_blueprint(maintenance.maintenance_bp)
        app.register_blueprint(notes.notes_bp)
        app.register_blueprint(achievements_view.achievements_bp) 

        if app.config['ENV'] == 'development' or app.debug: 
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
        commit_hash_short = 'N/A'
        source_info = ""

        render_commit = os.environ.get('RENDER_GIT_COMMIT')
        if render_commit:
            commit_hash_short = render_commit[:7]
            source_info = "(Render Build)"
        elif app.debug: 
            try:
                 project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
                 commit_hash_short = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=project_root).decode('utf-8').strip()
                 source_info = "(local dev)"
            except FileNotFoundError:
                 app.logger.warning("Git command not found. Cannot determine commit hash.")
                 commit_hash_short = "N/A (git not found)"; source_info = ""
            except subprocess.CalledProcessError:
                 app.logger.warning("Not a git repository or no commits yet.")
                 commit_hash_short = "N/A (not a git repo?)"; source_info = ""
            except Exception as e:
                 app.logger.error(f"Error getting git info locally: {e}")
                 commit_hash_short = "N/A (git error)"; source_info = ""
        else: 
            commit_hash_short = "N/A"; source_info = "(unknown)"

        build_version_string = f"{commit_hash_short} {source_info}".strip()

        misskey_instance_url = app.config.get('MISSKEY_INSTANCE_URL') 
        if not misskey_instance_url:
            misskey_instance_url = 'https://misskey.io'

        temp_domain = misskey_instance_url.replace('https://', '').replace('http://', '').split('/')[0].strip()
        if not temp_domain:
            misskey_instance_domain = 'misskey.io'
        else:
            misskey_instance_domain = temp_domain

        return {
            'current_year': datetime.datetime.now(datetime.timezone.utc).year,
            'build_version': build_version_string,
            'misskey_instance_domain': misskey_instance_domain 
        }

    # --- アプリケーションコンテキスト ---
    @app.shell_context_processor
    def make_shell_context():
        from .models import db, User, Motorcycle, FuelEntry, MaintenanceEntry, MaintenanceReminder, GeneralNote, OdoResetLog, AchievementDefinition, UserAchievement
        return {
            'db': db, 'User': User, 'Motorcycle': Motorcycle, 'FuelEntry': FuelEntry,
            'MaintenanceEntry': MaintenanceEntry, 'MaintenanceReminder': MaintenanceReminder,
            'GeneralNote': GeneralNote, 'OdoResetLog': OdoResetLog,
            'AchievementDefinition': AchievementDefinition, 'UserAchievement': UserAchievement
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
                with app.app_context(): 
                    db.session.rollback()
            except Exception as rb_exc: 
                click.echo(f"Additionally, an error occurred during rollback: {rb_exc}", err=True)
            click.echo(f"Error initializing database tables: {e}", err=True)
            app.logger.error(f"[ERROR] Error initializing database tables: {e}", exc_info=True)
    
    # ▼▼▼ カスタムCLIコマンドの登録 ▼▼▼
    from . import manage_commands # 新しく作成する manage_commands.py をインポート
    if hasattr(manage_commands, 'register_commands'): # register_commands 関数が存在するか確認
        manage_commands.register_commands(app)
        app.logger.info("Registered custom CLI commands from manage_commands.")
    else:
        app.logger.warning("manage_commands.py found, but no register_commands function was present or an error occurred during import.")
    # ▲▲▲ カスタムCLIコマンドの登録 ▲▲▲

    # --- デバッグ用: 登録ルートの確認 (前回追加したものは削除またはコメントアウトしました) ---
    # if app.debug or app.config['ENV'] == 'development':
    #     with app.app_context():
    #         app.logger.info("--- Registered URL Rules START ---")
    #         rules = sorted(list(app.url_map.iter_rules()), key=lambda rule: str(rule))
    #         for rule in rules:
    #             app.logger.info(f"Endpoint: {rule.endpoint}, Methods: {','.join(rule.methods)}, Rule: {str(rule)}")
    #         app.logger.info("--- Registered URL Rules END ---")

    return app