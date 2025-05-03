# motopuppu/views/vehicle.py
from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, abort, current_app
)
# ▼▼▼ datetime をインポート ▼▼▼
from datetime import date, datetime
# ログイン必須デコレータと現在のユーザー取得関数
from .auth import login_required_custom, get_current_user
# データベースモデルとdbオブジェクト
from ..models import db, Motorcycle, User, MaintenanceReminder

# 'vehicle' という名前でBlueprintオブジェクトを作成
vehicle_bp = Blueprint('vehicle', __name__, url_prefix='/vehicles')

# --- ルート定義 ---

@vehicle_bp.route('/')
@login_required_custom
def vehicle_list():
    """登録されている車両の一覧を表示"""
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.id).all()
    return render_template('vehicles.html', motorcycles=user_motorcycles)

@vehicle_bp.route('/add', methods=['GET', 'POST'])
@login_required_custom
def add_vehicle():
    """新しい車両を追加"""
    # ▼▼▼ 現在年を取得 ▼▼▼
    current_year = datetime.utcnow().year
    if request.method == 'POST':
        maker = request.form.get('maker')
        name = request.form.get('name')
        year_str = request.form.get('year')
        if not name:
            flash('車両名は必須です。', 'error')
            # ▼▼▼ current_year を渡す ▼▼▼
            return render_template('vehicle_form.html', form_action='add', vehicle=None, current_year=current_year)
        year = None
        if year_str:
            try:
                year = int(year_str)
            except ValueError:
                flash('年式は数値を入力してください。', 'error')
                vehicle_data = {'maker': maker, 'name': name, 'year': year_str}
                # ▼▼▼ current_year を渡す ▼▼▼
                return render_template('vehicle_form.html', form_action='add', vehicle=vehicle_data, current_year=current_year)
        new_motorcycle = Motorcycle(owner=g.user, maker=maker, name=name, year=year)
        existing_vehicles_count = Motorcycle.query.filter_by(user_id=g.user.id).count()
        if existing_vehicles_count == 0:
            new_motorcycle.is_default = True
        try:
            db.session.add(new_motorcycle)
            db.session.commit()
            flash(f'車両「{new_motorcycle.name}」を登録しました。', 'success')
            return redirect(url_for('vehicle.vehicle_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'車両の登録中にエラーが発生しました: {e}', 'error')
            current_app.logger.error(f"Error adding vehicle: {e}")
            # POSTエラー時にもフォーム表示が必要な場合があるが、現状はリダイレクトなので不要

    # GETリクエストの場合
    # ▼▼▼ current_year を渡す ▼▼▼
    return render_template('vehicle_form.html', form_action='add', vehicle=None, current_year=current_year)


# --- 車両編集画面 ---
@vehicle_bp.route('/<int:vehicle_id>/edit', methods=['GET', 'POST'])
@login_required_custom
def edit_vehicle(vehicle_id):
    """既存の車両情報を編集 (リマインダー情報も渡す)"""
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=g.user.id).first_or_404()
    reminders = MaintenanceReminder.query.filter_by(motorcycle_id=vehicle_id).order_by(MaintenanceReminder.id).all()
    # ▼▼▼ 現在年を取得 ▼▼▼
    current_year = datetime.utcnow().year

    if request.method == 'POST':
        # --- 車両基本情報の更新処理 ---
        maker = request.form.get('maker')
        name = request.form.get('name')
        year_str = request.form.get('year')
        errors = {}
        if not name: errors['name'] = '車両名は必須です。'
        year = None
        if year_str:
            try: year = int(year_str)
            except ValueError: errors['year'] = '年式は数値を入力してください。'

        if errors:
            for field, msg in errors.items(): flash(msg, 'danger')
            # ▼▼▼ current_year を渡す ▼▼▼
            return render_template('vehicle_form.html', form_action='edit', vehicle=motorcycle, reminders=reminders, current_year=current_year)

        motorcycle.maker = maker
        motorcycle.name = name
        motorcycle.year = year
        try:
            db.session.commit()
            flash(f'車両「{motorcycle.name}」の情報を更新しました。', 'success')
            return redirect(url_for('vehicle.edit_vehicle', vehicle_id=vehicle_id))
        except Exception as e:
            db.session.rollback()
            flash(f'車両情報の更新中にエラーが発生しました: {e}', 'error')
            current_app.logger.error(f"Error editing vehicle {vehicle_id}: {e}")
             # ▼▼▼ current_year を渡す ▼▼▼
            return render_template('vehicle_form.html', form_action='edit', vehicle=motorcycle, reminders=reminders, current_year=current_year)

    # --- GETリクエストの場合 ---
    # ▼▼▼ current_year を渡す ▼▼▼
    return render_template('vehicle_form.html', form_action='edit', vehicle=motorcycle, reminders=reminders, current_year=current_year)


@vehicle_bp.route('/<int:vehicle_id>/delete', methods=['POST'])
@login_required_custom
def delete_vehicle(vehicle_id):
    """車両を削除"""
    # (変更なし)
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=g.user.id).first_or_404()
    try:
        was_default = motorcycle.is_default
        vehicle_name = motorcycle.name
        db.session.delete(motorcycle)
        if was_default:
             other_vehicle = Motorcycle.query.filter(Motorcycle.user_id == g.user.id, Motorcycle.id != vehicle_id).first()
             if other_vehicle: other_vehicle.is_default = True
        db.session.commit()
        flash(f'車両「{vehicle_name}」を削除しました。', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'車両の削除中にエラーが発生しました: {e}', 'error')
        current_app.logger.error(f"Error deleting vehicle {vehicle_id}: {e}")
    return redirect(url_for('vehicle.vehicle_list'))

