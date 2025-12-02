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
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager, current_user

dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
    print("Loaded environment variables from .env")
else:
    print(f"Warning: .env file not found at {dotenv_path}")

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()
login_manager = LoginManager()
# ログインページへのリダイレクト先エンドポイントを修正
login_manager.login_view = 'auth.login'
login_manager.login_message = 'このページにアクセスするにはログインが必要です。'
login_manager.login_message_category = 'warning'

def user_or_ip_key():
    if current_user.is_authenticated:
        return str(current_user.id)
    return get_remote_address()

limiter = Limiter(key_func=user_or_ip_key)

def create_app(config_name=None):
    """Flaskアプリケーションインスタンスを作成するファクトリ関数"""
    app = Flask(__name__, instance_relative_config=True)

    # ▼▼▼ 修正: MAX_CONTENT_LENGTHのデフォルト値を 16 から 64 に変更 ▼▼▼
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-secret-key-replace-me'),
        SECRET_CRYPTO_KEY=os.environ.get('SECRET_CRYPTO_KEY'),
        SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URI', f"sqlite:///{os.path.join(app.instance_path, 'app.db')}"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 64)) * 1024 * 1024,
        MISSKEY_INSTANCE_URL=os.environ.get('MISSKEY_INSTANCE_URL', 'https://misskey.io'),
        LOCAL_ADMIN_USERNAME=os.environ.get('LOCAL_ADMIN_USERNAME'),
        LOCAL_ADMIN_PASSWORD=os.environ.get('LOCAL_ADMIN_PASSWORD'),
        ENV=os.environ.get('FLASK_ENV', 'production'),
        LOCAL_DEV_USER_ID=os.environ.get('LOCAL_DEV_USER_ID'),
        FUEL_ENTRIES_PER_PAGE = int(os.environ.get('FUEL_ENTRIES_PER_PAGE', 20)),
        MAINTENANCE_ENTRIES_PER_PAGE = int(os.environ.get('MAINTENANCE_ENTRIES_PER_PAGE', 20)),
        NOTES_PER_PAGE = int(os.environ.get('NOTES_PER_PAGE', 20)),
        ACTIVITIES_PER_PAGE = 10,
        GOOGLE_PLACES_API_KEY=os.environ.get('GOOGLE_PLACES_API_KEY'),
        REMEMBER_COOKIE_SAMESITE='Lax',
        REMEMBER_COOKIE_SECURE=True if os.environ.get('FLASK_ENV') == 'production' else False,
        GOOGLE_MAPS_API_KEY=os.environ.get('GOOGLE_PLACES_API_KEY')
    )
    # ▲▲▲ 修正ここまで ▲▲▲

    if app.config['SECRET_KEY'] == 'dev-secret-key-replace-me' and app.config['ENV'] != 'development':
        app.logger.warning("CRITICAL: SECRET_KEY is set to the default development value in a non-development environment. This is a security risk!")
    elif app.config['SECRET_KEY'] == 'dev-secret-key-replace-me':
        print("Warning: SECRET_KEY is set to the default development value. Set it in .env for production!")

    if not app.config['SECRET_CRYPTO_KEY'] and app.config['ENV'] != 'development':
        app.logger.warning("CRITICAL: SECRET_CRYPTO_KEY is not set in a non-development environment. This is required for data encryption.")
    elif not app.config['SECRET_CRYPTO_KEY']:
        print("Warning: SECRET_CRYPTO_KEY is not set. Set it in .env for production!")

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
    login_manager.init_app(app)
    limiter.init_app(app)

    from .utils.datetime_helpers import format_utc_to_jst_string, to_user_localtime
    app.jinja_env.filters['to_jst'] = format_utc_to_jst_string
    app.jinja_env.filters['user_localtime'] = to_user_localtime

    def format_number_filter(value):
        """数値を3桁区切りの文字列にフォーマットするJinja2フィルター"""
        if value is None:
            return ''
        try:
            return f"{int(value):,}"
        except (ValueError, TypeError):
            return value

    app.jinja_env.filters['format_number'] = format_number_filter

    def nl2br_filter(value):
        """改行コードを<br>タグに変換するフィルタ"""
        if not value:
            return ""
        from markupsafe import Markup
        return Markup(value.replace('\n', '<br>\n'))

    app.jinja_env.filters['nl2br'] = nl2br_filter
    
    from .models import User
    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None
    
    @app.before_request
    def load_global_g_variables():
        """
        全リクエスト共通で利用する変数をロードする。
        ナビゲーションバーの表示などに使用。
        """
        g.user_motorcycles = []
        g.user_teams = []
        if current_user.is_authenticated:
            from .models import Motorcycle, Team
            # パフォーマンス考慮: ここではナビゲーションに必要な基本情報のみを取得するのが望ましいが、
            # テンプレート側の依存関係が複雑なため、まずは標準的なクエリで取得する。
            # 重いカラム(Text型など)がある場合は defer() を検討すること。
            g.user_motorcycles = Motorcycle.query.filter_by(user_id=current_user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
            g.user_teams = current_user.teams.order_by(Team.name.asc()).all()

    try:
        # Blueprintのインポート
        from .views import auth, main, vehicle, fuel, maintenance, notes, dev_auth, leaderboard, profile, reminder, event, touring, team
        from .views import spec_sheet
        from .views import achievements as achievements_view
        from .views.activity import activity_bp
        from .views import help as help_view
        from .views import garage, search
        from .views import garage_settings
        from .views import circuit_dashboard

        # Blueprintの登録
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
        app.register_blueprint(touring.touring_bp)
        app.register_blueprint(spec_sheet.spec_sheet_bp)
        app.register_blueprint(help_view.help_bp)
        app.register_blueprint(garage.garage_bp)
        app.register_blueprint(search.search_bp)
        app.register_blueprint(garage_settings.garage_settings_bp)
        app.register_blueprint(circuit_dashboard.circuit_dashboard_bp)
        app.register_blueprint(team.team_bp)

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
            'misskey_instance_domain': misskey_instance_domain,
            'config': app.config
        }

    @app.shell_context_processor
    def make_shell_context():
        from .models import db, User, Motorcycle, FuelEntry, MaintenanceEntry, MaintenanceReminder, GeneralNote, OdoResetLog, AchievementDefinition, UserAchievement
        from .models import SettingSheet, ActivityLog, SessionLog, Event, EventParticipant, TouringLog, TouringSpot, TouringScrapbookEntry, MaintenanceSpecSheet, Team
        return {
            'db': db, 'User': User, 'Motorcycle': Motorcycle, 'FuelEntry': FuelEntry,
            'MaintenanceEntry': MaintenanceEntry, 'MaintenanceReminder': MaintenanceReminder,
            'GeneralNote': GeneralNote, 'OdoResetLog': OdoResetLog,
            'AchievementDefinition': AchievementDefinition, 'UserAchievement': UserAchievement,
            'SettingSheet': SettingSheet, 'ActivityLog': ActivityLog, 'SessionLog': SessionLog,
            'Event': Event, 'EventParticipant': EventParticipant,
            'TouringLog': TouringLog, 'TouringSpot': TouringSpot, 'TouringScrapbookEntry': TouringScrapbookEntry,
            'MaintenanceSpecSheet': MaintenanceSpecSheet, 'Team': Team
        }

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