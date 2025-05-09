# motopuppu/views/fuel.py
import csv
import io
from datetime import date, datetime # datetime オブジェクト全体をインポート

from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, abort, current_app, Response
)
from sqlalchemy import or_, asc, desc, func # ★ func を追加 (countで使用する可能性を考慮)

from .auth import login_required_custom, get_current_user
from ..models import db, Motorcycle, FuelEntry # DBモデル
from ..forms import FuelForm, GAS_STATION_BRANDS

fuel_bp = Blueprint('fuel', __name__, url_prefix='/fuel')

def get_previous_fuel_entry(motorcycle_id, current_entry_date, current_entry_id=None):
    # (この関数は変更なし)
    if not motorcycle_id or not current_entry_date:
        return None
    query = FuelEntry.query.filter(
        FuelEntry.motorcycle_id == motorcycle_id,
        FuelEntry.entry_date < current_entry_date
    )
    if current_entry_id is not None:
        query = query.filter(FuelEntry.id != current_entry_id)
    previous_entry = query.order_by(FuelEntry.entry_date.desc(), FuelEntry.total_distance.desc()).first()
    return previous_entry

@fuel_bp.route('/')
@login_required_custom
def fuel_log():
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    vehicle_id_str = request.args.get('vehicle_id')
    keyword = request.args.get('q', '').strip()
    sort_by = request.args.get('sort_by', 'date') # デフォルトは日付順
    order = request.args.get('order', 'desc')
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('FUEL_ENTRIES_PER_PAGE', 20)

    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    if not user_motorcycles:
        flash('給油記録を閲覧・追加するには、まず車両を登録してください。', 'info')
        return redirect(url_for('vehicle.add_vehicle'))

    user_motorcycle_ids = [m.id for m in user_motorcycles]

    query = db.session.query(FuelEntry).join(Motorcycle).filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids))

    active_filters = {k: v for k, v in request.args.items() if k not in ['page', 'sort_by', 'order']}

    try:
        if start_date_str:
            query = query.filter(FuelEntry.entry_date >= date.fromisoformat(start_date_str))
        if end_date_str:
            query = query.filter(FuelEntry.entry_date <= date.fromisoformat(end_date_str))
    except ValueError:
        flash('日付の形式が無効です。YYYY-MM-DD形式で入力してください。', 'warning')
        active_filters.pop('start_date', None)
        active_filters.pop('end_date', None)

    if vehicle_id_str:
        try:
            vehicle_id = int(vehicle_id_str)
            if vehicle_id in user_motorcycle_ids:
                query = query.filter(FuelEntry.motorcycle_id == vehicle_id)
            else:
                flash('選択された車両は有効ではありません。', 'warning')
                active_filters.pop('vehicle_id', None)
        except ValueError:
            active_filters.pop('vehicle_id', None)

    if keyword:
        search_term = f'%{keyword}%'
        query = query.filter(or_(FuelEntry.notes.ilike(search_term), FuelEntry.station_name.ilike(search_term)))

    # --- ソートキーの修正 ---
    sort_column_map = {
        'date': FuelEntry.entry_date,
        'vehicle': Motorcycle.name,
        'odo_reading': FuelEntry.odometer_reading,       # ODOメーター値
        'actual_distance': FuelEntry.total_distance,     # 実走行距離
        'volume': FuelEntry.fuel_volume,
        'price': FuelEntry.price_per_liter,
        'cost': FuelEntry.total_cost,
        'station': FuelEntry.station_name,
    }
    # デフォルトのソートキーを 'date' に設定
    current_sort_by = sort_by if sort_by in sort_column_map else 'date'
    sort_column = sort_column_map.get(current_sort_by, FuelEntry.entry_date) # 安全策

    current_order = 'desc' if order == 'desc' else 'asc'
    sort_modifier = desc if current_order == 'desc' else asc

    # ソートの優先順位を調整
    if sort_column == FuelEntry.entry_date:
        query = query.order_by(sort_modifier(FuelEntry.entry_date), desc(FuelEntry.total_distance), FuelEntry.id.desc())
    elif sort_column == FuelEntry.odometer_reading: # odo_reading
        query = query.order_by(sort_modifier(FuelEntry.odometer_reading), desc(FuelEntry.entry_date), FuelEntry.id.desc())
    elif sort_column == FuelEntry.total_distance: # actual_distance
        query = query.order_by(sort_modifier(FuelEntry.total_distance), desc(FuelEntry.entry_date), FuelEntry.id.desc())
    else:
        query = query.order_by(sort_modifier(sort_column), desc(FuelEntry.entry_date), FuelEntry.id.desc())


    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    fuel_entries = pagination.items

    return render_template('fuel_log.html',
                           entries=fuel_entries,
                           pagination=pagination,
                           motorcycles=user_motorcycles,
                           request_args=active_filters,
                           current_sort_by=current_sort_by,
                           current_order=current_order
                           )

