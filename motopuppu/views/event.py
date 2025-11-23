# motopuppu/views/event.py
from flask import (
    Blueprint, flash, redirect, render_template, request, url_for, abort, Response, current_app
)
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone, date
from sqlalchemy import func
from flask_login import login_required, current_user
from wtforms.validators import Optional
from ..models import db, Event, EventParticipant, Motorcycle, ParticipationStatus, User, Team
from ..forms import EventForm, ParticipantForm
from ..utils.datetime_helpers import JST
from .. import limiter

# iCalenderライブラリのインポート
try:
    from icalendar import Calendar, Event as ICalEvent
    ICALENDAR_AVAILABLE = True
except ImportError:
    ICALENDAR_AVAILABLE = False


event_bp = Blueprint('event', __name__, url_prefix='/event')

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
    
    return render_template('event/public_list_events.html', events_pagination=events_pagination)


@event_bp.route('/')
@login_required
def list_events():
    """ログインユーザーが作成したイベントの一覧を表示する"""
    page = request.args.get('page', 1, type=int)
    events_pagination = Event.query.filter_by(user_id=current_user.id).order_by(Event.start_datetime.desc()).paginate(page=page, per_page=10, error_out=False)
    
    return render_template('event/list_events.html', events_pagination=events_pagination)


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
    form.motorcycle_id.choices = [(m.id, m.name) for m in Motorcycle.query.filter_by(user_id=current_user.id).order_by('name')]
    form.motorcycle_id.choices.insert(0, (0, '--- 車両を関連付けない ---'))

    # ▼▼▼【追加】チームイベント作成時は「公開設定」を強制的にOFFの扱いにするための初期値設定
    if request.method == 'GET' and target_team:
        form.is_public.data = False
    # ▲▲▲【追加】▲▲▲

    if form.validate_on_submit():
        start_dt_utc = form.start_datetime.data.replace(tzinfo=JST).astimezone(timezone.utc)
        end_dt_utc = form.end_datetime.data.replace(tzinfo=JST).astimezone(timezone.utc) if form.end_datetime.data else None

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
            is_public=False if target_team else form.is_public.data
        )
        try:
            db.session.add(new_event)
            db.session.commit()
            
            # ▼▼▼【追加】リダイレクト先の調整
            if target_team:
                flash(f'チーム「{target_team.name}」のイベントを作成しました。', 'success')
            else:
                flash('新しいイベントを作成しました。', 'success')
            # ▲▲▲

            return redirect(url_for('event.event_detail', event_id=new_event.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error adding new event: {e}", exc_info=True)
            flash('イベントの保存中にエラーが発生しました。', 'danger')

    return render_template('event/event_form.html', form=form, mode='add', target_team=target_team)


@event_bp.route('/<int:event_id>/edit', methods=['GET', 'POST'])
@limiter.limit("30 per hour")
@login_required
def edit_event(event_id):
    """イベントを編集する"""
    event = Event.query.filter_by(id=event_id, user_id=current_user.id).first_or_404()
    form = EventForm(request.form)

    form.motorcycle_id.choices = [(m.id, m.name) for m in Motorcycle.query.filter_by(user_id=current_user.id).order_by('name')]
    form.motorcycle_id.choices.insert(0, (0, '--- 車両を関連付けない ---'))

    if form.validate_on_submit():
        start_dt_utc = form.start_datetime.data.replace(tzinfo=JST).astimezone(timezone.utc)
        end_dt_utc = form.end_datetime.data.replace(tzinfo=JST).astimezone(timezone.utc) if form.end_datetime.data else None

        event.motorcycle_id = form.motorcycle_id.data if form.motorcycle_id.data != 0 else None
        event.title = form.title.data
        event.description = form.description.data
        event.location = form.location.data
        event.start_datetime = start_dt_utc
        event.end_datetime = end_dt_utc
        
        # チームイベントの場合は公開設定を変更させない（元のまま or False固定）
        if not event.team_id:
            event.is_public = form.is_public.data

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
        form.start_datetime.data = event.start_datetime.astimezone(JST)
        if event.end_datetime:
            form.end_datetime.data = event.end_datetime.astimezone(JST)
        form.is_public.data = event.is_public
    
    return render_template('event/event_form.html', form=form, mode='edit', event=event)


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

    return render_template(
        'event/event_detail.html', 
        event=event,
        participants_attending=participants_attending,
        participants_tentative=participants_tentative,
        participants_not_attending=participants_not_attending,
        ical_available=ICALENDAR_AVAILABLE
    )


@event_bp.route('/public/<public_id>', methods=['GET', 'POST'])
@limiter.limit("15 per minute", methods=["POST"])
def public_event_view(public_id):
    """公開イベントページ（ログイン不要・ログイン時はユーザー連携）"""
    event = Event.query.filter_by(public_id=public_id).first_or_404()
    form = ParticipantForm()

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
                        passcode_hash=None # ログインユーザーはパスコード不要
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
                        vehicle_name=vehicle_name
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
        participants_not_attending=participants_not_attending
    )


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
        description += event.description + "\\n\\n"
    
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