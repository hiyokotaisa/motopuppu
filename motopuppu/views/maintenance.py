# motopuppu/views/maintenance.py
from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, abort, current_app
)
from datetime import date

# ログイン必須デコレータと現在のユーザー取得関数
from .auth import login_required_custom, get_current_user
# データベースモデルとdbオブジェクト
from ..models import db, Motorcycle, MaintenanceEntry # MaintenanceEntry モデルをインポート

# 'maintenance' という名前でBlueprintオブジェクトを作成
maintenance_bp = Blueprint('maintenance', __name__, url_prefix='/maintenance')

# --- ルート定義 ---

@maintenance_bp.route('/')
@login_required_custom
def maintenance_log():
    """整備記録の一覧を表示"""
    # (変更なし)
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('MAINTENANCE_ENTRIES_PER_PAGE', 20)
    user_motorcycle_ids = [m.id for m in Motorcycle.query.filter_by(user_id=g.user.id).all()]
    pagination = MaintenanceEntry.query.filter(
        MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids)
    ).order_by(
        MaintenanceEntry.maintenance_date.desc(),
        MaintenanceEntry.total_distance_at_maintenance.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)
    entries = pagination.items
    return render_template('maintenance_log.html',
                           entries=entries,
                           pagination=pagination)


@maintenance_bp.route('/add', methods=['GET', 'POST'])
@login_required_custom
def add_maintenance():
    """新しい整備記録を追加"""
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    if not user_motorcycles:
        flash('整備記録を追加するには、まず車両を登録してください。', 'warning')
        return redirect(url_for('vehicle.add_vehicle'))

    if request.method == 'POST':
        # (POST処理は変更なし)
        motorcycle_id = request.form.get('motorcycle_id', type=int)
        maintenance_date_str = request.form.get('maintenance_date')
        odometer_reading_str = request.form.get('odometer_reading_at_maintenance')
        description = request.form.get('description')
        location = request.form.get('location')
        category = request.form.get('category')
        parts_cost_str = request.form.get('parts_cost')
        labor_cost_str = request.form.get('labor_cost')
        notes = request.form.get('notes')

        errors = {}
        motorcycle = None
        maintenance_date = None
        odometer_reading = None
        parts_cost = 0.0
        labor_cost = 0.0

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
            try:
                parts_cost = float(parts_cost_str)
                if parts_cost < 0: errors['parts_cost'] = '部品代は0以上で入力してください。'
            except ValueError: errors['parts_cost'] = '部品代は有効な数値を入力してください。'
        else: parts_cost = 0.0
        if labor_cost_str:
            try:
                labor_cost = float(labor_cost_str)
                if labor_cost < 0: errors['labor_cost'] = '工賃は0以上で入力してください。'
            except ValueError: errors['labor_cost'] = '工賃は有効な数値を入力してください。'
        else: labor_cost = 0.0

        if errors:
            for field, msg in errors.items(): flash(f'{field} に関するエラー: {msg}', 'danger')
            entry_data = request.form.to_dict()
            entry_data['maintenance_date_obj'] = maintenance_date
            try: entry_data['motorcycle_id_int'] = int(motorcycle_id) if motorcycle_id else None
            except ValueError: entry_data['motorcycle_id_int'] = None
            today_iso_str = date.today().isoformat()
            return render_template('maintenance_form.html', form_action='add', entry=entry_data, motorcycles=user_motorcycles, today_iso=today_iso_str)
        else:
            total_distance = odometer_reading + motorcycle.odometer_offset
            new_entry = MaintenanceEntry(
                motorcycle_id=motorcycle_id, maintenance_date=maintenance_date,
                odometer_reading_at_maintenance=odometer_reading, total_distance_at_maintenance=total_distance,
                description=description, location=location if location else None,
                category=category if category else None, parts_cost=parts_cost,
                labor_cost=labor_cost, notes=notes if notes else None
            )
            try:
                db.session.add(new_entry)
                db.session.commit()
                flash('整備記録を追加しました。', 'success')
                return redirect(url_for('maintenance.maintenance_log'))
            except Exception as e:
                db.session.rollback()
                flash(f'記録のデータベース保存中にエラーが発生しました。', 'error')
                current_app.logger.error(f"Error saving maintenance entry: {e}")
                entry_data = request.form.to_dict()
                entry_data['maintenance_date_obj'] = maintenance_date
                try: entry_data['motorcycle_id_int'] = int(motorcycle_id) if motorcycle_id else None
                except ValueError: entry_data['motorcycle_id_int'] = None
                today_iso_str = date.today().isoformat()
                return render_template('maintenance_form.html', form_action='add', entry=entry_data, motorcycles=user_motorcycles, today_iso=today_iso_str)

    # --- GETリクエストの処理 ---
    else: # request.method == 'GET'
        today_iso_str = date.today().isoformat()
        # ▼▼▼ 【ここが修正箇所】クエリパラメータから motorcycle_id を取得 ▼▼▼
        preselected_motorcycle_id = request.args.get('motorcycle_id', type=int)
        # 念のため、取得したIDがユーザーの所有車両か確認
        if preselected_motorcycle_id:
            is_owner = Motorcycle.query.filter_by(id=preselected_motorcycle_id, user_id=g.user.id).first()
            if not is_owner:
                preselected_motorcycle_id = None # 所有者でなければ無視
        # ▲▲▲ 【修正箇所ここまで】▲▲▲

        # 新規追加フォームを表示
        return render_template('maintenance_form.html',
                               form_action='add',
                               entry=None,
                               motorcycles=user_motorcycles,
                               today_iso=today_iso_str,
                               # ▼▼▼【ここが修正箇所】テンプレートに渡す変数を追加 ▼▼▼
                               preselected_motorcycle_id=preselected_motorcycle_id)


