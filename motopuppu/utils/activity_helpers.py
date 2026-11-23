"""走行ログの閲覧権限と軽量なGPS有無判定。"""
from ..models import SessionLog, Team


def can_view_activity(activity, user):
    if not user.is_authenticated:
        return False
    if activity.user_id == user.id:
        return True
    if not activity.share_with_teams:
        return False
    return Team.query.with_entities(Team.id).filter(
        Team.members.any(id=activity.user_id),
        Team.members.any(id=user.id),
    ).first() is not None


def has_gps_tracks_expression():
    """JSON全体をアプリに転送せず、先頭ラップの存在だけを返す。"""
    return SessionLog.gps_tracks['laps'][0].isnot(None)
