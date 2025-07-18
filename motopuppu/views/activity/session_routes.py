# motopuppu/views/activity/session_routes.py
import json
import io
from collections import defaultdict
from decimal import Decimal

from flask import (
    flash, g, redirect, render_template, request, url_for, abort, current_app
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

# 他に必要なインポート
from .activity_routes import get_motorcycle_or_404 # ヘルパー関数をインポート
from ..auth import login_required_custom
from ...models import db, ActivityLog, SessionLog
from ...forms import SessionLogForm, LapTimeImportForm
from ...parsers import get_parser
from ... import limiter


def _prepare_comparison_data(sessions):
    """選択されたセッション群から比較用のデータを生成する"""
    if not sessions:
        return {}

    # 1. ラップタイム分析
    lap_analysis = {'stats': {}, 'chart_data': {'labels': [], 'datasets': []}}
    max_laps = 0
    chart_colors = ['rgb(75, 192, 192)', 'rgb(255, 99, 132)', 'rgb(54, 162, 235)', 'rgb(255, 205, 86)']
    
    # 1a. 各セッションのタイムを秒で計算し、一時的に保存
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
        
        # グラフ用データ作成
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

    # 1b. 全セッション中のベストタイムと平均タイムの最小値を見つける
    valid_best_laps = [s['best_sec'] for s in session_stats_raw if s['best_sec'] is not None]
    min_best_sec = min(valid_best_laps) if valid_best_laps else None
    
    valid_avg_laps = [s['avg_sec'] for s in session_stats_raw if s['avg_sec'] is not None]
    min_avg_sec = min(valid_avg_laps) if valid_avg_laps else None

    # 1c. 最終的な統計データを作成（差分計算を含む）
    for stats in session_stats_raw:
        session_id = stats['id']
        
        # ベストラップの差分
        best_diff_str = ''
        if min_best_sec is not None and stats['best_sec'] is not None:
            diff = stats['best_sec'] - min_best_sec
            if diff > 0:
                best_diff_str = f"+{diff:.3f}"

        # 平均ラップの差分
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
@login_required_custom
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
@login_required_custom
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

@activity_bp.route('/session/<int:session_id>/edit', methods=['GET', 'POST'])
@limiter.limit("30 per hour")
@login_required_custom
def edit_session(session_id):
    session = SessionLog.query.options(joinedload(SessionLog.activity).joinedload(ActivityLog.motorcycle))\
                               .join(ActivityLog)\
                               .filter(SessionLog.id == session_id, ActivityLog.user_id == g.user.id)\
                               .first_or_404()

    motorcycle = session.activity.motorcycle
    form = SessionLogForm(obj=session)
    
    # This needs to be imported here to avoid circular dependency at top level
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
@login_required_custom
def delete_session(session_id):
    session = SessionLog.query.join(ActivityLog).filter(SessionLog.id == session_id, ActivityLog.user_id == g.user.id).first_or_404()
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


@activity_bp.route('/session/<int:session_id>/import_laps', methods=['POST'])
@limiter.limit("10 per hour")
@login_required_custom
def import_laps(session_id):
    session = SessionLog.query.join(ActivityLog).filter(SessionLog.id == session_id, ActivityLog.user_id == g.user.id).first_or_404()
    form = LapTimeImportForm()

    if form.validate_on_submit():
        file_storage = form.csv_file.data
        device_type = form.device_type.data
        remove_outliers = form.remove_outliers.data

        try:
            parser = get_parser(device_type)
            encoding = 'shift_jis' if device_type == 'ziix' else 'utf-8'
            file_stream = io.TextIOWrapper(file_storage.stream, encoding=encoding, errors='replace')
            lap_times_list = parser.parse(file_stream)

            if not lap_times_list:
                flash('CSVファイルからラップタイムを読み込めませんでした。ファイルが空か、形式が異なっている可能性があります。', 'warning')
                return redirect(url_for('activity.detail_activity', activity_id=session.activity_log_id))

            for lap in lap_times_list:
                if not is_valid_lap_time_format(lap):
                    flash(f"CSVをパースしましたが、ラップタイムの形式が無効です (検出された値: '{lap}')。正しい機種を選択しているか確認してください。", 'danger')
                    return redirect(url_for('activity.detail_activity', activity_id=session.activity_log_id))

            original_lap_count = len(lap_times_list)
            laps_removed_count = 0
            
            if remove_outliers:
                filtered_laps = filter_outlier_laps(lap_times_list)
                laps_removed_count = original_lap_count - len(filtered_laps)
                lap_times_list = filtered_laps
            
            session.lap_times = lap_times_list
            _calculate_and_set_best_lap(session, lap_times_list)

            db.session.commit()
            
            success_message = f'{len(lap_times_list)}件のラップタイムを正常にインポートしました。'
            if laps_removed_count > 0:
                success_message += f' ({laps_removed_count}件の異常なラップを除外しました)'
            flash(success_message, 'success')

        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'danger')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Lap time import failed for session {session_id}: {e}", exc_info=True)
            flash(f'インポートに失敗しました。ファイルのエンコーディングや形式を確認してください。', 'danger')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{form[field].label.text}: {error}', 'danger')

    return redirect(url_for('activity.detail_activity', activity_id=session.activity_log_id))