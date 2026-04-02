# motopuppu/views/vehicle.py
import uuid
from flask import (
    Blueprint, flash, redirect, render_template, request, url_for, abort, current_app, jsonify
)
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import func
# ▼▼▼ インポート文を修正 ▼▼▼
from flask_login import login_required, current_user
# ▲▲▲ 変更ここまで ▲▲▲
# ▼▼▼【ここから変更】削除対象のモデルをインポート ▼▼▼
from ..models import (
    db, User, Motorcycle, MaintenanceReminder, OdoResetLog, MaintenanceEntry, ActivityLog,
    GeneralNote, Event, FuelEntry, SessionLog, TouringLog, SettingSheet
)
# ▲▲▲【変更はここまで】▲▲▲
from ..forms import VehicleForm, OdoResetLogForm
from ..achievement_evaluator import check_achievements_for_event, EVENT_ADD_VEHICLE, EVENT_ADD_ODO_RESET
from ..utils.image_security import process_and_upload_image
from .. import services, limiter


vehicle_bp = Blueprint('vehicle', __name__, url_prefix='/vehicles')

# --- ルート定義 ---
@vehicle_bp.route('/')
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def vehicle_list():
    activity_counts_subquery = db.session.query(
        ActivityLog.motorcycle_id,
        func.count(ActivityLog.id).label('activity_log_count')
    ).group_by(ActivityLog.motorcycle_id).subquery()

    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    motorcycles_with_counts = db.session.query(
        Motorcycle,
        activity_counts_subquery.c.activity_log_count
    ).outerjoin(
        activity_counts_subquery, Motorcycle.id == activity_counts_subquery.c.motorcycle_id
    ).filter(
        Motorcycle.user_id == current_user.id
    ).order_by(
        Motorcycle.is_archived.asc(), Motorcycle.is_default.desc(), Motorcycle.name
    ).all()
    # ▲▲▲ 変更ここまで ▲▲▲

    user_motorcycles = []
    for motorcycle, count in motorcycles_with_counts:
        motorcycle.activity_log_count = count or 0
        if not motorcycle.is_racer:
            motorcycle.avg_kpl = services.calculate_average_kpl(motorcycle)
        else:
            motorcycle.avg_kpl = None
        user_motorcycles.append(motorcycle)

    return render_template('vehicles.html', motorcycles=user_motorcycles)

