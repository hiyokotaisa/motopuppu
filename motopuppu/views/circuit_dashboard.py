# motopuppu/views/circuit_dashboard.py
import decimal
from flask import Blueprint, render_template, current_app, url_for
from flask_login import login_required, current_user
from sqlalchemy import func, case
from sqlalchemy.orm import aliased, joinedload

from ..models import db, ActivityLog, SessionLog, User, Motorcycle
from ..utils.lap_time_utils import format_seconds_to_time

# 新しいBlueprintを定義
circuit_dashboard_bp = Blueprint(
    'circuit_dashboard',
    __name__,
    template_folder='../../templates', # ルートのtemplatesディレクトリを指す
    url_prefix='/circuit-dashboard'
)

def get_leaderboard_rankings(circuit_name, user_id):
    """ 指定されたサーキットのリーダーボード情報を取得し、
        指定されたユーザーの順位と次の順位との差を返す """
        
    subquery = db.session.query(
        SessionLog.id.label('session_id'),
        ActivityLog.user_id,
        SessionLog.best_lap_seconds,
        func.row_number().over(
            partition_by=(ActivityLog.user_id, ActivityLog.motorcycle_id),
            order_by=SessionLog.best_lap_seconds.asc()
        ).label('rn')
    ).join(ActivityLog, SessionLog.activity_log_id == ActivityLog.id)\
     .filter(
        ActivityLog.circuit_name == circuit_name,
        SessionLog.include_in_leaderboard == True,
        SessionLog.best_lap_seconds.isnot(None)
    ).subquery()

    best_laps = db.session.query(
        subquery.c.user_id,
        subquery.c.best_lap_seconds,
    ).filter(subquery.c.rn == 1)\
     .order_by(subquery.c.best_lap_seconds.asc())\
     .all()

    user_rank = None
    user_best_lap = None
    next_rank_lap = None

    for i, row in enumerate(best_laps):
        if row.user_id == user_id:
            user_rank = i + 1
            user_best_lap = row.best_lap_seconds
            # 自分の1つ前の順位の人のタイムを取得
            if i > 0:
                next_rank_lap = best_laps[i-1].best_lap_seconds
            break
            
    gap = None
    if user_best_lap and next_rank_lap:
        gap = user_best_lap - next_rank_lap

    return {
        'rank': user_rank,
        'gap_to_next': gap
    }

