from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, abort, current_app
)
from datetime import date # dateオブジェクトのみ使用
from sqlalchemy import or_, asc, desc

from .auth import login_required_custom, get_current_user # ユーザー認証関連
from ..models import db, Motorcycle, MaintenanceEntry, MaintenanceReminder # DBモデル
from ..forms import MaintenanceForm # ★ 作成したMaintenanceFormをインポート

maintenance_bp = Blueprint('maintenance', __name__, url_prefix='/maintenance')

# --- ヘルパー関数: リマインダーの最終実施記録を更新 ---
def _update_reminder_last_done(maintenance_entry: MaintenanceEntry):
    """
    指定された整備記録に基づいて、対応するリマインダーの
    最終実施日と最終実施距離を更新する。
    照合は整備記録のカテゴリとリマインダーのタスク内容で行う (ケースインセンシティブ)。
    """
    # (このヘルパー関数のロジックは変更なし)
    if not maintenance_entry or not maintenance_entry.category:
        current_app.logger.debug(f"Skipping reminder update for maintenance {maintenance_entry.id}: No category.")
        return

    maintenance_category_lower = maintenance_entry.category.strip().lower()
    if not maintenance_category_lower:
        current_app.logger.debug(f"Skipping reminder update for maintenance {maintenance_entry.id}: Empty category after strip/lower.")
        return

    potential_reminders = MaintenanceReminder.query.filter_by(
        motorcycle_id=maintenance_entry.motorcycle_id
    ).all()

    matched_reminder = None
    for reminder in potential_reminders:
        if reminder.task_description and \
           reminder.task_description.strip().lower() == maintenance_category_lower:
            matched_reminder = reminder
            break

    if matched_reminder:
        try:
            update_needed = False
            log_prefix = f"Reminder '{matched_reminder.task_description}' (ID: {matched_reminder.id}) for Maint {maintenance_entry.id}:"

            should_update_date = (matched_reminder.last_done_date is None or
                                  maintenance_entry.maintenance_date >= matched_reminder.last_done_date)

            if should_update_date:
                should_update_km = (matched_reminder.last_done_km is None or
                                    maintenance_entry.maintenance_date > matched_reminder.last_done_date or
                                    (maintenance_entry.maintenance_date == matched_reminder.last_done_date and
                                     (maintenance_entry.total_distance_at_maintenance or 0) >= (matched_reminder.last_done_km or 0)))

                if should_update_km:
                    if matched_reminder.last_done_date != maintenance_entry.maintenance_date or \
                       matched_reminder.last_done_km != maintenance_entry.total_distance_at_maintenance:
                        matched_reminder.last_done_date = maintenance_entry.maintenance_date
                        matched_reminder.last_done_km = maintenance_entry.total_distance_at_maintenance
                        update_needed = True
                        current_app.logger.info(f"{log_prefix} Updating last_done_date to {matched_reminder.last_done_date} and last_done_km to {matched_reminder.last_done_km}")
                elif matched_reminder.last_done_date != maintenance_entry.maintenance_date:
                     matched_reminder.last_done_date = maintenance_entry.maintenance_date
                     update_needed = True
                     current_app.logger.info(f"{log_prefix} Updating last_done_date to {matched_reminder.last_done_date} (KM unchanged).")
            
            if not update_needed and matched_reminder.last_done_date is not None and maintenance_entry.maintenance_date == matched_reminder.last_done_date and \
               matched_reminder.last_done_km is None and maintenance_entry.total_distance_at_maintenance is not None:
                matched_reminder.last_done_km = maintenance_entry.total_distance_at_maintenance
                update_needed = True
                current_app.logger.info(f"{log_prefix} Updating last_done_km to {matched_reminder.last_done_km} (Date was same, KM was missing).")


            if not update_needed:
                 current_app.logger.debug(f"{log_prefix} No update needed for reminder based on this maintenance entry.")
        except Exception as e:
            current_app.logger.error(f"Error updating reminder {matched_reminder.id} for maintenance entry {maintenance_entry.id}: {e}", exc_info=True)
    else:
         current_app.logger.debug(f"No matching reminder found for maintenance category '{maintenance_category_lower}' (Maint ID: {maintenance_entry.id}).")