@vehicle_bp.route('/add', methods=['GET', 'POST'])
@limiter.limit("30 per hour")
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def add_vehicle():
    form = VehicleForm()
    current_year_for_validation = datetime.now(timezone.utc).year

    if form.validate_on_submit():
        MAX_VEHICLES = 100
        # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
        vehicle_count_before_add = Motorcycle.query.filter_by(user_id=current_user.id).count()
        # ▲▲▲ 変更ここまで ▲▲▲

        if vehicle_count_before_add >= MAX_VEHICLES:
            flash(f'登録できる車両の上限 ({MAX_VEHICLES}台) に達しました。新しい車両を追加できません。', 'warning')
            return redirect(url_for('vehicle.vehicle_list'))

        is_racer_vehicle = form.is_racer.data
        total_hours_data = form.total_operating_hours.data

        final_image_url = form.image_url.data
        if form.image_file.data:
            try:
                uploaded_url = process_and_upload_image(form.image_file.data, current_user.id)
                if uploaded_url:
                    final_image_url = uploaded_url
            except ValueError as e:
                flash(str(e), 'warning')
            except Exception as e:
                flash('画像のアップロードに失敗しました。', 'warning')

        new_motorcycle = Motorcycle(
            # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
            user_id=current_user.id,
            # ▲▲▲ 変更ここまで ▲▲▲
            maker=form.maker.data.strip() if form.maker.data else None,
            name=form.name.data.strip(),
            year=form.year.data,
            is_racer=is_racer_vehicle,
            # ▼▼▼ ここから追記 ▼▼▼
            show_in_garage=form.show_in_garage.data,
            image_url=final_image_url,
            custom_details=form.custom_details.data
            # ▲▲▲ 追記ここまで ▲▲▲
        )
        
        # --- ▼▼▼ 変更箇所（ここから） ▼▼▼ ---
        # 駆動系データをフォームから取得して設定
        new_motorcycle.primary_ratio = form.primary_ratio.data

        ratios = {}
        for i in range(1, 8): # 7速まで対応
            field_name = f'gear_ratio_{i}'
            field = getattr(form, field_name)
            if field.data is not None:
                ratios[str(i)] = float(field.data)
        
        new_motorcycle.gear_ratios = ratios if ratios else None
        # --- ▲▲▲ 変更箇所（ここまで） ▲▲▲ ---

        if is_racer_vehicle:
            new_motorcycle.total_operating_hours = total_hours_data if total_hours_data is not None else 0.00
            new_motorcycle.odometer_offset = 0
        else:
            new_motorcycle.total_operating_hours = None

        if vehicle_count_before_add == 0:
            new_motorcycle.is_default = True
        else:
            new_motorcycle.is_default = False

        try:
            db.session.add(new_motorcycle)
            db.session.commit()

            initial_odo = form.initial_odometer.data
            if not new_motorcycle.is_racer and initial_odo is not None and initial_odo >= 0:
                initial_maint_entry = MaintenanceEntry(
                    motorcycle_id=new_motorcycle.id,
                    maintenance_date=date.today(),
                    odometer_reading_at_maintenance=initial_odo,
                    total_distance_at_maintenance=initial_odo,
                    description="システム: 車両登録時の初期ODOメーター値",
                    category="システム登録",
                    parts_cost=0,
                    labor_cost=0
                )
                db.session.add(initial_maint_entry)
                db.session.commit()
                flash(f'車両「{new_motorcycle.name}」を登録し、初期ODOメーター値 ({initial_odo:,}km) を記録しました。', 'success')
            else:
                flash(f'車両「{new_motorcycle.name}」({"レーサー" if new_motorcycle.is_racer else "公道車"})を登録しました。', 'success')

            racer_vehicle_count_after_add = 0
            if new_motorcycle.is_racer:
                    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
                    racer_vehicle_count_after_add = Motorcycle.query.filter_by(user_id=current_user.id, is_racer=True).count()
                    # ▲▲▲ 変更ここまで ▲▲▲

            event_data_for_ach = {
                'new_vehicle_id': new_motorcycle.id,
                'vehicle_count_after_add': vehicle_count_before_add + 1,
                'is_racer': new_motorcycle.is_racer,
                'racer_vehicle_count_after_add': racer_vehicle_count_after_add
            }
            # ▼▼▼ g.user を current_user に変更 ▼▼▼
            check_achievements_for_event(current_user, EVENT_ADD_VEHICLE, event_data=event_data_for_ach)
            # ▲▲▲ 変更ここまで ▲▲▲
            
            # ▼▼▼【ここから変更】最初の車両登録後、ダッシュボードツアーにリダイレクト ▼▼▼
            if vehicle_count_before_add == 0:
                return redirect(url_for('main.dashboard', tutorial_completed='1'))
            else:
                return redirect(url_for('vehicle.vehicle_list'))
            # ▲▲▲【変更はここまで】▲▲▲

        except Exception as e:
            db.session.rollback()
            flash(f'車両の登録中にエラーが発生しました。詳細は管理者にお問い合わせください。', 'error')
            # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
            current_app.logger.error(f"Error adding vehicle for user {current_user.id}: {e}", exc_info=True)
            # ▲▲▲ 変更ここまで ▲▲▲

    elif request.method == 'POST':
        flash('入力内容にエラーがあります。ご確認ください。', 'danger')

    start_vehicle_tutorial = not current_user.completed_tutorials.get('vehicle_form', False)
    
    return render_template('vehicle_form.html',
                           form_action='add',
                           form=form,
                           current_year=current_year_for_validation,
                           start_vehicle_tutorial=start_vehicle_tutorial)

