# motopuppu/misskey_bot.py
"""
Misskey公式アカウントによる自動投稿モジュール。

1. 公開イベント（is_public=True）を段階的に告知投稿する。
   通知スパン: 2ヶ月前、1ヶ月前、2週間前、1週間前、3日前、1日前、当日
2. リーダーボードの新記録（コースレコード更新）を告知投稿する。
"""
import os
import decimal
import requests
from datetime import datetime, timezone, timedelta
from flask import current_app
from . import db
from .models import (
    Event, EventParticipant, ParticipationStatus,
    BotNotificationLog,
    ActivityLog, SessionLog, User, Motorcycle
)
from .utils.datetime_helpers import JST
from sqlalchemy import func


# 通知スパンの定義: (notification_type, 残日数の上限, 残日数の下限, 投稿プレフィックス)
# cron が毎日1回実行される前提で、各スパンに余裕を持たせた範囲で判定
NOTIFICATION_TIERS = [
    ('60days', 60, 56, '📢 2ヶ月後に開催！'),
    ('30days', 30, 28, '📢 1ヶ月後に開催！'),
    ('14days', 14, 13, '📢 2週間後に開催！'),
    ('7days',   7,  6, '📢 来週開催！'),
    ('3days',   3,  2, '📢 まもなく開催！'),
    ('1day',    1,  1, '📢 明日開催！'),
    ('today',   0,  0, '🏁 本日開催！'),
]


def _get_applicable_tier(days_until_event):
    """
    イベントまでの残日数から、該当する通知タイプを返す。
    該当するものがなければ None。
    """
    for tier_type, upper, lower, prefix in NOTIFICATION_TIERS:
        if lower <= days_until_event <= upper:
            return tier_type, prefix
    return None


def _build_note_text(event, prefix, app_base_url):
    """投稿文を生成する"""
    # JST変換して表示用の日時文字列を作る
    start_jst = event.start_datetime.replace(tzinfo=timezone.utc).astimezone(JST)

    # 曜日の日本語マッピング
    weekday_names = ['月', '火', '水', '木', '金', '土', '日']
    weekday_str = weekday_names[start_jst.weekday()]

    date_str = start_jst.strftime(f'%Y/%m/%d ({weekday_str}) %H:%M')

    # 終了日時がある場合
    if event.end_datetime:
        end_jst = event.end_datetime.replace(tzinfo=timezone.utc).astimezone(JST)
        # 同日ならば時間のみ表示
        if start_jst.date() == end_jst.date():
            date_str += f'〜{end_jst.strftime("%H:%M")}'
        else:
            end_weekday_str = weekday_names[end_jst.weekday()]
            date_str += f'〜{end_jst.strftime(f"%m/%d ({end_weekday_str}) %H:%M")}'

    # 参加者数をカウント
    attending_count = event.participants.filter_by(
        status=ParticipationStatus.ATTENDING
    ).count()

    # 投稿文の組み立て
    lines = [
        f'{prefix}',
        '',
        f'📌 「{event.title}」',
        f'📅 {date_str}',
    ]

    if event.location:
        lines.append(f'📍 {event.location}')

    if attending_count > 0:
        lines.append(f'👥 参加者: {attending_count}名')

    if event.description:
        # 説明文は長すぎる場合は省略
        desc = event.description
        if len(desc) > 100:
            desc = desc[:100] + '…'
        lines.append('')
        lines.append(desc)

    # 公開イベントページへのリンク
    event_url = f'{app_base_url}/event/public/{event.public_id}'
    lines.extend([
        '',
        f'詳しくはこちら👇',
        event_url,
        '',
        '#もとぷっぷー #バイクイベント'
    ])

    return '\n'.join(lines)


def _post_to_misskey(note_text, bot_token, misskey_instance_url):
    """Misskey API notes/create でノートを投稿する"""
    api_url = f'{misskey_instance_url}/api/notes/create'
    payload = {
        'i': bot_token,
        'text': note_text,
    }

    response = requests.post(api_url, json=payload, timeout=15)
    response.raise_for_status()

    result = response.json()
    # notes/create の成功時は {"createdNote": {"id": "...", ...}} が返る
    created_note = result.get('createdNote', {})
    return created_note.get('id')


