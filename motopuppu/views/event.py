# motopuppu/views/event.py
from flask import (
    Blueprint, flash, redirect, render_template, request, url_for, abort, Response, current_app
)
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone, date
from sqlalchemy import func
from flask_login import login_required, current_user
from wtforms.validators import Optional
from ..models import db, Event, EventCollectionPlan, EventParticipant, Motorcycle, ParticipationStatus, PaymentStatus, User, Team, GeneralNote
from ..forms import EventForm, ParticipantForm, WalkinParticipantForm
from ..utils.datetime_helpers import JST
from .. import limiter

# iCalenderライブラリのインポート
try:
    from icalendar import Calendar, Event as ICalEvent
    ICALENDAR_AVAILABLE = True
except ImportError:
    ICALENDAR_AVAILABLE = False


event_bp = Blueprint('event', __name__, url_prefix='/event')


def _redirect_after_participant_update(event, participant_id=None):
    """主催者操作の戻り先を呼び出し元 (redirect_to パラメータ) に応じて切り替える"""
    redirect_to = request.form.get('redirect_to')
    anchor = f'#p-{participant_id}' if participant_id else ''
    if redirect_to == 'day':
        return redirect(url_for('event.day_view', event_id=event.id) + anchor)
    return redirect(url_for('event.event_detail', event_id=event.id) + (anchor or '#collectionSection'))


# プラン管理の上限と各種制限
MAX_COLLECTION_PLANS = 20
MAX_PLAN_NAME_LEN = 50
MAX_PLAN_AMOUNT = 1_000_000


def _plans_from_request(form_data):
    """request.form からプラン入力データを抽出し、テンプレート再表示用のリストに変換する"""
    try:
        plan_count = int(form_data.get('plan_count', '0') or '0')
    except (TypeError, ValueError):
        plan_count = 0
    plan_count = max(0, min(plan_count, MAX_COLLECTION_PLANS))

    plans = []
    for i in range(plan_count):
        raw_id = (form_data.get(f'plan_id_{i}') or '').strip()
        raw_name = (form_data.get(f'plan_name_{i}') or '').strip()
        raw_amount = (form_data.get(f'plan_amount_{i}') or '').strip()
        if not raw_name and not raw_amount and not raw_id:
            continue
        plans.append({'id': raw_id, 'name': raw_name, 'amount': raw_amount})
    return plans


def _plans_from_event(event):
    """既存イベントのプランをテンプレート再表示用のリストに変換する"""
    return [
        {'id': str(p.id), 'name': p.name, 'amount': str(p.amount)}
        for p in event.collection_plans.order_by(EventCollectionPlan.sort_order, EventCollectionPlan.id).all()
    ]


def _sync_collection_plans(event, form_data):
    """request.form から送信された料金プラン情報を event.collection_plans に反映する。

    フォーマット:
        plan_count: 件数 (例: 3)
        plan_id_{i}: 既存プランID (新規は空)
        plan_name_{i}: プラン名
        plan_amount_{i}: 金額 (整数)

    集金OFFの場合は全プランを削除する。
    バリデーションエラーがある場合は (False, エラーメッセージ) を返す。
    """
    # 集金OFFならプランを全削除
    if not event.collection_enabled:
        for plan in event.collection_plans.all():
            db.session.delete(plan)
        return True, None

    try:
        plan_count = int(form_data.get('plan_count', '0') or '0')
    except (TypeError, ValueError):
        plan_count = 0

    plan_count = max(0, min(plan_count, MAX_COLLECTION_PLANS))

    # 送信内容を解釈
    submitted_plans = []  # [{id, name, amount, sort_order}]
    for i in range(plan_count):
        raw_id = (form_data.get(f'plan_id_{i}') or '').strip()
        raw_name = (form_data.get(f'plan_name_{i}') or '').strip()
        raw_amount = (form_data.get(f'plan_amount_{i}') or '').strip()

        # 空行はスキップ (削除されたか未入力)
        if not raw_name and not raw_amount:
            continue

        if not raw_name:
            return False, f'プラン {i + 1} のプラン名が入力されていません。'
        if len(raw_name) > MAX_PLAN_NAME_LEN:
            return False, f'プラン名は{MAX_PLAN_NAME_LEN}文字以内で入力してください。'

        try:
            amount = int(raw_amount)
        except ValueError:
            return False, f'プラン「{raw_name}」の金額は整数で入力してください。'
        if amount < 0 or amount > MAX_PLAN_AMOUNT:
            return False, f'プラン「{raw_name}」の金額は0〜{MAX_PLAN_AMOUNT:,}円の範囲で入力してください。'

        plan_id = None
        if raw_id:
            try:
                plan_id = int(raw_id)
            except ValueError:
                plan_id = None

        submitted_plans.append({
            'id': plan_id,
            'name': raw_name,
            'amount': amount,
            'sort_order': len(submitted_plans),
        })

    # 既存プランをID→entityで取得
    existing_plans = {p.id: p for p in event.collection_plans.all()}
    submitted_ids = {p['id'] for p in submitted_plans if p['id'] is not None}

    # 送信されなかった既存プランは削除 (参加者FKは ondelete=SET NULL で自動的にNULL化)
    for pid, plan in list(existing_plans.items()):
        if pid not in submitted_ids:
            db.session.delete(plan)

    # 更新 or 新規追加
    for p in submitted_plans:
        if p['id'] is not None and p['id'] in existing_plans:
            existing = existing_plans[p['id']]
            # 別イベントのプランIDを送られても無視 (security)
            if existing.event_id != event.id:
                continue
            existing.name = p['name']
            existing.amount = p['amount']
            existing.sort_order = p['sort_order']
        else:
            db.session.add(EventCollectionPlan(
                event_id=event.id,
                name=p['name'],
                amount=p['amount'],
                sort_order=p['sort_order'],
            ))

    return True, None

