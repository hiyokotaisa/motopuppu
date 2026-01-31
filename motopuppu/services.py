# motopuppu/services.py
from flask import current_app, url_for
from datetime import date, timedelta, datetime, timezone
from dateutil.relativedelta import relativedelta
from sqlalchemy import func, union_all, and_
from sqlalchemy.orm import joinedload
import jpholiday
import json
import math
from zoneinfo import ZoneInfo
from cryptography.fernet import Fernet

from .nyanpuppu import get_advice
from .utils.fuel_calculator import calculate_kpl_bulk
from .models import db, Motorcycle, FuelEntry, MaintenanceEntry, MaintenanceReminder, ActivityLog, GeneralNote, UserAchievement, AchievementDefinition, SessionLog, User
from .utils.lap_time_utils import format_seconds_to_time


# --- データ取得・計算ヘルパー ---

def get_latest_total_distance(motorcycle_id, offset_val):
    # ... (unchanged) ...
    latest_fuel_dist = db.session.query(db.func.max(FuelEntry.total_distance)).filter(
        FuelEntry.motorcycle_id == motorcycle_id).scalar() or 0
    latest_maint_dist = db.session.query(db.func.max(MaintenanceEntry.total_distance_at_maintenance)).filter(
        MaintenanceEntry.motorcycle_id == motorcycle_id).scalar() or 0
    return max(latest_fuel_dist, latest_maint_dist, offset_val if offset_val is not None else 0)


def calculate_average_kpl(motorcycle: Motorcycle, start_date=None, end_date=None):
    """車両の平均燃費を計算する。期間が指定されていれば、その期間で計算する。"""
    if motorcycle.is_racer:
        return None

    # 全エントリを一度に取得 (N+1対策)
    # 期間指定がある場合でも、前回の満タン給油からの消費量を計算するために
    # 少し前のデータが必要になるため、単純化して(あるいは安全策として)
    # ある程度広めに取るか、全件取得する。
    # ここでは既存ロジックの安全性と整合性を保つため、全件取得してPython側でフィルタリングする方式をとる。
    # レコード数が数千件レベルなら問題ない。
    
    query = FuelEntry.query.filter(
        FuelEntry.motorcycle_id == motorcycle.id
    ).order_by(FuelEntry.total_distance.asc())
    
    entries = query.all()
    
    if not entries:
        return None

    total_distance_sum = 0.0
    total_fuel_sum = 0.0
    
    last_full_entry = None
    accumulated_fuel = 0.0
    
    # 最初の有効な満タン給油を見つけるまでは、燃料を加算しても燃費計算には使えない
    # ただし、ロジックとしては「満タン〜満タン」の区間ごとに
    # 「走行距離」と「その間に給油した燃料の合計」を足し合わせる。
    
    for entry in entries:
        # 燃料を加算 (除外フラグがない場合)
        if not entry.exclude_from_average:
             accumulated_fuel += entry.fuel_volume
             
        if entry.is_full_tank:
            if last_full_entry:
                # 満タン〜満タンの区間が確定
                # 期間判定: 区間の終了日(entry.entry_date)が期間内かチェック
                is_within_period = True
                if start_date and entry.entry_date < start_date:
                    is_within_period = False
                if end_date and entry.entry_date > end_date:
                    is_within_period = False
                
                # 前回の満タンが除外対象でないかもチェック(既存ロジック準拠)
                if not last_full_entry.exclude_from_average and not entry.exclude_from_average:
                    if is_within_period:
                        dist_diff = entry.total_distance - last_full_entry.total_distance
                        if dist_diff > 0 and accumulated_fuel > 0:
                            total_distance_sum += dist_diff
                            total_fuel_sum += accumulated_fuel

            # 次の区間の開始点としてセット
            last_full_entry = entry
            accumulated_fuel = 0.0
        else:
            # 満タンでない場合、accumulated_fuelは維持して次へ
            pass

    if total_fuel_sum > 0 and total_distance_sum > 0:
        try:
            return round(total_distance_sum / total_fuel_sum, 2)
        except ZeroDivisionError:
            return None
    return None


# --- ダッシュボード用サービス関数 ---

