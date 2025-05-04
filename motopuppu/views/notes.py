# motopuppu/views/notes.py
from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, abort, current_app, jsonify
)
from datetime import date
from sqlalchemy import or_
import json # JSON処理のためにインポート

# 認証ヘルパーとモデルをインポート
from .auth import login_required_custom, get_current_user
from ..models import db, Motorcycle, GeneralNote

# Blueprint名は 'notes' のまま
notes_bp = Blueprint('notes', __name__, url_prefix='/notes')

# --- 定数 ---
MAX_TODO_ITEMS = 50
ALLOWED_CATEGORIES = ['note', 'task']


# --- メモ一覧 (変更なし) ---
@notes_bp.route('/')
@login_required_custom
def notes_log():
    """一般ノートの一覧を表示 (フィルター機能付き)"""
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('NOTES_PER_PAGE', 20)
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    user_motorcycle_ids = [m.id for m in user_motorcycles]

    start_date_str = request.args.get('start_date'); end_date_str = request.args.get('end_date')
    vehicle_id_str = request.args.get('vehicle_id'); keyword = request.args.get('q', '').strip()
    category_filter = request.args.get('category')
    request_args_dict = request.args.to_dict()

    query = GeneralNote.query.filter_by(user_id=g.user.id)

    # 日付フィルター
    try:
        if start_date_str: query = query.filter(GeneralNote.note_date >= date.fromisoformat(start_date_str))
        else: request_args_dict.pop('start_date', None)
        if end_date_str: query = query.filter(GeneralNote.note_date <= date.fromisoformat(end_date_str))
        else: request_args_dict.pop('end_date', None)
    except ValueError: flash('日付の形式が無効です。YYYY-MM-DD形式で入力してください。', 'warning'); request_args_dict.pop('start_date', None); request_args_dict.pop('end_date', None)

    # 車両フィルター
    if vehicle_id_str:
        if vehicle_id_str.lower() == 'none': query = query.filter(GeneralNote.motorcycle_id == None)
        else:
            try:
                vehicle_id = int(vehicle_id_str)
                if vehicle_id in user_motorcycle_ids: query = query.filter(GeneralNote.motorcycle_id == vehicle_id)
                else: flash('選択された車両は有効ではありません。', 'warning'); request_args_dict.pop('vehicle_id', None)
            except ValueError: request_args_dict.pop('vehicle_id', None)
    else: request_args_dict.pop('vehicle_id', None)

    # キーワードフィルター
    if keyword: query = query.filter(or_(GeneralNote.title.ilike(f'%{keyword}%'), GeneralNote.content.ilike(f'%{keyword}%')))
    else: request_args_dict.pop('q', None)

    # カテゴリーフィルター処理
    if category_filter and category_filter in ALLOWED_CATEGORIES:
        query = query.filter(GeneralNote.category == category_filter)
    elif category_filter:
        request_args_dict.pop('category', None)
    else:
        request_args_dict.pop('category', None)

    pagination = query.order_by(GeneralNote.note_date.desc(), GeneralNote.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    entries = pagination.items

    return render_template('notes_log.html',
                           entries=entries,
                           pagination=pagination,
                           motorcycles=user_motorcycles,
                           request_args=request_args_dict,
                           allowed_categories=ALLOWED_CATEGORIES,
                           selected_category=category_filter)


# --- ヘルパー関数: TODOリスト処理 ---
def process_todo_list(request_form):
    """
    フォームデータからTODOリストを処理し、整形・バリデーションする。
    note_form.html側の修正により、'todo_checked[]'には各アイテムに対応する
    'true'または'false'の文字列が送信される想定。
    """
    todos_data = []
    todo_texts = request_form.getlist('todo_text[]')
    todo_checked_values = request_form.getlist('todo_checked[]') # 'true' or 'false' list

    num_items = len(todo_texts)

    # 長さチェック（念のため）
    if len(todo_checked_values) != num_items:
        return None, ["TODOリストのテキストとチェック状態の数が一致しません。フォームの送信データを確認してください。"]

    if num_items > MAX_TODO_ITEMS:
        return None, [f"TODOアイテムは最大{MAX_TODO_ITEMS}個までです。"]

    errors = []
    for i in range(num_items):
        text = todo_texts[i].strip()
        # 'true' 文字列であれば True、それ以外（'false'）であれば False
        is_checked = todo_checked_values[i] == 'true'

        # テキストのバリデーション
        if not text:
            errors.append(f"{i+1}番目のTODOアイテムの内容が空です。")
            # continue
        elif len(text) > 100:
             errors.append(f"{i+1}番目のTODOアイテムの内容が長すぎます（100文字以内）。")
             # continue

        todos_data.append({"text": text, "checked": is_checked})

    if errors:
        # エラーがあれば None とエラーリストを返す
        return None, errors

    # エラーがなく、アイテムが存在する場合のみデータを返す
    return todos_data if todos_data else None, []


# --- メモ追加 ---
@notes_bp.route('/add', methods=['GET', 'POST'])
@login_required_custom
def add_note():
    """新しい一般ノートを追加"""
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    if request.method == 'POST':
        motorcycle_id_str = request.form.get('motorcycle_id')
        note_date_str = request.form.get('note_date')
        category = request.form.get('category')
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()

        note_date = None
        motorcycle_id = None
        todos_data = None
        form_errors = []

        # 基本フィールドのバリデーション
        if not content: form_errors.append('ノート内容は必須です。')
        elif len(content) > 2000: form_errors.append('ノート内容は2000文字以内で入力してください。')
        if title and len(title) > 150: form_errors.append('タイトルは150文字以内で入力してください。')
        if note_date_str:
            try: note_date = date.fromisoformat(note_date_str)
            except ValueError: form_errors.append('有効な日付形式 (YYYY-MM-DD) で入力してください。')
        else: form_errors.append('日付は必須です。')
        if motorcycle_id_str:
             try:
                 motorcycle_id = int(motorcycle_id_str)
                 if not any(m.id == motorcycle_id for m in user_motorcycles): form_errors.append('有効な車両を選択してください。')
             except ValueError: form_errors.append('車両の選択が無効です。')
        else: motorcycle_id = None

        # カテゴリーとTODOリストのバリデーション/処理
        if not category or category not in ALLOWED_CATEGORIES:
            form_errors.append('有効なカテゴリーを選択してください。')
        elif category == 'task':
            todos_data, todo_errors = process_todo_list(request.form)
            if todo_errors:
                form_errors.extend(todo_errors)
            # --- ▼▼▼ TODOリスト必須チェック ▼▼▼ ---
            elif not todos_data: # エラーがなく、かつアイテム数が0の場合
                form_errors.append('タスクカテゴリの場合、TODOアイテムを1つ以上入力してください。')
            # --- ▲▲▲ TODOリスト必須チェックここまで ▲▲▲ ---
        # カテゴリが 'note' の場合、todos は None (明示的に設定しても良い)
        # elif category == 'note':
        #    todos_data = None

        # エラーがあればフォーム再表示
        if form_errors:
            for msg in form_errors:
                flash(msg, 'danger')
            entry_data = request.form.to_dict()
            entry_data['todos'] = None # TODO復元は省略
            return render_template('note_form.html', form_action='add', entry=entry_data, motorcycles=user_motorcycles, today_iso=date.today().isoformat())

        # エラーがなければDB保存
        else:
            new_note = GeneralNote(
                user_id=g.user.id,
                motorcycle_id=motorcycle_id,
                note_date=note_date,
                title=title if title else None,
                content=content, # カテゴリがtaskでもcontentは保存される（非表示なだけ）
                category=category,
                todos=todos_data
            )
            try:
                db.session.add(new_note)
                db.session.commit()
                flash('ノートを追加しました。', 'success')
                return redirect(url_for('notes.notes_log'))
            except Exception as e:
                db.session.rollback()
                flash(f'ノートの保存中にエラーが発生しました: {e}', 'error')
                current_app.logger.error(f"Error saving general note: {e}")
                entry_data = request.form.to_dict()
                entry_data['todos'] = None
                return render_template('note_form.html', form_action='add', entry=entry_data, motorcycles=user_motorcycles, today_iso=date.today().isoformat())
    else: # GET
        today_iso_str = date.today().isoformat()
        preselected_motorcycle_id = request.args.get('motorcycle_id', type=int)
        if preselected_motorcycle_id:
             is_owner = any(m.id == preselected_motorcycle_id for m in user_motorcycles)
             if not is_owner: preselected_motorcycle_id = None
        return render_template('note_form.html', form_action='add', entry=None, motorcycles=user_motorcycles, today_iso=today_iso_str, preselected_motorcycle_id=preselected_motorcycle_id)


# --- メモ編集 ---
@notes_bp.route('/<int:note_id>/edit', methods=['GET', 'POST'])
@login_required_custom
def edit_note(note_id):
    """既存の一般ノートを編集"""
    note = GeneralNote.query.filter_by(id=note_id, user_id=g.user.id).first_or_404()
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()

    if request.method == 'POST':
        motorcycle_id_str = request.form.get('motorcycle_id')
        note_date_str = request.form.get('note_date')
        category = request.form.get('category')
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()

        note_date = None
        motorcycle_id = None
        todos_data = None
        form_errors = []

        # 基本フィールドのバリデーション
        if not content: form_errors.append('ノート内容は必須です。')
        elif len(content) > 2000: form_errors.append('ノート内容は2000文字以内で入力してください。')
        if title and len(title) > 150: form_errors.append('タイトルは150文字以内で入力してください。')
        if note_date_str:
            try: note_date = date.fromisoformat(note_date_str)
            except ValueError: form_errors.append('有効な日付形式 (YYYY-MM-DD) で入力してください。')
        else: form_errors.append('日付は必須です。')
        if motorcycle_id_str:
             try:
                 motorcycle_id = int(motorcycle_id_str)
                 if not any(m.id == motorcycle_id for m in user_motorcycles): form_errors.append('有効な車両を選択してください。')
             except ValueError: form_errors.append('車両の選択が無効です。')
        else: motorcycle_id = None

        # カテゴリーとTODOリストのバリデーション/処理
        if not category or category not in ALLOWED_CATEGORIES:
            form_errors.append('有効なカテゴリーを選択してください。')
        elif category == 'task':
            todos_data, todo_errors = process_todo_list(request.form)
            if todo_errors:
                form_errors.extend(todo_errors)
            # --- ▼▼▼ TODOリスト必須チェック ▼▼▼ ---
            elif not todos_data: # エラーがなく、かつアイテム数が0の場合
                 form_errors.append('タスクカテゴリの場合、TODOアイテムを1つ以上入力してください。')
            # --- ▲▲▲ TODOリスト必須チェックここまで ▲▲▲ ---
        elif category == 'note':
             # カテゴリが 'note' に変更された場合、todos は None にする
             todos_data = None

        # エラーがあればフォーム再表示
        if form_errors:
            for msg in form_errors:
                flash(msg, 'danger')
            # 編集中のノート `note` をそのままテンプレートに渡す
            # (フォーム入力値の復元が必要な場合は entry_data を使う)
            return render_template('note_form.html', form_action='edit', entry=note, motorcycles=user_motorcycles, today_iso=date.today().isoformat())

        # エラーがなければDB更新
        else:
            try:
                note.motorcycle_id = motorcycle_id
                note.note_date = note_date
                note.title = title if title else None
                note.content = content # カテゴリがtaskでもcontentは保存される
                note.category = category
                note.todos = todos_data
                db.session.commit()
                flash('ノートを更新しました。', 'success')
                return redirect(url_for('notes.notes_log'))
            except Exception as e:
                db.session.rollback()
                flash(f'ノートの更新中にエラーが発生しました: {e}', 'error')
                current_app.logger.error(f"Error updating general note {note_id}: {e}")
                return render_template('note_form.html', form_action='edit', entry=note, motorcycles=user_motorcycles, today_iso=date.today().isoformat())
    else: # GET
        return render_template('note_form.html', form_action='edit', entry=note, motorcycles=user_motorcycles, today_iso=date.today().isoformat())


# --- メモ削除 (変更なし) ---
@notes_bp.route('/<int:note_id>/delete', methods=['POST'])
@login_required_custom
def delete_note(note_id):
    """一般ノートを削除"""
    note = GeneralNote.query.filter_by(id=note_id, user_id=g.user.id).first_or_404()
    try:
        db.session.delete(note)
        db.session.commit()
        flash('ノートを削除しました。', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'ノートの削除中にエラーが発生しました: {e}', 'error')
        current_app.logger.error(f"Error deleting general note {note_id}: {e}")
    return redirect(url_for('notes.notes_log'))