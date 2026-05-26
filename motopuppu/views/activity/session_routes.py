# motopuppu/views/activity/session_routes.py
import json
import io
import math
from collections import defaultdict
from decimal import Decimal
import uuid

from flask import (
    flash, redirect, render_template, request, url_for, abort, current_app, jsonify,
    Response, stream_with_context
)
from sqlalchemy.orm import joinedload
from sqlalchemy import func

# 分割したBlueprintとユーティリティをインポート
from . import activity_bp
from ...utils.lap_time_utils import (
    calculate_lap_stats, parse_time_to_seconds, _calculate_and_set_best_lap,
    is_valid_lap_time_format, filter_outlier_laps, format_seconds_to_time
)
from ...constants import SETTING_KEY_MAP

from ...utils.view_helpers import get_motorcycle_or_404
from flask_login import login_required, current_user
from ...models import db, ActivityLog, SessionLog
from ...forms import SessionLogForm, LapTimeImportForm
from ...parsers import get_parser, PARSERS
from ... import limiter

# --- RDPアルゴリズム (Douglas-Peucker) のヘルパー関数 ---
def _calculate_perpendicular_distance(point, start, end):
    """点と直線の距離を計算する (平面近似)"""
    if start == end:
        return math.sqrt((point['lat'] - start['lat'])**2 + (point['lng'] - start['lng'])**2)
    
    # 直線 ax + by + c = 0 と点 (x0, y0) の距離
    x0, y0 = point['lng'], point['lat']
    x1, y1 = start['lng'], start['lat']
    x2, y2 = end['lng'], end['lat']
    
    nom = abs((y2 - y1) * x0 - (x2 - x1) * y0 + x2 * y1 - y2 * x1)
    denom = math.sqrt((y2 - y1)**2 + (x2 - x1)**2)
    
    if denom == 0:
        return 0
    return nom / denom

def _ramer_douglas_peucker(points, epsilon):
    """
    RDPアルゴリズムによる点群の間引き (反復実装)
    :param points: [{'lat': float, 'lng': float, ...}, ...]
    :param epsilon: 間引きの閾値 (度単位)
    :return: 間引き後のリスト

    Why iterative: 再帰実装は points[:i+1] / points[i:] のスライスを各レベルで生成し、
    深い再帰で一時オブジェクトが大量に積み上がる (Renderの2GB OOMの一因)。
    """
    n = len(points)
    if n < 3:
        return list(points)

    keep = [False] * n
    keep[0] = True
    keep[n - 1] = True

    stack = [(0, n - 1)]
    while stack:
        start, end = stack.pop()
        if end <= start + 1:
            continue

        start_p = points[start]
        end_p = points[end]
        dmax = 0
        index = start
        for i in range(start + 1, end):
            d = _calculate_perpendicular_distance(points[i], start_p, end_p)
            if d > dmax:
                index = i
                dmax = d

        if dmax > epsilon:
            keep[index] = True
            stack.append((start, index))
            stack.append((index, end))

    return [points[i] for i in range(n) if keep[i]]

# --- データ軽量化のための最適化関数 ---
def _optimize_track_points(points):
    """
    GPSデータの数値を丸めてサイズを削減する
    緯度経度: 小数点6桁(約11cm精度)
    速度/時間: 小数点2桁
    RPM: 整数化
    """
    optimized = []
    for p in points:
        new_p = {}
        # 必須フィールド (存在しない場合はスキップまたはエラーだが、Parserで保証済み)
        if 'lat' in p: new_p['lat'] = round(float(p['lat']), 6)
        if 'lng' in p: new_p['lng'] = round(float(p['lng']), 6)
        
        # オプションフィールド (存在する場合のみ丸めて追加)
        if 'speed' in p: new_p['speed'] = round(float(p['speed']), 2)
        if 'runtime' in p: new_p['runtime'] = round(float(p['runtime']), 3)
        if 'rpm' in p: new_p['rpm'] = int(float(p['rpm']))
        if 'throttle' in p: new_p['throttle'] = round(float(p['throttle']), 1)
        
        optimized.append(new_p)
    return optimized
