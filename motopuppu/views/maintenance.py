# motopuppu/views/maintenance.py
from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, abort, current_app
)
from datetime import date, datetime
from sqlalchemy import or_, asc, desc # asc, desc をインポート

# ログイン必須デコレータと現在のユーザー取得関数をインポート
from .auth import login_required_custom, get_current_user
# データベースモデル(Motorcycle, MaintenanceEntry, MaintenanceReminder)とdbオブジェクトをインポート
from ..models import db, Motorcycle, MaintenanceEntry, MaintenanceReminder

# 'maintenance' という名前でBlueprintオブジェクトを作成、URLプレフィックスを設定
maintenance_bp = Blueprint('maintenance', __name__, url_prefix='/maintenance')

# --- ▼▼▼ ヘルパー関数: リマインダーの最終実施記録を更新 (変更なし) ▼▼▼ ---
def _update_reminder_last_done(maintenance_entry: MaintenanceEntry):
    """
    指定された整備記録に基づいて、対応するリマインダーの
    最終実施日と最終実施距離を更新する。
    照合は整備記録のカテゴリとリマインダーのタスク内容で行う (ケースインセンシティブ)。
    """
    if not maintenance_entry or not maintenance_entry.category:
        # 照合に必要なカテゴリがない場合は何もしない
        current_app.logger.debug(f"Skipping reminder update for maintenance {maintenance_entry.id}: No category.")
        return

    # 比較用にカテゴリ名を小文字化・トリム
    maintenance_category_lower = maintenance_entry.category.strip().lower()
    if not maintenance_category_lower:
        current_app.logger.debug(f"Skipping reminder update for maintenance {maintenance_entry.id}: Empty category.")
        return

    # 同じ車両のリマインダーを検索
    potential_reminders = MaintenanceReminder.query.filter_by(
        motorcycle_id=maintenance_entry.motorcycle_id
    ).all()

    matched_reminder = None
    for reminder in potential_reminders:
        # リマインダーのタスク内容も小文字化・トリムして比較
        if reminder.task_description and \
           reminder.task_description.strip().lower() == maintenance_category_lower:
            matched_reminder = reminder
            break # 最初に見つかったものを使用

    if matched_reminder:
        try:
            update_needed = False
            log_prefix = f"Reminder '{matched_reminder.task_description}' (ID: {matched_reminder.id}) for Maint {maintenance_entry.id}:"

            # 最終実施日を更新するか判断
            # 1. リマインダーに日付がない OR
            # 2. 整備記録の日付がリマインダーの日付より新しい
            should_update_date = (matched_reminder.last_done_date is None or
                                  maintenance_entry.maintenance_date >= matched_reminder.last_done_date)

            if should_update_date:
                # 最終実施距離を更新するか判断
                # 1. リマインダーに距離がない OR
                # 2. 日付が新しい OR
                # 3. 日付が同じで、整備記録の距離がリマインダーの距離より大きい
                should_update_km = (matched_reminder.last_done_km is None or
                                    maintenance_entry.maintenance_date > matched_reminder.last_done_date or
                                    (maintenance_entry.maintenance_date == matched_reminder.last_done_date and
                                     maintenance_entry.total_distance_at_maintenance >= (matched_reminder.last_done_km or 0)))

                if should_update_km: # 距離を更新する場合は、日付も必ず更新する
                    if matched_reminder.last_done_date != maintenance_entry.maintenance_date or \
                       matched_reminder.last_done_km != maintenance_entry.total_distance_at_maintenance:
                        matched_reminder.last_done_date = maintenance_entry.maintenance_date
                        matched_reminder.last_done_km = maintenance_entry.total_distance_at_maintenance
                        update_needed = True
                        current_app.logger.info(f"{log_prefix} Updating last_done_date to {matched_reminder.last_done_date} and last_done_km to {matched_reminder.last_done_km}")
                    else:
                        current_app.logger.debug(f"{log_prefix} Date and KM are the same. No update needed.")
                elif matched_reminder.last_done_date != maintenance_entry.maintenance_date:
                     # 日付だけ新しい場合 (距離は更新しない) - 通常あまりないケース？
                     matched_reminder.last_done_date = maintenance_entry.maintenance_date
                     update_needed = True
                     current_app.logger.info(f"{log_prefix} Updating last_done_date to {matched_reminder.last_done_date} (KM unchanged).")

            # SQLAlchemyは変更を追跡するので、update_needed が True ならコミット時に保存されるはず
            # if update_needed:
            #     db.session.add(matched_reminder) # 通常は不要
            if not update_needed:
                 current_app.logger.debug(f"{log_prefix} No update needed for reminder based on this maintenance entry.")

        except Exception as e:
            # リマインダー更新エラーはログに残すが、整備記録の保存は妨げない
            current_app.logger.error(f"Error updating reminder {matched_reminder.id} for maintenance entry {maintenance_entry.id}: {e}")
    else:
         current_app.logger.debug(f"No matching reminder found for maintenance category '{maintenance_category_lower}' (Maint ID: {maintenance_entry.id}).")