@vehicle_bp.route('/<int:vehicle_id>/edit', methods=['GET', 'POST'])
@limiter.limit("30 per hour")
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def edit_vehicle(vehicle_id):
    # ▼▼▼【ここから変更】 first_or_444 を first_or_404 に修正 ▼▼▼
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=current_user.id).first_or_404()
    # ▲▲▲【変更はここまで】▲▲▲
    original_is_racer = motorcycle.is_racer
    form = VehicleForm(obj=motorcycle)
    odo_form = OdoResetLogForm()

    try:
        jst = ZoneInfo("Asia/Tokyo")
        today_jst_iso = datetime.now(jst).date().isoformat()
    except Exception:
        today_jst_iso = date.today().isoformat()
        current_app.logger.warning("ZoneInfo('Asia/Tokyo') not available, falling back to system local date for odo_form default.")

    if request.method == 'GET':
        form.is_racer.data = motorcycle.is_racer
        if motorcycle.is_racer:
            form.total_operating_hours.data = motorcycle.total_operating_hours
        if not motorcycle.is_racer:
            odo_form.reset_date.data = date.fromisoformat(today_jst_iso)
            odo_form.display_odo_after_reset.data = 0
            
        # --- ▼▼▼ 変更箇所（ここから） ▼▼▼ ---
        # DBのJSONからフォームの各ギア比フィールドに値を設定
        if motorcycle.gear_ratios:
            for i in range(1, 8): # 7速まで対応
                field_name = f'gear_ratio_{i}'
                field = getattr(form, field_name)
                if str(i) in motorcycle.gear_ratios:
                    field.data = motorcycle.gear_ratios[str(i)]
        # --- ▲▲▲ 変更箇所（ここまで） ▲▲▲ ---

    current_year_for_validation = datetime.now(timezone.utc).year
    odo_logs = OdoResetLog.query.filter_by(motorcycle_id=vehicle_id).order_by(OdoResetLog.reset_date.desc(), OdoResetLog.id.desc()).all()

    if form.submit.data and form.validate_on_submit():
        motorcycle.maker = form.maker.data.strip() if form.maker.data else None
        motorcycle.name = form.name.data.strip()
        motorcycle.year = form.year.data
        motorcycle.is_racer = original_is_racer

        # ▼▼▼ ここから変更 ▼▼▼
        final_image_url = form.image_url.data
        if form.image_file.data:
            try:
                uploaded_url = process_and_upload_image(form.image_file.data, current_user.id)
                if uploaded_url:
                    # ▼▼▼【ここから追記】新画像のアップロード成功後、旧GCS画像を削除 ▼▼▼
                    from ..utils.image_security import delete_gcs_image
                    old_image_url = motorcycle.image_url
                    if old_image_url and old_image_url != uploaded_url:
                        delete_gcs_image(old_image_url)
                    # ▲▲▲【追記はここまで】▲▲▲
                    final_image_url = uploaded_url
            except ValueError as e:
                flash(str(e), 'warning')
            except Exception as e:
                flash('画像のアップロードに失敗しました。', 'warning')

        motorcycle.show_in_garage = form.show_in_garage.data
        motorcycle.image_url = final_image_url
        motorcycle.custom_details = form.custom_details.data
        # ▲▲▲ 変更ここまで ▲▲▲

        # --- ▼▼▼ 変更箇所（ここから） ▼▼▼ ---
        # 駆動系データをフォームから取得して設定
        motorcycle.primary_ratio = form.primary_ratio.data

        ratios = {}
        for i in range(1, 8): # 7速まで対応
            field_name = f'gear_ratio_{i}'
            field = getattr(form, field_name)
            if field.data is not None:
                ratios[str(i)] = float(field.data)
        
        motorcycle.gear_ratios = ratios if ratios else None
        # --- ▲▲▲ 変更箇所（ここまで） ▲▲▲ ---

        if motorcycle.is_racer:
            motorcycle.total_operating_hours = form.total_operating_hours.data if form.total_operating_hours.data is not None else motorcycle.total_operating_hours

        try:
            db.session.commit()
            flash(f'車両「{motorcycle.name}」の情報を更新しました。', 'success')
            return redirect(url_for('vehicle.edit_vehicle', vehicle_id=vehicle_id))
        except Exception as e:
            db.session.rollback()
            flash(f'車両情報の更新中にエラーが発生しました。詳細は管理者にお問い合わせください。', 'danger')
            current_app.logger.error(f"Error editing vehicle ID {vehicle_id}: {e}", exc_info=True)
    elif request.method == 'POST' and form.submit.data:
        flash('入力内容にエラーがあります。ご確認ください。', 'danger')
        form.is_racer.data = original_is_racer

    # ▼▼▼【ここから修正】チュートリアル用の変数を定義 ▼▼▼
    # 編集ページではチュートリアルを自動開始しないため False 固定でも良いが、
    # 「？」ボタンでの手動開始機能を考慮し、追加ページとロジックを合わせておく
    start_vehicle_tutorial = not current_user.completed_tutorials.get('vehicle_form', False)
    # ▲▲▲【修正はここまで】▲▲▲

    return render_template('vehicle_form.html',
                           form_action='edit',
                           form=form,
                           odo_form=odo_form,
                           vehicle=motorcycle,
                           odo_logs=odo_logs,
                           current_year=current_year_for_validation,
                           now_date_iso=today_jst_iso,
                           is_racer_vehicle=motorcycle.is_racer,
                           # ▼▼▼【ここから修正】テンプレートに変数を渡す ▼▼▼
                           start_vehicle_tutorial=start_vehicle_tutorial)
                           # ▲▲▲【修正はここまで】▲▲▲

