# motopuppu/views/garage_settings.py
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from .. import db
from ..models import User, Motorcycle
from ..forms import GarageSettingsForm, GarageVehicleDetailsForm
import uuid

garage_settings_bp = Blueprint('garage_settings', __name__, url_prefix='/garage/settings')

@garage_settings_bp.route('/', methods=['GET', 'POST'])
@login_required
def settings():
    """ガレージカードの統合設定ページ"""
    form = GarageSettingsForm(obj=current_user)
    
    # ヒーロー車両選択肢をユーザーの所有車両で動的に設定
    user_motorcycles = Motorcycle.query.filter_by(user_id=current_user.id).order_by(Motorcycle.name).all()
    form.garage_hero_vehicle_id.choices = [(m.id, m.name) for m in user_motorcycles]
    form.garage_hero_vehicle_id.choices.insert(0, (0, '--- デフォルト車両に準ずる ---'))

    if form.validate_on_submit():
        current_user.is_garage_public = form.is_garage_public.data
        current_user.garage_theme = form.garage_theme.data
        
        # ヒーロー車両IDの処理 (0はNoneとして扱う)
        hero_id = form.garage_hero_vehicle_id.data
        current_user.garage_hero_vehicle_id = hero_id if hero_id != 0 else None
            
        # is_garage_public がONで public_id がなければ生成
        if current_user.is_garage_public and not current_user.public_id:
            current_user.public_id = str(uuid.uuid4())
        
        try:
            db.session.commit()
            flash('ガレージ設定を更新しました。', 'success')
            return redirect(url_for('garage_settings.settings'))
        except Exception as e:
            db.session.rollback()
            flash(f'設定の更新中にエラーが発生しました: {e}', 'danger')

    # GETリクエスト時にフォームの初期値を設定
    if request.method == 'GET' and current_user.garage_hero_vehicle_id:
        form.garage_hero_vehicle_id.data = current_user.garage_hero_vehicle_id

    # 車両ごとの「ガレージ掲載」設定のためのリスト
    vehicles_for_toggle = Motorcycle.query.filter_by(user_id=current_user.id).order_by(Motorcycle.name).all()

    details_form = GarageVehicleDetailsForm()
    
    return render_template('garage/settings.html', 
                           title="ガレージ設定", 
                           form=form,
                           details_form=details_form,
                           vehicles_for_toggle=vehicles_for_toggle)

@garage_settings_bp.route('/<int:vehicle_id>/update-details', methods=['POST'])
@login_required
def update_details(vehicle_id):
    """個別の車両のガレージ情報を更新する"""
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=current_user.id).first_or_404()
    form = GarageVehicleDetailsForm()

    if form.validate_on_submit():
        motorcycle.image_url = form.image_url.data
        motorcycle.custom_details = form.custom_details.data
        try:
            db.session.commit()
            flash(f'車両「{motorcycle.name}」のガレージ情報を更新しました。', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'情報の更新中にエラーが発生しました: {e}', 'danger')
    else:
        # バリデーションエラーメッセージをflashで表示
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{getattr(form, field).label.text}: {error}", 'danger')

    return redirect(url_for('garage_settings.settings'))


@garage_settings_bp.route('/share-note', methods=['GET'])
@login_required
def share_garage_note():
    """ガレージ共有用のMisskeyノートテキストを生成して返すAPIエンドポイント"""
    
    # ガレージに掲載する設定の車両を取得
    public_vehicles = Motorcycle.query.filter_by(user_id=current_user.id, show_in_garage=True).order_by(Motorcycle.name).all()
    
    # ノートのテキストを組み立て
    note_lines = [
        f"私のガレージを紹介します！🏍️✨\n"
    ]
    
    if public_vehicles:
        for v in public_vehicles:
            note_lines.append(f"・{v.maker or '不明'} {v.name}")
    else:
        note_lines.append("（まだ掲載している車両がありません）")
        
    note_lines.append("\n") # 空行
    
    # 公開URLを追加
    if current_user.is_garage_public and current_user.public_id:
        garage_url = url_for('garage.garage_detail', public_id=current_user.public_id, _external=True)
        note_lines.append(f"詳細はこちらから！\n{garage_url}\n")
    
    # ハッシュタグ
    note_lines.append("#もとぷっぷー #ガレージ紹介")
    
    note_text = "\n".join(note_lines)
    
    return jsonify({'note_text': note_text})