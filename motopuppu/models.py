# motopuppu/models.py
from . import db # __init__.py で初期化された SQLAlchemy オブジェクトをインポート
from datetime import datetime, date
# from flask_login import UserMixin # Flask-Login を使う場合

# --- データベースモデル定義 ---

# Flask-Loginを使う場合のUserMixinを継承
class User(db.Model): #, UserMixin):
    """アプリケーションのユーザーモデル"""
    __tablename__ = 'users' # テーブル名を明示的に指定 (任意)
    id = db.Column(db.Integer, primary_key=True)
    misskey_user_id = db.Column(db.String(100), unique=True, nullable=False) # Misskeyインスタンス内での一意なID
    misskey_username = db.Column(db.String(100), nullable=True) # Misskeyユーザー名
    is_admin = db.Column(db.Boolean, default=False, nullable=False) # 管理者フラグ (開発用)

    # Userが削除されたら、関連するレコードも削除 (cascade)
    motorcycles = db.relationship('Motorcycle', backref='owner', lazy=True, cascade="all, delete-orphan")
    # ▼▼▼ GeneralNoteへのリレーションシップを追加 ▼▼▼
    general_notes = db.relationship('GeneralNote', backref='owner', lazy=True, cascade="all, delete-orphan")


    # Flask-Loginを使う場合に必要
    # def get_id(self):
    #    return str(self.id)

    def __repr__(self):
        # デバッグ時に分かりやすい表現を返す
        return f'<User id={self.id} username={self.misskey_username}>'

class Motorcycle(db.Model):
    """車両情報モデル"""
    __tablename__ = 'motorcycles'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False) # 所有ユーザーへの外部キー
    maker = db.Column(db.String(80), nullable=True) # メーカー名
    name = db.Column(db.String(80), nullable=False) # 車両名
    year = db.Column(db.Integer, nullable=True) # 年式
    odometer_offset = db.Column(db.Integer, nullable=False, default=0) # ODOメーターリセットによる累積オフセット
    is_default = db.Column(db.Boolean, default=False, nullable=False) # ユーザーのデフォルト車両か (複数の車両を持つ場合)

    # 関連レコードへのリレーションシップ (削除時の連鎖設定)
    fuel_entries = db.relationship('FuelEntry', backref='motorcycle', lazy='dynamic', order_by="desc(FuelEntry.entry_date)", cascade="all, delete-orphan")
    maintenance_entries = db.relationship('MaintenanceEntry', backref='motorcycle', lazy='dynamic', order_by="desc(MaintenanceEntry.maintenance_date)", cascade="all, delete-orphan")
    consumable_logs = db.relationship('ConsumableLog', backref='motorcycle', lazy='dynamic', order_by="desc(ConsumableLog.change_date)", cascade="all, delete-orphan")
    maintenance_reminders = db.relationship('MaintenanceReminder', backref='motorcycle', lazy=True, cascade="all, delete-orphan")
    # general_notes への参照は GeneralNote モデルの backref='general_notes' で自動的に作成される
    # attachments = db.relationship('Attachment', backref='motorcycle', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f'<Motorcycle id={self.id} name={self.name}>'

