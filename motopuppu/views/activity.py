# motopuppu/views/activity.py
import json
from datetime import date
from decimal import Decimal
import io
import re # ▼▼▼ 正規表現モジュールをインポート ▼▼▼
import statistics
# ▼▼▼ 追加 ▼▼▼
from collections import defaultdict

from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, abort, current_app
)
# ▼ func をインポート
from sqlalchemy import func
from sqlalchemy.orm import joinedload, aliased

from .auth import login_required_custom
from ..models import db, Motorcycle, ActivityLog, SessionLog, SettingSheet
from ..forms import ActivityLogForm, SessionLogForm, SettingSheetForm, LapTimeImportForm
from ..parsers import get_parser


# --- ▼▼▼ セッティング項目定義を修正 ▼▼▼ ---
SETTING_KEY_MAP = {
    "sprocket": {
        "title": "スプロケット",
        "keys": {
            "front_teeth": "フロント (T)",
            "rear_teeth": "リア (T)"
        }
    },
    "ignition": {
        "title": "点火",
        "keys": {
            "spark_plug": "プラグ"
        }
    },
    "suspension": {
        "title": "サスペンション",
        "keys": {
            # フロント
            "front_protrusion_mm": "F: 突き出し(mm)",
            "front_preload": "F: プリロード",
            "front_spring_rate_nm": "F: スプリングレート(Nm)",
            "front_fork_oil": "F: フォークオイル",
            "front_oil_level_mm": "F: 油面(mm)",
            "front_damping_compression": "F: 減衰(圧側)",
            "front_damping_rebound": "F: 減衰(伸側)",
            # リア
            "rear_spring_rate_nm": "R: スプリングレート(Nm)",
            "rear_preload": "R: プリロード",
            "rear_damping_compression": "R: 減衰(圧側)",
            "rear_damping_rebound": "R: 減衰(伸側)"
        }
    },
    "tire": {
        "title": "タイヤ",
        "keys": {
            "tire_brand": "タイヤ銘柄",
            "tire_compound": "コンパウンド",
            "tire_pressure_kpa": "空気圧(kPa)"
        }
    },
    "carburetor": {
        "title": "キャブレター",
        "keys": {
            "main_jet": "メインジェット",
            "slow_jet": "スロージェット",
            "needle": "ニードル",
            "clip_position": "クリップ位置",
            "idle_screw": "アイドルスクリュー"
        }
    },
    "ecu": {
        "title": "ECU",
        "keys": {
            "map_name": "セット名"
        }
    }
}
# --- ▲▲▲ 修正ここまで ▲▲▲ ---


# --- ▼▼▼ ラップタイム計算用ヘルパー関数 ▼▼▼ ---
def get_rank_suffix(rank: int) -> str:
    """順位に応じた英語の接尾辞 (st, nd, rd, th) を返す"""
    if not isinstance(rank, int) or rank <= 0:
        return ""
    if 11 <= (rank % 100) <= 13:
        return "th"
    last_digit = rank % 10
    if last_digit == 1:
        return "st"
    if last_digit == 2:
        return "nd"
    if last_digit == 3:
        return "rd"
    return "th"

def parse_time_to_seconds(time_str):
    """ "M:S.f" または "S.f" 形式の文字列を秒(Decimal)に変換 """
    if not isinstance(time_str, str): return None
    try:
        # ZiiXの M'S.f 形式も考慮
        time_str = time_str.replace("'", ":")
        parts = time_str.split(':')
        if len(parts) == 2:
            # M:S.f 形式
            minutes = Decimal(parts[0])
            seconds = Decimal(parts[1])
            return minutes * 60 + seconds
        else:
            # S.f 形式
            return Decimal(parts[0])
    except:
        return None

def format_seconds_to_time(total_seconds):
    """ 秒(Decimal)を "M:SS.fff" 形式の文字列に変換 """
    if total_seconds is None: return "N/A"
    total_seconds = Decimal(total_seconds)
    minutes = int(total_seconds // 60)
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:06.3f}" # 0埋めして S.fff 形式にする