# -----------------------------------------------------------


def _prepare_comparison_data(sessions):
    """選択されたセッション群から比較用のデータを生成する"""
    if not sessions:
        return {}

    # 1. ラップタイム分析
    lap_analysis = {'stats': {}, 'chart_data': {'labels': [], 'datasets': []}}
    max_laps = 0
    chart_colors = ['rgb(75, 192, 192)', 'rgb(255, 99, 132)', 'rgb(54, 162, 235)', 'rgb(255, 205, 86)']
    
    session_stats_raw = []
    for i, session in enumerate(sessions):
        best_str, avg_str, _ = calculate_lap_stats(session.lap_times)
        best_sec = parse_time_to_seconds(best_str)
        avg_sec = parse_time_to_seconds(avg_str)
        session_stats_raw.append({
            'id': session.id,
            'best_str': best_str,
            'avg_str': avg_str,
            'best_sec': best_sec,
            'avg_sec': avg_sec
        })
        
        lap_seconds = [s for s in (parse_time_to_seconds(t) for t in session.lap_times or []) if s]
        if lap_seconds:
            max_laps = max(max_laps, len(lap_seconds))
            lap_analysis['chart_data']['datasets'].append({
                'label': session.session_name,
                'data': [float(s) for s in lap_seconds if s is not None],
                'borderColor': chart_colors[i % len(chart_colors)],
                'tension': 0.1
            })
    lap_analysis['chart_data']['labels'] = [f"Lap {i+1}" for i in range(max_laps)]

    valid_best_laps = [s['best_sec'] for s in session_stats_raw if s['best_sec'] is not None]
    min_best_sec = min(valid_best_laps) if valid_best_laps else None
    
    valid_avg_laps = [s['avg_sec'] for s in session_stats_raw if s['avg_sec'] is not None]
    min_avg_sec = min(valid_avg_laps) if valid_avg_laps else None

    for stats in session_stats_raw:
        session_id = stats['id']
        
        best_diff_str = ''
        if min_best_sec is not None and stats['best_sec'] is not None:
            diff = stats['best_sec'] - min_best_sec
            if diff > 0:
                best_diff_str = f"+{diff:.3f}"

        avg_diff_str = ''
        if min_avg_sec is not None and stats['avg_sec'] is not None:
            diff = stats['avg_sec'] - min_avg_sec
            if diff > 0:
                avg_diff_str = f"+{diff:.3f}"
        
        lap_analysis['stats'][session_id] = {
            'best': stats['best_str'],
            'avg': stats['avg_str'],
            'best_diff': best_diff_str,
            'avg_diff': avg_diff_str,
            'best_sec': stats['best_sec'],
            'avg_sec': stats['avg_sec']
        }

    # 2. セッティングシート比較
    settings_comparison = []
    all_keys = defaultdict(set)
    session_details_map = {}

    for session in sessions:
        details_data = {}
        if session.setting_sheet and session.setting_sheet.details is not None:
            raw_details = session.setting_sheet.details
            if isinstance(raw_details, dict):
                details_data = raw_details
            elif isinstance(raw_details, str):
                try:
                    details_data = json.loads(raw_details) if raw_details else {}
                except json.JSONDecodeError:
                    details_data = {}
        
        session_details_map[session.id] = details_data
        for category, items in details_data.items():
            if isinstance(items, dict):
                for key in items.keys():
                    all_keys[category].add(key)
    
    sorted_categories = sorted(all_keys.keys())
    for category_key in sorted_categories:
        category_info = SETTING_KEY_MAP.get(category_key, {'title': category_key.capitalize(), 'keys': {}})
        sorted_item_keys = sorted(list(all_keys[category_key]))
        
        for item_key in sorted_item_keys:
            item_label = category_info['keys'].get(item_key, item_key)
            row_data = {'category': category_info['title'], 'item': item_label, 'values': {}}
            values_set = set()
            for session in sessions:
                value = "N/A"
                details_data = session_details_map.get(session.id, {})
                retrieved_value = details_data.get(category_key, {}).get(item_key)
                if retrieved_value not in [None, '']:
                    value = retrieved_value
                row_data['values'][session.id] = value
                values_set.add(str(value))

            row_data['is_diff'] = len(values_set) > 1
            settings_comparison.append(row_data)

    return {
        'lap_analysis': lap_analysis,
        'settings_comparison': settings_comparison,
    }


