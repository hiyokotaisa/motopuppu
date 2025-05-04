# motopuppu/views/notes.py
from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, abort, current_app
)
from datetime import date
from sqlalchemy import or_ # For keyword search

# 認証ヘルパーとモデルをインポート
from .auth import login_required_custom, get_current_user
from ..models import db, Motorcycle, GeneralNote # Import GeneralNote

# Blueprint名は 'notes' のまま
notes_bp = Blueprint('notes', __name__, url_prefix='/notes')

# --- メモ一覧 (フィルター機能強化) ---
@notes_bp.route('/')
@login_required_custom
def notes_log(): # 関数名も 'notes_log' のまま
    """一般ノートの一覧を表示 (フィルター機能付き)""" # docstringは変更
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('NOTES_PER_PAGE', 20)
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    user_motorcycle_ids = [m.id for m in user_motorcycles]

    start_date_str = request.args.get('start_date'); end_date_str = request.args.get('end_date')
    vehicle_id_str = request.args.get('vehicle_id'); keyword = request.args.get('q', '').strip()
    request_args_dict = request.args.to_dict()

    query = GeneralNote.query.filter_by(user_id=g.user.id)

    # (フィルターロジックは変更なし)
    try:
        if start_date_str: query = query.filter(GeneralNote.note_date >= date.fromisoformat(start_date_str))
        else: request_args_dict.pop('start_date', None)
        if end_date_str: query = query.filter(GeneralNote.note_date <= date.fromisoformat(end_date_str))
        else: request_args_dict.pop('end_date', None)
    except ValueError: flash('日付の形式が無効です。YYYY-MM-DD形式で入力してください。', 'warning'); request_args_dict.pop('start_date', None); request_args_dict.pop('end_date', None)
    if vehicle_id_str:
        if vehicle_id_str.lower() == 'none': query = query.filter(GeneralNote.motorcycle_id == None)
        else:
            try:
                vehicle_id = int(vehicle_id_str)
                if vehicle_id in user_motorcycle_ids: query = query.filter(GeneralNote.motorcycle_id == vehicle_id)
                else: flash('選択された車両は有効ではありません。', 'warning'); request_args_dict.pop('vehicle_id', None)
            except ValueError: request_args_dict.pop('vehicle_id', None)
    else: request_args_dict.pop('vehicle_id', None)
    if keyword: query = query.filter(or_(GeneralNote.title.ilike(f'%{keyword}%'), GeneralNote.content.ilike(f'%{keyword}%')))
    else: request_args_dict.pop('q', None)

    pagination = query.order_by(GeneralNote.note_date.desc(), GeneralNote.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    entries = pagination.items

    return render_template('notes_log.html', # テンプレート名は元のまま
                           entries=entries,
                           pagination=pagination,
                           motorcycles=user_motorcycles,
                           request_args=request_args_dict)

# --- メモ追加 ---
@notes_bp.route('/add', methods=['GET', 'POST'])
@login_required_custom
def add_note():
    """新しい一般ノートを追加""" # docstring変更
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    if request.method == 'POST':
        motorcycle_id_str = request.form.get('motorcycle_id'); note_date_str = request.form.get('note_date')
        title = request.form.get('title', '').strip(); content = request.form.get('content', '').strip()
        errors = {}; note_date = None; motorcycle_id = None
        # ▼▼▼ Flashメッセージ用に修正 ▼▼▼
        if not content: errors['content'] = 'ノート内容は必須です。'
        elif len(content) > 2000: errors['content'] = 'ノート内容は2000文字以内で入力してください。'
        # ▲▲▲ 修正ここまで ▲▲▲
        if title and len(title) > 150: errors['title'] = 'タイトルは150文字以内で入力してください。'
        if note_date_str:
            try: note_date = date.fromisoformat(note_date_str)
            except ValueError: errors['note_date'] = '有効な日付形式 (YYYY-MM-DD) で入力してください。'
        else: errors['note_date'] = '日付は必須です。'
        if motorcycle_id_str:
             try:
                 motorcycle_id = int(motorcycle_id_str)
                 if not any(m.id == motorcycle_id for m in user_motorcycles): errors['motorcycle_id'] = '有効な車両を選択してください。'
             except ValueError: errors['motorcycle_id'] = '車両の選択が無効です。'
        else: motorcycle_id = None
        if errors:
            for field, msg in errors.items(): flash(msg, 'danger')
            entry_data = request.form.to_dict()
            return render_template('note_form.html', form_action='add', entry=entry_data, motorcycles=user_motorcycles, today_iso=date.today().isoformat())
        else:
            new_note = GeneralNote( user_id=g.user.id, motorcycle_id=motorcycle_id, note_date=note_date, title=title if title else None, content=content )
            try:
                db.session.add(new_note); db.session.commit()
                # ▼▼▼ Flashメッセージ修正 ▼▼▼
                flash('ノートを追加しました。', 'success')
                # ▲▲▲ 修正ここまで ▲▲▲
                return redirect(url_for('notes.notes_log')) # url_for は元のまま
            except Exception as e:
                db.session.rollback();
                # ▼▼▼ Flashメッセージ修正 ▼▼▼
                flash(f'ノートの保存中にエラーが発生しました: {e}', 'error')
                # ▲▲▲ 修正ここまで ▲▲▲
                current_app.logger.error(f"Error saving general note: {e}")
                entry_data = request.form.to_dict()
                return render_template('note_form.html', form_action='add', entry=entry_data, motorcycles=user_motorcycles, today_iso=date.today().isoformat())
    else: # GET
        today_iso_str = date.today().isoformat(); preselected_motorcycle_id = request.args.get('motorcycle_id', type=int)
        if preselected_motorcycle_id:
             is_owner = any(m.id == preselected_motorcycle_id for m in user_motorcycles)
             if not is_owner: preselected_motorcycle_id = None
        return render_template('note_form.html', form_action='add', entry=None, motorcycles=user_motorcycles, today_iso=today_iso_str, preselected_motorcycle_id=preselected_motorcycle_id)


# --- メモ編集 ---
@notes_bp.route('/<int:note_id>/edit', methods=['GET', 'POST'])
@login_required_custom
def edit_note(note_id):
    """既存の一般ノートを編集""" # docstring変更
    note = GeneralNote.query.filter_by(id=note_id, user_id=g.user.id).first_or_404()
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    if request.method == 'POST':
        motorcycle_id_str = request.form.get('motorcycle_id'); note_date_str = request.form.get('note_date')
        title = request.form.get('title', '').strip(); content = request.form.get('content', '').strip()
        errors = {}; note_date = None; motorcycle_id = None
        # ▼▼▼ Flashメッセージ用に修正 ▼▼▼
        if not content: errors['content'] = 'ノート内容は必須です。'
        elif len(content) > 2000: errors['content'] = 'ノート内容は2000文字以内で入力してください。'
        # ▲▲▲ 修正ここまで ▲▲▲
        if title and len(title) > 150: errors['title'] = 'タイトルは150文字以内で入力してください。'
        if note_date_str:
            try: note_date = date.fromisoformat(note_date_str)
            except ValueError: errors['note_date'] = '有効な日付形式 (YYYY-MM-DD) で入力してください。'
        else: errors['note_date'] = '日付は必須です。'
        if motorcycle_id_str:
             try:
                 motorcycle_id = int(motorcycle_id_str)
                 if not any(m.id == motorcycle_id for m in user_motorcycles): errors['motorcycle_id'] = '有効な車両を選択してください。'
             except ValueError: errors['motorcycle_id'] = '車両の選択が無効です。'
        else: motorcycle_id = None
        if errors:
            for field, msg in errors.items(): flash(msg, 'danger')
            return render_template('note_form.html', form_action='edit', entry=note, motorcycles=user_motorcycles, today_iso=date.today().isoformat())
        else:
            try:
                note.motorcycle_id = motorcycle_id; note.note_date = note_date
                note.title = title if title else None; note.content = content
                db.session.commit()
                 # ▼▼▼ Flashメッセージ修正 ▼▼▼
                flash('ノートを更新しました。', 'success')
                 # ▲▲▲ 修正ここまで ▲▲▲
                return redirect(url_for('notes.notes_log')) # url_for は元のまま
            except Exception as e:
                db.session.rollback();
                # ▼▼▼ Flashメッセージ修正 ▼▼▼
                flash(f'ノートの更新中にエラーが発生しました: {e}', 'error')
                # ▲▲▲ 修正ここまで ▲▲▲
                current_app.logger.error(f"Error updating general note {note_id}: {e}")
                return render_template('note_form.html', form_action='edit', entry=note, motorcycles=user_motorcycles, today_iso=date.today().isoformat())
    else: # GET
        return render_template('note_form.html', form_action='edit', entry=note, motorcycles=user_motorcycles, today_iso=date.today().isoformat())


# --- メモ削除 ---
@notes_bp.route('/<int:note_id>/delete', methods=['POST'])
@login_required_custom
def delete_note(note_id):
    """一般ノートを削除""" # docstring変更
    note = GeneralNote.query.filter_by(id=note_id, user_id=g.user.id).first_or_404()
    try:
        db.session.delete(note); db.session.commit()
        # ▼▼▼ Flashメッセージ修正 ▼▼▼
        flash('ノートを削除しました。', 'success')
        # ▲▲▲ 修正ここまで ▲▲▲
    except Exception as e:
        db.session.rollback();
        # ▼▼▼ Flashメッセージ修正 ▼▼▼
        flash(f'ノートの削除中にエラーが発生しました: {e}', 'error')
        # ▲▲▲ 修正ここまで ▲▲▲
        current_app.logger.error(f"Error deleting general note {note_id}: {e}")
    return redirect(url_for('notes.notes_log')) # url_for は元のまま