def calculate_lap_stats(lap_times):
    """ ラップタイムのリストからベスト、平均、各ラップの詳細（順位含む）を計算する """
    if not lap_times or not isinstance(lap_times, list):
        return "N/A", "N/A", []

    # 1. 元のインデックスを保持したまま、有効なラップタイム（秒）のリストを作成
    lap_seconds_indexed = []
    for i, t in enumerate(lap_times):
        sec = parse_time_to_seconds(t)
        if sec is not None and sec > 0:
            lap_seconds_indexed.append({'original_index': i, 'seconds': sec})

    if not lap_seconds_indexed:
        return "N/A", "N/A", []

    # 2. 統計計算のために秒のみのリストも用意
    valid_seconds = [item['seconds'] for item in lap_seconds_indexed]
    best_lap_sec = min(valid_seconds)
    average_lap_sec = sum(valid_seconds) / len(valid_seconds)

    # 3. タイム順にソートして順位を決定
    sorted_laps = sorted(lap_seconds_indexed, key=lambda x: x['seconds'])

    # 4. 元のインデックスをキーとして順位をマッピング
    rank_map = {}
    for rank, item in enumerate(sorted_laps, 1):
        rank_map[item['original_index']] = rank

    # 5. 最終的な詳細リストを作成
    lap_details = []
    for item in lap_seconds_indexed:
        original_index = item['original_index']
        sec = item['seconds']
        rank = rank_map.get(original_index)
        
        gap_str = ""
        if sec != best_lap_sec:
            diff = sec - best_lap_sec
            suffix = get_rank_suffix(rank)
            gap_str = f"+{diff:.3f} ({rank}{suffix})"

        lap_details.append({
            'lap_num': original_index + 1,
            'time_str': format_seconds_to_time(sec),
            'diff_str': gap_str,
            'is_best': sec == best_lap_sec
        })
    
    # 元の順序に戻す
    lap_details.sort(key=lambda x: x['lap_num'])

    return format_seconds_to_time(best_lap_sec), format_seconds_to_time(average_lap_sec), lap_details

def _calculate_and_set_best_lap(session, lap_times_list):
    """
    ラップタイムのリストからベストラップを秒で計算し、
    セッションオブジェクトにセットする
    """
    if not lap_times_list:
        session.best_lap_seconds = None
        return
    
    lap_seconds = [s for s in (parse_time_to_seconds(t) for t in lap_times_list) if s is not None]
    
    if lap_seconds:
        session.best_lap_seconds = min(lap_seconds)
    else:
        session.best_lap_seconds = None

def filter_outlier_laps(lap_times_list: list, threshold_multiplier: float = 2.0) -> list:
    """
    ラップタイムのリストから外れ値（極端に遅いラップ）を除外する。
    中央値の threshold_multiplier 倍より遅いラップを外れ値とみなす。
    """
    if not lap_times_list or len(lap_times_list) < 3:
        return lap_times_list # データが少ない場合は何もしない

    # 文字列のラップタイムをDecimalの秒に変換
    lap_seconds = [s for s in (parse_time_to_seconds(t) for t in lap_times_list) if s is not None and s > 0]
    if not lap_seconds:
        return []

    # 中央値を計算
    median_lap = statistics.median(lap_seconds)
    
    # 閾値を設定 (中央値の N 倍)
    threshold = median_lap * Decimal(str(threshold_multiplier))

    # 閾値を超えないラップタイムのみをフィルタリング
    # 元の文字列リストのインデックスと秒リストのインデックスは一致すると仮定
    filtered_laps = [
        lap_str for lap_str, lap_sec in zip(lap_times_list, lap_seconds) if lap_sec <= threshold
    ]
    
    return filtered_laps

