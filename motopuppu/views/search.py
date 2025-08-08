# motopuppu/views/search.py

from flask import Blueprint, request, jsonify, url_for
from flask_login import login_required, current_user
from sqlalchemy import or_

from ..models import (
    Motorcycle, MaintenanceEntry, FuelEntry, GeneralNote, 
    ActivityLog, SessionLog, SettingSheet
)

search_bp = Blueprint('search', __name__, url_prefix='/search')

MAX_RESULTS_PER_CATEGORY = 5
MIN_QUERY_LENGTH = 1 # 1文字から検索可能

@search_bp.route('/')
@login_required
def global_search():
    """
    アプリケーション全体から横断的にデータを検索し、
    JSON形式で結果を返すAPIエンドポイント。
    """
    query = request.args.get('q', '').strip()

    if len(query) < MIN_QUERY_LENGTH:
        return jsonify({'results': []})

    search_term = f"%{query}%"
    results = []

    # --- データ検索 ---

    # 1. 車両 (Motorcycle)
    motorcycles = Motorcycle.query.filter(
        Motorcycle.user_id == current_user.id,
        or_(
            Motorcycle.name.ilike(search_term),
            Motorcycle.maker.ilike(search_term)
        )
    ).limit(MAX_RESULTS_PER_CATEGORY).all()
    for item in motorcycles:
        results.append({
            'category': '車両',
            'title': f"{item.name} ({item.maker or 'メーカー未設定'})",
            'url': url_for('main.dashboard', stats_vehicle_id=item.id),
            'text': f"年式: {item.year or '未設定'}"
        })

    # 2. 整備記録 (MaintenanceEntry)
    maintenance_entries = MaintenanceEntry.query.join(Motorcycle).filter(
        Motorcycle.user_id == current_user.id,
        or_(
            MaintenanceEntry.description.ilike(search_term),
            MaintenanceEntry.category.ilike(search_term),
            MaintenanceEntry.notes.ilike(search_term)
        )
    ).order_by(MaintenanceEntry.maintenance_date.desc()).limit(MAX_RESULTS_PER_CATEGORY).all()
    for item in maintenance_entries:
        results.append({
            'category': '整備記録',
            'title': f"[{item.motorcycle.name}] {item.description[:30]}...",
            'url': url_for('maintenance.edit_maintenance', entry_id=item.id),
            'text': f"{item.maintenance_date.strftime('%Y-%m-%d')} | {item.category or 'カテゴリなし'}"
        })

    # 3. 給油記録 (FuelEntry) - メモやスタンド名
    # ▼▼▼ 修正箇所: 検索対象に車両名と油種を追加 ▼▼▼
    fuel_entries = FuelEntry.query.join(Motorcycle).filter(
        Motorcycle.user_id == current_user.id,
        or_(
            FuelEntry.notes.ilike(search_term),
            FuelEntry.station_name.ilike(search_term),
            FuelEntry.fuel_type.ilike(search_term),
            Motorcycle.name.ilike(search_term) 
        )
    ).order_by(FuelEntry.entry_date.desc()).limit(MAX_RESULTS_PER_CATEGORY).all()
    # ▲▲▲ 修正ここまで ▲▲▲
    for item in fuel_entries:
        results.append({
            'category': '給油記録',
            'title': f"[{item.motorcycle.name}] {item.entry_date.strftime('%Y-%m-%d')} の給油",
            'url': url_for('fuel.edit_fuel', entry_id=item.id),
            'text': f"スタンド: {item.station_name or '未記録'}, メモ: {item.notes[:20] if item.notes else 'なし'}..."
        })

    # 4. ノート (GeneralNote)
    notes = GeneralNote.query.filter(
        GeneralNote.user_id == current_user.id,
        or_(
            GeneralNote.title.ilike(search_term),
            GeneralNote.content.ilike(search_term)
        )
    ).order_by(GeneralNote.note_date.desc()).limit(MAX_RESULTS_PER_CATEGORY).all()
    for item in notes:
        results.append({
            'category': 'ノート',
            'title': item.title or "無題のノート",
            'url': url_for('notes.edit_note', note_id=item.id),
            'text': f"{item.note_date.strftime('%Y-%m-%d')} | {item.content[:30] if item.content else '内容なし'}..."
        })
    
    # 5. 活動ログ (ActivityLog)
    activities = ActivityLog.query.join(Motorcycle).filter(
        Motorcycle.user_id == current_user.id,
        or_(
            ActivityLog.activity_title.ilike(search_term),
            ActivityLog.location_name.ilike(search_term),
            ActivityLog.notes.ilike(search_term)
        )
    ).order_by(ActivityLog.activity_date.desc()).limit(MAX_RESULTS_PER_CATEGORY).all()
    for item in activities:
        results.append({
            'category': '活動ログ',
            'title': f"[{item.motorcycle.name}] {item.activity_title or item.location_name}",
            'url': url_for('activity.detail_activity', activity_id=item.id),
            'text': f"{item.activity_date.strftime('%Y-%m-%d')} | {item.notes[:30] if item.notes else 'メモなし'}..."
        })


    # --- 機能ショートカット ---
    
    # 辞書でキーワードと遷移先を定義
    shortcuts = {
        '燃費': {'url': url_for('fuel.fuel_log'), 'text': '給油記録と燃費グラフを確認します'},
        '給油': {'url': url_for('fuel.fuel_log'), 'text': '給油記録と燃費グラフを確認します'},
        '整備': {'url': url_for('maintenance.maintenance_log'), 'text': '整備記録の一覧を確認します'},
        'ノート': {'url': url_for('notes.notes_log'), 'text': 'ノートやタスクの一覧を確認します'},
        'タスク': {'url': url_for('notes.notes_log'), 'text': 'ノートやタスクの一覧を確認します'},
        'リマインダー': {'url': url_for('vehicle.vehicle_list'), 'text': '各車両のリマインダー設定を確認します'},
        '車両': {'url': url_for('vehicle.vehicle_list'), 'text': '登録車両の一覧・管理をします'},
        '追加': {'url': url_for('vehicle.add_vehicle'), 'text': '新しい車両を登録します'},
        '活動': {'url': url_for('main.dashboard'), 'text': '活動ログは車両を選択してアクセスします'},
        'セッティング': {'url': url_for('main.dashboard'), 'text': 'セッティングシートは車両を選択してアクセスします'},
        'イベント': {'url': url_for('event.list_events'), 'text': 'イベントの管理ページを開きます'},
        'リーダーボード': {'url': url_for('leaderboard.index'), 'text': 'サーキットのリーダーボードを表示します'},
    }

    for keyword, info in shortcuts.items():
        if query.lower() in keyword.lower():
            # 重複を避ける
            if not any(r['title'] == keyword for r in results if r['category'] == '機能'):
                 results.append({
                    'category': '機能',
                    'title': keyword,
                    'url': info['url'],
                    'text': info['text']
                })

    return jsonify({'results': results})