def post_upcoming_events(dry_run=False):
    """
    直近の公開イベントを段階的にMisskey公式アカウントで告知投稿する。

    Args:
        dry_run: Trueの場合は実際に投稿せず、投稿予定の内容を表示のみ。

    Returns:
        dict: 処理結果のサマリー
    """
    bot_token = current_app.config.get('MISSKEY_BOT_API_TOKEN')
    misskey_instance_url = current_app.config.get('MISSKEY_INSTANCE_URL', 'https://misskey.io')

    if not bot_token and not dry_run:
        current_app.logger.error('MISSKEY_BOT_API_TOKEN が設定されていません。')
        print('エラー: MISSKEY_BOT_API_TOKEN が設定されていません。')
        return {'error': 'MISSKEY_BOT_API_TOKEN not configured', 'posted': 0}

    # アプリケーションのベースURL（投稿文中のリンク生成用）
    # Render環境では RENDER_EXTERNAL_URL が使える
    import os
    app_base_url = os.environ.get('RENDER_EXTERNAL_URL', 'https://motopuppu.app')
    # 末尾スラッシュを除去
    app_base_url = app_base_url.rstrip('/')

    now_utc = datetime.now(timezone.utc)
    # 2ヶ月先まで（約61日）の公開イベントを取得
    cutoff_utc = now_utc + timedelta(days=61)

    upcoming_events = Event.query.filter(
        Event.is_public == True,
        Event.start_datetime >= now_utc,
        Event.start_datetime <= cutoff_utc,
    ).order_by(Event.start_datetime.asc()).all()

    if not upcoming_events:
        msg = '投稿対象の公開イベントはありません。'
        current_app.logger.info(msg)
        print(msg)
        return {'posted': 0, 'skipped': 0, 'events_checked': 0}

    posted_count = 0
    skipped_count = 0
    errors = []

    for event in upcoming_events:
        # イベント開催日までの残日数を計算 (JST基準)
        start_jst = event.start_datetime.replace(tzinfo=timezone.utc).astimezone(JST)
        now_jst = now_utc.astimezone(JST)
        days_until = (start_jst.date() - now_jst.date()).days

        # 該当する通知タイプを判定
        tier_result = _get_applicable_tier(days_until)
        if tier_result is None:
            # このイベントは現時点でどの通知スパンにも該当しない
            continue

        notification_type, prefix = tier_result

        # notification_typeにevent_idを含めて一意性を確保
        notification_key = f'event_{notification_type}_{event.id}'

        # 既に投稿済みかチェック
        existing = BotNotificationLog.query.filter_by(
            notification_type=notification_key
        ).first()

        if existing:
            skipped_count += 1
            current_app.logger.debug(
                f'スキップ: イベント「{event.title}」(ID:{event.id}) の {notification_type} は投稿済み'
            )
            continue

        # 投稿文を生成
        note_text = _build_note_text(event, prefix, app_base_url)

        if dry_run:
            print(f'\n{"="*60}')
            print(f'[DRY RUN] イベント: {event.title} (ID: {event.id})')
            print(f'  開催日: {start_jst.strftime("%Y/%m/%d %H:%M")} JST')
            print(f'  残日数: {days_until}日')
            print(f'  通知タイプ: {notification_type}')
            print(f'{"—"*60}')
            print(note_text)
            print(f'{"="*60}')
            posted_count += 1
            continue

        # 実際に投稿
        try:
            note_id = _post_to_misskey(note_text, bot_token, misskey_instance_url)

            # 投稿記録を保存
            notification = BotNotificationLog(
                event_id=event.id,
                notification_type=notification_key,
                misskey_note_id=note_id,
            )
            db.session.add(notification)
            db.session.commit()

            posted_count += 1
            current_app.logger.info(
                f'投稿成功: イベント「{event.title}」(ID:{event.id}) {notification_type} → Note ID: {note_id}'
            )
            print(f'✅ 投稿成功: 「{event.title}」 [{notification_type}]')

        except requests.exceptions.RequestException as e:
            db.session.rollback()
            error_msg = f'Misskey API エラー: イベント「{event.title}」(ID:{event.id}) {notification_type} - {e}'
            current_app.logger.error(error_msg)
            print(f'❌ {error_msg}')
            errors.append(error_msg)

        except Exception as e:
            db.session.rollback()
            error_msg = f'予期せぬエラー: イベント「{event.title}」(ID:{event.id}) {notification_type} - {e}'
            current_app.logger.error(error_msg, exc_info=True)
            print(f'❌ {error_msg}')
            errors.append(error_msg)

    # サマリー表示
    print(f'\n--- 処理完了 ---')
    print(f'  対象イベント数: {len(upcoming_events)}')
    print(f'  投稿{"予定" if dry_run else "成功"}: {posted_count}件')
    print(f'  スキップ（投稿済み）: {skipped_count}件')
    if errors:
        print(f'  エラー: {len(errors)}件')

    return {
        'events_checked': len(upcoming_events),
        'posted': posted_count,
        'skipped': skipped_count,
        'errors': errors,
    }


