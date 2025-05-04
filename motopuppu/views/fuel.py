# motopuppu/views/fuel.py
from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, abort, current_app
)
from datetime import date, datetime # datetime もインポート (日付比較のため)
from sqlalchemy import or_ # or_ をインポート (キーワード検索用)

# ログイン必須デコレータと現在のユーザー取得関数をauthビューからインポート
from .auth import login_required_custom, get_current_user
# データベースモデル(Motorcycle, FuelEntry)とdbオブジェクトをインポート
from ..models import db, Motorcycle, FuelEntry

# 'fuel' という名前でBlueprintオブジェクトを作成、URLプレフィックスを '/fuel' に設定
fuel_bp = Blueprint('fuel', __name__, url_prefix='/fuel')

# --- ▼▼▼ スタンド名の候補リストを定義 ▼▼▼ ---
# (本来は config から読み込むのが望ましい)
GAS_STATION_BRANDS = [
    'ENEOS',
    '出光興産/apollostation',
    'コスモ石油',
    'キグナス石油',
    'JA-SS',
    'SOLATO',
    # 必要に応じて追加
]
# --- ▲▲▲ スタンド名リスト定義ここまで ▲▲▲ ---


# --- ▼▼▼ ヘルパー関数: 前回給油情報を取得 ▼▼▼ ---
def get_previous_fuel_entry(motorcycle_id, current_entry_date, current_entry_id=None):
    """
    指定された車両IDと日付より前の、最新の給油記録を取得する。
    編集中の記録自体は除外する。
    Args:
        motorcycle_id (int): 対象の車両ID
        current_entry_date (date): 基準となる日付 (この日付より前の記録を探す)
        current_entry_id (int, optional): 編集中の記録ID (これを除外する). Defaults to None.
    Returns:
        FuelEntry or None: 見つかった直前の給油記録オブジェクト、またはNone
    """
    if not motorcycle_id or not current_entry_date:
        return None

    query = FuelEntry.query.filter(
        FuelEntry.motorcycle_id == motorcycle_id,
        FuelEntry.entry_date < current_entry_date
    )
    # 編集中の場合、その記録自体を除外
    if current_entry_id is not None:
        query = query.filter(FuelEntry.id != current_entry_id)

    # 日付で降順、次に総走行距離で降順（同日複数記録の場合）
    previous_entry = query.order_by(FuelEntry.entry_date.desc(), FuelEntry.total_distance.desc()).first()
    return previous_entry
# --- ▲▲▲ ヘルパー関数ここまで ▲▲▲ ---


# --- ルート定義 ---

@fuel_bp.route('/')
@login_required_custom # このルートはログインが必須
def fuel_log():
    """給油記録の一覧を表示 (フィルター機能付き)"""
    # --- フィルター条件の取得 ---
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    vehicle_id_str = request.args.get('vehicle_id')
    keyword = request.args.get('q', '').strip()

    # --- データの取得 ---
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('FUEL_ENTRIES_PER_PAGE', 20)
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    user_motorcycle_ids = [m.id for m in user_motorcycles]

    query = FuelEntry.query.filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids))
    request_args_dict = request.args.to_dict()

    try:
        if start_date_str: query = query.filter(FuelEntry.entry_date >= date.fromisoformat(start_date_str))
        else: request_args_dict.pop('start_date', None)
        if end_date_str: query = query.filter(FuelEntry.entry_date <= date.fromisoformat(end_date_str))
        else: request_args_dict.pop('end_date', None)
    except ValueError: flash('日付の形式が無効です。YYYY-MM-DD形式で入力してください。', 'warning'); request_args_dict.pop('start_date', None); request_args_dict.pop('end_date', None)

    if vehicle_id_str:
        try:
            vehicle_id = int(vehicle_id_str)
            if vehicle_id in user_motorcycle_ids: query = query.filter(FuelEntry.motorcycle_id == vehicle_id)
            else: flash('選択された車両は有効ではありません。', 'warning'); request_args_dict.pop('vehicle_id', None)
        except ValueError: request_args_dict.pop('vehicle_id', None)
    else: request_args_dict.pop('vehicle_id', None)

    if keyword: search_term = f'%{keyword}%'; query = query.filter(or_(FuelEntry.notes.ilike(search_term), FuelEntry.station_name.ilike(search_term)))
    else: request_args_dict.pop('q', None)

    pagination = query.order_by(FuelEntry.entry_date.desc(), FuelEntry.total_distance.desc()).paginate(page=page, per_page=per_page, error_out=False)
    fuel_entries = pagination.items

    return render_template('fuel_log.html',
                           entries=fuel_entries,
                           pagination=pagination,
                           motorcycles=user_motorcycles,
                           request_args=request_args_dict)

