# motopuppu/manage_commands.py
import click
from flask.cli import with_appcontext
from decimal import Decimal
# ▼▼▼ SQLAlchemyのjoinedloadをインポート ▼▼▼
from sqlalchemy.orm import joinedload
# ▲▲▲ インポートここまで ▲▲▲

from . import db
# ▼▼▼ モデルのインポートを修正 ▼▼▼
from .models import (
    User, AchievementDefinition, UserAchievement, ActivityLog, SessionLog,
    Motorcycle, FuelEntry, OdoResetLog
)
from sqlalchemy import asc
# ▲▲▲ 修正ここまで ▲▲▲
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

            # この部分はダミーです。実際のプロジェクトでは achievement_evaluator.py のロジックを呼び出します。
            # if evaluate_achievement_condition_for_backfill(user, ach_def):
            #     try:
            #         new_unlock = UserAchievement(user_id=user.id, achievement_code=ach_def.code)
            #         db.session.add(new_unlock)
            #         db.session.commit()
            #         unlocked_count_total += 1
            #         click.echo(f"  SUCCESS: Unlocked '{ach_def.name}' for user {user.id}")
            #     except IntegrityError:
            #         db.session.rollback()
            #         click.echo(f"  INFO: Achievement '{ach_def.name}' for user {user.id} was likely already unlocked (IntegrityError).")
            #     except Exception as e:
            #         db.session.rollback()
            #         click.echo(f"  ERROR: Failed to unlock '{ach_def.name}' for user {user.id}: {e}")

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


# ▼▼▼ 既存のコマンド ▼▼▼
@click.command('recalculate-total-distance')
@with_appcontext
@click.option('--motorcycle-id', required=True, type=int, help='Total distanceを再計算する車両のID。')
@click.option('--dry-run', is_flag=True, help='実際にはDBを更新せず、実行結果のプレビューのみ表示します。')
def recalculate_total_distance_command(motorcycle_id, dry_run):
    """
    指定された車両の全給油記録について、ODOリセットログを元にtotal_distanceを再計算します。
    """
    motorcycle = Motorcycle.query.get(motorcycle_id)
    if not motorcycle:
        click.echo(f"エラー: ID={motorcycle_id} の車両が見つかりません。")
        return

    click.echo(f"車両 '{motorcycle.name}' (ID: {motorcycle_id}) の total_distance を再計算します。")
    if dry_run:
        click.echo(click.style("--- ドライランモードで実行中（DBは更新されません）---", fg='yellow'))

    # 全給油記録と全ODOリセットログを日付順で取得
    fuel_entries = FuelEntry.query.filter_by(motorcycle_id=motorcycle_id).order_by(asc(FuelEntry.entry_date), asc(FuelEntry.id)).all()
    odo_resets = OdoResetLog.query.filter_by(motorcycle_id=motorcycle_id).order_by(asc(OdoResetLog.reset_date)).all()

    if not fuel_entries:
        click.echo("この車両には給油記録がありません。")
        return

    cumulative_offset = 0
    reset_idx = 0

    for entry in fuel_entries:
        # この給油記録の日付までに発生したODOリセットのオフセットをすべて加算
        while reset_idx < len(odo_resets) and odo_resets[reset_idx].reset_date <= entry.entry_date:
            cumulative_offset += odo_resets[reset_idx].offset_increment
            reset_idx += 1

        new_total_distance = entry.odometer_reading + cumulative_offset

        if entry.total_distance != new_total_distance:
            click.echo(
                f"ID: {entry.id}, 日付: {entry.entry_date}, "
                f"ODO: {entry.odometer_reading}, "
                f"旧 total_distance: {click.style(str(entry.total_distance), fg='red')}, "
                f"新 total_distance: {click.style(str(new_total_distance), fg='green')}"
            )
            if not dry_run:
                entry.total_distance = new_total_distance
        else:
            click.echo(
                 f"ID: {entry.id}, 日付: {entry.entry_date} - total_distanceは正常です ({entry.total_distance})。"
            )

    if not dry_run:
        try:
            db.session.commit()
            click.echo(click.style("データベースの更新が完了しました。", fg='green'))
        except Exception as e:
            db.session.rollback()
            click.echo(click.style(f"エラーが発生しました: {e}", fg='red'))
    else:
        click.echo(click.style("--- ドライランが終了しました ---", fg='yellow'))
# ▲▲▲ 既存のコマンドここまで ▲▲▲