def is_valid_lap_time_format(s: str) -> bool:
    """
    文字列が '分:秒.ミリ秒' または '秒.ミリ秒' の形式かチェックする。
    例: '1:23.456', '83.456', '1:23', '83'
    """
    if not isinstance(s, str):
        return False
    # 正規表現パターン: (任意で[数字とコロン]) + [数字] + (任意で[ドットと数字])
    # これにより "M:S.f" と "S.f" の両方の形式にマッチする
    pattern = re.compile(r'^(\d+:)?\d+(\.\d+)?$')
    return bool(pattern.match(s))


activity_bp = Blueprint('activity', __name__, url_prefix='/activity')

# --- Helper Functions ---
def get_motorcycle_or_404(vehicle_id):
    """指定されたIDの車両を取得し、所有者でなければ404を返す"""
    return Motorcycle.query.filter_by(id=vehicle_id, user_id=g.user.id).first_or_404()

# --- ▼▼▼ 比較機能ヘルパー関数 (完成版) ▼▼▼ ---
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

            # ★★★ ここでキー名を 'is_diff' に変更 ★★★
            row_data['is_diff'] = len(values_set) > 1
            settings_comparison.append(row_data)

    return {
        'lap_analysis': lap_analysis,
        'settings_comparison': settings_comparison,
    }
# --- ▲▲▲ 比較機能ヘルパー関数 ▲▲▲ ---


# --- ActivityLog Routes ---
# ... (以降のコードは変更ありませんので、そのままお使いください) ...
@activity_bp.route('/<int:vehicle_id>')
@login_required_custom
def list_activities(vehicle_id):
    """指定された車両の活動ログ一覧を表示する"""
    motorcycle = get_motorcycle_or_404(vehicle_id)
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('ACTIVITIES_PER_PAGE', 10)
    
    best_lap_subquery = db.session.query(
        SessionLog.activity_log_id,
        func.min(SessionLog.best_lap_seconds).label('overall_best_lap_seconds')
    ).filter(SessionLog.best_lap_seconds.isnot(None)).group_by(SessionLog.activity_log_id).subquery()

    query = db.session.query(
            ActivityLog, 
            best_lap_subquery.c.overall_best_lap_seconds
        ).outerjoin(
            best_lap_subquery, ActivityLog.id == best_lap_subquery.c.activity_log_id
        ).filter(
            ActivityLog.motorcycle_id == motorcycle.id
        ).order_by(
            ActivityLog.activity_date.desc()
        )
    
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    activities_for_template = []
    for activity, best_lap_seconds in pagination.items:
        formatted_lap = format_seconds_to_time(best_lap_seconds) if best_lap_seconds else ''
        activities_for_template.append({
            'activity': activity, 
            'best_lap_formatted': formatted_lap
        })
    
    return render_template('activity/list_activities.html',
                           motorcycle=motorcycle,
                           activities=activities_for_template,
                           pagination=pagination)

