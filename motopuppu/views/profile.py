# motopuppu/views/profile.py
from flask import (
    Blueprint, render_template, redirect, url_for, g, flash, request, current_app, session
)
from .. import db
from .auth import login_required_custom
from ..forms import ProfileForm, DeleteAccountForm
from ..models import User

# プロフィール管理用のBlueprintを作成
profile_bp = Blueprint('profile', __name__, url_prefix='/profile')

@profile_bp.route('/settings', methods=['GET', 'POST'])
@login_required_custom
def settings():
    # フォームを2つインスタンス化 (prefixでフォームを区別)
    profile_form = ProfileForm(prefix='profile')
    delete_form = DeleteAccountForm(prefix='delete')
    user = g.user

    # どのフォームが送信されたかを判定
    # 表示名更新フォームの処理
    if profile_form.submit_profile.data and profile_form.validate_on_submit():
        user.display_name = profile_form.display_name.data
        try:
            db.session.commit()
            flash('表示名を更新しました。', 'success')
            return redirect(url_for('profile.settings'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating display name for user {user.id}: {e}")
            flash('表示名の更新中にエラーが発生しました。', 'danger')

    # アカウント削除フォームの処理
    if delete_form.submit_delete.data and delete_form.validate_on_submit():
        try:
            # g.userではなく、DBから最新のユーザー情報を取得して削除
            user_to_delete = db.session.get(User, user.id)
            if user_to_delete:
                user_id_deleted = user_to_delete.id
                user_name_deleted = user_to_delete.misskey_username
                
                db.session.delete(user_to_delete)
                db.session.commit()
                
                # セッションをクリアしてログアウト
                session.clear()
                if 'user' in g:
                    del g.user
                
                current_app.logger.info(f"User account deleted successfully: App User ID={user_id_deleted}, Username={user_name_deleted}")
                # 退会完了ページへリダイレクト
                return redirect(url_for('auth.delete_account_complete'))
            else:
                flash('ユーザーが見つかりませんでした。', 'error')

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error deleting user account (ID: {user.id}): {e}")
            flash('アカウントの削除中にエラーが発生しました。', 'danger')
            return redirect(url_for('profile.settings'))

    # GETリクエスト時、またはバリデーション失敗時にフォームに初期値を設定
    if request.method == 'GET':
        profile_form.display_name.data = user.display_name or user.misskey_username

    return render_template('profile/settings.html',
                           title='プロフィール設定',
                           profile_form=profile_form,
                           delete_form=delete_form)