# motopuppu/views/reminder.py
from flask import (
    Blueprint, flash, redirect, render_template, request, url_for, abort, current_app
)
from datetime import date, datetime, timezone, timedelta
from dateutil.relativedelta import relativedelta
from zoneinfo import ZoneInfo
from sqlalchemy import func
# ▼▼▼ インポート文を修正 ▼▼▼
from flask_login import login_required, current_user
# ▲▲▲ 変更ここまで ▲▲▲
from ..models import db, Motorcycle, MaintenanceReminder, MaintenanceEntry
from ..forms import ReminderForm
from .. import limiter


reminder_bp = Blueprint('reminder', __name__, url_prefix='/reminders')

@reminder_bp.route('/vehicle/<int:vehicle_id>')
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def list_reminders(vehicle_id):
    """車両別のリマインダー一覧ページ"""
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=current_user.id).first_or_404()
    # ▲▲▲ 変更ここまで ▲▲▲

    all_reminders = MaintenanceReminder.query.filter_by(motorcycle_id=vehicle_id).order_by(MaintenanceReminder.task_description, MaintenanceReminder.id).all()
    
    active_reminders = []
    # ▼▼▼【ここから変更】非表示リマインダーは状態を持つ辞書のリストに変更 ▼▼▼
    inactive_reminders = []
    now = datetime.now(timezone.utc)

    for r in all_reminders:
        is_snoozed = False
        snoozed_until_aware = None
        if r.snoozed_until:
            snoozed_until_aware = r.snoozed_until.replace(tzinfo=timezone.utc)
            if snoozed_until_aware > now:
                is_snoozed = True
        
        if r.is_dismissed:
            inactive_reminders.append({
                'reminder': r,
                'status': 'dismissed'
            })
        elif is_snoozed:
            inactive_reminders.append({
                'reminder': r,
                'status': 'snoozed',
                'snoozed_until_aware': snoozed_until_aware
            })
        else:
            active_reminders.append(r)

    return render_template('reminder/list_reminders.html', 
                           motorcycle=motorcycle, 
                           reminders=active_reminders,
                           inactive_reminders=inactive_reminders)
    # ▲▲▲【変更はここまで】▲▲▲

@reminder_bp.route('/add/for/<int:vehicle_id>', methods=['GET', 'POST'])
@limiter.limit("30 per hour")
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def add_reminder(vehicle_id):
    """リマインダー追加ページ"""
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=current_user.id).first_or_404()
    # ▲▲▲ 変更ここまで ▲▲▲
    form = ReminderForm()

    def get_maintenance_entries():
        if motorcycle.is_racer:
            return []
        return MaintenanceEntry.query.filter_by(motorcycle_id=motorcycle.id).order_by(MaintenanceEntry.maintenance_date.desc(), MaintenanceEntry.id.desc())
    
    form.maintenance_entry.query_factory = get_maintenance_entries

    if form.validate_on_submit():
        new_reminder = MaintenanceReminder(motorcycle_id=vehicle_id)
        
        new_reminder.task_description = form.task_description.data.strip() if form.task_description.data else None
        new_reminder.interval_km = form.interval_km.data
        new_reminder.interval_months = form.interval_months.data
        new_reminder.auto_update_from_category = form.auto_update_from_category.data

        selected_entry = form.maintenance_entry.data
        if selected_entry:
            new_reminder.last_maintenance_entry_id = selected_entry.id
            new_reminder.last_done_date = selected_entry.maintenance_date
            new_reminder.last_done_km = selected_entry.total_distance_at_maintenance
            new_reminder.last_done_odo = selected_entry.odometer_reading_at_maintenance
        else:
            new_reminder.last_maintenance_entry_id = None
            new_reminder.last_done_date = form.last_done_date.data
            new_reminder.last_done_odo = form.last_done_odo.data

            if new_reminder.last_done_odo is not None and new_reminder.last_done_date is not None:
                offset = motorcycle.calculate_cumulative_offset_from_logs(target_date=new_reminder.last_done_date)
                new_reminder.last_done_km = new_reminder.last_done_odo + offset
            else:
                new_reminder.last_done_km = None

        try:
            db.session.add(new_reminder)
            db.session.commit()
            flash(f'リマインダー「{new_reminder.task_description}」を追加しました。', 'success')
            return redirect(url_for('reminder.list_reminders', vehicle_id=vehicle_id))
        except Exception as e:
            db.session.rollback()
            flash(f'リマインダーの追加中にエラーが発生しました: {e}', 'danger')
            current_app.logger.error(f"Error adding reminder for vehicle {vehicle_id}: {e}", exc_info=True)
    elif request.method == 'POST':
        flash('入力内容にエラーがあります。ご確認ください。', 'danger')

    category_suggestions = [
        cat[0] for cat in db.session.query(MaintenanceEntry.category).filter(
            MaintenanceEntry.category.isnot(None),
            MaintenanceEntry.category != ''
        ).distinct().all()
    ]
    
    maintenance_entries_for_js = get_maintenance_entries()
    
    return render_template('reminder/reminder_form.html',
                           form=form,
                           form_action='add',
                           motorcycle=motorcycle,
                           category_suggestions=category_suggestions,
                           maintenance_entries_for_js=maintenance_entries_for_js)

