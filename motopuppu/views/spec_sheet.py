# motopuppu/views/spec_sheet.py
import json
from datetime import datetime, timezone
from flask import (
    Blueprint, flash, redirect, render_template, request, url_for, current_app
)

from .. import db, limiter
from ..models import Motorcycle, MaintenanceSpecSheet
from ..forms import MaintenanceSpecSheetForm
# ▼▼▼ インポート文を修正 ▼▼▼
from flask_login import login_required, current_user
# ▲▲▲ 変更ここまで ▲▲▲

spec_sheet_bp = Blueprint('spec_sheet', __name__, url_prefix='/spec_sheet')

SPEC_SHEET_CATEGORIES = {
    'torque': {'title': '締め付けトルク', 'icon': 'fa-wrench'},
    'fluids': {'title': '油脂類・液量', 'icon': 'fa-tint'},
    'tires': {'title': 'タイヤ', 'icon': 'fa-dot-circle'},
    'parts': {'title': '消耗品・品番', 'icon': 'fa-cogs'},
    'suspension': {'title': 'サスペンション', 'icon': 'fa-sliders-h'},
    'other': {'title': 'その他', 'icon': 'fa-info-circle'}
}

def get_motorcycle_or_404(vehicle_id):
    """指定されたIDの車両を取得し、所有者でなければ404を返すヘルパー関数"""
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    return Motorcycle.query.filter_by(id=vehicle_id, user_id=current_user.id).first_or_404()
    # ▲▲▲ 変更ここまで ▲▲▲

# --- ルート定義 ---

@spec_sheet_bp.route('/<int:vehicle_id>')
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def list_sheets(vehicle_id):
    """特定の車両の整備情報シート一覧を表示する"""
    motorcycle = get_motorcycle_or_404(vehicle_id)
    sheets = motorcycle.maintenance_spec_sheets.all()
    return render_template('spec_sheet/list_sheets.html', motorcycle=motorcycle, sheets=sheets)

@spec_sheet_bp.route('/<int:sheet_id>/view')
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def view_sheet(sheet_id):
    """整備情報シートの詳細を閲覧する"""
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    sheet = MaintenanceSpecSheet.query.filter_by(id=sheet_id, user_id=current_user.id).first_or_404()
    # ▲▲▲ 変更ここまで ▲▲▲
    return render_template(
        'spec_sheet/view_sheet.html',
        sheet=sheet,
        motorcycle=sheet.motorcycle,
        categories=SPEC_SHEET_CATEGORIES
    )

@spec_sheet_bp.route('/<int:vehicle_id>/create', methods=['GET', 'POST'])
@limiter.limit("30 per hour")
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def create_sheet(vehicle_id):
    """新しい整備情報シートを作成する"""
    motorcycle = get_motorcycle_or_404(vehicle_id)
    form = MaintenanceSpecSheetForm()

    if form.validate_on_submit():
        try:
            spec_data_json = json.loads(form.spec_data.data or '{}')
        except json.JSONDecodeError:
            flash('スペックデータの形式が正しくありません。', 'danger')
            return render_template('spec_sheet/sheet_form.html', form=form, motorcycle=motorcycle, form_action='create')

        new_sheet = MaintenanceSpecSheet(
            # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
            user_id=current_user.id,
            # ▲▲▲ 変更ここまで ▲▲▲
            motorcycle_id=motorcycle.id,
            sheet_name=form.sheet_name.data,
            spec_data=spec_data_json
        )
        
        try:
            db.session.add(new_sheet)
            db.session.commit()
            flash(f'新しい整備情報シート「{new_sheet.sheet_name}」を作成しました。', 'success')
            return redirect(url_for('spec_sheet.list_sheets', vehicle_id=motorcycle.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating spec sheet for vehicle {vehicle_id}: {e}", exc_info=True)
            flash('シートの作成中にエラーが発生しました。', 'danger')

    return render_template('spec_sheet/sheet_form.html', form=form, motorcycle=motorcycle, form_action='create')

@spec_sheet_bp.route('/<int:sheet_id>/edit', methods=['GET', 'POST'])
@limiter.limit("60 per hour")
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def edit_sheet(sheet_id):
    """整備情報シートを編集する"""
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    sheet = MaintenanceSpecSheet.query.filter_by(id=sheet_id, user_id=current_user.id).first_or_404()
    # ▲▲▲ 変更ここまで ▲▲▲
    motorcycle = sheet.motorcycle
    form = MaintenanceSpecSheetForm(obj=sheet)

    if form.validate_on_submit():
        try:
            spec_data_json = json.loads(form.spec_data.data or '{}')
        except json.JSONDecodeError:
            flash('スペックデータの形式が正しくありません。', 'danger')
            return render_template('spec_sheet/sheet_form.html', form=form, motorcycle=motorcycle, sheet=sheet, form_action='edit')
        
        sheet.sheet_name = form.sheet_name.data
        sheet.spec_data = spec_data_json
        sheet.updated_at = datetime.now(timezone.utc)

        try:
            db.session.commit()
            flash(f'整備情報シート「{sheet.sheet_name}」を更新しました。', 'success')
            return redirect(url_for('spec_sheet.list_sheets', vehicle_id=motorcycle.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating spec sheet {sheet_id}: {e}", exc_info=True)
            flash('シートの更新中にエラーが発生しました。', 'danger')

    if request.method == 'GET':
        form.spec_data.data = json.dumps(sheet.spec_data, ensure_ascii=False)

    return render_template('spec_sheet/sheet_form.html', form=form, motorcycle=motorcycle, sheet=sheet, form_action='edit')

@spec_sheet_bp.route('/<int:sheet_id>/delete', methods=['POST'])
@limiter.limit("30 per hour")
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def delete_sheet(sheet_id):
    """整備情報シートを削除する"""
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    sheet = MaintenanceSpecSheet.query.filter_by(id=sheet_id, user_id=current_user.id).first_or_404()
    # ▲▲▲ 変更ここまで ▲▲▲
    vehicle_id = sheet.motorcycle_id
    sheet_name = sheet.sheet_name
    try:
        db.session.delete(sheet)
        db.session.commit()
        flash(f'整備情報シート「{sheet_name}」を削除しました。', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting spec sheet {sheet_id}: {e}", exc_info=True)
        flash('シートの削除中にエラーが発生しました。', 'danger')

    return redirect(url_for('spec_sheet.list_sheets', vehicle_id=vehicle_id))

@spec_sheet_bp.route('/<int:sheet_id>/duplicate', methods=['POST'])
@limiter.limit("30 per hour")
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def duplicate_sheet(sheet_id):
    """整備情報シートを複製する"""
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    original_sheet = MaintenanceSpecSheet.query.filter_by(id=sheet_id, user_id=current_user.id).first_or_404()
    # ▲▲▲ 変更ここまで ▲▲▲
    
    new_sheet = MaintenanceSpecSheet(
        user_id=original_sheet.user_id,
        motorcycle_id=original_sheet.motorcycle_id,
        sheet_name=f"{original_sheet.sheet_name} (コピー)",
        spec_data=original_sheet.spec_data
    )

    try:
        db.session.add(new_sheet)
        db.session.commit()
        flash(f'シート「{original_sheet.sheet_name}」を複製しました。', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error duplicating spec sheet {sheet_id}: {e}", exc_info=True)
        flash('シートの複製中にエラーが発生しました。', 'danger')

    return redirect(url_for('spec_sheet.list_sheets', vehicle_id=original_sheet.motorcycle_id))