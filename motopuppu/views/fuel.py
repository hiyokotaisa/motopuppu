# motopuppu/views/fuel.py
import csv
import io
from datetime import date, datetime
import os
import requests

from flask import (
    Blueprint, flash, redirect, render_template, request, url_for, abort, current_app, Response, jsonify
)
from sqlalchemy import or_, asc, desc, func, and_, case
from sqlalchemy.orm import joinedload

from flask_login import login_required, current_user
from ..models import db, Motorcycle, FuelEntry
from ..forms import FuelForm, FuelCsvUploadForm
from ..constants import GAS_STATION_BRANDS
from ..achievement_evaluator import check_achievements_for_event, EVENT_ADD_FUEL_LOG
from .. import limiter
from ..utils.receipt_parser import parse_receipt_image


fuel_bp = Blueprint('fuel', __name__, url_prefix='/fuel')

def _process_fuel_csv_import(file_stream, motorcycle: Motorcycle):
    """
    アップロードされたCSVファイルを解析し、給油記録をデータベースに登録する。
    重複チェック（ドライラン）と本実行の2段階で行う。

    Args:
        file_stream: アップロードされたCSVファイルのストリーム。
        motorcycle: 登録対象のMotorcycleオブジェクト。

    Returns:
        (int, list, list): (成功した件数, エラーメッセージのリスト, 重複データのリスト) のタプル。
    """
    required_headers = {'entry_date', 'odometer_reading', 'fuel_volume'}
    errors = []
    duplicates = []
    
    try:
        wrapper = io.TextIOWrapper(file_stream, encoding='utf-8-sig')
        # 全ての行を一度に読み込む
        all_rows = list(csv.reader(wrapper))

        # --- ヘッダーの特定と検証 ---
        header_row_index = -1
        for i, row in enumerate(all_rows):
            if row and not row[0].strip().startswith('#'):
                header_row_index = i
                break
        
        if header_row_index == -1:
            errors.append("CSVファイルにヘッダー行が見つかりませんでした。")
            return 0, errors, []

        header = [h.strip().lower() for h in all_rows[header_row_index]]
        if not required_headers.issubset(set(header)):
            missing = required_headers - set(header)
            errors.append(f"CSVファイルのヘッダーに必須項目がありません: {', '.join(missing)}")
            return 0, errors, []

        # --- 1. ドライラン（事前チェック）ステージ ---
        valid_rows_to_check = []
        for row_num, row in enumerate(all_rows[header_row_index + 1:], start=header_row_index + 2):
            if not row or (row and row[0].strip().startswith('#')):
                continue
            
            try:
                row_data = dict(zip(header, row))
                entry_date = date.fromisoformat(row_data.get('entry_date', '').strip())
                odometer_reading = int(row_data.get('odometer_reading', '').strip())
                valid_rows_to_check.append({'date': entry_date, 'odo': odometer_reading, 'row_num': row_num})
            except (ValueError, TypeError):
                errors.append(f"{row_num}行目: 日付またはODOメーターの形式が正しくありません。")

        if errors:
            return 0, errors, []

        # --- データベースで既存レコードを一括クエリ ---
        if valid_rows_to_check:
            conditions = [
                and_(FuelEntry.motorcycle_id == motorcycle.id, FuelEntry.entry_date == item['date'], FuelEntry.odometer_reading == item['odo'])
                for item in valid_rows_to_check
            ]
            existing_records_query = FuelEntry.query.filter(or_(*conditions)).with_entities(FuelEntry.entry_date, FuelEntry.odometer_reading)
            existing_keys = {(rec.entry_date, rec.odometer_reading) for rec in existing_records_query.all()}
            
            for item in valid_rows_to_check:
                if (item['date'], item['odo']) in existing_keys:
                    duplicates.append(f"{item['row_num']}行目 (日付: {item['date']}, ODO: {item['odo']}km)")

        # 重複が見つかった場合は、ここで処理を中断して警告
        if duplicates:
            return 0, [], duplicates

        # --- 2. 本実行ステージ ---
        entries_to_add = []
        for row_num, row in enumerate(all_rows[header_row_index + 1:], start=header_row_index + 2):
            if not row or (row and row[0].strip().startswith('#')):
                continue

            try:
                # バリデーションは済んでいるが、再度データを整形
                row_data = dict(zip(header, row))
                entry_date = date.fromisoformat(row_data.get('entry_date', '').strip())
                odometer_reading = int(row_data.get('odometer_reading', '').strip())
                fuel_volume = float(row_data.get('fuel_volume', '').strip())
                
                price_per_liter = float(row_data.get('price_per_liter', '').strip()) if row_data.get('price_per_liter', '').strip() else None
                total_cost = int(row_data.get('total_cost', '').strip()) if row_data.get('total_cost', '').strip() else None
                
                if total_cost is None and price_per_liter is not None:
                    total_cost = round(price_per_liter * fuel_volume)

                is_full_tank_str = row_data.get('is_full_tank', 'true').strip().lower()
                is_full_tank = is_full_tank_str in ['true', '1', 'yes', 'はい', 't']
                exclude_str = row_data.get('exclude_from_average', 'false').strip().lower()
                exclude_from_average = exclude_str in ['true', '1', 'yes', 'はい', 't']

                offset_at_entry_date = motorcycle.calculate_cumulative_offset_from_logs(target_date=entry_date)
                total_distance = odometer_reading + offset_at_entry_date

                new_entry = FuelEntry(
                    motorcycle_id=motorcycle.id, entry_date=entry_date, odometer_reading=odometer_reading,
                    total_distance=total_distance, fuel_volume=fuel_volume, price_per_liter=price_per_liter,
                    total_cost=total_cost, station_name=row_data.get('station_name', '').strip() or None,
                    fuel_type=row_data.get('fuel_type', '').strip() or None, notes=row_data.get('notes', '').strip() or None,
                    is_full_tank=is_full_tank, exclude_from_average=exclude_from_average
                )
                entries_to_add.append(new_entry)
            except Exception as e:
                # 基本的にここまで来ないはずだが念のため
                errors.append(f"{row_num}行目: 予期せぬエラーが発生しました。({e})")

        if not errors and entries_to_add:
            db.session.add_all(entries_to_add)
            db.session.commit()
            for entry in entries_to_add:
                event_data_for_ach = {'new_fuel_log_id': entry.id, 'motorcycle_id': motorcycle.id}
                check_achievements_for_event(current_user, EVENT_ADD_FUEL_LOG, event_data=event_data_for_ach)
            return len(entries_to_add), [], []
        else:
            db.session.rollback()
            return 0, errors, []

    except Exception as e:
        db.session.rollback()
        errors.append(f"ファイル処理中に致命的なエラーが発生しました: {e}")
        return 0, errors, []


