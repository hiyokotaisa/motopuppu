# motopuppu/views/notes.py
from flask import (
    Blueprint, flash, redirect, render_template, request, url_for, abort, current_app, jsonify
)
from datetime import date, timezone, datetime 
from sqlalchemy import or_
import json

# ▼▼▼ インポート文を修正 ▼▼▼
from flask_login import login_required, current_user
# ▲▲▲ 変更ここまで ▲▲▲
from ..models import db, Motorcycle, GeneralNote
from ..forms import NoteForm
from ..constants import NOTE_CATEGORIES, MAX_TODO_ITEMS
from ..achievement_evaluator import check_achievements_for_event, EVENT_ADD_NOTE
from .. import limiter


notes_bp = Blueprint('notes', __name__, url_prefix='/notes')

@notes_bp.route('/')
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def notes_log():
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('NOTES_PER_PAGE', 20)
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    user_motorcycles = Motorcycle.query.filter_by(user_id=current_user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    user_motorcycle_ids = [m.id for m in user_motorcycles]

    request_args_dict = {k: v for k, v in request.args.items() if k != 'page'}
    query = GeneralNote.query.filter_by(user_id=current_user.id)
    # ▲▲▲ 変更ここまで ▲▲▲

    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    vehicle_id_str = request.args.get('vehicle_id')
    keyword = request.args.get('q', '').strip()
    category_filter = request.args.get('category')

    try:
        if start_date_str: query = query.filter(GeneralNote.note_date >= date.fromisoformat(start_date_str))
        if end_date_str: query = query.filter(GeneralNote.note_date <= date.fromisoformat(end_date_str))
    except ValueError:
        flash('日付の形式が無効です。YYYY-MM-DD形式で入力してください。', 'warning')
        request_args_dict.pop('start_date', None); request_args_dict.pop('end_date', None)

    if vehicle_id_str:
        if vehicle_id_str == '0': query = query.filter(GeneralNote.motorcycle_id.is_(None))
        elif vehicle_id_str.isdigit():
            try:
                vehicle_id = int(vehicle_id_str)
                if vehicle_id in user_motorcycle_ids: query = query.filter(GeneralNote.motorcycle_id == vehicle_id)
                else: flash('選択された車両は有効ではありません。', 'warning'); request_args_dict.pop('vehicle_id', None)
            except ValueError: flash('車両フィルターの値が無効です。', 'warning'); request_args_dict.pop('vehicle_id', None)
        elif vehicle_id_str: flash('車両フィルターの値が無効です。', 'warning'); request_args_dict.pop('vehicle_id', None)

    if keyword:
        search_term = f'%{keyword}%'
        query = query.filter(or_(GeneralNote.title.ilike(search_term), GeneralNote.content.ilike(search_term)))

    allowed_category_values = [cat_val for cat_val, _ in NOTE_CATEGORIES]
    if category_filter and category_filter in allowed_category_values:
        query = query.filter(GeneralNote.category == category_filter)
    elif category_filter:
        flash('無効なカテゴリフィルターが指定されました。', 'warning'); request_args_dict.pop('category', None)

    pagination = query.order_by(GeneralNote.note_date.desc(), GeneralNote.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    entries = pagination.items
    
    is_filter_active = bool(request_args_dict)

    return render_template('notes_log.html',
                           entries=entries, pagination=pagination,
                           motorcycles=user_motorcycles, request_args=request_args_dict,
                           allowed_categories_for_template=[{'value': val, 'display': disp} for val, disp in NOTE_CATEGORIES],
                           selected_category=category_filter,
                           is_filter_active=is_filter_active)

@notes_bp.route('/add', methods=['GET', 'POST'])
@limiter.limit("30 per hour")
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def add_note():
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    user_motorcycles = Motorcycle.query.filter_by(user_id=current_user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    # ▲▲▲ 変更ここまで ▲▲▲
    form = NoteForm()
    form.motorcycle_id.choices = [(0, '-- 車両に紐付けない --')] + [(m.id, m.name) for m in user_motorcycles]

    if request.method == 'GET':
        default_vehicle = next((m for m in user_motorcycles if m.is_default), None)
        if default_vehicle: form.motorcycle_id.data = default_vehicle.id
        else: form.motorcycle_id.data = 0

        preselected_motorcycle_id = request.args.get('motorcycle_id', type=int)
        if preselected_motorcycle_id and any(m.id == preselected_motorcycle_id for m in user_motorcycles):
            form.motorcycle_id.data = preselected_motorcycle_id

    if form.validate_on_submit():
        # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
        new_note = GeneralNote(user_id=current_user.id)
        # ▲▲▲ 変更ここまで ▲▲▲
        selected_motorcycle_id = form.motorcycle_id.data
        new_note.motorcycle_id = selected_motorcycle_id if selected_motorcycle_id != 0 else None
        new_note.note_date = form.note_date.data
        new_note.category = form.category.data
        new_note.title = form.title.data.strip() if form.title.data else None

        if new_note.category == 'note':
            new_note.content = form.content.data.strip() if form.content.data else None
            new_note.todos = None
        elif new_note.category == 'task':
            new_note.content = '' 
            todos_data = []
            for item_form in form.todos:
                if item_form.text.data and item_form.text.data.strip(): 
                    todos_data.append({
                        'text': item_form.text.data.strip(),
                        'checked': item_form.checked.data
                    })
            new_note.todos = todos_data if todos_data else None 

        new_note.created_at = datetime.now(timezone.utc) 
        new_note.updated_at = datetime.now(timezone.utc) 
        
        try:
            db.session.add(new_note)
            db.session.commit() 
            flash('ノートを追加しました。', 'success')

            event_data_for_ach = {'new_note_id': new_note.id, 'category': new_note.category}
            # ▼▼▼ g.user を current_user に変更 ▼▼▼
            check_achievements_for_event(current_user, EVENT_ADD_NOTE, event_data=event_data_for_ach)
            # ▲▲▲ 変更ここまで ▲▲▲

            return redirect(url_for('notes.notes_log'))
        except Exception as e:
            db.session.rollback()
            # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
            flash(f'ノートの保存中にエラーが発生しました: {e}', 'error')
            current_app.logger.error(f"Error saving new general note for user {current_user.id}: {e}", exc_info=True)
            # ▲▲▲ 変更ここまで ▲▲▲

    elif request.method == 'POST': 
        form.motorcycle_id.choices = [(0, '-- 車両に紐付けない --')] + [(m.id, m.name) for m in user_motorcycles]

    return render_template('note_form.html',
                           form=form,
                           form_action='add',
                           motorcycles=user_motorcycles,
                           today_iso=date.today().isoformat(),
                           MAX_TODO_ITEMS=MAX_TODO_ITEMS,
                           note_id=None 
                           )

@notes_bp.route('/<int:note_id>/edit', methods=['GET', 'POST'])
@limiter.limit("30 per hour")
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def edit_note(note_id):
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    note = GeneralNote.query.filter_by(id=note_id, user_id=current_user.id).first_or_404()
    user_motorcycles = Motorcycle.query.filter_by(user_id=current_user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    # ▲▲▲ 変更ここまで ▲▲▲
    form = NoteForm(obj=note)
    form.motorcycle_id.choices = [(0, '-- 車両に紐付けない --')] + [(m.id, m.name) for m in user_motorcycles]

    if request.method == 'GET':
        form.motorcycle_id.data = note.motorcycle_id if note.motorcycle_id is not None else 0
        if note.category == 'task' and note.todos:
            num_entries_to_pop = len(form.todos.entries)
            for _ in range(num_entries_to_pop):
                if form.todos.entries: 
                    form.todos.pop_entry()

            for item_data in note.todos:
                if isinstance(item_data, dict) and item_data.get('text'): 
                    todo_item_form_entry = form.todos.append_entry()
                    todo_item_form_entry.text.data = item_data.get('text')
                    todo_item_form_entry.checked.data = item_data.get('checked', False)

    if form.validate_on_submit():
        selected_motorcycle_id = form.motorcycle_id.data
        note.motorcycle_id = selected_motorcycle_id if selected_motorcycle_id != 0 else None
        note.note_date = form.note_date.data
        note.category = form.category.data
        note.title = form.title.data.strip() if form.title.data else None

        if note.category == 'note':
            note.content = form.content.data.strip() if form.content.data else None
            note.todos = None
        elif note.category == 'task':
            note.content = '' 
            todos_data = []
            for item_data_from_form in form.todos.data:
                if item_data_from_form.get('text') and item_data_from_form['text'].strip(): 
                    todos_data.append({
                        'text': item_data_from_form['text'].strip(),
                        'checked': item_data_from_form.get('checked', False)
                    })
            note.todos = todos_data if todos_data else None 
        
        note.updated_at = datetime.now(timezone.utc) 
        
        try:
            db.session.commit()
            flash('ノートを更新しました。', 'success')
            return redirect(url_for('notes.notes_log'))
        except Exception as e:
            db.session.rollback()
            flash(f'ノートの更新中にエラーが発生しました: {e}', 'error')
            current_app.logger.error(f"Error updating general note ID {note_id}: {e}", exc_info=True)

    elif request.method == 'POST': 
        form.motorcycle_id.choices = [(0, '-- 車両に紐付けない --')] + [(m.id, m.name) for m in user_motorcycles]

    return render_template('note_form.html',
                           form=form,
                           form_action='edit',
                           note_id=note.id,
                           motorcycles=user_motorcycles,
                           today_iso=date.today().isoformat(),
                           MAX_TODO_ITEMS=MAX_TODO_ITEMS
                           )

@notes_bp.route('/<int:note_id>/delete', methods=['POST'])
@limiter.limit("30 per hour")
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def delete_note(note_id):
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    note = GeneralNote.query.filter_by(id=note_id, user_id=current_user.id).first_or_404()
    # ▲▲▲ 変更ここまで ▲▲▲
    try:
        db.session.delete(note)
        db.session.commit()
        flash('ノートを削除しました。', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'ノートの削除中にエラーが発生しました: {e}', 'error')
        current_app.logger.error(f"Error deleting general note ID {note_id}: {e}", exc_info=True)
    return redirect(url_for('notes.notes_log'))