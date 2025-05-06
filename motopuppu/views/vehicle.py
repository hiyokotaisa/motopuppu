# motopuppu/views/vehicle.py

from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, abort, current_app
)
from datetime import date, datetime 
from zoneinfo import ZoneInfo 
# ▼▼▼ 必要なモデルと認証関数をインポート ▼▼▼
from ..models import db, Motorcycle, User, MaintenanceReminder, OdoResetLog 
from .auth import login_required_custom, get_current_user # login_required_custom をインポート

vehicle_bp = Blueprint('vehicle', __name__, url_prefix='/vehicles')

# --- ルート定義 ---

@vehicle_bp.route('/')
@login_required_custom 
def vehicle_list():
    # (変更なし)
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.id).all()
    return render_template('vehicles.html', motorcycles=user_motorcycles)

@vehicle_bp.route('/add', methods=['GET', 'POST'])
@login_required_custom 
def add_vehicle():
    """新しい車両を追加 (100台まで)"""
    # (変更なし)
    current_year = datetime.utcnow().year 

    if request.method == 'POST':
        MAX_VEHICLES = 100
        vehicle_count = Motorcycle.query.filter_by(user_id=g.user.id).count()

        if vehicle_count >= MAX_VEHICLES:
            flash(f'登録できる車両の上限 ({MAX_VEHICLES}台) に達しました。新しい車両を追加できません。', 'warning')
            return redirect(url_for('vehicle.vehicle_list'))

        maker = request.form.get('maker')
        name = request.form.get('name')
        year_str = request.form.get('year')

        if not name:
            flash('車両名は必須です。', 'error')
            return render_template('vehicle_form.html', form_action='add', vehicle=None, current_year=current_year)

        year = None
        if year_str:
            try:
                year = int(year_str)
            except ValueError:
                flash('年式は数値を入力してください。', 'error')
                vehicle_data = {'maker': maker, 'name': name, 'year': year_str}
                return render_template('vehicle_form.html', form_action='add', vehicle=vehicle_data, current_year=current_year)

        new_motorcycle = Motorcycle(
            owner=g.user,
            maker=maker,
            name=name,
            year=year
        )

        if vehicle_count == 0:
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
            vehicle_data = {'maker': maker, 'name': name, 'year': year_str}
            return render_template('vehicle_form.html', form_action='add', vehicle=vehicle_data, current_year=current_year)

    return render_template('vehicle_form.html', form_action='add', vehicle=None, current_year=current_year)


@vehicle_bp.route('/<int:vehicle_id>/edit', methods=['GET', 'POST'])
@login_required_custom 
def edit_vehicle(vehicle_id):
    """既存の車両情報を編集 (リマインダー情報とODOログも渡す)"""
    # (変更なし - odo_logs を取得して渡す処理は前回追加済み)
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=g.user.id).first_or_404()
    reminders = MaintenanceReminder.query.filter_by(motorcycle_id=vehicle_id).order_by(MaintenanceReminder.id).all()
    current_year = datetime.utcnow().year
    
    try:
        jst = ZoneInfo("Asia/Tokyo")
        now_date_iso = datetime.now(jst).date().isoformat()
    except Exception as e: 
        now_date_iso = date.today().isoformat()
        current_app.logger.warning(f"Failed to get JST date using ZoneInfo in edit_vehicle ({e}), falling back to system local date.")

    odo_logs = motorcycle.odo_reset_logs.all() 

    if request.method == 'POST':
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
            return render_template('vehicle_form.html', form_action='edit', vehicle=motorcycle, reminders=reminders, current_year=current_year, now_date_iso=now_date_iso, odo_logs=odo_logs)

        motorcycle.maker = maker
        motorcycle.name = name
        motorcycle.year = year
        try:
            db.session.commit()
            flash(f'車両「{motorcycle.name}」の情報を更新しました。', 'success')
            return redirect(url_for('vehicle.edit_vehicle', vehicle_id=vehicle_id))
        except Exception as e:
            db.session.rollback()
            flash(f'車両情報の更新中にエラーが発生しました: {e}', 'danger')
            current_app.logger.error(f"Error editing vehicle {vehicle_id}: {e}")
            return render_template('vehicle_form.html', form_action='edit', vehicle=motorcycle, reminders=reminders, current_year=current_year, now_date_iso=now_date_iso, odo_logs=odo_logs)
            
    return render_template('vehicle_form.html', form_action='edit', vehicle=motorcycle, reminders=reminders, current_year=current_year, now_date_iso=now_date_iso, odo_logs=odo_logs)


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
        flash(f'車両の削除中にエラーが発生しました: {e}', 'danger')
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
        flash(f'デフォルト車両の設定中にエラーが発生しました: {e}', 'danger')
        current_app.logger.error(f"Error setting default vehicle {vehicle_id}: {e}")
    return redirect(url_for('vehicle.vehicle_list'))