@maintenance_bp.route('/<int:entry_id>/edit', methods=['GET', 'POST'])
@login_required_custom
def edit_maintenance(entry_id):
    """既存の整備記録を編集"""
    # (この関数は変更なし)
    entry = MaintenanceEntry.query.filter(MaintenanceEntry.id == entry_id)\
                                  .join(Motorcycle)\
                                  .filter(Motorcycle.user_id == g.user.id)\
                                  .first_or_404()
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.name).all()

    if request.method == 'POST':
        maintenance_date_str = request.form.get('maintenance_date')
        odometer_reading_str = request.form.get('odometer_reading_at_maintenance')
        description = request.form.get('description')
        location = request.form.get('location')
        category = request.form.get('category')
        parts_cost_str = request.form.get('parts_cost')
        labor_cost_str = request.form.get('labor_cost')
        notes = request.form.get('notes')

        errors = {}
        maintenance_date = None
        odometer_reading = None
        parts_cost = 0.0
        labor_cost = 0.0

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
            try:
                parts_cost = float(parts_cost_str)
                if parts_cost < 0: errors['parts_cost'] = '部品代は0以上で入力してください。'
            except ValueError: errors['parts_cost'] = '部品代は有効な数値を入力してください。'
        else: parts_cost = 0.0
        if labor_cost_str:
            try:
                labor_cost = float(labor_cost_str)
                if labor_cost < 0: errors['labor_cost'] = '工賃は0以上で入力してください。'
            except ValueError: errors['labor_cost'] = '工賃は有効な数値を入力してください。'
        else: labor_cost = 0.0

        if errors:
            for field, msg in errors.items(): flash(f'{field} に関するエラー: {msg}', 'danger')
            today_iso_str = date.today().isoformat()
            return render_template('maintenance_form.html', form_action='edit', entry=entry, motorcycles=user_motorcycles, today_iso=today_iso_str)
        else:
            try:
                entry.maintenance_date = maintenance_date
                entry.odometer_reading_at_maintenance = odometer_reading
                entry.total_distance_at_maintenance = odometer_reading + entry.motorcycle.odometer_offset
                entry.description = description
                entry.location = location if location else None
                entry.category = category if category else None
                entry.parts_cost = parts_cost
                entry.labor_cost = labor_cost
                entry.notes = notes if notes else None
                db.session.commit()
                flash('整備記録を更新しました。', 'success')
                return redirect(url_for('maintenance.maintenance_log'))
            except Exception as e:
                db.session.rollback()
                flash(f'記録の更新中にエラーが発生しました。', 'error')
                current_app.logger.error(f"Error updating maintenance entry {entry_id}: {e}")
                today_iso_str = date.today().isoformat()
                return render_template('maintenance_form.html', form_action='edit', entry=entry, motorcycles=user_motorcycles, today_iso=today_iso_str)

    else: # GETリクエストの処理
        today_iso_str = date.today().isoformat()
        return render_template('maintenance_form.html', form_action='edit', entry=entry, motorcycles=user_motorcycles, today_iso=today_iso_str)


@maintenance_bp.route('/<int:entry_id>/delete', methods=['POST'])
@login_required_custom
def delete_maintenance(entry_id):
    """整備記録を削除"""
    # (この関数は変更なし)
    entry = MaintenanceEntry.query.filter(MaintenanceEntry.id == entry_id)\
                                   .join(Motorcycle)\
                                   .filter(Motorcycle.user_id == g.user.id)\
                                   .first_or_404()
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