def get_previous_fuel_entry(motorcycle_id, current_entry_date, current_entry_id=None):
    if not motorcycle_id or not current_entry_date:
        return None
    query = FuelEntry.query.filter(
        FuelEntry.motorcycle_id == motorcycle_id,
        FuelEntry.entry_date <= current_entry_date
    )
    if current_entry_id is not None:
        query = query.filter(FuelEntry.id != current_entry_id)

    previous_entry = query.order_by(FuelEntry.entry_date.desc(), FuelEntry.odometer_reading.desc(), FuelEntry.id.desc()).first()
    return previous_entry



from ..utils.fuel_calculator import calculate_kpl_bulk

@fuel_bp.route('/search_gas_station')
@limiter.limit("30 per minute")
@login_required
def search_gas_station():
    """フロントエンドからのリクエストでガソリンスタンドを検索するAPIエンドポイント"""
    query = request.args.get('q', type=str)
    if not query:
        return jsonify({'error': 'Query parameter is missing'}), 400

    api_key = current_app.config.get('GOOGLE_PLACES_API_KEY')
    if not api_key:
        current_app.logger.error("GOOGLE_PLACES_API_KEY is not set in the environment.")
        return jsonify({'error': 'API key is not configured on the server.'}), 500

    endpoint_url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    
    params = {
        'query': query,
        'key': api_key,
        'language': 'ja',
        'type': 'gas_station'
    }

    try:
        response = requests.get(endpoint_url, params=params, timeout=5)
        response.raise_for_status()
        
        data = response.json()
        
        results = [
            {'name': place.get('name'), 'address': place.get('formatted_address')}
            for place in data.get('results', [])
        ]
        
        return jsonify({'results': results})

    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Failed to call Google Places API: {e}")
        return jsonify({'error': 'Failed to communicate with the search service.'}), 503
    except Exception as e:
        current_app.logger.error(f"An unexpected error occurred during gas station search: {e}")
        return jsonify({'error': 'An internal server error occurred.'}), 500


@fuel_bp.route('/parse_receipt', methods=['POST'])
@limiter.limit("10 per day")
@login_required
def parse_receipt():
    """レシート画像をアップロードして解析結果を返すAPI"""
    if 'receipt_image' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['receipt_image']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if not file or not file.content_type.startswith('image/'):
        return jsonify({'error': 'Invalid file type. Please upload an image.'}), 400

    # ファイルサイズチェック (例: 10MB以下)
    file.seek(0, os.SEEK_END)
    file_length = file.tell()
    if file_length > 10 * 1024 * 1024:
        return jsonify({'error': 'File size too large. Max 10MB.'}), 400
    file.seek(0)

    try:
        image_bytes = file.read()
        result = parse_receipt_image(image_bytes, mime_type=file.content_type)
        
        if result['success']:
            return jsonify(result['data'])
        else:
            return jsonify({'error': result.get('error', 'Unknown error occurred')}), 500
            
    except Exception as e:
        current_app.logger.error(f"Error in parse_receipt route: {e}")
        return jsonify({'error': 'Internal server error processing receipt'}), 500


