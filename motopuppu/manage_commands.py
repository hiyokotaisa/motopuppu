# motopuppu/manage_commands.py
import click
from flask.cli import with_appcontext
from .. import db # アプリケーションインスタンスではなく、dbオブジェクトを直接インポート
from .models import User, AchievementDefinition, UserAchievement # 必要なモデルをインポート
from .achievement_evaluator import evaluate_achievement_condition_for_backfill # 遡及評価関数
from sqlalchemy.exc import IntegrityError

# このファイルに関数を定義し、__init__.py からコマンドを登録することもできるが、
# ここでは直接 app.cli.command を使わずに、登録用の関数を用意する

def register_commands(app):
    @app.cli.command("backfill-achievements")
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
            
            # ユーザーが既に解除している実績のコードセットを取得
            existing_user_achievements = {ua.achievement_code for ua in UserAchievement.query.filter_by(user_id=user.id).all()}

            for ach_def in all_achievement_defs:
                if ach_def.code in existing_user_achievements:
                    # click.echo(f"  Skipping (already unlocked): {ach_def.name}")
                    continue

                # 遡及的な条件評価
                if evaluate_achievement_condition_for_backfill(user, ach_def):
                    try:
                        new_unlock = UserAchievement(user_id=user.id, achievement_code=ach_def.code)
                        db.session.add(new_unlock)
                        db.session.commit()
                        unlocked_count_total += 1
                        click.echo(f"  SUCCESS: Unlocked '{ach_def.name}' for user {user.id}")
                    except IntegrityError: # 主にUniqueConstraint違反 (万が一の重複時)
                        db.session.rollback()
                        click.echo(f"  INFO: Achievement '{ach_def.name}' for user {user.id} was likely already unlocked (IntegrityError).")
                    except Exception as e:
                        db.session.rollback()
                        click.echo(f"  ERROR: Failed to unlock '{ach_def.name}' for user {user.id}: {e}")
            
        click.echo(f"Achievement backfill process completed. Total new achievements unlocked: {unlocked_count_total}")