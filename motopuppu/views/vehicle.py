# motopuppu/views/vehicle.py
from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, abort, current_app
)
# ログイン必須デコレータと現在のユーザー取得関数
from .auth import login_required_custom, get_current_user
# データベースモデルとdbオブジェクト
from ..models import db, Motorcycle, User
# from ..forms import VehicleForm, OdometerResetForm # (Flask-WTFを使う場合)

# 'vehicle' という名前でBlueprintオブジェクトを作成
vehicle_bp = Blueprint('vehicle', __name__, url_prefix='/vehicles')

# --- ルート定義 ---

@vehicle_bp.route('/')
@login_required_custom
def vehicle_list():
    """登録されている車両の一覧を表示"""
    # 現在のユーザーが所有する車両を取得
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.id).all()
    return render_template('vehicles.html', motorcycles=user_motorcycles)

@vehicle_bp.route('/add', methods=['GET', 'POST'])
@login_required_custom
def add_vehicle():
    """新しい車両を追加"""
    if request.method == 'POST':
        # フォームからデータを取得 (バリデーションは後で追加推奨)
        maker = request.form.get('maker')
        name = request.form.get('name')
        year_str = request.form.get('year')

        # 簡単な入力チェック (名前は必須)
        if not name:
            flash('車両名は必須です。', 'error')
            return render_template('vehicle_form.html', form_action='add', vehicle=None)

        # 年式は数値かチェック (任意)
        year = None
        if year_str:
            try:
                year = int(year_str)
            except ValueError:
                flash('年式は数値を入力してください。', 'error')
                # 入力値を保持してフォームを再表示
                vehicle_data = {'maker': maker, 'name': name, 'year': year_str}
                return render_template('vehicle_form.html', form_action='add', vehicle=vehicle_data)

        # 新しい車両オブジェクトを作成
        new_motorcycle = Motorcycle(
            owner=g.user, # 所有者を現在のユーザーに設定
            maker=maker,
            name=name,
            year=year
        )

        # ユーザーが他に車両を持っていない場合、これをデフォルトにする
        existing_vehicles_count = Motorcycle.query.filter_by(user_id=g.user.id).count()
        if existing_vehicles_count == 0:
            new_motorcycle.is_default = True

        try:
            db.session.add(new_motorcycle)
            db.session.commit()
            flash(f'車両「{new_motorcycle.name}」を登録しました。', 'success')
            # 登録後は車両一覧ページへリダイレクト
            return redirect(url_for('vehicle.vehicle_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'車両の登録中にエラーが発生しました: {e}', 'error')
            current_app.logger.error(f"Error adding vehicle: {e}")

    # GETリクエストの場合、またはPOSTでエラーがあった場合
    # 空のフォームを表示
    return render_template('vehicle_form.html', form_action='add', vehicle=None)


@vehicle_bp.route('/<int:vehicle_id>/edit', methods=['GET', 'POST'])
@login_required_custom
def edit_vehicle(vehicle_id):
    """既存の車両情報を編集"""
    # 編集対象の車両を取得 (存在しない or 他人の車両なら404)
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=g.user.id).first_or_404()

    if request.method == 'POST':
        # フォームからデータを取得
        maker = request.form.get('maker')
        name = request.form.get('name')
        year_str = request.form.get('year')

        if not name:
            flash('車両名は必須です。', 'error')
        else:
            year = None
            if year_str:
                try:
                    year = int(year_str)
                except ValueError:
                    flash('年式は数値を入力してください。', 'error')
                    # エラーの場合は更新せずにフォームを再表示
                    return render_template('vehicle_form.html', form_action='edit', vehicle=motorcycle)

            # データを更新
            motorcycle.maker = maker
            motorcycle.name = name
            motorcycle.year = year
            try:
                db.session.commit()
                flash(f'車両「{motorcycle.name}」の情報を更新しました。', 'success')
                return redirect(url_for('vehicle.vehicle_list'))
            except Exception as e:
                db.session.rollback()
                flash(f'車両情報の更新中にエラーが発生しました: {e}', 'error')
                current_app.logger.error(f"Error editing vehicle {vehicle_id}: {e}")

    # GETリクエストの場合、現在のデータで初期化されたフォームを表示
    return render_template('vehicle_form.html', form_action='edit', vehicle=motorcycle)


@vehicle_bp.route('/<int:vehicle_id>/delete', methods=['POST']) # GETでの削除は避ける
@login_required_custom
def delete_vehicle(vehicle_id):
    """車両を削除"""
    # 削除対象の車両を取得 (存在しない or 他人の車両なら404)
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=g.user.id).first_or_404()

    try:
        # 削除前にデフォルト車両か確認 (もしそうなら他の車両をデフォルトにするロジックが必要かも)
        was_default = motorcycle.is_default
        vehicle_name = motorcycle.name

        db.session.delete(motorcycle)

        # もし削除したのがデフォルト車両で、他に車両があれば、最初の車両をデフォルトにする (例)
        if was_default:
             other_vehicle = Motorcycle.query.filter(Motorcycle.user_id == g.user.id, Motorcycle.id != vehicle_id).first()
             if other_vehicle:
                 other_vehicle.is_default = True

        db.session.commit()
        flash(f'車両「{vehicle_name}」を削除しました。', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'車両の削除中にエラーが発生しました: {e}', 'error')
        current_app.logger.error(f"Error deleting vehicle {vehicle_id}: {e}")

    return redirect(url_for('vehicle.vehicle_list'))

