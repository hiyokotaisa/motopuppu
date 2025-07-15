# motopuppu/views/vehicle.py
from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, abort, current_app
)
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo # Python 3.9+
# --- ▼▼▼ 変更 ▼▼▼ ---
from sqlalchemy import func
from ..models import db, User, Motorcycle, MaintenanceReminder, OdoResetLog, MaintenanceEntry, ActivityLog
# --- ▲▲▲ 変更 ▲▲▲ ---
from .auth import login_required_custom, get_current_user
from ..forms import VehicleForm, OdoResetLogForm, ReminderForm
# 実績評価モジュールとイベントタイプをインポート
from ..achievement_evaluator import check_achievements_for_event, EVENT_ADD_VEHICLE, EVENT_ADD_ODO_RESET

vehicle_bp = Blueprint('vehicle', __name__, url_prefix='/vehicles')

# --- ルート定義 ---
@vehicle_bp.route('/')
@login_required_custom
def vehicle_list():
    # --- ▼▼▼ 変更点 ▼▼▼ ---
    # N+1問題を避けるため、活動ログの件数をサブクエリで効率的に取得する
    activity_counts_subquery = db.session.query(
        ActivityLog.motorcycle_id,
        func.count(ActivityLog.id).label('activity_log_count')
    ).group_by(ActivityLog.motorcycle_id).subquery()

    # 車両情報と活動ログ件数を外部結合で取得
    motorcycles_with_counts = db.session.query(
        Motorcycle,
        activity_counts_subquery.c.activity_log_count
    ).outerjoin(
        activity_counts_subquery, Motorcycle.id == activity_counts_subquery.c.motorcycle_id
    ).filter(
        Motorcycle.user_id == g.user.id
    ).order_by(
        Motorcycle.is_default.desc(), Motorcycle.name
    ).all()

    # テンプレートで扱いやすいように、Motorcycleオブジェクトに件数をプロパティとして追加
    user_motorcycles = []
    for motorcycle, count in motorcycles_with_counts:
        motorcycle.activity_log_count = count or 0 # レコードがない場合は0
        user_motorcycles.append(motorcycle)
    # --- ▲▲▲ 変更点 ▲▲▲ ---

    return render_template('vehicles.html', motorcycles=user_motorcycles)