# ▼▼▼▼▼ この新しいコマンドを、既存のコマンド定義の後に追加してください ▼▼▼▼▼
@click.command('check-abnormal-mileage')
@with_appcontext
@click.option('--threshold', default=100.0, type=float, help='異常と判定する燃費の閾値 (km/L)。')
@click.option('--user-id', default=None, type=int, help='特定のユーザーIDに対して実行（省略時は全ユーザー）')
def check_abnormal_mileage_command(threshold, user_id):
    """
    異常な燃費が記録されている給油記録を検出し、関連情報を表示します。
    ODOリセットのオフセットが正しく反映されていない古いデータが原因で、
    走行距離が過大に計算されている記録を特定するために使用します。
    """
    click.echo(f"--- 異常燃費記録のチェックを開始します (閾値: {threshold} km/L) ---")

    query = FuelEntry.query.join(Motorcycle).filter(
        Motorcycle.is_racer == False
    ).options(
        joinedload(FuelEntry.motorcycle).joinedload(Motorcycle.owner)
    ).order_by(
        Motorcycle.user_id, FuelEntry.motorcycle_id, FuelEntry.entry_date
    )

    if user_id:
        query = query.filter(Motorcycle.user_id == user_id)
        click.echo(f"対象ユーザー: ID={user_id}")

    all_fuel_entries = query.all()

    abnormal_count = 0

    click.echo(f"チェック対象の給油記録: {len(all_fuel_entries)} 件")
    click.echo("-" * 40)

    for entry in all_fuel_entries:
        # entry.km_per_liter はプロパティなので、ここで計算が実行される
        kpl = entry.km_per_liter

        # 閾値を超えた場合、または計算結果が0以下の非現実的な値の場合を異常と判定
        if kpl is not None and (kpl > threshold or kpl <= 0):
            abnormal_count += 1

            click.echo(click.style(f"\n▼▼▼ 異常な燃費を検出しました #{abnormal_count} ▼▼▼", fg='red', bold=True))
            click.echo(f"  ユーザー          : {entry.motorcycle.owner.misskey_username} (ID: {entry.motorcycle.owner.id})")
            click.echo(f"  車両              : {entry.motorcycle.name} (ID: {entry.motorcycle.id})")
            click.echo("-" * 20)

            # 異常値となった今回の給油記録
            click.echo(click.style("  [今回の給油記録]", fg='yellow'))
            click.echo(f"    - 給油記録ID    : {entry.id}")
            click.echo(f"    - 日付          : {entry.entry_date}")
            click.echo(f"    - ODOメーター   : {entry.odometer_reading:,} km")
            click.echo(f"    - total_distance: {click.style(str(entry.total_distance), fg='magenta')}")
            click.echo(f"    - 給油量        : {entry.fuel_volume} L")
            click.echo(f"    - 計算された燃費: {click.style(f'{kpl:.2f} km/L', fg='red', bold=True)}")

            # 燃費計算の基準となった前回の給油記録を探す
            # models.pyのkm_per_literプロパティと同じロジックで取得
            prev_entry = FuelEntry.query.filter(
                FuelEntry.motorcycle_id == entry.motorcycle_id,
                FuelEntry.total_distance < entry.total_distance,
                FuelEntry.is_full_tank == True
            ).order_by(FuelEntry.total_distance.desc()).first()

            if prev_entry:
                distance_diff = entry.total_distance - prev_entry.total_distance
                click.echo(click.style("  [計算に使われた前回の給油記録]", fg='yellow'))
                click.echo(f"    - 給油記録ID    : {prev_entry.id}")
                click.echo(f"    - 日付          : {prev_entry.entry_date}")
                click.echo(f"    - ODOメーター   : {prev_entry.odometer_reading:,} km")
                click.echo(f"    - total_distance: {click.style(str(prev_entry.total_distance), fg='magenta')}")
                click.echo(f"  計算された走行距離: {click.style(f'{distance_diff:,} km', fg='magenta', bold=True)} ({entry.total_distance} - {prev_entry.total_distance})")
            else:
                click.echo(click.style("  [計算に使われた前回の給油記録が見つかりません]", fg='yellow'))

            # 原因究明のため、該当車両のODOリセット履歴も表示
            odo_resets = OdoResetLog.query.filter_by(motorcycle_id=entry.motorcycle.id).order_by(OdoResetLog.reset_date.asc()).all()
            if odo_resets:
                click.echo(click.style("  [車両のODOリセット履歴]", fg='cyan'))
                for reset_log in odo_resets:
                    click.echo(
                        f"    - {reset_log.reset_date}: ODO {reset_log.display_odo_before_reset} -> {reset_log.display_odo_after_reset}, "
                        f"オフセット増加量: +{reset_log.offset_increment}"
                    )
            else:
                click.echo(click.style("  [車両にODOリセット履歴はありません]", fg='cyan'))

            click.echo(click.style("▲" * 25, fg='red', bold=True))

    if abnormal_count == 0:
        click.echo(click.style("\nチェック完了: 異常な燃費記録は見つかりませんでした。", fg='green'))
    else:
        click.echo(click.style(f"\n--- チェック完了: 合計 {abnormal_count} 件の異常な記録を検出しました ---", fg='yellow', bold=True))
        click.echo("これらの記録は、`recalculate-total-distance --motorcycle-id [ID]` コマンドで total_distance を修正することで、正常な燃費に再計算される可能性があります。")

# ▲▲▲▲▲ ここまで追加 ▲▲▲▲▲


# --- アプリケーションへのコマンド登録 ---
def register_commands(app):
    """FlaskアプリケーションインスタンスにCLIコマンドを登録する"""
    app.cli.add_command(backfill_achievements_command)
    app.cli.add_command(migrate_activity_data_command)
    # ▼▼▼ 既存のコマンド登録を修正 ▼▼▼
    app.cli.add_command(recalculate_total_distance_command)
    # ▲▲▲ 登録ここまで ▲▲▲
    # ▼▼▼ 新しいコマンドを登録 ▼▼▼
    app.cli.add_command(check_abnormal_mileage_command)
    # ▲▲▲ 登録ここまで ▲▲▲