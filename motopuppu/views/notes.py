# motopuppu/views/notes.py
from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, abort, current_app
)
from datetime import date
from sqlalchemy import or_ # For keyword search

# 認証ヘルパーとモデルをインポート
from .auth import login_required_custom, get_current_user
from ..models import db, Motorcycle, GeneralNote # Import GeneralNote

notes_bp = Blueprint('notes', __name__, url_prefix='/notes')

# --- メモ一覧 (フィルター機能強化) ---
@notes_bp.route('/')
@login_required_custom
def notes_log():
    """一般メモの一覧を表示 (フィルター機能付き)"""
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('NOTES_PER_PAGE', 20)
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    user_motorcycle_ids = [m.id for m in user_motorcycles] # フィルターでの所有権チェック用

    # --- フィルター条件の取得 ---
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    vehicle_id_str = request.args.get('vehicle_id') # '', 'none', or '<id>'
    keyword = request.args.get('q', '').strip()
    request_args_dict = request.args.to_dict() # For repopulating form

    # ベースクエリ: ログインユーザーのメモのみ
    query = GeneralNote.query.filter_by(user_id=g.user.id)

    # --- フィルター適用 ---
    try:
        if start_date_str:
            start_date = date.fromisoformat(start_date_str)
            query = query.filter(GeneralNote.note_date >= start_date)
        else: request_args_dict.pop('start_date', None) # なければ辞書からも削除
        if end_date_str:
            end_date = date.fromisoformat(end_date_str)
            query = query.filter(GeneralNote.note_date <= end_date)
        else: request_args_dict.pop('end_date', None)
    except ValueError:
        flash('日付の形式が無効です。YYYY-MM-DD形式で入力してください。', 'warning')
        request_args_dict.pop('start_date', None); request_args_dict.pop('end_date', None)

    # 車両フィルター
    if vehicle_id_str:
        if vehicle_id_str.lower() == 'none':
            # 「車両未指定」が選択された場合
            query = query.filter(GeneralNote.motorcycle_id == None)
        else:
            # 特定の車両IDが選択された場合
            try:
                vehicle_id = int(vehicle_id_str)
                # ユーザー所有の車両IDかチェック
                if vehicle_id in user_motorcycle_ids:
                    query = query.filter(GeneralNote.motorcycle_id == vehicle_id)
                else:
                    flash('選択された車両は有効ではありません。', 'warning')
                    request_args_dict.pop('vehicle_id', None) # 選択をリセット
            except ValueError:
                 request_args_dict.pop('vehicle_id', None) # 不正なIDの場合もリセット
    else:
        # vehicle_id パラメータがなければ辞書からも削除 (リセットボタン用)
        request_args_dict.pop('vehicle_id', None)

    # キーワードフィルター (タイトルと内容を検索)
    if keyword:
        search_term = f'%{keyword}%'
        query = query.filter(
            or_(
                GeneralNote.title.ilike(search_term),
                GeneralNote.content.ilike(search_term)
            )
        )
    else:
        request_args_dict.pop('q', None) # キーワードがなければクリア

    # --- ページネーション ---
    pagination = query.order_by(
        GeneralNote.note_date.desc(), GeneralNote.created_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)
    entries = pagination.items

    return render_template('notes_log.html',
                           entries=entries,
                           pagination=pagination,
                           motorcycles=user_motorcycles, # フィルタードロップダウン用
                           request_args=request_args_dict) # フィルターフォームの値維持用