@reminder_bp.route('/<int:reminder_id>/edit', methods=['GET', 'POST'])
@limiter.limit("30 per hour")
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def edit_reminder(reminder_id):
    """リマインダー編集ページ"""
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    reminder = MaintenanceReminder.query.join(Motorcycle).filter(
        MaintenanceReminder.id == reminder_id,
        Motorcycle.user_id == current_user.id
    ).first_or_404()
    # ▲▲▲ 変更ここまで ▲▲▲
    motorcycle = reminder.motorcycle
    form = ReminderForm(obj=reminder)

    def get_maintenance_entries():
        if motorcycle.is_racer:
            return []
        return MaintenanceEntry.query.filter_by(motorcycle_id=motorcycle.id).order_by(MaintenanceEntry.maintenance_date.desc(), MaintenanceEntry.id.desc())

    form.maintenance_entry.query_factory = get_maintenance_entries
    
    if request.method == 'GET':
        form.maintenance_entry.data = reminder.last_maintenance_entry
        form.last_done_odo.data = reminder.last_done_odo

    if form.validate_on_submit():
        reminder.task_description = form.task_description.data.strip() if form.task_description.data else None
        reminder.interval_km = form.interval_km.data
        reminder.interval_months = form.interval_months.data
        reminder.auto_update_from_category = form.auto_update_from_category.data

        selected_entry = form.maintenance_entry.data
        if selected_entry:
            reminder.last_maintenance_entry_id = selected_entry.id
            reminder.last_done_date = selected_entry.maintenance_date
            reminder.last_done_km = selected_entry.total_distance_at_maintenance
            reminder.last_done_odo = selected_entry.odometer_reading_at_maintenance
        else:
            reminder.last_maintenance_entry_id = None
            reminder.last_done_date = form.last_done_date.data
            reminder.last_done_odo = form.last_done_odo.data
            
            if reminder.last_done_odo is not None and reminder.last_done_date is not None:
                offset = motorcycle.calculate_cumulative_offset_from_logs(target_date=reminder.last_done_date)
                reminder.last_done_km = reminder.last_done_odo + offset
            else:
                reminder.last_done_km = None
            
        try:
            db.session.commit()
            flash(f'リマインダー「{reminder.task_description}」を更新しました。', 'success')
            return redirect(url_for('reminder.list_reminders', vehicle_id=motorcycle.id))
        except Exception as e:
            db.session.rollback()
            flash(f'リマインダーの更新中にエラーが発生しました: {e}', 'danger')
            current_app.logger.error(f"Error editing reminder {reminder_id}: {e}", exc_info=True)
    elif request.method == 'POST':
        flash('入力内容にエラーがあります。ご確認ください。', 'danger')

    category_suggestions = [
        cat[0] for cat in db.session.query(MaintenanceEntry.category).filter(
            MaintenanceEntry.category.isnot(None),
            MaintenanceEntry.category != ''
        ).distinct().all()
    ]

    maintenance_entries_for_js = get_maintenance_entries()

    return render_template('reminder/reminder_form.html',
                           form=form,
                           form_action='edit',
                           motorcycle=motorcycle,
                           reminder=reminder,
                           category_suggestions=category_suggestions,
                           maintenance_entries_for_js=maintenance_entries_for_js)