def get_timeline_events(motorcycle_ids, start_date=None, end_date=None):
    """指定された車両IDリストの給油・整備記録を時系列で取得する"""
    if not motorcycle_ids:
        return []

    timeline_events = []
    is_multiple_vehicles = len(motorcycle_ids) > 1
    
    # --- 燃費の一括計算 ---
    # タイムラインに表示する対象車両のIDについて、全期間の給油記録を取得して燃費を計算する
    # ※期間フィルタがあっても、正確な燃費計算には過去の記録が必要なため全期間取得する
    # データ量が多くても、ID/Distance/Volume/IsFull だけなら軽量
    all_fuel_entries = db.session.query(
        FuelEntry.id, FuelEntry.motorcycle_id, FuelEntry.total_distance, 
        FuelEntry.fuel_volume, FuelEntry.is_full_tank
    ).filter(
        FuelEntry.motorcycle_id.in_(motorcycle_ids)
    ).order_by(FuelEntry.motorcycle_id, FuelEntry.total_distance).all()
    
    kpl_map = calculate_kpl_bulk(all_fuel_entries)

    # 1. 給油記録を取得 (N+1対策: joinedloadを追加)
    fuel_query = FuelEntry.query.options(db.joinedload(FuelEntry.motorcycle)).filter(FuelEntry.motorcycle_id.in_(motorcycle_ids))
    if start_date and end_date:
        fuel_query = fuel_query.filter(FuelEntry.entry_date.between(start_date, end_date))
    
    for entry in fuel_query.all():
        title = f"給油 ({entry.fuel_volume:.2f}L)"
        if is_multiple_vehicles:
            title = f"[{entry.motorcycle.name}] {title}"
        
        # プロパティアクセスを回避
        kpl = kpl_map.get(entry.id)
        kpl_str = f"{kpl:.2f}" if kpl is not None else "---"

        timeline_events.append({
            'type': 'fuel',
            'date': entry.entry_date,
            'id': entry.id,
            'odo': entry.odometer_reading,
            'total_dist': entry.total_distance,
            'title': title,
            'description': f"燃費: {kpl_str} km/L",
            'cost': entry.total_cost,
            'details': {
                '車両名': entry.motorcycle.name,
                '燃費': f"{kpl_str} km/L",
                '給油量': f"{entry.fuel_volume:.2f} L",
                '単価': f"{entry.price_per_liter} 円/L" if entry.price_per_liter else '---',
                '合計金額': f"{entry.total_cost:,.0f} 円" if entry.total_cost is not None else '---',
                'スタンド': entry.station_name or '未記録',
                'メモ': entry.notes or 'なし'
            },
            'edit_url': url_for('fuel.edit_fuel', entry_id=entry.id)
        })

    # 2. 整備記録を取得 (N+1対策: joinedloadを追加)
    maint_query = MaintenanceEntry.query.options(db.joinedload(MaintenanceEntry.motorcycle)).filter(MaintenanceEntry.motorcycle_id.in_(motorcycle_ids)).filter(MaintenanceEntry.category != '初期設定')
    if start_date and end_date:
        maint_query = maint_query.filter(MaintenanceEntry.maintenance_date.between(start_date, end_date))

    for entry in maint_query.all():
        title = entry.category or entry.description
        if is_multiple_vehicles:
            title = f"[{entry.motorcycle.name}] {title}"

        timeline_events.append({
            'type': 'maintenance',
            'date': entry.maintenance_date,
            'id': entry.id,
            'odo': entry.odometer_reading_at_maintenance,
            'total_dist': entry.total_distance_at_maintenance,
            'title': title,
            'description': entry.description,
            'cost': entry.total_cost,
            'details': {
                '車両名': entry.motorcycle.name,
                'カテゴリ': entry.category or '未分類',
                '内容': entry.description,
                '部品代': f"{entry.parts_cost:,.0f} 円" if entry.parts_cost is not None else '---',
                '工賃': f"{entry.labor_cost:,.0f} 円" if entry.labor_cost is not None else '---',
                '合計費用': f"{entry.total_cost:,.0f} 円" if entry.total_cost is not None else '---',
                '場所': entry.location or '未記録',
                'メモ': entry.notes or 'なし'
            },
            'edit_url': url_for('maintenance.edit_maintenance', entry_id=entry.id)
        })

    # 3. 日付(降順)、次にID(降順)でソート
    timeline_events.sort(key=lambda x: (x['date'], x['id']), reverse=True)

    return timeline_events


def get_upcoming_reminders(user_motorcycles_all, user_id):
    """メンテナンスリマインダーを取得・計算する"""
    upcoming_reminders = []
    today = date.today()

    KM_THRESHOLD_WARNING = current_app.config.get('REMINDER_KM_WARNING', 500)
    DAYS_THRESHOLD_WARNING = current_app.config.get('REMINDER_DAYS_WARNING', 14)
    KM_THRESHOLD_DANGER = current_app.config.get('REMINDER_KM_DANGER', 0)
    DAYS_THRESHOLD_DANGER = current_app.config.get('REMINDER_DAYS_DANGER', 0)

    current_public_distances = {}
    for m in user_motorcycles_all:
        if not m.is_racer:
            current_public_distances[m.id] = get_latest_total_distance(
                m.id, m.odometer_offset)

    # N+1対策: joinedloadで関連データを一括取得
    all_reminders = MaintenanceReminder.query.options(
        db.joinedload(MaintenanceReminder.motorcycle),
        db.joinedload(MaintenanceReminder.last_maintenance_entry)
    ).join(Motorcycle).filter(
        Motorcycle.user_id == user_id,
        MaintenanceReminder.is_dismissed == False,
        (MaintenanceReminder.snoozed_until == None) | (MaintenanceReminder.snoozed_until <= datetime.now(timezone.utc))
    ).all()


    for reminder in all_reminders:
        motorcycle = reminder.motorcycle
        status = 'ok'
        messages = []
        due_info_parts = []
        is_due = False

        if not motorcycle.is_racer and reminder.interval_km and reminder.last_done_km is not None:
            current_km = current_public_distances.get(motorcycle.id, 0)
            next_km_due = reminder.last_done_km + reminder.interval_km
            remaining_km = next_km_due - current_km
            due_info_parts.append(f"{next_km_due:,} km")

            if remaining_km <= KM_THRESHOLD_DANGER:
                messages.append(f"距離超過 (現在 {current_km:,} km)")
                status = 'danger'
                is_due = True
            elif remaining_km <= KM_THRESHOLD_WARNING:
                messages.append(f"あと {remaining_km:,} km")
                status = 'warning'
                is_due = True

        if reminder.interval_months and reminder.last_done_date:
            try:
                next_date_due = reminder.last_done_date + \
                    relativedelta(months=reminder.interval_months)
                remaining_days = (next_date_due - today).days
                due_info_parts.append(f"{next_date_due.strftime('%Y-%m-%d')}")
                period_status = 'ok'
                period_message = ''
                if remaining_days <= DAYS_THRESHOLD_DANGER:
                    period_status = 'danger'
                    period_message = f"期限超過"
                elif remaining_days <= DAYS_THRESHOLD_WARNING:
                    period_status = 'warning'
                    period_message = f"あと {remaining_days} 日"

                if period_status != 'ok':
                    is_due = True
                    messages.append(period_message)
                    if (period_status == 'danger') or (period_status == 'warning' and status != 'danger'):
                        status = period_status
            except Exception as e:
                current_app.logger.error(
                    f"Error calculating date reminder {reminder.id}: {e}")
                messages.append("日付計算エラー")
                status = 'warning'
                is_due = True

        if is_due:
            last_done_str = "未実施"
            last_done_odo_val = None
            
            # 表示するODO値を決定（連携記録を優先）
            if reminder.last_maintenance_entry:
                last_done_odo_val = reminder.last_maintenance_entry.odometer_reading_at_maintenance
            elif reminder.last_done_odo is not None:
                last_done_odo_val = reminder.last_done_odo

            # 表示用の文字列を生成
            if reminder.last_done_date:
                last_done_str = reminder.last_done_date.strftime('%Y-%m-%d')
                if not motorcycle.is_racer and last_done_odo_val is not None:
                    last_done_str += f" ({last_done_odo_val:,} km)"
            elif not motorcycle.is_racer and last_done_odo_val is not None:
                last_done_str = f"{last_done_odo_val:,} km"

            upcoming_reminders.append({
                'reminder_id': reminder.id,
                'motorcycle_id': motorcycle.id,
                'motorcycle_name': motorcycle.name,
                'task': reminder.task_description,
                'status': status,
                'message': ", ".join(messages) if messages else "要確認",
                'due_info': " / ".join(due_info_parts) if due_info_parts else '未設定',
                'last_done': last_done_str,
                'is_racer': motorcycle.is_racer
            })

    upcoming_reminders.sort(
        key=lambda x: (x['status'] != 'danger', x['status'] != 'warning'))
    return upcoming_reminders


