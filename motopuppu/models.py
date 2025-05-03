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

    # Userが削除されたら、関連するMotorcycleも削除 (cascade)
    motorcycles = db.relationship('Motorcycle', backref='owner', lazy=True, cascade="all, delete-orphan")

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
    # order_by で取得時のデフォルトソート順を指定
    fuel_entries = db.relationship('FuelEntry', backref='motorcycle', lazy='dynamic', order_by="desc(FuelEntry.entry_date)", cascade="all, delete-orphan")
    maintenance_entries = db.relationship('MaintenanceEntry', backref='motorcycle', lazy='dynamic', order_by="desc(MaintenanceEntry.maintenance_date)", cascade="all, delete-orphan")
    consumable_logs = db.relationship('ConsumableLog', backref='motorcycle', lazy='dynamic', order_by="desc(ConsumableLog.change_date)", cascade="all, delete-orphan")
    maintenance_reminders = db.relationship('MaintenanceReminder', backref='motorcycle', lazy=True, cascade="all, delete-orphan")
    # attachments = db.relationship('Attachment', backref='motorcycle', lazy=True, cascade="all, delete-orphan") # 車両自体に添付する場合

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
        """
        この給油記録が「満タン」の場合に、その直前の「満タン」記録との間の
        区間燃費を計算するプロパティ (読み取り専用)。
        満タンでない場合や、直前の満タン記録がない場合は None を返す。
        """
        # この記録自体が満タンでなければ計算対象外
        if not self.is_full_tank:
            return None

        # 同じ車両で、この記録より前の「満タン」記録の中で最新のものを取得
        prev_full_entry = FuelEntry.query.filter(
            FuelEntry.motorcycle_id == self.motorcycle_id,
            FuelEntry.is_full_tank == True, # 満タン記録に絞る
            FuelEntry.total_distance < self.total_distance
        ).order_by(FuelEntry.total_distance.desc()).first()

        # 直前の満タン記録が見つからない場合は計算不可
        if not prev_full_entry:
            return None

        # 走行距離を計算
        distance_diff = self.total_distance - prev_full_entry.total_distance

        # 消費燃料を計算: 直前の満タン記録の後から今回の記録までの給油量の合計
        # (今回の給油量は含める - 今回満タンにした量で前の区間の燃費を計算するため)
        entries_in_interval = FuelEntry.query.filter(
            FuelEntry.motorcycle_id == self.motorcycle_id,
            FuelEntry.total_distance > prev_full_entry.total_distance,
            FuelEntry.total_distance <= self.total_distance
        ).all()
        fuel_consumed = sum(entry.fuel_volume for entry in entries_in_interval)

        # 燃費計算 (走行距離と消費燃料が共に正の場合のみ)
        if fuel_consumed > 0 and distance_diff > 0:
            try:
                return round(distance_diff / fuel_consumed, 2)
            except ZeroDivisionError:
                return None # 念のため
        else:
            return None # 計算不能

    def __repr__(self):
        return f'<FuelEntry id={self.id} date={self.entry_date}>'

# --- MaintenanceEntry, ConsumableLog, MaintenanceReminder, Attachment クラス (変更なし) ---
class MaintenanceEntry(db.Model):
    __tablename__ = 'maintenance_entries'
    id = db.Column(db.Integer, primary_key=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id'), nullable=False) # 関連車両への外部キー
    maintenance_date = db.Column(db.Date, nullable=False, default=date.today) # 整備日
    odometer_reading_at_maintenance = db.Column(db.Integer, nullable=False) # 整備時のメーター表示値
    total_distance_at_maintenance = db.Column(db.Integer, nullable=False) # 計算された総走行距離
    description = db.Column(db.Text, nullable=False) # 整備内容
    location = db.Column(db.String(100), nullable=True) # 整備場所
    parts_cost = db.Column(db.Float, nullable=True, default=0.0) # 部品代
    labor_cost = db.Column(db.Float, nullable=True, default=0.0) # 工賃
    category = db.Column(db.String(50), nullable=True) # 整備カテゴリ (例: Engine, Brakes, Tire, Oil, Chain, Electrical, Other)
    notes = db.Column(db.Text, nullable=True) # メモ
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
    type = db.Column(db.String(20), nullable=False) # 'Tire' or 'Oil' など、識別用の文字列
    change_date = db.Column(db.Date, nullable=False, default=date.today) # 交換日
    total_distance_at_change = db.Column(db.Integer, nullable=False) # 交換時の総走行距離
    brand_name = db.Column(db.String(100), nullable=True) # 銘柄 (タイヤ名、オイル名など)
    notes = db.Column(db.Text, nullable=True) # メモ (例: タイヤの位置 Front/Rear, オイル粘度)
    def __repr__(self):
        return f'<ConsumableLog id={self.id} type={self.type}>'

class MaintenanceReminder(db.Model):
    __tablename__ = 'maintenance_reminders'
    id = db.Column(db.Integer, primary_key=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id'), nullable=False)
    task_description = db.Column(db.String(200), nullable=False) # リマインド内容 (例: エンジンオイル交換)
    interval_km = db.Column(db.Integer, nullable=True) # 距離間隔 (km)。指定しない場合はNone
    interval_months = db.Column(db.Integer, nullable=True) # 期間間隔 (月)。指定しない場合はNone
    last_done_date = db.Column(db.Date, nullable=True) # 最後に実施した日
    last_done_km = db.Column(db.Integer, nullable=True) # 最後に実施した時の総走行距離
    def __repr__(self):
        return f'<MaintenanceReminder id={self.id} task={self.task_description}>'

class Attachment(db.Model):
    __tablename__ = 'attachments'
    id = db.Column(db.Integer, primary_key=True)
    maintenance_entry_id = db.Column(db.Integer, db.ForeignKey('maintenance_entries.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False) # アップロードされた元のファイル名
    filepath = db.Column(db.String(512), nullable=False, unique=True)
    upload_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow) # アップロード日時(UTC)
    def __repr__(self):
        return f'<Attachment id={self.id} filename={self.filename}>'
