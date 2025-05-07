# motopuppu/views/fuel.py

from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, abort, current_app
)
from datetime import date # dateオブジェクトのみ使用
# datetimeオブジェクトは不要になったため削除

from sqlalchemy import or_, asc, desc

from .auth import login_required_custom, get_current_user # ユーザー認証関連
from ..models import db, Motorcycle, FuelEntry # DBモデル
from ..forms import FuelForm, GAS_STATION_BRANDS # ★ 作成したFuelFormとスタンド名リストをインポート

fuel_bp = Blueprint('fuel', __name__, url_prefix='/fuel')

def get_previous_fuel_entry(motorcycle_id, current_entry_date, current_entry_id=None):
    """
    指定された車両IDと日付に基づいて、直前の給油記録を取得する。
    current_entry_id が指定された場合、そのIDの記録は除外する (編集時用)。
    """
    if not motorcycle_id or not current_entry_date:
        return None
    query = FuelEntry.query.filter(
        FuelEntry.motorcycle_id == motorcycle_id,
        FuelEntry.entry_date < current_entry_date
    )
    if current_entry_id is not None:
        query = query.filter(FuelEntry.id != current_entry_id)
    previous_entry = query.order_by(FuelEntry.entry_date.desc(), FuelEntry.total_distance.desc()).first()
    return previous_entry

@fuel_bp.route('/')
@login_required_custom
def fuel_log():
    """給油記録の一覧を表示 (フィルター・ソート機能付き)"""
    # (このルートのロジックはFlask-WTF導入の影響を直接受けないため、ほぼ変更なし)
    # (ただし、フィルター部分のバリデーションも将来的にFlask-WTFで扱うことも可能)
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    vehicle_id_str = request.args.get('vehicle_id')
    keyword = request.args.get('q', '').strip()
    sort_by = request.args.get('sort_by', 'date') # デフォルトは日付
    order = request.args.get('order', 'desc')     # デフォルトは降順
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('FUEL_ENTRIES_PER_PAGE', 20)

    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    if not user_motorcycles: # 車両が1台も登録されていなければメッセージを表示して車両登録を促す
        flash('給油記録を閲覧・追加するには、まず車両を登録してください。', 'info')
        return redirect(url_for('vehicle.add_vehicle'))

    user_motorcycle_ids = [m.id for m in user_motorcycles]

    query = db.session.query(FuelEntry).join(Motorcycle).filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids))

    request_args_dict = request.args.to_dict()
    request_args_dict.pop('page', None)
    request_args_dict.pop('sort_by', None)
    request_args_dict.pop('order', None)

    # フィルター適用
    try:
        if start_date_str:
            query = query.filter(FuelEntry.entry_date >= date.fromisoformat(start_date_str))
        else: request_args_dict.pop('start_date', None) # キーが存在しない場合は削除
        if end_date_str:
            query = query.filter(FuelEntry.entry_date <= date.fromisoformat(end_date_str))
        else: request_args_dict.pop('end_date', None)
    except ValueError:
        flash('日付の形式が無効です。YYYY-MM-DD形式で入力してください。', 'warning')
        request_args_dict.pop('start_date', None) # エラー時はキーを削除
        request_args_dict.pop('end_date', None)

    if vehicle_id_str:
        try:
            vehicle_id = int(vehicle_id_str)
            if vehicle_id in user_motorcycle_ids:
                query = query.filter(FuelEntry.motorcycle_id == vehicle_id)
            else:
                flash('選択された車両は有効ではありません。', 'warning')
                request_args_dict.pop('vehicle_id', None)
        except ValueError:
            request_args_dict.pop('vehicle_id', None) # 無効な値ならキー削除
    else:
        request_args_dict.pop('vehicle_id', None)

    if keyword:
        search_term = f'%{keyword}%'
        query = query.filter(or_(FuelEntry.notes.ilike(search_term), FuelEntry.station_name.ilike(search_term)))
    else:
        request_args_dict.pop('q', None)

    # ソート処理
    sort_column_map = {
        'date': FuelEntry.entry_date,
        'vehicle': Motorcycle.name, # Join済みなのでMotorcycle.nameでソート可能
        'odo': FuelEntry.odometer_reading,
        'volume': FuelEntry.fuel_volume,
        'price': FuelEntry.price_per_liter,
        'cost': FuelEntry.total_cost,
        'station': FuelEntry.station_name,
    }
    sort_column = sort_column_map.get(sort_by, FuelEntry.entry_date)
    current_sort_by = sort_by if sort_by in sort_column_map else 'date'
    current_order = 'desc' if order == 'desc' else 'asc'

    sort_modifier = desc if current_order == 'desc' else asc

    # SQLAlchemyのソート順は .asc() または .desc() メソッドで指定
    if sort_column == FuelEntry.entry_date: # 日付の場合、同じ日付ならODO降順
        query = query.order_by(sort_modifier(FuelEntry.entry_date), desc(FuelEntry.total_distance))
    elif sort_column == FuelEntry.odometer_reading: # ODOの場合、同じODOなら日付降順
        query = query.order_by(sort_modifier(FuelEntry.odometer_reading), desc(FuelEntry.entry_date))
    else:
        query = query.order_by(sort_modifier(sort_column))


    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    fuel_entries = pagination.items

    return render_template('fuel_log.html',
                           entries=fuel_entries,
                           pagination=pagination,
                           motorcycles=user_motorcycles, # フィルター用
                           request_args=request_args_dict,
                           current_sort_by=current_sort_by,
                           current_order=current_order
                           )


