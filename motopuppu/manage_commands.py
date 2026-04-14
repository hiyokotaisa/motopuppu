# motopuppu/manage_commands.py
import click
from flask.cli import with_appcontext
from decimal import Decimal
from sqlalchemy.orm import joinedload

from . import db
from .models import (
    User, AchievementDefinition, UserAchievement, ActivityLog, SessionLog,
    Motorcycle, FuelEntry, OdoResetLog
)
from sqlalchemy import asc
from sqlalchemy.exc import IntegrityError
from flask import current_app
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


# ▼▼▼▼▼ ここから `recalculate-total-distance` コマンドを修正 ▼▼▼▼▼

def _calculate_kpl_from_simulated_data(target_entry_sim, all_entries_sim):
    """メモリ上のシミュレーションデータから燃費を計算するヘルパー関数"""
    if not target_entry_sim['is_full_tank']:
        return None

    # target_entryより前の、満タン給油記録をシミュレーションデータから探す
    prev_entry_sim = None
    for entry_sim in sorted(all_entries_sim, key=lambda x: x['total_distance'], reverse=True):
        if entry_sim['total_distance'] < target_entry_sim['total_distance'] and entry_sim['is_full_tank']:
            prev_entry_sim = entry_sim
            break

    if not prev_entry_sim:
        return None

    distance_diff = target_entry_sim['total_distance'] - prev_entry_sim['total_distance']
    fuel_consumed = target_entry_sim['fuel_volume']

    if fuel_consumed is not None and fuel_consumed > 0 and distance_diff > 0:
        try:
            return round(float(distance_diff) / float(fuel_consumed), 2)
        except (ZeroDivisionError, TypeError):
            return None
    return None

@click.command('recalculate-total-distance')
@with_appcontext
@click.option('--motorcycle-id', required=True, type=int, help='Total distanceを再計算する車両のID。')
@click.option('--dry-run', is_flag=True, help='実際にはDBを更新せず、実行結果のプレビューのみ表示します。')
def recalculate_total_distance_command(motorcycle_id, dry_run):
    """
    指定された車両の全給油記録についてtotal_distanceを再計算し、
    修正前後の燃費の変化を表示します。
    """
    motorcycle = Motorcycle.query.get(motorcycle_id)
    if not motorcycle:
        click.echo(f"エラー: ID={motorcycle_id} の車両が見つかりません。")
        return

    click.echo(f"車両 '{motorcycle.name}' (ID: {motorcycle_id}) の total_distance を再計算します。")
    if dry_run:
        click.echo(click.style("--- ドライランモードで実行中（DBは更新されません）---", fg='yellow'))

    fuel_entries = FuelEntry.query.filter_by(motorcycle_id=motorcycle_id).order_by(asc(FuelEntry.entry_date), asc(FuelEntry.id)).all()
    odo_resets = OdoResetLog.query.filter_by(motorcycle_id=motorcycle_id).order_by(asc(OdoResetLog.reset_date)).all()

    if not fuel_entries:
        click.echo("この車両には給油記録がありません。")
        return

    # 1. 修正前の燃費(kpl)を計算して保存
    original_kpls = {entry.id: entry.km_per_liter for entry in fuel_entries}

    # 2. メモリ上で新しいtotal_distanceをシミュレーション
    simulated_entries = []
    cumulative_offset = 0
    reset_idx = 0
    for entry in fuel_entries:
        while reset_idx < len(odo_resets) and odo_resets[reset_idx].reset_date <= entry.entry_date:
            cumulative_offset += odo_resets[reset_idx].offset_increment
            reset_idx += 1

        new_total_distance = entry.odometer_reading + cumulative_offset
        simulated_entries.append({
            'id': entry.id,
            'entry_date': entry.entry_date,
            'odometer_reading': entry.odometer_reading,
            'original_total_distance': entry.total_distance,
            'total_distance': new_total_distance, # これが新しい値
            'fuel_volume': entry.fuel_volume,
            'is_full_tank': entry.is_full_tank
        })

    # 3. シミュレーションデータを使って、修正後の燃費を計算
    new_kpls = {}
    for sim_entry in simulated_entries:
        new_kpls[sim_entry['id']] = _calculate_kpl_from_simulated_data(sim_entry, simulated_entries)

    # 4. 結果を表示し、必要であればDBを更新
    click.echo("-" * 60)
    for i, entry in enumerate(fuel_entries):
        sim_data = simulated_entries[i]
        original_kpl = original_kpls.get(entry.id)
        new_kpl = new_kpls.get(entry.id)

        original_kpl_str = f"{original_kpl:.2f}" if original_kpl is not None else "N/A"
        new_kpl_str = f"{new_kpl:.2f}" if new_kpl is not None else "N/A"

        click.echo(f"ID: {entry.id}, 日付: {entry.entry_date}, ODO: {entry.odometer_reading}")

        # total_distance の変更を表示
        if sim_data['original_total_distance'] != sim_data['total_distance']:
            click.echo(
                f"  total_distance: "
                f"{click.style(str(sim_data['original_total_distance']), fg='red')} -> "
                f"{click.style(str(sim_data['total_distance']), fg='green')}"
            )
        else:
            click.echo(f"  total_distance: {sim_data['total_distance']} (変更なし)")

        # 燃費の変更を表示
        if original_kpl_str != new_kpl_str:
             click.echo(
                f"  燃費 (km/L)   : "
                f"{click.style(original_kpl_str, fg='red')} -> "
                f"{click.style(new_kpl_str, fg='green')}"
            )
        else:
             click.echo(f"  燃費 (km/L)   : {new_kpl_str} (変更なし)")

        click.echo("-" * 20)


        # DB更新（ドライランでない場合）
        if not dry_run:
            entry.total_distance = sim_data['total_distance']

    if not dry_run:
        try:
            db.session.commit()
            click.echo(click.style("\nデータベースの更新が完了しました。", fg='green', bold=True))
        except Exception as e:
            db.session.rollback()
            click.echo(click.style(f"\nエラーが発生しました: {e}", fg='red'))
    else:
        click.echo(click.style("\n--- ドライランが終了しました ---", fg='yellow', bold=True))