@fuel_bp.route('/')
@login_required
def fuel_log():
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    vehicle_id_str = request.args.get('vehicle_id')
    keyword = request.args.get('q', '').strip()
    sort_by = request.args.get('sort_by', 'date')
    order = request.args.get('order', 'desc')
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('FUEL_ENTRIES_PER_PAGE', 20)

    user_motorcycles_all = Motorcycle.query.filter_by(user_id=current_user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    user_motorcycles_for_fuel = [m for m in user_motorcycles_all if not m.is_racer]

    if not user_motorcycles_all:
        flash('給油記録を閲覧・追加するには、まず車両を登録してください。', 'info')
        return redirect(url_for('vehicle.add_vehicle'))
    if not user_motorcycles_for_fuel and user_motorcycles_all:
        flash('登録されている車両はすべてレーサー仕様のため、給油記録の対象外です。公道走行可能な車両を登録してください。', 'info')

    user_motorcycle_ids_for_fuel = [m.id for m in user_motorcycles_for_fuel]

    # --- 1. ベースクエリの構築 (N+1対策済み) ---
    base_query = db.session.query(FuelEntry).options(joinedload(FuelEntry.motorcycle)).join(Motorcycle).filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids_for_fuel))

    # --- 燃費の一括計算 (N+1対策) ---
    # フィルタリングに関わらず、対象車両の全記録を取得して燃費を計算しておく
    # これにより、FuelEntry.km_per_liter プロパティへのアクセス(個別クエリ)を回避する
    all_entries_for_calc = db.session.query(
        FuelEntry.id, FuelEntry.motorcycle_id, FuelEntry.total_distance, 
        FuelEntry.fuel_volume, FuelEntry.is_full_tank
    ).filter(
        FuelEntry.motorcycle_id.in_(user_motorcycle_ids_for_fuel)
    ).order_by(FuelEntry.motorcycle_id, FuelEntry.total_distance).all()

    kpl_map = calculate_kpl_bulk(all_entries_for_calc)

    active_filters = {k: v for k, v in request.args.items() if k not in ['page', 'sort_by', 'order']}

    # --- 2. フィルタリングの適用 ---
    try:
        if start_date_str:
            base_query = base_query.filter(FuelEntry.entry_date >= date.fromisoformat(start_date_str))
        if end_date_str:
            base_query = base_query.filter(FuelEntry.entry_date <= date.fromisoformat(end_date_str))
    except ValueError:
        flash('日付の形式が無効です。YYYY-MM-DD形式で入力してください。', 'warning')
        active_filters.pop('start_date', None)
        active_filters.pop('end_date', None)

    if vehicle_id_str:
        try:
            vehicle_id = int(vehicle_id_str)
            if vehicle_id in user_motorcycle_ids_for_fuel:
                base_query = base_query.filter(FuelEntry.motorcycle_id == vehicle_id)
            else:
                flash('選択された車両は給油記録の対象外か、有効ではありません。', 'warning')
                active_filters.pop('vehicle_id', None)
        except ValueError:
            active_filters.pop('vehicle_id', None)

    if keyword:
        search_term = f'%{keyword}%'
        base_query = base_query.filter(or_(FuelEntry.notes.ilike(search_term), FuelEntry.station_name.ilike(search_term)))

    # --- 3. 統計情報の集計 (SQLで実行可能な項目のみ) ---
    # Pythonのpropertyである km_per_liter はSQLクエリに含められないため削除
    stats_data = base_query.with_entities(
        func.count(FuelEntry.id).label('count'),
        func.sum(FuelEntry.total_cost).label('total_cost'),
        func.sum(FuelEntry.fuel_volume).label('total_volume'),
        func.min(FuelEntry.total_distance).label('min_dist'),
        func.max(FuelEntry.total_distance).label('max_dist')
    ).one()

    # 総走行距離の計算 (最大ODO - 最小ODO)
    total_distance_interval = 0
    if stats_data.max_dist is not None and stats_data.min_dist is not None:
        total_distance_interval = stats_data.max_dist - stats_data.min_dist

    # --- 4. チャート用データ & 平均燃費の作成 (Pythonで処理) ---
    # すべての対象データを取得し、Python側で燃費プロパティにアクセスしてリスト化
    all_filtered_entries = base_query.order_by(asc(FuelEntry.entry_date)).all()
    
    chart_labels = []
    chart_values = []
    valid_efficiency_sum = 0
    valid_efficiency_count = 0

    for e in all_filtered_entries:
        # km_per_literはモデルプロパティではなく、一括計算結果を使用
        kpl = kpl_map.get(e.id)
        if kpl is not None:
            chart_labels.append(e.entry_date.strftime('%Y/%m/%d'))
            chart_values.append(round(kpl, 2))
            
            # 平均計算用に集計
            if not e.exclude_from_average:
                valid_efficiency_sum += kpl
                valid_efficiency_count += 1
    
    chart_data = {
        'labels': chart_labels,
        'data': chart_values
    }

    # 平均燃費の計算
    calculated_efficiency = 0
    if valid_efficiency_count > 0:
        calculated_efficiency = valid_efficiency_sum / valid_efficiency_count

    summary_stats = {
        'total_entries': stats_data.count,
        'total_cost': stats_data.total_cost or 0,
        'total_distance': total_distance_interval,
        'average_efficiency': calculated_efficiency
    }

    # --- 5. リスト表示用のソートとページネーション ---
    query = base_query # base_queryをそのまま利用

    sort_column_map = {
        'date': FuelEntry.entry_date, 'vehicle': Motorcycle.name,
        'odo_reading': FuelEntry.odometer_reading, 'actual_distance': FuelEntry.total_distance,
        'volume': FuelEntry.fuel_volume, 'price': FuelEntry.price_per_liter,
        'cost': FuelEntry.total_cost, 'station': FuelEntry.station_name,
    }
    current_sort_by = sort_by if sort_by in sort_column_map else 'date'
    sort_column = sort_column_map.get(current_sort_by, FuelEntry.entry_date)
    current_order = 'desc' if order == 'desc' else 'asc'
    
    # 修正: 'asc' 文字列ではなく、SQLAlchemyの関数 asc を使用
    sort_modifier = desc if current_order == 'desc' else asc

    # 常に日付を第2ソートキーにして並び順を安定させる
    if sort_column == FuelEntry.entry_date:
        query = query.order_by(sort_modifier(FuelEntry.entry_date), desc(FuelEntry.total_distance), FuelEntry.id.desc())
    elif sort_column == FuelEntry.odometer_reading:
        query = query.order_by(sort_modifier(FuelEntry.odometer_reading), desc(FuelEntry.entry_date), FuelEntry.id.desc())
    elif sort_column == FuelEntry.total_distance:
        query = query.order_by(sort_modifier(FuelEntry.total_distance), desc(FuelEntry.entry_date), FuelEntry.id.desc())
    else:
        query = query.order_by(sort_modifier(sort_column), desc(FuelEntry.entry_date), FuelEntry.id.desc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    fuel_entries = pagination.items

    is_filter_active = bool(active_filters)
    upload_form = FuelCsvUploadForm()

    return render_template('fuel_log.html',
                           entries=fuel_entries, pagination=pagination,
                           motorcycles=user_motorcycles_for_fuel,
                           request_args=active_filters,
                           current_sort_by=current_sort_by, current_order=current_order,
                           is_filter_active=is_filter_active,
                           upload_form=upload_form,
                           summary_stats=summary_stats,
                           chart_data=chart_data,
                           kpl_map=kpl_map)


@fuel_bp.route('/add', methods=['GET', 'POST'])
@limiter.limit("60 per hour")
@login_required
def add_fuel():
    user_motorcycles_for_fuel = Motorcycle.query.filter_by(user_id=current_user.id, is_racer=False).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    if not user_motorcycles_for_fuel:
        all_motorcycles_count = Motorcycle.query.filter_by(user_id=current_user.id).count()
        if all_motorcycles_count > 0:
            flash('登録されている車両はすべてレーサー仕様のため、給油記録を追加できません。公道走行可能な車両を登録してください。', 'warning')
            return redirect(url_for('vehicle.vehicle_list'))
        else:
            flash('給油記録を追加するには、まず車両を登録してください。', 'warning')
            return redirect(url_for('vehicle.add_vehicle'))

    form = FuelForm()
    form.motorcycle_id.choices = [(m.id, f"{m.name} ({m.maker or 'メーカー不明'})") for m in user_motorcycles_for_fuel]

    if request.method == 'GET':
        default_vehicle = next((m for m in user_motorcycles_for_fuel if m.is_default), user_motorcycles_for_fuel[0] if user_motorcycles_for_fuel else None)
        if default_vehicle: form.motorcycle_id.data = default_vehicle.id
        preselected_motorcycle_id = request.args.get('motorcycle_id', type=int)
        if preselected_motorcycle_id and any(m.id == preselected_motorcycle_id for m in user_motorcycles_for_fuel):
            form.motorcycle_id.data = preselected_motorcycle_id
        form.entry_date.data = date.today()
        form.is_full_tank.data = True

    if form.validate_on_submit():
        motorcycle = Motorcycle.query.filter_by(id=form.motorcycle_id.data, user_id=current_user.id, is_racer=False).first()
        if not motorcycle:
            flash('選択された車両が見つからないか、給油記録の対象外です。再度お試しください。', 'danger')
            return render_template('fuel_form.html', form_action='add', form=form, gas_station_brands=GAS_STATION_BRANDS, start_fuel_tutorial=False)

        previous_fuel = get_previous_fuel_entry(motorcycle.id, form.entry_date.data)

        if form.input_mode.data:
            if form.trip_distance.data is None:
                form.trip_distance.errors.append('トリップメーターで入力する場合、この項目は必須です。')
            elif previous_fuel:
                form.odometer_reading.data = previous_fuel.odometer_reading + form.trip_distance.data
            else:
                form.trip_distance.errors.append('この車両で初めての給油です。トリップ入力は使用できません。ODOメーター値を直接入力してください。')
        else:
            if form.odometer_reading.data is None:
                form.odometer_reading.errors.append('ODOメーターで入力する場合、この項目は必須です。')

        if form.errors:
            flash('入力内容にエラーがあります。ご確認ください。', 'danger')
            return render_template('fuel_form.html', form_action='add', form=form, gas_station_brands=GAS_STATION_BRANDS, start_fuel_tutorial=False)

        offset_at_entry_date = motorcycle.calculate_cumulative_offset_from_logs(target_date=form.entry_date.data)
        total_distance = form.odometer_reading.data + offset_at_entry_date

        if previous_fuel and total_distance < previous_fuel.total_distance:
            flash(f'注意: 今回の総走行距離 ({total_distance:,}km) が、前回記録 ({previous_fuel.entry_date.strftime("%Y-%m-%d")} の {previous_fuel.total_distance:,}km) より小さくなっています。入力内容を確認してください。', 'warning')

        total_cost_val = form.total_cost.data
        if total_cost_val is None and form.price_per_liter.data is not None and form.fuel_volume.data is not None:
            try: total_cost_val = round(float(form.price_per_liter.data) * float(form.fuel_volume.data))
            except TypeError: total_cost_val = None
        elif total_cost_val is not None: total_cost_val = int(round(float(total_cost_val)))

        new_entry = FuelEntry(
            motorcycle_id=motorcycle.id, entry_date=form.entry_date.data, odometer_reading=form.odometer_reading.data,
            total_distance=total_distance, fuel_volume=float(form.fuel_volume.data),
            price_per_liter=float(form.price_per_liter.data) if form.price_per_liter.data is not None else None,
            total_cost=total_cost_val, station_name=form.station_name.data.strip() if form.station_name.data else None,
            fuel_type=form.fuel_type.data if form.fuel_type.data else None,
            notes=form.notes.data.strip() if form.notes.data else None, is_full_tank=form.is_full_tank.data,
            exclude_from_average=form.exclude_from_average.data
        )

        try:
            db.session.add(new_entry)
            db.session.commit()
            flash('給油記録を追加しました。', 'success')

            event_data_for_ach = {'new_fuel_log_id': new_entry.id, 'motorcycle_id': motorcycle.id}
            check_achievements_for_event(current_user, EVENT_ADD_FUEL_LOG, event_data=event_data_for_ach)

            return redirect(url_for('fuel.fuel_log'))
        except Exception as e:
            db.session.rollback()
            flash(f'記録のデータベース保存中にエラーが発生しました。詳細は管理者にお問い合わせください。', 'error')
            current_app.logger.error(f"Error saving new fuel entry: {e}", exc_info=True)

    elif request.method == 'POST':
        flash('入力内容にエラーがあります。ご確認ください。', 'danger')

    previous_entry_info = None
    if form.motorcycle_id.data and form.entry_date.data:
        previous_fuel = get_previous_fuel_entry(form.motorcycle_id.data, form.entry_date.data)
        if previous_fuel:
            previous_entry_info = {
                'date': previous_fuel.entry_date.strftime('%Y-%m-%d'),
                'odo': f"{previous_fuel.odometer_reading:,}km"
            }
            
    start_fuel_tutorial = False
    if user_motorcycles_for_fuel:
        user_motorcycle_ids_for_fuel = [m.id for m in user_motorcycles_for_fuel]
        has_existing_fuel_logs = FuelEntry.query.filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids_for_fuel)).first() is not None
        if not has_existing_fuel_logs and not current_user.completed_tutorials.get('fuel_form', False):
            start_fuel_tutorial = True
    
    return render_template('fuel_form.html', 
                           form_action='add', 
                           form=form, 
                           gas_station_brands=GAS_STATION_BRANDS, 
                           previous_entry_info=previous_entry_info,
                           start_fuel_tutorial=start_fuel_tutorial)