# --- メモ追加 (変更なし) ---
@notes_bp.route('/add', methods=['GET', 'POST'])
@login_required_custom
def add_note():
    """新しい一般メモを追加"""
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    if request.method == 'POST':
        motorcycle_id_str = request.form.get('motorcycle_id'); note_date_str = request.form.get('note_date')
        title = request.form.get('title', '').strip(); content = request.form.get('content', '').strip()
        errors = {}; note_date = None; motorcycle_id = None
        if not content: errors['content'] = 'メモ内容は必須です。'
        elif len(content) > 2000: errors['content'] = 'メモ内容は2000文字以内で入力してください。'
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
                flash('メモを追加しました。', 'success')
                return redirect(url_for('notes.notes_log'))
            except Exception as e:
                db.session.rollback(); flash(f'メモの保存中にエラーが発生しました: {e}', 'error')
                current_app.logger.error(f"Error saving general note: {e}")
                entry_data = request.form.to_dict()
                return render_template('note_form.html', form_action='add', entry=entry_data, motorcycles=user_motorcycles, today_iso=date.today().isoformat())
    else: # GET
        today_iso_str = date.today().isoformat(); preselected_motorcycle_id = request.args.get('motorcycle_id', type=int)
        if preselected_motorcycle_id:
             is_owner = any(m.id == preselected_motorcycle_id for m in user_motorcycles)
             if not is_owner: preselected_motorcycle_id = None
        return render_template('note_form.html', form_action='add', entry=None, motorcycles=user_motorcycles, today_iso=today_iso_str, preselected_motorcycle_id=preselected_motorcycle_id)


# --- ▼▼▼ メモ編集 ▼▼▼ ---
@notes_bp.route('/<int:note_id>/edit', methods=['GET', 'POST'])
@login_required_custom
def edit_note(note_id):
    """既存の一般メモを編集"""
    # note_id と g.user.id でメモを取得 (存在しない or 他人のメモなら404)
    note = GeneralNote.query.filter_by(id=note_id, user_id=g.user.id).first_or_404()
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()

    if request.method == 'POST':
        motorcycle_id_str = request.form.get('motorcycle_id')
        note_date_str = request.form.get('note_date')
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()

        errors = {}
        note_date = None
        motorcycle_id = None

        # --- バリデーション (add_noteと同様) ---
        if not content: errors['content'] = 'メモ内容は必須です。'
        elif len(content) > 2000: errors['content'] = 'メモ内容は2000文字以内で入力してください。'
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
        else: motorcycle_id = None # 紐付け解除

        if errors:
            for field, msg in errors.items():
                flash(msg, 'danger')
            # エラー時は編集対象のメモデータを渡してフォームを再表示
            # today_iso も渡す (テンプレートで使っているため)
            return render_template('note_form.html',
                                   form_action='edit',
                                   entry=note, # オブジェクトを渡す
                                   motorcycles=user_motorcycles,
                                   today_iso=date.today().isoformat())
        else:
            # バリデーション成功 -> DB更新
            try:
                note.motorcycle_id = motorcycle_id
                note.note_date = note_date
                note.title = title if title else None
                note.content = content
                # updated_at は onupdate=datetime.utcnow で自動更新されるはず

                db.session.commit()
                flash('メモを更新しました。', 'success')
                return redirect(url_for('notes.notes_log')) # メモ一覧へリダイレクト
            except Exception as e:
                db.session.rollback()
                flash(f'メモの更新中にエラーが発生しました: {e}', 'error')
                current_app.logger.error(f"Error updating general note {note_id}: {e}")
                # DBエラー時もフォームを再表示
                return render_template('note_form.html',
                                       form_action='edit',
                                       entry=note,
                                       motorcycles=user_motorcycles,
                                       today_iso=date.today().isoformat())
    else: # GET
        # 編集フォームを表示
        return render_template('note_form.html',
                               form_action='edit',
                               entry=note, # DBから取得したオブジェクトを渡す
                               motorcycles=user_motorcycles,
                               today_iso=date.today().isoformat())


# --- ▼▼▼ メモ削除 ▼▼▼ ---
@notes_bp.route('/<int:note_id>/delete', methods=['POST'])
@login_required_custom
def delete_note(note_id):
    """一般メモを削除"""
    # note_id と g.user.id でメモを取得 (存在しない or 他人のメモなら404)
    note = GeneralNote.query.filter_by(id=note_id, user_id=g.user.id).first_or_404()
    try:
        db.session.delete(note)
        db.session.commit()
        flash('メモを削除しました。', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'メモの削除中にエラーが発生しました: {e}', 'error')
        current_app.logger.error(f"Error deleting general note {note_id}: {e}")
    return redirect(url_for('notes.notes_log')) # メモ一覧へリダイレクト