@vehicle_bp.route('/<int:vehicle_id>/set_default', methods=['POST'])
@login_required_custom
def set_default_vehicle(vehicle_id):
    """指定された車両をデフォルトに設定"""
    # 設定対象の車両を取得 (存在しない or 他人の車両なら404)
    target_vehicle = Motorcycle.query.filter_by(id=vehicle_id, user_id=g.user.id).first_or_404()

    try:
        # まず、現在のユーザーの他のすべての車両の is_default を False に設定
        Motorcycle.query.filter(
            Motorcycle.user_id == g.user.id,
            Motorcycle.id != vehicle_id
        ).update({'is_default': False})

        # 対象の車両を is_default = True に設定
        target_vehicle.is_default = True

        db.session.commit()
        flash(f'車両「{target_vehicle.name}」をデフォルトに設定しました。', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'デフォルト車両の設定中にエラーが発生しました: {e}', 'error')
        current_app.logger.error(f"Error setting default vehicle {vehicle_id}: {e}")

    return redirect(url_for('vehicle.vehicle_list'))

@vehicle_bp.route('/<int:vehicle_id>/record_reset', methods=['POST'])
@login_required_custom
def record_reset(vehicle_id):
    """ODOメーターリセットを記録"""
    # 対象車両を取得
    motorcycle = Motorcycle.query.filter_by(id=vehicle_id, user_id=g.user.id).first_or_404()

    try:
        # フォームから値を取得
        reading_before_reset_str = request.form.get('reading_before_reset')
        reading_after_reset_str = request.form.get('reading_after_reset', '0') # デフォルトは0

        # 数値変換とバリデーション
        if not reading_before_reset_str:
            flash('リセット直前のメーター表示値は必須です。', 'error')
        else:
            try:
                reading_before_reset = int(reading_before_reset_str)
                reading_after_reset = int(reading_after_reset_str)

                if reading_before_reset < 0 or reading_after_reset < 0:
                     raise ValueError("走行距離は0以上である必要があります。")
                if reading_before_reset < reading_after_reset:
                     raise ValueError("リセット前の値はリセット後の値以上である必要があります。")

                # オフセット計算と更新
                added_offset = reading_before_reset - reading_after_reset
                motorcycle.odometer_offset += added_offset
                db.session.commit()
                flash(f'ODOメーターリセットを記録しました (オフセット: {motorcycle.odometer_offset} km)。', 'success')
                # 編集ページに戻る
                return redirect(url_for('vehicle.edit_vehicle', vehicle_id=vehicle_id))

            except ValueError as e:
                db.session.rollback() # エラーならロールバック
                flash(f'入力値が無効です: {e}', 'error')
            except Exception as e:
                 db.session.rollback()
                 flash(f'リセット記録中にエラーが発生しました: {e}', 'error')
                 current_app.logger.error(f"Error recording odometer reset for vehicle {vehicle_id}: {e}")

    except Exception as e:
         # フォーム取得以前のエラーなど
         flash(f'リセット記録処理中に予期せぬエラーが発生しました: {e}', 'error')
         current_app.logger.error(f"Unexpected error in record_reset for vehicle {vehicle_id}: {e}")

    # エラー時は編集ページにリダイレクト
    return redirect(url_for('vehicle.edit_vehicle', vehicle_id=vehicle_id))