class FuelEntry(db.Model):
    """給油記録モデル"""
    __tablename__ = 'fuel_entries'
    id = db.Column(db.Integer, primary_key=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id'), nullable=False) # 関連車両への外部キー
    entry_date = db.Column(db.Date, nullable=False, default=date.today) # 給油日
    odometer_reading = db.Column(db.Integer, nullable=False) # 給油時のメーター表示値
    total_distance = db.Column(db.Integer, nullable=False) # 計算された総走行距離 (odo + offset)
    fuel_volume = db.Column(db.Float, nullable=False) # 給油量 (L)
    price_per_liter = db.Column(db.Float, nullable=True) # リッター単価 (円/L)
    total_cost = db.Column(db.Float, nullable=True) # 合計金額 (自動計算 or 手入力)
    station_name = db.Column(db.String(100), nullable=True) # 給油スタンド名
    fuel_type = db.Column(db.String(20), nullable=True) # 油種 (例: Regular, Premium)
    notes = db.Column(db.Text, nullable=True) # メモ
    is_full_tank = db.Column(db.Boolean, nullable=False, default=True, server_default='1') # 満タン給油フラグ

    @property
    def km_per_liter(self):
        """区間燃費を計算するプロパティ (読み取り専用)"""
        if not self.is_full_tank: return None
        prev_full_entry = FuelEntry.query.filter(
            FuelEntry.motorcycle_id == self.motorcycle_id,
            FuelEntry.is_full_tank == True,
            FuelEntry.total_distance < self.total_distance
        ).order_by(FuelEntry.total_distance.desc()).first()
        if not prev_full_entry: return None
        distance_diff = self.total_distance - prev_full_entry.total_distance
        entries_in_interval = FuelEntry.query.filter(
            FuelEntry.motorcycle_id == self.motorcycle_id,
            FuelEntry.total_distance > prev_full_entry.total_distance,
            FuelEntry.total_distance <= self.total_distance
        ).all()
        fuel_consumed = sum(entry.fuel_volume for entry in entries_in_interval)
        if fuel_consumed > 0 and distance_diff > 0:
            try: return round(distance_diff / fuel_consumed, 2)
            except ZeroDivisionError: return None
        return None

    def __repr__(self):
        return f'<FuelEntry id={self.id} date={self.entry_date}>'

class MaintenanceEntry(db.Model):
    __tablename__ = 'maintenance_entries'
    id = db.Column(db.Integer, primary_key=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id'), nullable=False)
    maintenance_date = db.Column(db.Date, nullable=False, default=date.today)
    odometer_reading_at_maintenance = db.Column(db.Integer, nullable=False)
    total_distance_at_maintenance = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text, nullable=False)
    location = db.Column(db.String(100), nullable=True)
    parts_cost = db.Column(db.Float, nullable=True, default=0.0)
    labor_cost = db.Column(db.Float, nullable=True, default=0.0)
    category = db.Column(db.String(50), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    attachments = db.relationship('Attachment', backref='maintenance_entry', lazy=True, cascade="all, delete-orphan")
    @property
    def total_cost(self):
        cost_parts = self.parts_cost if self.parts_cost is not None else 0.0
        cost_labor = self.labor_cost if self.labor_cost is not None else 0.0
        return cost_parts + cost_labor
    def __repr__(self):
        return f'<MaintenanceEntry id={self.id} date={self.maintenance_date}>'

class ConsumableLog(db.Model):
    __tablename__ = 'consumable_logs'
    id = db.Column(db.Integer, primary_key=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id'), nullable=False)
    type = db.Column(db.String(20), nullable=False)
    change_date = db.Column(db.Date, nullable=False, default=date.today)
    total_distance_at_change = db.Column(db.Integer, nullable=False)
    brand_name = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    def __repr__(self):
        return f'<ConsumableLog id={self.id} type={self.type}>'

class MaintenanceReminder(db.Model):
    __tablename__ = 'maintenance_reminders'
    id = db.Column(db.Integer, primary_key=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id'), nullable=False)
    task_description = db.Column(db.String(200), nullable=False)
    interval_km = db.Column(db.Integer, nullable=True)
    interval_months = db.Column(db.Integer, nullable=True)
    last_done_date = db.Column(db.Date, nullable=True)
    last_done_km = db.Column(db.Integer, nullable=True)
    def __repr__(self):
        return f'<MaintenanceReminder id={self.id} task={self.task_description}>'

class Attachment(db.Model):
    __tablename__ = 'attachments'
    id = db.Column(db.Integer, primary_key=True)
    maintenance_entry_id = db.Column(db.Integer, db.ForeignKey('maintenance_entries.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    filepath = db.Column(db.String(512), nullable=False, unique=True)
    upload_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    def __repr__(self):
        return f'<Attachment id={self.id} filename={self.filename}>'

# --- ▼▼▼ 新しいモデル: GeneralNote を追加 ▼▼▼ ---
class GeneralNote(db.Model):
    """走行距離に紐づかない一般的なメモ"""
    __tablename__ = 'general_notes'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False) # 所有ユーザー (必須)
    # nullable=True で車両との紐付けを任意（オプション）にする
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id'), nullable=True)
    note_date = db.Column(db.Date, nullable=False, default=date.today) # メモの日付 (必須)
    title = db.Column(db.String(150), nullable=True) # タイトル (任意)
    content = db.Column(db.Text, nullable=False) # メモ本文 (必須)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow) # 作成日時
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow) # 更新日時

    # Motorcycleへのリレーションシップ定義 (メモから車両情報を参照できるように)
    # backref='general_notes' により、Motorcycleオブジェクトから motorcycle.general_notes でメモを参照できる
    # cascade設定はUserモデル側で行われているため、ここではシンプルに定義
    motorcycle = db.relationship('Motorcycle', backref=db.backref('general_notes', lazy=True))
    # Userへのリレーションシップは User モデル側の backref='owner' で定義済み

    def __repr__(self):
        # デバッグ時の表示用
        return f'<GeneralNote id={self.id} user_id={self.user_id} title="{self.title[:20]}">'
# --- ▲▲▲ GeneralNote モデル定義ここまで ▲▲▲ ---