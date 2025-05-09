# motopuppu/views/vehicle.py

from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, abort, current_app
)
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from ..models import db, Motorcycle, User, MaintenanceReminder, OdoResetLog
from .auth import login_required_custom, get_current_user
from ..forms import VehicleForm, OdoResetLogForm, ReminderForm
# 実績評価モジュールとイベントタイプをインポート
from ..achievement_evaluator import check_achievements_for_event, EVENT_ADD_VEHICLE, EVENT_ADD_ODO_RESET

vehicle_bp = Blueprint('vehicle', __name__, url_prefix='/vehicles')

# --- ルート定義 ---
@vehicle_bp.route('/')
@login_required_custom
def vehicle_list():
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    return render_template('vehicles.html', motorcycles=user_motorcycles)

@vehicle_bp.route('/add', methods=['GET', 'POST'])
@login_required_custom
def add_vehicle():
    form = VehicleForm()
    current_year_for_validation = datetime.now(timezone.utc).year

    if form.validate_on_submit():
        MAX_VEHICLES = 100
        vehicle_count_before_add = Motorcycle.query.filter_by(user_id=g.user.id).count() # 追加前のカウント

        if vehicle_count_before_add >= MAX_VEHICLES:
            flash(f'登録できる車両の上限 ({MAX_VEHICLES}台) に達しました。新しい車両を追加できません。', 'warning')
            return redirect(url_for('vehicle.vehicle_list'))

        new_motorcycle = Motorcycle(
            user_id=g.user.id,
            maker=form.maker.data.strip() if form.maker.data else None,
            name=form.name.data.strip(),
            year=form.year.data
        )

        if vehicle_count_before_add == 0:
            new_motorcycle.is_default = True
        else:
            new_motorcycle.is_default = False
        
        try:
            db.session.add(new_motorcycle)
            db.session.commit() # まずメインの処理をコミット
            flash(f'車両「{new_motorcycle.name}」を登録しました。', 'success')

            # ▼▼▼ コミット成功後に実績評価を呼び出し ▼▼▼
            # event_data は必要に応じて追加された車両IDなどを渡せる
            event_data_for_ach = {'new_vehicle_id': new_motorcycle.id, 'vehicle_count_after_add': vehicle_count_before_add + 1}
            check_achievements_for_event(g.user, EVENT_ADD_VEHICLE, event_data=event_data_for_ach)
            # ▲▲▲ 実績評価の呼び出し ▲▲▲
            
            return redirect(url_for('vehicle.vehicle_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'車両の登録中にエラーが発生しました。詳細は管理者にお問い合わせください。', 'error')
            current_app.logger.error(f"Error adding vehicle for user {g.user.id}: {e}", exc_info=True)
            
    elif request.method == 'POST':
        pass

    return render_template('vehicle_form.html',
                           form_action='add',
                           form=form,
                           current_year=current_year_for_validation
                           )


@vehicle_bp.route('/<int:vehicle_id>/edit', methods=['GET', 'POST'])
@login_required_custom
def edit_vehicle(vehicle_id):
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=g.user.id).first_or_404()
    form = VehicleForm(obj=motorcycle)
    odo_form = OdoResetLogForm() 
    
    try:
        jst = ZoneInfo("Asia/Tokyo")
        today_jst_iso = datetime.now(jst).date().isoformat()
    except Exception:
        today_jst_iso = date.today().isoformat()
        current_app.logger.warning("ZoneInfo('Asia/Tokyo') not available, falling back to system local date for odo_form default.")
    
    if request.method == 'GET':
        odo_form.reset_date.data = date.fromisoformat(today_jst_iso)
        odo_form.display_odo_after_reset.data = 0

    current_year_for_validation = datetime.now(timezone.utc).year
    reminders = MaintenanceReminder.query.filter_by(motorcycle_id=vehicle_id).order_by(MaintenanceReminder.task_description, MaintenanceReminder.id).all()
    odo_logs = OdoResetLog.query.filter_by(motorcycle_id=vehicle_id).order_by(OdoResetLog.reset_date.desc(), OdoResetLog.id.desc()).all()

    if form.submit.data and form.validate_on_submit(): 
        motorcycle.maker = form.maker.data.strip() if form.maker.data else None
        motorcycle.name = form.name.data.strip()
        motorcycle.year = form.year.data
        try:
            db.session.commit()
            flash(f'車両「{motorcycle.name}」の情報を更新しました。', 'success')
            return redirect(url_for('vehicle.edit_vehicle', vehicle_id=vehicle_id)) 
        except Exception as e:
            db.session.rollback()
            flash(f'車両情報の更新中にエラーが発生しました。詳細は管理者にお問い合わせください。', 'danger')
            current_app.logger.error(f"Error editing vehicle ID {vehicle_id}: {e}", exc_info=True)
    elif request.method == 'POST' and form.submit.data: 
        pass
            
    return render_template('vehicle_form.html',
                           form_action='edit',
                           form=form, 
                           odo_form=odo_form, 
                           vehicle=motorcycle,
                           reminders=reminders,
                           odo_logs=odo_logs,
                           current_year=current_year_for_validation,
                           now_date_iso=today_jst_iso
                           )


@vehicle_bp.route('/<int:vehicle_id>/delete', methods=['POST'])
@login_required_custom
def delete_vehicle(vehicle_id):
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=g.user.id).first_or_404()
    try:
        was_default = motorcycle.is_default
        vehicle_name = motorcycle.name
        
        MaintenanceReminder.query.filter_by(motorcycle_id=motorcycle.id).delete(synchronize_session=False)
        OdoResetLog.query.filter_by(motorcycle_id=motorcycle.id).delete(synchronize_session=False)
        
        db.session.delete(motorcycle) 
        
        if was_default: 
             other_vehicle = Motorcycle.query.filter(Motorcycle.user_id == g.user.id).order_by(Motorcycle.id).first()
             if other_vehicle:
                 other_vehicle.is_default = True 
        db.session.commit()
        flash(f'車両「{vehicle_name}」と関連データを削除しました。', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'車両の削除中にエラーが発生しました: {e}', 'danger')
        current_app.logger.error(f"Error deleting vehicle ID {vehicle_id}: {e}", exc_info=True)
    return redirect(url_for('vehicle.vehicle_list'))