@activity_bp.route('/compare', methods=['GET'])
@login_required
def compare_sessions():
    vehicle_id = request.args.get('vehicle_id', type=int)
    session_ids = request.args.getlist('session_ids', type=int)

    if not vehicle_id:
        abort(400, "Vehicle ID is required.")

    motorcycle = get_motorcycle_or_404(vehicle_id)
    
    if len(session_ids) < 2:
        flash('比較するには、セッションを2つ以上選択してください。', 'warning')
        if session_ids:
            first_session = SessionLog.query.get(session_ids[0])
            if first_session and first_session.activity.motorcycle_id == vehicle_id:
                 return redirect(url_for('activity.detail_activity', activity_id=first_session.activity_log_id))
        return redirect(url_for('activity.list_activities', vehicle_id=vehicle_id))
    
    sessions = SessionLog.query.options(
            joinedload(SessionLog.setting_sheet),
            joinedload(SessionLog.activity)
        ).filter(
            SessionLog.id.in_(session_ids),
            SessionLog.activity.has(motorcycle_id=vehicle_id)
        ).order_by(SessionLog.id.asc()).all()

    if len(sessions) < 2:
        flash('選択されたセッションが見つからないか、比較するにはセッションが少なすぎます。', 'danger')
        return redirect(url_for('activity.list_activities', vehicle_id=vehicle_id))
        
    comparison_data = _prepare_comparison_data(sessions)

    return render_template('activity/compare_sessions.html',
                           motorcycle=motorcycle,
                           sessions=sessions,
                           comparison_data=comparison_data,
                           setting_key_map=SETTING_KEY_MAP)

@activity_bp.route('/<int:vehicle_id>/best_settings')
@login_required
def best_settings_finder(vehicle_id):
    motorcycle = get_motorcycle_or_404(vehicle_id)

    ranked_sessions_subq = db.session.query(
        SessionLog.id,
        func.row_number().over(
            partition_by=ActivityLog.circuit_name,
            order_by=SessionLog.best_lap_seconds.asc()
        ).label('rn')
    ).join(ActivityLog).filter(
        ActivityLog.motorcycle_id == vehicle_id,
        ActivityLog.location_type == 'circuit',
        ActivityLog.circuit_name.isnot(None),
        SessionLog.best_lap_seconds.isnot(None)
    ).subquery()
    
    best_session_ids_query = db.session.query(ranked_sessions_subq.c.id)\
                                     .filter(ranked_sessions_subq.c.rn == 1)

    best_sessions = SessionLog.query.options(
        joinedload(SessionLog.activity),
        joinedload(SessionLog.setting_sheet)
    ).join(
        ActivityLog, SessionLog.activity_log_id == ActivityLog.id
    ).filter(
        SessionLog.id.in_(best_session_ids_query)
    ).order_by(
        ActivityLog.circuit_name.asc()
    ).all()
    
    return render_template('activity/best_settings.html',
                           motorcycle=motorcycle,
                           best_sessions=best_sessions,
                           setting_key_map=SETTING_KEY_MAP,
                           format_seconds_to_time=format_seconds_to_time)