# --- ODOメーターリセット記録 (変更なし - フェーズ1で修正済み) ---
@vehicle_bp.route('/<int:vehicle_id>/record_reset', methods=['POST'])
@login_required_custom 
def record_reset(vehicle_id):
    """ODOメーターリセットを記録"""
    # (変更なし - フェーズ1で確定したロジック)
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=g.user.id).first_or_404()
    
    try:
        jst = ZoneInfo("Asia/Tokyo")
        today_jst = datetime.now(jst).date()
    except Exception as e:
        today_jst = date.today() 
        current_app.logger.warning(f"Failed to get JST date for validation in record_reset ({e}), falling back to system local date.")

    try:
        reset_date_str = request.form.get('reset_date') 
        display_odo_before_reset_str = request.form.get('reading_before_reset')
        display_odo_after_reset_str = request.form.get('reading_after_reset', '0')

        errors = {}
        reset_date_obj = None 
        display_odo_before_reset = None
        display_odo_after_reset = None

        if not reset_date_str:
            errors['reset_date'] = 'リセット日は必須です。'
        else:
            try:
                reset_date_obj = date.fromisoformat(reset_date_str)
                if reset_date_obj > today_jst: 
                    errors['reset_date'] = 'リセット日には未来の日付を指定できません。'
            except ValueError:
                errors['reset_date'] = 'リセット日の形式が無効です (YYYY-MM-DD)。'

        if not display_odo_before_reset_str:
            errors['reading_before_reset'] = 'リセット直前のメーター表示値は必須です。'
        else:
            try:
                display_odo_before_reset = int(display_odo_before_reset_str)
                if display_odo_before_reset < 0:
                    errors['reading_before_reset'] = 'メーター表示値は0以上である必要があります。'
            except ValueError:
                errors['reading_before_reset'] = 'リセット直前のメーター表示値は数値を入力してください。'
        
        try:
            display_odo_after_reset = int(display_odo_after_reset_str)
            if display_odo_after_reset < 0:
                errors['reading_after_reset'] = 'リセット直後のメーター表示値は0以上である必要があります。'
        except ValueError:
            errors['reading_after_reset'] = 'リセット直後のメーター表示値は数値を入力してください。'

        if display_odo_before_reset is not None and display_odo_after_reset is not None:
            if display_odo_before_reset < display_odo_after_reset:
                errors['reading_consistency'] = 'リセット前の値はリセット後の値以上である必要があります。'

        if errors:
            for field, msg in errors.items():
                flash(msg, 'danger') 
        else:
            offset_increment_this_time = display_odo_before_reset - display_odo_after_reset

            new_odo_log = OdoResetLog(
                motorcycle_id=motorcycle.id,
                reset_date=reset_date_obj,
                display_odo_before_reset=display_odo_before_reset,
                display_odo_after_reset=display_odo_after_reset,
                offset_increment=offset_increment_this_time
            )
            db.session.add(new_odo_log)

            motorcycle.odometer_offset = (motorcycle.odometer_offset or 0) + offset_increment_this_time
            
            db.session.commit()
            flash(f'{reset_date_obj.strftime("%Y年%m月%d日")}のODOメーターリセットを記録しました (追加オフセット: {offset_increment_this_time:,} km)。現在の累積オフセット: {motorcycle.odometer_offset:,} km。', 'success')
            return redirect(url_for('vehicle.edit_vehicle', vehicle_id=vehicle_id))

    except Exception as e:
        db.session.rollback() 
        flash(f'リセット記録処理中に予期せぬエラーが発生しました: {e}', 'danger')
        current_app.logger.error(f"Unexpected error in record_reset for vehicle {vehicle_id}: {e}")
    
    return redirect(url_for('vehicle.edit_vehicle', vehicle_id=vehicle_id))

# --- ODOリセット履歴 削除ルート (変更なし - 前回追加済み) ---
@vehicle_bp.route('/odo_reset_log/<int:log_id>/delete', methods=['POST'])
@login_required_custom
def delete_odo_reset_log(log_id):
    """指定されたODOリセットログを削除する"""
    # (変更なし - 前回追加したロジック)
    log_to_delete = db.session.query(OdoResetLog).join(Motorcycle).filter(
        OdoResetLog.id == log_id,
        Motorcycle.user_id == g.user.id
    ).first() 

    if not log_to_delete:
        flash('削除対象の履歴が見つからないか、アクセス権限がありません。', 'danger')
        return redirect(url_for('main.dashboard')) 
        
    motorcycle = log_to_delete.motorcycle 
    offset_to_remove = log_to_delete.offset_increment 
    log_date_str = log_to_delete.reset_date.strftime("%Y年%m月%d日") 

    try:
        db.session.delete(log_to_delete)
        motorcycle.odometer_offset = (motorcycle.odometer_offset or 0) - offset_to_remove
        db.session.commit()
        flash(f'{log_date_str}のリセット履歴を削除しました。累積オフセットが再計算されました。', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'履歴の削除中にエラーが発生しました: {e}', 'danger')
        current_app.logger.error(f"Error deleting OdoResetLog {log_id}: {e}")

    return redirect(url_for('vehicle.edit_vehicle', vehicle_id=motorcycle.id))

# --- ▼▼▼ ODOリセット履歴 編集ルートを追加 ▼▼▼ ---
@vehicle_bp.route('/odo_reset_log/<int:log_id>/edit', methods=['GET', 'POST'])
@login_required_custom
def edit_odo_reset_log(log_id):
    """指定されたODOリセットログを編集する"""
    # ログを取得し、現在のユーザーが所有する車両のログか確認
    log_to_edit = db.session.query(OdoResetLog).join(Motorcycle).filter(
        OdoResetLog.id == log_id,
        Motorcycle.user_id == g.user.id
    ).first_or_404() # 見つからなければ404

    motorcycle = log_to_edit.motorcycle # 関連する車両

    # JSTの今日の日付（バリデーション用）
    try:
        jst = ZoneInfo("Asia/Tokyo")
        today_jst = datetime.now(jst).date()
    except Exception as e:
        today_jst = date.today()
        current_app.logger.warning(f"Failed to get JST date for validation in edit_odo_reset_log ({e}), falling back to system local date.")

    if request.method == 'POST':
        reset_date_str = request.form.get('reset_date')
        display_odo_before_reset_str = request.form.get('display_odo_before_reset')
        display_odo_after_reset_str = request.form.get('display_odo_after_reset')

        errors = {}
        reset_date_obj = None
        display_odo_before_reset = None
        display_odo_after_reset = None

        # --- バリデーション (record_reset と同様) ---
        if not reset_date_str:
            errors['reset_date'] = 'リセット日は必須です。'
        else:
            try:
                reset_date_obj = date.fromisoformat(reset_date_str)
                if reset_date_obj > today_jst:
                    errors['reset_date'] = 'リセット日には未来の日付を指定できません。'
            except ValueError:
                errors['reset_date'] = 'リセット日の形式が無効です (YYYY-MM-DD)。'

        if not display_odo_before_reset_str:
            errors['reading_before_reset'] = 'リセット直前のメーター表示値は必須です。'
        else:
            try:
                display_odo_before_reset = int(display_odo_before_reset_str)
                if display_odo_before_reset < 0:
                    errors['reading_before_reset'] = 'メーター表示値は0以上である必要があります。'
            except ValueError:
                errors['reading_before_reset'] = 'リセット直前のメーター表示値は数値を入力してください。'
        
        if not display_odo_after_reset_str: 
            errors['reading_after_reset'] = 'リセット直後のメーター表示値は必須です。'
        else:
            try:
                display_odo_after_reset = int(display_odo_after_reset_str)
                if display_odo_after_reset < 0:
                    errors['reading_after_reset'] = 'リセット直後のメーター表示値は0以上である必要があります。'
            except ValueError:
                errors['reading_after_reset'] = 'リセット直後のメーター表示値は数値を入力してください。'

        if display_odo_before_reset is not None and display_odo_after_reset is not None:
            if display_odo_before_reset < display_odo_after_reset:
                errors['reading_consistency'] = 'リセット前の値はリセット後の値以上である必要があります。'
        # --- バリデーションここまで ---

        if errors:
            for field, msg in errors.items():
                flash(msg, 'danger')
            # エラー時はフォームを再表示 (テンプレート側で request.form を使う想定)
            return render_template('odo_reset_log_form.html', log=log_to_edit) 
        else:
            # エラーがなければログを更新
            try:
                # 1. OdoResetLog オブジェクトの属性を更新
                log_to_edit.reset_date = reset_date_obj
                log_to_edit.display_odo_before_reset = display_odo_before_reset
                log_to_edit.display_odo_after_reset = display_odo_after_reset
                # 2. offset_increment も再計算して更新
                log_to_edit.offset_increment = display_odo_before_reset - display_odo_after_reset
                
                # 3. Motorcycle の odometer_offset キャッシュをログ全体から再計算して更新
                #    注意: コミット前に再計算メソッドを呼ぶ (セッション内の変更が反映されるはず)
                new_cumulative_offset = motorcycle.calculate_cumulative_offset_from_logs()
                motorcycle.odometer_offset = new_cumulative_offset

                # 4. 変更をコミット
                db.session.commit()
                
                flash(f'{log_to_edit.reset_date.strftime("%Y年%m月%d日")}のリセット履歴を更新しました。累積オフセットが再計算されました。', 'success')
                return redirect(url_for('vehicle.edit_vehicle', vehicle_id=motorcycle.id))

            except Exception as e:
                db.session.rollback()
                flash(f'履歴の更新中にエラーが発生しました: {e}', 'danger')
                current_app.logger.error(f"Error updating OdoResetLog {log_id}: {e}")
                # エラー時もフォームを再表示
                return render_template('odo_reset_log_form.html', log=log_to_edit)

    # GET リクエストの場合: 編集フォームを表示
    return render_template('odo_reset_log_form.html', log=log_to_edit)
