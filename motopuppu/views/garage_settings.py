# motopuppu/views/garage_settings.py
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from .. import db, limiter
from ..models import User, Motorcycle
from ..forms import GarageSettingsForm, GarageVehicleDetailsForm
import uuid

garage_settings_bp = Blueprint('garage_settings', __name__, url_prefix='/garage/settings')

@garage_settings_bp.route('/', methods=['GET', 'POST'])
@login_required
def settings():
    """ガレージカードの統合設定ページ"""
    # ▼▼▼【ここから変更】GETリクエスト時のデータ読み込みを修正 ▼▼▼
    # obj=current_user だとJSONカラムをうまく扱えないため、手動で設定する
    form = GarageSettingsForm()
    # ▲▲▲【変更はここまで】▲▲▲
    
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
        
        # ▼▼▼【ここから追記】表示設定をJSONにまとめて保存 ▼▼▼
        current_user.garage_display_settings = {
            'show_hero_stats': form.show_hero_stats.data,
            'show_custom_details': form.show_custom_details.data,
            'show_other_vehicles': form.show_other_vehicles.data,
            'show_achievements': form.show_achievements.data,
            'show_circuit_info': form.show_circuit_info.data,
        }
        # ▲▲▲【追記はここまで】▲▲▲
        
        try:
            db.session.commit()
            flash('ガレージ設定を更新しました。', 'success')
            return redirect(url_for('garage_settings.settings'))
        except Exception as e:
            db.session.rollback()
            flash(f'設定の更新中にエラーが発生しました: {e}', 'danger')

    # ▼▼▼【ここから変更】GETリクエスト時にDBから設定を読み込みフォームに設定 ▼▼▼
    if request.method == 'GET':
        form.is_garage_public.data = current_user.is_garage_public
        form.garage_theme.data = current_user.garage_theme
        form.garage_hero_vehicle_id.data = current_user.garage_hero_vehicle_id or 0
        
        # DBのJSON設定をフォームに反映 (設定がない項目はデフォルト値 True を使用)
        settings = current_user.garage_display_settings or {}
        form.show_hero_stats.data = settings.get('show_hero_stats', True)
        form.show_custom_details.data = settings.get('show_custom_details', True)
        form.show_other_vehicles.data = settings.get('show_other_vehicles', True)
        form.show_achievements.data = settings.get('show_achievements', True)
        form.show_circuit_info.data = settings.get('show_circuit_info', True)
    # ▲▲▲【変更はここまで】▲▲▲

    # 車両ごとの「ガレージ掲載」設定のためのリスト
    vehicles_for_toggle = Motorcycle.query.filter_by(user_id=current_user.id).order_by(Motorcycle.name).all()

    details_form = GarageVehicleDetailsForm()

    template_name = 'beta/garage_settings_beta.html' if current_user.use_beta_ui else 'garage/settings.html'
    return render_template(template_name,
                           title="ガレージ設定",
                           form=form,
                           details_form=details_form,
                           vehicles_for_toggle=vehicles_for_toggle)

@garage_settings_bp.route('/<int:vehicle_id>/update-details', methods=['POST'])
@limiter.limit("30 per hour")
@login_required
def update_details(vehicle_id):
    """個別の車両のガレージ情報を更新する"""
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=current_user.id).first_or_404()
    form = GarageVehicleDetailsForm()

    if form.validate_on_submit():
        final_image_url = form.image_url.data
        if form.image_file.data:
            try:
                from ..utils.image_security import process_and_upload_image, delete_gcs_image
                uploaded_url = process_and_upload_image(form.image_file.data, current_user.id)
                if uploaded_url:
                    # ▼▼▼【ここから追記】新画像のアップロード成功後、旧GCS画像を削除 ▼▼▼
                    old_image_url = motorcycle.image_url
                    if old_image_url and old_image_url != uploaded_url:
                        delete_gcs_image(old_image_url)
                    # ▲▲▲【追記はここまで】▲▲▲
                    final_image_url = uploaded_url
            except ValueError as e:
                flash(str(e), 'warning')
            except Exception as e:
                flash('画像のアップロードに失敗しました。', 'warning')

        motorcycle.image_url = final_image_url
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