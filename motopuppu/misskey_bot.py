# motopuppu/misskey_bot.py
"""
Misskey公式アカウントによるイベント自動告知モジュール。

公開イベント（is_public=True）を段階的に告知投稿する。
通知スパン: 2ヶ月前、1ヶ月前、2週間前、1週間前、3日前、1日前、当日
"""
import requests
from datetime import datetime, timezone, timedelta
from flask import current_app
from . import db
from .models import Event, EventNotification, EventParticipant, ParticipationStatus
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

        # 既に投稿済みかチェック
        existing = EventNotification.query.filter_by(
            event_id=event.id,
            notification_type=notification_type
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
            notification = EventNotification(
                event_id=event.id,
                notification_type=notification_type,
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