# --- ▲▲▲ 編集ルートここまで ▲▲▲ ---

# --- Maintenance Reminder Routes (変更なし) ---
# (add_reminder, edit_reminder, delete_reminder 関数は元のまま。ここでは省略します。)
@vehicle_bp.route('/<int:vehicle_id>/reminders/add', methods=['GET', 'POST'])
@login_required_custom
def add_reminder(vehicle_id):
    # (変更なし)
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=g.user.id).first_or_404()
    current_year = datetime.utcnow().year
    if request.method == 'POST':
        task = request.form.get('task_description', '').strip(); interval_km_str = request.form.get('interval_km')
        interval_months_str = request.form.get('interval_months'); last_done_date_str = request.form.get('last_done_date')
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
            flash('距離または期間のどちらかのサイクルは設定してください。', 'danger'); errors['cycle'] = True
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
                db.session.add(new_reminder); db.session.commit()
                flash(f'リマインダー「{task}」を追加しました。', 'success')
                return redirect(url_for('vehicle.edit_vehicle', vehicle_id=vehicle_id))
            except Exception as e:
                db.session.rollback(); flash(f'リマインダーの追加中にエラーが発生しました: {e}', 'danger')
                current_app.logger.error(f"Error adding reminder for vehicle {vehicle_id}: {e}")
                reminder_data = request.form.to_dict()
                return render_template('reminder_form.html', form_action='add', reminder=reminder_data, motorcycle=motorcycle, current_year=current_year)
    return render_template('reminder_form.html', form_action='add', reminder=None, motorcycle=motorcycle, current_year=current_year)

@vehicle_bp.route('/reminders/<int:reminder_id>/edit', methods=['GET', 'POST'])
@login_required_custom
def edit_reminder(reminder_id):
    # (変更なし)
    reminder = MaintenanceReminder.query.join(Motorcycle).filter(MaintenanceReminder.id == reminder_id, Motorcycle.user_id == g.user.id).first_or_404()
    motorcycle = reminder.motorcycle; current_year = datetime.utcnow().year
    if request.method == 'POST':
        task = request.form.get('task_description', '').strip(); interval_km_str = request.form.get('interval_km')
        interval_months_str = request.form.get('interval_months'); last_done_date_str = request.form.get('last_done_date')
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
            flash('距離または期間のどちらかのサイクルは設定してください。', 'danger'); errors['cycle'] = True
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
                reminder.task_description = task; reminder.interval_km = interval_km; reminder.interval_months = interval_months
                reminder.last_done_date = last_done_date; reminder.last_done_km = last_done_km
                db.session.commit()
                flash(f'リマインダー「{task}」を更新しました。', 'success')
                return redirect(url_for('vehicle.edit_vehicle', vehicle_id=motorcycle.id))
            except Exception as e:
                db.session.rollback(); flash(f'リマインダーの更新中にエラーが発生しました: {e}', 'danger')
                current_app.logger.error(f"Error editing reminder {reminder_id}: {e}")
                return render_template('reminder_form.html', form_action='edit', reminder=reminder, motorcycle=motorcycle, current_year=current_year)
    return render_template('reminder_form.html', form_action='edit', reminder=reminder, motorcycle=motorcycle, current_year=current_year)

@vehicle_bp.route('/reminders/<int:reminder_id>/delete', methods=['POST'])
@login_required_custom
def delete_reminder(reminder_id):
    # (変更なし)
    reminder = MaintenanceReminder.query.join(Motorcycle).filter(MaintenanceReminder.id == reminder_id, Motorcycle.user_id == g.user.id).first_or_404()
    vehicle_id = reminder.motorcycle_id; task_name = reminder.task_description
    try:
        db.session.delete(reminder); db.session.commit()
        flash(f'リマインダー「{task_name}」を削除しました。', 'success')
    except Exception as e:
        db.session.rollback(); flash(f'リマインダーの削除中にエラーが発生しました: {e}', 'danger')
        current_app.logger.error(f"Error deleting reminder {reminder_id}: {e}")
    return redirect(url_for('vehicle.edit_vehicle', vehicle_id=vehicle_id))