@vehicle_bp.route('/<int:vehicle_id>/set_default', methods=['POST'])
@login_required_custom
def set_default_vehicle(vehicle_id):
    """指定された車両をデフォルトに設定"""
    # (変更なし)
    target_vehicle = Motorcycle.query.filter_by(id=vehicle_id, user_id=g.user.id).first_or_404()
    try:
        Motorcycle.query.filter(Motorcycle.user_id == g.user.id, Motorcycle.id != vehicle_id).update({'is_default': False})
        target_vehicle.is_default = True
        db.session.commit()
        flash(f'車両「{target_vehicle.name}」をデフォルトに設定しました。', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'デフォルト車両の設定中にエラーが発生しました: {e}', 'error')
        current_app.logger.error(f"Error setting default vehicle {vehicle_id}: {e}")
    return redirect(url_for('vehicle.vehicle_list'))

@vehicle_bp.route('/<int:vehicle_id>/record_reset', methods=['POST'])
@login_required_custom
def record_reset(vehicle_id):
    """ODOメーターリセットを記録"""
    # (変更なし)
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=g.user.id).first_or_404()
    try:
        reading_before_reset_str = request.form.get('reading_before_reset')
        reading_after_reset_str = request.form.get('reading_after_reset', '0')
        if not reading_before_reset_str: flash('リセット直前のメーター表示値は必須です。', 'error')
        else:
            try:
                reading_before_reset = int(reading_before_reset_str)
                reading_after_reset = int(reading_after_reset_str)
                if reading_before_reset < 0 or reading_after_reset < 0: raise ValueError("走行距離は0以上である必要があります。")
                if reading_before_reset < reading_after_reset: raise ValueError("リセット前の値はリセット後の値以上である必要があります。")
                added_offset = reading_before_reset - reading_after_reset
                motorcycle.odometer_offset += added_offset
                db.session.commit()
                flash(f'ODOメーターリセットを記録しました (オフセット: {motorcycle.odometer_offset} km)。', 'success')
                return redirect(url_for('vehicle.edit_vehicle', vehicle_id=vehicle_id))
            except ValueError as e: db.session.rollback(); flash(f'入力値が無効です: {e}', 'error')
            except Exception as e: db.session.rollback(); flash(f'リセット記録中にエラーが発生しました: {e}', 'error'); current_app.logger.error(f"Error recording odometer reset for vehicle {vehicle_id}: {e}")
    except Exception as e: flash(f'リセット記録処理中に予期せぬエラーが発生しました: {e}', 'error'); current_app.logger.error(f"Unexpected error in record_reset for vehicle {vehicle_id}: {e}")
    return redirect(url_for('vehicle.edit_vehicle', vehicle_id=vehicle_id))


