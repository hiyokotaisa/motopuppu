# motopuppu/views/achievements.py
from flask import Blueprint, render_template, g, current_app, abort
from sqlalchemy.orm import joinedload # joinedload は現在このビューでは直接使われていませんが、必要に応じて利用できます
from ..models import db, User, UserAchievement, AchievementDefinition # Userモデルもインポートしておくとg.userの型ヒントなどで役立つ場合があります
from .auth import login_required_custom # 既存のログイン必須デコレータ

achievements_bp = Blueprint('achievements', __name__, url_prefix='/achievements')

@achievements_bp.route('/')
@login_required_custom
def index():
    """全ての実績定義と、ユーザーの解除状況を一覧表示する"""
    if not g.user:
        # 通常、login_required_custom がこれを処理するはずですが、念のため
        current_app.logger.warning("g.user not found in achievements index despite @login_required_custom")
        abort(403) # または適切なエラー処理

    # 全ての実績定義を取得 (カテゴリ名、実績名の順で初期ソート)
    all_achievement_defs = AchievementDefinition.query.order_by(
        AchievementDefinition.category_name,
        AchievementDefinition.name
    ).all()

    # ユーザーが解除した実績のコードと解除日時を辞書として取得
    unlocked_achievements_info = {
        ua.achievement_code: ua.unlocked_at
        for ua in UserAchievement.query.filter_by(user_id=g.user.id).all()
    }

    # カテゴリごとに実績をグループ化し、解除情報を付加
    categorized_achievements_with_status = {}
    if all_achievement_defs:
        for ach_def in all_achievement_defs:
            category_name = ach_def.category_name
            if category_name not in categorized_achievements_with_status:
                categorized_achievements_with_status[category_name] = []
            
            is_unlocked = ach_def.code in unlocked_achievements_info
            unlocked_at = unlocked_achievements_info.get(ach_def.code) # is_unlocked が False なら None になる
            
            categorized_achievements_with_status[category_name].append({
                'code': ach_def.code,
                'name': ach_def.name,
                'description': ach_def.description,
                'icon_class': ach_def.icon_class,
                'is_unlocked': is_unlocked,
                'unlocked_at': unlocked_at,
                'share_text_template': ach_def.share_text_template if is_unlocked else None
            })
    
    # 各カテゴリ内の実績リストをソートする
    # 解除済みの実績 (is_unlocked=True) を先頭に、次に実績名 (name) でソート
    for category_name in categorized_achievements_with_status:
        categorized_achievements_with_status[category_name].sort(
            key=lambda ach: (not ach['is_unlocked'], ach['name'])
        )
    
    # ロギングはデバッグ時に役立ちますが、本番では必要に応じて調整してください
    # current_app.logger.debug(f"User {g.user.id} achievements page data (categorized and sorted): {categorized_achievements_with_status}")

    return render_template(
        'achievements/unlocked_list.html',
        categorized_achievements=categorized_achievements_with_status
    )