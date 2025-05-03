# motopuppu/views/fuel.py
from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, abort, current_app
)
from datetime import date # dateオブジェクトを使用するためインポート

# ログイン必須デコレータと現在のユーザー取得関数をauthビューからインポート
from .auth import login_required_custom, get_current_user
# データベースモデル(Motorcycle, FuelEntry)とdbオブジェクトをインポート
from ..models import db, Motorcycle, FuelEntry

# 'fuel' という名前でBlueprintオブジェクトを作成、URLプレフィックスを '/fuel' に設定
fuel_bp = Blueprint('fuel', __name__, url_prefix='/fuel')

# --- ルート定義 ---

@fuel_bp.route('/')
@login_required_custom # このルートはログインが必須
def fuel_log():
    """給油記録の一覧を表示"""
    # (変更なし)
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('FUEL_ENTRIES_PER_PAGE', 20)
    user_motorcycle_ids = [m.id for m in Motorcycle.query.filter_by(user_id=g.user.id).all()]
    pagination = FuelEntry.query.filter(
        FuelEntry.motorcycle_id.in_(user_motorcycle_ids)
    ).order_by(
        FuelEntry.entry_date.desc(), FuelEntry.total_distance.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)
    fuel_entries = pagination.items
    return render_template('fuel_log.html',
                           fuel_entries=fuel_entries,
                           pagination=pagination)

