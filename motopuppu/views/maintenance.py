# motopuppu/views/maintenance.py
import csv
import io
from datetime import date, datetime

from flask import (
    Blueprint, flash, redirect, render_template, request, url_for, abort, current_app, Response, jsonify
)
from sqlalchemy import or_, asc, desc, func

# ▼▼▼ インポート文を修正 ▼▼▼
from flask_login import login_required, current_user
# ▲▲▲ 変更ここまで ▲▲▲
from ..models import db, Motorcycle, MaintenanceEntry, MaintenanceReminder
from ..forms import MaintenanceForm
from ..constants import MAINTENANCE_CATEGORIES
from ..achievement_evaluator import check_achievements_for_event, EVENT_ADD_MAINTENANCE_LOG
from .. import limiter


maintenance_bp = Blueprint('maintenance', __name__, url_prefix='/maintenance')

def get_previous_maintenance_entry(motorcycle_id, current_maintenance_date, current_entry_id=None):
    """指定された車両・日付に基づき、直前の整備記録を取得する"""
    if not motorcycle_id or not current_maintenance_date:
        return None
    
    query = MaintenanceEntry.query.filter(
        MaintenanceEntry.motorcycle_id == motorcycle_id,
        MaintenanceEntry.maintenance_date <= current_maintenance_date
    )
    
    if current_entry_id is not None:
        query = query.filter(MaintenanceEntry.id != current_entry_id)

    previous_entry = query.order_by(
        MaintenanceEntry.maintenance_date.desc(), 
        MaintenanceEntry.total_distance_at_maintenance.desc(), 
        MaintenanceEntry.id.desc()
    ).first()
    
    return previous_entry


def _update_reminder_if_applicable(maintenance_entry: MaintenanceEntry):
    """
    条件付きでリマインダーを自動更新する関数。
    """
    if not maintenance_entry or not maintenance_entry.category:
        return

    maint_category_lower = maintenance_entry.category.strip().lower()
    if not maint_category_lower:
        return

    potential_reminders = MaintenanceReminder.query.filter_by(
        motorcycle_id=maintenance_entry.motorcycle_id).all()

    for reminder in potential_reminders:
        if reminder.task_description and reminder.task_description.strip().lower() == maint_category_lower:
            
            if not reminder.auto_update_from_category:
                current_app.logger.debug(f"Reminder '{reminder.task_description}' (ID:{reminder.id}) has auto-update disabled. Skipping.")
                continue

            is_newer = False
            if reminder.last_done_date is None:
                is_newer = True
            elif maintenance_entry.maintenance_date > reminder.last_done_date:
                is_newer = True
            elif (maintenance_entry.maintenance_date == reminder.last_done_date and
                    not reminder.motorcycle.is_racer and
                    (maintenance_entry.total_distance_at_maintenance or 0) >= (reminder.last_done_km or 0)):
                is_newer = True

            if is_newer:
                reminder.last_maintenance_entry_id = maintenance_entry.id
                reminder.last_done_date = maintenance_entry.maintenance_date
                reminder.last_done_km = maintenance_entry.total_distance_at_maintenance
                reminder.last_done_odo = maintenance_entry.odometer_reading_at_maintenance
                flash(f"整備記録に基づき、リマインダー「{reminder.task_description}」を新しい記録に自動連携しました。", 'info')
                current_app.logger.info(f"Reminder '{reminder.task_description}' (ID:{reminder.id}) was auto-linked to new MaintenanceEntry ID:{maintenance_entry.id}")
                break