@event_bp.route('/list')
def public_events_list():
    """公開設定された、開催予定のイベント一覧を誰でも閲覧できるように表示する"""
    now_utc = datetime.now(timezone.utc)
    page = request.args.get('page', 1, type=int)
    
    # 参加者数をステータス別にカウントする相関サブクエリを作成
    attending_count_subquery = db.session.query(
        func.count(EventParticipant.id)
    ).filter(
        EventParticipant.event_id == Event.id,
        EventParticipant.status == ParticipationStatus.ATTENDING
    ).correlate(Event).as_scalar()

    tentative_count_subquery = db.session.query(
        func.count(EventParticipant.id)
    ).filter(
        EventParticipant.event_id == Event.id,
        EventParticipant.status == ParticipationStatus.TENTATIVE
    ).correlate(Event).as_scalar()

    # メインクエリにサブクエリをカラムとして追加し、イベント情報と参加者数を一括で取得
    events_query = Event.query.options(
        db.joinedload(Event.owner).load_only(User.display_name, User.misskey_username, User.avatar_url) # 主催者情報も効率的に読み込む
    ).add_columns(
        attending_count_subquery.label('attending_count'),
        tentative_count_subquery.label('tentative_count')
    ).filter(
        Event.is_public == True,
        Event.start_datetime >= now_utc
    ).order_by(Event.start_datetime.asc())
    
    events_pagination = events_query.paginate(page=page, per_page=15, error_out=False)
    
    template_name = 'event/public_list_events.html'
    if current_user.is_authenticated and current_user.use_beta_ui:
        template_name = 'beta/public_list_events_beta.html'
    return render_template(template_name, events_pagination=events_pagination)


@event_bp.route('/')
@login_required
def list_events():
    """ログインユーザーが作成したイベントの一覧を表示する"""
    page = request.args.get('page', 1, type=int)
    filter_type = request.args.get('filter', 'upcoming')
    if filter_type not in ('upcoming', 'past', 'all'):
        filter_type = 'upcoming'

    now_utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)

    base_query = Event.query.filter_by(user_id=current_user.id)

    if filter_type == 'upcoming':
        events_query = base_query.filter(Event.start_datetime >= now_utc_naive).order_by(Event.start_datetime.asc())
    elif filter_type == 'past':
        events_query = base_query.filter(Event.start_datetime < now_utc_naive).order_by(Event.start_datetime.desc())
    else:
        events_query = base_query.order_by(Event.start_datetime.desc())

    events_pagination = events_query.paginate(page=page, per_page=10, error_out=False)

    # タブ用件数
    upcoming_count = Event.query.filter_by(user_id=current_user.id).filter(Event.start_datetime >= now_utc_naive).count()
    past_count = Event.query.filter_by(user_id=current_user.id).filter(Event.start_datetime < now_utc_naive).count()
    total_count = upcoming_count + past_count

    template_name = 'event/list_events.html'
    if current_user.use_beta_ui:
        template_name = 'beta/list_events_beta.html'

    return render_template(
        template_name,
        events_pagination=events_pagination,
        filter_type=filter_type,
        upcoming_count=upcoming_count,
        past_count=past_count,
        total_count=total_count,
        now_utc_naive=now_utc_naive,
    )