@fuel_bp.route('/add', methods=['GET', 'POST'])
@login_required_custom # ログイン必須
def add_fuel():
    """新しい給油記録を追加"""
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    if not user_motorcycles:
        flash('給油記録を追加するには、まず車両を登録してください。', 'warning')
        return redirect(url_for('vehicle.add_vehicle'))

    if request.method == 'POST':
        # フォームからデータを取得
        motorcycle_id = request.form.get('motorcycle_id', type=int)
        entry_date_str = request.form.get('entry_date')
        odometer_reading_str = request.form.get('odometer_reading')
        fuel_volume_str = request.form.get('fuel_volume')
        price_per_liter_str = request.form.get('price_per_liter')
        total_cost_str = request.form.get('total_cost')
        station_name = request.form.get('station_name')
        fuel_type = request.form.get('fuel_type')
        notes = request.form.get('notes')
        # ▼▼▼ チェックボックスの値を取得 ▼▼▼
        # チェックされていれば 'on' (または設定したvalue値)、されていなければ None になる
        # より確実なのはキーの存在を確認する方法
        is_full_tank = 'is_full_tank' in request.form # これで True/False が取れる
        # ▲▲▲ 取得ここまで ▲▲▲

        errors = {}
        motorcycle = None
        odometer_reading = None
        fuel_volume = None
        entry_date = None
        price_per_liter = None
        total_cost = None

        # --- 入力値の検証 (変更なし) ---
        if motorcycle_id:
            motorcycle = Motorcycle.query.filter_by(id=motorcycle_id, user_id=g.user.id).first()
            if not motorcycle: errors['motorcycle_id'] = '有効な車両を選択してください。'
        else: errors['motorcycle_id'] = '車両を選択してください。'
        if entry_date_str:
            try: entry_date = date.fromisoformat(entry_date_str)
            except ValueError: errors['entry_date'] = '有効な日付形式 (YYYY-MM-DD) で入力してください。'
        else: errors['entry_date'] = '給油日は必須です。'
        if odometer_reading_str:
            try:
                odometer_reading = int(odometer_reading_str)
                if odometer_reading < 0: errors['odometer_reading'] = 'ODOメーター値は0以上で入力してください。'
                elif motorcycle:
                    last_entry = FuelEntry.query.filter_by(motorcycle_id=motorcycle.id).order_by(FuelEntry.total_distance.desc()).first()
                    if last_entry and (odometer_reading + motorcycle.odometer_offset) < last_entry.total_distance:
                         flash(f'注意: ODOメーター値から計算される総走行距離 ({odometer_reading + motorcycle.odometer_offset}km) が、前回の記録 ({last_entry.total_distance}km) より小さくなっています。', 'warning')
            except ValueError: errors['odometer_reading'] = 'ODOメーター値は有効な数値を入力してください。'
        else: errors['odometer_reading'] = 'ODOメーター値は必須です。'
        if fuel_volume_str:
            try:
                fuel_volume = float(fuel_volume_str)
                if fuel_volume <= 0: errors['fuel_volume'] = '給油量は0より大きい数値を入力してください。'
            except ValueError: errors['fuel_volume'] = '給油量は有効な数値を入力してください。'
        else: errors['fuel_volume'] = '給油量は必須です。'
        if price_per_liter_str:
            try:
                price_per_liter = float(price_per_liter_str)
                if price_per_liter < 0: errors['price_per_liter'] = 'リッター単価は0以上で入力してください。'
            except ValueError: errors['price_per_liter'] = 'リッター単価は有効な数値を入力してください。'
        else: price_per_liter = None
        if total_cost_str:
            try:
                total_cost = float(total_cost_str)
                if total_cost < 0: errors['total_cost'] = '合計金額は0以上で入力してください。'
            except ValueError: errors['total_cost'] = '合計金額は有効な数値を入力してください。'
        else: total_cost = None

        if errors:
            for field, msg in errors.items(): flash(f'{field} に関するエラー: {msg}', 'danger')
            entry_data_for_form = request.form.to_dict()
            entry_data_for_form['entry_date_obj'] = entry_date
            try: entry_data_for_form['motorcycle_id_int'] = int(motorcycle_id) if motorcycle_id else None
            except ValueError: entry_data_for_form['motorcycle_id_int'] = None
            today_iso_str = date.today().isoformat()
            # ★ エラー時も preselected_motorcycle_id は不要 (entry_data_for_form を使うため)
            # ★ entry_data_for_form に is_full_tank の状態を含める必要はない（テンプレート側で request.form のキー存在有無で判断するため）
            return render_template('fuel_form.html',
                                   form_action='add',
                                   entry=entry_data_for_form, # ここに is_full_tank の情報も含まれる（チェック時）
                                   motorcycles=user_motorcycles,
                                   today_iso=today_iso_str)
        else:
            # エラーなし -> DB保存
            total_distance = odometer_reading + motorcycle.odometer_offset
            if total_cost is None and price_per_liter is not None and fuel_volume is not None:
                total_cost = round(price_per_liter * fuel_volume, 2)

            new_entry = FuelEntry(
                motorcycle_id=motorcycle_id, entry_date=entry_date,
                odometer_reading=odometer_reading, total_distance=total_distance,
                fuel_volume=fuel_volume, price_per_liter=price_per_liter,
                total_cost=total_cost, station_name=station_name,
                fuel_type=fuel_type, notes=notes,
                # ▼▼▼ is_full_tank の値を保存 ▼▼▼
                is_full_tank=is_full_tank
                # ▲▲▲ 保存 ▲▲▲
            )
            try:
                db.session.add(new_entry)
                db.session.commit()
                flash('給油記録を追加しました。', 'success')
                return redirect(url_for('fuel.fuel_log'))
            except Exception as e:
                db.session.rollback()
                flash(f'記録のデータベース保存中にエラーが発生しました。', 'error')
                current_app.logger.error(f"Error saving fuel entry: {e}")
                entry_data_for_form = request.form.to_dict()
                entry_data_for_form['entry_date_obj'] = entry_date
                try: entry_data_for_form['motorcycle_id_int'] = int(motorcycle_id) if motorcycle_id else None
                except ValueError: entry_data_for_form['motorcycle_id_int'] = None
                today_iso_str = date.today().isoformat()
                return render_template('fuel_form.html',
                                       form_action='add',
                                       entry=entry_data_for_form, # ここに is_full_tank 情報も含まれる
                                       motorcycles=user_motorcycles,
                                       today_iso=today_iso_str)

    else: # GETリクエストの処理
        today_iso_str = date.today().isoformat()
        preselected_motorcycle_id = request.args.get('motorcycle_id', type=int)
        if preselected_motorcycle_id:
            is_owner = Motorcycle.query.filter_by(id=preselected_motorcycle_id, user_id=g.user.id).first()
            if not is_owner:
                preselected_motorcycle_id = None
        return render_template('fuel_form.html',
                               form_action='add',
                               entry=None,
                               motorcycles=user_motorcycles,
                               today_iso=today_iso_str,
                               preselected_motorcycle_id=preselected_motorcycle_id)