@maintenance_bp.route('/')
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def maintenance_log():
    start_date_str = request.args.get('start_date'); end_date_str = request.args.get('end_date')
    vehicle_id_str = request.args.get('vehicle_id'); category_filter = request.args.get('category', '').strip()
    keyword = request.args.get('q', '').strip(); sort_by = request.args.get('sort_by', 'date')
    order = request.args.get('order', 'desc'); page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('MAINTENANCE_ENTRIES_PER_PAGE', 20)

    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    user_motorcycles_all = Motorcycle.query.filter_by(user_id=current_user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    # ▲▲▲ 変更ここまで ▲▲▲
    user_motorcycles_for_maintenance = [m for m in user_motorcycles_all if not m.is_racer]

    if not user_motorcycles_all:
        flash('整備記録を閲覧・追加するには、まず車両を登録してください。', 'info')
        return redirect(url_for('vehicle.add_vehicle'))
    if not user_motorcycles_for_maintenance and user_motorcycles_all:
        flash('登録されている車両はすべてレーサー仕様のため、整備記録の対象外です。公道走行可能な車両を登録してください。', 'info')

    user_motorcycle_ids_for_maintenance = [m.id for m in user_motorcycles_for_maintenance]

    query = db.session.query(MaintenanceEntry).join(Motorcycle).filter(
        MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids_for_maintenance)
    )
    active_filters = {k: v for k, v in request.args.items() if k not in ['page', 'sort_by', 'order']}

    try:
        if start_date_str: query = query.filter(MaintenanceEntry.maintenance_date >= date.fromisoformat(start_date_str))
        if end_date_str: query = query.filter(MaintenanceEntry.maintenance_date <= date.fromisoformat(end_date_str))
    except ValueError:
        flash('日付の形式が無効です。YYYY-MM-DD形式で入力してください。', 'warning')
        active_filters.pop('start_date', None); active_filters.pop('end_date', None)

    if vehicle_id_str:
        try:
            vehicle_id = int(vehicle_id_str)
            if vehicle_id in user_motorcycle_ids_for_maintenance:
                query = query.filter(MaintenanceEntry.motorcycle_id == vehicle_id)
            else:
                flash('選択された車両は整備記録の対象外か、有効ではありません。', 'warning')
                active_filters.pop('vehicle_id', None)
        except ValueError: active_filters.pop('vehicle_id', None)

    if category_filter: query = query.filter(MaintenanceEntry.category.ilike(f'%{category_filter}%'))
    if keyword:
        search_term = f'%{keyword}%'
        query = query.filter(or_(MaintenanceEntry.description.ilike(search_term), MaintenanceEntry.location.ilike(search_term), MaintenanceEntry.notes.ilike(search_term)))

    sort_column_map = {
        'date': MaintenanceEntry.maintenance_date, 'vehicle': Motorcycle.name,
        'odo_reading': MaintenanceEntry.odometer_reading_at_maintenance,
        'actual_distance': MaintenanceEntry.total_distance_at_maintenance,
        'category': MaintenanceEntry.category
    }
    current_sort_by = sort_by if sort_by in sort_column_map else 'date'
    sort_column = sort_column_map.get(current_sort_by, MaintenanceEntry.maintenance_date)
    current_order = 'desc' if order == 'desc' else 'asc'
    sort_modifier = desc if current_order == 'desc' else asc

    if sort_column == MaintenanceEntry.maintenance_date:
        query = query.order_by(sort_modifier(MaintenanceEntry.maintenance_date), desc(MaintenanceEntry.total_distance_at_maintenance), MaintenanceEntry.id.desc())
    elif sort_column == MaintenanceEntry.odometer_reading_at_maintenance:
        query = query.order_by(sort_modifier(MaintenanceEntry.odometer_reading_at_maintenance), desc(MaintenanceEntry.maintenance_date), MaintenanceEntry.id.desc())
    elif sort_column == MaintenanceEntry.total_distance_at_maintenance:
        query = query.order_by(sort_modifier(MaintenanceEntry.total_distance_at_maintenance), desc(MaintenanceEntry.maintenance_date), MaintenanceEntry.id.desc())
    else:
        query = query.order_by(sort_modifier(sort_column), desc(MaintenanceEntry.maintenance_date), MaintenanceEntry.id.desc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    entries = pagination.items
    
    is_filter_active = bool(active_filters)

    return render_template('maintenance_log.html',
                           entries=entries, pagination=pagination,
                           motorcycles=user_motorcycles_for_maintenance,
                           request_args=active_filters,
                           current_sort_by=current_sort_by, current_order=current_order,
                           is_filter_active=is_filter_active)

@maintenance_bp.route('/add', methods=['GET', 'POST'])
@limiter.limit("30 per hour")
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def add_maintenance():
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    user_motorcycles_for_maintenance = Motorcycle.query.filter_by(user_id=current_user.id, is_racer=False).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    if not user_motorcycles_for_maintenance:
        all_motorcycles_count = Motorcycle.query.filter_by(user_id=current_user.id).count()
    # ▲▲▲ 変更ここまで ▲▲▲
        if all_motorcycles_count > 0:
            flash('登録されている車両はすべてレーサー仕様のため、整備記録を追加できません。公道走行可能な車両を登録してください。', 'warning')
            return redirect(url_for('vehicle.vehicle_list'))
        else:
            flash('整備記録を追加するには、まず車両を登録してください。', 'warning')
            return redirect(url_for('vehicle.add_vehicle'))

    form = MaintenanceForm()
    form.motorcycle_id.choices = [(m.id, f"{m.name} ({m.maker or 'メーカー不明'})") for m in user_motorcycles_for_maintenance]

    if request.method == 'GET':
        default_vehicle = next((m for m in user_motorcycles_for_maintenance if m.is_default), user_motorcycles_for_maintenance[0] if user_motorcycles_for_maintenance else None)
        if default_vehicle: form.motorcycle_id.data = default_vehicle.id

        preselected_motorcycle_id = request.args.get('motorcycle_id', type=int)
        if preselected_motorcycle_id and any(m.id == preselected_motorcycle_id for m in user_motorcycles_for_maintenance):
            form.motorcycle_id.data = preselected_motorcycle_id

        form.maintenance_date.data = date.today()

    if form.validate_on_submit():
        # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
        motorcycle = Motorcycle.query.filter_by(id=form.motorcycle_id.data, user_id=current_user.id, is_racer=False).first()
        # ▲▲▲ 変更ここまで ▲▲▲
        if not motorcycle:
            flash('選択された車両が見つからないか、整備記録の対象外です。再度お試しください。', 'danger')
            return render_template('maintenance_form.html', form_action='add', form=form, category_options=MAINTENANCE_CATEGORIES)

        previous_mainte = get_previous_maintenance_entry(motorcycle.id, form.maintenance_date.data)

        if form.input_mode.data:
            if form.trip_distance.data is None:
                form.trip_distance.errors.append('トリップメーターで入力する場合、この項目は必須です。')
            elif previous_mainte:
                form.odometer_reading_at_maintenance.data = previous_mainte.odometer_reading_at_maintenance + form.trip_distance.data
            else:
                form.trip_distance.errors.append('この車両で初めての整備記録です。トリップ入力は使用できません。ODOメーター値を直接入力してください。')
        else:
            if form.odometer_reading_at_maintenance.data is None:
                form.odometer_reading_at_maintenance.errors.append('ODOメーターで入力する場合、この項目は必須です。')
        
        if form.errors:
            flash('入力内容にエラーがあります。ご確認ください。', 'danger')
            return render_template('maintenance_form.html', form_action='add', form=form, category_options=MAINTENANCE_CATEGORIES)

        offset_at_maintenance_date = motorcycle.calculate_cumulative_offset_from_logs(target_date=form.maintenance_date.data)
        total_distance = form.odometer_reading_at_maintenance.data + offset_at_maintenance_date

        new_entry = MaintenanceEntry(
            motorcycle_id=motorcycle.id, maintenance_date=form.maintenance_date.data,
            odometer_reading_at_maintenance=form.odometer_reading_at_maintenance.data,
            total_distance_at_maintenance=total_distance,
            description=form.description.data.strip(),
            location=form.location.data.strip() if form.location.data else None,
            category=form.category.data.strip() if form.category.data else None,
            parts_cost=form.parts_cost.data, labor_cost=form.labor_cost.data,
            notes=form.notes.data.strip() if form.notes.data else None
        )

        try:
            db.session.add(new_entry)
            db.session.flush()
            _update_reminder_if_applicable(new_entry)
            db.session.commit()
            flash('整備記録を追加しました。', 'success')

            event_data_for_ach = {'new_maintenance_log_id': new_entry.id, 'motorcycle_id': motorcycle.id, 'category': new_entry.category}
            # ▼▼▼ g.user を current_user に変更 ▼▼▼
            check_achievements_for_event(current_user, EVENT_ADD_MAINTENANCE_LOG, event_data=event_data_for_ach)
            # ▲▲▲ 変更ここまで ▲▲▲

            return redirect(url_for('maintenance.maintenance_log'))
        except Exception as e:
            db.session.rollback()
            flash(f'記録のデータベース保存中にエラーが発生しました。詳細は管理者にお問い合わせください。', 'error')
            current_app.logger.error(f"Error saving new maintenance entry: {e}", exc_info=True)

    elif request.method == 'POST':
        flash('入力内容にエラーがあります。ご確認ください。', 'danger')

    return render_template('maintenance_form.html', form_action='add', form=form, category_options=MAINTENANCE_CATEGORIES)

@maintenance_bp.route('/<int:entry_id>/edit', methods=['GET', 'POST'])
@limiter.limit("30 per hour")
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def edit_maintenance(entry_id):
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    entry = MaintenanceEntry.query.join(Motorcycle).filter(
        MaintenanceEntry.id == entry_id,
        Motorcycle.user_id == current_user.id,
        Motorcycle.is_racer == False
    ).first_or_404()
    
    user_motorcycles_for_maintenance = Motorcycle.query.filter_by(user_id=current_user.id, is_racer=False).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    # ▲▲▲ 変更ここまで ▲▲▲
    
    form = MaintenanceForm(obj=entry)
    form.motorcycle_id.choices = [(m.id, f"{m.name} ({m.maker or 'メーカー不明'})") for m in user_motorcycles_for_maintenance]

    if request.method == 'GET':
        form.motorcycle_id.data = entry.motorcycle_id
        form.input_mode.data = False

    if form.validate_on_submit():
        # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
        motorcycle = Motorcycle.query.filter_by(id=form.motorcycle_id.data, user_id=current_user.id, is_racer=False).first()
        # ▲▲▲ 変更ここまで ▲▲▲
        if not motorcycle:
            flash('選択された車両が見つからないか、整備記録の対象外です。再度お試しください。', 'danger')
            return render_template('maintenance_form.html', form_action='edit', form=form, entry_id=entry.id, category_options=MAINTENANCE_CATEGORIES)

        previous_mainte = get_previous_maintenance_entry(motorcycle.id, form.maintenance_date.data, entry.id)

        if form.input_mode.data:
            if form.trip_distance.data is None:
                form.trip_distance.errors.append('トリップメーターで入力する場合、この項目は必須です。')
            elif previous_mainte:
                form.odometer_reading_at_maintenance.data = previous_mainte.odometer_reading_at_maintenance + form.trip_distance.data
            else:
                form.trip_distance.errors.append('この記録より前の整備記録がありません。トリップ入力は使用できません。')
        else:
            if form.odometer_reading_at_maintenance.data is None:
                form.odometer_reading_at_maintenance.errors.append('ODOメーターで入力する場合、この項目は必須です。')
        
        if form.errors:
            flash('入力内容にエラーがあります。ご確認ください。', 'danger')
            return render_template('maintenance_form.html', form_action='edit', form=form, entry_id=entry.id, category_options=MAINTENANCE_CATEGORIES)

        offset_at_maintenance_date = motorcycle.calculate_cumulative_offset_from_logs(target_date=form.maintenance_date.data)
        total_distance = form.odometer_reading_at_maintenance.data + offset_at_maintenance_date

        entry.motorcycle_id = motorcycle.id
        entry.maintenance_date = form.maintenance_date.data
        entry.odometer_reading_at_maintenance = form.odometer_reading_at_maintenance.data
        entry.total_distance_at_maintenance = total_distance
        entry.description = form.description.data.strip()
        entry.location = form.location.data.strip() if form.location.data else None
        entry.category = form.category.data.strip() if form.category.data else None
        entry.parts_cost = form.parts_cost.data
        entry.labor_cost = form.labor_cost.data
        entry.notes = form.notes.data.strip() if form.notes.data else None

        try:
            _update_reminder_if_applicable(entry)
            db.session.commit()
            flash('整備記録を更新しました。', 'success')
            return redirect(url_for('maintenance.maintenance_log'))
        except Exception as e:
            db.session.rollback()
            flash(f'記録の更新中にエラーが発生しました。詳細は管理者にお問い合わせください。', 'error')
            current_app.logger.error(f"Error updating maintenance entry ID {entry_id}: {e}", exc_info=True)

    elif request.method == 'POST':
        flash('入力内容にエラーがあります。ご確認ください。', 'danger')

    return render_template('maintenance_form.html', form_action='edit', form=form, entry_id=entry.id, category_options=MAINTENANCE_CATEGORIES)


@maintenance_bp.route('/<int:entry_id>/delete', methods=['POST'])
@limiter.limit("30 per hour")
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def delete_maintenance(entry_id):
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    entry = MaintenanceEntry.query.join(Motorcycle).filter(
        MaintenanceEntry.id == entry_id,
        Motorcycle.user_id == current_user.id,
        Motorcycle.is_racer == False
    ).first_or_404()
    # ▲▲▲ 変更ここまで ▲▲▲
    try:
        db.session.delete(entry)
        db.session.commit()
        flash('整備記録を削除しました。', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'記録の削除中にエラーが発生しました。詳細は管理者にお問い合わせください。', 'error')
        current_app.logger.error(f"Error deleting maintenance entry ID {entry_id}: {e}", exc_info=True)
    return redirect(url_for('maintenance.maintenance_log'))

@maintenance_bp.route('/motorcycle/<int:motorcycle_id>/export_csv')
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def export_maintenance_logs_csv(motorcycle_id):
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    motorcycle = Motorcycle.query.filter_by(id=motorcycle_id, user_id=current_user.id, is_racer=False).first_or_404()
    # ▲▲▲ 変更ここまで ▲▲▲
    maintenance_logs = MaintenanceEntry.query.filter_by(motorcycle_id=motorcycle.id).order_by(MaintenanceEntry.maintenance_date.asc(), MaintenanceEntry.total_distance_at_maintenance.asc()).all()
    if not maintenance_logs:
        flash(f'{motorcycle.name}にはエクスポート対象の整備記録がありません。', 'info')
        return redirect(url_for('maintenance.maintenance_log', vehicle_id=motorcycle.id))
    output = io.StringIO()
    writer = csv.writer(output)
    header = ['id', 'motorcycle_id', 'motorcycle_name', 'maintenance_date', 'odometer_reading_at_maintenance', 'total_distance_at_maintenance', 'category', 'description', 'parts_cost', 'labor_cost', 'total_cost', 'location', 'notes']
    writer.writerow(header)
    for record in maintenance_logs:
        total_cost_val = record.total_cost
        row = [record.id, record.motorcycle_id, motorcycle.name, record.maintenance_date.strftime('%Y-%m-%d') if record.maintenance_date else '', record.odometer_reading_at_maintenance, record.total_distance_at_maintenance, record.category if record.category else '', record.description if record.description else '', f"{record.parts_cost:.2f}" if record.parts_cost is not None else '', f"{record.labor_cost:.2f}" if record.labor_cost is not None else '', f"{total_cost_val:.2f}" if total_cost_val is not None else '', record.location if record.location else '', record.notes if record.notes else '']
        writer.writerow(row)
    output.seek(0)
    safe_vehicle_name = "".join(c for c in motorcycle.name if c.isalnum() or c in ['_', '-']).strip()
    if not safe_vehicle_name: safe_vehicle_name = "vehicle"
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    filename = f"motopuppu_maintenance_logs_{safe_vehicle_name}_{motorcycle.id}_{timestamp}.csv"
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment;filename=\"{filename}\"", "Content-Type": "text/csv; charset=utf-8-sig"})