@fuel_bp.route('/add', methods=['GET', 'POST'])
@login_required_custom
def add_fuel():
    # (この関数は変更なし - 前回の修正を維持)
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    if not user_motorcycles:
        flash('給油記録を追加するには、まず車両を登録してください。', 'warning')
        return redirect(url_for('vehicle.add_vehicle'))

    form = FuelForm()
    form.motorcycle_id.choices = [(m.id, f"{m.name} ({m.maker or 'メーカー不明'})") for m in user_motorcycles]
    previous_entry_info = None

    if request.method == 'GET':
        default_vehicle = next((m for m in user_motorcycles if m.is_default), user_motorcycles[0] if user_motorcycles else None)
        if default_vehicle: form.motorcycle_id.data = default_vehicle.id
        preselected_motorcycle_id = request.args.get('motorcycle_id', type=int)
        if preselected_motorcycle_id and any(m.id == preselected_motorcycle_id for m in user_motorcycles):
            form.motorcycle_id.data = preselected_motorcycle_id
        form.entry_date.data = date.today()
        form.is_full_tank.data = True

    if form.validate_on_submit():
        motorcycle = Motorcycle.query.filter_by(id=form.motorcycle_id.data, user_id=g.user.id).first()
        if not motorcycle:
            flash('選択された車両が見つかりません。再度お試しください。', 'danger')
            return render_template('fuel_form.html', form_action='add', form=form, gas_station_brands=GAS_STATION_BRANDS, previous_entry_info=None)
        offset_at_entry_date = motorcycle.calculate_cumulative_offset_from_logs(target_date=form.entry_date.data)
        total_distance = form.odometer_reading.data + offset_at_entry_date
        previous_entry_for_check = get_previous_fuel_entry(motorcycle.id, form.entry_date.data)
        if previous_entry_for_check and total_distance < previous_entry_for_check.total_distance:
            flash(f'注意: 今回の総走行距離 ({total_distance:,}km) が、前回記録 ({previous_entry_for_check.entry_date.strftime("%Y-%m-%d")} の {previous_entry_for_check.total_distance:,}km) より小さくなっています。入力内容を確認してください。', 'warning')
        total_cost_val = form.total_cost.data
        if total_cost_val is None and form.price_per_liter.data is not None and form.fuel_volume.data is not None:
            try: total_cost_val = round(float(form.price_per_liter.data) * float(form.fuel_volume.data))
            except TypeError: total_cost_val = None
        elif total_cost_val is not None: total_cost_val = int(round(float(total_cost_val)))
        new_entry = FuelEntry(
            motorcycle_id=motorcycle.id, entry_date=form.entry_date.data, odometer_reading=form.odometer_reading.data,
            total_distance=total_distance, fuel_volume=float(form.fuel_volume.data),
            price_per_liter=float(form.price_per_liter.data) if form.price_per_liter.data is not None else None,
            total_cost=total_cost_val, station_name=form.station_name.data.strip() if form.station_name.data else None,
            fuel_type=form.fuel_type.data.strip() if form.fuel_type.data else None,
            notes=form.notes.data.strip() if form.notes.data else None, is_full_tank=form.is_full_tank.data)
        try:
            db.session.add(new_entry); db.session.commit()
            flash('給油記録を追加しました。', 'success')
            return redirect(url_for('fuel.fuel_log'))
        except Exception as e:
            db.session.rollback()
            flash(f'記録のデータベース保存中にエラーが発生しました。詳細は管理者にお問い合わせください。', 'error')
            current_app.logger.error(f"Error saving new fuel entry: {e}", exc_info=True)
    elif request.method == 'POST':
        form.motorcycle_id.choices = [(m.id, f"{m.name} ({m.maker or 'メーカー不明'})") for m in user_motorcycles]
    selected_motorcycle_id_for_prev = form.motorcycle_id.data
    entry_date_for_prev = form.entry_date.data
    if selected_motorcycle_id_for_prev and entry_date_for_prev:
        previous_fuel = get_previous_fuel_entry(selected_motorcycle_id_for_prev, entry_date_for_prev)
        if previous_fuel: previous_entry_info = {'date': previous_fuel.entry_date.strftime('%Y-%m-%d'), 'odo': f"{previous_fuel.odometer_reading:,}km"}
    return render_template('fuel_form.html', form_action='add', form=form, gas_station_brands=GAS_STATION_BRANDS, previous_entry_info=previous_entry_info)