def get_recent_logs(model, vehicle_ids, order_by_cols, selected_vehicle_id=None, start_date=None, end_date=None, extra_filters=None, limit=5):
    """指定されたモデルの直近ログを取得する共通関数"""
    query = model.query.options(db.joinedload(model.motorcycle)).filter(
        model.motorcycle_id.in_(vehicle_ids)
    )

    if selected_vehicle_id:
        query = query.filter(model.motorcycle_id == selected_vehicle_id)
    
    if start_date:
        # モデルに応じて日付カラムを特定
        date_column = getattr(model, 'entry_date', getattr(model, 'maintenance_date', None))
        if date_column:
            query = query.filter(date_column.between(start_date, end_date))
    
    if extra_filters:
        for f in extra_filters:
            query = query.filter(f)
            
    return query.order_by(*order_by_cols).limit(limit).all()


def get_dashboard_stats(user_motorcycles_all, user_motorcycle_ids_public, target_vehicle_for_stats=None, start_date=None, end_date=None, show_cost=True):
    """ダッシュボードの統計カード情報を計算して返す"""
    stats = {
        'primary_metric_val': 0, 'primary_metric_unit': '', 'primary_metric_label': '-',
        'is_racer_stats': False, 'average_kpl_val': None, 'average_kpl_label': '-',
        'show_cost': show_cost, # 表示モードを格納
    }
    # 表示モードに応じて初期化するキーを変更
    if show_cost:
        stats.update({'total_fuel_cost': 0, 'total_maint_cost': 0, 'cost_label': '-'})
    else:
        stats.update({'total_fuel_volume': 0, 'total_maint_count': 0, 'non_cost_label': '-'})

    if target_vehicle_for_stats:
        stats['is_racer_stats'] = target_vehicle_for_stats.is_racer
        if target_vehicle_for_stats.is_racer:
            stats['primary_metric_val'] = target_vehicle_for_stats.total_operating_hours if target_vehicle_for_stats.total_operating_hours is not None else 0
            stats['primary_metric_unit'] = '時間'
            stats['primary_metric_label'] = target_vehicle_for_stats.name
            stats['average_kpl_label'] = f"{target_vehicle_for_stats.name} (レーサー)"
            # ラベルを更新
            if show_cost:
                stats['cost_label'] = target_vehicle_for_stats.name
            else:
                stats['non_cost_label'] = target_vehicle_for_stats.name
        else: # 公道車（個別）
            vehicle_id = target_vehicle_for_stats.id
            fuel_q = db.session.query(FuelEntry.total_distance.label('distance')).filter(FuelEntry.motorcycle_id == vehicle_id)
            maint_q = db.session.query(MaintenanceEntry.total_distance_at_maintenance.label('distance')).filter(MaintenanceEntry.motorcycle_id == vehicle_id)
            if start_date:
                fuel_q = fuel_q.filter(FuelEntry.entry_date.between(start_date, end_date))
                maint_q = maint_q.filter(MaintenanceEntry.maintenance_date.between(start_date, end_date))
            
            all_distances_q = fuel_q.union_all(maint_q).subquery()
            result = db.session.query(func.max(all_distances_q.c.distance), func.min(all_distances_q.c.distance)).one_or_none()
            running_dist = 0
            if result and result[0] is not None and result[1] is not None:
                if result[0] != result[1]:
                    running_dist = float(result[0]) - float(result[1])

            stats['primary_metric_val'] = running_dist
            stats['primary_metric_unit'] = 'km'
            stats['primary_metric_label'] = target_vehicle_for_stats.name
            
            stats['average_kpl_val'] = calculate_average_kpl(target_vehicle_for_stats, start_date, end_date)
            stats['average_kpl_label'] = target_vehicle_for_stats.name

            # コスト表示/非表示に応じてクエリを分岐
            if show_cost:
                fuel_cost_q = db.session.query(func.sum(FuelEntry.total_cost)).filter(FuelEntry.motorcycle_id == vehicle_id)
                maint_cost_q = db.session.query(func.sum(func.coalesce(MaintenanceEntry.parts_cost, 0) + func.coalesce(MaintenanceEntry.labor_cost, 0))).filter(MaintenanceEntry.motorcycle_id == vehicle_id)
                if start_date:
                    fuel_cost_q = fuel_cost_q.filter(FuelEntry.entry_date.between(start_date, end_date))
                    maint_cost_q = maint_cost_q.filter(MaintenanceEntry.maintenance_date.between(start_date, end_date))

                stats['total_fuel_cost'] = fuel_cost_q.scalar() or 0
                stats['total_maint_cost'] = maint_cost_q.scalar() or 0
                stats['cost_label'] = target_vehicle_for_stats.name
            else:
                fuel_volume_q = db.session.query(func.sum(FuelEntry.fuel_volume)).filter(FuelEntry.motorcycle_id == vehicle_id)
                maint_count_q = db.session.query(func.count(MaintenanceEntry.id)).filter(MaintenanceEntry.motorcycle_id == vehicle_id)
                if start_date:
                    fuel_volume_q = fuel_volume_q.filter(FuelEntry.entry_date.between(start_date, end_date))
                    maint_count_q = maint_count_q.filter(MaintenanceEntry.maintenance_date.between(start_date, end_date))

                stats['total_fuel_volume'] = fuel_volume_q.scalar() or 0
                stats['total_maint_count'] = maint_count_q.scalar() or 0
                stats['non_cost_label'] = target_vehicle_for_stats.name
    else: # 全車両
        # 走行距離
        total_running_distance = 0
        if user_motorcycle_ids_public:
            fuel_dist_q = db.session.query(FuelEntry.motorcycle_id.label('mc_id'), FuelEntry.total_distance.label('distance')).filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids_public))
            maint_dist_q = db.session.query(MaintenanceEntry.motorcycle_id.label('mc_id'), MaintenanceEntry.total_distance_at_maintenance.label('distance')).filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids_public))
            if start_date:
                fuel_dist_q = fuel_dist_q.filter(FuelEntry.entry_date.between(start_date, end_date))
                maint_dist_q = maint_dist_q.filter(MaintenanceEntry.maintenance_date.between(start_date, end_date))

            combined_q = union_all(fuel_dist_q, maint_dist_q).subquery()
            vehicle_dists = db.session.query((func.max(combined_q.c.distance) - func.min(combined_q.c.distance)).label('travelled')).group_by(combined_q.c.mc_id).having(func.count(combined_q.c.distance) > 1).subquery()
            total_running_distance = db.session.query(func.sum(vehicle_dists.c.travelled)).scalar() or 0
        
        stats['primary_metric_val'] = total_running_distance
        stats['primary_metric_unit'] = 'km'
        stats['primary_metric_label'] = "すべての公道車"
        
        # 平均燃費
        default_vehicle = next((m for m in user_motorcycles_all if m.is_default), user_motorcycles_all[0] if user_motorcycles_all else None)
        if default_vehicle and not default_vehicle.is_racer:
            stats['average_kpl_val'] = calculate_average_kpl(default_vehicle, start_date, end_date)
            stats['average_kpl_label'] = f"デフォルト ({default_vehicle.name})"
        else:
            stats['average_kpl_label'] = "計算対象外"

        # 費用または代替情報
        if user_motorcycle_ids_public:
            if show_cost:
                fuel_cost_q = db.session.query(func.sum(FuelEntry.total_cost)).filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids_public))
                maint_cost_q = db.session.query(func.sum(func.coalesce(MaintenanceEntry.parts_cost, 0) + func.coalesce(MaintenanceEntry.labor_cost, 0))).filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids_public))
                if start_date:
                    fuel_cost_q = fuel_cost_q.filter(FuelEntry.entry_date.between(start_date, end_date))
                    maint_cost_q = maint_cost_q.filter(MaintenanceEntry.maintenance_date.between(start_date, end_date))

                stats['total_fuel_cost'] = fuel_cost_q.scalar() or 0
                stats['total_maint_cost'] = maint_cost_q.scalar() or 0
                stats['cost_label'] = "すべての公道車"
            else:
                fuel_volume_q = db.session.query(func.sum(FuelEntry.fuel_volume)).filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids_public))
                maint_count_q = db.session.query(func.count(MaintenanceEntry.id)).filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids_public))
                if start_date:
                    fuel_volume_q = fuel_volume_q.filter(FuelEntry.entry_date.between(start_date, end_date))
                    maint_count_q = maint_count_q.filter(MaintenanceEntry.maintenance_date.between(start_date, end_date))

                stats['total_fuel_volume'] = fuel_volume_q.scalar() or 0
                stats['total_maint_count'] = maint_count_q.scalar() or 0
                stats['non_cost_label'] = "すべての公道車"
        
    return stats