@vehicle_bp.route('/<int:vehicle_id>/delete', methods=['POST'])
@limiter.limit("30 per hour")
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def delete_vehicle(vehicle_id):
    # ▼▼▼【ここから変更】 first_or_444 を first_or_404 に修正 ▼▼▼
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=current_user.id).first_or_404()
    # ▲▲▲【変更はここまで】▲▲▲
    
    # ▼▼▼【ここから変更】関連データを明示的に削除する処理を修正 ▼▼▼
    try:
        was_default = motorcycle.is_default
        vehicle_name = motorcycle.name

        # ▼▼▼【ここから追記】車両削除前にGCS上の画像を削除してオーファンを防ぐ ▼▼▼
        if motorcycle.image_url:
            from ..utils.image_security import delete_gcs_image
            delete_gcs_image(motorcycle.image_url)
        # ▲▲▲【追記はここまで】▲▲▲

        # ondelete='SET NULL' が設定されている関連データを先に手動で削除する
        GeneralNote.query.filter_by(motorcycle_id=motorcycle.id).delete(synchronize_session=False)
        Event.query.filter_by(motorcycle_id=motorcycle.id).delete(synchronize_session=False)

        # この車両の削除を実行
        # models.pyで cascade="all, delete-orphan" や ondelete='CASCADE' が
        # 設定されている他の全ての関連データ (FuelEntry, MaintenanceEntry, ActivityLog,
        # OdoResetLog, MaintenanceReminder など) は
        # この db.session.delete() によって自動的に削除されます。
        db.session.delete(motorcycle)
        
        if was_default:
            # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
            other_vehicle = Motorcycle.query.filter(Motorcycle.user_id == current_user.id).order_by(Motorcycle.id).first()
            # ▲▲▲ 変更ここまで ▲▲▲
            if other_vehicle:
                other_vehicle.is_default = True
        
        db.session.commit()
        flash(f'車両「{vehicle_name}」と、それに紐づく全ての関連データを削除しました。', 'success')
    # ▲▲▲【変更はここまで】▲▲▲
    except Exception as e:
        db.session.rollback()
        flash(f'車両の削除中にエラーが発生しました: {e}', 'danger')
        current_app.logger.error(f"Error deleting vehicle ID {vehicle_id}: {e}", exc_info=True)
    return redirect(url_for('vehicle.vehicle_list'))