@vehicle_bp.route('/add', methods=['GET', 'POST'])
@login_required_custom
def add_vehicle():
    form = VehicleForm()
    current_year_for_validation = datetime.now(timezone.utc).year

    if form.validate_on_submit():
        MAX_VEHICLES = 100 # 定数として定義されているのは良い
        vehicle_count_before_add = Motorcycle.query.filter_by(user_id=g.user.id).count()

        if vehicle_count_before_add >= MAX_VEHICLES:
            flash(f'登録できる車両の上限 ({MAX_VEHICLES}台) に達しました。新しい車両を追加できません。', 'warning')
            return redirect(url_for('vehicle.vehicle_list'))

        # --- ▼▼▼ フェーズ1変更点 (is_racer と total_operating_hours の処理追加) ▼▼▼
        is_racer_vehicle = form.is_racer.data
        total_hours_data = form.total_operating_hours.data

        new_motorcycle = Motorcycle(
            user_id=g.user.id,
            maker=form.maker.data.strip() if form.maker.data else None,
            name=form.name.data.strip(),
            year=form.year.data,
            is_racer=is_racer_vehicle
        )

        if is_racer_vehicle:
            new_motorcycle.total_operating_hours = total_hours_data if total_hours_data is not None else 0.00
            new_motorcycle.odometer_offset = 0 # レーサー車両はODOオフセットを0に固定
        else:
            new_motorcycle.total_operating_hours = None # 公道車は総稼働時間を使用しない
            # odometer_offset はデフォルトの0が設定される
        # --- ▲▲▲ フェーズ1変更点 ▲▲▲ ---

        if vehicle_count_before_add == 0:
            new_motorcycle.is_default = True
        else:
            new_motorcycle.is_default = False

        try:
            db.session.add(new_motorcycle)
            db.session.commit() # 先に車両をコミットしてIDを確定させる

            # --- ▼▼▼ 変更点 ▼▼▼ ---
            initial_odo = form.initial_odometer.data
            if not new_motorcycle.is_racer and initial_odo is not None and initial_odo >= 0:
                initial_maint_entry = MaintenanceEntry(
                    motorcycle_id=new_motorcycle.id,
                    maintenance_date=date.today(), # 登録日を整備日とする
                    odometer_reading_at_maintenance=initial_odo,
                    total_distance_at_maintenance=initial_odo, # 新規登録なのでオフセットは0
                    description="システム: 車両登録時の初期ODOメーター値", # 説明を変更
                    category="システム登録", # カテゴリを変更
                    parts_cost=0,
                    labor_cost=0
                )
                db.session.add(initial_maint_entry)
                db.session.commit() # 初期記録もコミット
                flash(f'車両「{new_motorcycle.name}」を登録し、初期ODOメーター値 ({initial_odo:,}km) を記録しました。', 'success')
            else:
                flash(f'車両「{new_motorcycle.name}」({"レーサー" if new_motorcycle.is_racer else "公道車"})を登録しました。', 'success')
            # --- ▲▲▲ 変更点 ▲▲▲ ---


            # --- ▼▼▼ フェーズ1変更点 (実績評価のevent_dataにis_racerとレーサー車両カウント情報を追加検討) ▼▼▼
            racer_vehicle_count_after_add = 0
            if new_motorcycle.is_racer:
                    racer_vehicle_count_after_add = Motorcycle.query.filter_by(user_id=g.user.id, is_racer=True).count()

            event_data_for_ach = {
                'new_vehicle_id': new_motorcycle.id,
                'vehicle_count_after_add': vehicle_count_before_add + 1,
                'is_racer': new_motorcycle.is_racer, # is_racer情報を追加
                'racer_vehicle_count_after_add': racer_vehicle_count_after_add # レーサー車両の場合のみカウント
            }
            check_achievements_for_event(g.user, EVENT_ADD_VEHICLE, event_data=event_data_for_ach)
            # --- ▲▲▲ フェーズ1変更点 ▲▲▲ ---

            return redirect(url_for('vehicle.vehicle_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'車両の登録中にエラーが発生しました。詳細は管理者にお問い合わせください。', 'error')
            current_app.logger.error(f"Error adding vehicle for user {g.user.id}: {e}", exc_info=True)

    elif request.method == 'POST': # バリデーション失敗時
        flash('入力内容にエラーがあります。ご確認ください。', 'danger')


    return render_template('vehicle_form.html',
                           form_action='add',
                           form=form,
                           current_year=current_year_for_validation
                           )


@vehicle_bp.route('/<int:vehicle_id>/edit', methods=['GET', 'POST'])
@login_required_custom
def edit_vehicle(vehicle_id):
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=g.user.id).first_or_404()
    # --- ▼▼▼ フェーズ1変更点 (is_racer の値を保持) ▼▼▼
    original_is_racer = motorcycle.is_racer # 編集前の is_racer の値を保持
    # --- ▲▲▲ フェーズ1変更点 ▲▲▲ ---

    form = VehicleForm(obj=motorcycle)
    odo_form = OdoResetLogForm() # ODOリセットフォームは変更なし

    try:
        jst = ZoneInfo("Asia/Tokyo")
        today_jst_iso = datetime.now(jst).date().isoformat()
    except Exception:
        today_jst_iso = date.today().isoformat()
        current_app.logger.warning("ZoneInfo('Asia/Tokyo') not available, falling back to system local date for odo_form default.")

    if request.method == 'GET':
        # --- ▼▼▼ フェーズ1変更点 (is_racer の値をフォームに設定。テンプレートでdisabledにする想定) ▼▼▼
        form.is_racer.data = motorcycle.is_racer
        if motorcycle.is_racer:
            form.total_operating_hours.data = motorcycle.total_operating_hours
        # --- ▲▲▲ フェーズ1変更点 ▲▲▲ ---
        if not motorcycle.is_racer: # 公道車の場合のみODOフォームのデフォルト値を設定
            odo_form.reset_date.data = date.fromisoformat(today_jst_iso)
            odo_form.display_odo_after_reset.data = 0


    current_year_for_validation = datetime.now(timezone.utc).year
    reminders = MaintenanceReminder.query.filter_by(motorcycle_id=vehicle_id).order_by(MaintenanceReminder.task_description, MaintenanceReminder.id).all()
    odo_logs = OdoResetLog.query.filter_by(motorcycle_id=vehicle_id).order_by(OdoResetLog.reset_date.desc(), OdoResetLog.id.desc()).all()

    if form.submit.data and form.validate_on_submit():
        motorcycle.maker = form.maker.data.strip() if form.maker.data else None
        motorcycle.name = form.name.data.strip()
        motorcycle.year = form.year.data

        # --- ▼▼▼ フェーズ1変更点 (is_racer は変更不可とし、total_operating_hours を更新) ▼▼▼
        motorcycle.is_racer = original_is_racer # フォームからの値ではなく、DBの値を維持

        if motorcycle.is_racer: # is_racer は original_is_racer を参照
            motorcycle.total_operating_hours = form.total_operating_hours.data if form.total_operating_hours.data is not None else motorcycle.total_operating_hours
        # else: # 公道車両の場合、total_operating_hours は None のまま or 更新しない
        #     motorcycle.total_operating_hours = None # 明示的にNoneにするか、何もしない
        # --- ▲▲▲ フェーズ1変更点 ▲▲▲ ---

        try:
            db.session.commit()
            flash(f'車両「{motorcycle.name}」の情報を更新しました。', 'success')
            return redirect(url_for('vehicle.edit_vehicle', vehicle_id=vehicle_id))
        except Exception as e:
            db.session.rollback()
            flash(f'車両情報の更新中にエラーが発生しました。詳細は管理者にお問い合わせください。', 'danger')
            current_app.logger.error(f"Error editing vehicle ID {vehicle_id}: {e}", exc_info=True)
    elif request.method == 'POST' and form.submit.data: # バリデーション失敗時
        flash('入力内容にエラーがあります。ご確認ください。', 'danger')
        # is_racer の値は original_is_racer を維持するため、フォームに再設定しておく
        form.is_racer.data = original_is_racer


    return render_template('vehicle_form.html',
                           form_action='edit',
                           form=form,
                           odo_form=odo_form,
                           vehicle=motorcycle,
                           reminders=reminders,
                           odo_logs=odo_logs,
                           current_year=current_year_for_validation,
                           now_date_iso=today_jst_iso,
                           is_racer_vehicle=motorcycle.is_racer # テンプレートでの表示制御用
                           )


@vehicle_bp.route('/<int:vehicle_id>/delete', methods=['POST'])
@login_required_custom
def delete_vehicle(vehicle_id):
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=g.user.id).first_or_404()
    try:
        was_default = motorcycle.is_default
        vehicle_name = motorcycle.name

        # 関連データの削除 (MaintenanceReminder, OdoResetLog は既存のまま)
        # FuelEntry, MaintenanceEntry, GeneralNote なども Motorcycle の cascade="all, delete-orphan" で削除される
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
    # --- ▼▼▼ フェーズ1変更点 (レーサー車両はODOリセット不可) ▼▼▼ ---
    if motorcycle.is_racer:
        flash('レーサー車両にはODOメーターリセット機能はご利用いただけません。', 'warning')
        return redirect(url_for('vehicle.edit_vehicle', vehicle_id=motorcycle.id))
    # --- ▲▲▲ フェーズ1変更点 ▲▲▲ ---
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
            db.session.commit()
            flash(f'{new_odo_log.reset_date.strftime("%Y年%m月%d日")}の過去のリセット履歴を追加しました (オフセット増分: {offset_increment_this_time:,} km)。現在の累積オフセット: {motorcycle.odometer_offset:,} km。', 'success')

            event_data_for_ach = {'new_odo_log_id': new_odo_log.id, 'motorcycle_id': motorcycle.id}
            check_achievements_for_event(g.user, EVENT_ADD_ODO_RESET, event_data=event_data_for_ach)

            return redirect(url_for('vehicle.edit_vehicle', vehicle_id=motorcycle.id))
        except Exception as e:
                db.session.rollback()
                flash(f'履歴の追加中にエラーが発生しました: {e}', 'danger')
                current_app.logger.error(f"Error adding OdoResetLog for vehicle {vehicle_id}: {e}", exc_info=True)

    elif request.method == 'POST': # バリデーション失敗時
        flash('入力内容にエラーがあります。ご確認ください。', 'danger')

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
    # --- ▼▼▼ フェーズ1変更点 (レーサー車両はODOリセット不可 - 通常このルートには来ないはずだが念のため) ▼▼▼ ---
    if motorcycle.is_racer:
        flash('不正な操作です。レーサー車両にODOリセットログは存在しません。', 'danger')
        return redirect(url_for('vehicle.edit_vehicle', vehicle_id=motorcycle.id))
    # --- ▲▲▲ フェーズ1変更点 ▲▲▲ ---
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
    # --- ▼▼▼ フェーズ1変更点 (レーサー車両はODOリセット不可) ▼▼▼ ---
    if motorcycle.is_racer:
        flash('不正な操作です。レーサー車両のODOリセットログは編集できません。', 'danger')
        return redirect(url_for('vehicle.edit_vehicle', vehicle_id=motorcycle.id))
    # --- ▲▲▲ フェーズ1変更点 ▲▲▲ ---

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
    elif request.method == 'POST': # バリデーション失敗時
        flash('入力内容にエラーがあります。ご確認ください。', 'danger')


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

    # 整備記録をプルダウンの選択肢として設定するファクトリ関数
    def get_maintenance_entries():
        # 公道車のみ整備記録を持つ
        if motorcycle.is_racer:
            return []
        return MaintenanceEntry.query.filter_by(motorcycle_id=motorcycle.id).order_by(MaintenanceEntry.maintenance_date.desc(), MaintenanceEntry.id.desc())
    
    form.maintenance_entry.query_factory = get_maintenance_entries

    if form.validate_on_submit():
        new_reminder = MaintenanceReminder(motorcycle_id=vehicle_id)
        
        # フォームの値をモデルに設定
        new_reminder.task_description = form.task_description.data.strip() if form.task_description.data else None
        new_reminder.interval_km = form.interval_km.data
        new_reminder.interval_months = form.interval_months.data

        # 整備記録との連携処理
        selected_entry = form.maintenance_entry.data
        if selected_entry:
            new_reminder.last_maintenance_entry_id = selected_entry.id
            new_reminder.last_done_date = selected_entry.maintenance_date
            new_reminder.last_done_km = selected_entry.total_distance_at_maintenance
        else:
            new_reminder.last_maintenance_entry_id = None
            new_reminder.last_done_date = form.last_done_date.data
            new_reminder.last_done_km = form.last_done_km.data

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
        flash('入力内容にエラーがあります。ご確認ください。', 'danger')

    # カテゴリのサジェストリストを作成
    category_suggestions = [
        cat[0] for cat in db.session.query(MaintenanceEntry.category).filter(
            MaintenanceEntry.category.isnot(None),
            MaintenanceEntry.category != ''
        ).distinct().all()
    ]

    # --- ▼▼▼ ここから修正 ▼▼▼ ---
    # JavaScriptで使うための整備記録リストを取得
    maintenance_entries_for_js = get_maintenance_entries()
    
    return render_template('reminder_form.html',
                           form=form,
                           form_action='add',
                           motorcycle=motorcycle,
                           category_suggestions=category_suggestions,
                           maintenance_entries_for_js=maintenance_entries_for_js) # テンプレートに渡す
    # --- ▲▲▲ ここまで修正 ▲▲▲ ---