def get_latest_log_info_for_vehicles(motorcycles):
    """
    複数の車両について、給油記録または整備記録から最新のログ情報を1クエリで取得する。
    """
    if not motorcycles:
        return {}

    motorcycle_ids = [m.id for m in motorcycles]

    # 給油記録から必要な情報を選択
    fuel_q = db.session.query(
        FuelEntry.motorcycle_id.label('motorcycle_id'),
        FuelEntry.odometer_reading.label('odo'),
        FuelEntry.entry_date.label('log_date')
    ).filter(FuelEntry.motorcycle_id.in_(motorcycle_ids))

    # 整備記録から必要な情報を選択
    maint_q = db.session.query(
        MaintenanceEntry.motorcycle_id.label('motorcycle_id'),
        MaintenanceEntry.odometer_reading_at_maintenance.label('odo'),
        MaintenanceEntry.maintenance_date.label('log_date')
    ).filter(MaintenanceEntry.motorcycle_id.in_(motorcycle_ids))

    # 2つのクエリをUNIONで結合
    combined_q = union_all(fuel_q, maint_q).subquery()

    # ウィンドウ関数を使い、車両ごとに日付で降順にランク付け
    ranked_q = db.session.query(
        combined_q.c.motorcycle_id,
        combined_q.c.odo,
        combined_q.c.log_date,
        func.row_number().over(
            partition_by=combined_q.c.motorcycle_id,
            order_by=combined_q.c.log_date.desc()
        ).label('rn')
    ).subquery()

    # ランクが1のもの（＝最新の記録）のみを抽出
    latest_logs = db.session.query(
        ranked_q.c.motorcycle_id,
        ranked_q.c.odo,
        ranked_q.c.log_date
    ).filter(ranked_q.c.rn == 1).all()

    # 結果を使いやすい辞書形式に変換
    result_dict = {
        log.motorcycle_id: {'odo': log.odo, 'date': log.log_date}
        for log in latest_logs
    }
    
    return result_dict


