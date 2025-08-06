# motopuppu/views/help.py

from flask import Blueprint, render_template

help_bp = Blueprint('help', __name__, url_prefix='/help')

@help_bp.route('/')
def index():
    """ヘルプセンターのトップページを表示します。"""
    return render_template('help/index.html', title="ヘルプセンター")

@help_bp.route('/getting-started')
def getting_started():
    """「はじめに」ページを表示します。"""
    return render_template('help/getting_started.html', title="はじめに")

# --- ▼▼▼ ここから統合・修正 ▼▼▼ ---

@help_bp.route('/features/dashboard')
def feature_dashboard():
    """機能ガイド：ダッシュボード"""
    return render_template('help/features/dashboard.html', title="機能ガイド：ダッシュボード")

@help_bp.route('/features/vehicles')
def feature_vehicles():
    """機能ガイド：車両管理"""
    return render_template('help/features/vehicles.html', title="機能ガイド：車両管理")

@help_bp.route('/features/fuel')
def feature_fuel():
    """機能ガイド：給油記録"""
    return render_template('help/features/fuel.html', title="機能ガイド：給油記録")

@help_bp.route('/features/maintenance')
def feature_maintenance():
    """機能ガイド：整備記録"""
    return render_template('help/features/maintenance.html', title="機能ガイド：整備記録")

@help_bp.route('/features/reminders')
def feature_reminders():
    """機能ガイド：リマインダー"""
    return render_template('help/features/reminders.html', title="機能ガイド：リマインダー")

@help_bp.route('/features/notes')
def feature_notes():
    """機能ガイド：ノート機能"""
    return render_template('help/features/notes.html', title="機能ガイド：ノート機能")

@help_bp.route('/features/activity-log')
def feature_activity_log():
    """機能ガイド：活動ログ＆セッティングシートのページを表示します。"""
    # テンプレートを専用のものに修正
    return render_template('help/features/activity_log.html', title="機能ガイド：活動ログ")

@help_bp.route('/faq')
def faq():
    """よくある質問（FAQ）ページを表示します。"""
    # テンプレートを専用のものに修正
    return render_template('help/faq.html', title="よくある質問 (FAQ)")

# --- ▲▲▲ 統合・修正ここまで ▲▲▲ ---