# ▲▲▲▲▲ `recalculate-total-distance` コマンドの修正ここまで ▲▲▲▲▲

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
                # ▼▼▼ ここを修正しました ▼▼▼
                click.echo(f"    - 日付          : {prev_entry.entry_date}")
                # ▲▲▲ 修正ここまで ▲▲▲
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

# ▼▼▼▼▼ 新しいコマンドをここに追加 ▼▼▼▼▼
@click.command('dump-user-fuel-data')
@with_appcontext
@click.option('--user-id', required=True, type=int, help='データをダンプするユーザーのID。')
def dump_user_fuel_data_command(user_id):
    """
    指定されたユーザーの全給油関連データ（車両、ODOリセット、給油記録）を
    デバッグ目的で時系列に表示します。
    """
    user = User.query.get(user_id)
    if not user:
        click.echo(click.style(f"エラー: ユーザーID {user_id} が見つかりません。", fg='red'))
        return

    click.echo("=" * 60)
    click.echo(click.style(f"ユーザー: {user.misskey_username} (ID: {user.id}) の給油データをダンプします。", fg='cyan', bold=True))
    click.echo("=" * 60)

    # 燃費記録の対象となる公道車のみを取得
    motorcycles = Motorcycle.query.filter_by(user_id=user.id, is_racer=False).all()

    if not motorcycles:
        click.echo(click.style("対象となる車両（公道車）が見つかりません。", fg='yellow'))
        return

    for motorcycle in motorcycles:
        click.echo(f"\n" + "-" * 60)
        click.echo(click.style(f"🏍️ 車両: {motorcycle.name} (ID: {motorcycle.id})", fg='green', bold=True))
        click.echo("-" * 60)

        # 1. ODOリセット履歴を表示
        click.echo(click.style("\n[ODOリセット履歴]", fg='yellow'))
        odo_resets = OdoResetLog.query.filter_by(motorcycle_id=motorcycle.id).order_by(OdoResetLog.reset_date.asc()).all()
        if odo_resets:
            for log in odo_resets:
                click.echo(
                    f"  - {log.reset_date}: ODO {log.display_odo_before_reset} -> {log.display_odo_after_reset} "
                    f"(オフセット増加: +{log.offset_increment})"
                )
        else:
            click.echo("  - 履歴なし")

        # 2. 給油記録を時系列で表示
        click.echo(click.style("\n[給油記録]", fg='yellow'))
        fuel_entries = FuelEntry.query.filter_by(motorcycle_id=motorcycle.id).order_by(FuelEntry.entry_date.asc(), FuelEntry.id.asc()).all()
        if fuel_entries:
            click.echo("  ID   | 日付       | ODO      | total_distance | 燃費 (km/L)")
            click.echo("  -----|------------|----------|----------------|-------------")
            for entry in fuel_entries:
                kpl = entry.km_per_liter
                kpl_str = f"{kpl:.2f}" if kpl is not None else "N/A"

                # 異常な燃費をハイライト
                kpl_styled_str = kpl_str
                if kpl is not None and (kpl > 100 or kpl <= 0):
                    kpl_styled_str = click.style(kpl_str, fg='red', bold=True)

                click.echo(
                    f"  {entry.id:<4} | {entry.entry_date} | {entry.odometer_reading:<8} | "
                    f"{entry.total_distance:<14} | {kpl_styled_str}"
                )
        else:
            click.echo("  - 記録なし")

    click.echo("\n" + "=" * 60)
    click.echo(click.style("ダンプが完了しました。", fg='cyan', bold=True))
    click.echo("=" * 60)