@activity_bp.route('/<int:vehicle_id>/add', methods=['GET', 'POST'])
@login_required_custom
def add_activity(vehicle_id):
    """新しい活動ログを作成する"""
    motorcycle = get_motorcycle_or_404(vehicle_id)
    if request.method == 'POST':
        event_id = request.form.get('event_id', type=int)
    else:
        event_id = request.args.get('event_id', type=int)

    form = ActivityLogForm(request.form)
    
    if form.validate_on_submit():
        new_activity = ActivityLog(
            motorcycle_id=motorcycle.id,
            user_id=g.user.id,
            event_id=event_id,
            activity_date=form.activity_date.data,
            activity_title=form.activity_title.data,
            location_type=form.location_type.data,
            circuit_name=form.circuit_name.data if form.location_type.data == 'circuit' else None,
            custom_location=form.custom_location.data if form.location_type.data == 'custom' else None,
            weather=form.weather.data,
            temperature=form.temperature.data,
            notes=form.notes.data
        )
        try:
            db.session.add(new_activity)
            db.session.commit()
            flash('新しい活動記録を作成しました。走行セッションを記録してください。', 'success')
            return redirect(url_for('activity.detail_activity', activity_id=new_activity.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error adding new activity log: {e}", exc_info=True)
            flash('活動記録の保存中にエラーが発生しました。', 'danger')

    if request.method == 'GET':
        form.activity_title.data = request.args.get('activity_title', '')
        activity_date_str = request.args.get('activity_date')
        if activity_date_str:
            try:
                form.activity_date.data = date.fromisoformat(activity_date_str)
            except (ValueError, TypeError):
                form.activity_date.data = date.today()
        
        custom_location = request.args.get('custom_location')
        if custom_location:
            form.location_type.data = 'custom'
            form.custom_location.data = custom_location

    return render_template('activity/activity_form.html',
                           form=form,
                           motorcycle=motorcycle,
                           event_id=event_id,
                           form_action='add')

@activity_bp.route('/<int:activity_id>/edit', methods=['GET', 'POST'])
@login_required_custom
def edit_activity(activity_id):
    """活動ログを編集する"""
    activity = ActivityLog.query.filter_by(id=activity_id, user_id=g.user.id).first_or_404()
    motorcycle = activity.motorcycle
    form = ActivityLogForm(obj=activity)

    if form.validate_on_submit():
        activity.activity_date = form.activity_date.data
        activity.activity_title = form.activity_title.data
        activity.location_type = form.location_type.data
        activity.circuit_name = form.circuit_name.data if form.location_type.data == 'circuit' else None
        activity.custom_location = form.custom_location.data if form.location_type.data == 'custom' else None
        activity.weather = form.weather.data
        activity.temperature = form.temperature.data
        activity.notes = form.notes.data
        try:
            db.session.commit()
            flash('活動ログを更新しました。', 'success')
            return redirect(url_for('activity.detail_activity', activity_id=activity.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error editing activity log {activity_id}: {e}", exc_info=True)
            flash('活動ログの更新中にエラーが発生しました。', 'danger')
    
    if request.method == 'GET':
        form.location_type.data = activity.location_type or 'circuit'
        form.circuit_name.data = activity.circuit_name
        form.custom_location.data = activity.custom_location

    return render_template('activity/activity_form.html',
                           form=form,
                           motorcycle=motorcycle,
                           activity=activity,
                           form_action='edit')

@activity_bp.route('/<int:activity_id>/delete', methods=['POST'])
@login_required_custom
def delete_activity(activity_id):
    """活動ログを削除する"""
    activity = ActivityLog.query.filter_by(id=activity_id, user_id=g.user.id).first_or_404()
    vehicle_id = activity.motorcycle_id
    try:
        db.session.delete(activity)
        db.session.commit()
        flash('活動ログを削除しました。', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting activity log {activity_id}: {e}", exc_info=True)
        flash('活動ログの削除中にエラーが発生しました。', 'danger')
    return redirect(url_for('activity.list_activities', vehicle_id=vehicle_id))


@activity_bp.route('/<int:activity_id>/detail', methods=['GET', 'POST'])
@login_required_custom
def detail_activity(activity_id):
    """活動ログの詳細とセッションの追加/一覧表示"""
    activity = ActivityLog.query.options(joinedload(ActivityLog.motorcycle))\
                                 .filter_by(id=activity_id)\
                                 .first_or_404()
    if activity.user_id != g.user.id:
        abort(403)
        
    motorcycle = activity.motorcycle
    sessions = SessionLog.query.filter_by(activity_log_id=activity.id).order_by(SessionLog.id.asc()).all()

    for session in sessions:
        session.best_lap, session.average_lap, session.lap_details = calculate_lap_stats(session.lap_times)
        
        lap_seconds_for_chart = []
        if session.lap_times and isinstance(session.lap_times, list):
            for lap_str in session.lap_times:
                sec = parse_time_to_seconds(lap_str)
                if sec is not None and sec > 0:
                    lap_seconds_for_chart.append(float(sec))
        
        if lap_seconds_for_chart:
            best_lap_seconds = min(lap_seconds_for_chart)
            lap_percentages = [(best_lap_seconds / sec) * 100 for sec in lap_seconds_for_chart]
            session.lap_chart_dict = {
                'labels': list(range(1, len(lap_seconds_for_chart) + 1)),
                'percentages': lap_percentages,
                'raw_times': lap_seconds_for_chart
            }
        else:
            session.lap_chart_dict = None
    
    session_form = SessionLogForm()
    import_form = LapTimeImportForm()

    setting_sheets = SettingSheet.query.filter_by(motorcycle_id=motorcycle.id, is_archived=False).order_by(SettingSheet.sheet_name).all()
    session_form.setting_sheet_id.choices = [(s.id, s.sheet_name) for s in setting_sheets]
    session_form.setting_sheet_id.choices.insert(0, (0, '--- セッティングなし ---'))

    if session_form.validate_on_submit():
        lap_times_list = json.loads(session_form.lap_times_json.data) if session_form.lap_times_json.data else []
        
        new_session = SessionLog(
            activity_log_id=activity.id,
            session_name=session_form.session_name.data,
            setting_sheet_id=session_form.setting_sheet_id.data if session_form.setting_sheet_id.data != 0 else None,
            rider_feel=session_form.rider_feel.data,
            lap_times=lap_times_list,
            include_in_leaderboard=session_form.include_in_leaderboard.data
        )

        _calculate_and_set_best_lap(new_session, lap_times_list)

        if motorcycle.is_racer:
            duration = session_form.session_duration_hours.data
            if duration is not None:
                new_session.session_duration_hours = duration
                current_hours = motorcycle.total_operating_hours or Decimal('0.0')
                motorcycle.total_operating_hours = current_hours + duration
        else:
            distance = session_form.session_distance.data
            if distance is not None:
                new_session.session_distance = distance

        try:
            db.session.add(new_session)
            db.session.commit()
            flash('新しいセッションを記録しました。', 'success')
            return redirect(url_for('activity.detail_activity', activity_id=activity.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error adding new session log: {e}", exc_info=True)
            flash('セッションの保存中にエラーが発生しました。', 'danger')

    return render_template('activity/detail_activity.html',
                           activity=activity,
                           sessions=sessions,
                           motorcycle=motorcycle,
                           session_form=session_form,
                           import_form=import_form,
                           setting_key_map=SETTING_KEY_MAP)

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
@login_required_custom
def edit_session(session_id):
    session = SessionLog.query.options(joinedload(SessionLog.activity).joinedload(ActivityLog.motorcycle))\
                               .join(ActivityLog)\
                               .filter(SessionLog.id == session_id, ActivityLog.user_id == g.user.id)\
                               .first_or_404()

    motorcycle = session.activity.motorcycle
    form = SessionLogForm(obj=session)
    
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


# --- SettingSheet Routes ---
@activity_bp.route('/<int:vehicle_id>/settings')
@login_required_custom
def list_settings(vehicle_id):
    motorcycle = get_motorcycle_or_404(vehicle_id)
    settings = SettingSheet.query.filter_by(motorcycle_id=motorcycle.id).order_by(SettingSheet.is_archived, SettingSheet.sheet_name).all()
    return render_template('activity/list_settings.html',
                           motorcycle=motorcycle,
                           settings=settings)

@activity_bp.route('/<int:vehicle_id>/settings/add', methods=['GET', 'POST'])
@login_required_custom
def add_setting(vehicle_id):
    motorcycle = get_motorcycle_or_404(vehicle_id)
    form = SettingSheetForm()

    if form.validate_on_submit():
        details_json_str = request.form.get('details_json', '{}')
        try:
            details = json.loads(details_json_str)
        except (json.JSONDecodeError, TypeError):
            flash('セッティング詳細のデータ形式が無効です。', 'danger')
            return render_template('activity/setting_form.html', form=form, motorcycle=motorcycle, form_action='add', details_json=details_json_str)

        new_setting = SettingSheet(
            motorcycle_id=motorcycle.id,
            user_id=g.user.id,
            sheet_name=form.sheet_name.data,
            details=details,
            notes=form.notes.data
        )
        try:
            db.session.add(new_setting)
            db.session.commit()
            flash(f'セッティングシート「{new_setting.sheet_name}」を作成しました。', 'success')
            return redirect(url_for('activity.list_settings', vehicle_id=motorcycle.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error adding new setting sheet: {e}", exc_info=True)
            flash('セッティングシートの保存中にエラーが発生しました。', 'danger')
    
    if request.method == 'POST' and form.errors:
        error_messages = '; '.join([f'{field}: {", ".join(error_list)}' for field, error_list in form.errors.items()])
        flash(f'入力内容にエラーがあります: {error_messages}', 'danger')

    return render_template('activity/setting_form.html',
                           form=form,
                           motorcycle=motorcycle,
                           form_action='add',
                           details_json='{}')

@activity_bp.route('/settings/<int:setting_id>/edit', methods=['GET', 'POST'])
@login_required_custom
def edit_setting(setting_id):
    setting = SettingSheet.query.filter_by(id=setting_id, user_id=g.user.id).first_or_404()
    motorcycle = setting.motorcycle
    form = SettingSheetForm(obj=setting)

    if form.validate_on_submit():
        details_json_str = request.form.get('details_json', '{}')
        
        try:
            details = json.loads(details_json_str)
        except (json.JSONDecodeError, TypeError):
            flash('セッティング詳細のデータ形式が無効です。', 'danger')
            return render_template('activity/setting_form.html', form=form, motorcycle=motorcycle, setting=setting, form_action='edit', details_json=details_json_str)

        setting.sheet_name = form.sheet_name.data
        setting.notes = form.notes.data
        setting.details = details
        
        try:
            db.session.commit()
            flash(f'セッティングシート「{setting.sheet_name}」を更新しました。', 'success')
            return redirect(url_for('activity.list_settings', vehicle_id=motorcycle.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error editing setting sheet {setting_id}: {e}", exc_info=True)
            flash('セッティングシートの更新中にエラーが発生しました。', 'danger')

    details_json_for_template = json.dumps(setting.details)
    return render_template('activity/setting_form.html',
                           form=form,
                           motorcycle=motorcycle,
                           setting=setting,
                           form_action='edit',
                           details_json=details_json_for_template)

@activity_bp.route('/settings/<int:setting_id>/toggle_archive', methods=['POST'])
@login_required_custom
def toggle_archive_setting(setting_id):
    setting = SettingSheet.query.filter_by(id=setting_id, user_id=g.user.id).first_or_404()
    setting.is_archived = not setting.is_archived
    try:
        db.session.commit()
        status = "アーカイブしました" if setting.is_archived else "有効化しました"
        flash(f'セッティングシート「{setting.sheet_name}」を{status}。', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error toggling archive for setting sheet {setting_id}: {e}", exc_info=True)
        flash('状態の変更中にエラーが発生しました。', 'danger')
    return redirect(url_for('activity.list_settings', vehicle_id=setting.motorcycle_id))

@activity_bp.route('/settings/<int:setting_id>/delete', methods=['POST'])
@login_required_custom
def delete_setting(setting_id):
    setting = SettingSheet.query.filter_by(id=setting_id, user_id=g.user.id).first_or_404()
    vehicle_id = setting.motorcycle_id
    sheet_name = setting.sheet_name
    try:
        db.session.delete(setting)
        db.session.commit()
        flash(f'セッティングシート「{sheet_name}」を削除しました。', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting setting sheet {setting_id}: {e}", exc_info=True)
        flash('セッティングシートの削除中にエラーが発生しました。', 'danger')
    return redirect(url_for('activity.list_settings', vehicle_id=vehicle_id))