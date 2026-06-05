# motopuppu/views/admin_schedule.py
import json
from datetime import date, datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required
from sqlalchemy import asc, desc
from sqlalchemy.exc import IntegrityError

from .. import db
from ..models import TrackSchedule
from ..forms import TrackScheduleForm, ScheduleImportForm, ScheduleImportConfirmForm
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


def _normalize_schedule_rows(data):
    """
    インポートされたJSONレコード配列を正規化・検証する。
    各行を文字列のまま保持しつつ、不正な値は破棄せず _warnings に積んでプレビューに残す。
    """
    rows = []
    for item in data:
        if not isinstance(item, dict):
            rows.append({
                'circuit_name': '', 'date': '', 'start_time': '', 'end_time': '',
                'title': '', 'notes': '',
                '_warnings': ['オブジェクト形式ではありません。'],
            })
            continue

        circuit_name = (str(item.get('circuit_name') or '')).strip()
        date_str = (str(item.get('date') or '')).strip()
        start_str = (str(item.get('start_time') or '')).strip()
        end_str = (str(item.get('end_time') or '')).strip()
        title = (str(item.get('title') or '')).strip()
        notes_raw = item.get('notes')
        notes = (str(notes_raw).strip() if notes_raw not in (None, '') else '')

        warnings = []

        # circuit_name 検証
        if not circuit_name:
            warnings.append('サーキット名が空です。')
        elif circuit_name not in CIRCUIT_METADATA:
            warnings.append('サーキット名が登録済みの選択肢と一致しません。')

        # date 検証
        if not date_str:
            warnings.append('日付が空です。')
        else:
            try:
                datetime.strptime(date_str, '%Y-%m-%d')
            except ValueError:
                warnings.append('日付の形式が不正です（YYYY-MM-DD）。')

        # 時刻検証 (任意項目だが、値があれば形式チェック)
        if start_str:
            try:
                datetime.strptime(start_str, '%H:%M')
            except ValueError:
                warnings.append('開始時刻の形式が不正です（HH:MM）。')
        if end_str:
            try:
                datetime.strptime(end_str, '%H:%M')
            except ValueError:
                warnings.append('終了時刻の形式が不正です（HH:MM）。')

        # title 検証
        if not title:
            warnings.append('走行枠名が空です。')
        elif len(title) > 100:
            warnings.append('走行枠名が100文字を超えています。')

        if len(notes) > 200:
            warnings.append('補足が200文字を超えています。')

        rows.append({
            'circuit_name': circuit_name,
            'date': date_str,
            'start_time': start_str,
            'end_time': end_str,
            'title': title,
            'notes': notes,
            '_warnings': warnings,
        })
    return rows


@admin_schedule_bp.route('/import', methods=['GET', 'POST'])
@login_required
@admin_required
def import_schedules():
    form = ScheduleImportForm()

    if form.validate_on_submit():
        # json_file を優先、無ければ json_text
        raw_text = None
        if form.json_file.data:
            try:
                raw_text = form.json_file.data.read().decode('utf-8')
            except UnicodeDecodeError:
                flash('JSONファイルの文字コードを読み取れませんでした（UTF-8で保存してください）。', 'danger')
                return render_template('admin/schedule_import.html', form=form)
        else:
            raw_text = form.json_text.data

        try:
            data = json.loads(raw_text)
        except (TypeError, ValueError) as e:
            flash(f'JSONの解析に失敗しました: {e}', 'danger')
            return render_template('admin/schedule_import.html', form=form)

        if not isinstance(data, list):
            flash('JSONはレコードの配列（[...]）形式で指定してください。', 'danger')
            return render_template('admin/schedule_import.html', form=form)

        if not data:
            flash('JSONにレコードが含まれていません。', 'warning')
            return render_template('admin/schedule_import.html', form=form)

        rows = _normalize_schedule_rows(data)
        warning_count = sum(1 for r in rows if r['_warnings'])

        confirm_form = ScheduleImportConfirmForm()
        confirm_form.payload.data = json.dumps(rows, ensure_ascii=False)
        confirm_form.source_url.data = (form.source_url.data or '').strip()

        return render_template(
            'admin/schedule_import_preview.html',
            rows=rows,
            warning_count=warning_count,
            confirm_form=confirm_form
        )

    return render_template('admin/schedule_import.html', form=form)


@admin_schedule_bp.route('/import/confirm', methods=['POST'])
@login_required
@admin_required
def import_schedules_confirm():
    confirm_form = ScheduleImportConfirmForm()
    if not confirm_form.validate_on_submit():
        flash('セッションが無効です。お手数ですが最初からやり直してください。', 'danger')
        return redirect(url_for('admin_schedule.import_schedules'))

    try:
        rows = json.loads(confirm_form.payload.data)
    except (TypeError, ValueError):
        flash('プレビューデータの読み込みに失敗しました。やり直してください。', 'danger')
        return redirect(url_for('admin_schedule.import_schedules'))

    source_url = (confirm_form.source_url.data or '').strip() or None

    created, skipped, error_count = 0, 0, 0

    for row in rows:
        try:
            circuit = (row.get('circuit_name') or '').strip()
            title = (row.get('title') or '').strip()
            d = datetime.strptime(row['date'], '%Y-%m-%d').date()
            start_str = (row.get('start_time') or '').strip()
            end_str = (row.get('end_time') or '').strip()
            st = datetime.strptime(start_str, '%H:%M').time() if start_str else None
            et = datetime.strptime(end_str, '%H:%M').time() if end_str else None
            notes = (row.get('notes') or '').strip() or None
            if not circuit or not title:
                raise ValueError('circuit_name / title が空です。')
        except (KeyError, ValueError, TypeError):
            error_count += 1
            continue

        # 重複チェック (ユニーク制約キー: circuit_name, date, start_time, title)
        exists = TrackSchedule.query.filter_by(
            circuit_name=circuit, date=d, start_time=st, title=title
        ).first()
        if exists:
            skipped += 1
            continue

        db.session.add(TrackSchedule(
            circuit_name=circuit,
            date=d,
            start_time=st,
            end_time=et,
            title=title,
            notes=notes,
            source_url=source_url,
        ))
        created += 1

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash('一括登録中に重複エラーが発生しました。お手数ですがやり直してください。', 'danger')
        return redirect(url_for('admin_schedule.import_schedules'))
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error bulk-importing TrackSchedule: {e}")
        flash('一括登録中にエラーが発生しました。', 'danger')
        return redirect(url_for('admin_schedule.import_schedules'))

    msg = f'{created}件の走行枠を登録しました。（重複スキップ {skipped}件）'
    if error_count:
        msg += f' / 形式エラーで {error_count}件をスキップしました。'
    flash(msg, 'success')
    return redirect(url_for('admin_schedule.list_schedules'))