@fuel_bp.route('/<int:entry_id>/edit', methods=['GET', 'POST'])
@login_required_custom
def edit_fuel(entry_id):
    """既存の給油記録を編集"""
    entry = FuelEntry.query.filter(FuelEntry.id == entry_id)\
                           .join(Motorcycle)\
                           .filter(Motorcycle.user_id == g.user.id)\
                           .first_or_404()
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.name).all()

    if request.method == 'POST':
        # --- ▼▼▼ 編集のPOST処理 ▼▼▼ ---
        entry_date_str = request.form.get('entry_date')
        odometer_reading_str = request.form.get('odometer_reading')
        fuel_volume_str = request.form.get('fuel_volume')
        price_per_liter_str = request.form.get('price_per_liter')
        total_cost_str = request.form.get('total_cost')
        station_name = request.form.get('station_name')
        fuel_type = request.form.get('fuel_type')
        notes = request.form.get('notes')
        # ▼▼▼ チェックボックスの値を取得 ▼▼▼
        is_full_tank = 'is_full_tank' in request.form
        # ▲▲▲ 取得 ▲▲▲

        errors = {}
        entry_date = None
        odometer_reading = None
        fuel_volume = None
        price_per_liter = None
        total_cost = None

        # --- 入力値の検証 ---
        if entry_date_str:
            try: entry_date = date.fromisoformat(entry_date_str)
            except ValueError: errors['entry_date'] = '有効な日付形式 (YYYY-MM-DD) で入力してください。'
        else: errors['entry_date'] = '給油日は必須です。'
        if odometer_reading_str:
            try:
                odometer_reading = int(odometer_reading_str)
                if odometer_reading < 0: errors['odometer_reading'] = 'ODOメーター値は0以上で入力してください。'
            except ValueError: errors['odometer_reading'] = 'ODOメーター値は有効な数値を入力してください。'
        else: errors['odometer_reading'] = 'ODOメーター値は必須です。'
        if fuel_volume_str:
            try:
                fuel_volume = float(fuel_volume_str)
                if fuel_volume <= 0: errors['fuel_volume'] = '給油量は0より大きい数値を入力してください。'
            except ValueError: errors['fuel_volume'] = '給油量は有効な数値を入力してください。'
        else: errors['fuel_volume'] = '給油量は必須です。'
        if price_per_liter_str:
            try:
                price_per_liter = float(price_per_liter_str)
                if price_per_liter < 0: errors['price_per_liter'] = 'リッター単価は0以上で入力してください。'
            except ValueError: errors['price_per_liter'] = 'リッター単価は有効な数値を入力してください。'
        else: price_per_liter = None
        if total_cost_str:
            try:
                total_cost = float(total_cost_str)
                if total_cost < 0: errors['total_cost'] = '合計金額は0以上で入力してください。'
            except ValueError: errors['total_cost'] = '合計金額は有効な数値を入力してください。'
        else: total_cost = None

        if errors:
            for field, msg in errors.items(): flash(f'{field} に関するエラー: {msg}', 'danger')
            today_iso_str = date.today().isoformat()
            # エラー時は元のentryを渡すので、チェックボックスの状態も元のままになる
            return render_template('fuel_form.html', form_action='edit', entry=entry, motorcycles=user_motorcycles, today_iso=today_iso_str)
        else:
            try:
                # 既存オブジェクトの値を更新
                entry.entry_date = entry_date
                entry.odometer_reading = odometer_reading
                entry.fuel_volume = fuel_volume
                entry.price_per_liter = price_per_liter
                entry.total_cost = total_cost
                entry.station_name = station_name if station_name else None
                entry.fuel_type = fuel_type if fuel_type else None
                entry.notes = notes if notes else None
                # ▼▼▼ is_full_tank の値を更新 ▼▼▼
                entry.is_full_tank = is_full_tank
                # ▲▲▲ 更新 ▲▲▲

                entry.total_distance = entry.odometer_reading + entry.motorcycle.odometer_offset
                if entry.total_cost is None and entry.price_per_liter is not None and entry.fuel_volume is not None:
                    entry.total_cost = round(entry.price_per_liter * entry.fuel_volume, 2)

                db.session.commit()
                flash('給油記録を更新しました。', 'success')
                return redirect(url_for('fuel.fuel_log'))
            except Exception as e:
                db.session.rollback()
                flash(f'記録の更新中にエラーが発生しました。', 'error')
                current_app.logger.error(f"Error updating fuel entry {entry_id}: {e}")
                today_iso_str = date.today().isoformat()
                return render_template('fuel_form.html', form_action='edit', entry=entry, motorcycles=user_motorcycles, today_iso=today_iso_str)

    else: # GETリクエストの処理
        today_iso_str = date.today().isoformat()
        return render_template('fuel_form.html', form_action='edit', entry=entry, motorcycles=user_motorcycles, today_iso=today_iso_str)

# --- 給油記録の削除 ---
@fuel_bp.route('/<int:entry_id>/delete', methods=['POST'])
@login_required_custom
def delete_fuel(entry_id):
    # (変更なし)
    entry = FuelEntry.query.filter(FuelEntry.id == entry_id)\
                           .join(Motorcycle)\
                           .filter(Motorcycle.user_id == g.user.id)\
                           .first_or_404()
    try:
        db.session.delete(entry)
        db.session.commit()
        flash('給油記録を削除しました。', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'記録の削除中にエラーが発生しました。', 'error')
        current_app.logger.error(f"Error deleting fuel entry {entry_id}: {e}")
    return redirect(url_for('fuel.fuel_log'))
