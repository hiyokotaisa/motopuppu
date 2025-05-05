# motopuppu/models.py (最終修正案 - DBスキーマ同期版)

from . import db
from datetime import datetime, date
from sqlalchemy.dialects.postgresql import JSONB
# インデックス定義のために追加
from sqlalchemy import Index

# --- データベースモデル定義 ---

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    misskey_user_id = db.Column(db.String(100), unique=True, nullable=False)
    misskey_username = db.Column(db.String(100), nullable=True)
    # is_admin default は Python側で処理されるため server_default 不要
    is_admin = db.Column(db.Boolean, default=False, nullable=False)

    # Relationships
    # cascade="all, delete-orphan" は SQLAlchemy 側でのPythonオブジェクト削除時の挙動
    # DBレベルの ON DELETE は ForeignKey で設定
    motorcycles = db.relationship('Motorcycle', backref='owner', lazy=True, cascade="all, delete-orphan")
    general_notes = db.relationship('GeneralNote', backref='owner', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f'<User id={self.id} username={self.misskey_username}>'

class Motorcycle(db.Model):
    __tablename__ = 'motorcycles'
    id = db.Column(db.Integer, primary_key=True)
    # DBスキーマに合わせるため ForeignKey に ondelete を追加 (任意だが推奨)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    maker = db.Column(db.String(80), nullable=True)
    name = db.Column(db.String(80), nullable=False)
    year = db.Column(db.Integer, nullable=True)
    # DBスキーマに合わせて server_default を追加
    odometer_offset = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    # DBスキーマに合わせて server_default を追加 (boolean は 'true'/'false')
    is_default = db.Column(db.Boolean, nullable=False, server_default='false')

    # Relationships
    fuel_entries = db.relationship('FuelEntry', backref='motorcycle', lazy='dynamic', order_by="desc(FuelEntry.entry_date)", cascade="all, delete-orphan")
    maintenance_entries = db.relationship('MaintenanceEntry', backref='motorcycle', lazy='dynamic', order_by="desc(MaintenanceEntry.maintenance_date)", cascade="all, delete-orphan")
    consumable_logs = db.relationship('ConsumableLog', backref='motorcycle', lazy='dynamic', order_by="desc(ConsumableLog.change_date)", cascade="all, delete-orphan")
    maintenance_reminders = db.relationship('MaintenanceReminder', backref='motorcycle', lazy=True, cascade="all, delete-orphan")
    general_notes = db.relationship('GeneralNote', backref='motorcycle', lazy=True) # cascade は User 側と FK で定義
    # ▼▼▼ OdoResetLog へのリレーションシップを追加 ▼▼▼
    odo_reset_logs = db.relationship('OdoResetLog', backref='motorcycle', lazy='dynamic', order_by="desc(OdoResetLog.reset_date)", cascade="all, delete-orphan")


    def __repr__(self):
        return f'<Motorcycle id={self.id} name={self.name}>'


class FuelEntry(db.Model):
    __tablename__ = 'fuel_entries'
    id = db.Column(db.Integer, primary_key=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='CASCADE'), nullable=False)
    entry_date = db.Column(db.Date, nullable=False) # DB default 無いため Python default 削除
    odometer_reading = db.Column(db.Integer, nullable=False)
    total_distance = db.Column(db.Integer, nullable=False, server_default='0') # DB default に合わせる
    fuel_volume = db.Column(db.Float, nullable=False) # Float は double precision にマップされる
    price_per_liter = db.Column(db.Float, nullable=True)
    total_cost = db.Column(db.Float, nullable=True)
    station_name = db.Column(db.String(100), nullable=True)
    fuel_type = db.Column(db.String(20), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    # DB default 'true' に合わせる
    is_full_tank = db.Column(db.Boolean, nullable=False, server_default='true')

    # DBに存在するインデックスを明示的に定義
    __table_args__ = (
        Index('ix_fuel_entries_entry_date', 'entry_date'),
    )

    @property
    def km_per_liter(self):
        """区間燃費を計算するプロパティ (読み取り専用)"""
        if not self.is_full_tank: return None
        prev_full_entry = FuelEntry.query.filter(
            FuelEntry.motorcycle_id == self.motorcycle_id,
            FuelEntry.is_full_tank == True, # SQLAlchemy では == True で比較
            FuelEntry.total_distance < self.total_distance
        ).order_by(FuelEntry.total_distance.desc()).first()
        if not prev_full_entry: return None
        distance_diff = self.total_distance - prev_full_entry.total_distance
        entries_in_interval = FuelEntry.query.filter(
            FuelEntry.motorcycle_id == self.motorcycle_id,
            FuelEntry.total_distance > prev_full_entry.total_distance,
            FuelEntry.total_distance <= self.total_distance
        ).all()
        # Make sure fuel_volume is treated as float for sum
        fuel_consumed = sum(float(entry.fuel_volume) for entry in entries_in_interval if entry.fuel_volume is not None)
        if fuel_consumed > 0 and distance_diff > 0:
            try:
                # Ensure distance_diff is treated as a number
                return round(float(distance_diff) / fuel_consumed, 2)
            except (ZeroDivisionError, TypeError):
                 return None
        return None

    def __repr__(self):
        return f'<FuelEntry id={self.id} date={self.entry_date}>'


class MaintenanceEntry(db.Model):
    __tablename__ = 'maintenance_entries'
    id = db.Column(db.Integer, primary_key=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='CASCADE'), nullable=False)
    maintenance_date = db.Column(db.Date, nullable=False) # DB default 無いため Python default 削除
    odometer_reading_at_maintenance = db.Column(db.Integer, nullable=False)
    total_distance_at_maintenance = db.Column(db.Integer, nullable=False, server_default='0') # DB default に合わせる
    description = db.Column(db.Text, nullable=False)
    location = db.Column(db.String(100), nullable=True)
    # DB に default が設定されていないため、Python側の default のみ残す (SQLAlchemyがINSERT時に処理)
    parts_cost = db.Column(db.Float, nullable=True, default=0.0)
    labor_cost = db.Column(db.Float, nullable=True, default=0.0)
    category = db.Column(db.String(50), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    attachments = db.relationship('Attachment', backref='maintenance_entry', lazy=True, cascade="all, delete-orphan")

    # DBに存在するインデックスを明示的に定義
    __table_args__ = (
        Index('ix_maintenance_entries_category', 'category'),
        Index('ix_maintenance_entries_maintenance_date', 'maintenance_date'),
    )

    @property
    def total_cost(self):
        # property の計算はスキーマとは無関係
        cost_parts = self.parts_cost if self.parts_cost is not None else 0.0
        cost_labor = self.labor_cost if self.labor_cost is not None else 0.0
        return cost_parts + cost_labor

    def __repr__(self):
        return f'<MaintenanceEntry id={self.id} date={self.maintenance_date}>'


class ConsumableLog(db.Model):
    __tablename__ = 'consumable_logs'
    id = db.Column(db.Integer, primary_key=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='CASCADE'), nullable=False)
    type = db.Column(db.String(20), nullable=False)
    change_date = db.Column(db.Date, nullable=False) # DB default 無いため Python default 削除
    brand_name = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    # DBスキーマに合わせてカラム名を変更し、nullable=True にする
    odometer_reading_at_change = db.Column(db.Integer, nullable=True)

    def __repr__(self):
        return f'<ConsumableLog id={self.id} type={self.type}>'