@maintenance_bp.route('/export_all_csv')
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def export_all_maintenance_logs_csv():
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    user_motorcycles_for_maintenance = Motorcycle.query.filter_by(user_id=current_user.id, is_racer=False).all()
    # ▲▲▲ 変更ここまで ▲▲▲
    if not user_motorcycles_for_maintenance:
        flash('エクスポート対象の車両（公道車）が登録されていません。', 'info')
        return redirect(url_for('maintenance.maintenance_log'))

    user_motorcycle_ids_for_maintenance = [m.id for m in user_motorcycles_for_maintenance]
    all_maintenance_logs = MaintenanceEntry.query.filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids_for_maintenance))\
                                                 .options(db.joinedload(MaintenanceEntry.motorcycle))\
                                                 .order_by(MaintenanceEntry.motorcycle_id, MaintenanceEntry.maintenance_date.asc(), MaintenanceEntry.total_distance_at_maintenance.asc()).all()
    if not all_maintenance_logs:
        flash('エクスポート対象の整備記録がありません。', 'info')
        return redirect(url_for('maintenance.maintenance_log'))
    output = io.StringIO()
    writer = csv.writer(output)
    header = [
        'id', 'motorcycle_id', 'motorcycle_name', 'maintenance_date',
        'odometer_reading_at_maintenance', 'total_distance_at_maintenance',
        'category', 'description', 'parts_cost', 'labor_cost', 'total_cost',
        'location', 'notes'
    ]
    writer.writerow(header)
    for record in all_maintenance_logs:
        total_cost_val = record.total_cost
        row = [
            record.id, record.motorcycle_id, record.motorcycle.name,
            record.maintenance_date.strftime('%Y-%m-%d') if record.maintenance_date else '',
            record.odometer_reading_at_maintenance, record.total_distance_at_maintenance,
            record.category if record.category else '', record.description if record.description else '',
            f"{record.parts_cost:.2f}" if record.parts_cost is not None else '',
            f"{record.labor_cost:.2f}" if record.labor_cost is not None else '',
            f"{total_cost_val:.2f}" if total_cost_val is not None else '',
            record.location if record.location else '', record.notes if record.notes else ''
        ]
        writer.writerow(row)
    output.seek(0)
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    filename = f"motopuppu_maintenance_logs_all_vehicles_{timestamp}.csv"
    return Response(
        output.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename=\"{filename}\"", "Content-Type": "text/csv; charset=utf-8-sig"}
    )

@maintenance_bp.route('/get-previous-entry', methods=['GET'])
@limiter.limit("60 per minute")
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def get_previous_maintenance_api():
    motorcycle_id = request.args.get('motorcycle_id', type=int)
    maintenance_date_str = request.args.get('maintenance_date')
    entry_id = request.args.get('entry_id', type=int)

    if not motorcycle_id or not maintenance_date_str:
        return jsonify({'error': 'Missing required parameters'}), 400

    try:
        maintenance_date = date.fromisoformat(maintenance_date_str)
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400

    previous_mainte = get_previous_maintenance_entry(motorcycle_id, maintenance_date, current_entry_id=entry_id)

    if previous_mainte:
        return jsonify({
            'found': True,
            'date': previous_mainte.maintenance_date.strftime('%Y-%m-%d'),
            'odo': f"{previous_mainte.odometer_reading_at_maintenance:,}km"
        })
    else:
        return jsonify({'found': False})