@maintenance_bp.route('/')
@login_required_custom
def maintenance_log():
    """整備記録の一覧を表示 (フィルター・ソート機能付き)"""
    # (このルートのロジックは変更なし)
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    vehicle_id_str = request.args.get('vehicle_id')
    category_filter = request.args.get('category', '').strip()
    keyword = request.args.get('q', '').strip()
    sort_by = request.args.get('sort_by', 'date')
    order = request.args.get('order', 'desc')
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('MAINTENANCE_ENTRIES_PER_PAGE', 20)

    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    if not user_motorcycles:
        flash('整備記録を閲覧・追加するには、まず車両を登録してください。', 'info')
        return redirect(url_for('vehicle.add_vehicle'))
        
    user_motorcycle_ids = [m.id for m in user_motorcycles]

    query = db.session.query(MaintenanceEntry).join(Motorcycle).filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids))

    request_args_dict = {k: v for k, v in request.args.items() if k not in ['page', 'sort_by', 'order']}

    try:
        if start_date_str:
            query = query.filter(MaintenanceEntry.maintenance_date >= date.fromisoformat(start_date_str))
        if end_date_str:
            query = query.filter(MaintenanceEntry.maintenance_date <= date.fromisoformat(end_date_str))
    except ValueError:
        flash('日付の形式が無効です。YYYY-MM-DD形式で入力してください。', 'warning')
        request_args_dict.pop('start_date', None)
        request_args_dict.pop('end_date', None)

    if vehicle_id_str:
        try:
            vehicle_id = int(vehicle_id_str)
            if vehicle_id in user_motorcycle_ids:
                query = query.filter(MaintenanceEntry.motorcycle_id == vehicle_id)
            else:
                flash('選択された車両は有効ではありません。', 'warning')
                request_args_dict.pop('vehicle_id', None)
        except ValueError:
            request_args_dict.pop('vehicle_id', None)

    if category_filter:
        query = query.filter(MaintenanceEntry.category.ilike(f'%{category_filter}%'))
    
    if keyword:
        search_term = f'%{keyword}%'
        query = query.filter(or_(
            MaintenanceEntry.description.ilike(search_term),
            MaintenanceEntry.location.ilike(search_term),
            MaintenanceEntry.notes.ilike(search_term)
        ))

    sort_column_map = {
        'date': MaintenanceEntry.maintenance_date,
        'vehicle': Motorcycle.name,
        'odo': MaintenanceEntry.total_distance_at_maintenance,
        'category': MaintenanceEntry.category,
    }
    current_sort_by = sort_by if sort_by in sort_column_map else 'date'
    sort_column = sort_column_map.get(current_sort_by)
    current_order = 'desc' if order == 'desc' else 'asc'
    sort_modifier = desc if current_order == 'desc' else asc

    if sort_column:
        if current_sort_by == 'date':
            query = query.order_by(sort_modifier(MaintenanceEntry.maintenance_date), desc(MaintenanceEntry.total_distance_at_maintenance))
        elif current_sort_by == 'odo':
            query = query.order_by(sort_modifier(MaintenanceEntry.total_distance_at_maintenance), desc(MaintenanceEntry.maintenance_date))
        else: 
            query = query.order_by(sort_modifier(sort_column), desc(MaintenanceEntry.maintenance_date))
    else: 
        query = query.order_by(desc(MaintenanceEntry.maintenance_date), desc(MaintenanceEntry.total_distance_at_maintenance))


    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    entries = pagination.items

    return render_template('maintenance_log.html',
                           entries=entries,
                           pagination=pagination,
                           motorcycles=user_motorcycles, 
                           request_args=request_args_dict,
                           current_sort_by=current_sort_by,
                           current_order=current_order
                          )


@maintenance_bp.route('/add', methods=['GET', 'POST'])
@login_required_custom
def add_maintenance():
    """新しい整備記録を追加"""
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    if not user_motorcycles:
        flash('整備記録を追加するには、まず車両を登録してください。', 'warning')
        return redirect(url_for('vehicle.add_vehicle'))

    form = MaintenanceForm()
    form.motorcycle_id.choices = [(m.id, f"{m.name} ({m.maker or 'メーカー不明'})") for m in user_motorcycles]

    if request.method == 'GET':
        default_vehicle = next((m for m in user_motorcycles if m.is_default), user_motorcycles[0] if user_motorcycles else None)
        if default_vehicle:
            form.motorcycle_id.data = default_vehicle.id
        
        preselected_motorcycle_id = request.args.get('motorcycle_id', type=int)
        if preselected_motorcycle_id and any(m.id == preselected_motorcycle_id for m in user_motorcycles):
            form.motorcycle_id.data = preselected_motorcycle_id
            
        form.maintenance_date.data = date.today() 

    if form.validate_on_submit():
        motorcycle = Motorcycle.query.filter_by(id=form.motorcycle_id.data, user_id=g.user.id).first()
        if not motorcycle:
            flash('選択された車両が見つかりません。再度お試しください。', 'danger')
            form.motorcycle_id.choices = [(m.id, f"{m.name} ({m.maker or 'メーカー不明'})") for m in user_motorcycles]
            return render_template('maintenance_form.html', form_action='add', form=form, today_iso=date.today().isoformat())

        # ★ 修正 ★
        # 総走行距離の計算 (ODO + 記録日時点のオフセット)
        offset_at_maintenance_date = motorcycle.calculate_cumulative_offset_from_logs(target_date=form.maintenance_date.data)
        total_distance = form.odometer_reading_at_maintenance.data + offset_at_maintenance_date
        # ★ 修正ここまで ★

        new_entry = MaintenanceEntry(
            motorcycle_id=motorcycle.id,
            maintenance_date=form.maintenance_date.data,
            odometer_reading_at_maintenance=form.odometer_reading_at_maintenance.data,
            total_distance_at_maintenance=total_distance, # ★ 修正された total_distance を使用
            description=form.description.data.strip(),
            location=form.location.data.strip() if form.location.data else None,
            category=form.category.data.strip() if form.category.data else None,
            parts_cost=form.parts_cost.data, 
            labor_cost=form.labor_cost.data, 
            notes=form.notes.data.strip() if form.notes.data else None
        )
        try:
            db.session.add(new_entry)
            _update_reminder_last_done(new_entry) 
            db.session.commit()
            flash('整備記録を追加しました。', 'success')
            return redirect(url_for('maintenance.maintenance_log'))
        except Exception as e:
            db.session.rollback()
            flash(f'記録のデータベース保存中にエラーが発生しました。詳細は管理者にお問い合わせください。', 'error')
            current_app.logger.error(f"Error saving new maintenance entry: {e}", exc_info=True)
            
    elif request.method == 'POST': 
        form.motorcycle_id.choices = [(m.id, f"{m.name} ({m.maker or 'メーカー不明'})") for m in user_motorcycles]

    return render_template('maintenance_form.html',
                           form_action='add',
                           form=form,
                           today_iso=date.today().isoformat() 
                           )