# --- ▲▲▲ ヘルパー関数ここまで ▲▲▲ ---


# --- ルート定義 ---

@maintenance_bp.route('/')
@login_required_custom
def maintenance_log():
    """整備記録の一覧を表示 (フィルター・ソート機能付き)"""
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    vehicle_id_str = request.args.get('vehicle_id')
    category_filter = request.args.get('category', '').strip()
    keyword = request.args.get('q', '').strip()
    # ▼▼▼ ソートパラメータを追加 ▼▼▼
    sort_by = request.args.get('sort_by', 'date') # デフォルトは日付
    order = request.args.get('order', 'desc') # デフォルトは降順
    # ▲▲▲ 追加ここまで ▲▲▲
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('MAINTENANCE_ENTRIES_PER_PAGE', 20)

    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    user_motorcycle_ids = [m.id for m in user_motorcycles]

    # クエリにMotorcycleをJoinしておく (車両名でのソートに必要)
    query = db.session.query(MaintenanceEntry).join(Motorcycle).filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids))

    # テンプレートに渡すための現在のリクエストパラメータ (ページネーション、ソートを除く)
    request_args_dict = request.args.to_dict()
    request_args_dict.pop('page', None)
    request_args_dict.pop('sort_by', None)
    request_args_dict.pop('order', None)

    # フィルター適用 (変更なし)
    try:
        if start_date_str: query = query.filter(MaintenanceEntry.maintenance_date >= date.fromisoformat(start_date_str))
        else: request_args_dict.pop('start_date', None)
        if end_date_str: query = query.filter(MaintenanceEntry.maintenance_date <= date.fromisoformat(end_date_str))
        else: request_args_dict.pop('end_date', None)
    except ValueError:
        flash('日付の形式が無効です。YYYY-MM-DD形式で入力してください。', 'warning')
        request_args_dict.pop('start_date', None)
        request_args_dict.pop('end_date', None)

    if vehicle_id_str:
        try:
            vehicle_id = int(vehicle_id_str)
            if vehicle_id in user_motorcycle_ids: query = query.filter(MaintenanceEntry.motorcycle_id == vehicle_id)
            else: flash('選択された車両は有効ではありません。', 'warning'); request_args_dict.pop('vehicle_id', None)
        except ValueError:
            request_args_dict.pop('vehicle_id', None)
    else:
        request_args_dict.pop('vehicle_id', None)

    if category_filter: query = query.filter(MaintenanceEntry.category.ilike(f'%{category_filter}%'))
    else: request_args_dict.pop('category', None)

    if keyword: query = query.filter(or_(MaintenanceEntry.description.ilike(f'%{keyword}%'), MaintenanceEntry.location.ilike(f'%{keyword}%'), MaintenanceEntry.notes.ilike(f'%{keyword}%')))
    else: request_args_dict.pop('q', None)

    # ▼▼▼ ソート処理を追加 ▼▼▼
    # ソート対象カラムのマッピング
    sort_column_map = {
        'date': MaintenanceEntry.maintenance_date,
        'vehicle': Motorcycle.name,
        'odo': MaintenanceEntry.total_distance_at_maintenance,
        'category': MaintenanceEntry.category,
        # total_cost はプロパティなのでサーバーサイドソート対象外とする
    }

    # 無効なソートキーの場合はデフォルトに戻す
    current_sort_by = sort_by if sort_by in sort_column_map else 'date'
    sort_column = sort_column_map.get(current_sort_by, MaintenanceEntry.maintenance_date) # デフォルト

    # 無効な順序の場合はデフォルトに戻す
    current_order = 'desc' if order == 'desc' else 'asc'
    sort_modifier = desc if current_order == 'desc' else asc

    # クエリにソート条件を適用
    query = query.order_by(sort_modifier(sort_column))

    # 同じ日付や同じODOの場合は、IDなどで安定ソート (任意だが推奨)
    if current_sort_by == 'date':
         query = query.order_by(sort_modifier(MaintenanceEntry.maintenance_date), desc(MaintenanceEntry.total_distance_at_maintenance)) # 日付が同じならODO降順
    elif current_sort_by == 'odo':
         query = query.order_by(sort_modifier(MaintenanceEntry.total_distance_at_maintenance), desc(MaintenanceEntry.maintenance_date)) # ODOが同じなら日付降順
    elif current_sort_by == 'vehicle' or current_sort_by == 'category':
        # 車両名やカテゴリが同じ場合は日付降順
        query = query.order_by(sort_modifier(sort_column), desc(MaintenanceEntry.maintenance_date))

    # ▲▲▲ ソート処理追加ここまで ▲▲▲


    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    entries = pagination.items

    # ▼▼▼ テンプレートにソート関連の変数を追加して渡す ▼▼▼
    return render_template('maintenance_log.html',
                           entries=entries,
                           pagination=pagination,
                           motorcycles=user_motorcycles,
                           request_args=request_args_dict,
                           current_sort_by=current_sort_by, # 現在のソートキー
                           current_order=current_order # 現在のソート順序
                          )
    # ▲▲▲ 変更ここまで ▲▲▲


