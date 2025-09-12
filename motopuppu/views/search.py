# motopuppu/views/search.py

# ▼▼▼【ここから変更】g をインポート ▼▼▼
from flask import Blueprint, request, jsonify, url_for, g
# ▲▲▲【変更はここまで】▲▲▲
from flask_login import login_required, current_user
from sqlalchemy import or_

from ..models import (
    Motorcycle, MaintenanceEntry, FuelEntry, GeneralNote, 
    ActivityLog, SessionLog, SettingSheet, MaintenanceReminder,
    TouringLog, Event, Team, MaintenanceSpecSheet
)
from ..constants import JAPANESE_CIRCUITS


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
    query_lower = query.lower()

    if len(query) < MIN_QUERY_LENGTH:
        return jsonify({'results': []})

    search_term = f"%{query}%"
    results = []

    # --- データ検索 --- (このセクションは変更ありません)

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
            'url': url_for('vehicle.edit_vehicle', vehicle_id=item.id),
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

    # 3. 給油記録 (FuelEntry)
    fuel_entries = FuelEntry.query.join(Motorcycle).filter(
        Motorcycle.user_id == current_user.id,
        or_(
            FuelEntry.notes.ilike(search_term),
            FuelEntry.station_name.ilike(search_term),
            FuelEntry.fuel_type.ilike(search_term),
            Motorcycle.name.ilike(search_term) 
        )
    ).order_by(FuelEntry.entry_date.desc()).limit(MAX_RESULTS_PER_CATEGORY).all()
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
            ActivityLog.circuit_name.ilike(search_term),
            ActivityLog.custom_location.ilike(search_term),
            ActivityLog.notes.ilike(search_term)
        )
    ).order_by(ActivityLog.activity_date.desc()).limit(MAX_RESULTS_PER_CATEGORY).all()
    for item in activities:
        results.append({
            'category': '活動ログ',
            'title': f"[{item.motorcycle.name}] {item.activity_title or item.location_name_display}",
            'url': url_for('activity.detail_activity', activity_id=item.id),
            'text': f"{item.activity_date.strftime('%Y-%m-%d')} | {item.notes[:30] if item.notes else 'メモなし'}..."
        })

    # 6. リマインダー (MaintenanceReminder)
    reminders = MaintenanceReminder.query.join(Motorcycle).filter(
        Motorcycle.user_id == current_user.id,
        MaintenanceReminder.task_description.ilike(search_term)
    ).limit(MAX_RESULTS_PER_CATEGORY).all()
    for item in reminders:
        interval_parts = []
        if item.interval_km:
            interval_parts.append(f"{item.interval_km}km")
        if item.interval_months:
            interval_parts.append(f"{item.interval_months}ヶ月")
        interval_display = " / ".join(interval_parts)

        results.append({
            'category': 'リマインダー',
            'title': f"[{item.motorcycle.name}] {item.task_description}",
            'url': url_for('reminder.edit_reminder', reminder_id=item.id),
            'text': f"サイクル: {interval_display}"
        })

    # 7. セッティングシート (SettingSheet)
    setting_sheets = SettingSheet.query.join(Motorcycle).filter(
        Motorcycle.user_id == current_user.id,
        or_(
            SettingSheet.sheet_name.ilike(search_term),
            SettingSheet.notes.ilike(search_term)
        )
    ).limit(MAX_RESULTS_PER_CATEGORY).all()
    for item in setting_sheets:
        results.append({
            'category': 'セッティングシート',
            'title': f"[{item.motorcycle.name}] {item.sheet_name}",
            'url': url_for('activity.edit_setting', setting_id=item.id),
            'text': f"メモ: {item.notes[:30] if item.notes else 'なし'}..."
        })

    # 8. ツーリングログ (TouringLog)
    touring_logs = TouringLog.query.join(Motorcycle).filter(
        Motorcycle.user_id == current_user.id,
        or_(
            TouringLog.title.ilike(search_term),
            TouringLog.memo.ilike(search_term)
        )
    ).order_by(TouringLog.touring_date.desc()).limit(MAX_RESULTS_PER_CATEGORY).all()
    for item in touring_logs:
        results.append({
            'category': 'ツーリングログ',
            'title': f"[{item.motorcycle.name}] {item.title}",
            'url': url_for('touring.detail_log', log_id=item.id),
            'text': f"{item.touring_date.strftime('%Y-%m-%d')} | {item.memo[:30] if item.memo else 'メモなし'}..."
        })

    # 9. イベント (Event)
    events = Event.query.filter(
        Event.user_id == current_user.id,
        or_(
            Event.title.ilike(search_term),
            Event.description.ilike(search_term),
            Event.location.ilike(search_term)
        )
    ).order_by(Event.start_datetime.desc()).limit(MAX_RESULTS_PER_CATEGORY).all()
    for item in events:
        results.append({
            'category': 'イベント',
            'title': item.title,
            'url': url_for('event.event_detail', event_id=item.id),
            'text': f"{item.start_datetime.strftime('%Y-%m-%d %H:%M')} | {item.location or '場所未設定'}"
        })

    # 10. チーム (Team) - 自分が所属するチーム
    teams = Team.query.filter(Team.members.any(id=current_user.id)).filter(
        Team.name.ilike(search_term)
    ).limit(MAX_RESULTS_PER_CATEGORY).all()
    for item in teams:
        results.append({
            'category': 'チーム',
            'title': item.name,
            'url': url_for('team.dashboard', team_id=item.id),
            'text': f"オーナー: {item.owner.display_name or item.owner.misskey_username}"
        })

    # 11. 整備情報シート (MaintenanceSpecSheet)
    spec_sheets = MaintenanceSpecSheet.query.join(Motorcycle).filter(
        Motorcycle.user_id == current_user.id,
        MaintenanceSpecSheet.sheet_name.ilike(search_term)
    ).limit(MAX_RESULTS_PER_CATEGORY).all()
    for item in spec_sheets:
        results.append({
            'category': '整備情報シート',
            'title': f"[{item.motorcycle.name}] {item.sheet_name}",
            'url': url_for('spec_sheet.view_sheet', sheet_id=item.id),
            'text': f"車両固有の整備情報を記録・閲覧します。"
        })

    # リーダーボード検索
    leaderboard_results = []
    for circuit_name in JAPANESE_CIRCUITS:
        if query_lower in circuit_name.lower():
            leaderboard_results.append({
                'category': 'リーダーボード',
                'title': circuit_name,
                'url': url_for('leaderboard.ranking', circuit_name=circuit_name),
                'text': 'このサーキットのランキングを表示します。'
            })
        if len(leaderboard_results) >= MAX_RESULTS_PER_CATEGORY:
            break
    results.extend(leaderboard_results)


    # --- 機能ショートカット ---
    
    # ▼▼▼【ここから変更】ショートカットの定義を関数内に移動 ▼▼▼
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
        'ツーリング': {'url': url_for('touring.list_logs', vehicle_id=g.user_motorcycles[0].id if g.user_motorcycles else None), 'text': 'ツーリングログの一覧を確認します'},
        'イベント': {'url': url_for('event.list_events'), 'text': 'イベントの管理ページを開きます'},
        'チーム': {'url': url_for('team.list_teams'), 'text': 'チームの管理ページを開きます'},
        'リーダーボード': {'url': url_for('leaderboard.index'), 'text': 'サーキットのリーダーボードを表示します'},
        'プロフィール': {'url': url_for('profile.settings'), 'text': 'プロフィール設定を編集します'},
        '設定': {'url': url_for('profile.settings'), 'text': 'プロフィール設定を編集します'},
        'ガレージ設定': {'url': url_for('garage_settings.settings'), 'text': '公開ガレージの設定を編集します'},
        'ヘルプ': {'url': url_for('help.index'), 'text': 'もとぷっぷーの使い方を確認します'},
        '使い方': {'url': url_for('help.index'), 'text': 'もとぷっぷーの使い方を確認します'},
    }
    # ▲▲▲【変更はここまで】▲▲▲

    for keyword, info in shortcuts.items():
        if query_lower in keyword.lower():
            # URLがNoneになる可能性を回避 (車両が1台もない場合など)
            if info['url']:
                if not any(r['title'] == keyword for r in results if r['category'] == '機能'):
                     results.append({
                        'category': '機能',
                        'title': keyword,
                        'url': info['url'],
                        'text': info['text']
                    })

    return jsonify({'results': results})