class MaintenanceReminder(db.Model):
    __tablename__ = 'maintenance_reminders'
    id = db.Column(db.Integer, primary_key=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='CASCADE'), nullable=False)
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
    maintenance_entry_id = db.Column(db.Integer, db.ForeignKey('maintenance_entries.id', ondelete='CASCADE'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    filepath = db.Column(db.String(512), nullable=False, unique=True)
    # DB default がないため Python default 削除。Timestamp は通常アプリ側で設定
    upload_date = db.Column(db.DateTime, nullable=False)

    def __repr__(self):
        return f'<Attachment id={self.id} filename={self.filename}>'

class GeneralNote(db.Model):
    __tablename__ = 'general_notes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    # DBスキーマの ON DELETE SET NULL に合わせる
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='SET NULL'), nullable=True)
    note_date = db.Column(db.Date, nullable=False) # DB default 無いため Python default 削除
    title = db.Column(db.String(150), nullable=True)
    content = db.Column(db.Text, nullable=False)
    # DB default/index と一致
    category = db.Column(db.String(20), nullable=False, default='note', server_default='note', index=True)
    todos = db.Column(JSONB, nullable=True) # DB type jsonb と一致
    # DB default がない場合、server_default を使うことでDBレベルでデフォルトを設定できる
    # アプリケーションの一貫性のため server_default(db.func.now()) を推奨
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    # onupdate は DB レベルのトリガーがなければアプリ側で処理する必要がある
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())

    def __repr__(self):
        return f'<GeneralNote id={self.id} user_id={self.user_id} title="{self.title[:20]}">'

# ▼▼▼ 新しく OdoResetLog モデルを追加 ▼▼▼
class OdoResetLog(db.Model):
    __tablename__ = 'odo_reset_logs'

    id = db.Column(db.Integer, primary_key=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='CASCADE'), nullable=False)
    # DBのインデックス 'ix_odo_reset_logs_reset_date' に合わせて index=True を追加
    reset_date = db.Column(db.Date, nullable=False, index=True)
    odometer_before_reset = db.Column(db.Integer, nullable=False)
    odometer_after_reset = db.Column(db.Integer, nullable=False)
    offset_change = db.Column(db.Integer, nullable=False)
    # DBに default はないが、整合性のために server_default を追加 (DBに合わせるなら削除)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    # Relationships (Motorcycle 側で backref='odo_reset_logs' を定義済み)
    # motorcycle = db.relationship('Motorcycle')

    def __repr__(self):
        return f'<OdoResetLog id={self.id} date={self.reset_date}>'