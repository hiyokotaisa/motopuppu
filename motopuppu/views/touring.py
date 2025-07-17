# motopuppu/views/touring.py
import json
# ▼▼▼ timedelta をインポートリストに追加 ▼▼▼
from datetime import datetime, date, timezone, timedelta
# ▲▲▲ 変更ここまで ▲▲▲
import requests

from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, current_app, jsonify
)
from sqlalchemy import func
from sqlalchemy.orm import joinedload, subqueryload

from .auth import login_required_custom
from ..models import db, Motorcycle, TouringLog, TouringSpot, TouringScrapbookEntry
from ..forms import TouringLogForm
from ..services import CryptoService

touring_bp = Blueprint('touring', __name__, url_prefix='/touring')

def get_motorcycle_or_404(vehicle_id):
    """指定されたIDの車両を取得し、所有者でなければ404を返す"""
    return Motorcycle.query.filter_by(id=vehicle_id, user_id=g.user.id).first_or_404()

@touring_bp.route('/<int:vehicle_id>')
@login_required_custom
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
@login_required_custom
def create_log(vehicle_id):
    """新しいツーリングログを作成する"""
    motorcycle = get_motorcycle_or_404(vehicle_id)
    form = TouringLogForm()

    if form.validate_on_submit():
        new_log = TouringLog(
            user_id=g.user.id,
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
@login_required_custom
def edit_log(log_id):
    """ツーリングログを編集する"""
    log = TouringLog.query.filter_by(id=log_id, user_id=g.user.id).first_or_404()
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
@login_required_custom
def delete_log(log_id):
    """ツーリングログを削除する"""
    log = TouringLog.query.filter_by(id=log_id, user_id=g.user.id).first_or_404()
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
@login_required_custom
def detail_log(log_id):
    """ツーリングログの詳細ページ"""
    log = TouringLog.query.options(
        subqueryload(TouringLog.spots),
        subqueryload(TouringLog.scrapbook_entries)
    ).filter_by(id=log_id, user_id=g.user.id).first_or_404()
    
    return render_template('touring/detail_log.html', log=log)


@touring_bp.route('/api/misskey_notes')
@login_required_custom
def fetch_misskey_notes_api():
    """指定された日付のMisskeyノートを取得する内部API"""
    date_str = request.args.get('date')
    if not date_str:
        return jsonify({"error": "Date parameter is required"}), 400

    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        return jsonify({"error": "Invalid date format"}), 400

    if not g.user.encrypted_misskey_api_token:
        return jsonify({"error": "Misskey API token not found."}), 403

    try:
        crypto = CryptoService()
        api_token = crypto.decrypt(g.user.encrypted_misskey_api_token)
    except Exception as e:
        current_app.logger.error(f"Failed to decrypt API token for user {g.user.id}: {e}")
        return jsonify({"error": "Failed to decrypt API token."}), 500

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
        'userId': g.user.misskey_user_id,
        'sinceDate': since_ts,
        'untilDate': until_ts,
        'includeMyRenotes': False,
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