@fuel_bp.route('/add', methods=['GET', 'POST'])
@login_required_custom
def add_fuel():
    """新しい給油記録を追加"""
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    if not user_motorcycles:
        flash('給油記録を追加するには、まず車両を登録してください。', 'warning')
        return redirect(url_for('vehicle.add_vehicle'))

    form = FuelForm()
    # SelectFieldの選択肢を動的に設定
    form.motorcycle_id.choices = [(m.id, f"{m.name} ({m.maker or 'メーカー不明'})") for m in user_motorcycles]

    previous_entry_info = None # テンプレート表示用

    # GETリクエスト時の初期値設定
    if request.method == 'GET':
        # デフォルト車両を事前選択
        default_vehicle = next((m for m in user_motorcycles if m.is_default), user_motorcycles[0] if user_motorcycles else None)
        if default_vehicle:
            form.motorcycle_id.data = default_vehicle.id

        # URLクエリからの車両ID指定があればそれを優先
        preselected_motorcycle_id = request.args.get('motorcycle_id', type=int)
        if preselected_motorcycle_id and any(m.id == preselected_motorcycle_id for m in user_motorcycles):
            form.motorcycle_id.data = preselected_motorcycle_id
        
        form.entry_date.data = date.today() # 給油日のデフォルトを今日に
        form.is_full_tank.data = True # 満タンをデフォルトに

    if form.validate_on_submit(): # POSTリクエストでバリデーション成功
        motorcycle = Motorcycle.query.filter_by(id=form.motorcycle_id.data, user_id=g.user.id).first()
        if not motorcycle: # 通常はSelectFieldのchoicesで防がれる
            flash('選択された車両が見つかりません。再度お試しください。', 'danger')
            return render_template('fuel_form.html', form_action='add', form=form, gas_station_brands=GAS_STATION_BRANDS, previous_entry_info=None)

        # 総走行距離の計算 (ODO + オフセット)
        total_distance = form.odometer_reading.data + (motorcycle.odometer_offset or 0)

        # ODOメーター値の整合性チェック (前回記録との比較) - 警告のみ
        previous_entry_for_check = get_previous_fuel_entry(motorcycle.id, form.entry_date.data)
        if previous_entry_for_check and total_distance < previous_entry_for_check.total_distance:
            flash(f'注意: 今回の総走行距離 ({total_distance:,}km) が、前回記録 ({previous_entry_for_check.entry_date.strftime("%Y-%m-%d")} の {previous_entry_for_check.total_distance:,}km) より小さくなっています。入力内容を確認してください。', 'warning')

        # 合計金額の自動計算ロジック (入力がなければ)
        total_cost_val = form.total_cost.data
        if total_cost_val is None and form.price_per_liter.data is not None and form.fuel_volume.data is not None:
            # WTFormsのDecimalFieldはDecimal型を返すので、計算時はfloatに変換
            try:
                total_cost_val = round(float(form.price_per_liter.data) * float(form.fuel_volume.data)) # 端数は四捨五入して整数円
            except TypeError: # データ型が不正な場合はNoneのまま
                total_cost_val = None
        elif total_cost_val is not None: # 手入力された場合は整数に丸める
            total_cost_val = int(round(float(total_cost_val)))


        new_entry = FuelEntry(
            motorcycle_id=motorcycle.id,
            entry_date=form.entry_date.data,
            odometer_reading=form.odometer_reading.data,
            total_distance=total_distance,
            fuel_volume=float(form.fuel_volume.data), # DBモデルに合わせてfloatに
            price_per_liter=float(form.price_per_liter.data) if form.price_per_liter.data is not None else None,
            total_cost=total_cost_val, # 計算済みまたは入力された値
            station_name=form.station_name.data.strip() if form.station_name.data else None,
            fuel_type=form.fuel_type.data.strip() if form.fuel_type.data else None,
            notes=form.notes.data.strip() if form.notes.data else None,
            is_full_tank=form.is_full_tank.data
        )
        try:
            db.session.add(new_entry)
            db.session.commit()
            flash('給油記録を追加しました。', 'success')
            return redirect(url_for('fuel.fuel_log'))
        except Exception as e:
            db.session.rollback()
            flash(f'記録のデータベース保存中にエラーが発生しました。詳細は管理者にお問い合わせください。', 'error')
            current_app.logger.error(f"Error saving new fuel entry: {e}", exc_info=True)
            # エラー時は form オブジェクトがエラー情報と入力値を保持してテンプレートに渡される
            
    elif request.method == 'POST': # バリデーション失敗時
        # エラーメッセージはWTFormsがformオブジェクトに格納するので、ここで個別flashは不要
        # flash('入力内容に誤りがあります。内容を確認してください。', 'danger') # 必要なら一般的なエラーを出す
        # motorcycle_id の choices はPOSTリクエストでも再設定が必要 (テンプレートで表示するため)
        form.motorcycle_id.choices = [(m.id, f"{m.name} ({m.maker or 'メーカー不明'})") for m in user_motorcycles]


    # GETリクエスト時、またはPOSTでバリデーション失敗時に前回給油情報を取得
    # form.<field>.dataにはバリデーション失敗時でもユーザーの入力値が保持されている
    # ただし、データ型変換に失敗した場合はNoneになることがあるので注意
    selected_motorcycle_id_for_prev = form.motorcycle_id.data
    entry_date_for_prev = form.entry_date.data
    if selected_motorcycle_id_for_prev and entry_date_for_prev:
        previous_fuel = get_previous_fuel_entry(selected_motorcycle_id_for_prev, entry_date_for_prev)
        if previous_fuel:
            previous_entry_info = {
                'date': previous_fuel.entry_date.strftime('%Y-%m-%d'),
                'odo': f"{previous_fuel.odometer_reading:,}km"
            }

    return render_template('fuel_form.html',
                           form_action='add',
                           form=form, # フォームオブジェクトをテンプレートへ
                           gas_station_brands=GAS_STATION_BRANDS, # datalist用
                           previous_entry_info=previous_entry_info)