def get_circuit_activity_for_dashboard(user_id):
    """ダッシュボードのサーキット活動ウィジェット用のデータを取得する"""
    
    # 1. サマリー統計の計算
    total_circuits = db.session.query(
        func.count(func.distinct(ActivityLog.circuit_name))
    ).filter(
        ActivityLog.user_id == user_id,
        ActivityLog.circuit_name.isnot(None)
    ).scalar() or 0

    total_sessions = db.session.query(
        func.count(SessionLog.id)
    ).join(ActivityLog).filter(
        ActivityLog.user_id == user_id
    ).scalar() or 0

    summary = {
        'total_circuits': total_circuits,
        'total_sessions': total_sessions,
    }

    # 2. 最近の活動ログ5件を取得 (N+1対策: joinedload)
    recent_activities = ActivityLog.query.options(
        joinedload(ActivityLog.motorcycle)
    ).filter(
        ActivityLog.user_id == user_id
    ).order_by(
        ActivityLog.activity_date.desc(),
        ActivityLog.created_at.desc()
    ).limit(5).all()

    # 3. 取得した活動ログのIDリストを作成
    if recent_activities:
        activity_ids = [act.id for act in recent_activities]

        # 4. 活動ログごとのベストラップ（最小のbest_lap_seconds）を1回のクエリで取得
        best_laps_query = db.session.query(
            SessionLog.activity_log_id,
            func.min(SessionLog.best_lap_seconds).label('activity_best_lap')
        ).filter(
            SessionLog.activity_log_id.in_(activity_ids),
            SessionLog.best_lap_seconds.isnot(None)
        ).group_by(
            SessionLog.activity_log_id
        ).all()

        # 高速アクセスのために結果を辞書に変換
        best_laps_map = {act_id: lap_time for act_id, lap_time in best_laps_query}

        # 5. 各活動ログオブジェクトにベストラップ情報を追加
        for activity in recent_activities:
            activity.best_lap_for_activity = best_laps_map.get(activity.id)

    # --- 追加: サーキットごとの自己ベスト (Top 5) ---
    # 回数が多いサーキット順に、そのサーキットでのベストタイムを取得
    personal_bests = []
    
    # まず、よく行くサーキットTop5を取得
    top_circuits = db.session.query(
        ActivityLog.circuit_name,
        func.count(ActivityLog.id).label('visit_count')
    ).filter(
        ActivityLog.user_id == user_id,
        ActivityLog.circuit_name.isnot(None)
    ).group_by(
        ActivityLog.circuit_name
    ).order_by(
        func.count(ActivityLog.id).desc()
    ).limit(5).all()

    for circuit_name, _ in top_circuits:
        # 各サーキットのベストタイムを取得
        best_session = db.session.query(
            SessionLog.best_lap_seconds,
            Motorcycle.name.label('vehicle_name')
        ).select_from(SessionLog).join(ActivityLog).join(Motorcycle).filter(
            ActivityLog.user_id == user_id,
            ActivityLog.circuit_name == circuit_name,
            SessionLog.best_lap_seconds.isnot(None)
        ).order_by(
            SessionLog.best_lap_seconds.asc()
        ).first()

        if best_session:
            personal_bests.append({
                'circuit_name': circuit_name,
                'best_lap': best_session.best_lap_seconds,
                'vehicle_name': best_session.vehicle_name
            })

    # --- 追加: 次回のサーキット走行予定 ---
    # ユーザー要望: イベント機能ではなく、「アクティビティ」の走行ログで将来の日付になっているものを予定として扱う
    today = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    next_circuit_event = ActivityLog.query.filter(
        ActivityLog.user_id == user_id,
        ActivityLog.activity_date >= today,
        ActivityLog.circuit_name.isnot(None)
    ).order_by(ActivityLog.activity_date.asc()).first()

    return {
        'summary': summary,
        'recent_activities': recent_activities,
        'personal_bests': personal_bests,
        'next_circuit_event': next_circuit_event
    }


def get_holidays_json():
    """祝日情報を取得し、JSON文字列として返す"""
    try:
        today_for_holiday = date.today()
        # カレンダー表示のパフォーマンスのため、前後1年分の祝日を取得
        years_to_fetch = [today_for_holiday.year - 1, today_for_holiday.year, today_for_holiday.year + 1]
        holidays_dict = {}
        for year in years_to_fetch:
            try:
                holidays_raw = jpholiday.year_holidays(year)
                for holiday_date_obj, holiday_name in holidays_raw:
                    holidays_dict[holiday_date_obj.strftime('%Y-%m-%d')] = holiday_name
            except Exception as e:
                current_app.logger.error(f"Error fetching holidays for year {year}: {e}")
        return json.dumps(holidays_dict)
    except Exception as e:
        current_app.logger.error(f"Error processing holidays data: {e}")
        return '{}' # エラーが発生した場合は空のJSONを返す


def get_calendar_events_for_user(user):
    """指定されたユーザーのカレンダーイベントをすべて取得・整形して返す"""
    events = []
    user_id = user.id
    
    # 全車両IDを取得
    user_motorcycles_all = Motorcycle.query.filter_by(user_id=user_id).all()
    user_motorcycle_ids_all = [m.id for m in user_motorcycles_all]
    
    # 公道車のみのIDリスト
    user_motorcycle_ids_public = [m.id for m in user_motorcycles_all if not m.is_racer]


    # 給油記録 (公道車のみ)
    if user_motorcycle_ids_public:
        # --- 燃費の一括計算 ---
        # カレンダー表示用にはフィルタリングがない(全件表示)ため、
        # そのまま全公道車の全記録を取得して計算する
        all_fuel_entries_for_calc = db.session.query(
            FuelEntry.id, FuelEntry.motorcycle_id, FuelEntry.total_distance, 
            FuelEntry.fuel_volume, FuelEntry.is_full_tank
        ).filter(
            FuelEntry.motorcycle_id.in_(user_motorcycle_ids_public)
        ).order_by(FuelEntry.motorcycle_id, FuelEntry.total_distance).all()
        
        kpl_map = calculate_kpl_bulk(all_fuel_entries_for_calc)

        fuel_entries = FuelEntry.query.options(db.joinedload(FuelEntry.motorcycle)).filter(
            FuelEntry.motorcycle_id.in_(user_motorcycle_ids_public)).all()
            
        for entry in fuel_entries:
            # プロパティアクセスを回避
            kpl = kpl_map.get(entry.id)
            kpl_display = f"{kpl:.2f} km/L" if kpl is not None else None
            
            edit_url = url_for('fuel.edit_fuel', entry_id=entry.id)
            events.append({
                'id': f'fuel-{entry.id}', 'title': f"⛽ 給油: {entry.motorcycle.name}",
                'start': entry.entry_date.isoformat(), 'allDay': True, 'url': edit_url,
                'backgroundColor': '#198754', 'borderColor': '#198754', 'textColor': 'white',
                'extendedProps': {
                    'type': 'fuel', 'motorcycleName': entry.motorcycle.name,
                    'odometer': entry.odometer_reading, 'fuelVolume': entry.fuel_volume, 'kmPerLiter': kpl_display,
                    'totalCost': math.ceil(entry.total_cost) if entry.total_cost is not None else None,
                    'stationName': entry.station_name, 'notes': entry.notes, 'editUrl': edit_url
                }
            })


    # 整備記録 (公道車のみ)
    if user_motorcycle_ids_public:
        maintenance_entries = MaintenanceEntry.query.options(db.joinedload(MaintenanceEntry.motorcycle)).filter(
            MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids_public),
            MaintenanceEntry.category != '初期設定'
        ).all()
        for entry in maintenance_entries:
            event_title_base = entry.category if entry.category else entry.description
            event_title = f"🔧 整備: {event_title_base[:15]}" + ("..." if len(event_title_base) > 15 else "")
            total_cost = entry.total_cost
            edit_url = url_for('maintenance.edit_maintenance', entry_id=entry.id)
            events.append({
                'id': f'maint-{entry.id}', 'title': event_title,
                'start': entry.maintenance_date.isoformat(), 'allDay': True, 'url': edit_url,
                'backgroundColor': '#ffc107', 'borderColor': '#ffc107', 'textColor': 'black',
                'extendedProps': {
                    'type': 'maintenance', 'motorcycleName': entry.motorcycle.name,
                    'odometer': entry.total_distance_at_maintenance, 'description': entry.description, 'category': entry.category,
                    'totalCost': math.ceil(total_cost) if total_cost is not None else None,
                    'location': entry.location, 'notes': entry.notes, 'editUrl': edit_url
                }
            })

    # 活動ログ (全車両対象)
    if user_motorcycle_ids_all:
        activity_logs = ActivityLog.query.options(db.joinedload(ActivityLog.motorcycle)).filter(
            ActivityLog.motorcycle_id.in_(user_motorcycle_ids_all)).all()
        for entry in activity_logs:
            location_display = entry.activity_title or entry.location_name or '活動'
            event_title = f"🏁 {location_display[:15]}" + ("..." if len(location_display) > 15 else "")
            edit_url = url_for('activity.detail_activity', activity_id=entry.id)
            
            location_details = []
            if entry.circuit_name:
                location_details.append(entry.circuit_name)
            if entry.custom_location:
                location_details.append(entry.custom_location)
            location_full_display = ", ".join(location_details) or entry.location_name or '未設定'

            events.append({
                'id': f'activity-{entry.id}', 'title': event_title,
                'start': entry.activity_date.isoformat(), 'allDay': True, 'url': edit_url,
                'backgroundColor': '#0dcaf0', 'borderColor': '#0dcaf0', 'textColor': 'black',
                'extendedProps': {
                    'type': 'activity',
                    'motorcycleName': entry.motorcycle.name,
                    'isRacer': entry.motorcycle.is_racer,
                    'activityTitle': entry.activity_title or '活動ログ',
                    'location': location_full_display,
                    'weather': entry.weather,
                    'temperature': f"{entry.temperature}°C" if entry.temperature is not None else None,
                    'notes': entry.notes,
                    'editUrl': edit_url
                }
            })

    # 一般ノート・タスク (全車両対象)
    general_notes = GeneralNote.query.options(
        db.joinedload(GeneralNote.motorcycle)).filter_by(user_id=user_id).all()
    for note in general_notes:
        motorcycle_name = note.motorcycle.name if note.motorcycle else None
        note_title_display = note.title or ('タスク' if note.category == 'task' else 'メモ')
        icon = "✅" if note.category == 'task' else "📝"
        title_prefix = f"{icon} {'タスク' if note.category == 'task' else 'メモ'}: "
        event_type = note.category
        event_title = title_prefix + note_title_display[:15] + ("..." if len(note_title_display) > 15 else "")
        edit_url = url_for('notes.edit_note', note_id=note.id)
        extended_props = {
            'type': event_type, 'category': note.category, 'title': note.title, 'motorcycleName': motorcycle_name,
            'noteDate': note.note_date.strftime('%Y-%m-%d'),
            'createdAt': note.created_at.strftime('%Y-%m-%d %H:%M'),
            'updatedAt': note.updated_at.strftime('%Y-%m-%d %H:%M'), 'editUrl': edit_url,
            'isRacer': note.motorcycle.is_racer if note.motorcycle else False
        }
        if event_type == 'task':
            extended_props['todos'] = note.todos if note.todos is not None else []
        else:
            extended_props['content'] = note.content
        events.append({
            'id': f'note-{note.id}', 'title': event_title,
            'start': note.note_date.isoformat(), 'allDay': True, 'url': edit_url,
            'backgroundColor': '#6c757d', 'borderColor': '#6c757d', 'textColor': 'white',
            'extendedProps': extended_props
        })

    return events

# --- 暗号化サービス ---

class CryptoService:
    """
    データ暗号化・復号を行うサービスクラス。
    Fernet (AES128-CBC) を使用します。
    """
    def __init__(self):
        """
        コンストラクタ。
        環境変数から暗号化キーを読み込み、Fernetインスタンスを初期化します。
        """
        key_str = current_app.config.get('SECRET_CRYPTO_KEY')
        if not key_str:
            raise ValueError("SECRET_CRYPTO_KEY is not set in the application configuration.")
        
        key_bytes = key_str.encode()
        self.fernet = Fernet(key_bytes)

    def encrypt(self, data: str) -> str | None:
        if not data:
            return None
        return self.fernet.encrypt(data.encode()).decode()

    def decrypt(self, encrypted_data: str) -> str | None:
        if not encrypted_data:
            return None
        return self.fernet.decrypt(encrypted_data.encode()).decode()


def get_user_garage_data(user: User) -> dict:
    """ユーザーの公開ガレージ表示に必要なデータをまとめて取得する"""
    if not user:
        return None

    # ガレージに掲載する設定の車両を取得
    vehicles_in_garage = Motorcycle.query.filter(
        Motorcycle.user_id == user.id,
        Motorcycle.show_in_garage == True
    ).order_by(Motorcycle.is_default.desc(), Motorcycle.id.asc()).all()

    hero_vehicle = None
    if user.garage_hero_vehicle_id:
        hero_vehicle = next((v for v in vehicles_in_garage if v.id == user.garage_hero_vehicle_id), None)
    if not hero_vehicle:
        hero_vehicle = next((v for v in vehicles_in_garage if v.is_default), None)
    if not hero_vehicle and vehicles_in_garage:
        hero_vehicle = vehicles_in_garage[0]
    
    other_vehicles = [v for v in vehicles_in_garage if v != hero_vehicle]
    
    # ヒーロー車両の統計情報
    hero_stats = {}
    if hero_vehicle:
        if hero_vehicle.is_racer:
            hero_stats['primary_metric_label'] = '総稼働時間'
            hero_stats['primary_metric_value'] = f"{hero_vehicle.total_operating_hours or 0:.2f}"
            hero_stats['primary_metric_unit'] = '時間'
        else:
            total_mileage = get_latest_total_distance(hero_vehicle.id, hero_vehicle.odometer_offset)
            avg_kpl = calculate_average_kpl(hero_vehicle)
            hero_stats['primary_metric_label'] = '総走行距離'
            hero_stats['primary_metric_value'] = f"{total_mileage:,}"
            hero_stats['primary_metric_unit'] = 'km'
            hero_stats['avg_kpl'] = f"{avg_kpl:.2f} km/L" if avg_kpl else "---"

        total_maint_cost = db.session.query(
            func.sum(func.coalesce(MaintenanceEntry.parts_cost, 0) + func.coalesce(MaintenanceEntry.labor_cost, 0))
        ).filter(
            MaintenanceEntry.motorcycle_id == hero_vehicle.id
        ).scalar() or 0
        hero_stats['total_maint_cost'] = f"{total_maint_cost:,.0f} 円"

        total_activities = db.session.query(
            func.count(ActivityLog.id)
        ).filter(
            ActivityLog.motorcycle_id == hero_vehicle.id
        ).scalar() or 0
        hero_stats['total_activities'] = f"{total_activities} 回"

    # ユーザーの総合サーキット実績を取得するロジック
    user_circuit_performance = []
    if user.garage_display_settings.get('show_circuit_info', True):
        user_sessions_ranked_sq = db.session.query(
            ActivityLog.circuit_name,
            SessionLog.best_lap_seconds,
            Motorcycle.name.label('vehicle_name'),
            func.row_number().over(
                partition_by=ActivityLog.circuit_name,
                order_by=SessionLog.best_lap_seconds.asc()
            ).label('rn')
        ).join(ActivityLog, SessionLog.activity_log_id == ActivityLog.id)\
         .join(Motorcycle, ActivityLog.motorcycle_id == Motorcycle.id)\
         .filter(ActivityLog.user_id == user.id)\
         .filter(ActivityLog.circuit_name.isnot(None))\
         .filter(SessionLog.best_lap_seconds.isnot(None))\
         .subquery('user_sessions_ranked')

        user_best_laps_q = db.session.query(
            user_sessions_ranked_sq.c.circuit_name,
            user_sessions_ranked_sq.c.best_lap_seconds,
            user_sessions_ranked_sq.c.vehicle_name
        ).filter(user_sessions_ranked_sq.c.rn == 1).subquery('user_best_laps')

        session_counts_q = db.session.query(
            ActivityLog.circuit_name,
            func.count(SessionLog.id).label('session_count')
        ).join(SessionLog, SessionLog.activity_log_id == ActivityLog.id)\
         .filter(ActivityLog.user_id == user.id)\
         .filter(ActivityLog.circuit_name.isnot(None))\
         .group_by(ActivityLog.circuit_name)\
         .subquery('session_counts')
         
        leaderboard_ranked_sq = db.session.query(
            ActivityLog.circuit_name,
            SessionLog.best_lap_seconds,
            ActivityLog.user_id,
            func.rank().over(
                partition_by=ActivityLog.circuit_name,
                order_by=SessionLog.best_lap_seconds.asc()
            ).label('rank')
        ).join(ActivityLog, SessionLog.activity_log_id == ActivityLog.id)\
         .filter(SessionLog.include_in_leaderboard == True)\
         .filter(ActivityLog.circuit_name.isnot(None))\
         .filter(SessionLog.best_lap_seconds.isnot(None))\
         .subquery('leaderboard_ranks')

        final_query = db.session.query(
            user_best_laps_q.c.circuit_name,
            session_counts_q.c.session_count,
            user_best_laps_q.c.best_lap_seconds,
            user_best_laps_q.c.vehicle_name,
            leaderboard_ranked_sq.c.rank
        ).select_from(user_best_laps_q)\
         .join(session_counts_q, user_best_laps_q.c.circuit_name == session_counts_q.c.circuit_name)\
         .outerjoin(leaderboard_ranked_sq, 
                    and_(
                        user_best_laps_q.c.circuit_name == leaderboard_ranked_sq.c.circuit_name,
                        user_best_laps_q.c.best_lap_seconds == leaderboard_ranked_sq.c.best_lap_seconds,
                        leaderboard_ranked_sq.c.user_id == user.id
                    )
         ).order_by(user_best_laps_q.c.circuit_name)

        results = final_query.all()
        user_circuit_performance = [
            {
                'circuit_name': row.circuit_name,
                'session_count': row.session_count,
                'best_lap_time': format_seconds_to_time(row.best_lap_seconds),
                'best_lap_vehicle': row.vehicle_name,
                'leaderboard_rank': row.rank,
            } for row in results
        ]

    # ユーザーの実績
    unlocked_achievements = db.session.query(
        AchievementDefinition.name,
        AchievementDefinition.icon_class
    ).join(
        UserAchievement, UserAchievement.achievement_code == AchievementDefinition.code
    ).filter(
        UserAchievement.user_id == user.id
    ).order_by(
        UserAchievement.unlocked_at.desc()
    ).limit(5).all()

    return {
        'owner': user,
        'hero_vehicle': hero_vehicle,
        'other_vehicles': other_vehicles,
        'hero_stats': hero_stats,
        'achievements': unlocked_achievements,
        'user_circuit_performance': user_circuit_performance,
    }


def get_nyanpuppu_advice(user, motorcycles):
    """
    ダッシュボードに表示する「にゃんぷっぷー」のアドバイスと画像を決定して返す。
    実際のロジックは nyanpuppu.py に委譲する。
    """
    return get_advice(user, motorcycles)