# --- 給油記録の追加 ---
@fuel_bp.route('/add', methods=['GET', 'POST'])
@login_required_custom
def add_fuel():
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    if not user_motorcycles:
        flash('給油記録を追加するには、まず車両を登録してください。', 'warning')
        return redirect(url_for('vehicle.add_vehicle'))

    if request.method == 'POST':
        motorcycle_id = request.form.get('motorcycle_id', type=int)
        entry_date_str = request.form.get('entry_date')
        odometer_reading_str = request.form.get('odometer_reading')
        fuel_volume_str = request.form.get('fuel_volume')
        price_per_liter_str = request.form.get('price_per_liter')
        total_cost_str = request.form.get('total_cost')
        station_name = request.form.get('station_name', '').strip()
        fuel_type = request.form.get('fuel_type')
        notes = request.form.get('notes')
        is_full_tank = 'is_full_tank' in request.form

        errors = {}; motorcycle = None; odometer_reading = None; fuel_volume = None; entry_date = None; price_per_liter = None; total_cost = None; previous_entry = None

        if motorcycle_id:
            motorcycle = Motorcycle.query.filter_by(id=motorcycle_id, user_id=g.user.id).first()
            if not motorcycle: errors['motorcycle_id'] = '有効な車両を選択してください。'
        else: errors['motorcycle_id'] = '車両を選択してください。'
        if entry_date_str:
            try: entry_date = date.fromisoformat(entry_date_str)
            except ValueError: errors['entry_date'] = '有効な日付形式 (YYYY-MM-DD) で入力してください。'
        else: errors['entry_date'] = '給油日は必須です。'

        # 日付と車両が有効なら前回情報を取得
        if not errors.get('entry_date') and not errors.get('motorcycle_id'):
             previous_entry = get_previous_fuel_entry(motorcycle.id, entry_date)

        if odometer_reading_str:
            try:
                odometer_reading = int(odometer_reading_str)
                if odometer_reading < 0: errors['odometer_reading'] = 'ODOメーター値は0以上で入力してください。'
                elif motorcycle:
                    current_offset = motorcycle.odometer_offset or 0
                    current_total_distance = odometer_reading + current_offset
                    if previous_entry and current_total_distance < previous_entry.total_distance:
                         flash(f'注意: ODOメーター値から計算される総走行距離 ({current_total_distance:,}km) が、前回記録 ({previous_entry.entry_date.strftime("%Y-%m-%d")} の {previous_entry.total_distance:,}km) より小さくなっています。', 'warning')
            except ValueError: errors['odometer_reading'] = 'ODOメーター値は有効な数値を入力してください。'
        else: errors['odometer_reading'] = 'ODOメーター値は必須です。'

        if fuel_volume_str:
            try: fuel_volume = float(fuel_volume_str); assert fuel_volume > 0
            except (ValueError, AssertionError): errors['fuel_volume'] = '給油量は0より大きい数値を入力してください。'
        else: errors['fuel_volume'] = '給油量は必須です。'
        if price_per_liter_str:
            try: price_per_liter = float(price_per_liter_str); assert price_per_liter >= 0
            except (ValueError, AssertionError): errors['price_per_liter'] = 'リッター単価は0以上の有効な数値を入力してください。'
        if total_cost_str:
            try: total_cost = float(total_cost_str); assert total_cost >= 0
            except (ValueError, AssertionError): errors['total_cost'] = '合計金額は0以上の有効な数値を入力してください。'

        if errors:
            for field, msg in errors.items(): flash(f'{msg}', 'danger')
            entry_data_for_form = request.form.to_dict()
            entry_data_for_form['entry_date_obj'] = entry_date
            try: entry_data_for_form['motorcycle_id_int'] = int(motorcycle_id) if motorcycle_id else None
            except ValueError: entry_data_for_form['motorcycle_id_int'] = None
            today_iso_str = date.today().isoformat()
            # --- ▼▼▼ エラー時も前回情報を整形して渡す ▼▼▼ ---
            previous_info = None
            if previous_entry:
                previous_info = {
                    'date': previous_entry.entry_date.strftime('%Y-%m-%d'),
                    'odo': f"{previous_entry.odometer_reading:,}km"
                }
            # --- ▲▲▲ ここまで ▲▲▲ ---
            return render_template('fuel_form.html',
                                   form_action='add', entry=entry_data_for_form,
                                   motorcycles=user_motorcycles, today_iso=today_iso_str,
                                   gas_station_brands=GAS_STATION_BRANDS, # ブランドリスト
                                   previous_entry_info=previous_info) # 前回情報
        else:
            if not motorcycle: motorcycle = Motorcycle.query.filter_by(id=motorcycle_id, user_id=g.user.id).first()
            total_distance = odometer_reading + (motorcycle.odometer_offset or 0)
            if total_cost is None and price_per_liter is not None and fuel_volume is not None:
                total_cost = round(price_per_liter * fuel_volume, 2)

            new_entry = FuelEntry(
                motorcycle_id=motorcycle_id, entry_date=entry_date,
                odometer_reading=odometer_reading, total_distance=total_distance,
                fuel_volume=fuel_volume, price_per_liter=price_per_liter,
                total_cost=total_cost, station_name=station_name if station_name else None,
                fuel_type=fuel_type, notes=notes, is_full_tank=is_full_tank
            )
            try:
                db.session.add(new_entry); db.session.commit()
                flash('給油記録を追加しました。', 'success'); return redirect(url_for('fuel.fuel_log'))
            except Exception as e:
                db.session.rollback(); flash(f'記録のデータベース保存中にエラーが発生しました。', 'error')
                current_app.logger.error(f"Error saving fuel entry: {e}")
                entry_data_for_form = request.form.to_dict(); entry_data_for_form['entry_date_obj'] = entry_date
                try: entry_data_for_form['motorcycle_id_int'] = int(motorcycle_id) if motorcycle_id else None
                except ValueError: entry_data_for_form['motorcycle_id_int'] = None
                today_iso_str = date.today().isoformat()
                # --- ▼▼▼ エラー時も前回情報を整形して渡す ▼▼▼ ---
                previous_info = None
                if previous_entry:
                     previous_info = { 'date': previous_entry.entry_date.strftime('%Y-%m-%d'), 'odo': f"{previous_entry.odometer_reading:,}km" }
                # --- ▲▲▲ ここまで ▲▲▲ ---
                return render_template('fuel_form.html', form_action='add', entry=entry_data_for_form, motorcycles=user_motorcycles, today_iso=today_iso_str, gas_station_brands=GAS_STATION_BRANDS, previous_entry_info=previous_info)
    else: # GET
        today_iso_str = date.today().isoformat()
        preselected_motorcycle_id = request.args.get('motorcycle_id', type=int)
        preselected_moto = None
        if preselected_motorcycle_id:
            preselected_moto = Motorcycle.query.filter_by(id=preselected_motorcycle_id, user_id=g.user.id).first()
            if not preselected_moto: preselected_motorcycle_id = None

        # --- ▼▼▼ GET時にも前回情報を取得 ---
        previous_entry_info = None
        if preselected_moto:
            today_date = date.today()
            previous_entry = get_previous_fuel_entry(preselected_moto.id, today_date)
            if previous_entry:
                previous_entry_info = {
                    'date': previous_entry.entry_date.strftime('%Y-%m-%d'),
                    'odo': f"{previous_entry.odometer_reading:,}km"
                }
        # --- ▲▲▲ GET時の前回情報取得ここまで ---

        return render_template('fuel_form.html',
                               form_action='add', entry=None,
                               motorcycles=user_motorcycles, today_iso=today_iso_str,
                               preselected_motorcycle_id=preselected_motorcycle_id,
                               # --- ▼▼▼ ブランドリストと前回情報を渡す ---
                               gas_station_brands=GAS_STATION_BRANDS,
                               previous_entry_info=previous_entry_info
                               # --- ▲▲▲ ここまで ---
                               )