# --- ▼▼▼ Maintenance Reminder Routes ▼▼▼ ---
# (変更なし、前の回答と同じ)
# --- リマインダー追加 ---
@vehicle_bp.route('/<int:vehicle_id>/reminders/add', methods=['GET', 'POST'])
@login_required_custom
def add_reminder(vehicle_id):
    """車両に新しいメンテナンスリマインダーを追加"""
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=g.user.id).first_or_404()
    # ▼▼▼ 現在年を取得 (reminder_form.htmlで使う可能性は低いが念のため) ▼▼▼
    current_year = datetime.utcnow().year
    if request.method == 'POST':
        task = request.form.get('task_description', '').strip()
        interval_km_str = request.form.get('interval_km')
        interval_months_str = request.form.get('interval_months')
        last_done_date_str = request.form.get('last_done_date')
        last_done_km_str = request.form.get('last_done_km')
        errors = {}; interval_km=None; interval_months=None; last_done_date=None; last_done_km=None
        if not task: errors['task_description'] = 'リマインド内容は必須です。'
        if interval_km_str:
            try:
                interval_km = int(interval_km_str)
                if interval_km <= 0: errors['interval_km'] = '距離サイクルは0より大きい値を入力してください。'
            except ValueError: errors['interval_km'] = '距離サイクルは数値を入力してください。'
        if interval_months_str:
            try:
                interval_months = int(interval_months_str)
                if interval_months <= 0: errors['interval_months'] = '期間サイクルは0より大きい値を入力してください。'
            except ValueError: errors['interval_months'] = '期間サイクルは数値を入力してください。'
        if interval_km is None and interval_months is None:
            flash('距離または期間のどちらかのサイクルは設定してください。', 'danger')
            errors['cycle'] = True
        if last_done_date_str:
            try: last_done_date = date.fromisoformat(last_done_date_str)
            except ValueError: errors['last_done_date'] = '最終実施日は有効な日付形式 (YYYY-MM-DD) で入力してください。'
        if last_done_km_str:
            try:
                last_done_km = int(last_done_km_str)
                if last_done_km < 0: errors['last_done_km'] = '最終実施距離は0以上の値を入力してください。'
            except ValueError: errors['last_done_km'] = '最終実施距離は数値を入力してください。'
        for field, msg in errors.items():
            if field != 'cycle': flash(msg, 'danger')
        if errors:
            reminder_data = request.form.to_dict()
            return render_template('reminder_form.html', form_action='add', reminder=reminder_data, motorcycle=motorcycle, current_year=current_year)
        else:
            new_reminder = MaintenanceReminder(motorcycle_id=vehicle_id, task_description=task, interval_km=interval_km, interval_months=interval_months, last_done_date=last_done_date, last_done_km=last_done_km)
            try:
                db.session.add(new_reminder)
                db.session.commit()
                flash(f'リマインダー「{task}」を追加しました。', 'success')
                return redirect(url_for('vehicle.edit_vehicle', vehicle_id=vehicle_id))
            except Exception as e:
                db.session.rollback()
                flash(f'リマインダーの追加中にエラーが発生しました: {e}', 'danger')
                current_app.logger.error(f"Error adding reminder for vehicle {vehicle_id}: {e}")
                reminder_data = request.form.to_dict()
                return render_template('reminder_form.html', form_action='add', reminder=reminder_data, motorcycle=motorcycle, current_year=current_year)
    return render_template('reminder_form.html', form_action='add', reminder=None, motorcycle=motorcycle, current_year=current_year)