@fuel_bp.route('/<int:entry_id>/edit', methods=['GET', 'POST'])
@limiter.limit("60 per hour")
@login_required
def edit_fuel(entry_id):
    entry = FuelEntry.query.join(Motorcycle).filter(
        FuelEntry.id == entry_id,
        Motorcycle.user_id == current_user.id,
        Motorcycle.is_racer == False
    ).first_or_404()
    
    form = FuelForm(obj=entry)

    user_motorcycles_for_fuel = Motorcycle.query.filter_by(user_id=current_user.id, is_racer=False).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    form.motorcycle_id.choices = [(m.id, f"{m.name} ({m.maker or 'メーカー不明'})") for m in user_motorcycles_for_fuel]
    
    if request.method == 'GET':
        form.motorcycle_id.data = entry.motorcycle_id
        form.input_mode.data = False 
    
    if form.validate_on_submit():
        new_motorcycle = Motorcycle.query.filter_by(id=form.motorcycle_id.data, user_id=current_user.id, is_racer=False).first()
        if not new_motorcycle:
            flash('選択された車両が見つからないか、給油記録の対象外です。再度お試しください。', 'danger')
            return render_template('fuel_form.html', form_action='edit', form=form, entry_id=entry.id, gas_station_brands=GAS_STATION_BRANDS, start_fuel_tutorial=False)

        vehicle_changed = entry.motorcycle_id != new_motorcycle.id
        if vehicle_changed:
            flash('注意: 記録の対象車両が変更されました。ODOメーター値や実走行距離が、新しい車両の履歴に対して妥当かご確認ください。', 'warning')
        
        previous_fuel = get_previous_fuel_entry(new_motorcycle.id, form.entry_date.data, entry.id)

        if form.input_mode.data:
            if form.trip_distance.data is None:
                form.trip_distance.errors.append('トリップメーターで入力する場合、この項目は必須です。')
            elif previous_fuel:
                form.odometer_reading.data = previous_fuel.odometer_reading + form.trip_distance.data
            else:
                form.trip_distance.errors.append('この記録より前の給油記録がありません。トリップ入力は使用できません。ODOメーター値を直接入力してください。')
        else:
            if form.odometer_reading.data is None:
                form.odometer_reading.errors.append('ODOメーターで入力する場合、この項目は必須です。')

        if form.errors:
            flash('入力内容にエラーがあります。ご確認ください。', 'danger')
            return render_template('fuel_form.html', form_action='edit', form=form, entry_id=entry.id, gas_station_brands=GAS_STATION_BRANDS, start_fuel_tutorial=False)

        offset_at_entry_date = new_motorcycle.calculate_cumulative_offset_from_logs(target_date=form.entry_date.data)
        total_distance = form.odometer_reading.data + offset_at_entry_date

        if previous_fuel and total_distance < previous_fuel.total_distance:
                      flash(f'注意: 今回の総走行距離 ({total_distance:,}km) が、前回記録 ({previous_fuel.entry_date.strftime("%Y-%m-%d")} の {previous_fuel.total_distance:,}km) より小さくなっています。入力内容を確認してください。', 'warning')

        total_cost_val = form.total_cost.data
        if total_cost_val is None and form.price_per_liter.data is not None and form.fuel_volume.data is not None:
            try: total_cost_val = round(float(form.price_per_liter.data) * float(form.fuel_volume.data))
            except TypeError: total_cost_val = None
        elif total_cost_val is not None: total_cost_val = int(round(float(total_cost_val)))

        entry.motorcycle_id = new_motorcycle.id
        entry.entry_date = form.entry_date.data
        entry.odometer_reading = form.odometer_reading.data
        entry.total_distance = total_distance
        entry.fuel_volume = float(form.fuel_volume.data)
        entry.price_per_liter = float(form.price_per_liter.data) if form.price_per_liter.data is not None else None
        entry.total_cost = total_cost_val
        entry.station_name = form.station_name.data.strip() if form.station_name.data else None
        entry.fuel_type = form.fuel_type.data if form.fuel_type.data else None
        entry.notes = form.notes.data.strip() if form.notes.data else None
        entry.is_full_tank = form.is_full_tank.data
        entry.exclude_from_average = form.exclude_from_average.data

        try:
            db.session.commit()
            flash('給油記録を更新しました。', 'success')
            return redirect(url_for('fuel.fuel_log'))
        except Exception as e:
            db.session.rollback()
            flash(f'記録の更新中にエラーが発生しました。詳細は管理者にお問い合わせください。', 'error')
            current_app.logger.error(f"Error updating fuel entry ID {entry_id}: {e}", exc_info=True)

    elif request.method == 'POST':
        flash('入力内容にエラーがあります。ご確認ください。', 'danger')

    previous_entry_info = None
    selected_motorcycle_id_for_prev = form.motorcycle_id.data if not form.motorcycle_id.errors else entry.motorcycle_id
    entry_date_for_prev = form.entry_date.data if not form.entry_date.errors else entry.entry_date
    if selected_motorcycle_id_for_prev and entry_date_for_prev:
        previous_fuel = get_previous_fuel_entry(selected_motorcycle_id_for_prev, entry_date_for_prev, entry.id)
        if previous_fuel:
            previous_entry_info = {
                'date': previous_fuel.entry_date.strftime('%Y-%m-%d'),
                'odo': f"{previous_fuel.odometer_reading:,}km"
            }
    start_fuel_tutorial = False
    return render_template('fuel_form.html', 
                           form_action='edit', 
                           form=form, 
                           entry_id=entry.id, 
                           gas_station_brands=GAS_STATION_BRANDS, 
                           previous_entry_info=previous_entry_info,
                           start_fuel_tutorial=start_fuel_tutorial)