# ▲▲▲▲▲ 追加ここまで ▲▲▲▲▲

@click.command('seed-achievements')
@with_appcontext
def seed_achievements_command():
    """新しい実績定義をデータベースに追加（シード）します。"""
    click.echo("Seeding achievement definitions...")

    definitions = [
        # --- 1. マイレージ (Mileage) ---
        {
            "code": "MILEAGE_1000KM",
            "name": "週末ライダー",
            "description": "公道車で累計 1,000 km 走行。バイクとの旅はまだ始まったばかり。",
            "icon_class": "bi-speedometer",
            "category_code": "mileage",
            "category_name": "マイレージ",
            "share_text_template": "公道車で1,000km走行し、実績「週末ライダー」を解除しました！ #もとぷっぷー",
            "trigger_event_type": "add_fuel_log", # or add_maintenance_log
            "criteria": {"type": "mileage_vehicle", "value_km": 1000}
        },
        {
            "code": "MILEAGE_5000KM",
            "name": "旅のベテラン",
            "description": "公道車で累計 5,000 km 走行。日本列島縦断くらいの距離。",
            "icon_class": "bi-speedometer2",
            "category_code": "mileage",
            "category_name": "マイレージ",
            "share_text_template": "公道車で5,000km走行し、実績「旅のベテラン」を解除しました！ #もとぷっぷー",
            "trigger_event_type": "add_fuel_log",
            "criteria": {"type": "mileage_vehicle", "value_km": 5000}
        },
        {
            "code": "MILEAGE_10000KM",
            "name": "地球への第一歩",
            "description": "公道車で累計 10,000 km 走行。地球一周の1/4に到達。",
            "icon_class": "bi-globe-asia-australia",
            "category_code": "mileage",
            "category_name": "マイレージ",
            "share_text_template": "公道車で10,000km走行し、実績「地球への第一歩」を解除しました！ #もとぷっぷー",
            "trigger_event_type": "add_fuel_log",
            "criteria": {"type": "mileage_vehicle", "value_km": 10000}
        },

        # --- 2. メンテナンス (Maintenance) ---
        {
            "code": "MAINT_COUNT_10",
            "name": "アマチュア整備士",
            "description": "整備記録を10回記録。工具の扱いに慣れてきましたね。",
            "icon_class": "bi-wrench",
            "category_code": "maintenance",
            "category_name": "メンテナンス",
            "share_text_template": "整備記録10回達成！実績「アマチュア整備士」を解除しました。 #もとぷっぷー",
            "trigger_event_type": "add_maintenance_log",
            "criteria": {"type": "count", "target_model": "MaintenanceEntry", "value": 10}
        },
        {
            "code": "MAINT_COUNT_50",
            "name": "ガレージの主",
            "description": "整備記録を50回記録。手の油汚れは勲章です。",
            "icon_class": "bi-tools",
            "category_code": "maintenance",
            "category_name": "メンテナンス",
            "share_text_template": "整備記録50回達成！実績「ガレージの主」を解除しました。 #もとぷっぷー",
            "trigger_event_type": "add_maintenance_log",
            "criteria": {"type": "count", "target_model": "MaintenanceEntry", "value": 50}
        },
        {
            "code": "MAINT_OIL_5",
            "name": "オイル交換マニア",
            "description": "オイル交換を5回記録。エンジンも喜んでいます。",
            "icon_class": "bi-droplet-half",
            "category_code": "maintenance",
            "category_name": "メンテナンス",
            "share_text_template": "オイル交換5回達成！実績「オイル交換マニア」を解除しました。 #もとぷっぷー",
            "trigger_event_type": "add_maintenance_log",
            # 注意: achievement_evaluator で criteria['type'] == 'count_by_category' などの対応が必要
            # 今回は簡易的に通常の整備回数ロジックを使用せず、evaluatorを拡張する必要があるが、
            # Planに基づきシンプルに「回数」として実装し、evaluator側でcategory判定を追加する。
            "criteria": {"type": "count_maintenance_category", "category_keyword": "オイル", "value": 5}
        },

        # --- 3. アクティビティ/サーキット (Activity) ---
        {
            "code": "CIRCUIT_COUNT_5",
            "name": "サーキットの狼",
            "description": "サーキット走行を5回記録。レコードラインが見えてきた？",
            "icon_class": "bi-flag",
            "category_code": "activity",
            "category_name": "アクティビティ",
            "share_text_template": "サーキット走行5回達成！実績「サーキットの狼」を解除しました。 #もとぷっぷー",
            "trigger_event_type": "add_activity_log",
            "criteria": {"type": "count_circuit_activity", "value": 5}
        },
        {
            "code": "CIRCUIT_COUNT_20",
            "name": "トラックマスター",
            "description": "サーキット走行を20回記録。サーキットが実家のような安心感。",
            "icon_class": "bi-trophy",
            "category_code": "activity",
            "category_name": "アクティビティ",
            "share_text_template": "サーキット走行20回達成！実績「トラックマスター」を解除しました。 #もとぷっぷー",
            "trigger_event_type": "add_activity_log",
            "criteria": {"type": "count_circuit_activity", "value": 20}
        },

        # --- 4. ユーモア/ファン (Fun) ---
        {
            "code": "FUEL_COUNT_50",
            "name": "ガソスタの常連",
            "description": "給油記録を50回記録。店員さんに顔を覚えられているかも。",
            "icon_class": "bi-fuel-pump",
            "category_code": "fun",
            "category_name": "ユーモア",
            "share_text_template": "給油記録50回達成！実績「ガソスタの常連」を解除しました。 #もとぷっぷー",
            "trigger_event_type": "add_fuel_log",
            "criteria": {"type": "count", "target_model": "FuelEntry", "value": 50}
        },
        {
            "code": "NOTE_COUNT_10",
            "name": "メモ魔",
            "description": "ノート/タスクを10回記録。忘却とは無縁のライダー。",
            "icon_class": "bi-journal-text",
            "category_code": "fun",
            "category_name": "ユーモア",
            "share_text_template": "ノート記録10回達成！実績「メモ魔」を解除しました。 #もとぷっぷー",
            "trigger_event_type": "add_note",
            "criteria": {"type": "count", "target_model": "GeneralNote", "value": 10}
        },
        {
            "code": "VEHICLE_COUNT_3",
            "name": "コレクター",
            "description": "車両を3台登録。体は一つしかありませんよ？",
            "icon_class": "bi-collection",
            "category_code": "fun",
            "category_name": "ユーモア",
            "share_text_template": "3台目の所有バイク登録！実績「コレクター」を解除しました。 #もとぷっぷー",
            "trigger_event_type": "add_vehicle",
            "criteria": {"type": "vehicle_count", "value": 3}
        }
    ]

    added_count = 0
    updated_count = 0

    for data in definitions:
        achievement = AchievementDefinition.query.filter_by(code=data['code']).first()
        if not achievement:
            achievement = AchievementDefinition(
                code=data['code'],
                name=data['name'],
                description=data['description'],
                icon_class=data['icon_class'],
                category_code=data['category_code'],
                category_name=data['category_name'],
                share_text_template=data['share_text_template'],
                trigger_event_type=data['trigger_event_type'],
                criteria=data['criteria']
            )
            db.session.add(achievement)
            added_count += 1
            click.echo(f"  [NEW] Added: {data['name']} ({data['code']})")
        else:
            # 既存項目の更新 (説明や条件のアップデート)
            achievement.name = data['name']
            achievement.description = data['description']
            achievement.icon_class = data['icon_class']
            achievement.category_code = data['category_code']
            achievement.category_name = data['category_name']
            achievement.share_text_template = data['share_text_template']
            achievement.trigger_event_type = data['trigger_event_type']
            achievement.criteria = data['criteria']
            updated_count += 1
            click.echo(f"  [UPD] Updated: {data['name']} ({data['code']})")

    try:
        db.session.commit()
        click.echo(f"Finished. Added: {added_count}, Updated: {updated_count}")
    except Exception as e:
        db.session.rollback()
        click.echo(f"Error seeding achievements: {e}")