# --- 給油記録の編集 ---
@fuel_bp.route('/<int:entry_id>/edit', methods=['GET', 'POST'])
@login_required_custom
def edit_fuel(entry_id):
    entry = FuelEntry.query.filter(FuelEntry.id == entry_id).join(Motorcycle).filter(Motorcycle.user_id == g.user.id).first_or_404()
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.name).all()

    if request.method == 'POST':
        entry_date_str = request.form.get('entry_date'); odometer_reading_str = request.form.get('odometer_reading')
        fuel_volume_str = request.form.get('fuel_volume'); price_per_liter_str = request.form.get('price_per_liter')
        total_cost_str = request.form.get('total_cost'); station_name = request.form.get('station_name', '').strip()
        fuel_type = request.form.get('fuel_type'); notes = request.form.get('notes'); is_full_tank = 'is_full_tank' in request.form
        errors = {}; entry_date = None; odometer_reading = None; fuel_volume = None; price_per_liter = None; total_cost = None; previous_entry = None

        if entry_date_str:
            try: entry_date = date.fromisoformat(entry_date_str)
            except ValueError: errors['entry_date'] = '有効な日付形式 (YYYY-MM-DD) で入力してください。'
        else: errors['entry_date'] = '給油日は必須です。'

        # 日付が有効なら前回情報を取得（編集中の記録を除く）
        if not errors.get('entry_date'):
             previous_entry = get_previous_fuel_entry(entry.motorcycle_id, entry_date, entry.id)

        if odometer_reading_str:
            try:
                odometer_reading = int(odometer_reading_str)
                if odometer_reading < 0: errors['odometer_reading'] = 'ODOメーター値は0以上で入力してください。'
                elif entry.motorcycle:
                    current_offset = entry.motorcycle.odometer_offset or 0
                    current_total_distance = odometer_reading + current_offset
                    if previous_entry and current_total_distance < previous_entry.total_distance:
                         flash(f'注意: ODOメーター値から計算される総走行距離 ({current_total_distance:,}km) が、前回記録 ({previous_entry.entry_date.strftime("%Y-%m-%d")} の {previous_entry.total_distance:,}km) より小さくなっています。', 'warning')
            except ValueError: errors['odometer_reading'] = 'ODOメーター値は有効な数値を入力してください。'
        else: errors['odometer_reading'] = 'ODOメーター値は必須です。'

        if fuel_volume_str:
            try: fuel_volume = float(fuel_volume_str); assert fuel_volume > 0
            except (ValueError, AssertionError): errors['fuel_volume'] = '給油量は0より大きい数値を入力してください。'
        else: errors['fuel_volume'] = '給油量は必須です。'
        if price_per_liter_str:
            try: price_per_liter = float(price_per_liter_str); assert price_per_liter >= 0
            except (ValueError, AssertionError): errors['price_per_liter'] = 'リッター単価は0以上の有効な数値を入力してください。'
        if total_cost_str:
            try: total_cost = float(total_cost_str); assert total_cost >= 0
            except (ValueError, AssertionError): errors['total_cost'] = '合計金額は0以上の有効な数値を入力してください。'

        if errors:
            for field, msg in errors.items(): flash(f'{msg}', 'danger')
            today_iso_str = date.today().isoformat()
            # --- ▼▼▼ エラー時も前回情報を整形して渡す ▼▼▼ ---
            previous_info = None
            if previous_entry:
                previous_info = { 'date': previous_entry.entry_date.strftime('%Y-%m-%d'), 'odo': f"{previous_entry.odometer_reading:,}km" }
            # --- ▲▲▲ ここまで ▲▲▲ ---
            return render_template('fuel_form.html', form_action='edit', entry=entry, motorcycles=user_motorcycles, today_iso=today_iso_str, gas_station_brands=GAS_STATION_BRANDS, previous_entry_info=previous_info)
        else:
            try:
                entry.entry_date = entry_date; entry.odometer_reading = odometer_reading; entry.fuel_volume = fuel_volume
                entry.price_per_liter = price_per_liter if price_per_liter is not None else None
                entry.total_cost = total_cost if total_cost is not None else None
                entry.station_name = station_name if station_name else None
                entry.fuel_type = fuel_type if fuel_type else None
                entry.notes = notes if notes else None
                entry.is_full_tank = is_full_tank
                entry.total_distance = entry.odometer_reading + (entry.motorcycle.odometer_offset or 0)
                if entry.total_cost is None and entry.price_per_liter is not None and entry.fuel_volume is not None:
                    entry.total_cost = round(entry.price_per_liter * entry.fuel_volume, 2)
                db.session.commit()
                flash('給油記録を更新しました。', 'success'); return redirect(url_for('fuel.fuel_log'))
            except Exception as e:
                db.session.rollback(); flash(f'記録の更新中にエラーが発生しました。', 'error')
                current_app.logger.error(f"Error updating fuel entry {entry_id}: {e}")
                today_iso_str = date.today().isoformat()
                # --- ▼▼▼ エラー時も前回情報を整形して渡す ▼▼▼ ---
                previous_info = None
                if previous_entry:
                    previous_info = { 'date': previous_entry.entry_date.strftime('%Y-%m-%d'), 'odo': f"{previous_entry.odometer_reading:,}km" }
                # --- ▲▲▲ ここまで ▲▲▲ ---
                return render_template('fuel_form.html', form_action='edit', entry=entry, motorcycles=user_motorcycles, today_iso=today_iso_str, gas_station_brands=GAS_STATION_BRANDS, previous_entry_info=previous_info)
    else: # GET
        today_iso_str = date.today().isoformat()
        # --- ▼▼▼ GET時にも前回情報を取得 ---
        previous_entry_info = None
        previous_entry = get_previous_fuel_entry(entry.motorcycle_id, entry.entry_date, entry.id)
        if previous_entry:
            previous_entry_info = {
                'date': previous_entry.entry_date.strftime('%Y-%m-%d'),
                'odo': f"{previous_entry.odometer_reading:,}km"
            }
        # --- ▲▲▲ GET時の前回情報取得ここまで ---

        return render_template('fuel_form.html',
                               form_action='edit', entry=entry,
                               motorcycles=user_motorcycles, today_iso=today_iso_str,
                               # --- ▼▼▼ ブランドリストと前回情報を渡す ---
                               gas_station_brands=GAS_STATION_BRANDS,
                               previous_entry_info=previous_entry_info
                               # --- ▲▲▲ ここまで ---
                               )

# --- 給油記録の削除 (変更なし) ---
@fuel_bp.route('/<int:entry_id>/delete', methods=['POST'])
@login_required_custom
def delete_fuel(entry_id):
    entry = FuelEntry.query.filter(FuelEntry.id == entry_id).join(Motorcycle).filter(Motorcycle.user_id == g.user.id).first_or_404()
    try:
        db.session.delete(entry); db.session.commit()
        flash('給油記録を削除しました。', 'success')
    except Exception as e:
        db.session.rollback(); flash(f'記録の削除中にエラーが発生しました。', 'error')
        current_app.logger.error(f"Error deleting fuel entry {entry_id}: {e}")
    return redirect(url_for('fuel.fuel_log'))