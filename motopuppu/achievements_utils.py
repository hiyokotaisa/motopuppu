# motopuppu/achievements_utils.py
from flask import flash, current_app
from . import db
from .models import User, UserAchievement, AchievementDefinition # 変更なし
from datetime import datetime

def unlock_achievement(user: User, achievement_code: str):
    # (既存の解除済みチェック、実績定義取得は変更なし)
    if not user or not achievement_code:
        current_app.logger.warning(f"unlock_achievement called with invalid user or achievement_code. User: {user}, Code: {achievement_code}")
        return False

    existing_unlock = UserAchievement.query.filter_by(
        user_id=user.id,
        achievement_code=achievement_code
    ).first()

    if existing_unlock:
        current_app.logger.debug(f"User {user.id} has already unlocked achievement {achievement_code}.")
        return False

    achievement_def = AchievementDefinition.query.filter_by(code=achievement_code).first()
    if not achievement_def:
        current_app.logger.error(f"Achievement definition not found for code: {achievement_code}")
        return False

    try:
        new_user_achievement = UserAchievement(
            user_id=user.id,
            achievement_code=achievement_code,
            unlocked_at=datetime.utcnow()
        )
        db.session.add(new_user_achievement)
        db.session.commit() 
        current_app.logger.info(f"Attempted commit for UserAchievement: user_id={user.id}, code={achievement_code}") # コミット試行ログ

        # ▼▼▼ コミット後の確認クエリ ▼▼▼
        check_ua = UserAchievement.query.filter_by(user_id=user.id, achievement_code=achievement_code).first()
        if check_ua:
            current_app.logger.info(f"SUCCESSFULLY VERIFIED UserAchievement in DB after commit: id={check_ua.id}, user_id={check_ua.user_id}, code={check_ua.achievement_code}")
        else:
            current_app.logger.error(f"FAILED TO VERIFY UserAchievement in DB after commit for user_id={user.id}, code={achievement_code}")
        # ▲▲▲ コミット後の確認クエリ ▲▲▲

        icon_html = f"<i class='{achievement_def.icon_class} me-1'></i>" if achievement_def.icon_class else ""
        flash(f"実績解除！ {icon_html}<strong>{achievement_def.name}</strong> を達成しました！", "success")
        current_app.logger.info(f"User {user.id} unlocked achievement (flash message sent): {achievement_code} - {achievement_def.name}")
        return True

    except Exception as e:
        db.session.rollback() 
        current_app.logger.error(f"Error during unlock_achievement (commit or verification) for {achievement_code} user {user.id}: {e}", exc_info=True)
        return False