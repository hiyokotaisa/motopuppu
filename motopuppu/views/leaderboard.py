# motopuppu/views/leaderboard.py
import decimal
from flask import Blueprint, render_template, current_app, redirect, url_for
from sqlalchemy import func

from ..models import db, ActivityLog, SessionLog, User, Motorcycle
# ▼▼▼ インポート文を追加 ▼▼▼
from ..constants import TARGET_CIRCUITS
# ▲▲▲ ここまで追加 ▲▲▲

# リーダーボード機能のBlueprintを作成
leaderboard_bp = Blueprint('leaderboard', __name__, url_prefix='/leaderboard')

def format_seconds_to_time(total_seconds):
    """ 秒(Decimal)を "M:SS.fff" 形式の文字列に変換するヘルパー関数 """
    if total_seconds is None or not isinstance(total_seconds, decimal.Decimal):
        return "N/A"
    
    total_seconds = decimal.Decimal(total_seconds)
    minutes = int(total_seconds // 60)
    seconds = total_seconds % 60
    # 秒を小数点以下3桁まで表示し、秒が10未満の場合は0でパディング
    return f"{minutes}:{seconds:06.3f}"


@leaderboard_bp.route('/')
def index():
    """リーダーボードのトップページ（サーキット選択画面）"""
    return render_template('leaderboard/index.html', circuits=TARGET_CIRCUITS)


@leaderboard_bp.route('/<path:circuit_name>')
def ranking(circuit_name):
    """指定されたサーキットのランキングを表示"""
    # URLに含まれるサーキット名が対象外であれば、選択ページにリダイレクト
    if circuit_name not in TARGET_CIRCUITS:
        return redirect(url_for('leaderboard.index'))

    # 各ユーザーの各車両ごとのベストラップを特定するためのサブクエリ
    # ウィンドウ関数を使い、ユーザーと車両の組み合わせごとにベストラップ秒でランク付けする
    subquery = db.session.query(
        SessionLog.id.label('session_id'),
        ActivityLog.user_id,
        ActivityLog.motorcycle_id,
        ActivityLog.activity_date,
        SessionLog.best_lap_seconds,
        func.row_number().over(
            # ▼▼▼ ここから変更 ▼▼▼
            partition_by=(ActivityLog.user_id, ActivityLog.motorcycle_id),
            # ▲▲▲ ここまで変更 ▲▲▲
            order_by=SessionLog.best_lap_seconds.asc()
        ).label('rn')
    ).join(ActivityLog, SessionLog.activity_log_id == ActivityLog.id)\
     .filter(
        ActivityLog.circuit_name == circuit_name,
        SessionLog.include_in_leaderboard == True,
        SessionLog.best_lap_seconds.isnot(None)
    ).subquery()

    # --- ▼▼▼ ここから変更 ▼▼▼ ---
    # ランク1位（各ユーザーの自己ベスト）の記録のみを抽出
    best_laps = db.session.query(
        User.misskey_username,
        User.display_name,
        User.avatar_url, # アバターURLを取得するよう追加
        Motorcycle.name.label('motorcycle_name'),
        subquery.c.best_lap_seconds,
        subquery.c.activity_date
    ).join(subquery, User.id == subquery.c.user_id)\
     .join(Motorcycle, Motorcycle.id == subquery.c.motorcycle_id)\
     .filter(subquery.c.rn == 1)\
     .order_by(subquery.c.best_lap_seconds.asc())\
     .all()
    
    # テンプレートで使いやすいようにランキングデータを整形
    rankings = []
    for i, row in enumerate(best_laps):
        rankings.append({
            'rank': i + 1,
            'username': row.display_name or row.misskey_username,
            'avatar_url': row.avatar_url, # 辞書にアバターURLを追加
            'motorcycle_name': row.motorcycle_name,
            'lap_time': format_seconds_to_time(row.best_lap_seconds),
            'date': row.activity_date.strftime('%Y-%m-%d')
        })
    # --- ▲▲▲ ここまで変更 ▲▲▲ ---

    return render_template('leaderboard/ranking.html', circuit_name=circuit_name, rankings=rankings)