@vehicle_bp.route('/<int:vehicle_id>/set_default', methods=['POST'])
@login_required_custom
def set_default_vehicle(vehicle_id):
    target_vehicle = Motorcycle.query.filter_by(id=vehicle_id, user_id=g.user.id).first_or_404()
    try:
        Motorcycle.query.filter(Motorcycle.user_id == g.user.id, Motorcycle.id != vehicle_id).update({'is_default': False}, synchronize_session='fetch')
        target_vehicle.is_default = True
        db.session.commit()
        flash(f'車両「{target_vehicle.name}」をデフォルトに設定しました。', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'デフォルト車両の設定中にエラーが発生しました: {e}', 'danger')
        current_app.logger.error(f"Error setting default vehicle ID {vehicle_id}: {e}", exc_info=True)
    return redirect(url_for('vehicle.vehicle_list'))

@vehicle_bp.route('/<int:vehicle_id>/odo_reset_log/add', methods=['GET', 'POST'])
@login_required_custom
def add_odo_reset_log(vehicle_id): 
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=g.user.id).first_or_404()
    form = OdoResetLogForm()

    if request.method == 'GET':
        try:
            jst = ZoneInfo("Asia/Tokyo") 
            form.reset_date.data = datetime.now(jst).date()
        except Exception:
            form.reset_date.data = date.today() 
        form.display_odo_after_reset.data = 0

    if form.validate_on_submit(): 
        offset_increment_this_time = form.display_odo_before_reset.data - form.display_odo_after_reset.data

        new_odo_log = OdoResetLog(
            motorcycle_id=motorcycle.id, 
            reset_date=form.reset_date.data,
            display_odo_before_reset=form.display_odo_before_reset.data,
            display_odo_after_reset=form.display_odo_after_reset.data,
            offset_increment=offset_increment_this_time,
            created_at=datetime.now(timezone.utc) 
        )
        db.session.add(new_odo_log)
        
        motorcycle.odometer_offset = motorcycle.calculate_cumulative_offset_from_logs() 
        db.session.add(motorcycle) 
        
        try:
            db.session.commit() # まずメインの処理をコミット
            flash(f'{new_odo_log.reset_date.strftime("%Y年%m月%d日")}の過去のリセット履歴を追加しました (オフセット増分: {offset_increment_this_time:,} km)。現在の累積オフセット: {motorcycle.odometer_offset:,} km。', 'success')

            # ▼▼▼ コミット成功後に実績評価を呼び出し ▼▼▼
            event_data_for_ach = {'new_odo_log_id': new_odo_log.id, 'motorcycle_id': motorcycle.id}
            check_achievements_for_event(g.user, EVENT_ADD_ODO_RESET, event_data=event_data_for_ach)
            # ▲▲▲ 実績評価の呼び出し ▲▲▲

            return redirect(url_for('vehicle.edit_vehicle', vehicle_id=motorcycle.id))
        except Exception as e:
             db.session.rollback()
             flash(f'履歴の追加中にエラーが発生しました: {e}', 'danger')
             current_app.logger.error(f"Error adding OdoResetLog for vehicle {vehicle_id}: {e}", exc_info=True)
    
    elif request.method == 'POST': 
        pass
    
    try:
        jst = ZoneInfo("Asia/Tokyo")
        now_date_iso_for_template = datetime.now(jst).date().isoformat()
    except Exception:
        now_date_iso_for_template = date.today().isoformat()

    return render_template('odo_reset_log_form.html', 
                           form=form,
                           form_action='add', 
                           vehicle_name=motorcycle.name,
                           cancel_url=url_for('vehicle.edit_vehicle', vehicle_id=motorcycle.id),
                           now_date_iso=now_date_iso_for_template
                           )


