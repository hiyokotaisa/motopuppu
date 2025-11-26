# motopuppu/views/leaderboard.py
import decimal
from flask import Blueprint, render_template, current_app, redirect, url_for
from sqlalchemy import func, desc

from ..models import db, ActivityLog, SessionLog, User, Motorcycle
from ..constants import CIRCUITS_BY_REGION, JAPANESE_CIRCUITS

# リーダーボード機能のBlueprintを作成
leaderboard_bp = Blueprint('leaderboard', __name__, url_prefix='/leaderboard')

def format_seconds_to_time(total_seconds):
    """ 秒(Decimal)を "M:SS.fff" 形式の文字列に変換するヘルパー関数 """
    if total_seconds is None:
        return "N/A"
    
    # float等の場合もDecimalに変換して精度を維持
    if not isinstance(total_seconds, decimal.Decimal):
        total_seconds = decimal.Decimal(str(total_seconds))
    
    minutes = int(total_seconds // 60)
    seconds = total_seconds % 60
    # 秒を小数点以下3桁まで表示し、秒が10未満の場合は0でパディング
    return f"{minutes}:{seconds:06.3f}"


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

    return render_template('leaderboard/index.html', 
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
        User.misskey_username,
        User.display_name,
        User.avatar_url,
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

    for i, row in enumerate(best_laps):
        current_time = row.best_lap_seconds
        
        # 1位のタイムを保持
        if i == 0:
            top_time = current_time
            gap = None
        else:
            # 1位との差を計算
            gap = current_time - top_time

        rankings.append({
            'rank': i + 1,
            'username': row.display_name or row.misskey_username,
            'avatar_url': row.avatar_url,
            'motorcycle_name': row.motorcycle_name,
            'lap_time': format_seconds_to_time(current_time),
            'gap': f"+{gap:.3f}" if gap is not None else "-", # Gap文字列を作成
            'date': row.activity_date.strftime('%Y-%m-%d')
        })

    return render_template('leaderboard/ranking.html', circuit_name=circuit_name, rankings=rankings)