# --- リマインダー編集 ---
@vehicle_bp.route('/reminders/<int:reminder_id>/edit', methods=['GET', 'POST'])
@login_required_custom
def edit_reminder(reminder_id):
    """既存のメンテナンスリマインダーを編集"""
    reminder = MaintenanceReminder.query.join(Motorcycle).filter(MaintenanceReminder.id == reminder_id, Motorcycle.user_id == g.user.id).first_or_404()
    motorcycle = reminder.motorcycle
    # ▼▼▼ 現在年を取得 (reminder_form.htmlで使う可能性は低いが念のため) ▼▼▼
    current_year = datetime.utcnow().year
    if request.method == 'POST':
        task = request.form.get('task_description', '').strip()
        interval_km_str = request.form.get('interval_km')
        interval_months_str = request.form.get('interval_months')
        last_done_date_str = request.form.get('last_done_date')
        last_done_km_str = request.form.get('last_done_km')
        errors = {}; interval_km=None; interval_months=None; last_done_date=None; last_done_km=None
        if not task: errors['task_description'] = 'リマインド内容は必須です。'
        if interval_km_str:
            try:
                interval_km = int(interval_km_str)
                if interval_km <= 0: errors['interval_km'] = '距離サイクルは0より大きい値を入力してください。'
            except ValueError: errors['interval_km'] = '距離サイクルは数値を入力してください。'
        if interval_months_str:
            try:
                interval_months = int(interval_months_str)
                if interval_months <= 0: errors['interval_months'] = '期間サイクルは0より大きい値を入力してください。'
            except ValueError: errors['interval_months'] = '期間サイクルは数値を入力してください。'
        if interval_km is None and interval_months is None:
            flash('距離または期間のどちらかのサイクルは設定してください。', 'danger')
            errors['cycle'] = True
        if last_done_date_str:
            try: last_done_date = date.fromisoformat(last_done_date_str)
            except ValueError: errors['last_done_date'] = '最終実施日は有効な日付形式 (YYYY-MM-DD) で入力してください。'
        if last_done_km_str:
            try:
                last_done_km = int(last_done_km_str)
                if last_done_km < 0: errors['last_done_km'] = '最終実施距離は0以上の値を入力してください。'
            except ValueError: errors['last_done_km'] = '最終実施距離は数値を入力してください。'
        for field, msg in errors.items():
            if field != 'cycle': flash(msg, 'danger')
        if errors:
            return render_template('reminder_form.html', form_action='edit', reminder=reminder, motorcycle=motorcycle, current_year=current_year)
        else:
            try:
                reminder.task_description = task
                reminder.interval_km = interval_km
                reminder.interval_months = interval_months
                reminder.last_done_date = last_done_date
                reminder.last_done_km = last_done_km
                db.session.commit()
                flash(f'リマインダー「{task}」を更新しました。', 'success')
                return redirect(url_for('vehicle.edit_vehicle', vehicle_id=motorcycle.id))
            except Exception as e:
                db.session.rollback()
                flash(f'リマインダーの更新中にエラーが発生しました: {e}', 'danger')
                current_app.logger.error(f"Error editing reminder {reminder_id}: {e}")
                return render_template('reminder_form.html', form_action='edit', reminder=reminder, motorcycle=motorcycle, current_year=current_year)
    return render_template('reminder_form.html', form_action='edit', reminder=reminder, motorcycle=motorcycle, current_year=current_year)

# --- リマインダー削除 ---
@vehicle_bp.route('/reminders/<int:reminder_id>/delete', methods=['POST'])
@login_required_custom
def delete_reminder(reminder_id):
    """メンテナンスリマインダーを削除"""
    reminder = MaintenanceReminder.query.join(Motorcycle).filter(MaintenanceReminder.id == reminder_id, Motorcycle.user_id == g.user.id).first_or_404()
    vehicle_id = reminder.motorcycle_id
    task_name = reminder.task_description
    try:
        db.session.delete(reminder)
        db.session.commit()
        flash(f'リマインダー「{task_name}」を削除しました。', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'リマインダーの削除中にエラーが発生しました: {e}', 'danger')
        current_app.logger.error(f"Error deleting reminder {reminder_id}: {e}")
    return redirect(url_for('vehicle.edit_vehicle', vehicle_id=vehicle_id))

# --- ▲▲▲ Maintenance Reminder Routes ▲▲▲ ---