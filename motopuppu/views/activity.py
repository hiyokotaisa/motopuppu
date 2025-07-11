# motopuppu/views/activity.py
import json
from datetime import date
from decimal import Decimal

from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, abort, current_app
)
# ▼ func をインポート
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from .auth import login_required_custom
from ..models import db, Motorcycle, ActivityLog, SessionLog, SettingSheet
from ..forms import ActivityLogForm, SessionLogForm, SettingSheetForm, JAPANESE_CIRCUITS


# --- ▼▼▼ セッティング項目定義を追加 ▼▼▼ ---
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
            "front_protrusion_mm": "突き出し(mm)",
            "front_preload": "プリロード",
            "front_spring_rate_nm": "スプリングレート(Nm)",
            "front_fork_oil": "フォークオイル",
            "front_oil_level_mm": "油面(mm)",
            "front_damping_compression": "減衰(圧側)",
            "front_damping_rebound": "減衰(伸側)",
            # リア
            "rear_spring_rate_nm": "スプリングレート(Nm)",
            "rear_preload": "プリロード",
            "rear_damping_compression": "減衰(圧側)",
            "rear_damping_rebound": "減衰(伸側)"
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
# --- ▲▲▲ 追加はここまで ▲▲▲ ---


# --- ▼▼▼ ラップタイム計算用ヘルパー関数 ▼▼▼ ---
def parse_time_to_seconds(time_str):
    """ "M:S.f" 形式の文字列を秒(Decimal)に変換 """
    if not isinstance(time_str, str): return None
    try:
        parts = time_str.split(':')
        if len(parts) == 2:
            minutes = Decimal(parts[0])
            seconds = Decimal(parts[1])
            return minutes * 60 + seconds
        else:
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
    """ ラップタイムのリストからベストと平均を計算 """
    if not lap_times or not isinstance(lap_times, list):
        return "N/A", "N/A"
    
    lap_seconds = [s for s in (parse_time_to_seconds(t) for t in lap_times) if s is not None]
    
    if not lap_seconds:
        return "N/A", "N/A"

    best_lap = min(lap_seconds)
    average_lap = sum(lap_seconds) / len(lap_seconds)
    
    return format_seconds_to_time(best_lap), format_seconds_to_time(average_lap)

# --- ▼▼▼ 変更: ベストラップ計算ヘルパーを追加 ▼▼▼ ---
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
# --- ▲▲▲ 変更ここまで ▲▲▲ ---


activity_bp = Blueprint('activity', __name__, url_prefix='/activity')

# --- Helper Functions ---
def get_motorcycle_or_404(vehicle_id):
    """指定されたIDの車両を取得し、所有者でなければ404を返す"""
    return Motorcycle.query.filter_by(id=vehicle_id, user_id=g.user.id).first_or_404()

# --- ActivityLog Routes ---

@activity_bp.route('/<int:vehicle_id>')
@login_required_custom
def list_activities(vehicle_id):
    """指定された車両の活動ログ一覧を表示する"""
    motorcycle = get_motorcycle_or_404(vehicle_id)
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('ACTIVITIES_PER_PAGE', 10)
    
    # ▼▼▼ ここから修正 ▼▼▼
    # 1. ベストラップを計算するサブクエリを作成
    best_lap_subquery = db.session.query(
        SessionLog.activity_log_id,
        func.min(SessionLog.best_lap_seconds).label('overall_best_lap_seconds')
    ).filter(SessionLog.best_lap_seconds.isnot(None)).group_by(SessionLog.activity_log_id).subquery()

    # 2. メインクエリでサブクエリを外部結合
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
    
    # 3. テンプレートで使いやすいように、結果を整形
    activities_for_template = []
    for activity, best_lap_seconds in pagination.items:
        formatted_lap = format_seconds_to_time(best_lap_seconds) if best_lap_seconds else ''
        activities_for_template.append({
            'activity': activity, 
            'best_lap_formatted': formatted_lap
        })
    # ▲▲▲ 修正ここまで ▲▲▲
    
    return render_template('activity/list_activities.html',
                           motorcycle=motorcycle,
                           activities=activities_for_template,  # 整形したリストを渡す
                           pagination=pagination)

# --- ▼▼▼ 変更: 新しいフォームとDB構造に対応 ▼▼▼ ---
@activity_bp.route('/<int:vehicle_id>/add', methods=['GET', 'POST'])
@login_required_custom
def add_activity(vehicle_id):
    """新しい活動ログを作成する"""
    motorcycle = get_motorcycle_or_404(vehicle_id)
    form = ActivityLogForm()
    
    if form.validate_on_submit():
        new_activity = ActivityLog(
            motorcycle_id=motorcycle.id,
            user_id=g.user.id,
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

    return render_template('activity/activity_form.html',
                           form=form,
                           motorcycle=motorcycle,
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
    
    # GETリクエストの場合、DBの値からフォームにデフォルト値を設定
    if request.method == 'GET':
        form.location_type.data = activity.location_type or 'circuit'
        form.circuit_name.data = activity.circuit_name
        form.custom_location.data = activity.custom_location

    return render_template('activity/activity_form.html',
                           form=form,
                           motorcycle=motorcycle,
                           activity=activity,
                           form_action='edit')
# --- ▲▲▲ 変更ここまで ▲▲▲ ---

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
    sessions = activity.sessions.all()

    for session in sessions:
        session.best_lap, session.average_lap = calculate_lap_stats(session.lap_times)
    
    session_form = SessionLogForm()
    setting_sheets = SettingSheet.query.filter_by(motorcycle_id=motorcycle.id, is_archived=False).order_by(SettingSheet.sheet_name).all()
    session_form.setting_sheet_id.choices = [(s.id, s.sheet_name) for s in setting_sheets]
    session_form.setting_sheet_id.choices.insert(0, (0, '--- セッティングなし ---'))

    # --- ▼▼▼ 変更: セッション追加ロジックを更新 ▼▼▼ ---
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
    # --- ▲▲▲ 変更ここまで ▲▲▲ ---

    return render_template('activity/detail_activity.html',
                           activity=activity,
                           sessions=sessions,
                           motorcycle=motorcycle,
                           session_form=session_form,
                           setting_key_map=SETTING_KEY_MAP)

# --- SessionLog Routes ---

# --- ▼▼▼ 変更: セッション編集ロジックを更新 ▼▼▼ ---
@activity_bp.route('/session/<int:session_id>/edit', methods=['GET', 'POST'])
@login_required_custom
def edit_session(session_id):
    """セッションログを編集する"""
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
# --- ▲▲▲ 変更ここまで ▲▲▲ ---


@activity_bp.route('/session/<int:session_id>/delete', methods=['POST'])
@login_required_custom
def delete_session(session_id):
    """セッションログを削除する"""
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

# --- SettingSheet Routes ---
@activity_bp.route('/<int:vehicle_id>/settings')
@login_required_custom
def list_settings(vehicle_id):
    """セッティングシートの一覧を表示する"""
    motorcycle = get_motorcycle_or_404(vehicle_id)
    settings = SettingSheet.query.filter_by(motorcycle_id=motorcycle.id).order_by(SettingSheet.is_archived, SettingSheet.sheet_name).all()
    return render_template('activity/list_settings.html',
                           motorcycle=motorcycle,
                           settings=settings)

@activity_bp.route('/<int:vehicle_id>/settings/add', methods=['GET', 'POST'])
@login_required_custom
def add_setting(vehicle_id):
    """新しいセッティングシートを作成する"""
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
    """セッティングシートを編集する"""
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
    """セッティングシートのアーカイブ状態を切り替える"""
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
    """セッティングシートを完全に削除する"""
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