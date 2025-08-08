# motopuppu/views/profile.py
import uuid
from flask import (
    Blueprint, render_template, redirect, url_for, flash, request, current_app, session
)
from .. import db
# ▼▼▼ インポート文を修正 ▼▼▼
from flask_login import login_required, current_user, logout_user
# ▲▲▲ 変更ここまで ▲▲▲
from ..forms import ProfileForm, DeleteAccountForm
from ..models import User

# プロフィール管理用のBlueprintを作成
profile_bp = Blueprint('profile', __name__, url_prefix='/profile')

@profile_bp.route('/settings', methods=['GET', 'POST'])
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def settings():
    # フォームを2つインスタンス化 (prefixでフォームを区別)
    profile_form = ProfileForm(prefix='profile', obj=current_user)
    delete_form = DeleteAccountForm(prefix='delete')
    # g.user の代わりに current_user を直接使用します

    # 表示名更新フォームの処理
    if profile_form.submit_profile.data and profile_form.validate_on_submit():
        # ▼▼▼ user を current_user に変更 ▼▼▼
        current_user.display_name = profile_form.display_name.data
        # ▼▼▼ ここから追記 ▼▼▼
        current_user.is_garage_public = profile_form.is_garage_public.data
        # もし公開設定がONにされ、かつ公開IDがまだ無ければ、新しく生成する
        if current_user.is_garage_public and not current_user.public_id:
            current_user.public_id = str(uuid.uuid4())
        # ▲▲▲ 追記ここまで ▲▲▲
        try:
            db.session.commit()
            flash('プロフィール情報を更新しました。', 'success')
            return redirect(url_for('profile.settings'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating profile for user {current_user.id}: {e}")
            flash('プロフィール情報の更新中にエラーが発生しました。', 'danger')
        # ▲▲▲ 変更ここまで ▲▲▲

    # アカウント削除フォームの処理
    if delete_form.submit_delete.data and delete_form.validate_on_submit():
        try:
            # ▼▼▼ g.user.id を current_user.id に変更し、削除処理を修正 ▼▼▼
            # DBから最新のユーザー情報を取得して削除
            user_to_delete = db.session.get(User, current_user.id)
            if user_to_delete:
                user_id_deleted = user_to_delete.id
                user_name_deleted = user_to_delete.misskey_username
                
                # ユーザーオブジェクトをDBから削除する前にログアウト処理を行う
                logout_user()
                
                db.session.delete(user_to_delete)
                db.session.commit()
                
                current_app.logger.info(f"User account deleted successfully: App User ID={user_id_deleted}, Username={user_name_deleted}")
                # 退会完了ページへリダイレクト
                return redirect(url_for('auth.delete_account_complete'))
            else:
                flash('ユーザーが見つかりませんでした。', 'error')

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error deleting user account (ID: {current_user.id}): {e}")
            flash('アカウントの削除中にエラーが発生しました。', 'danger')
            return redirect(url_for('profile.settings'))
        # ▲▲▲ 変更ここまで ▲▲▲

    # GETリクエスト時、またはバリデーション失敗時にフォームに初期値を設定
    if request.method == 'GET':
        # ▼▼▼ user を current_user に変更 ▼▼▼
        profile_form.display_name.data = current_user.display_name or current_user.misskey_username
        profile_form.is_garage_public.data = current_user.is_garage_public
        # ▲▲▲ 変更ここまで ▲▲▲

    return render_template('profile/settings.html',
                           title='プロフィール設定',
                           profile_form=profile_form,
                           delete_form=delete_form)