@fuel_bp.route('/<int:entry_id>/delete', methods=['POST'])
@limiter.limit("60 per hour")
@login_required
def delete_fuel(entry_id):
    entry = FuelEntry.query.join(Motorcycle).filter(
        FuelEntry.id == entry_id,
        Motorcycle.user_id == current_user.id,
        Motorcycle.is_racer == False
    ).first_or_404()
    try:
        db.session.delete(entry)
        db.session.commit()
        flash('給油記録を削除しました。', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'記録の削除中にエラーが発生しました。詳細は管理者にお問い合わせください。', 'error')
        current_app.logger.error(f"Error deleting fuel entry ID {entry_id}: {e}", exc_info=True)
    return redirect(url_for('fuel.fuel_log'))

@fuel_bp.route('/template/fuel_import_template.csv')
@login_required
def download_fuel_import_template():
    """給油記録インポート用のCSVテンプレートをダウンロードさせる"""
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow(['# もとぷっぷー 給油記録インポート用CSVテンプレート'])
    writer.writerow(['#'])
    writer.writerow(['# 以下のヘッダーに従ってデータを入力してください。(この行を含む「#」で始まる行はインポート時に無視されます)'])
    writer.writerow(['#'])
    writer.writerow(['# --- 項目説明 ---'])
    writer.writerow(['# entry_date (必須): 給油日をYYYY-MM-DD形式で入力します。例: 2025-08-06'])
    writer.writerow(['# odometer_reading (必須): 給油時のODOメーターの値を整数で入力します。例: 12500'])
    writer.writerow(['# fuel_volume (必須): 給油量をリットル単位で入力します。例: 5.50'])
    writer.writerow(['# price_per_liter (任意): 1リットルあたりの単価を整数で入力します。例: 175'])
    writer.writerow(['# total_cost (任意): 合計金額を整数で入力します。単価と給油量を入力した場合、この値は無視され自動計算されます。'])
    writer.writerow(['# station_name (任意): ガソリンスタンド名を入力します。例: もとぷーSS'])
    writer.writerow(['# is_full_tank (任意): 満タン給油の場合に「true」と入力します。燃費計算に利用されます。空欄の場合はtrueとして扱われます。'])
    writer.writerow(['# exclude_from_average (任意): 平均燃費の計算から除外する場合に「true」と入力します。'])
    writer.writerow(['# notes (任意): メモを入力します。'])
    writer.writerow(['# fuel_type (任意): 油種を入力します。例: ハイオク, レギュラー'])
    writer.writerow(['#'])
    writer.writerow(['# --- ヘッダー (この行は編集しないでください) ---'])
    header = [
        'entry_date', 'odometer_reading', 'fuel_volume', 'price_per_liter',
        'total_cost', 'station_name', 'is_full_tank', 'exclude_from_average',
        'notes', 'fuel_type'
    ]
    writer.writerow(header)
    
    sample_data = [
        '2025-08-01', '12500', '5.50', '175', 
        '963', 'もとぷーSS', 'true', 'false',
        'テスト走行後の給油', 'ハイオク'
    ]
    writer.writerow(sample_data)
    
    output.seek(0)
    
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment;filename=motopuppu_fuel_import_template.csv",
            "Content-Type": "text/csv; charset=utf-8-sig"
        }
    )