@vehicle_bp.route('/<int:vehicle_id>/set_default', methods=['POST'])
@limiter.limit("30 per hour")
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def set_default_vehicle(vehicle_id):
    # ▼▼▼【ここから変更】 first_or_444 を first_or_404 に修正 ▼▼▼
    target_vehicle = Motorcycle.query.filter_by(id=vehicle_id, user_id=current_user.id).first_or_404()
    # ▲▲▲【変更はここまで】▲▲▲
    try:
        Motorcycle.query.filter(Motorcycle.user_id == current_user.id, Motorcycle.id != vehicle_id).update({'is_default': False}, synchronize_session='fetch')
        target_vehicle.is_default = True
        db.session.commit()
        flash(f'車両「{target_vehicle.name}」をデフォルトに設定しました。', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'デフォルト車両の設定中にエラーが発生しました: {e}', 'danger')
        current_app.logger.error(f"Error setting default vehicle ID {vehicle_id}: {e}", exc_info=True)
    return redirect(url_for('vehicle.vehicle_list'))

@vehicle_bp.route('/<int:vehicle_id>/archive', methods=['POST'])
@login_required
def archive_vehicle(vehicle_id):
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=current_user.id).first_or_404()
    if motorcycle.is_default:
        flash('デフォルト車両はアーカイブできません。先に別の車両をデフォルトに設定してください。', 'danger')
        return redirect(url_for('vehicle.vehicle_list'))
    
    try:
        motorcycle.is_archived = True
        motorcycle.is_default = False # 念のため
        db.session.commit()
        flash(f'車両「{motorcycle.name}」をアーカイブしました。', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error archiving vehicle {vehicle_id}: {e}", exc_info=True)
        flash('車両のアーカイブ中にエラーが発生しました。', 'danger')
    return redirect(url_for('vehicle.vehicle_list'))

@vehicle_bp.route('/<int:vehicle_id>/unarchive', methods=['POST'])
@login_required
def unarchive_vehicle(vehicle_id):
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=current_user.id).first_or_404()
    try:
        motorcycle.is_archived = False
        db.session.commit()
        flash(f'車両「{motorcycle.name}」をアーカイブから復元しました。', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error unarchiving vehicle {vehicle_id}: {e}", exc_info=True)
        flash('車両のアーカイブ復元中にエラーが発生しました。', 'danger')
    return redirect(url_for('vehicle.vehicle_list'))

@vehicle_bp.route('/<int:vehicle_id>/odo_reset_log/add', methods=['GET', 'POST'])
@limiter.limit("30 per hour")
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def add_odo_reset_log(vehicle_id):
    # ▼▼▼【ここから変更】 first_or_444 を first_or_404 に修正 ▼▼▼
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=current_user.id).first_or_404()
    # ▲▲▲【変更はここまで】▲▲▲
    if motorcycle.is_racer:
        flash('レーサー車両にはODOメーターリセット機能はご利用いただけません。', 'warning')
        return redirect(url_for('vehicle.edit_vehicle', vehicle_id=motorcycle.id))
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
            # ▼▼▼ g.user を current_user に変更 ▼▼▼
            check_achievements_for_event(current_user, EVENT_ADD_ODO_RESET, event_data=event_data_for_ach)
            # ▲▲▲ 変更ここまで ▲▲▲
            return redirect(url_for('vehicle.edit_vehicle', vehicle_id=motorcycle.id))
        except Exception as e:
                db.session.rollback()
                flash(f'履歴の追加中にエラーが発生しました: {e}', 'danger')
                current_app.logger.error(f"Error adding OdoResetLog for vehicle {vehicle_id}: {e}", exc_info=True)
    elif request.method == 'POST':
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
                           now_date_iso=now_date_iso_for_template)


