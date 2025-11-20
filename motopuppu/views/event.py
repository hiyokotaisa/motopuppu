# motopuppu/views/event.py
from flask import (
    Blueprint, flash, redirect, render_template, request, url_for, abort, Response, current_app
)
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone, date
from sqlalchemy import func
from flask_login import login_required, current_user
from ..models import db, Event, EventParticipant, Motorcycle, ParticipationStatus, User
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
    form = EventForm()
    form.motorcycle_id.choices = [(m.id, m.name) for m in Motorcycle.query.filter_by(user_id=current_user.id).order_by('name')]
    form.motorcycle_id.choices.insert(0, (0, '--- 車両を関連付けない ---'))

    if form.validate_on_submit():
        start_dt_utc = form.start_datetime.data.replace(tzinfo=JST).astimezone(timezone.utc)
        end_dt_utc = form.end_datetime.data.replace(tzinfo=JST).astimezone(timezone.utc) if form.end_datetime.data else None

        new_event = Event(
            user_id=current_user.id,
            motorcycle_id=form.motorcycle_id.data if form.motorcycle_id.data != 0 else None,
            title=form.title.data,
            description=form.description.data,
            location=form.location.data,
            start_datetime=start_dt_utc,
            end_datetime=end_dt_utc,
            is_public=form.is_public.data
        )
        try:
            db.session.add(new_event)
            db.session.commit()
            flash('新しいイベントを作成しました。', 'success')
            return redirect(url_for('event.event_detail', event_id=new_event.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error adding new event: {e}", exc_info=True)
            flash('イベントの保存中にエラーが発生しました。', 'danger')

    return render_template('event/event_form.html', form=form, mode='add')


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
    """イベントの詳細ページ（作成者向け）"""
    event = Event.query.filter_by(id=event_id, user_id=current_user.id).first_or_404()
    
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
    """公開イベントページ（ログイン不要）"""
    event = Event.query.filter_by(public_id=public_id).first_or_404()
    form = ParticipantForm()

    if form.validate_on_submit():
        participant_name = form.name.data
        passcode = form.passcode.data
        status = form.status.data
        comment = form.comment.data
        # ▼▼▼【ここから追記】▼▼▼
        vehicle_name = form.vehicle_name.data
        # ▲▲▲【追記ここまで】▲▲▲
        
        existing_participant = event.participants.filter_by(name=participant_name).first()

        try:
            if existing_participant:
                if not existing_participant.check_passcode(passcode):
                    flash('パスコードが正しくありません。', 'danger')
                    return redirect(url_for('event.public_event_view', public_id=public_id))

                if status == 'delete':
                    db.session.delete(existing_participant)
                    flash(f'「{participant_name}」さんの参加登録を取り消しました。', 'info')
                else:
                    existing_participant.status = ParticipationStatus(status)
                    existing_participant.comment = comment
                    # ▼▼▼【ここから追記】▼▼▼
                    existing_participant.vehicle_name = vehicle_name
                    # ▲▲▲【追記ここまで】▲▲▲
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
                    # ▼▼▼【ここから追記】▼▼▼
                    vehicle_name=vehicle_name
                    # ▲▲▲【追記ここまで】▲▲▲
                )
                new_participant.set_passcode(passcode)
                db.session.add(new_participant)
                flash(f'「{participant_name}」さんの出欠を登録しました。ありがとうございます！', 'success')
            
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            # ▼▼▼【ここから修正】エラーメッセージを具体化 ▼▼▼
            flash('その名前は既に使用されています。別のニックネーム（例: Taro_H）を使用してください。', 'danger')
            # ▲▲▲【修正ここまで】▲▲▲
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error registering participant for event public_id {public_id}: {e}", exc_info=True)
            flash('出欠の登録中にエラーが発生しました。', 'danger')

        return redirect(url_for('event.public_event_view', public_id=public_id))

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

    return Response(
        cal.to_ical(),
        mimetype='text/calendar',
        headers={'Content-Disposition': f'attachment; filename="event_{event.id}.ics"'}
    )