@event_bp.route('/add', methods=['GET', 'POST'])
@limiter.limit("20 per hour")
@login_required
def add_event():
    """新しいイベントを作成する"""
    # ▼▼▼【追加】チームIDの取得と検証 ▼▼▼
    team_id = request.args.get('team_id', type=int)
    target_team = None
    if team_id:
        target_team = Team.query.get_or_404(team_id)
        # 自分がメンバーでないチームのイベントは作れない
        if current_user not in target_team.members:
            abort(403)
    # ▲▲▲【追加】▲▲▲

    form = EventForm()
    user_motorcycles = Motorcycle.query.filter_by(user_id=current_user.id, is_archived=False).order_by('name').all()
    form.motorcycle_id.choices = [(m.id, m.name) for m in user_motorcycles]
    form.motorcycle_id.choices.insert(0, (0, '--- 車両を関連付けない ---'))

    # ▼▼▼【追加】チームイベント作成時は「公開設定」を強制的にOFFの扱いにするための初期値設定
    if request.method == 'GET' and target_team:
        form.is_public.data = False
    # ▲▲▲【追加】▲▲▲

    if form.validate_on_submit():
        # フォームの入力値はJSTとして解釈し、UTCのnaive datetimeに変換して保存
        start_dt_utc = form.start_datetime.data.replace(tzinfo=JST).astimezone(timezone.utc).replace(tzinfo=None)
        end_dt_utc = form.end_datetime.data.replace(tzinfo=JST).astimezone(timezone.utc).replace(tzinfo=None) if form.end_datetime.data else None

        collection_enabled = bool(form.collection_enabled.data)
        new_event = Event(
            user_id=current_user.id,
            team_id=team_id, # ▼▼▼【追加】チームIDを保存
            motorcycle_id=form.motorcycle_id.data if form.motorcycle_id.data != 0 else None,
            title=form.title.data,
            description=form.description.data,
            location=form.location.data,
            start_datetime=start_dt_utc,
            end_datetime=end_dt_utc,
            # チームイベントなら強制的に非公開(False)、そうでなければフォームの値
            is_public=False if target_team else form.is_public.data,
            collection_enabled=collection_enabled,
            collection_amount=form.collection_amount.data if collection_enabled else None,
            collection_note=form.collection_note.data if collection_enabled else None,
        )
        try:
            db.session.add(new_event)
            db.session.flush()  # plan FK 用に new_event.id を確定

            ok, err = _sync_collection_plans(new_event, request.form)
            if not ok:
                db.session.rollback()
                flash(err, 'danger')
                return render_template('event/event_form.html', form=form, mode='add', target_team=target_team, plans=_plans_from_request(request.form))

            db.session.commit()

            if target_team:
                flash(f'チーム「{target_team.name}」のイベントを作成しました。', 'success')
            else:
                flash('新しいイベントを作成しました。', 'success')

            return redirect(url_for('event.event_detail', event_id=new_event.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error adding new event: {e}", exc_info=True)
            flash('イベントの保存中にエラーが発生しました。', 'danger')

    plans_data = _plans_from_request(request.form) if request.method == 'POST' else []
    return render_template('event/event_form.html', form=form, mode='add', target_team=target_team, plans=plans_data)


@event_bp.route('/<int:event_id>/edit', methods=['GET', 'POST'])
@limiter.limit("30 per hour")
@login_required
def edit_event(event_id):
    """イベントを編集する"""
    event = Event.query.filter_by(id=event_id, user_id=current_user.id).first_or_404()
    form = EventForm(request.form)

    user_motorcycles = Motorcycle.query.filter_by(user_id=current_user.id).order_by('name').all()
    form.motorcycle_id.choices = [(m.id, f"{m.name} (アーカイブ)" if m.is_archived else m.name) for m in user_motorcycles]
    form.motorcycle_id.choices.insert(0, (0, '--- 車両を関連付けない ---'))

    if form.validate_on_submit():
        # フォームの入力値はJSTとして解釈し、UTCのnaive datetimeに変換して保存
        start_dt_utc = form.start_datetime.data.replace(tzinfo=JST).astimezone(timezone.utc).replace(tzinfo=None)
        end_dt_utc = form.end_datetime.data.replace(tzinfo=JST).astimezone(timezone.utc).replace(tzinfo=None) if form.end_datetime.data else None

        event.motorcycle_id = form.motorcycle_id.data if form.motorcycle_id.data != 0 else None
        event.title = form.title.data
        event.description = form.description.data
        event.location = form.location.data
        event.start_datetime = start_dt_utc
        event.end_datetime = end_dt_utc

        # チームイベントの場合は公開設定を変更させない（元のまま or False固定）
        if not event.team_id:
            event.is_public = form.is_public.data

        # 集金設定の更新
        collection_enabled = bool(form.collection_enabled.data)
        event.collection_enabled = collection_enabled
        event.collection_amount = form.collection_amount.data if collection_enabled else None
        event.collection_note = form.collection_note.data if collection_enabled else None

        ok, err = _sync_collection_plans(event, request.form)
        if not ok:
            db.session.rollback()
            flash(err, 'danger')
            return render_template('event/event_form.html', form=form, mode='edit', event=event, plans=_plans_from_request(request.form))

        try:
            db.session.commit()
            flash('イベント情報を更新しました。', 'success')
            return redirect(url_for('event.event_detail', event_id=event.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error editing event {event_id}: {e}", exc_info=True)
            flash('イベントの更新中にエラーが発生しました。', 'danger')

    elif request.method == 'GET':
        form.title.data = event.title
        form.description.data = event.description
        form.location.data = event.location
        form.motorcycle_id.data = event.motorcycle_id
        # DBのnaive datetime (UTC) を明示的にUTCマーキングしてからJSTに変換
        form.start_datetime.data = event.start_datetime.replace(tzinfo=timezone.utc).astimezone(JST)
        if event.end_datetime:
            form.end_datetime.data = event.end_datetime.replace(tzinfo=timezone.utc).astimezone(JST)
        form.is_public.data = event.is_public
        form.collection_enabled.data = event.collection_enabled
        form.collection_amount.data = event.collection_amount
        form.collection_note.data = event.collection_note
    
    if request.method == 'POST':
        plans_data = _plans_from_request(request.form)
    else:
        plans_data = _plans_from_event(event)
    return render_template('event/event_form.html', form=form, mode='edit', event=event, plans=plans_data)


@event_bp.route('/<int:event_id>/delete', methods=['POST'])
@limiter.limit("30 per hour")
@login_required
def delete_event(event_id):
    """イベントを削除する"""
    event = Event.query.filter_by(id=event_id, user_id=current_user.id).first_or_404()
    try:
        db.session.delete(event)
        db.session.commit()
        flash('イベントを削除しました。', 'info')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting event {event_id}: {e}", exc_info=True)
        flash('イベントの削除中にエラーが発生しました。', 'danger')
    return redirect(url_for('event.list_events'))


@event_bp.route('/<int:event_id>')
@login_required
def event_detail(event_id):
    """イベントの詳細ページ"""
    # ▼▼▼【変更】filter_by(user_id=...) を削除し、get_or_404のみにする
    # 作成者以外も（チームメンバーなら）見られるようにするため
    event = Event.query.get_or_404(event_id)
    
    # ▼▼▼【追加】アクセス権限チェック
    # 1. 作成者本人はOK
    # 2. チームイベントの場合、そのチームのメンバーならOK
    is_authorized = False
    if event.user_id == current_user.id:
        is_authorized = True
    elif event.team_id:
        # イベントが属するチームに、現在のユーザーが含まれているか確認
        if event.team.members.filter(User.id == current_user.id).count() > 0:
            is_authorized = True
    
    if not is_authorized:
        abort(403) # 権限なし
    # ▲▲▲【追加】▲▲▲
    
    participants_attending = event.participants.filter_by(status=ParticipationStatus.ATTENDING).order_by(EventParticipant.created_at).all()
    participants_tentative = event.participants.filter_by(status=ParticipationStatus.TENTATIVE).order_by(EventParticipant.created_at).all()
    participants_not_attending = event.participants.filter_by(status=ParticipationStatus.NOT_ATTENDING).order_by(EventParticipant.created_at).all()

    # イベントに紐付いた準備ノートを取得
    is_owner = (event.user_id == current_user.id)
    event_notes = []
    if is_owner:
        event_notes = event.notes.all()

    # 料金プラン一覧 (集金有効時のみ意味を持つ)
    collection_plans = []
    if event.collection_enabled:
        collection_plans = event.collection_plans.order_by(EventCollectionPlan.sort_order, EventCollectionPlan.id).all()

    # 集金集計（主催者のみ・集金有効時のみ意味を持つ）
    collection_summary = None
    if is_owner and event.collection_enabled:
        targets = participants_attending + participants_tentative

        # プラン別集計用バケット (key: plan_id or None)
        buckets = {}  # plan_id -> {name, amount, paid_count, unpaid_count, exempt_count}
        # デフォルト枠 (key: None)
        default_amount = event.collection_amount or 0
        buckets[None] = {
            'plan_id': None,
            'name': 'デフォルト',
            'amount': default_amount,
            'paid_count': 0,
            'unpaid_count': 0,
            'exempt_count': 0,
        }
        for plan in collection_plans:
            buckets[plan.id] = {
                'plan_id': plan.id,
                'name': plan.name,
                'amount': plan.amount,
                'paid_count': 0,
                'unpaid_count': 0,
                'exempt_count': 0,
            }

        paid_count = unpaid_count = exempt_count = 0
        expected_total = collected_total = outstanding_total = 0
        for p in targets:
            key = p.collection_plan_id if p.collection_plan_id in buckets else None
            bucket = buckets[key]
            amount = bucket['amount'] or 0
            if p.payment_status == PaymentStatus.PAID:
                bucket['paid_count'] += 1
                paid_count += 1
                expected_total += amount
                collected_total += amount
            elif p.payment_status == PaymentStatus.UNPAID:
                bucket['unpaid_count'] += 1
                unpaid_count += 1
                expected_total += amount
                outstanding_total += amount
            else:  # EXEMPT
                bucket['exempt_count'] += 1
                exempt_count += 1

        # 表示順: デフォルト → プラン定義順 (使われていないプランは非表示にしない=主催者の確認用)
        plan_breakdown = []
        for key in [None] + [pl.id for pl in collection_plans]:
            b = buckets[key]
            count = b['paid_count'] + b['unpaid_count'] + b['exempt_count']
            if count == 0 and key is None and not collection_plans:
                # プラン未定義時はデフォルトのみ出すので素通し
                pass
            b['count'] = count
            b['expected'] = b['amount'] * (b['paid_count'] + b['unpaid_count'])
            b['collected'] = b['amount'] * b['paid_count']
            b['outstanding'] = b['amount'] * b['unpaid_count']
            plan_breakdown.append(b)

        collection_summary = {
            'total_count': len(targets),
            'paid_count': paid_count,
            'unpaid_count': unpaid_count,
            'exempt_count': exempt_count,
            'expected_total': expected_total,
            'collected_total': collected_total,
            'outstanding_total': outstanding_total,
            'plan_breakdown': plan_breakdown,
        }

    # 走行ログ作成用: 車両未設定でもボタンを表示できるようユーザーの車両リストを取得
    user_motorcycles = []
    if is_owner:
        user_motorcycles = Motorcycle.query.filter_by(
            user_id=current_user.id, is_archived=False
        ).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()

    return render_template(
        'event/event_detail.html',
        event=event,
        participants_attending=participants_attending,
        participants_tentative=participants_tentative,
        participants_not_attending=participants_not_attending,
        ical_available=ICALENDAR_AVAILABLE,
        event_notes=event_notes,
        is_owner=is_owner,
        user_motorcycles=user_motorcycles,
        collection_summary=collection_summary,
        collection_plans=collection_plans,
        PaymentStatus=PaymentStatus,
    )


@event_bp.route('/<int:event_id>/day', methods=['GET'])
@login_required
def day_view(event_id):
    """主催者専用の当日運用ページ (チェックイン+集金、モバイル最適化)"""
    event = Event.query.filter_by(id=event_id, user_id=current_user.id).first_or_404()

    # 表示対象: 参加 + 保留 (不参加は飛ばす)
    participants = event.participants.filter(
        EventParticipant.status.in_([ParticipationStatus.ATTENDING, ParticipationStatus.TENTATIVE])
    ).order_by(EventParticipant.created_at).all()

    # 料金プラン
    collection_plans = []
    if event.collection_enabled:
        collection_plans = event.collection_plans.order_by(EventCollectionPlan.sort_order, EventCollectionPlan.id).all()

    # 集計
    total_count = len(participants)
    checked_in_count = sum(1 for p in participants if p.checked_in_at is not None)

    expected_total = collected_total = outstanding_total = 0
    paid_count = unpaid_count = exempt_count = 0
    if event.collection_enabled:
        for p in participants:
            amount = p.effective_amount or 0
            if p.payment_status == PaymentStatus.PAID:
                paid_count += 1
                expected_total += amount
                collected_total += amount
            elif p.payment_status == PaymentStatus.UNPAID:
                unpaid_count += 1
                expected_total += amount
                outstanding_total += amount
            else:
                exempt_count += 1

    day_summary = {
        'total_count': total_count,
        'checked_in_count': checked_in_count,
        'not_checked_in_count': total_count - checked_in_count,
        'paid_count': paid_count,
        'unpaid_count': unpaid_count,
        'exempt_count': exempt_count,
        'expected_total': expected_total,
        'collected_total': collected_total,
        'outstanding_total': outstanding_total,
    }

    walkin_form = WalkinParticipantForm()
    walkin_form.collection_plan_id.choices = [('', f'デフォルト ({(event.collection_amount or 0):,}円)' if event.collection_enabled else 'なし')] + [
        (str(p.id), f'{p.name} ({p.amount:,}円)') for p in collection_plans
    ]

    return render_template(
        'event/day_view.html',
        event=event,
        participants=participants,
        collection_plans=collection_plans,
        day_summary=day_summary,
        walkin_form=walkin_form,
        PaymentStatus=PaymentStatus,
    )


@event_bp.route('/participant/<int:participant_id>/checkin', methods=['POST'])
@limiter.limit("240 per hour")
@login_required
def update_participant_checkin(participant_id):
    """主催者が参加者のチェックイン状態をトグルする"""
    participant = EventParticipant.query.get_or_404(participant_id)
    event = participant.event

    if event.user_id != current_user.id:
        abort(403)

    action = request.form.get('action', 'toggle')

    try:
        if action == 'check_in':
            participant.checked_in_at = datetime.now(timezone.utc).replace(tzinfo=None)
        elif action == 'check_out':
            participant.checked_in_at = None
        else:  # toggle
            if participant.checked_in_at is None:
                participant.checked_in_at = datetime.now(timezone.utc).replace(tzinfo=None)
            else:
                participant.checked_in_at = None
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating check-in for participant {participant_id}: {e}", exc_info=True)
        flash('チェックイン状態の更新中にエラーが発生しました。', 'danger')

    return _redirect_after_participant_update(event, participant.id)


@event_bp.route('/<int:event_id>/walkin', methods=['POST'])
@limiter.limit("60 per hour")
@login_required
def add_walkin_participant(event_id):
    """主催者が当日モードから飛び入り参加者を追加する (チェックイン済み状態で作成)"""
    event = Event.query.filter_by(id=event_id, user_id=current_user.id).first_or_404()

    form = WalkinParticipantForm()
    # プラン選択肢を組み立て (バリデーション用)
    plans = []
    if event.collection_enabled:
        plans = event.collection_plans.order_by(EventCollectionPlan.sort_order, EventCollectionPlan.id).all()
    form.collection_plan_id.choices = [('', 'デフォルト')] + [(str(p.id), p.name) for p in plans]

    if not form.validate_on_submit():
        for field, errs in form.errors.items():
            for err in errs:
                flash(err, 'danger')
        return redirect(url_for('event.day_view', event_id=event.id))

    name = form.name.data.strip()

    # 名前重複チェック
    if event.participants.filter_by(name=name).first():
        flash(f'「{name}」さんは既に登録されています。', 'warning')
        return redirect(url_for('event.day_view', event_id=event.id))

    # プランIDの解決
    selected_plan_id = None
    if event.collection_enabled:
        raw = (form.collection_plan_id.data or '').strip()
        if raw:
            try:
                pid = int(raw)
                if any(p.id == pid for p in plans):
                    selected_plan_id = pid
            except ValueError:
                selected_plan_id = None

    try:
        new_participant = EventParticipant(
            event_id=event.id,
            name=name,
            status=ParticipationStatus.ATTENDING,
            vehicle_name=form.vehicle_name.data or None,
            checked_in_at=datetime.now(timezone.utc).replace(tzinfo=None),
            collection_plan_id=selected_plan_id if event.collection_enabled else None,
        )
        db.session.add(new_participant)
        db.session.commit()
        flash(f'飛び入り参加者「{name}」さんを追加・チェックインしました。', 'success')
    except IntegrityError:
        db.session.rollback()
        flash('その名前は既に使用されています。', 'danger')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error adding walk-in participant: {e}", exc_info=True)
        flash('参加者の追加中にエラーが発生しました。', 'danger')

    return redirect(url_for('event.day_view', event_id=event.id))


@event_bp.route('/public/<public_id>', methods=['GET', 'POST'])
@limiter.limit("15 per minute", methods=["POST"])
def public_event_view(public_id):
    """公開イベントページ（ログイン不要・ログイン時はユーザー連携）"""
    event = Event.query.filter_by(public_id=public_id).first_or_404()
    form = ParticipantForm()

    # 料金プランの選択肢 (集金有効時のみ)
    event_plans = []
    if event.collection_enabled:
        event_plans = event.collection_plans.order_by(EventCollectionPlan.sort_order, EventCollectionPlan.id).all()
    default_amount = event.collection_amount or 0
    default_label = f'デフォルト ({default_amount:,}円)' if event.collection_enabled else 'デフォルト'
    form.collection_plan_id.choices = [('', default_label)] + [
        (str(p.id), f'{p.name} ({p.amount:,}円)') for p in event_plans
    ]

    # ログインユーザーの場合の初期値設定とバリデーション調整
    if current_user.is_authenticated:
        # ログインユーザーとしての参加記録を探す
        current_participant = event.participants.filter_by(user_id=current_user.id).first()
        
        # フォームの必須バリデーションを無効化 (ユーザー情報は自動設定するため)
        form.name.validators = [Optional()]
        form.passcode.validators = [Optional()]

        # GETリクエストかつ、まだフォーム送信されていない場合、初期値をセット
        if request.method == 'GET' and not form.vehicle_name.data:
            if current_participant:
                # 既に参加済みならその情報をセット
                form.status.data = current_participant.status.value
                form.vehicle_name.data = current_participant.vehicle_name
                form.comment.data = current_participant.comment
                form.collection_plan_id.data = str(current_participant.collection_plan_id) if current_participant.collection_plan_id else ''
            else:
                # 未参加ならデフォルト情報をセット
                form.status.data = 'attending'
                # デフォルト車両があればセット (ガレージのヒーロー車両など)
                if current_user.garage_hero_vehicle_id:
                     hero_bike = Motorcycle.query.get(current_user.garage_hero_vehicle_id)
                     if hero_bike:
                         form.vehicle_name.data = hero_bike.name

    if form.validate_on_submit():
        status = form.status.data
        comment = form.comment.data
        vehicle_name = form.vehicle_name.data

        # 料金プランIDの解決 (集金有効時のみ意味を持つ)
        selected_plan_id = None
        if event.collection_enabled:
            raw_plan_id = (form.collection_plan_id.data or '').strip()
            if raw_plan_id:
                try:
                    pid = int(raw_plan_id)
                    if any(p.id == pid for p in event_plans):
                        selected_plan_id = pid
                except ValueError:
                    selected_plan_id = None

        # --- A. ログインユーザーの処理 ---
        if current_user.is_authenticated:
            # ▼▼▼【変更】名前属性を変更して受け取る ▼▼▼
            claim_name = request.form.get('claim_name')
            claim_passcode = request.form.get('claim_passcode')
            
            if claim_name and claim_passcode:
                # ゲスト統合モード
                target_participant = event.participants.filter_by(name=claim_name).first()
                if target_participant:
                    if target_participant.user_id is not None and target_participant.user_id != current_user.id:
                        flash('その参加者は既に別のユーザーアカウントに紐づけられています。', 'danger')
                    elif target_participant.check_passcode(claim_passcode):
                        # ▼▼▼【変更】認証成功：過去のデータを削除して、新規登録フローへ流す ▼▼▼
                        db.session.delete(target_participant)
                        db.session.commit()
                        flash(f'過去のゲスト参加データ（{claim_name}）を削除し、このアカウントで紐付け登録しました。', 'success')
                        # ここでreturnせず、下の「通常のログイン参加処理」へ進むことで、
                        # フォームに入力された最新の状態（status/comment/vehicle）で新規作成（または更新）される
                    else:
                        flash('パスコードが正しくありません。', 'danger')
                        return redirect(url_for('event.public_event_view', public_id=public_id))
                else:
                    flash('指定された名前の参加者が見つかりません。', 'warning')
                    return redirect(url_for('event.public_event_view', public_id=public_id))
            # ▲▲▲【変更】ここまで ▲▲▲

            # 通常のログイン参加/更新処理 (名前・パスコード入力なし)
            participant = event.participants.filter_by(user_id=current_user.id).first()
            
            if status == 'delete':
                if participant:
                    db.session.delete(participant)
                    db.session.commit()
                    flash('参加登録を取り消しました。', 'info')
                else:
                    flash('まだ参加登録されていません。', 'warning')
            else:
                # 表示名の決定 (Display Name > Misskey Username)
                user_name = current_user.display_name or current_user.misskey_username

                if participant:
                    # 更新
                    participant.status = ParticipationStatus(status)
                    participant.comment = comment
                    participant.vehicle_name = vehicle_name
                    participant.name = user_name # 名前も最新のユーザー名に同期
                    if event.collection_enabled:
                        participant.collection_plan_id = selected_plan_id
                    flash('出欠情報を更新しました。', 'success')
                else:
                    # 新規作成
                    # 名前重複チェック (自分以外に同名のゲストがいる場合)
                    conflict_participant = event.participants.filter_by(name=user_name).first()
                    if conflict_participant:
                        # 同名のゲストがいる場合、それは「かつての自分」か「他人」か判断できないため、警告を出す
                        flash(f'名前「{user_name}」は既にゲスト参加者として登録されています。もしこれが過去のあなたなら、下の「過去のゲスト登録を紐付ける」からパスコードを入力して統合してください。別人であれば、プロフィール設定から表示名を変更してください。', 'warning')
                        return redirect(url_for('event.public_event_view', public_id=public_id))

                    new_participant = EventParticipant(
                        event_id=event.id,
                        user_id=current_user.id,
                        name=user_name,
                        status=ParticipationStatus(status),
                        comment=comment,
                        vehicle_name=vehicle_name,
                        passcode_hash=None, # ログインユーザーはパスコード不要
                        collection_plan_id=selected_plan_id if event.collection_enabled else None,
                    )
                    db.session.add(new_participant)
                    # メッセージ重複回避のため、統合処理直後でない場合のみ表示
                    if not (claim_name and claim_passcode):
                         flash('イベントに参加登録しました。', 'success')
                
                db.session.commit()

        # --- B. 未ログイン(ゲスト)の処理 ---
        else:
            participant_name = form.name.data
            passcode = form.passcode.data
            
            # ゲストは名前とパスコード必須 (フォームクラスのデフォルトバリデータが効いているが念のため)
            if not participant_name or not passcode:
                flash('名前とパスコードを入力してください。', 'danger')
                return redirect(url_for('event.public_event_view', public_id=public_id))

            existing_participant = event.participants.filter_by(name=participant_name).first()

            try:
                if existing_participant:
                    # 既存データがユーザー紐付け済みの場合、ゲストとしての変更は許可しない（ログインを促す）
                    if existing_participant.user_id is not None:
                        flash(f'「{participant_name}」さんは登録ユーザーです。変更するにはログインしてください。', 'warning')
                        return redirect(url_for('auth.login', next=request.url))

                    if not existing_participant.check_passcode(passcode):
                        flash('パスコードが正しくありません。', 'danger')
                        return redirect(url_for('event.public_event_view', public_id=public_id))

                    if status == 'delete':
                        db.session.delete(existing_participant)
                        flash(f'「{participant_name}」さんの参加登録を取り消しました。', 'info')
                    else:
                        existing_participant.status = ParticipationStatus(status)
                        existing_participant.comment = comment
                        existing_participant.vehicle_name = vehicle_name
                        if event.collection_enabled:
                            existing_participant.collection_plan_id = selected_plan_id
                        flash(f'「{participant_name}」さんの出欠情報を更新しました。', 'success')
                else:
                    if status == 'delete':
                        flash('まだ参加登録されていません。', 'warning')
                        return redirect(url_for('event.public_event_view', public_id=public_id))

                    new_participant = EventParticipant(
                        event_id=event.id,
                        name=participant_name,
                        status=ParticipationStatus(status),
                        comment=comment,
                        vehicle_name=vehicle_name,
                        collection_plan_id=selected_plan_id if event.collection_enabled else None,
                    )
                    new_participant.set_passcode(passcode)
                    db.session.add(new_participant)
                    flash(f'「{participant_name}」さんの出欠を登録しました。', 'success')
                
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash('その名前は既に使用されています。別の名前を使用してください。', 'danger')
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error registering participant: {e}", exc_info=True)
                flash('エラーが発生しました。', 'danger')

        return redirect(url_for('event.public_event_view', public_id=public_id))

    # 表示用データの取得
    participants_attending = event.participants.filter_by(status=ParticipationStatus.ATTENDING).order_by(EventParticipant.created_at).all()
    participants_tentative = event.participants.filter_by(status=ParticipationStatus.TENTATIVE).order_by(EventParticipant.created_at).all()
    participants_not_attending = event.participants.filter_by(status=ParticipationStatus.NOT_ATTENDING).order_by(EventParticipant.created_at).all()

    return render_template(
        'event/public_event_view.html',
        event=event,
        form=form,
        participants_attending=participants_attending,
        participants_tentative=participants_tentative,
        participants_not_attending=participants_not_attending,
        event_plans=event_plans,
    )


@event_bp.route('/participant/<int:participant_id>/payment', methods=['POST'])
@limiter.limit("120 per hour")
@login_required
def update_participant_payment(participant_id):
    """主催者が参加者の支払いステータスを更新する"""
    participant = EventParticipant.query.get_or_404(participant_id)
    event = participant.event

    if event.user_id != current_user.id:
        abort(403)

    if not event.collection_enabled:
        flash('このイベントは集金が有効ではありません。', 'warning')
        return _redirect_after_participant_update(event, participant.id)

    new_status_value = request.form.get('payment_status')
    try:
        new_status = PaymentStatus(new_status_value)
    except ValueError:
        flash('不正な支払いステータスです。', 'danger')
        return _redirect_after_participant_update(event, participant.id)

    try:
        participant.payment_status = new_status
        if new_status == PaymentStatus.PAID:
            participant.paid_at = datetime.now(timezone.utc).replace(tzinfo=None)
        else:
            participant.paid_at = None
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating payment status for participant {participant_id}: {e}", exc_info=True)
        flash('支払いステータスの更新中にエラーが発生しました。', 'danger')

    return _redirect_after_participant_update(event, participant.id)


@event_bp.route('/participant/<int:participant_id>/plan', methods=['POST'])
@limiter.limit("120 per hour")
@login_required
def update_participant_plan(participant_id):
    """主催者が参加者の料金プランを変更する"""
    participant = EventParticipant.query.get_or_404(participant_id)
    event = participant.event

    if event.user_id != current_user.id:
        abort(403)
    if not event.collection_enabled:
        flash('このイベントは集金が有効ではありません。', 'warning')
        return _redirect_after_participant_update(event, participant.id)

    raw_plan_id = request.form.get('collection_plan_id', '').strip()
    new_plan_id = None
    if raw_plan_id:
        try:
            new_plan_id = int(raw_plan_id)
        except ValueError:
            flash('不正なプラン指定です。', 'danger')
            return _redirect_after_participant_update(event, participant.id)
        # 指定プランが本イベントのものか検証
        plan = EventCollectionPlan.query.filter_by(id=new_plan_id, event_id=event.id).first()
        if not plan:
            flash('指定された料金プランが見つかりません。', 'danger')
            return _redirect_after_participant_update(event, participant.id)

    try:
        participant.collection_plan_id = new_plan_id
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating plan for participant {participant_id}: {e}", exc_info=True)
        flash('プランの更新中にエラーが発生しました。', 'danger')

    return _redirect_after_participant_update(event, participant.id)


@event_bp.route('/<int:event_id>/payments/bulk', methods=['POST'])
@limiter.limit("30 per hour")
@login_required
def bulk_update_payments(event_id):
    """主催者が一括で支払いステータスを変更する (全員未払い化など)"""
    event = Event.query.get_or_404(event_id)
    if event.user_id != current_user.id:
        abort(403)
    if not event.collection_enabled:
        flash('このイベントは集金が有効ではありません。', 'warning')
        return _redirect_after_participant_update(event)

    action = request.form.get('action')
    target_statuses = [ParticipationStatus.ATTENDING, ParticipationStatus.TENTATIVE]

    try:
        participants = event.participants.filter(EventParticipant.status.in_(target_statuses)).all()
        if action == 'reset_unpaid':
            for p in participants:
                p.payment_status = PaymentStatus.UNPAID
                p.paid_at = None
            flash('支払い状況をすべて「未払い」にリセットしました。', 'info')
        else:
            flash('不正な操作です。', 'danger')
            return _redirect_after_participant_update(event)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error bulk updating payments for event {event_id}: {e}", exc_info=True)
        flash('一括更新中にエラーが発生しました。', 'danger')

    return _redirect_after_participant_update(event)


@event_bp.route('/participant/<int:participant_id>/delete', methods=['POST'])
@limiter.limit("30 per hour")
@login_required
def delete_participant(participant_id):
    """主催者が参加者を削除する"""
    participant = EventParticipant.query.get_or_404(participant_id)
    event = participant.event
    
    if event.user_id != current_user.id:
        abort(403)
        
    try:
        db.session.delete(participant)
        db.session.commit()
        flash(f'参加者「{participant.name}」を削除しました。', 'info')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting participant {participant_id} by owner: {e}", exc_info=True)
        flash('参加者の削除中にエラーが発生しました。', 'danger')
        
    return redirect(url_for('event.event_detail', event_id=event.id))


@event_bp.route('/<int:event_id>/export.ics')
@login_required
def export_ics(event_id):
    """iCal形式でイベントをエクスポートする"""
    if not ICALENDAR_AVAILABLE:
        flash('カレンダーエクスポート機能は現在利用できません。', 'danger')
        return redirect(url_for('event.event_detail', event_id=event_id))

    event = Event.query.filter_by(id=event_id, user_id=current_user.id).first_or_404()

    cal = Calendar()
    cal.add('prodid', '-//もとぷっぷー Event//motopuppu.app//')
    cal.add('version', '2.0')

    ical_event = ICalEvent()
    ical_event.add('summary', event.title)
    ical_event.add('dtstart', event.start_datetime)
    if event.end_datetime:
        ical_event.add('dtend', event.end_datetime)
    ical_event.add('dtstamp', datetime.now(timezone.utc))
    ical_event.add('uid', f'event-{event.public_id}@motopuppu.app')
    
    if event.location:
        ical_event.add('location', event.location)
    
    description = ""
    if event.description:
        description += event.description + "\n\n"
    
    public_url = url_for('event.public_event_view', public_id=event.public_id, _external=True)
    description += f"イベントページ: {public_url}"
    ical_event.add('description', description)

    cal.add_component(ical_event)

    filename = f"event_{event.id}.ics"
    return Response(
        cal.to_ical(),
        mimetype='text/calendar',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )