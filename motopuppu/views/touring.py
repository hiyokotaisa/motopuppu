# motopuppu/views/touring.py
import json
from datetime import datetime, date, timezone, timedelta
import requests
import time # ◀◀◀ timeモジュールをインポート

from flask import (
    Blueprint, flash, redirect, render_template, request, url_for, current_app, jsonify
)
from sqlalchemy import func
from sqlalchemy.orm import joinedload, subqueryload

# ▼▼▼ インポート文を修正 ▼▼▼
from flask_login import login_required, current_user
# ▲▲▲ 変更ここまで ▲▲▲
from ..models import db, Motorcycle, TouringLog, TouringSpot, TouringScrapbookEntry
from ..forms import TouringLogForm
from ..services import CryptoService

touring_bp = Blueprint('touring', __name__, url_prefix='/touring')

# ▼▼▼ 絵文字キャッシュ用の変数をグローバルスコープに定義 ▼▼▼
emoji_cache = {
    "data": None,
    "timestamp": 0
}
CACHE_DURATION_SECONDS = 86400  # 24時間 (60秒 * 60分 * 24時間)
# ▲▲▲ 変更ここまで ▲▲▲

def get_motorcycle_or_404(vehicle_id):
    """指定されたIDの車両を取得し、所有者でなければ404を返す"""
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    return Motorcycle.query.filter_by(id=vehicle_id, user_id=current_user.id).first_or_404()
    # ▲▲▲ 変更ここまで ▲▲▲

@touring_bp.route('/<int:vehicle_id>')
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def list_logs(vehicle_id):
    """指定された車両のツーリングログ一覧を表示する"""
    motorcycle = get_motorcycle_or_404(vehicle_id)
    spot_count_subq = db.session.query(
        TouringSpot.touring_log_id,
        func.count(TouringSpot.id).label('spot_count')
    ).group_by(TouringSpot.touring_log_id).subquery()
    
    scrapbook_count_subq = db.session.query(
        TouringScrapbookEntry.touring_log_id,
        func.count(TouringScrapbookEntry.id).label('scrapbook_count')
    ).group_by(TouringScrapbookEntry.touring_log_id).subquery()

    logs_with_counts = db.session.query(
        TouringLog,
        spot_count_subq.c.spot_count,
        scrapbook_count_subq.c.scrapbook_count
    ).filter(TouringLog.motorcycle_id == vehicle_id)\
    .outerjoin(spot_count_subq, TouringLog.id == spot_count_subq.c.touring_log_id)\
    .outerjoin(scrapbook_count_subq, TouringLog.id == scrapbook_count_subq.c.touring_log_id)\
    .order_by(TouringLog.touring_date.desc()).all()

    return render_template('touring/list_logs.html', motorcycle=motorcycle, logs_with_counts=logs_with_counts)


@touring_bp.route('/<int:vehicle_id>/create', methods=['GET', 'POST'])
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def create_log(vehicle_id):
    """新しいツーリングログを作成する"""
    motorcycle = get_motorcycle_or_404(vehicle_id)
    form = TouringLogForm()

    if form.validate_on_submit():
        new_log = TouringLog(
            # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
            user_id=current_user.id,
            # ▲▲▲ 変更ここまで ▲▲▲
            motorcycle_id=motorcycle.id,
            title=form.title.data,
            touring_date=form.touring_date.data,
            memo=form.memo.data
        )
        db.session.add(new_log)
        try:
            db.session.commit()
            process_spots_and_scrapbook(new_log, form)
            flash('新しいツーリングログを作成しました。', 'success')
            return redirect(url_for('touring.detail_log', log_id=new_log.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating touring log: {e}", exc_info=True)
            flash('ツーリングログの作成中にエラーが発生しました。', 'danger')

    return render_template('touring/touring_log_form.html', form=form, motorcycle=motorcycle, form_action='add')


@touring_bp.route('/<int:log_id>/edit', methods=['GET', 'POST'])
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def edit_log(log_id):
    """ツーリングログを編集する"""
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    log = TouringLog.query.filter_by(id=log_id, user_id=current_user.id).first_or_404()
    # ▲▲▲ 変更ここまで ▲▲▲
    motorcycle = log.motorcycle
    form = TouringLogForm(obj=log)
    
    if form.validate_on_submit():
        try:
            log.title = form.title.data
            log.touring_date = form.touring_date.data
            log.memo = form.memo.data
            
            process_spots_and_scrapbook(log, form)
            flash('ツーリングログを更新しました。', 'success')
            return redirect(url_for('touring.detail_log', log_id=log.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating touring log {log_id}: {e}", exc_info=True)
            flash('ツーリングログの更新中にエラーが発生しました。', 'danger')

    if request.method == 'GET':
        spots_data = [{'spot_name': s.spot_name, 'memo': s.memo or '', 'photo_link_url': s.photo_link_url or ''} for s in log.spots]
        form.spots_data.data = json.dumps(spots_data)
        
        note_ids = [entry.misskey_note_id for entry in log.scrapbook_entries]
        form.scrapbook_note_ids.data = json.dumps(note_ids)

    return render_template('touring/touring_log_form.html', form=form, motorcycle=motorcycle, log=log, form_action='edit')


def process_spots_and_scrapbook(log, form):
    """フォームから送られてきたスポットとスクラップブックのJSONデータを処理する"""
    TouringSpot.query.filter_by(touring_log_id=log.id).delete()
    TouringScrapbookEntry.query.filter_by(touring_log_id=log.id).delete()
    db.session.commit()

    if form.spots_data.data:
        try:
            spots = json.loads(form.spots_data.data)
            for spot_data in spots:
                if spot_data.get('spot_name'):
                    new_spot = TouringSpot(touring_log_id=log.id, **spot_data)
                    db.session.add(new_spot)
        except json.JSONDecodeError:
            current_app.logger.warning(f"Failed to decode spots_data JSON for log {log.id}")

    if form.scrapbook_note_ids.data:
        try:
            note_ids = json.loads(form.scrapbook_note_ids.data)
            for note_id in note_ids:
                new_entry = TouringScrapbookEntry(touring_log_id=log.id, misskey_note_id=note_id)
                db.session.add(new_entry)
        except json.JSONDecodeError:
            current_app.logger.warning(f"Failed to decode scrapbook_note_ids JSON for log {log.id}")
            
    db.session.commit()


@touring_bp.route('/<int:log_id>/delete', methods=['POST'])
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def delete_log(log_id):
    """ツーリングログを削除する"""
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    log = TouringLog.query.filter_by(id=log_id, user_id=current_user.id).first_or_404()
    # ▲▲▲ 変更ここまで ▲▲▲
    vehicle_id = log.motorcycle_id
    try:
        db.session.delete(log)
        db.session.commit()
        flash('ツーリングログを削除しました。', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting touring log {log_id}: {e}", exc_info=True)
        flash('ツーリングログの削除中にエラーが発生しました。', 'danger')
    return redirect(url_for('touring.list_logs', vehicle_id=vehicle_id))


@touring_bp.route('/<int:log_id>/detail')
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def detail_log(log_id):
    """ツーリングログの詳細ページ"""
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    log = TouringLog.query.options(
        subqueryload(TouringLog.spots),
        subqueryload(TouringLog.scrapbook_entries)
    ).filter_by(id=log_id, user_id=current_user.id).first_or_404()
    # ▲▲▲ 変更ここまで ▲▲▲
    
    # ▼▼▼ Misskey絵文字の取得処理をキャッシュ対応に変更 ▼▼▼
    current_time = time.time()
    
    # キャッシュが有効期限切れかチェック
    if emoji_cache["data"] and (current_time - emoji_cache["timestamp"] < CACHE_DURATION_SECONDS):
        # キャッシュが有効な場合はキャッシュからデータを取得
        emojis_json = emoji_cache["data"]
        current_app.logger.info("Using cached Misskey emojis.")
    else:
        # キャッシュがない、または期限切れの場合はAPIから取得
        current_app.logger.info("Fetching new Misskey emojis from API.")
        try:
            misskey_instance_url = current_app.config.get('MISSKEY_INSTANCE_URL', 'https://misskey.io')
            # /api/emojis は POST リクエストを必要とする場合があるため、空のjsonを送信
            response = requests.post(f"{misskey_instance_url}/api/emojis", json={}, timeout=10)
            response.raise_for_status()
            # レスポンスが {"emojis": [...]} という形式であることを想定
            emojis_data = response.json().get("emojis", [])
            emojis_json = json.dumps(emojis_data)
            
            # 取得したデータと現在時刻をキャッシュに保存
            emoji_cache["data"] = emojis_json
            emoji_cache["timestamp"] = current_time
            
        except requests.RequestException as e:
            current_app.logger.error(f"Failed to fetch Misskey emojis: {e}")
            # エラー発生時は、もし古いキャッシュがあればそれを使う (なければ空)
            emojis_json = emoji_cache["data"] if emoji_cache["data"] else '[]'
        except Exception as e:
            current_app.logger.error(f"An unexpected error occurred while fetching emojis: {e}", exc_info=True)
            emojis_json = emoji_cache["data"] if emoji_cache["data"] else '[]'
    # ▲▲▲ 変更ここまで ▲▲▲

    return render_template('touring/detail_log.html', log=log, emojis_json=emojis_json)


@touring_bp.route('/api/misskey_notes')
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def fetch_misskey_notes_api():
    """指定された日付のMisskeyノートを取得する内部API"""
    date_str = request.args.get('date')
    if not date_str:
        return jsonify({"error": "Date parameter is required"}), 400

    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        return jsonify({"error": "Invalid date format"}), 400

    # ▼▼▼ g.user を current_user に変更 ▼▼▼
    if not current_user.encrypted_misskey_api_token:
        return jsonify({"error": "Misskey API token not found."}), 403

    try:
        crypto = CryptoService()
        api_token = crypto.decrypt(current_user.encrypted_misskey_api_token)
    except Exception as e:
        current_app.logger.error(f"Failed to decrypt API token for user {current_user.id}: {e}")
        return jsonify({"error": "Failed to decrypt API token."}), 500
    # ▲▲▲ 変更ここまで ▲▲▲

    jst = timezone(timedelta(hours=9))
    start_dt_local = datetime.combine(target_date, datetime.min.time(), tzinfo=jst)
    end_dt_local = datetime.combine(target_date, datetime.max.time(), tzinfo=jst)
    
    since_ts = int(start_dt_local.timestamp() * 1000)
    until_ts = int(end_dt_local.timestamp() * 1000)

    misskey_instance_url = current_app.config.get('MISSKEY_INSTANCE_URL', 'https://misskey.io')
    api_url = f"{misskey_instance_url}/api/users/notes"
    
    headers = {'Content-Type': 'application/json'}
    payload = {
        'i': api_token,
        # ▼▼▼ g.user を current_user に変更 ▼▼▼
        'userId': current_user.misskey_user_id,
        # ▲▲▲ 変更ここまで ▲▲▲
        'sinceDate': since_ts,
        'untilDate': until_ts,
        'includeMyRenotes': False,
        'withChannelNotes': True,
        'limit': 100
    }
    
    try:
        response = requests.post(api_url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        notes = response.json()
        
        filtered_notes = [
            {
                'id': note.get('id'),
                'text': note.get('text'),
                'files': note.get('files'),
                'createdAt': note.get('createdAt')
            } for note in notes
        ]
        return jsonify(sorted(filtered_notes, key=lambda x: x['createdAt']))
    except requests.RequestException as e:
        current_app.logger.error(f"Failed to fetch Misskey notes: {e}")
        return jsonify({"error": "Misskey APIへの接続に失敗しました。"}), 502
    except Exception as e:
        current_app.logger.error(f"An unexpected error occurred while fetching notes: {e}", exc_info=True)
        return jsonify({"error": "ノートの取得中に予期せぬエラーが発生しました。"}), 500

@touring_bp.route('/api/fetch_note_details', methods=['POST'])
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def fetch_note_details_api():
    """ノートIDのリストを受け取り、Misskeyから詳細情報を取得して返すAPI"""
    note_ids = request.json.get('note_ids')
    if not note_ids or not isinstance(note_ids, list):
        return jsonify({"error": "note_ids (list) is required"}), 400

    # ▼▼▼ g.user を current_user に変更 ▼▼▼
    if not current_user.encrypted_misskey_api_token:
        return jsonify({"error": "Misskey API token not found."}), 403

    try:
        crypto = CryptoService()
        api_token = crypto.decrypt(current_user.encrypted_misskey_api_token)
    except Exception:
        return jsonify({"error": "Failed to decrypt API token."}), 500
    # ▲▲▲ 変更ここまで ▲▲▲
    
    misskey_instance_url = current_app.config.get('MISSKEY_INSTANCE_URL', 'https://misskey.io')
    api_url = f"{misskey_instance_url}/api/notes/show"
    headers = {'Content-Type': 'application/json'}
    
    note_details = {}
    for note_id in note_ids:
        payload = {'i': api_token, 'noteId': note_id}
        try:
            response = requests.post(api_url, headers=headers, json=payload, timeout=5)
            if response.status_code == 200:
                note_details[note_id] = response.json()
            else:
                note_details[note_id] = None
        except requests.RequestException:
            note_details[note_id] = None

    return jsonify(note_details)