@vehicle_bp.route('/odo_reset_log/<int:log_id>/delete', methods=['POST'])
@login_required_custom
def delete_odo_reset_log(log_id):
    log_to_delete = db.session.query(OdoResetLog).join(Motorcycle).filter(
        OdoResetLog.id == log_id,
        Motorcycle.user_id == g.user.id
    ).first_or_404()

    motorcycle = log_to_delete.motorcycle
    log_date_str = log_to_delete.reset_date.strftime("%Y年%m月%d日")

    try:
        db.session.delete(log_to_delete)
        motorcycle.odometer_offset = motorcycle.calculate_cumulative_offset_from_logs()
        db.session.add(motorcycle) 
        db.session.commit()
        flash(f'{log_date_str}のリセット履歴を削除しました。累積オフセットが再計算されました。現在の累積オフセット: {motorcycle.odometer_offset:,} km。', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'履歴の削除中にエラーが発生しました: {e}', 'danger')
        current_app.logger.error(f"Error deleting OdoResetLog ID {log_id}: {e}", exc_info=True)

    return redirect(url_for('vehicle.edit_vehicle', vehicle_id=motorcycle.id))


@vehicle_bp.route('/odo_reset_log/<int:log_id>/edit', methods=['GET', 'POST'])
@login_required_custom
def edit_odo_reset_log(log_id):
    log_to_edit = db.session.query(OdoResetLog).join(Motorcycle).filter(
        OdoResetLog.id == log_id,
        Motorcycle.user_id == g.user.id
    ).first_or_404()
    motorcycle = log_to_edit.motorcycle
    
    form = OdoResetLogForm(obj=log_to_edit)

    if form.validate_on_submit():
        form.populate_obj(log_to_edit) 
        log_to_edit.offset_increment = form.display_odo_before_reset.data - form.display_odo_after_reset.data
        
        motorcycle.odometer_offset = motorcycle.calculate_cumulative_offset_from_logs()
        db.session.add(motorcycle) 
        try:
            db.session.commit()
            flash(f'{log_to_edit.reset_date.strftime("%Y年%m月%d日")}のリセット履歴を更新しました。累積オフセットが再計算されました。', 'success')
            return redirect(url_for('vehicle.edit_vehicle', vehicle_id=motorcycle.id))
        except Exception as e:
            db.session.rollback()
            flash(f'履歴の更新中にエラーが発生しました: {e}', 'danger')
            current_app.logger.error(f"Error updating OdoResetLog {log_id}: {e}", exc_info=True)
    elif request.method == 'POST': 
        pass

    try:
        jst = ZoneInfo("Asia/Tokyo")
        now_date_iso_for_template = datetime.now(jst).date().isoformat()
    except Exception:
        now_date_iso_for_template = date.today().isoformat()

    return render_template('odo_reset_log_form.html',
                           form=form,
                           form_action='edit', 
                           vehicle_name=motorcycle.name,
                           cancel_url=url_for('vehicle.edit_vehicle', vehicle_id=motorcycle.id),
                           now_date_iso=now_date_iso_for_template)