@vehicle_bp.route('/reminders/<int:reminder_id>/edit', methods=['GET', 'POST'])
@login_required_custom
def edit_reminder(reminder_id):
    reminder = MaintenanceReminder.query.join(Motorcycle).filter(
        MaintenanceReminder.id == reminder_id,
        Motorcycle.user_id == g.user.id
    ).first_or_404()
    motorcycle = reminder.motorcycle
    form = ReminderForm(obj=reminder)

    # 整備記録をプルダウンの選択肢として設定するファクトリ関数
    def get_maintenance_entries():
        if motorcycle.is_racer:
            return []
        return MaintenanceEntry.query.filter_by(motorcycle_id=motorcycle.id).order_by(MaintenanceEntry.maintenance_date.desc(), MaintenanceEntry.id.desc())

    form.maintenance_entry.query_factory = get_maintenance_entries
    
    # GETリクエスト時、連携されている整備記録があればフォームに設定
    if request.method == 'GET':
        form.maintenance_entry.data = reminder.last_maintenance_entry

    if form.validate_on_submit():
        # フォームの値をモデルに設定
        reminder.task_description = form.task_description.data.strip() if form.task_description.data else None
        reminder.interval_km = form.interval_km.data
        reminder.interval_months = form.interval_months.data

        # 整備記録との連携処理
        selected_entry = form.maintenance_entry.data
        if selected_entry:
            reminder.last_maintenance_entry_id = selected_entry.id
            reminder.last_done_date = selected_entry.maintenance_date
            reminder.last_done_km = selected_entry.total_distance_at_maintenance
        else:
            reminder.last_maintenance_entry_id = None
            reminder.last_done_date = form.last_done_date.data
            reminder.last_done_km = form.last_done_km.data
            
        try:
            db.session.commit()
            flash(f'リマインダー「{reminder.task_description}」を更新しました。', 'success')
            return redirect(url_for('vehicle.edit_vehicle', vehicle_id=motorcycle.id))
        except Exception as e:
            db.session.rollback()
            flash(f'リマインダーの更新中にエラーが発生しました: {e}', 'danger')
            current_app.logger.error(f"Error editing reminder {reminder_id}: {e}", exc_info=True)
    elif request.method == 'POST':
        flash('入力内容にエラーがあります。ご確認ください。', 'danger')

    # カテゴリのサジェストリストを作成
    category_suggestions = [
        cat[0] for cat in db.session.query(MaintenanceEntry.category).filter(
            MaintenanceEntry.category.isnot(None),
            MaintenanceEntry.category != ''
        ).distinct().all()
    ]

    # --- ▼▼▼ ここから修正 ▼▼▼ ---
    # JavaScriptで使うための整備記録リストを取得
    maintenance_entries_for_js = get_maintenance_entries()

    return render_template('reminder_form.html',
                           form=form,
                           form_action='edit',
                           motorcycle=motorcycle,
                           reminder_id=reminder.id,
                           category_suggestions=category_suggestions,
                           maintenance_entries_for_js=maintenance_entries_for_js) # テンプレートに渡す
    # --- ▲▲▲ ここまで修正 ▲▲▲ ---

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