@reminder_bp.route('/<int:reminder_id>/delete', methods=['POST'])
@limiter.limit("30 per hour")
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def delete_reminder(reminder_id):
    """リマインダー削除処理"""
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    reminder = MaintenanceReminder.query.join(Motorcycle).filter(
        MaintenanceReminder.id == reminder_id,
        Motorcycle.user_id == current_user.id
    ).first_or_404()
    # ▲▲▲ 変更ここまで ▲▲▲
    vehicle_id = reminder.motorcycle_id
    task_name = reminder.task_description
    try:
        db.session.delete(reminder)
        db.session.commit()
        flash(f'リマインダー「{task_name}」を削除しました。', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'リマインダーの削除中にエラーが発生しました: {e}', 'danger')
        current_app.logger.error(f"Error deleting reminder {reminder_id}: {e}", exc_info=True)
    return redirect(url_for('reminder.list_reminders', vehicle_id=vehicle_id))


@reminder_bp.route('/<int:reminder_id>/snooze', methods=['POST'])
@limiter.limit("60 per minute")
@login_required
def snooze_reminder(reminder_id):
    """指定されたリマインダーを一定期間スヌーズする"""
    reminder = MaintenanceReminder.query.join(Motorcycle).filter(
        MaintenanceReminder.id == reminder_id,
        Motorcycle.user_id == current_user.id
    ).first_or_404()

    period = request.form.get('period')
    now = datetime.now(timezone.utc)
    snooze_until = None
    flash_msg = ''

    if period == '1_day':
        snooze_until = now + timedelta(days=1)
        flash_msg = '1日間'
    elif period == '1_week':
        snooze_until = now + timedelta(weeks=1)
        flash_msg = '1週間'
    elif period == '1_month':
        snooze_until = now + relativedelta(months=1)
        flash_msg = '1ヶ月間'
    else:
        flash('無効なスヌーズ期間です。', 'danger')
        return redirect(url_for('main.dashboard'))

    try:
        reminder.snoozed_until = snooze_until
        db.session.commit()
        flash(f'リマインダー「{reminder.task_description}」を{flash_msg}非表示にしました。', 'success')
    except Exception as e:
        db.session.rollback()
        flash('リマインダーのスヌーズ処理中にエラーが発生しました。', 'danger')
        current_app.logger.error(f"Error snoozing reminder {reminder_id}: {e}", exc_info=True)
        
    return redirect(request.referrer or url_for('main.dashboard'))


@reminder_bp.route('/<int:reminder_id>/dismiss', methods=['POST'])
@limiter.limit("60 per minute")
@login_required
def dismiss_reminder(reminder_id):
    """指定されたリマインダーを永続的に非表示にする"""
    reminder = MaintenanceReminder.query.join(Motorcycle).filter(
        MaintenanceReminder.id == reminder_id,
        Motorcycle.user_id == current_user.id
    ).first_or_404()
    
    try:
        reminder.is_dismissed = True
        db.session.commit()
        flash(f'リマインダー「{reminder.task_description}」を非表示にしました。', 'success')
    except Exception as e:
        db.session.rollback()
        flash('リマインダーの非表示処理中にエラーが発生しました。', 'danger')
        current_app.logger.error(f"Error dismissing reminder {reminder_id}: {e}", exc_info=True)
        
    return redirect(request.referrer or url_for('main.dashboard'))


# ▼▼▼【ここから追記】▼▼▼
@reminder_bp.route('/<int:reminder_id>/reactivate', methods=['POST'])
@limiter.limit("60 per minute")
@login_required
def reactivate_reminder(reminder_id):
    """非表示になっているリマインダーを再表示する"""
    reminder = MaintenanceReminder.query.join(Motorcycle).filter(
        MaintenanceReminder.id == reminder_id,
        Motorcycle.user_id == current_user.id
    ).first_or_404()
    
    try:
        reminder.is_dismissed = False
        reminder.snoozed_until = None
        db.session.commit()
        flash(f'リマインダー「{reminder.task_description}」を再表示しました。', 'success')
    except Exception as e:
        db.session.rollback()
        flash('リマインダーの再表示処理中にエラーが発生しました。', 'danger')
        current_app.logger.error(f"Error reactivating reminder {reminder_id}: {e}", exc_info=True)
        
    return redirect(url_for('reminder.list_reminders', vehicle_id=reminder.motorcycle_id))
# ▲▲▲【追記ここまで】▲▲▲