@circuit_dashboard_bp.route('/')
@login_required
def index():
    """ サーキットダッシュボードのメインページ """
    
    # ユーザーの全セッションログから、サーキット名が存在するものだけを対象にする
    base_query = db.session.query(
        ActivityLog, SessionLog
    ).join(
        SessionLog, ActivityLog.id == SessionLog.activity_log_id
    ).filter(
        ActivityLog.user_id == current_user.id,
        ActivityLog.circuit_name.isnot(None),
        SessionLog.best_lap_seconds.isnot(None)
    )

    # 1. サーキットごとの自己ベストセッションを取得
    #    ウィンドウ関数を使い、サーキットごとにベストラップでランク付け
    subq = base_query.with_entities(
        ActivityLog.circuit_name,
        SessionLog.id.label('session_id'),
        func.row_number().over(
            partition_by=ActivityLog.circuit_name,
            order_by=SessionLog.best_lap_seconds.asc()
        ).label('rn')
    ).subquery()

    # ランク1位のセッションIDのみを取得
    best_session_ids = db.session.query(subq.c.session_id).filter(subq.c.rn == 1).all()
    best_session_ids_list = [sid for sid, in best_session_ids]
    
    best_sessions = db.session.query(SessionLog).options(
        joinedload(SessionLog.activity).joinedload(ActivityLog.motorcycle),
        joinedload(SessionLog.setting_sheet)
    ).filter(
        SessionLog.id.in_(best_session_ids_list)
    ).all()
    
    # 2. ダッシュボードに表示するデータを整形
    circuit_data = []
    
    # 全セッションログを取得（グラフ用）
    all_sessions_for_graph = base_query.options(
        db.joinedload(SessionLog.activity)
    ).order_by(ActivityLog.activity_date.asc()).all()

    # サーキットごとにデータをまとめる
    for best_session in best_sessions:
        circuit_name = best_session.activity.circuit_name
        
        # 2a. 車両ごとのベストラップと統計を取得
        # SessionLog.id を直接 group_by に含めると意図しない挙動になるため、ウィンドウ関数でベストセッションIDを特定
        best_session_id_subq = db.session.query(
            ActivityLog.motorcycle_id,
            func.first_value(SessionLog.id).over(
                partition_by=ActivityLog.motorcycle_id,
                order_by=SessionLog.best_lap_seconds.asc()
            ).label('best_session_id')
        ).join(SessionLog, ActivityLog.id == SessionLog.activity_log_id)\
         .filter(
            ActivityLog.user_id == current_user.id,
            ActivityLog.circuit_name == circuit_name,
            SessionLog.best_lap_seconds.isnot(None)
        ).distinct().subquery()

        vehicle_breakdown_query = db.session.query(
            Motorcycle.id.label('motorcycle_id'),
            Motorcycle.name.label('motorcycle_name'),
            func.min(SessionLog.best_lap_seconds).label('vehicle_best_lap'),
            func.count(SessionLog.id).label('session_count'),
            best_session_id_subq.c.best_session_id
        ).join(
            ActivityLog, SessionLog.activity_log_id == ActivityLog.id
        ).join(
            Motorcycle, ActivityLog.motorcycle_id == Motorcycle.id
        ).join(
            best_session_id_subq, Motorcycle.id == best_session_id_subq.c.motorcycle_id
        ).filter(
            ActivityLog.user_id == current_user.id,
            ActivityLog.circuit_name == circuit_name,
            SessionLog.best_lap_seconds.isnot(None)
        ).group_by(
            Motorcycle.id, 
            Motorcycle.name,
            best_session_id_subq.c.best_session_id
        ).order_by(
            func.min(SessionLog.best_lap_seconds).asc()
        ).all()
        
        vehicle_data = []
        user_personal_best = best_session.best_lap_seconds
        for row in vehicle_breakdown_query:
            gap = row.vehicle_best_lap - user_personal_best if user_personal_best else None
            vehicle_data.append({
                'id': row.motorcycle_id,
                'name': row.motorcycle_name,
                'best_lap': row.vehicle_best_lap,
                'session_count': row.session_count,
                'gap_to_pb': gap,
                'is_pb_holder': abs(gap) < decimal.Decimal('0.0001') if gap is not None else False,
                'best_session_id': row.best_session_id
            })
        
        # 2b. ラップタイム推移グラフのデータを作成
        chart_data = {
            'labels': [], # 日付
            'data': []   # ベストラップ
        }
        for activity, session in all_sessions_for_graph:
            if activity.circuit_name == circuit_name:
                chart_data['labels'].append(activity.activity_date.isoformat())
                chart_data['data'].append(float(session.best_lap_seconds))

        # 2c. リーダーボード情報を取得
        leaderboard_info = get_leaderboard_rankings(circuit_name, current_user.id)
        
        # 2d. 最新セッションを取得
        latest_session = base_query.filter(
            ActivityLog.circuit_name == circuit_name
        ).order_by(ActivityLog.activity_date.desc(), SessionLog.id.desc()).first()

        circuit_data.append({
            'name': circuit_name,
            'best_session': best_session,
            'latest_session_id': latest_session.SessionLog.id if latest_session else None,
            'chart_data': chart_data,
            'leaderboard': leaderboard_info,
            'vehicle_breakdown': vehicle_data
        })
        
    # 3. 総合サマリー情報を計算
    all_sessions = base_query.all()
    total_sessions = len(all_sessions)
    total_laps = sum(len(s.lap_times) for a, s in all_sessions if s.lap_times)
    
    summary_stats = {
        'total_circuits': len(circuit_data),
        'total_sessions': total_sessions,
        'total_laps': total_laps
    }

    # サーキット名でソートしてテンプレートに渡す
    circuit_data.sort(key=lambda x: x['name'])
    
    return render_template(
        'circuit_dashboard/index.html',
        summary_stats=summary_stats,
        circuit_data=circuit_data,
        format_seconds_to_time=format_seconds_to_time
    )