@click.command('list-achievements')
@with_appcontext
def list_achievements_command():
    """現在DBに登録されている全ての実績定義をリスト表示します。"""
    defs = AchievementDefinition.query.order_by(AchievementDefinition.code).all()
    click.echo(f"Found {len(defs)} achievement definitions:")
    for d in defs:
        click.echo(f"Code: {d.code:<30} Name: {d.name}")

@click.command('merge-duplicate-achievements')
@with_appcontext
@click.command('merge-duplicate-achievements')
@with_appcontext
@click.option('--dry-run', is_flag=True, help='実際にはDBを更新せず、実行結果のプレビューのみ表示します。')
def merge_duplicate_achievements_command(dry_run):
    """
    重複または類似した古い実績定義を新しい実績定義に統合します。
    古い実績を解除済みのユーザーは、新しい実績を解除済みに移行され、古いデータは削除されます。
    """
    click.echo("Starting achievement merge process...")

    # 旧コード -> 新コード のマッピング
    merge_map = {
        # メンテナンス
        'MAINT_LOG_COUNT_10': 'MAINT_COUNT_10',
        'MAINT_LOG_COUNT_50': 'MAINT_COUNT_50',
        'MAINT_LOG_COUNT_100': 'MAINT_COUNT_50', # 100回は50回に丸める（新しい定義に100がないため）
        # 給油
        'FUEL_LOG_COUNT_50': 'FUEL_COUNT_50',
        'FUEL_LOG_COUNT_100': 'FUEL_COUNT_50', # 100回は50回に丸める
        # マイレージ
        'MILEAGE_VEHICLE_1000KM': 'MILEAGE_1000KM',
        'MILEAGE_VEHICLE_10000KM': 'MILEAGE_10000KM',
        # 'MILEAGE_VEHICLE_100000KM' # 10万キロは該当なし、残す
    }
    
    # マッピングにはないが、削除したい古い実績があればここに追加
    # delete_codes = []

    for old_code, new_code in merge_map.items():
        click.echo(f"\nProcessing merge: {old_code} -> {new_code}")
        
        old_def = AchievementDefinition.query.filter_by(code=old_code).first()
        new_def = AchievementDefinition.query.filter_by(code=new_code).first()
        
        if not old_def:
            click.echo(f"  Old definition '{old_code}' not found. Skipping.")
            continue
        if not new_def:
            click.echo(f"  New definition '{new_code}' not found. Skipping. (Please run seed-achievements first)")
            continue

        # この古い実績を解除している全ユーザー実績を取得
        old_unlocks = UserAchievement.query.filter_by(achievement_code=old_code).all()
        
        click.echo(f"  Found {len(old_unlocks)} user unlocks for '{old_code}'.")

        for ua in old_unlocks:
            user_id = ua.user_id
            
            # すでに新しい実績を持っているか確認
            existing_new_unlock = UserAchievement.query.filter_by(user_id=user_id, achievement_code=new_code).first()
            
            if existing_new_unlock:
                # 両方持っている -> 古い方を削除するだけでOK
                if not dry_run:
                    db.session.delete(ua)
                click.echo(f"    User {user_id}: Already has new achievement. Marking old one for deletion.")
            else:
                # 新しい方を持っていない -> 古い方を新しいコードに書き換える (解除日時は維持)
                if not dry_run:
                    ua.achievement_code = new_code
                    # セッション上のリレーション整合性を保つため、フラッシュしてDB反映を確実にする
                    db.session.add(ua) 
                click.echo(f"    User {user_id}: Migrating unlock record to '{new_code}'.")

        # 変更を一旦フラッシュして、uaが古い定義を参照しなくなったことをDBに伝える
        if not dry_run:
            db.session.flush()

        # 旧定義自体の削除
        if not dry_run:
            # リレーションのリロードを防ぐため、クエリで直接削除を試みるか、
            # あるいは flush 後なので delete(old_def) でも通るはずだが、念の為
            db.session.delete(old_def)
        click.echo(f"  Marking definition '{old_code}' for deletion.")

    if dry_run:
        click.echo(click.style("\n--- Dry run finished. No changes made. ---", fg='yellow'))
    else:
        try:
            db.session.commit()
            click.echo(click.style("\n--- Merge completed successfully. ---", fg='green', bold=True))
        except Exception as e:
            db.session.rollback()
            click.echo(click.style(f"\nError during commit: {e}", fg='red'))