@maintenance_bp.route('/<int:entry_id>/edit', methods=['GET', 'POST'])
@login_required_custom
def edit_maintenance(entry_id):
    """既存の整備記録を編集"""
    entry = MaintenanceEntry.query.filter(MaintenanceEntry.id == entry_id)\
                               .join(Motorcycle).filter(Motorcycle.user_id == g.user.id)\
                               .first_or_404()
    
    form = MaintenanceForm(obj=entry) 
    form.motorcycle_id.choices = [(entry.motorcycle.id, f"{entry.motorcycle.name} ({entry.motorcycle.maker or 'メーカー不明'})")]
    form.motorcycle_id.data = entry.motorcycle.id 

    if form.validate_on_submit():
        motorcycle = entry.motorcycle 

        # ★ 修正 ★
        # 総走行距離の計算 (ODO + 記録日時点のオフセット)
        offset_at_maintenance_date = motorcycle.calculate_cumulative_offset_from_logs(target_date=form.maintenance_date.data)
        total_distance = form.odometer_reading_at_maintenance.data + offset_at_maintenance_date
        # ★ 修正ここまで ★

        entry.maintenance_date = form.maintenance_date.data
        entry.odometer_reading_at_maintenance = form.odometer_reading_at_maintenance.data
        entry.total_distance_at_maintenance = total_distance # ★ 修正された total_distance を使用
        entry.description = form.description.data.strip()
        entry.location = form.location.data.strip() if form.location.data else None
        entry.category = form.category.data.strip() if form.category.data else None
        entry.parts_cost = form.parts_cost.data
        entry.labor_cost = form.labor_cost.data
        entry.notes = form.notes.data.strip() if form.notes.data else None
        
        try:
            _update_reminder_last_done(entry) 
            db.session.commit()
            flash('整備記録を更新しました。', 'success')
            return redirect(url_for('maintenance.maintenance_log'))
        except Exception as e:
            db.session.rollback()
            flash(f'記録の更新中にエラーが発生しました。詳細は管理者にお問い合わせください。', 'error')
            current_app.logger.error(f"Error updating maintenance entry ID {entry_id}: {e}", exc_info=True)

    elif request.method == 'POST': 
        form.motorcycle_id.choices = [(entry.motorcycle.id, f"{entry.motorcycle.name} ({entry.motorcycle.maker or 'メーカー不明'})")]
        form.motorcycle_id.data = entry.motorcycle.id

    return render_template('maintenance_form.html',
                           form_action='edit',
                           form=form,
                           entry_id=entry.id, 
                           today_iso=date.today().isoformat()
                           )


@maintenance_bp.route('/<int:entry_id>/delete', methods=['POST'])
@login_required_custom
def delete_maintenance(entry_id):
    """整備記録を削除"""
    # (このルートのロジックは変更なし)
    entry = MaintenanceEntry.query.filter(MaintenanceEntry.id == entry_id)\
                               .join(Motorcycle).filter(Motorcycle.user_id == g.user.id)\
                               .first_or_404()
    try:
        db.session.delete(entry)
        db.session.commit()
        flash('整備記録を削除しました。', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'記録の削除中にエラーが発生しました。詳細は管理者にお問い合わせください。', 'error')
        current_app.logger.error(f"Error deleting maintenance entry ID {entry_id}: {e}", exc_info=True)
    return redirect(url_for('maintenance.maintenance_log'))