@maintenance_bp.route('/add', methods=['GET', 'POST'])
@login_required_custom
def add_maintenance():
    """新しい整備記録を追加"""
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    if not user_motorcycles:
        flash('整備記録を追加するには、まず車両を登録してください。', 'warning')
        return redirect(url_for('vehicle.add_vehicle'))

    if request.method == 'POST':
        # (フォームデータの取得とバリデーション - 変更なし)
        motorcycle_id = request.form.get('motorcycle_id', type=int)
        maintenance_date_str = request.form.get('maintenance_date')
        odometer_reading_str = request.form.get('odometer_reading_at_maintenance')
        description = request.form.get('description')
        location = request.form.get('location')
        category = request.form.get('category', '').strip() # strip()
        parts_cost_str = request.form.get('parts_cost')
        labor_cost_str = request.form.get('labor_cost')
        notes = request.form.get('notes')
        errors = {}; motorcycle = None; maintenance_date = None; odometer_reading = None; parts_cost = 0.0; labor_cost = 0.0
        if motorcycle_id:
            motorcycle = Motorcycle.query.filter_by(id=motorcycle_id, user_id=g.user.id).first()
            if not motorcycle: errors['motorcycle_id'] = '有効な車両を選択してください。'
        else: errors['motorcycle_id'] = '車両を選択してください。'
        if maintenance_date_str:
            try: maintenance_date = date.fromisoformat(maintenance_date_str)
            except ValueError: errors['maintenance_date'] = '有効な日付形式 (YYYY-MM-DD) で入力してください。'
        else: errors['maintenance_date'] = '整備日は必須です。'
        if odometer_reading_str:
            try:
                odometer_reading = int(odometer_reading_str)
                if odometer_reading < 0: errors['odometer_reading_at_maintenance'] = 'ODOメーター値は0以上で入力してください。'
            except ValueError: errors['odometer_reading_at_maintenance'] = 'ODOメーター値は有効な数値を入力してください。'
        else: errors['odometer_reading_at_maintenance'] = '整備時のODOメーター値は必須です。'
        if not description: errors['description'] = '整備内容は必須です。'
        if parts_cost_str:
            try: parts_cost = float(parts_cost_str); assert parts_cost >= 0
            except (ValueError, AssertionError): errors['parts_cost'] = '部品代は0以上の数値を入力してください。'
        if labor_cost_str:
            try: labor_cost = float(labor_cost_str); assert labor_cost >= 0
            except (ValueError, AssertionError): errors['labor_cost'] = '工賃は0以上の数値を入力してください。'

        if errors:
            for field, msg in errors.items(): flash(f'{msg}', 'danger')
            entry_data = request.form.to_dict(); entry_data['maintenance_date_obj'] = maintenance_date
            try: entry_data['motorcycle_id_int'] = int(motorcycle_id) if motorcycle_id else None
            except ValueError: entry_data['motorcycle_id_int'] = None
            return render_template('maintenance_form.html', form_action='add', entry=entry_data, motorcycles=user_motorcycles, today_iso=date.today().isoformat())
        else:
            # (MaintenanceEntry オブジェクト作成 - 変更なし)
            total_distance = odometer_reading + (motorcycle.odometer_offset or 0)
            new_entry = MaintenanceEntry(
                motorcycle_id=motorcycle_id, maintenance_date=maintenance_date,
                odometer_reading_at_maintenance=odometer_reading, total_distance_at_maintenance=total_distance,
                description=description, location=location if location else None,
                category=category if category else None,
                parts_cost=parts_cost, labor_cost=labor_cost, notes=notes if notes else None
            )
            try:
                db.session.add(new_entry)
                # リマインダー更新処理を呼び出す
                _update_reminder_last_done(new_entry)
                db.session.commit()
                flash('整備記録を追加しました。', 'success')
                return redirect(url_for('maintenance.maintenance_log'))
            except Exception as e:
                db.session.rollback()
                flash(f'記録のデータベース保存中にエラーが発生しました。', 'error')
                current_app.logger.error(f"Error saving maintenance entry: {e}")
                entry_data = request.form.to_dict(); entry_data['maintenance_date_obj'] = maintenance_date
                try: entry_data['motorcycle_id_int'] = int(motorcycle_id) if motorcycle_id else None
                except ValueError: entry_data['motorcycle_id_int'] = None
                return render_template('maintenance_form.html', form_action='add', entry=entry_data, motorcycles=user_motorcycles, today_iso=date.today().isoformat())
    else: # GET
        # (変更なし)
        today_iso_str = date.today().isoformat()
        preselected_motorcycle_id = request.args.get('motorcycle_id', type=int)
        if preselected_motorcycle_id:
            is_owner = Motorcycle.query.filter_by(id=preselected_motorcycle_id, user_id=g.user.id).first()
            if not is_owner: preselected_motorcycle_id = None
        return render_template('maintenance_form.html', form_action='add', entry=None, motorcycles=user_motorcycles, today_iso=today_iso_str, preselected_motorcycle_id=preselected_motorcycle_id)