@fuel_bp.route('/<int:entry_id>/edit', methods=['GET', 'POST'])
@login_required_custom
def edit_fuel(entry_id):
    """既存の給油記録を編集"""
    entry = FuelEntry.query.filter(FuelEntry.id == entry_id)\
                           .join(Motorcycle).filter(Motorcycle.user_id == g.user.id)\
                           .first_or_404()
    
    # 編集時はobj=entryでフォームに既存データをロード
    form = FuelForm(obj=entry)
    
    # motorcycle_id は編集不可とするため、choicesは設定するが表示のみ (テンプレート側でdisabled)
    # 現在の車両のみを選択肢として設定 (変更不可のため)
    form.motorcycle_id.choices = [(entry.motorcycle.id, f"{entry.motorcycle.name} ({entry.motorcycle.maker or 'メーカー不明'})")]
    form.motorcycle_id.data = entry.motorcycle_id # 確実に現在の車両IDを設定

    previous_entry_info = None # テンプレート表示用

    if form.validate_on_submit():
        # motorcycle_id は変更しない前提
        motorcycle = entry.motorcycle # 既存の車両情報をそのまま使用

        total_distance = form.odometer_reading.data + (motorcycle.odometer_offset or 0)
        previous_entry_for_check = get_previous_fuel_entry(motorcycle.id, form.entry_date.data, entry.id) # 編集対象を除外
        if previous_entry_for_check and total_distance < previous_entry_for_check.total_distance:
             flash(f'注意: 今回の総走行距離 ({total_distance:,}km) が、前回記録 ({previous_entry_for_check.entry_date.strftime("%Y-%m-%d")} の {previous_entry_for_check.total_distance:,}km) より小さくなっています。入力内容を確認してください。', 'warning')

        total_cost_val = form.total_cost.data
        if total_cost_val is None and form.price_per_liter.data is not None and form.fuel_volume.data is not None:
            try:
                total_cost_val = round(float(form.price_per_liter.data) * float(form.fuel_volume.data))
            except TypeError:
                total_cost_val = None
        elif total_cost_val is not None:
            total_cost_val = int(round(float(total_cost_val)))

        # フォームデータでentryオブジェクトを更新
        entry.entry_date = form.entry_date.data
        entry.odometer_reading = form.odometer_reading.data
        entry.total_distance = total_distance # 再計算した値
        entry.fuel_volume = float(form.fuel_volume.data)
        entry.price_per_liter = float(form.price_per_liter.data) if form.price_per_liter.data is not None else None
        entry.total_cost = total_cost_val
        entry.station_name = form.station_name.data.strip() if form.station_name.data else None
        entry.fuel_type = form.fuel_type.data.strip() if form.fuel_type.data else None
        entry.notes = form.notes.data.strip() if form.notes.data else None
        entry.is_full_tank = form.is_full_tank.data
        try:
            db.session.commit()
            flash('給油記録を更新しました。', 'success')
            return redirect(url_for('fuel.fuel_log'))
        except Exception as e:
            db.session.rollback()
            flash(f'記録の更新中にエラーが発生しました。詳細は管理者にお問い合わせください。', 'error')
            current_app.logger.error(f"Error updating fuel entry ID {entry_id}: {e}", exc_info=True)
    
    elif request.method == 'POST': # バリデーション失敗時
        # エラーメッセージはWTFormsがformオブジェクトに格納
        # flash('入力内容に誤りがあります。内容を確認してください。', 'danger') # 必要なら一般的なエラーを出す
        # motorcycle_id の choices はPOSTリクエストでも再設定が必要
        form.motorcycle_id.choices = [(entry.motorcycle.id, f"{entry.motorcycle.name} ({entry.motorcycle.maker or 'メーカー不明'})")]
        form.motorcycle_id.data = entry.motorcycle_id


    # GETリクエスト時、またはPOSTでバリデーション失敗時に前回給油情報を取得
    # 編集時は車両IDは固定
    current_motorcycle_id_for_prev = entry.motorcycle_id
    # form.entry_date.data にはバリデーション失敗時のユーザー入力値が入っている
    # GET時は obj=entry で初期化されているので entry.entry_date が使われる
    entry_date_for_prev = form.entry_date.data if form.entry_date.data else entry.entry_date

    if current_motorcycle_id_for_prev and entry_date_for_prev:
        previous_fuel = get_previous_fuel_entry(current_motorcycle_id_for_prev, entry_date_for_prev, entry.id) # 自分自身は除外
        if previous_fuel:
            previous_entry_info = {
                'date': previous_fuel.entry_date.strftime('%Y-%m-%d'),
                'odo': f"{previous_fuel.odometer_reading:,}km"
            }
    
    return render_template('fuel_form.html',
                           form_action='edit',
                           form=form, # フォームオブジェクトをテンプレートへ
                           entry_id=entry.id, # action URL生成と、テンプレート内での判定用
                           gas_station_brands=GAS_STATION_BRANDS,
                           previous_entry_info=previous_entry_info)


@fuel_bp.route('/<int:entry_id>/delete', methods=['POST'])
@login_required_custom
def delete_fuel(entry_id):
    """給油記録を削除"""
    # (このルートのロジックは変更なし)
    entry = FuelEntry.query.filter(FuelEntry.id == entry_id)\
                           .join(Motorcycle).filter(Motorcycle.user_id == g.user.id)\
                           .first_or_404()
    try:
        db.session.delete(entry)
        db.session.commit()
        flash('給油記録を削除しました。', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'記録の削除中にエラーが発生しました。詳細は管理者にお問い合わせください。', 'error')
        current_app.logger.error(f"Error deleting fuel entry ID {entry_id}: {e}", exc_info=True)
    return redirect(url_for('fuel.fuel_log'))