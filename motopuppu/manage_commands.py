# motopuppu/manage_commands.py
import click
from flask.cli import with_appcontext
from decimal import Decimal

from . import db
from .models import User, AchievementDefinition, UserAchievement, ActivityLog, SessionLog
from .achievement_evaluator import evaluate_achievement_condition_for_backfill
from sqlalchemy.exc import IntegrityError
from flask import current_app
# ▼▼▼ forms.py からサーキットリストをインポート
from .forms import JAPANESE_CIRCUITS


# --- データ移行用のヘルパー関数 ---
def parse_time_to_seconds(time_str):
    """ "M:S.f" 形式の文字列を秒(Decimal)に変換 """
    if not isinstance(time_str, str): return None
    try:
        parts = time_str.split(':')
        seconds = Decimal(0)
        if len(parts) == 2:
            seconds += Decimal(parts[0]) * 60
            seconds += Decimal(parts[1])
        else:
            seconds += Decimal(parts[0])
        return seconds
    except (ValueError, TypeError):
        return None

# --- CLIコマンドの定義 ---

@click.command("backfill-achievements")
@with_appcontext # アプリケーションコンテキスト内で実行するために必要
@click.option('--user-id', default=None, type=int, help='特定のユーザーIDに対して実行（省略時は全ユーザー）')
def backfill_achievements_command(user_id):
    """既存ユーザーに対して実績を遡及的に評価・解除します。"""
    click.echo("Starting achievement backfill process...")

    if user_id:
        users_to_process = User.query.filter_by(id=user_id).all()
        if not users_to_process:
            click.echo(f"User with ID {user_id} not found.")
            return
        click.echo(f"Processing for specified user ID: {user_id}")
    else:
        users_to_process = User.query.all()
        click.echo(f"Processing all {len(users_to_process)} users...")

    all_achievement_defs = AchievementDefinition.query.all()
    if not all_achievement_defs:
        click.echo("No achievement definitions found in the database.")
        return

    unlocked_count_total = 0
    processed_users_count = 0

    for user in users_to_process:
        processed_users_count += 1
        click.echo(f"[{processed_users_count}/{len(users_to_process)}] Processing user: {user.id} ({user.misskey_username or 'Unknown'})")
        
        existing_user_achievements = {ua.achievement_code for ua in UserAchievement.query.filter_by(user_id=user.id).all()}

        for ach_def in all_achievement_defs:
            if ach_def.code in existing_user_achievements:
                continue

            if evaluate_achievement_condition_for_backfill(user, ach_def):
                try:
                    new_unlock = UserAchievement(user_id=user.id, achievement_code=ach_def.code)
                    db.session.add(new_unlock)
                    db.session.commit()
                    unlocked_count_total += 1
                    click.echo(f"  SUCCESS: Unlocked '{ach_def.name}' for user {user.id}")
                except IntegrityError:
                    db.session.rollback()
                    click.echo(f"  INFO: Achievement '{ach_def.name}' for user {user.id} was likely already unlocked (IntegrityError).")
                except Exception as e:
                    db.session.rollback()
                    click.echo(f"  ERROR: Failed to unlock '{ach_def.name}' for user {user.id}: {e}")
        
    click.echo(f"Achievement backfill process completed. Total new achievements unlocked: {unlocked_count_total}")


@click.command('migrate-activity-data')
@with_appcontext
def migrate_activity_data_command():
    """
    古い活動ログデータを新しい構造化されたフィールドに移行し、
    セッションログにベストラップタイムを計算して格納する。
    """
    click.echo("データ移行処理を開始します...")
    
    circuit_set = set(JAPANESE_CIRCUITS)
    
    activities_to_migrate = ActivityLog.query.filter(ActivityLog.activity_title == None).all()
    
    if not activities_to_migrate:
        click.echo("移行対象のデータはありませんでした。")
        return

    migrated_activities = 0
    migrated_sessions = 0

    for activity in activities_to_migrate:
        click.echo(f"ActivityLog ID: {activity.id} を処理中...")
        
        # 1. ActivityLog のデータ移行
        if activity.location_name in circuit_set:
            activity.location_type = 'circuit'
            activity.circuit_name = activity.location_name
            activity.activity_title = f"{activity.activity_date.strftime('%Y/%m/%d')} の活動"
        else:
            activity.location_type = 'custom'
            activity.activity_title = activity.location_name
            activity.custom_location = ''
        
        # 2. 関連する SessionLog のデータ移行
        for session in activity.sessions:
            if session.lap_times and isinstance(session.lap_times, list) and len(session.lap_times) > 0:
                lap_seconds = [s for s in (parse_time_to_seconds(t) for t in session.lap_times) if s is not None]
                
                if lap_seconds:
                    session.best_lap_seconds = min(lap_seconds)
                    migrated_sessions += 1

        migrated_activities += 1
    
    try:
        db.session.commit()
        click.echo("-" * 30)
        click.echo(f"成功: {migrated_activities} 件の活動ログを移行しました。")
        click.echo(f"成功: {migrated_sessions} 件のセッションログにベストラップを記録しました。")
        click.echo("データ移行処理が完了しました。")
    except Exception as e:
        db.session.rollback()
        click.echo(f"エラー: データ移行中に問題が発生しました。{e}")


# --- アプリケーションへのコマンド登録 ---
def register_commands(app):
    """FlaskアプリケーションインスタンスにCLIコマンドを登録する"""
    app.cli.add_command(backfill_achievements_command)
    app.cli.add_command(migrate_activity_data_command)