@activity_bp.route('/session/<int:session_id>/gps_data', methods=['GET'])
@login_required
def get_gps_data(session_id):
    session = SessionLog.query.options(
        joinedload(SessionLog.activity).joinedload(ActivityLog.user),
        joinedload(SessionLog.activity).joinedload(ActivityLog.motorcycle),
        joinedload(SessionLog.setting_sheet)
    ).filter_by(id=session_id).first_or_404()

    is_owner = (session.activity.user_id == current_user.id)
    is_team_member = False

    if not is_owner:
        owner_teams = set(team.id for team in session.activity.user.teams)
        current_user_teams = set(team.id for team in current_user.teams)
        if owner_teams.intersection(current_user_teams):
            is_team_member = True
    
    if not is_owner and not is_team_member:
        abort(403)

    if not session.gps_tracks or not session.gps_tracks.get('laps'):
        return jsonify({'error': 'No GPS data available'}), 404

    motorcycle = session.activity.motorcycle
    setting_sheet = session.setting_sheet
    
    vehicle_specs = {
        'primary_ratio': float(motorcycle.primary_ratio) if motorcycle.primary_ratio else None,
        'gear_ratios': {k: float(v) for k, v in motorcycle.gear_ratios.items()} if motorcycle.gear_ratios else None,
        'front_sprocket': None,
        'rear_sprocket': None,
        'rear_tyre_size': None,
    }

    if setting_sheet and setting_sheet.details:
        sprocket_settings = setting_sheet.details.get('sprocket', {})
        tyre_settings = setting_sheet.details.get('tire_rear', {}) 
        
        try:
            front_sprocket = sprocket_settings.get('front_teeth')
            if front_sprocket:
                vehicle_specs['front_sprocket'] = int(front_sprocket)
        except (ValueError, TypeError):
            pass

        try:
            rear_sprocket = sprocket_settings.get('rear_teeth')
            if rear_sprocket:
                vehicle_specs['rear_sprocket'] = int(rear_sprocket)
        except (ValueError, TypeError):
            pass
        
        rear_tyre_size = tyre_settings.get('tire_size')
        if rear_tyre_size:
            vehicle_specs['rear_tyre_size'] = rear_tyre_size

    response_data = {
        'laps': [],
        'lap_times': session.lap_times or [],
        'vehicle_specs': vehicle_specs
    }
    
    # マップ表示用に、すでに保存されているデータをさらに軽量化して返す
    raw_laps = session.gps_tracks.get('laps', [])
    
    for lap in raw_laps:
        raw_track = lap.get('track', [])
        
        # ▼▼▼ 修正: 再生・チャート用のデータも、点数が多すぎる場合は間引く ▼▼▼
        # 1ラップあたり2000点を超えるとブラウザ描画が重くなる傾向があるため
        optimized_track = raw_track
        if len(raw_track) > 2000:
             # 0.000001 (約11cm) 程度の閾値で軽く間引く
             # これにより、直線上の過剰な点は削除されるが、コーナーの形状は保たれる
             optimized_track = _ramer_douglas_peucker(raw_track, 0.000001)
        # ▲▲▲ 修正ここまで ▲▲▲
        
        # マップ表示用はさらに強く間引く (閾値 0.000003 ≒ 33cm)
        # 保存時に既に0.000002で間引かれているが、マップ用はもっと荒くてもよい
        if len(raw_track) > 500:
            simplified_track = _ramer_douglas_peucker(raw_track, 0.000003)
        else:
            simplified_track = raw_track
            
        response_data['laps'].append({
            'lap_number': lap.get('lap_number'),
            'track': optimized_track,    # 修正: raw_track -> optimized_track
            'map_track': simplified_track # 地図表示用（軽量）
        })
    
    return jsonify(response_data)


