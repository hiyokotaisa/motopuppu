# motopuppu/__init__.py
import os
import datetime
import click
from flask import Flask, g
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
import logging
import subprocess

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

    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-secret-key-replace-me'),
        # ▼▼▼ 暗号化キーの読み込み設定を追記 ▼▼▼
        SECRET_CRYPTO_KEY=os.environ.get('SECRET_CRYPTO_KEY'),
        # ▲▲▲ 追記ここまで ▲▲▲
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
        ACTIVITIES_PER_PAGE = 10,
        # ▼▼▼▼▼ ここから修正 ▼▼▼▼▼
        # Google Places APIキーをFlaskのconfigに追加
        GOOGLE_PLACES_API_KEY=os.environ.get('GOOGLE_PLACES_API_KEY'),
        # ▲▲▲▲▲ ここまで修正 ▲▲▲▲▲
    )
    if app.config['SECRET_KEY'] == 'dev-secret-key-replace-me' and app.config['ENV'] != 'development':
        app.logger.warning("CRITICAL: SECRET_KEY is set to the default development value in a non-development environment. This is a security risk!")
    elif app.config['SECRET_KEY'] == 'dev-secret-key-replace-me':
        print("Warning: SECRET_KEY is set to the default development value. Set it in .env for production!")

    # ▼▼▼ 暗号化キーの存在チェックを追加 ▼▼▼
    if not app.config['SECRET_CRYPTO_KEY'] and app.config['ENV'] != 'development':
        app.logger.warning("CRITICAL: SECRET_CRYPTO_KEY is not set in a non-development environment. This is required for data encryption.")
    elif not app.config['SECRET_CRYPTO_KEY']:
        print("Warning: SECRET_CRYPTO_KEY is not set. Set it in .env for production!")
    # ▲▲▲ 追記ここまで ▲▲▲

    log_level_name = os.environ.get('LOG_LEVEL', 'INFO').upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    app.logger.setLevel(log_level)

    if not app.logger.handlers:
        stream_handler = logging.StreamHandler()
        app.logger.addHandler(stream_handler)

    app.logger.info(f"Flask logger initialized. Application log level set to: {log_level_name} ({log_level})")

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    from .utils.datetime_helpers import format_utc_to_jst_string
    app.jinja_env.filters['to_jst'] = format_utc_to_jst_string

    @app.before_request
    def load_logged_in_user_and_motorcycles():
        from .views.auth import get_current_user
        from .models import Motorcycle
        
        g.user = get_current_user()
        g.user_motorcycles = []
        if g.user:
            g.user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()

    try:
        # ▼▼▼ touring をインポートリストに追加 ▼▼▼
        from .views import auth, main, vehicle, fuel, maintenance, notes, dev_auth, leaderboard, profile, reminder, event, touring
        from .views import achievements as achievements_view
        from .views.activity import activity_bp
        # ▲▲▲ 変更ここまで ▲▲▲

        app.register_blueprint(auth.auth_bp)
        app.register_blueprint(main.main_bp)
        app.register_blueprint(vehicle.vehicle_bp)
        app.register_blueprint(fuel.fuel_bp)
        app.register_blueprint(maintenance.maintenance_bp)
        app.register_blueprint(reminder.reminder_bp)
        app.register_blueprint(notes.notes_bp)
        app.register_blueprint(achievements_view.achievements_bp)
        app.register_blueprint(leaderboard.leaderboard_bp)
        app.register_blueprint(profile.profile_bp)
        app.register_blueprint(event.event_bp)
        app.register_blueprint(activity_bp)
        
        # ▼▼▼ 新しい touring_bp を登録 ▼▼▼
        app.register_blueprint(touring.touring_bp)
        # ▲▲▲ 登録ここまで ▲▲▲

        if app.config['ENV'] == 'development' or app.debug: 
            app.register_blueprint(dev_auth.dev_auth_bp)
            app.logger.info("Registered development blueprint: dev_auth")

    except ImportError as e:
        app.logger.error(f"Error importing or registering blueprints: {e}", exc_info=True)
        print(f"Error importing or registering blueprints: {e}") 

    @app.context_processor
    def inject_global_variables():
        commit_hash_short = 'N/A'; source_info = ""
        render_commit = os.environ.get('RENDER_GIT_COMMIT')
        if render_commit:
            commit_hash_short = render_commit[:7]; source_info = "(Render Build)"
        elif app.debug: 
            try:
                project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
                commit_hash_short = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=project_root).decode('utf-8').strip()
                source_info = "(local dev)"
            except Exception:
                commit_hash_short = "N/A (git error)"; source_info = ""
        
        build_version_string = f"{commit_hash_short} {source_info}".strip()
        misskey_instance_url = app.config.get('MISSKEY_INSTANCE_URL', 'https://misskey.io')
        misskey_instance_domain = misskey_instance_url.replace('https://', '').replace('http://', '').split('/')[0].strip() or 'misskey.io'

        return {
            'current_year': datetime.datetime.now(datetime.timezone.utc).year,
            'build_version': build_version_string,
            'misskey_instance_domain': misskey_instance_domain 
        }

    @app.shell_context_processor
    def make_shell_context():
        # ▼▼▼ 新しいモデルをインポートリストと辞書に追加 ▼▼▼
        from .models import db, User, Motorcycle, FuelEntry, MaintenanceEntry, MaintenanceReminder, GeneralNote, OdoResetLog, AchievementDefinition, UserAchievement
        from .models import SettingSheet, ActivityLog, SessionLog, Event, EventParticipant, TouringLog, TouringSpot, TouringScrapbookEntry
        return {
            'db': db, 'User': User, 'Motorcycle': Motorcycle, 'FuelEntry': FuelEntry,
            'MaintenanceEntry': MaintenanceEntry, 'MaintenanceReminder': MaintenanceReminder,
            'GeneralNote': GeneralNote, 'OdoResetLog': OdoResetLog,
            'AchievementDefinition': AchievementDefinition, 'UserAchievement': UserAchievement,
            'SettingSheet': SettingSheet, 'ActivityLog': ActivityLog, 'SessionLog': SessionLog,
            'Event': Event, 'EventParticipant': EventParticipant,
            'TouringLog': TouringLog, 'TouringSpot': TouringSpot, 'TouringScrapbookEntry': TouringScrapbookEntry
        }
        # ▲▲▲ 変更ここまで ▲▲▲

    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass 

    @app.cli.command("init-db")
    def init_db_command():
        click.echo("Initializing the database tables...")
        db.create_all()
        click.echo("Initialized.")
    
    from . import manage_commands
    if hasattr(manage_commands, 'register_commands'):
        manage_commands.register_commands(app)

    return app