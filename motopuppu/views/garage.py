# motopuppu/views/garage.py
import io
import os
import requests
from flask import (
    Blueprint, render_template, abort, current_app, send_file, url_for
)
# ▼▼▼【ここから変更】不要なインポートを削除し、シンプルに ▼▼▼
from ..models import User
from .. import services
# ▲▲▲【変更はここまで】▲▲▲
from PIL import Image, ImageDraw, ImageFont

# ガレージ公開ページ用のBlueprintを作成
garage_bp = Blueprint('garage', __name__, url_prefix='/garage')

@garage_bp.route('/<public_id>')
def garage_detail(public_id):
    """ユーザーの公開ガレージHTMLページ"""
    user = User.query.filter_by(public_id=public_id, is_garage_public=True).first_or_404()
    
    # ▼▼▼【ここから変更】サービス関数を呼び出すだけで全てのデータが揃う ▼▼▼
    garage_data = services.get_user_garage_data(user)
    if not garage_data:
        abort(500, "ガレージデータの生成に失敗しました。")
    
    # データを展開してテンプレートに渡す
    return render_template('garage/public_garage.html', **garage_data)
    # ▲▲▲【変更はここまで】▲▲▲


@garage_bp.route('/<public_id>/image.png')
def garage_ogp_image(public_id):
    """ユーザーの公開ガレージ用のOGP画像を動的に生成するAPI"""
    user = User.query.filter_by(public_id=public_id, is_garage_public=True).first_or_404()
    garage_data = services.get_user_garage_data(user)
    if not garage_data:
        abort(500)

    try:
        # --- Pillowを使った画像生成 ---
        base_width, base_height = 1200, 630
        img = Image.new('RGB', (base_width, base_height), color=(20, 20, 30)) # 濃い紺色の背景
        draw = ImageDraw.Draw(img)

        # フォントのパス (プロジェクトルートに fonts/ipaexg.ttf などを配置)
        font_path = os.path.join(current_app.root_path, '..', 'fonts', 'ipaexg.ttf')
        if not os.path.exists(font_path):
            current_app.logger.error(f"Font file not found at {font_path}. Using default font.")
            font_path_bold = None
            font_path_reg = None
        else:
            font_path_bold = font_path
            font_path_reg = font_path

        font_l = ImageFont.truetype(font_path_bold, 70) if font_path_bold else ImageFont.load_default()
        font_m = ImageFont.truetype(font_path_reg, 36) if font_path_reg else ImageFont.load_default()
        font_s = ImageFont.truetype(font_path_reg, 28) if font_path_reg else ImageFont.load_default()

        # --- ヒーロー車両（デフォルト車両）の描画 ---
        hero_vehicle = garage_data.get('hero_vehicle')
        if hero_vehicle and hero_vehicle.image_url:
            try:
                res = requests.get(hero_vehicle.image_url, timeout=5)
                res.raise_for_status()
                vehicle_img_data = io.BytesIO(res.content)
                vehicle_img = Image.open(vehicle_img_data).convert("RGBA")
                
                # 画像をいい感じにリサイズして右側に配置
                max_w, max_h = 700, 530
                vehicle_img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
                
                paste_x = base_width - vehicle_img.width - 50
                paste_y = (base_height - vehicle_img.height) // 2
                img.paste(vehicle_img, (paste_x, paste_y), vehicle_img)
            except Exception as e:
                current_app.logger.error(f"Failed to load hero vehicle image: {e}")
        
        # --- 左側の情報描画 ---
        # オーナー情報
        owner = garage_data.get('owner')
        draw.text((60, 60), f"{owner.display_name or owner.misskey_username}'s", font=font_m, fill=(200, 200, 200))
        draw.text((60, 100), "Garage", font=font_l, fill=(255, 255, 255))

        # ヒーロー車両情報
        if hero_vehicle:
            draw.text((60, 220), hero_vehicle.name, font=font_m, fill=(255, 255, 255))
            draw.text((60, 270), f"{hero_vehicle.maker or ''} {hero_vehicle.year or ''}", font=font_s, fill=(180, 180, 180))

        # 他の車両リスト
        other_vehicles = garage_data.get('other_vehicles', [])
        if other_vehicles:
            start_y = 380
            draw.text((60, start_y - 40), "Also owns:", font=font_s, fill=(150, 150, 150))
            for i, vehicle in enumerate(other_vehicles[:4]): # 最大4台まで表示
                draw.text((80, start_y + (i * 40)), f"・{vehicle.name}", font=font_s, fill=(200, 200, 200))

        # 右下のロゴ
        draw.text((base_width - 200, base_height - 60), "もとぷっぷー", font=font_s, fill=(100, 100, 100))

        # バッファに画像を保存
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        
        return send_file(buf, mimetype='image/png')

    except Exception as e:
        current_app.logger.error(f"Failed to generate OGP image for {public_id}: {e}", exc_info=True)
        abort(500)