@fuel_bp.route('/<int:entry_id>/edit', methods=['GET', 'POST'])
@login_required_custom
def edit_fuel(entry_id):
    # (この関数は変更なし - 前回の修正を維持)
    entry = FuelEntry.query.filter(FuelEntry.id == entry_id).join(Motorcycle).filter(Motorcycle.user_id == g.user.id).first_or_404()
    form = FuelForm(obj=entry)
    form.motorcycle_id.choices = [(entry.motorcycle.id, f"{entry.motorcycle.name} ({entry.motorcycle.maker or 'メーカー不明'})")]
    form.motorcycle_id.data = entry.motorcycle_id
    previous_entry_info = None
    if form.validate_on_submit():
        motorcycle = entry.motorcycle
        offset_at_entry_date = motorcycle.calculate_cumulative_offset_from_logs(target_date=form.entry_date.data)
        total_distance = form.odometer_reading.data + offset_at_entry_date
        previous_entry_for_check = get_previous_fuel_entry(motorcycle.id, form.entry_date.data, entry.id)
        if previous_entry_for_check and total_distance < previous_entry_for_check.total_distance:
             flash(f'注意: 今回の総走行距離 ({total_distance:,}km) が、前回記録 ({previous_entry_for_check.entry_date.strftime("%Y-%m-%d")} の {previous_entry_for_check.total_distance:,}km) より小さくなっています。入力内容を確認してください。', 'warning')
        total_cost_val = form.total_cost.data
        if total_cost_val is None and form.price_per_liter.data is not None and form.fuel_volume.data is not None:
            try: total_cost_val = round(float(form.price_per_liter.data) * float(form.fuel_volume.data))
            except TypeError: total_cost_val = None
        elif total_cost_val is not None: total_cost_val = int(round(float(total_cost_val)))
        entry.entry_date = form.entry_date.data; entry.odometer_reading = form.odometer_reading.data
        entry.total_distance = total_distance; entry.fuel_volume = float(form.fuel_volume.data)
        entry.price_per_liter = float(form.price_per_liter.data) if form.price_per_liter.data is not None else None
        entry.total_cost = total_cost_val; entry.station_name = form.station_name.data.strip() if form.station_name.data else None
        entry.fuel_type = form.fuel_type.data.strip() if form.fuel_type.data else None
        entry.notes = form.notes.data.strip() if form.notes.data else None; entry.is_full_tank = form.is_full_tank.data
        try:
            db.session.commit(); flash('給油記録を更新しました。', 'success')
            return redirect(url_for('fuel.fuel_log'))
        except Exception as e:
            db.session.rollback(); flash(f'記録の更新中にエラーが発生しました。詳細は管理者にお問い合わせください。', 'error')
            current_app.logger.error(f"Error updating fuel entry ID {entry_id}: {e}", exc_info=True)
    elif request.method == 'POST':
        form.motorcycle_id.choices = [(entry.motorcycle.id, f"{entry.motorcycle.name} ({entry.motorcycle.maker or 'メーカー不明'})")]
        form.motorcycle_id.data = entry.motorcycle.id
    current_motorcycle_id_for_prev = entry.motorcycle_id
    entry_date_for_prev = form.entry_date.data if form.entry_date.data else entry.entry_date
    if current_motorcycle_id_for_prev and entry_date_for_prev:
        previous_fuel = get_previous_fuel_entry(current_motorcycle_id_for_prev, entry_date_for_prev, entry.id)
        if previous_fuel: previous_entry_info = {'date': previous_fuel.entry_date.strftime('%Y-%m-%d'), 'odo': f"{previous_fuel.odometer_reading:,}km"}
    return render_template('fuel_form.html', form_action='edit', form=form, entry_id=entry.id, gas_station_brands=GAS_STATION_BRANDS, previous_entry_info=previous_entry_info)

@fuel_bp.route('/<int:entry_id>/delete', methods=['POST'])
@login_required_custom
def delete_fuel(entry_id):
    # (この関数は変更なし - 前回の修正を維持)
    entry = FuelEntry.query.filter(FuelEntry.id == entry_id).join(Motorcycle).filter(Motorcycle.user_id == g.user.id).first_or_404()
    try:
        db.session.delete(entry); db.session.commit()
        flash('給油記録を削除しました。', 'success')
    except Exception as e:
        db.session.rollback(); flash(f'記録の削除中にエラーが発生しました。詳細は管理者にお問い合わせください。', 'error')
        current_app.logger.error(f"Error deleting fuel entry ID {entry_id}: {e}", exc_info=True)
    return redirect(url_for('fuel.fuel_log'))

