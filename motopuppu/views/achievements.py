# motopuppu/views/achievements.py
from flask import Blueprint, render_template, g, current_app, abort
from sqlalchemy.orm import joinedload
from ..models import db, User, UserAchievement, AchievementDefinition
from .auth import login_required_custom # 既存のログイン必須デコレータ

achievements_bp = Blueprint('achievements', __name__, url_prefix='/achievements')

@achievements_bp.route('/')
@login_required_custom
def index():
    """全ての実績定義と、ユーザーの解除状況を一覧表示する"""
    if not g.user:
        abort(403)

    # 全ての実績定義を取得
    all_achievement_defs = AchievementDefinition.query.order_by(AchievementDefinition.category_name, AchievementDefinition.name).all()

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
            unlocked_at = unlocked_achievements_info.get(ach_def.code) if is_unlocked else None
            
            categorized_achievements_with_status[category_name].append({
                'code': ach_def.code, # 実績コードも渡す
                'name': ach_def.name,
                'description': ach_def.description, # これが解除条件
                'icon_class': ach_def.icon_class,
                'is_unlocked': is_unlocked,
                'unlocked_at': unlocked_at,
                'share_text_template': ach_def.share_text_template if is_unlocked else None # 解除済みのみ共有可能
            })
    
    current_app.logger.info(f"User {g.user.id} achievements page data (categorized with status): {categorized_achievements_with_status}")

    return render_template(
        'achievements/unlocked_list.html',
        # テンプレートに渡す変数名を変更 (categorized_achievements -> all_categorized_achievements など、より意味のある名前にしても良い)
        categorized_achievements=categorized_achievements_with_status 
    )