@vehicle_bp.route('/odo_reset_log/<int:log_id>/delete', methods=['POST'])
@limiter.limit("30 per hour")
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def delete_odo_reset_log(log_id):
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    log_to_delete = db.session.query(OdoResetLog).join(Motorcycle).filter(
        OdoResetLog.id == log_id,
        Motorcycle.user_id == current_user.id
    ).first_or_404()
    # ▲▲▲ 変更ここまで ▲▲▲
    motorcycle = log_to_delete.motorcycle
    if motorcycle.is_racer:
        flash('不正な操作です。レーサー車両にODOリセットログは存在しません。', 'danger')
        return redirect(url_for('vehicle.edit_vehicle', vehicle_id=motorcycle.id))
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
@limiter.limit("30 per hour")
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def edit_odo_reset_log(log_id):
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    log_to_edit = db.session.query(OdoResetLog).join(Motorcycle).filter(
        OdoResetLog.id == log_id,
        Motorcycle.user_id == current_user.id
    ).first_or_404()
    # ▲▲▲ 変更ここまで ▲▲▲
    motorcycle = log_to_edit.motorcycle
    if motorcycle.is_racer:
        flash('不正な操作です。レーサー車両のODOリセットログは編集できません。', 'danger')
        return redirect(url_for('vehicle.edit_vehicle', vehicle_id=motorcycle.id))

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