@fuel_bp.route('/motorcycle/<int:vehicle_id>/import_csv', methods=['POST'])
@limiter.limit("10 per hour")
@login_required
def import_fuel_records_csv(vehicle_id):
    """CSVファイルをアップロードして給油記録を一括登録する"""
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=current_user.id, is_racer=False).first_or_404('対象の車両が見つからないか、レーサー車両のためインポートできません。')
    
    form = FuelCsvUploadForm()
    
    if form.validate_on_submit():
        csv_file = form.csv_file.data
        try:
            csv_file.stream.seek(0)
            success_count, errors, duplicates = _process_fuel_csv_import(csv_file.stream, motorcycle)

            if duplicates:
                flash_message = "<strong>インポートが中断されました。以下のデータが既にデータベースに存在します。</strong><br>CSVファイルから該当の行を削除して、再度アップロードしてください。<ul class='mb-0'>"
                for dup in duplicates:
                    flash_message += f"<li>{dup}</li>"
                flash_message += "</ul>"
                flash(flash_message, 'warning')
            
            if errors:
                for error in errors:
                    flash(f'CSVインポートエラー: {error}', 'danger')
            
            if success_count > 0:
                flash(f'{success_count}件の給油記録を正常にインポートしました。', 'success')
            elif not errors and not duplicates:
                flash('インポートするデータが見つかりませんでした。', 'info')
                
        except Exception as e:
            current_app.logger.error(f"CSV import failed for vehicle {vehicle_id}: {e}", exc_info=True)
            flash('CSVファイルの処理中に予期せぬエラーが発生しました。ファイルの形式や文字コード（UTF-8）を確認してください。', 'danger')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{getattr(form, field).label.text}: {error}', 'danger')

    return redirect(url_for('fuel.fuel_log', vehicle_id=vehicle_id))


