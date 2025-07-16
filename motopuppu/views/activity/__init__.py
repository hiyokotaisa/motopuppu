# motopuppu/views/activity/__init__.py
from flask import Blueprint

# 新しいBlueprintを定義。テンプレートフォルダのパスを正しく設定することが重要
activity_bp = Blueprint(
    'activity',
    __name__,
    template_folder='../../../templates', # ルートのtemplatesディレクトリを指す
    url_prefix='/activity'
)

# 分割した各ルートファイルをインポートして、Blueprintにルートを登録
from . import activity_routes, session_routes, setting_routes