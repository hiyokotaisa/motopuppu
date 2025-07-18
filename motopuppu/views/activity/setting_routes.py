# motopuppu/views/activity/setting_routes.py
import json

from flask import (
    flash, redirect, render_template, request, url_for, current_app
)

# 分割したBlueprintをインポート
from . import activity_bp

# ▼▼▼ インポート文を修正 ▼▼▼
from .activity_routes import get_motorcycle_or_404
from flask_login import login_required, current_user
# ▲▲▲ 変更ここまで ▲▲▲
from ...models import db, SettingSheet
from ...forms import SettingSheetForm
from ... import limiter


@activity_bp.route('/<int:vehicle_id>/settings')
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def list_settings(vehicle_id):
    motorcycle = get_motorcycle_or_404(vehicle_id)
    settings = SettingSheet.query.filter_by(motorcycle_id=motorcycle.id).order_by(SettingSheet.is_archived, SettingSheet.sheet_name).all()
    return render_template('activity/list_settings.html',
                           motorcycle=motorcycle,
                           settings=settings)

@activity_bp.route('/<int:vehicle_id>/settings/add', methods=['GET', 'POST'])
@limiter.limit("30 per hour")
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def add_setting(vehicle_id):
    motorcycle = get_motorcycle_or_404(vehicle_id)
    form = SettingSheetForm()

    if form.validate_on_submit():
        details_json_str = request.form.get('details_json', '{}')
        try:
            details = json.loads(details_json_str)
        except (json.JSONDecodeError, TypeError):
            flash('セッティング詳細のデータ形式が無効です。', 'danger')
            return render_template('activity/setting_form.html', form=form, motorcycle=motorcycle, form_action='add', details_json=details_json_str)

        new_setting = SettingSheet(
            motorcycle_id=motorcycle.id,
            # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
            user_id=current_user.id,
            # ▲▲▲ 変更ここまで ▲▲▲
            sheet_name=form.sheet_name.data,
            details=details,
            notes=form.notes.data
        )
        try:
            db.session.add(new_setting)
            db.session.commit()
            flash(f'セッティングシート「{new_setting.sheet_name}」を作成しました。', 'success')
            return redirect(url_for('activity.list_settings', vehicle_id=motorcycle.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error adding new setting sheet: {e}", exc_info=True)
            flash('セッティングシートの保存中にエラーが発生しました。', 'danger')
    
    if request.method == 'POST' and form.errors:
        error_messages = '; '.join([f'{field}: {", ".join(error_list)}' for field, error_list in form.errors.items()])
        flash(f'入力内容にエラーがあります: {error_messages}', 'danger')

    return render_template('activity/setting_form.html',
                           form=form,
                           motorcycle=motorcycle,
                           form_action='add',
                           details_json='{}')

@activity_bp.route('/settings/<int:setting_id>/edit', methods=['GET', 'POST'])
@limiter.limit("30 per hour")
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def edit_setting(setting_id):
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    setting = SettingSheet.query.filter_by(id=setting_id, user_id=current_user.id).first_or_404()
    # ▲▲▲ 変更ここまで ▲▲▲
    motorcycle = setting.motorcycle
    form = SettingSheetForm(obj=setting)

    if form.validate_on_submit():
        details_json_str = request.form.get('details_json', '{}')
        
        try:
            details = json.loads(details_json_str)
        except (json.JSONDecodeError, TypeError):
            flash('セッティング詳細のデータ形式が無効です。', 'danger')
            return render_template('activity/setting_form.html', form=form, motorcycle=motorcycle, setting=setting, form_action='edit', details_json=details_json_str)

        setting.sheet_name = form.sheet_name.data
        setting.notes = form.notes.data
        setting.details = details
        
        try:
            db.session.commit()
            flash(f'セッティングシート「{setting.sheet_name}」を更新しました。', 'success')
            return redirect(url_for('activity.list_settings', vehicle_id=motorcycle.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error editing setting sheet {setting_id}: {e}", exc_info=True)
            flash('セッティングシートの更新中にエラーが発生しました。', 'danger')

    details_json_for_template = json.dumps(setting.details)
    return render_template('activity/setting_form.html',
                           form=form,
                           motorcycle=motorcycle,
                           setting=setting,
                           form_action='edit',
                           details_json=details_json_for_template)

@activity_bp.route('/settings/<int:setting_id>/toggle_archive', methods=['POST'])
@limiter.limit("30 per hour")
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def toggle_archive_setting(setting_id):
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    setting = SettingSheet.query.filter_by(id=setting_id, user_id=current_user.id).first_or_404()
    # ▲▲▲ 変更ここまで ▲▲▲
    setting.is_archived = not setting.is_archived
    try:
        db.session.commit()
        status = "アーカイブしました" if setting.is_archived else "有効化しました"
        flash(f'セッティングシート「{setting.sheet_name}」を{status}。', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error toggling archive for setting sheet {setting_id}: {e}", exc_info=True)
        flash('状態の変更中にエラーが発生しました。', 'danger')
    return redirect(url_for('activity.list_settings', vehicle_id=setting.motorcycle_id))

@activity_bp.route('/settings/<int:setting_id>/delete', methods=['POST'])
@limiter.limit("30 per hour")
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def delete_setting(setting_id):
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    setting = SettingSheet.query.filter_by(id=setting_id, user_id=current_user.id).first_or_404()
    # ▲▲▲ 変更ここまで ▲▲▲
    vehicle_id = setting.motorcycle_id
    sheet_name = setting.sheet_name
    try:
        db.session.delete(setting)
        db.session.commit()
        flash(f'セッティングシート「{sheet_name}」を削除しました。', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting setting sheet {setting_id}: {e}", exc_info=True)
        flash('セッティングシートの削除中にエラーが発生しました。', 'danger')
    return redirect(url_for('activity.list_settings', vehicle_id=vehicle_id))