# motopuppu/views/admin_schedule.py
from datetime import date
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required
from sqlalchemy import asc, desc

from .. import db
from ..models import TrackSchedule
from ..forms import TrackScheduleForm
from ..constants import CIRCUIT_METADATA
from .auth import admin_required

admin_schedule_bp = Blueprint(
    'admin_schedule',
    __name__,
    url_prefix='/admin/track-schedules'
)


@admin_schedule_bp.route('/')
@login_required
@admin_required
def list_schedules():
    circuit_filter = request.args.get('circuit_name', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 30

    query = TrackSchedule.query

    if circuit_filter:
        query = query.filter(TrackSchedule.circuit_name == circuit_filter)

    query = query.order_by(
        desc(TrackSchedule.date),
        asc(TrackSchedule.start_time),
        asc(TrackSchedule.id)
    )

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    entries = pagination.items

    circuit_choices = list(CIRCUIT_METADATA.keys())

    return render_template(
        'admin/track_schedule_list.html',
        entries=entries,
        pagination=pagination,
        circuit_choices=circuit_choices,
        current_circuit=circuit_filter
    )


@admin_schedule_bp.route('/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_schedule():
    form = TrackScheduleForm()

    if request.method == 'GET':
        prefilled_circuit = request.args.get('circuit_name')
        if prefilled_circuit and prefilled_circuit in CIRCUIT_METADATA:
            form.circuit_name.data = prefilled_circuit

    if form.validate_on_submit():
        entry = TrackSchedule(
            circuit_name=form.circuit_name.data,
            date=form.date.data,
            start_time=form.start_time.data,
            end_time=form.end_time.data,
            title=form.title.data.strip(),
            notes=form.notes.data.strip() if form.notes.data else None,
            source_url=form.source_url.data.strip() if form.source_url.data else None,
        )
        db.session.add(entry)
        try:
            db.session.commit()
            flash('走行枠を登録しました。', 'success')
            return redirect(url_for('admin_schedule.list_schedules', circuit_name=entry.circuit_name))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating TrackSchedule: {e}")
            flash('登録中にエラーが発生しました。同一の走行枠が既に登録されていないかご確認ください。', 'danger')

    return render_template('admin/track_schedule_form.html', form=form, form_action='add')


@admin_schedule_bp.route('/<int:entry_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_schedule(entry_id):
    entry = TrackSchedule.query.get_or_404(entry_id)
    form = TrackScheduleForm(obj=entry)

    if form.validate_on_submit():
        entry.circuit_name = form.circuit_name.data
        entry.date = form.date.data
        entry.start_time = form.start_time.data
        entry.end_time = form.end_time.data
        entry.title = form.title.data.strip()
        entry.notes = form.notes.data.strip() if form.notes.data else None
        entry.source_url = form.source_url.data.strip() if form.source_url.data else None
        try:
            db.session.commit()
            flash('走行枠を更新しました。', 'success')
            return redirect(url_for('admin_schedule.list_schedules', circuit_name=entry.circuit_name))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating TrackSchedule {entry_id}: {e}")
            flash('更新中にエラーが発生しました。', 'danger')

    return render_template('admin/track_schedule_form.html', form=form, form_action='edit', entry=entry)


@admin_schedule_bp.route('/<int:entry_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_schedule(entry_id):
    entry = TrackSchedule.query.get_or_404(entry_id)
    circuit_name = entry.circuit_name
    try:
        db.session.delete(entry)
        db.session.commit()
        flash('走行枠を削除しました。', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting TrackSchedule {entry_id}: {e}")
        flash('削除中にエラーが発生しました。', 'danger')

    return redirect(url_for('admin_schedule.list_schedules', circuit_name=circuit_name))