@fuel_bp.route('/motorcycle/<int:motorcycle_id>/export_csv')
@login_required
def export_fuel_records_csv(motorcycle_id):
    motorcycle = Motorcycle.query.filter_by(id=motorcycle_id, user_id=current_user.id, is_racer=False).first_or_404()
    fuel_records = FuelEntry.query.filter_by(motorcycle_id=motorcycle.id).order_by(FuelEntry.entry_date.asc(), FuelEntry.total_distance.asc()).all()
    if not fuel_records:
        flash(f'{motorcycle.name}にはエクスポート対象の燃費記録がありません。', 'info')
        return redirect(url_for('fuel.fuel_log', vehicle_id=motorcycle.id))
    output = io.StringIO()
    writer = csv.writer(output)
    header = ['id', 'motorcycle_id', 'motorcycle_name', 'entry_date', 'odometer_reading', 'total_distance', 'fuel_volume', 'price_per_liter', 'total_cost', 'station_name', 'is_full_tank', 'km_per_liter', 'exclude_from_average', 'notes', 'fuel_type']
    writer.writerow(header)
    for record in fuel_records:
        km_per_liter_val = record.km_per_liter
        row = [record.id, record.motorcycle_id, motorcycle.name, record.entry_date.strftime('%Y-%m-%d') if record.entry_date else '', record.odometer_reading, record.total_distance, f"{record.fuel_volume:.2f}" if record.fuel_volume is not None else '', f"{record.price_per_liter:.1f}" if record.price_per_liter is not None else '', f"{record.total_cost:.0f}" if record.total_cost is not None else '', record.station_name if record.station_name else '', str(record.is_full_tank), f"{km_per_liter_val:.2f}" if km_per_liter_val is not None else '', str(record.exclude_from_average), record.notes if record.notes else '', record.fuel_type if record.fuel_type else '']
        writer.writerow(row)
    output.seek(0)
    safe_vehicle_name = "".join(c for c in motorcycle.name if c.isalnum() or c in ['_', '-']).strip()
    if not safe_vehicle_name: safe_vehicle_name = "vehicle"
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    filename = f"motopuppu_fuel_records_{safe_vehicle_name}_{motorcycle.id}_{timestamp}.csv"
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment;filename=\"{filename}\"", "Content-Type": "text/csv; charset=utf-8-sig"})

