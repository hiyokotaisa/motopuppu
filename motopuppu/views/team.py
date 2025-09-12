# motopuppu/views/team.py
from flask import (
    Blueprint, render_template, request, flash, redirect, url_for, abort, current_app
)
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from sqlalchemy import func
import uuid

from .. import db, limiter
# Motorcycle モデルをインポート
from ..models import Team, User, ActivityLog, SessionLog, Motorcycle
from ..forms import TeamForm
from ..utils.lap_time_utils import format_seconds_to_time

team_bp = Blueprint(
    'team',
    __name__,
    template_folder='../../templates',
    url_prefix='/teams'
)


@team_bp.route('/')
@login_required
def list_teams():
    """ユーザーが所属するチームの一覧を表示する"""
    teams = current_user.teams.order_by(Team.name.asc()).all()
    return render_template('team/list_teams.html', teams=teams)


@team_bp.route('/create', methods=['GET', 'POST'])
@login_required
@limiter.limit("10 per hour")
def create_team():
    """新しいチームを作成する"""
    form = TeamForm()
    if form.validate_on_submit():
        new_team = Team(
            name=form.name.data,
            owner_id=current_user.id
        )
        new_team.members.append(current_user)
        db.session.add(new_team)
        try:
            db.session.commit()
            flash(f'チーム「{new_team.name}」を作成しました。', 'success')
            return redirect(url_for('team.manage_team', team_id=new_team.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating team: {e}", exc_info=True)
            flash('チームの作成中にエラーが発生しました。', 'danger')
    return render_template('team/team_form.html', form=form, form_action='create')


# ▼▼▼【ここから追記】チーム名編集のルート ▼▼▼
@team_bp.route('/<int:team_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_team(team_id):
    """チーム名を編集する（オーナーのみ）"""
    team = Team.query.get_or_404(team_id)
    if team.owner_id != current_user.id:
        abort(403)

    form = TeamForm(obj=team)
    form.submit.label.text = '更新する' # ボタンのテキストを変更

    if form.validate_on_submit():
        original_name = team.name
        team.name = form.name.data
        try:
            db.session.commit()
            flash(f'チーム名を「{original_name}」から「{team.name}」に変更しました。', 'success')
            return redirect(url_for('team.manage_team', team_id=team.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error editing team {team_id}: {e}", exc_info=True)
            flash('チーム名の更新中にエラーが発生しました。', 'danger')

    return render_template('team/team_form.html', form=form, form_action='edit', team=team)
# ▲▲▲【追記はここまで】▲▲▲


@team_bp.route('/<int:team_id>/manage')
@login_required
def manage_team(team_id):
    """チームの管理ページ（オーナーのみアクセス可能）"""
    team = Team.query.get_or_404(team_id)
    if team.owner_id != current_user.id:
        abort(403)

    members = team.members.order_by(User.display_name.asc()).all()
    invite_url = url_for('team.join_team', token=team.invite_token, _external=True)
    
    return render_template('team/manage_team.html', team=team, invite_url=invite_url, members=members)


@team_bp.route('/join/<token>', methods=['GET', 'POST'])
@login_required
def join_team(token):
    """招待トークンを使ってチームに参加する"""
    team = Team.query.filter_by(invite_token=token).first_or_404()

    if current_user in team.members:
        flash('すでにこのチームのメンバーです。', 'info')
        return redirect(url_for('team.dashboard', team_id=team.id))

    if request.method == 'POST':
        team.members.append(current_user)
        try:
            db.session.commit()
            flash(f'チーム「{team.name}」に参加しました！', 'success')
            return redirect(url_for('team.dashboard', team_id=team.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error joining team: {e}", exc_info=True)
            flash('チームへの参加中にエラーが発生しました。', 'danger')
            return redirect(url_for('team.list_teams'))

    return render_template('team/join_team.html', team=team)


@team_bp.route('/<int:team_id>/dashboard')
@login_required
def dashboard(team_id):
    """チームのダッシュボードを表示する"""
    team = Team.query.get_or_404(team_id)
    if current_user not in team.members:
        abort(403)

    member_ids = [member.id for member in team.members]

    # --- ベストタイムランキングの処理 (変更なし) ---
    best_lap_subquery = db.session.query(
        ActivityLog.user_id,
        ActivityLog.circuit_name,
        func.min(SessionLog.best_lap_seconds).label('personal_best')
    ).join(
        SessionLog, ActivityLog.id == SessionLog.activity_log_id
    ).filter(
        ActivityLog.user_id.in_(member_ids),
        ActivityLog.circuit_name.isnot(None),
        SessionLog.best_lap_seconds.isnot(None)
    ).group_by(
        ActivityLog.user_id,
        ActivityLog.circuit_name
    ).subquery()

    circuit_rankings_query = db.session.query(
        User,
        best_lap_subquery.c.circuit_name,
        best_lap_subquery.c.personal_best
    ).join(
        best_lap_subquery, User.id == best_lap_subquery.c.user_id
    ).order_by(
        best_lap_subquery.c.circuit_name.asc(),
        best_lap_subquery.c.personal_best.asc()
    ).all()

    circuit_data = {}
    for user, circuit_name, personal_best in circuit_rankings_query:
        if circuit_name not in circuit_data:
            circuit_data[circuit_name] = []
        circuit_data[circuit_name].append({
            'user': user,
            'best_lap': personal_best
        })

    members = team.members.order_by(User.display_name.asc()).all()
    
    # ▼▼▼【ここから追記】チームメンバーの最新活動ログを取得 ▼▼▼
    recent_activities = ActivityLog.query.options(
        joinedload(ActivityLog.user),
        joinedload(ActivityLog.motorcycle)
    ).filter(
        ActivityLog.user_id.in_(member_ids)
    ).order_by(
        ActivityLog.activity_date.desc(),
        ActivityLog.created_at.desc()
    ).limit(15).all()
    # ▲▲▲【追記はここまで】▲▲▲

    return render_template(
        'team/team_dashboard.html',
        team=team,
        members=members,
        circuit_data=circuit_data,
        format_seconds_to_time=format_seconds_to_time,
        recent_activities=recent_activities  # テンプレートに活動ログを渡す
    )


@team_bp.route('/<int:team_id>/leave', methods=['POST'])
@login_required
def leave_team(team_id):
    """チームから脱退する"""
    team = Team.query.get_or_404(team_id)
    
    if current_user not in team.members:
        flash('あなたはこのチームのメンバーではありません。', 'warning')
        return redirect(url_for('main.index'))
        
    if team.owner_id == current_user.id:
        flash('チームの所有者はチームから脱退できません。チームを削除する必要があります。', 'danger')
        return redirect(url_for('team.manage_team', team_id=team.id))

    team.members.remove(current_user)
    try:
        db.session.commit()
        flash(f'チーム「{team.name}」から脱退しました。', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error leaving team: {e}", exc_info=True)
        flash('チームからの脱退中にエラーが発生しました。', 'danger')
        
    return redirect(url_for('team.list_teams'))


@team_bp.route('/<int:team_id>/remove_member/<int:user_id>', methods=['POST'])
@login_required
def remove_member(team_id, user_id):
    """チームからメンバーを削除する（オーナーのみ）"""
    team = Team.query.get_or_404(team_id)
    
    if team.owner_id != current_user.id:
        abort(403)
        
    if team.owner_id == user_id:
        flash('自分自身をチームから削除することはできません。', 'danger')
        return redirect(url_for('team.manage_team', team_id=team.id))

    member_to_remove = User.query.get_or_404(user_id)
    
    if member_to_remove in team.members:
        team.members.remove(member_to_remove)
        db.session.commit()
        flash(f'「{member_to_remove.display_name}」をチームから削除しました。', 'success')
    else:
        flash('そのユーザーはチームのメンバーではありません。', 'warning')

    return redirect(url_for('team.manage_team', team_id=team.id))


@team_bp.route('/<int:team_id>/regenerate_token', methods=['POST'])
@login_required
def regenerate_token(team_id):
    """招待トークンを再生成する（オーナーのみ）"""
    team = Team.query.get_or_404(team_id)
    if team.owner_id != current_user.id:
        abort(403)
    
    team.invite_token = str(uuid.uuid4())
    db.session.commit()
    flash('新しい招待リンクを生成しました。古いリンクは無効になりました。', 'success')
        
    return redirect(url_for('team.manage_team', team_id=team.id))


@team_bp.route('/<int:team_id>/delete', methods=['POST'])
@login_required
def delete_team(team_id):
    """チームを削除する（オーナーのみ）"""
    team = Team.query.get_or_404(team_id)
    
    if team.owner_id != current_user.id:
        abort(403)
        
    try:
        team_name = team.name
        db.session.delete(team)
        db.session.commit()
        flash(f'チーム「{team_name}」を削除しました。', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting team {team_id}: {e}", exc_info=True)
        flash('チームの削除中にエラーが発生しました。', 'danger')
        return redirect(url_for('team.manage_team', team_id=team_id))
        
    return redirect(url_for('team.list_teams'))