# --- Maintenance Reminder Routes ---
@vehicle_bp.route('/<int:vehicle_id>/reminders/add', methods=['GET', 'POST'])
@login_required_custom
def add_reminder(vehicle_id):
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=g.user.id).first_or_404()
    form = ReminderForm() 

    if form.validate_on_submit():
        new_reminder = MaintenanceReminder(motorcycle_id=vehicle_id)
        form.populate_obj(new_reminder)
        if new_reminder.task_description:
            new_reminder.task_description = new_reminder.task_description.strip()
        try:
            db.session.add(new_reminder)
            db.session.commit()
            flash(f'リマインダー「{new_reminder.task_description}」を追加しました。', 'success')
            return redirect(url_for('vehicle.edit_vehicle', vehicle_id=vehicle_id))
        except Exception as e:
            db.session.rollback()
            flash(f'リマインダーの追加中にエラーが発生しました: {e}', 'danger')
            current_app.logger.error(f"Error adding reminder for vehicle {vehicle_id}: {e}", exc_info=True)
    elif request.method == 'POST': 
        pass
    
    current_year_for_template = datetime.now(timezone.utc).year
    return render_template('reminder_form.html',
                           form=form, 
                           form_action='add',
                           motorcycle=motorcycle,
                           current_year=current_year_for_template)

@vehicle_bp.route('/reminders/<int:reminder_id>/edit', methods=['GET', 'POST'])
@login_required_custom
def edit_reminder(reminder_id):
    reminder = MaintenanceReminder.query.join(Motorcycle).filter(
        MaintenanceReminder.id == reminder_id,
        Motorcycle.user_id == g.user.id
    ).first_or_404()
    motorcycle = reminder.motorcycle
    form = ReminderForm(obj=reminder) 

    if form.validate_on_submit():
        form.populate_obj(reminder) 
        if reminder.task_description:
            reminder.task_description = reminder.task_description.strip()
        try:
            db.session.commit()
            flash(f'リマインダー「{reminder.task_description}」を更新しました。', 'success')
            return redirect(url_for('vehicle.edit_vehicle', vehicle_id=motorcycle.id))
        except Exception as e:
            db.session.rollback()
            flash(f'リマインダーの更新中にエラーが発生しました: {e}', 'danger')
            current_app.logger.error(f"Error editing reminder {reminder_id}: {e}", exc_info=True)
    elif request.method == 'POST': 
        pass

    current_year_for_template = datetime.now(timezone.utc).year
    return render_template('reminder_form.html',
                           form=form, 
                           form_action='edit',
                           motorcycle=motorcycle, 
                           reminder_id=reminder.id, 
                           current_year=current_year_for_template)

@vehicle_bp.route('/reminders/<int:reminder_id>/delete', methods=['POST'])
@login_required_custom
def delete_reminder(reminder_id):
    reminder = MaintenanceReminder.query.join(Motorcycle).filter(
        MaintenanceReminder.id == reminder_id,
        Motorcycle.user_id == g.user.id
    ).first_or_404()
    vehicle_id = reminder.motorcycle_id
    task_name = reminder.task_description
    try:
        db.session.delete(reminder)
        db.session.commit()
        flash(f'リマインダー「{task_name}」を削除しました。', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'リマインダーの削除中にエラーが発生しました: {e}', 'danger')
        current_app.logger.error(f"Error deleting reminder {reminder_id}: {e}", exc_info=True)
    return redirect(url_for('vehicle.edit_vehicle', vehicle_id=vehicle_id))