# --- 整備記録の編集 (変更なし) ---
@maintenance_bp.route('/<int:entry_id>/edit', methods=['GET', 'POST'])
@login_required_custom
def edit_maintenance(entry_id):
    """既存の整備記録を編集"""
    entry = MaintenanceEntry.query.filter(MaintenanceEntry.id == entry_id).join(Motorcycle).filter(Motorcycle.user_id == g.user.id).first_or_404()
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.name).all()

    if request.method == 'POST':
        # (フォームデータの取得とバリデーション - 変更なし)
        maintenance_date_str = request.form.get('maintenance_date')
        odometer_reading_str = request.form.get('odometer_reading_at_maintenance')
        description = request.form.get('description')
        location = request.form.get('location')
        category = request.form.get('category', '').strip() # strip()
        parts_cost_str = request.form.get('parts_cost')
        labor_cost_str = request.form.get('labor_cost')
        notes = request.form.get('notes')
        errors = {}; maintenance_date = None; odometer_reading = None; parts_cost = 0.0; labor_cost = 0.0
        if maintenance_date_str:
            try: maintenance_date = date.fromisoformat(maintenance_date_str)
            except ValueError: errors['maintenance_date'] = '有効な日付形式 (YYYY-MM-DD) で入力してください。'
        else: errors['maintenance_date'] = '整備日は必須です。'
        if odometer_reading_str:
            try:
                odometer_reading = int(odometer_reading_str)
                if odometer_reading < 0: errors['odometer_reading_at_maintenance'] = 'ODOメーター値は0以上で入力してください。'
            except ValueError: errors['odometer_reading_at_maintenance'] = 'ODOメーター値は有効な数値を入力してください。'
        else: errors['odometer_reading_at_maintenance'] = '整備時のODOメーター値は必須です。'
        if not description: errors['description'] = '整備内容は必須です。'
        if parts_cost_str:
            try: parts_cost = float(parts_cost_str); assert parts_cost >= 0
            except (ValueError, AssertionError): errors['parts_cost'] = '部品代は0以上の数値を入力してください。'
        if labor_cost_str:
            try: labor_cost = float(labor_cost_str); assert labor_cost >= 0
            except (ValueError, AssertionError): errors['labor_cost'] = '工賃は0以上の数値を入力してください。'

        if errors:
            for field, msg in errors.items(): flash(f'{msg}', 'danger')
            return render_template('maintenance_form.html', form_action='edit', entry=entry, motorcycles=user_motorcycles, today_iso=date.today().isoformat())
        else:
            try:
                # entry オブジェクトの属性を更新
                entry.maintenance_date = maintenance_date
                entry.odometer_reading_at_maintenance = odometer_reading
                # total_distance も再計算して更新
                entry.total_distance_at_maintenance = odometer_reading + (entry.motorcycle.odometer_offset or 0)
                entry.description = description
                entry.location = location if location else None
                entry.category = category if category else None # 更新するカテゴリ
                entry.parts_cost = parts_cost
                entry.labor_cost = labor_cost
                entry.notes = notes if notes else None

                # リマインダー更新処理を呼び出す
                _update_reminder_last_done(entry)

                db.session.commit()
                flash('整備記録を更新しました。', 'success')
                return redirect(url_for('maintenance.maintenance_log'))
            except Exception as e:
                db.session.rollback()
                flash(f'記録の更新中にエラーが発生しました。', 'error')
                current_app.logger.error(f"Error updating maintenance entry {entry_id}: {e}")
                return render_template('maintenance_form.html', form_action='edit', entry=entry, motorcycles=user_motorcycles, today_iso=date.today().isoformat())
    else: # GET
        # (変更なし)
        return render_template('maintenance_form.html', form_action='edit', entry=entry, motorcycles=user_motorcycles, today_iso=date.today().isoformat())


# --- 整備記録の削除 (変更なし) ---
@maintenance_bp.route('/<int:entry_id>/delete', methods=['POST'])
@login_required_custom
def delete_maintenance(entry_id):
    """整備記録を削除"""
    # (変更なし)
    entry = MaintenanceEntry.query.filter(MaintenanceEntry.id == entry_id).join(Motorcycle).filter(Motorcycle.user_id == g.user.id).first_or_404()
    try:
        # TODO: 関連する添付ファイルも削除する処理が必要
        db.session.delete(entry)
        db.session.commit()
        flash('整備記録を削除しました。', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'記録の削除中にエラーが発生しました。', 'error')
        current_app.logger.error(f"Error deleting maintenance entry {entry_id}: {e}")
    return redirect(url_for('maintenance.maintenance_log'))