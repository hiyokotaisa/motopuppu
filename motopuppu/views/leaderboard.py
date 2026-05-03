# motopuppu/views/leaderboard.py
import decimal
from datetime import date
from flask import Blueprint, render_template, current_app, redirect, url_for
from flask_login import current_user
from sqlalchemy import func, desc

from ..models import db, ActivityLog, SessionLog, User, Motorcycle
from ..constants import CIRCUITS_BY_REGION, JAPANESE_CIRCUITS
from ..utils.lap_time_utils import format_seconds_to_time

# リーダーボード機能のBlueprintを作成
leaderboard_bp = Blueprint('leaderboard', __name__, url_prefix='/leaderboard')


@leaderboard_bp.route('/')
def index():
    """リーダーボードのトップページ（サーキット選択画面）"""
    
    # --- 統計情報の取得 ---
    # 1. データが存在するサーキット数
    active_circuits_count = db.session.query(ActivityLog.circuit_name).filter(
        ActivityLog.circuit_name.isnot(None)
    ).distinct().count()

    # 2. リーダーボードに登録されている総レコード数（ベストラップ数）
    total_records_count = SessionLog.query.filter(
        SessionLog.include_in_leaderboard == True,
        SessionLog.best_lap_seconds.isnot(None)
    ).count()
    
    stats = {
        'active_circuits': active_circuits_count,
        'total_records': total_records_count
    }

    # --- 最近更新された（走行があった）サーキットトップ4を取得 ---
    # ActivityLog.activity_date が新しい順にサーキット名を取得
    # 条件: サーキット名があり、リーダーボード対象のセッションログが存在すること
    recent_circuits_data = db.session.query(
        ActivityLog.circuit_name,
        func.max(ActivityLog.activity_date).label('last_activity')
    ).join(SessionLog, SessionLog.activity_log_id == ActivityLog.id)\
     .filter(
        ActivityLog.circuit_name.isnot(None),
        ActivityLog.circuit_name != '',
        # 有効な定数リストにあるサーキットのみに限定（リンク切れ防止）
        ActivityLog.circuit_name.in_(JAPANESE_CIRCUITS),
        SessionLog.include_in_leaderboard == True,
        SessionLog.best_lap_seconds.isnot(None)
    ).group_by(ActivityLog.circuit_name)\
     .order_by(desc('last_activity'))\
     .limit(4).all()

    # テンプレートに渡しやすい形式に整形 (名前, 日付)
    recent_circuits = []
    for row in recent_circuits_data:
        recent_circuits.append({
            'name': row.circuit_name,
            'last_activity': row.last_activity
        })

    template_name = 'leaderboard/index.html'
    if current_user.is_authenticated and current_user.use_beta_ui:
        template_name = 'beta/leaderboard_index_beta.html'
    return render_template(template_name,
                           circuits_by_region=CIRCUITS_BY_REGION,
                           stats=stats,
                           recent_circuits=recent_circuits)


@leaderboard_bp.route('/<path:circuit_name>')
def ranking(circuit_name):
    """指定されたサーキットのランキングを表示"""
    if circuit_name not in JAPANESE_CIRCUITS:
        return redirect(url_for('leaderboard.index'))

    # 各ユーザーの各車両ごとのベストラップを特定するためのサブクエリ
    subquery = db.session.query(
        SessionLog.id.label('session_id'),
        ActivityLog.user_id,
        ActivityLog.motorcycle_id,
        ActivityLog.activity_date,
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

    # ランク1位（各ユーザーの自己ベスト）の記録のみを抽出
    best_laps = db.session.query(
        User.id.label('user_id'),
        User.misskey_username,
        User.display_name,
        User.avatar_url,
        User.public_id,
        User.is_garage_public,
        Motorcycle.name.label('motorcycle_name'),
        subquery.c.best_lap_seconds,
        subquery.c.activity_date
    ).join(subquery, User.id == subquery.c.user_id)\
     .join(Motorcycle, Motorcycle.id == subquery.c.motorcycle_id)\
     .filter(subquery.c.rn == 1)\
     .order_by(subquery.c.best_lap_seconds.asc())\
     .all()
    
    rankings = []
    top_time = None
    prev_time = None

    for i, row in enumerate(best_laps):
        current_time = row.best_lap_seconds
        
        # 1位のタイムを保持
        if i == 0:
            top_time = current_time
            gap = None
            gap_to_above = None
        else:
            # 1位との差を計算
            gap = current_time - top_time
            # ▼▼▼【追加】B-2: 1つ上の順位との差分 ▼▼▼
            gap_to_above = current_time - prev_time if prev_time is not None else None

        prev_time = current_time

        # ▼▼▼【追加】B-1: キャラクターの鮮度判定 (14日以内か) ▼▼▼
        days_since = (date.today() - row.activity_date).days
        is_fresh = days_since <= 14

        # ガレージカードが公開されている場合はURLを生成
        garage_url = None
        if row.is_garage_public and row.public_id:
            garage_url = url_for('garage.garage_detail', public_id=row.public_id)

        rankings.append({
            'rank': i + 1,
            'username': row.display_name or row.misskey_username,
            'avatar_url': row.avatar_url,
            'motorcycle_name': row.motorcycle_name,
            'lap_time': format_seconds_to_time(current_time),
            'gap': f"+{gap:.3f}" if gap is not None else "-", # Gap文字列を作成
            'date': row.activity_date.strftime('%Y-%m-%d'),
            # ▼▼▼【追加】B-1, B-2 用データ ▼▼▼
            'user_id': row.user_id,
            'is_fresh': is_fresh,
            'gap_to_above': f"+{gap_to_above:.3f}" if gap_to_above is not None else None,
            'gap_to_above_raw': float(gap_to_above) if gap_to_above is not None else None,
            # ▲▲▲【追加】ここまで ▲▲▲
            'garage_url': garage_url,
        })

    # ▼▼▼【追加】B-2: ログインユーザーIDをテンプレートに渡す ▼▼▼
    current_user_id = current_user.id if current_user.is_authenticated else None

    template_name = 'leaderboard/ranking.html'
    if current_user.is_authenticated and current_user.use_beta_ui:
        template_name = 'beta/leaderboard_ranking_beta.html'
    return render_template(template_name, circuit_name=circuit_name, rankings=rankings, current_user_id=current_user_id)