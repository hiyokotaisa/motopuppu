# motopuppu/views/activity.py
import json
from datetime import date

from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, abort, current_app
)
from sqlalchemy.orm import joinedload

from .auth import login_required_custom
from ..models import db, Motorcycle, ActivityLog, SessionLog, SettingSheet
from ..forms import ActivityLogForm, SessionLogForm, SettingSheetForm, JAPANESE_CIRCUITS

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
    
    pagination = ActivityLog.query.filter_by(motorcycle_id=motorcycle.id)\
                                  .order_by(ActivityLog.activity_date.desc())\
                                  .paginate(page=page, per_page=per_page, error_out=False)
    activities = pagination.items
    
    return render_template('activity/list_activities.html',
                           motorcycle=motorcycle,
                           activities=activities,
                           pagination=pagination)

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
            location_name=form.location_name.data,
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
                           circuits=JAPANESE_CIRCUITS,
                           form_action='add')

@activity_bp.route('/<int:activity_id>/edit', methods=['GET', 'POST'])
@login_required_custom
def edit_activity(activity_id):
    """活動ログを編集する"""
    activity = ActivityLog.query.filter_by(id=activity_id, user_id=g.user.id).first_or_404()
    motorcycle = activity.motorcycle
    form = ActivityLogForm(obj=activity)

    if form.validate_on_submit():
        form.populate_obj(activity)
        try:
            db.session.commit()
            flash('活動ログを更新しました。', 'success')
            return redirect(url_for('activity.detail_activity', activity_id=activity.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error editing activity log {activity_id}: {e}", exc_info=True)
            flash('活動ログの更新中にエラーが発生しました。', 'danger')

    return render_template('activity/activity_form.html',
                           form=form,
                           motorcycle=motorcycle,
                           activity=activity,
                           circuits=JAPANESE_CIRCUITS,
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
    sessions = activity.sessions.all()
    
    session_form = SessionLogForm()
    setting_sheets = SettingSheet.query.filter_by(motorcycle_id=motorcycle.id, is_archived=False).order_by(SettingSheet.sheet_name).all()
    session_form.setting_sheet_id.choices = [(s.id, s.sheet_name) for s in setting_sheets]
    session_form.setting_sheet_id.choices.insert(0, (0, '--- セッティングなし ---'))

    if session_form.validate_on_submit():
        new_session = SessionLog(
            activity_log_id=activity.id,
            session_name=session_form.session_name.data,
            setting_sheet_id=session_form.setting_sheet_id.data if session_form.setting_sheet_id.data != 0 else None,
            rider_feel=session_form.rider_feel.data,
            lap_times=json.loads(session_form.lap_times_json.data) if session_form.lap_times_json.data else None
        )

        if motorcycle.is_racer:
            new_session.operating_hours_start = session_form.operating_hours_start.data
            new_session.operating_hours_end = session_form.operating_hours_end.data
            if new_session.operating_hours_end and (motorcycle.total_operating_hours is None or new_session.operating_hours_end > motorcycle.total_operating_hours):
                motorcycle.total_operating_hours = new_session.operating_hours_end
        else:
            new_session.odo_start = session_form.odo_start.data
            new_session.odo_end = session_form.odo_end.data

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
                           session_form=session_form)

# --- SessionLog Routes ---

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