# ============================================================
# 2. リーダーボード新記録（コースレコード更新）通知
# ============================================================

def _format_seconds_to_time(total_seconds):
    """秒(Decimal)を "M:SS.fff" 形式の文字列に変換する"""
    if total_seconds is None:
        return "N/A"
    if not isinstance(total_seconds, decimal.Decimal):
        total_seconds = decimal.Decimal(str(total_seconds))
    minutes = int(total_seconds // 60)
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:06.3f}"


def _build_record_note_text(circuit_name, user, motorcycle, lap_time_seconds, app_base_url):
    """コースレコード更新の投稿文を生成する"""
    lap_time_str = _format_seconds_to_time(lap_time_seconds)
    user_display = user.display_name or user.misskey_username

    lines = [
        '🏆 コースレコード更新！',
        '',
        f'🏁 {circuit_name}',
        f'⏱️ {lap_time_str}',
        f'🏍️ {motorcycle.name}',
        f'👤 {user_display}',
        '',
        f'リーダーボードで確認👇',
        f'{app_base_url}/leaderboard/{circuit_name}',
        '',
        '#もとぷっぷー #サーキット #コースレコード'
    ]

    return '\n'.join(lines)


def post_leaderboard_records(dry_run=False, hours_back=25):
    """
    直近hours_back時間以内に更新されたコースレコード（各サーキットの全体1位）を
    Misskey公式アカウントで告知投稿する。

    検出ロジック:
    - 各サーキットについて、リーダーボード対象の全セッションから全体のベストラップを取得
    - そのベストラップが hours_back 時間以内に作成されたものであるかを確認
    - 既に通知済みでなければ投稿

    Args:
        dry_run: Trueの場合は実際に投稿せず、投稿予定の内容を表示のみ。
        hours_back: 何時間前まで遡って新記録を探すか。デフォルト25時間（cronの実行間隔に余裕）。

    Returns:
        dict: 処理結果のサマリー
    """
    from .constants import JAPANESE_CIRCUITS

    bot_token = current_app.config.get('MISSKEY_BOT_API_TOKEN')
    misskey_instance_url = current_app.config.get('MISSKEY_INSTANCE_URL', 'https://misskey.io')

    if not bot_token and not dry_run:
        current_app.logger.error('MISSKEY_BOT_API_TOKEN が設定されていません。')
        print('エラー: MISSKEY_BOT_API_TOKEN が設定されていません。')
        return {'error': 'MISSKEY_BOT_API_TOKEN not configured', 'posted': 0}

    app_base_url = os.environ.get('RENDER_EXTERNAL_URL', 'https://motopuppu.app').rstrip('/')
    now_utc = datetime.now(timezone.utc)
    cutoff_time = now_utc - timedelta(hours=hours_back)

    posted_count = 0
    skipped_count = 0
    errors = []
    circuits_checked = 0

    # データが存在するサーキットのリストを取得
    active_circuits = db.session.query(
        ActivityLog.circuit_name
    ).join(SessionLog, SessionLog.activity_log_id == ActivityLog.id).filter(
        ActivityLog.circuit_name.isnot(None),
        ActivityLog.circuit_name.in_(JAPANESE_CIRCUITS),
        SessionLog.include_in_leaderboard == True,
        SessionLog.best_lap_seconds.isnot(None)
    ).distinct().all()

    active_circuit_names = [row[0] for row in active_circuits]

    if not active_circuit_names:
        msg = 'リーダーボードにデータのあるサーキットがありません。'
        current_app.logger.info(msg)
        print(msg)
        return {'posted': 0, 'skipped': 0, 'circuits_checked': 0}

    for circuit_name in active_circuit_names:
        circuits_checked += 1

        # このサーキットの全体ベストラップ（1位のセッション）を取得
        best_session = db.session.query(
            SessionLog.id,
            SessionLog.best_lap_seconds,
            ActivityLog.user_id,
            ActivityLog.motorcycle_id,
            ActivityLog.activity_date
        ).join(ActivityLog, SessionLog.activity_log_id == ActivityLog.id).filter(
            ActivityLog.circuit_name == circuit_name,
            SessionLog.include_in_leaderboard == True,
            SessionLog.best_lap_seconds.isnot(None)
        ).order_by(SessionLog.best_lap_seconds.asc()).first()

        if not best_session:
            continue

        session_id = best_session.id
        lap_time = best_session.best_lap_seconds
        user_id = best_session.user_id
        motorcycle_id = best_session.motorcycle_id

        # このセッションに紐づくActivityLogの作成日時で「新しいかどうか」を判定
        # SessionLog自体にcreated_atがないため、ActivityLogのactivity_dateを使う
        # ただしactivity_dateはDateなので、より正確にはSessionLogのIDの新しさで判定する
        # → BotNotificationLogに記録がなければ「初めて1位になった」=新記録
        notification_type = f'leaderboard_record_{session_id}'

        # 既に通知済みか確認
        existing = BotNotificationLog.query.filter_by(
            notification_type=notification_type
        ).first()

        if existing:
            skipped_count += 1
            continue

        # 追加チェック: activity_dateが直近のものかどうか
        # 過去の記録を初回実行時にすべて投稿しないよう、cutoff以降の記録のみ対象
        activity = ActivityLog.query.get(
            db.session.query(SessionLog.activity_log_id).filter_by(id=session_id).scalar()
        )
        if not activity:
            continue

        # activity_dateはDate型なので、cutoffの日付と比較
        if activity.activity_date < cutoff_time.date():
            # 古い記録なので初回スキップ（でも通知済みとして記録しておく）
            notification = BotNotificationLog(
                notification_type=notification_type,
                misskey_note_id=None,
            )
            db.session.add(notification)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
            skipped_count += 1
            continue

        # ユーザーと車両情報を取得
        user = db.session.get(User, user_id)
        motorcycle = db.session.get(Motorcycle, motorcycle_id)
        if not user or not motorcycle:
            continue

        note_text = _build_record_note_text(circuit_name, user, motorcycle, lap_time, app_base_url)

        if dry_run:
            print(f'\n{"="*60}')
            print(f'[DRY RUN] 🏆 新記録: {circuit_name}')
            print(f'  タイム: {_format_seconds_to_time(lap_time)}')
            print(f'  ライダー: {user.display_name or user.misskey_username}')
            print(f'  車両: {motorcycle.name}')
            print(f'  セッションID: {session_id}')
            print(f'{"—"*60}')
            print(note_text)
            print(f'{"="*60}')
            posted_count += 1
            continue

        # 実際に投稿
        try:
            note_id = _post_to_misskey(note_text, bot_token, misskey_instance_url)

            notification = BotNotificationLog(
                notification_type=notification_type,
                misskey_note_id=note_id,
            )
            db.session.add(notification)
            db.session.commit()

            posted_count += 1
            current_app.logger.info(
                f'投稿成功: コースレコード {circuit_name} {_format_seconds_to_time(lap_time)} → Note ID: {note_id}'
            )
            print(f'✅ 投稿成功: 🏆 {circuit_name} [{_format_seconds_to_time(lap_time)}]')

        except requests.exceptions.RequestException as e:
            db.session.rollback()
            error_msg = f'Misskey API エラー: レコード通知 {circuit_name} - {e}'
            current_app.logger.error(error_msg)
            print(f'❌ {error_msg}')
            errors.append(error_msg)

        except Exception as e:
            db.session.rollback()
            error_msg = f'予期せぬエラー: レコード通知 {circuit_name} - {e}'
            current_app.logger.error(error_msg, exc_info=True)
            print(f'❌ {error_msg}')
            errors.append(error_msg)

    # サマリー表示
    print(f'\n--- リーダーボード通知 処理完了 ---')
    print(f'  チェックしたサーキット数: {circuits_checked}')
    print(f'  投稿{"予定" if dry_run else "成功"}: {posted_count}件')
    print(f'  スキップ: {skipped_count}件')
    if errors:
        print(f'  エラー: {len(errors)}件')

    return {
        'circuits_checked': circuits_checked,
        'posted': posted_count,
        'skipped': skipped_count,
        'errors': errors,
    }