# ▼▼▼ ここから追記 ▼▼▼
@vehicle_bp.route('/<int:vehicle_id>/toggle_garage_display', methods=['POST'])
@login_required
def toggle_garage_display(vehicle_id):
    """車両のガレージ表示/非表示を切り替えるAPI"""
    # ▼▼▼【ここから変更】 first_or_444 を first_or_404 に修正 ▼▼▼
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=current_user.id).first_or_404()
    # ▲▲▲【変更はここまで】▲▲▲
    try:
        motorcycle.show_in_garage = not motorcycle.show_in_garage
        db.session.commit()
        return jsonify({
            'status': 'success',
            'newState': motorcycle.show_in_garage,
            'message': f'「{motorcycle.name}」のガレージ掲載設定を更新しました。'
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error toggling show_in_garage for vehicle {vehicle_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': '設定の更新中にエラーが発生しました。'}), 500
# ▲▲▲ 追記ここまで ▲▲▲

@vehicle_bp.route('/<int:vehicle_id>/dashboard')
@login_required
def dashboard(vehicle_id):
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=current_user.id).first_or_404()
    
    # 最近のデータを取得（各カテゴリ最大10件で十分、タイムライン構築時に30件に絞り込む）
    recent_fuels = FuelEntry.query.filter_by(motorcycle_id=motorcycle.id).order_by(FuelEntry.entry_date.desc(), FuelEntry.id.desc()).limit(10).all()
    recent_maintenances = MaintenanceEntry.query.filter_by(motorcycle_id=motorcycle.id).order_by(MaintenanceEntry.maintenance_date.desc(), MaintenanceEntry.id.desc()).limit(10).all()
    recent_notes = GeneralNote.query.filter_by(motorcycle_id=motorcycle.id).order_by(GeneralNote.note_date.desc(), GeneralNote.id.desc()).limit(10).all()
    recent_activities = ActivityLog.query.filter_by(motorcycle_id=motorcycle.id).order_by(ActivityLog.activity_date.desc(), ActivityLog.id.desc()).limit(10).all()
    recent_tourings = TouringLog.query.filter_by(motorcycle_id=motorcycle.id).order_by(TouringLog.touring_date.desc(), TouringLog.id.desc()).limit(10).all()
    recent_settings = SettingSheet.query.filter_by(motorcycle_id=motorcycle.id, is_archived=False).order_by(SettingSheet.updated_at.desc(), SettingSheet.id.desc()).limit(10).all()
    
    # リマインダー (次回対応が近いものを services 経由で取得)
    upcoming_reminders = services.get_upcoming_reminders([motorcycle], current_user.id)
    
    # タイムラインの構築（すべてのアクティビティを時系列で混合、直近30件）
    timeline_items = _build_vehicle_timeline(motorcycle, recent_fuels, recent_maintenances, recent_notes, recent_activities, recent_tourings, recent_settings)
    
    # 統計情報の計算（コスト合計クエリを集約）
    total_fuel_cost = db.session.query(
        db.func.coalesce(db.func.sum(FuelEntry.total_cost), 0)
    ).filter_by(motorcycle_id=motorcycle.id).scalar() or 0
    
    maint_stats = db.session.query(
        db.func.coalesce(db.func.sum(MaintenanceEntry.parts_cost), 0),
        db.func.coalesce(db.func.sum(MaintenanceEntry.labor_cost), 0)
    ).filter_by(motorcycle_id=motorcycle.id).first()
    
    total_maint_parts = maint_stats[0] if maint_stats else 0
    total_maint_labor = maint_stats[1] if maint_stats else 0
    total_maint_cost = total_maint_parts + total_maint_labor
    total_expense = total_fuel_cost + total_maint_cost
    
    avg_kpl = services.calculate_average_kpl(motorcycle) if not motorcycle.is_racer else None
    
    return render_template('vehicle_dashboard.html',
                           vehicle=motorcycle,
                           timeline=timeline_items,
                           fuels=recent_fuels,
                           maintenances=recent_maintenances,
                           notes=recent_notes,
                           activities=recent_activities,
                           tourings=recent_tourings,
                           settings=recent_settings,
                           upcoming_reminders=upcoming_reminders,
                           total_fuel_cost=total_fuel_cost,
                           total_maint_cost=total_maint_cost,
                           total_maint_parts=total_maint_parts,
                           total_expense=total_expense,
                           avg_kpl=avg_kpl)


def _build_vehicle_timeline(motorcycle, fuels, maintenances, notes, activities, tourings, settings):
    """車両ダッシュボード用のタイムラインを構築するヘルパー関数"""
    timeline_items = []
    
    for f in fuels:
        timeline_items.append({
            'date': f.entry_date,
            'type': 'fuel',
            'title': f'給油: {f.fuel_volume}L ({f.total_distance:,}km)',
            'icon': 'fa-gas-pump',
            'bg_class': 'bg-info',
            'text_class': 'text-info',
            'link': url_for('fuel.fuel_log', vehicle_id=motorcycle.id) + f"#record-{f.id}"
        })
    for m in maintenances:
        try:
            desc = m.category or m.description
        except Exception:
            desc = m.description
        timeline_items.append({
            'date': m.maintenance_date,
            'type': 'maintenance',
            'title': f'整備: {desc}',
            'icon': 'fa-tools',
            'bg_class': 'bg-warning text-dark',
            'text_class': 'text-warning text-dark',
            'link': url_for('maintenance.edit_maintenance', entry_id=m.id)
        })
    for n in notes:
        try:
            title = n.title or n.category
        except Exception:
            title = 'ノート'
        timeline_items.append({
            'date': n.note_date,
            'type': 'note',
            'title': f'ノート: {title}',
            'icon': 'fa-sticky-note',
            'bg_class': 'bg-secondary',
            'text_class': 'text-secondary',
            'link': url_for('notes.edit_note', note_id=n.id)
        })
    for a in activities:
        title = a.location_name_display or a.activity_title
        timeline_items.append({
            'date': a.activity_date,
            'type': 'activity',
            'title': f'活動: {title}',
            'icon': 'fa-flag-checkered',
            'bg_class': 'bg-success',
            'text_class': 'text-success',
            'link': url_for('activity.detail_activity', activity_id=a.id)
        })
    for t in tourings:
        timeline_items.append({
            'date': t.touring_date,
            'type': 'touring',
            'title': f'ツーリング: {t.title}',
            'icon': 'fa-map-signs',
            'bg_class': 'bg-primary',
            'text_class': 'text-primary',
            'link': url_for('touring.detail_log', log_id=t.id)
        })
    for s in settings:
        if hasattr(s, 'created_at') and s.created_at:
            s_date = s.created_at.date()
        elif hasattr(s, 'updated_at') and s.updated_at:
            s_date = s.updated_at.date()
        else:
            s_date = datetime.now(timezone.utc).date()
            
        timeline_items.append({
            'date': s_date,
            'type': 'setting',
            'title': f'セッティング: {s.sheet_name}',
            'icon': 'fa-clipboard-list',
            'bg_class': 'bg-dark',
            'text_class': 'text-dark',
            'link': url_for('activity.edit_setting', setting_id=s.id)
        })
        
    timeline_items.sort(key=lambda x: x['date'], reverse=True)
    return timeline_items[:30]