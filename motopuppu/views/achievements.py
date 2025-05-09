# motopuppu/views/achievements.py
from flask import Blueprint, render_template, g, current_app, abort
from sqlalchemy.orm import joinedload
from ..models import db, User, UserAchievement, AchievementDefinition
from .auth import login_required_custom # 既存のログイン必須デコレータ

achievements_bp = Blueprint('achievements', __name__, url_prefix='/achievements')

@achievements_bp.route('/')
@login_required_custom
def index():
    """解除済み実績の一覧を表示する"""
    if not g.user:
        abort(403) # 通常 login_required_custom で防がれるはず

    # ユーザーが解除した実績を取得し、実績定義も結合して取得
    # unlocked_at の降順（新しいものから）で並べる
    user_achievements_with_def = db.session.query(UserAchievement, AchievementDefinition)\
        .join(AchievementDefinition, UserAchievement.achievement_code == AchievementDefinition.code)\
        .filter(UserAchievement.user_id == g.user.id)\
        .order_by(UserAchievement.unlocked_at.desc())\
        .all()

    # カテゴリごとに実績をグループ化
    categorized_achievements = {}
    if user_achievements_with_def:
        for ua, ach_def in user_achievements_with_def:
            category_name = ach_def.category_name # 表示用のカテゴリ名
            if category_name not in categorized_achievements:
                categorized_achievements[category_name] = []
            categorized_achievements[category_name].append({
                'name': ach_def.name,
                'description': ach_def.description,
                'icon_class': ach_def.icon_class,
                'unlocked_at': ua.unlocked_at,
                'share_text_template': ach_def.share_text_template, # Misskey共有用
                'achievement_code': ach_def.code # Misskey共有時の識別等に使える
            })

    current_app.logger.info(f"User {g.user.id} unlocked achievements (categorized): {categorized_achievements}")

    return render_template(
        'achievements/unlocked_list.html',
        categorized_achievements=categorized_achievements
    )