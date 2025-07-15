# motopuppu/views/event.py
from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, abort, Response, current_app
)
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone

from .auth import login_required_custom
from ..models import db, Event, EventParticipant, Motorcycle, ParticipationStatus
from ..forms import EventForm, ParticipantForm
from ..utils.datetime_helpers import JST

# iCalenderライブラリのインポート
try:
    from icalendar import Calendar, Event as ICalEvent
    ICALENDAR_AVAILABLE = True
except ImportError:
    ICALENDAR_AVAILABLE = False


event_bp = Blueprint('event', __name__, url_prefix='/event')

@event_bp.route('/')
@login_required_custom
def list_events():
    """ログインユーザーが作成したイベントの一覧を表示する"""
    page = request.args.get('page', 1, type=int)
    # 日付が新しい順にイベントを並べる
    events_pagination = Event.query.filter_by(user_id=g.user.id).order_by(Event.start_datetime.desc()).paginate(page=page, per_page=10, error_out=False)
    
    return render_template('event/list_events.html', events_pagination=events_pagination)


@event_bp.route('/add', methods=['GET', 'POST'])
@login_required_custom
def add_event():
    """新しいイベントを作成する"""
    form = EventForm()
    # ユーザーが所有する車両をドロップダウンにセット
    form.motorcycle_id.choices = [(m.id, m.name) for m in Motorcycle.query.filter_by(user_id=g.user.id).order_by('name')]
    form.motorcycle_id.choices.insert(0, (0, '--- 車両を関連付けない ---'))

    if form.validate_on_submit():
        # フォームから受け取った日時はNaiveなので、JSTとして解釈し、UTCに変換してDBに保存
        start_dt_utc = form.start_datetime.data.replace(tzinfo=JST).astimezone(timezone.utc)
        end_dt_utc = form.end_datetime.data.replace(tzinfo=JST).astimezone(timezone.utc) if form.end_datetime.data else None

        new_event = Event(
            user_id=g.user.id,
            motorcycle_id=form.motorcycle_id.data if form.motorcycle_id.data != 0 else None,
            title=form.title.data,
            description=form.description.data,
            location=form.location.data,
            start_datetime=start_dt_utc,
            end_datetime=end_dt_utc
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
@login_required_custom
def edit_event(event_id):
    """イベントを編集する"""
    event = Event.query.filter_by(id=event_id, user_id=g.user.id).first_or_404()
    form = EventForm(obj=event)

    form.motorcycle_id.choices = [(m.id, m.name) for m in Motorcycle.query.filter_by(user_id=g.user.id).order_by('name')]
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
        try:
            db.session.commit()
            flash('イベント情報を更新しました。', 'success')
            return redirect(url_for('event.event_detail', event_id=event.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error editing event {event_id}: {e}", exc_info=True)
            flash('イベントの更新中にエラーが発生しました。', 'danger')

    # GETリクエスト時、DBのUTC時刻をJSTに変換してフォームにセット
    form.start_datetime.data = event.start_datetime.astimezone(JST)
    if event.end_datetime:
        form.end_datetime.data = event.end_datetime.astimezone(JST)
    
    return render_template('event/event_form.html', form=form, mode='edit', event=event)


@event_bp.route('/<int:event_id>/delete', methods=['POST'])
@login_required_custom
def delete_event(event_id):
    """イベントを削除する"""
    event = Event.query.filter_by(id=event_id, user_id=g.user.id).first_or_404()
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
@login_required_custom
def event_detail(event_id):
    """イベントの詳細ページ（作成者向け）"""
    event = Event.query.filter_by(id=event_id, user_id=g.user.id).first_or_404()
    
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
def public_event_view(public_id):
    """公開イベントページ（ログイン不要）"""
    event = Event.query.filter_by(public_id=public_id).first_or_404()
    form = ParticipantForm()

    if form.validate_on_submit():
        participant_name = form.name.data
        passcode = form.passcode.data
        status = form.status.data
        existing_participant = event.participants.filter_by(name=participant_name).first()

        try:
            if existing_participant:
                # --- ▼▼▼ ここから修正 ▼▼▼ ---
                # 既存参加者の処理
                if not existing_participant.check_passcode(passcode):
                    flash('パスコードが正しくありません。', 'danger')
                    return redirect(url_for('event.public_event_view', public_id=public_id))

                if status == 'delete':
                    # 参加取り消しの場合
                    db.session.delete(existing_participant)
                    db.session.commit()
                    flash(f'「{participant_name}」さんの参加登録を取り消しました。', 'info')
                else:
                    # ステータス更新の場合
                    existing_participant.status = ParticipationStatus(status)
                    db.session.commit()
                    flash(f'「{participant_name}」さんの出欠を更新しました。', 'success')
                # --- ▲▲▲ 修正ここまで ▲▲▲ ---
            else:
                # 新規作成の場合
                if status == 'delete':
                    flash('まだ参加登録されていません。', 'warning')
                    return redirect(url_for('event.public_event_view', public_id=public_id))

                new_participant = EventParticipant(
                    event_id=event.id,
                    name=participant_name,
                    status=ParticipationStatus(status)
                )
                new_participant.set_passcode(passcode)
                db.session.add(new_participant)
                db.session.commit()
                flash(f'「{participant_name}」さんの出欠を登録しました。ありがとうございます！', 'success')

        except IntegrityError:
            db.session.rollback()
            flash('出欠の登録に失敗しました。同じ名前の参加者が既に登録されている可能性があります。', 'danger')
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
@login_required_custom
def delete_participant(participant_id):
    """主催者が参加者を削除する"""
    participant = EventParticipant.query.get_or_404(participant_id)
    event = participant.event
    
    # この操作を実行しようとしているのが、本当にイベントの主催者か確認
    if event.user_id != g.user.id:
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
@login_required_custom
def export_ics(event_id):
    """iCal形式でイベントをエクスポートする"""
    if not ICALENDAR_AVAILABLE:
        flash('カレンダーエクスポート機能は現在利用できません。', 'danger')
        return redirect(url_for('event.event_detail', event_id=event_id))

    event = Event.query.filter_by(id=event_id, user_id=g.user.id).first_or_404()

    cal = Calendar()
    cal.add('prodid', '-//もとぷっぷー Event//motopuppu.app//')
    cal.add('version', '2.0')

    ical_event = ICalEvent()
    ical_event.add('summary', event.title)
    # iCalのDATETIMEはUTCである必要がある
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