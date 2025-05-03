# motopuppu/views/main.py

from flask import (
    Blueprint, render_template, redirect, url_for, session, g, flash, current_app, jsonify
)
from .auth import login_required_custom, get_current_user
from ..models import Motorcycle, FuelEntry, MaintenanceEntry # dbオブジェクトは不要
# ▼▼▼ math モジュールをインポート ▼▼▼
import math

main_bp = Blueprint('main', __name__)

# --- ルート定義 ---

@main_bp.route('/')
def index():
    """トップページを表示"""
    g.user = get_current_user()
    return render_template('index.html')

@main_bp.route('/dashboard')
@login_required_custom
def dashboard():
    """ログイン後のダッシュボードを表示"""
    vehicle_count = Motorcycle.query.filter_by(user_id=g.user.id).count()
    if vehicle_count == 0:
        flash('ようこそ！最初に利用する車両を登録してください。', 'info')
        return redirect(url_for('vehicle.add_vehicle'))

    current_app.logger.debug(f"User {g.user.id} has {vehicle_count} vehicles. Showing dashboard.")

    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.id).all()
    user_motorcycle_ids = [m.id for m in user_motorcycles]

    # --- ▼▼▼ 平均燃費計算ロジック修正 ▼▼▼ ---
    for m in user_motorcycles:
        # 各車両の「満タン」給油記録を走行距離(昇順)で取得
        full_tank_entries = FuelEntry.query.filter(
            FuelEntry.motorcycle_id == m.id,
            FuelEntry.is_full_tank == True # 満タンフラグで絞り込み
        ).order_by(FuelEntry.total_distance.asc()).all()

        if len(full_tank_entries) < 2:
             # 満タン記録が2件未満の場合は計算不可
            m._average_kpl = None # 一時的な属性としてNoneをセット
        else:
            # 総走行距離 = 最後の満タン記録の総走行距離 - 最初の満タン記録の総走行距離
            total_distance_traveled = full_tank_entries[-1].total_distance - full_tank_entries[0].total_distance
            # 総給油量 = 2回目以降の「満タン」記録の給油量の合計
            total_fuel_consumed = sum(entry.fuel_volume for entry in full_tank_entries[1:])

            # 燃費計算 (ゼロ除算と走行距離0を回避)
            if total_fuel_consumed > 0 and total_distance_traveled > 0:
                avg_kpl = total_distance_traveled / total_fuel_consumed
                m._average_kpl = round(avg_kpl, 2) # 計算結果を一時的な属性にセット
            else:
                m._average_kpl = None # 計算不能の場合
    # --- ▲▲▲ 平均燃費計算ここまで ▲▲▲ ---

    recent_fuel_entries = FuelEntry.query.filter(
        FuelEntry.motorcycle_id.in_(user_motorcycle_ids)
    ).order_by(
        FuelEntry.entry_date.desc(), FuelEntry.total_distance.desc()
    ).limit(5).all()

    recent_maintenance_entries = MaintenanceEntry.query.filter(
        MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids)
    ).order_by(
        MaintenanceEntry.maintenance_date.desc(), MaintenanceEntry.total_distance_at_maintenance.desc()
    ).limit(5).all()

    return render_template('dashboard.html',
                           motorcycles=user_motorcycles,
                           recent_fuel_entries=recent_fuel_entries,
                           recent_maintenance_entries=recent_maintenance_entries)


# --- APIエンドポイント (修正: extendedProps を追加) ---
@main_bp.route('/api/dashboard/events')
@login_required_custom
def dashboard_events_api():
    """ダッシュボードのFullCalendarに表示するイベントデータを返すAPI (詳細情報付き)"""
    events = []
    user_motorcycle_ids = [m.id for m in Motorcycle.query.filter_by(user_id=g.user.id).all()]

    # --- 給油記録 ---
    fuel_entries = FuelEntry.query.filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids)).all()
    for entry in fuel_entries:
        # km_per_liter はプロパティなので、ここでアクセスして値を取得
        # None の場合の処理も考慮
        kpl = entry.km_per_liter
        kpl_display = f"{kpl:.2f} km/L" if kpl is not None else None

        events.append({
            'title': f"給油: {entry.motorcycle.name}",
            'start': entry.entry_date.isoformat(),
            'url': url_for('fuel.edit_fuel', entry_id=entry.id),
            'backgroundColor': '#198754',
            'borderColor': '#198754',
            'textColor': 'white',
            # ▼▼▼ 詳細情報を extendedProps に追加 ▼▼▼
            'extendedProps': {
                'type': 'fuel', # 記録タイプを明示
                'motorcycleName': entry.motorcycle.name,
                'odometer': entry.odometer_reading,
                'fuelVolume': entry.fuel_volume,
                'kmPerLiter': kpl_display, # 計算済み/フォーマット済み燃費
                'totalCost': math.ceil(entry.total_cost) if entry.total_cost is not None else None, # 小数点以下切り上げ (または round)
                'stationName': entry.station_name,
                'notes': entry.notes
            }
            # ▲▲▲ 追加ここまで ▲▲▲
        })

    # --- 整備記録 ---
    maintenance_entries = MaintenanceEntry.query.filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids)).all()
    for entry in maintenance_entries:
        # イベントタイトル生成 (変更なし)
        event_title_base = entry.category if entry.category else entry.description
        event_title = f"整備: {event_title_base[:15]}"
        if len(event_title_base) > 15: event_title += "..."

        # total_cost はプロパティ
        total_cost = entry.total_cost

        events.append({
            'title': event_title,
            'start': entry.maintenance_date.isoformat(),
            'url': url_for('maintenance.edit_maintenance', entry_id=entry.id),
            'backgroundColor': '#ffc107',
            'borderColor': '#ffc107',
            'textColor': 'black', # 文字色は黒のまま (Bootstrapのbtn-warningに準拠)
            # ▼▼▼ 詳細情報を extendedProps に追加 ▼▼▼
            'extendedProps': {
                'type': 'maintenance', # 記録タイプを明示
                'motorcycleName': entry.motorcycle.name,
                'odometer': entry.total_distance_at_maintenance, # total_distance を使う
                'description': entry.description,
                'category': entry.category,
                'totalCost': math.ceil(total_cost) if total_cost is not None else None, # 小数点以下切り上げ
                'location': entry.location,
                'notes': entry.notes
            }
            # ▲▲▲ 追加ここまで ▲▲▲
        })

    return jsonify(events)

# --- (他のルートやエラーハンドラは省略) ---