@click.command('post-upcoming-events')
@with_appcontext
@click.option('--dry-run', is_flag=True, help='実際には投稿せず、投稿内容をプレビューします。')
def post_upcoming_events_command(dry_run):
    """直近の公開イベントをMisskey公式アカウントで段階的に告知投稿します。"""
    from .misskey_bot import post_upcoming_events
    result = post_upcoming_events(dry_run=dry_run)
    if result.get('error'):
        raise SystemExit(1)


@click.command('post-leaderboard-records')
@with_appcontext
@click.option('--dry-run', is_flag=True, help='実際には投稿せず、投稿内容をプレビューします。')
def post_leaderboard_records_command(dry_run):
    """リーダーボードの新コースレコードをMisskey公式アカウントで告知投稿します。"""
    from .misskey_bot import post_leaderboard_records
    result = post_leaderboard_records(dry_run=dry_run)
    if result.get('error'):
        raise SystemExit(1)


@click.command('post-misskey-bot')
@with_appcontext
@click.option('--dry-run', is_flag=True, help='実際には投稿せず、投稿内容をプレビューします。')
def post_misskey_bot_command(dry_run):
    """Misskey Bot の全自動投稿を実行します（イベント告知 + リーダーボード通知）。
    Render Cron Job からはこのコマンドを使用してください。"""
    from .misskey_bot import post_upcoming_events, post_leaderboard_records

    click.echo('=== 1. イベント告知 ===')
    event_result = post_upcoming_events(dry_run=dry_run)

    click.echo('\n=== 2. リーダーボード新記録通知 ===')
    record_result = post_leaderboard_records(dry_run=dry_run)

    if event_result.get('error') or record_result.get('error'):
        raise SystemExit(1)


# --- アプリケーションへのコマンド登録 ---
def register_commands(app):
    """FlaskアプリケーションインスタンスにCLIコマンドを登録する"""
    app.cli.add_command(backfill_achievements_command)
    app.cli.add_command(migrate_activity_data_command)
    app.cli.add_command(recalculate_total_distance_command)
    app.cli.add_command(check_abnormal_mileage_command)
    # ▼▼▼ 新しいコマンドを登録 ▼▼▼
    app.cli.add_command(dump_user_fuel_data_command)
    app.cli.add_command(seed_achievements_command)
    app.cli.add_command(list_achievements_command)
    app.cli.add_command(merge_duplicate_achievements_command)
    app.cli.add_command(post_upcoming_events_command)
    app.cli.add_command(post_leaderboard_records_command)
    app.cli.add_command(post_misskey_bot_command)
    # ▲▲▲ 登録ここまで ▲▲▲