@activity_bp.route('/session/<int:session_id>/edit', methods=['GET', 'POST'])
@limiter.limit("30 per hour")
@login_required
def edit_session(session_id):
    session = SessionLog.query.options(joinedload(SessionLog.activity).joinedload(ActivityLog.motorcycle))\
                               .join(ActivityLog)\
                               .filter(SessionLog.id == session_id, ActivityLog.user_id == current_user.id)\
                               .first_or_404()

    motorcycle = session.activity.motorcycle
    form = SessionLogForm(obj=session)
    
    from ...models import SettingSheet
    setting_sheets = SettingSheet.query.filter_by(motorcycle_id=motorcycle.id, is_archived=False).order_by(SettingSheet.sheet_name).all()
    form.setting_sheet_id.choices = [(s.id, s.sheet_name) for s in setting_sheets]
    form.setting_sheet_id.choices.insert(0, (0, '--- セッティングなし ---'))

    old_duration = session.session_duration_hours if motorcycle.is_racer else None

    if form.validate_on_submit():
        session.session_name = form.session_name.data
        session.setting_sheet_id = form.setting_sheet_id.data if form.setting_sheet_id.data != 0 else None
        session.rider_feel = form.rider_feel.data
        
        lap_times_list = json.loads(form.lap_times_json.data) if form.lap_times_json.data else []
        
        # ▼▼▼ 追加: GPSデータの同期処理 ▼▼▼
        lap_indices_json = request.form.get('lap_time_indices_json')
        if lap_indices_json and session.gps_tracks and session.gps_tracks.get('laps'):
            try:
                lap_indices = json.loads(lap_indices_json)
                current_gps_laps = {lap['lap_number']: lap for lap in session.gps_tracks['laps']}
                new_gps_laps = []
                
                # インデックスリスト（[0, 2, 4, null, ...]）を走査して新しいGPSリストを構築
                # nullは新規追加されたラップなのでGPSデータなし
                for i, original_idx in enumerate(lap_indices):
                    if original_idx is not None:
                        # オリジナルのラップ番号は index + 1
                        original_lap_num = original_idx + 1
                        if original_lap_num in current_gps_laps:
                            # 既存のトラックデータを取得し、新しいラップ番号を割り当てて保存
                            track_data = current_gps_laps[original_lap_num]
                            # deep copy的なことをして新しいオブジェクトにする
                            new_track_data = track_data.copy()
                            new_track_data['lap_number'] = i + 1
                            new_gps_laps.append(new_track_data)
                
                if new_gps_laps:
                    session.gps_tracks = {'laps': new_gps_laps}
                else:
                    session.gps_tracks = None
                    
            except (json.JSONDecodeError, ValueError) as e:
                current_app.logger.warning(f"Failed to sync GPS tracks: {e}")
                # エラー時は安全のためGPSデータを変更しない（あるいは整合性が取れないので削除するか要検討だが、一旦維持）
        # ▲▲▲ 追加ここまで ▲▲▲

        session.lap_times = lap_times_list
        _calculate_and_set_best_lap(session, lap_times_list)
        
        session.include_in_leaderboard = form.include_in_leaderboard.data

        if motorcycle.is_racer:
            new_duration = form.session_duration_hours.data
            session.session_duration_hours = new_duration
            
            duration_diff = (new_duration or Decimal('0.0')) - (old_duration or Decimal('0.0'))
            motorcycle.total_operating_hours = (motorcycle.total_operating_hours or Decimal('0.0')) + duration_diff
        else:
            session.session_distance = form.session_distance.data

        try:
            db.session.commit()
            flash('セッション記録を更新しました。', 'success')
            return redirect(url_for('activity.detail_activity', activity_id=session.activity_log_id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error editing session log {session_id}: {e}", exc_info=True)
            flash('セッション記録の更新中にエラーが発生しました。', 'danger')

    lap_times_json = json.dumps(session.lap_times) if session.lap_times else '[]'

    return render_template('activity/session_form.html',
                           form=form,
                           session=session,
                           motorcycle=motorcycle,
                           lap_times_json=lap_times_json)


@activity_bp.route('/session/<int:session_id>/delete', methods=['POST'])
@limiter.limit("30 per hour")
@login_required
def delete_session(session_id):
    session = SessionLog.query.join(ActivityLog).filter(SessionLog.id == session_id, ActivityLog.user_id == current_user.id).first_or_404()
    activity_id = session.activity_log_id
    try:
        db.session.delete(session)
        db.session.commit()
        flash('セッション記録を削除しました。', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting session log {session_id}: {e}", exc_info=True)
        flash('セッション記録の削除中にエラーが発生しました。', 'danger')
    return redirect(url_for('activity.detail_activity', activity_id=activity_id))


def _find_best_parser_type(file_storage, excluded_type):
    """
    アップロードされたファイルを各パーサーで試し、最適な形式を推測する。
    """
    PARSER_NAMES = dict(LapTimeImportForm().device_type.choices)

    for device_type, parser_class in PARSERS.items():
        if device_type == excluded_type:
            continue

        try:
            file_storage.seek(0)

            current_app.logger.debug(f"Probing with parser: {device_type}")

            parser = parser_class()

            if device_type == 'drogger':
                if parser.probe(file_storage.stream):
                     return PARSER_NAMES.get(device_type, device_type)
            else:
                encoding = 'shift_jis' if device_type == 'ziix' else 'utf-8'
                text_stream = io.TextIOWrapper(file_storage.stream, encoding=encoding, errors='replace', newline='')
                if parser.probe(text_stream):
                    text_stream.detach()
                    return PARSER_NAMES.get(device_type, device_type)
                text_stream.detach()

        except Exception as e:
            current_app.logger.debug(f"Probe for {device_type} failed: {e}")
            continue


def _find_best_parser_type_from_bytes(file_bytes, excluded_type):
    """bytes 版の _find_best_parser_type (streaming import 用)"""
    PARSER_NAMES = dict(LapTimeImportForm().device_type.choices)

    for device_type, parser_class in PARSERS.items():
        if device_type == excluded_type:
            continue
        try:
            parser = parser_class()
            byte_stream = io.BytesIO(file_bytes)
            if device_type == 'drogger':
                if parser.probe(byte_stream):
                    return PARSER_NAMES.get(device_type, device_type)
            else:
                encoding = 'shift_jis' if device_type == 'ziix' else 'utf-8'
                text_stream = io.TextIOWrapper(byte_stream, encoding=encoding, errors='replace', newline='')
                if parser.probe(text_stream):
                    text_stream.detach()
                    return PARSER_NAMES.get(device_type, device_type)
                text_stream.detach()
        except Exception as e:
            current_app.logger.debug(f"Probe (bytes) for {device_type} failed: {e}")
            continue
    return None

def _import_laps_generator(
    session_id, activity_log_id, file_bytes, device_type,
    remove_outliers_flag, threshold, is_append_mode, redirect_url
):
    """import_laps の処理を進捗イベントを yield しながら実行するジェネレータ。

    各 yield は {'stage': str, 'message': str, ...} 形式の dict。
    終端は 'done' か 'error' のいずれか1回。
    """
    PARSER_NAMES = dict(LapTimeImportForm().device_type.choices)
    parsed_data = None
    gps_tracks_dict = None

    try:
        yield {'stage': 'parsing', 'message': 'CSVファイルを解析中...'}

        parser = get_parser(device_type)
        if device_type == 'drogger':
            file_stream = io.BytesIO(file_bytes)
        else:
            encoding = 'shift_jis' if device_type == 'ziix' else 'utf-8'
            file_stream = io.TextIOWrapper(io.BytesIO(file_bytes), encoding=encoding, errors='replace')

        try:
            parsed_data = parser.parse(file_stream)
            lap_times_list = parsed_data.get('lap_times', [])
            if not lap_times_list:
                raise ValueError("No lap times parsed")
            for lap in lap_times_list:
                if not is_valid_lap_time_format(lap):
                    raise ValueError(f"Invalid lap time format detected: {lap}")
        except Exception as e:
            current_app.logger.warning(f"Parser '{device_type}' failed: {e}")
            suggested_format = _find_best_parser_type_from_bytes(file_bytes, device_type)
            display_name_failed = PARSER_NAMES.get(device_type, device_type)
            if suggested_format:
                yield {
                    'stage': 'error',
                    'message': f'「{display_name_failed}」形式では読み込めませんでした。このファイルは「{suggested_format}」形式ではありませんか？'
                }
            else:
                yield {
                    'stage': 'error',
                    'message': 'CSVファイルからラップタイムを読み込めませんでした。ファイルが空か、サポートされていない形式の可能性があります。'
                }
            return

        gps_tracks_dict = parsed_data.get('gps_tracks', {}) or {}
        parsed_data = None  # 早期解放

        original_lap_count = len(lap_times_list)
        laps_removed_count = 0
        if remove_outliers_flag:
            yield {'stage': 'filtering', 'message': '外れ値となるラップを除外中...'}
            filtered = filter_outlier_laps(lap_times_list, threshold_multiplier=float(threshold))
            laps_removed_count = original_lap_count - len(filtered)
            lap_times_list = filtered

        # ジェネレータ内で再取得 (元の session オブジェクトはこの時点で参照不可の可能性)
        session_obj = SessionLog.query.get(session_id)
        if not session_obj:
            yield {'stage': 'error', 'message': 'セッションが見つかりません。'}
            return

        sorted_keys = sorted(gps_tracks_dict.keys()) if gps_tracks_dict else []
        total_laps = len(sorted_keys)

        if is_append_mode:
            current_gps_data = session_obj.gps_tracks or {}
            if not isinstance(current_gps_data, dict):
                current_gps_data = {}
            current_laps_list = current_gps_data.get('laps', [])

            offset = len(current_laps_list)
            new_laps_list = []

            for idx, lap_num in enumerate(sorted_keys):
                yield {
                    'stage': 'optimizing',
                    'message': f'GPS軌跡を最適化中... ({idx + 1}/{total_laps})',
                    'lap': idx + 1,
                    'total_laps': total_laps,
                }
                raw_track_points = gps_tracks_dict[lap_num]
                simplified_points = _ramer_douglas_peucker(raw_track_points, 0.000002)
                optimized_points = _optimize_track_points(simplified_points)
                new_laps_list.append({"lap_number": offset + lap_num, "track": optimized_points})
                gps_tracks_dict[lap_num] = None
            gps_tracks_dict = None

            session_obj.gps_tracks = {"laps": current_laps_list + new_laps_list}
            current_times = session_obj.lap_times or []
            combined_lap_times = current_times + lap_times_list
            session_obj.lap_times = combined_lap_times
            _calculate_and_set_best_lap(session_obj, combined_lap_times)
            success_action = "追記"
        else:
            session_obj.lap_times = lap_times_list
            _calculate_and_set_best_lap(session_obj, lap_times_list)

            if total_laps > 0:
                laps_data_for_db = []
                for idx, lap_num in enumerate(sorted_keys):
                    yield {
                        'stage': 'optimizing',
                        'message': f'GPS軌跡を最適化中... ({idx + 1}/{total_laps})',
                        'lap': idx + 1,
                        'total_laps': total_laps,
                    }
                    raw_track_points = gps_tracks_dict[lap_num]
                    simplified_points = _ramer_douglas_peucker(raw_track_points, 0.000002)
                    optimized_points = _optimize_track_points(simplified_points)
                    laps_data_for_db.append({"lap_number": lap_num, "track": optimized_points})
                    gps_tracks_dict[lap_num] = None
                session_obj.gps_tracks = {"laps": laps_data_for_db} if laps_data_for_db else None
            else:
                session_obj.gps_tracks = None
            gps_tracks_dict = None
            success_action = "インポート"

        yield {'stage': 'saving', 'message': 'データベースに保存中...'}
        db.session.commit()

        success_message = f'{len(lap_times_list)}件のラップタイムを正常に{success_action}しました。'
        if laps_removed_count > 0:
            success_message += f' ({laps_removed_count}件の異常なラップを除外しました)'

        yield {
            'stage': 'done',
            'message': success_message,
            'redirect_url': redirect_url,
        }

    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.error(
            f"Error processing lap data for session {session_id}: {e}",
            exc_info=True,
        )
        yield {
            'stage': 'error',
            'message': 'ラップデータの処理中にエラーが発生しました。データサイズが大きすぎる可能性があります。',
        }


@activity_bp.route('/session/<int:session_id>/import_laps', methods=['POST'])
@limiter.limit("10 per hour")
@login_required
def import_laps(session_id):
    session = SessionLog.query.join(ActivityLog).filter(
        SessionLog.id == session_id, ActivityLog.user_id == current_user.id
    ).first_or_404()
    form = LapTimeImportForm()

    activity_log_id = session.activity_log_id
    redirect_url = url_for('activity.detail_activity', activity_id=activity_log_id)

    # AJAX/ndjson ストリーミング希望かどうか
    accept_header = request.headers.get('Accept', '') or ''
    wants_stream = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or 'application/x-ndjson' in accept_header
    )

    if not form.validate_on_submit():
        if wants_stream:
            error_msgs = []
            for field, errors in form.errors.items():
                label = form[field].label.text if hasattr(form[field], 'label') else field
                for error in errors:
                    error_msgs.append(f'{label}: {error}')
            return jsonify({
                'stage': 'error',
                'message': '\n'.join(error_msgs) or 'フォームのバリデーションに失敗しました。'
            }), 400

        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{form[field].label.text}: {error}', 'danger')
        return redirect(redirect_url)

    file_storage = form.csv_file.data
    file_storage.stream.seek(0)
    file_bytes = file_storage.stream.read()
    device_type = form.device_type.data
    remove_outliers_flag = form.remove_outliers.data
    threshold = form.outlier_threshold.data
    is_append_mode = form.append_mode.data

    if wants_stream:
        def json_lines():
            for event in _import_laps_generator(
                session_id, activity_log_id, file_bytes, device_type,
                remove_outliers_flag, threshold, is_append_mode, redirect_url,
            ):
                yield json.dumps(event, ensure_ascii=False) + '\n'

        return Response(
            stream_with_context(json_lines()),
            mimetype='application/x-ndjson',
        )

    # 非AJAX フォールバック: ジェネレータを同期消費して flash + redirect
    last_event = None
    for event in _import_laps_generator(
        session_id, activity_log_id, file_bytes, device_type,
        remove_outliers_flag, threshold, is_append_mode, redirect_url,
    ):
        last_event = event

    if last_event and last_event.get('stage') == 'done':
        flash(last_event.get('message', 'インポートが完了しました。'), 'success')
    elif last_event and last_event.get('stage') == 'error':
        flash(last_event.get('message', 'エラーが発生しました。'), 'danger')

    return redirect(redirect_url)


@activity_bp.route('/session/<int:session_id>/toggle_share', methods=['POST'])
@limiter.limit("60 per minute")
@login_required
def toggle_share_session(session_id):
    """セッションの公開設定を切り替えるAPI"""
    session = SessionLog.query.join(ActivityLog).filter(
        SessionLog.id == session_id,
        ActivityLog.user_id == current_user.id
    ).first_or_404()

    try:
        session.is_public = not session.is_public
        if session.is_public and not session.public_share_token:
            session.public_share_token = str(uuid.uuid4())
        
        db.session.commit()

        public_url = None
        if session.is_public:
            public_url = url_for('activity.public_session_view', token=session.public_share_token, _external=True)

        return jsonify({
            'success': True,
            'is_public': session.is_public,
            'public_url': public_url
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error toggling share for session {session_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'サーバーエラーが発生しました。'}), 500