@fuel_bp.route('/export_all_csv')
@login_required
def export_all_fuel_records_csv():
    user_motorcycles_for_fuel = Motorcycle.query.filter_by(user_id=current_user.id, is_racer=False).all()
    if not user_motorcycles_for_fuel:
        flash('エクスポート対象の車両（公道車）が登録されていません。', 'info')
        return redirect(url_for('fuel.fuel_log'))

    user_motorcycle_ids_for_fuel = [m.id for m in user_motorcycles_for_fuel]

    all_fuel_records = FuelEntry.query.filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids_for_fuel))\
                                         .options(db.joinedload(FuelEntry.motorcycle))\
                                         .order_by(FuelEntry.motorcycle_id, FuelEntry.entry_date.asc(), FuelEntry.total_distance.asc()).all()

    if not all_fuel_records:
        flash('エクスポート対象の燃費記録がありません。', 'info')
        return redirect(url_for('fuel.fuel_log'))

    output = io.StringIO()
    writer = csv.writer(output)
    header = [
        'id', 'motorcycle_id', 'motorcycle_name', 'entry_date', 'odometer_reading',
        'total_distance', 'fuel_volume', 'price_per_liter', 'total_cost',
        'station_name', 'is_full_tank', 'km_per_liter', 'exclude_from_average', 'notes', 'fuel_type'
    ]
    writer.writerow(header)
    for record in all_fuel_records:
        km_per_liter_val = record.km_per_liter
        row = [
            record.id, record.motorcycle_id, record.motorcycle.name,
            record.entry_date.strftime('%Y-%m-%d') if record.entry_date else '',
            record.odometer_reading, record.total_distance,
            f"{record.fuel_volume:.2f}" if record.fuel_volume is not None else '',
            f"{record.price_per_liter:.1f}" if record.price_per_liter is not None else '',
            f"{record.total_cost:.0f}" if record.total_cost is not None else '',
            record.station_name if record.station_name else '', str(record.is_full_tank),
            f"{km_per_liter_val:.2f}" if km_per_liter_val is not None else '',
            str(record.exclude_from_average),
            record.notes if record.notes else '', record.fuel_type if record.fuel_type else ''
        ]
        writer.writerow(row)
    output.seek(0)
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    filename = f"motopuppu_fuel_records_all_vehicles_{timestamp}.csv"
    return Response(
        output.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename=\"{filename}\"", "Content-Type": "text/csv; charset=utf-8-sig"}
    )

@fuel_bp.route('/get-previous-entry', methods=['GET'])
@login_required
def get_previous_entry_api():
    motorcycle_id = request.args.get('motorcycle_id', type=int)
    entry_date_str = request.args.get('entry_date')
    entry_id = request.args.get('entry_id', type=int)

    if not motorcycle_id or not entry_date_str:
        return jsonify({'error': 'Missing required parameters'}), 400

    try:
        entry_date = date.fromisoformat(entry_date_str)
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400

    previous_fuel = get_previous_fuel_entry(motorcycle_id, entry_date, current_entry_id=entry_id)

    if previous_fuel:
        return jsonify({
            'found': True,
            'date': previous_fuel.entry_date.strftime('%Y-%m-%d'),
            'odo': f"{previous_fuel.odometer_reading:,}km"
        })
    else:
        return jsonify({'found': False})