@fuel_bp.route('/motorcycle/<int:motorcycle_id>/export_csv')
@login_required_custom
def export_fuel_records_csv(motorcycle_id):
    # (この関数は変更なし - 前回のものを維持)
    motorcycle = Motorcycle.query.filter_by(id=motorcycle_id, user_id=g.user.id).first_or_404()
    fuel_records = FuelEntry.query.filter_by(motorcycle_id=motorcycle.id).order_by(FuelEntry.entry_date.asc(), FuelEntry.total_distance.asc()).all()
    if not fuel_records:
        flash(f'{motorcycle.name}にはエクスポート対象の燃費記録がありません。', 'info')
        return redirect(url_for('fuel.fuel_log', vehicle_id=motorcycle.id))
    output = io.StringIO(); writer = csv.writer(output)
    header = ['id', 'motorcycle_id', 'motorcycle_name', 'entry_date', 'odometer_reading', 'total_distance', 'fuel_volume', 'price_per_liter', 'total_cost', 'station_name', 'is_full_tank', 'km_per_liter', 'notes', 'fuel_type']
    writer.writerow(header)
    for record in fuel_records:
        km_per_liter_val = record.km_per_liter
        row = [record.id, record.motorcycle_id, motorcycle.name, record.entry_date.strftime('%Y-%m-%d') if record.entry_date else '', record.odometer_reading, record.total_distance, f"{record.fuel_volume:.2f}" if record.fuel_volume is not None else '', f"{record.price_per_liter:.1f}" if record.price_per_liter is not None else '', f"{record.total_cost:.0f}" if record.total_cost is not None else '', record.station_name if record.station_name else '', str(record.is_full_tank), f"{km_per_liter_val:.2f}" if km_per_liter_val is not None else '', record.notes if record.notes else '', record.fuel_type if record.fuel_type else '']
        writer.writerow(row)
    output.seek(0)
    safe_vehicle_name = "".join(c for c in motorcycle.name if c.isalnum() or c in ['_', '-']).strip()
    if not safe_vehicle_name: safe_vehicle_name = "vehicle"
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    filename = f"motopuppu_fuel_records_{safe_vehicle_name}_{motorcycle.id}_{timestamp}.csv"
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment;filename=\"{filename}\"", "Content-Type": "text/csv; charset=utf-8-sig"})

@fuel_bp.route('/export_all_csv')
@login_required_custom
def export_all_fuel_records_csv():
    # (この関数は変更なし - 前回のものを維持)
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).all()
    if not user_motorcycles:
        flash('エクスポート対象の車両が登録されていません。', 'info')
        return redirect(url_for('fuel.fuel_log'))

    user_motorcycle_ids = [m.id for m in user_motorcycles]
    
    all_fuel_records = FuelEntry.query.filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids))\
                                      .options(db.joinedload(FuelEntry.motorcycle))\
                                      .order_by(FuelEntry.motorcycle_id, FuelEntry.entry_date.asc(), FuelEntry.total_distance.asc()).all()

    if not all_fuel_records:
        flash('エクスポート対象の燃費記録がありません。', 'info')
        return redirect(url_for('fuel.fuel_log'))

    output = io.StringIO()
    writer = csv.writer(output)

    header = [
        'id', 'motorcycle_id', 'motorcycle_name', 'entry_date', 'odometer_reading',
        'total_distance', 'fuel_volume', 'price_per_liter', 'total_cost',
        'station_name', 'is_full_tank', 'km_per_liter', 'notes', 'fuel_type'
    ]
    writer.writerow(header)

    for record in all_fuel_records:
        km_per_liter_val = record.km_per_liter
        row = [
            record.id,
            record.motorcycle_id,
            record.motorcycle.name,
            record.entry_date.strftime('%Y-%m-%d') if record.entry_date else '',
            record.odometer_reading,
            record.total_distance,
            f"{record.fuel_volume:.2f}" if record.fuel_volume is not None else '',
            f"{record.price_per_liter:.1f}" if record.price_per_liter is not None else '',
            f"{record.total_cost:.0f}" if record.total_cost is not None else '',
            record.station_name if record.station_name else '',
            str(record.is_full_tank),
            f"{km_per_liter_val:.2f}" if km_per_liter_val is not None else '',
            record.notes if record.notes else '',
            record.fuel_type if record.fuel_type else ''
        ]
        writer.writerow(row)

    output.seek(0)

    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    filename = f"motopuppu_fuel_records_all_vehicles_{timestamp}.csv"

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment;filename=\"{filename}\"",
            "Content-Type": "text/csv; charset=utf-8-sig"
        }
    )