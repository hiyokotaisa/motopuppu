# motopuppu/models.py

from . import db
from datetime import datetime, date # date をインポートリストに追加 (または確認)
from sqlalchemy.dialects.postgresql import JSONB
# インデックス定義のために追加
from sqlalchemy import Index

# --- データベースモデル定義 ---

class User(db.Model):
    # (変更なし)
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    misskey_user_id = db.Column(db.String(100), unique=True, nullable=False)
    misskey_username = db.Column(db.String(100), nullable=True)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)

    motorcycles = db.relationship('Motorcycle', backref='owner', lazy=True, cascade="all, delete-orphan")
    general_notes = db.relationship('GeneralNote', backref='owner', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f'<User id={self.id} username={self.misskey_username}>'

class Motorcycle(db.Model):
    __tablename__ = 'motorcycles'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    maker = db.Column(db.String(80), nullable=True)
    name = db.Column(db.String(80), nullable=False)
    year = db.Column(db.Integer, nullable=True)
    odometer_offset = db.Column(db.Integer, nullable=False, default=0, server_default='0') # 累積オフセットキャッシュとして維持
    is_default = db.Column(db.Boolean, nullable=False, server_default='false')

    fuel_entries = db.relationship('FuelEntry', backref='motorcycle', lazy='dynamic', order_by="desc(FuelEntry.entry_date)", cascade="all, delete-orphan")
    maintenance_entries = db.relationship('MaintenanceEntry', backref='motorcycle', lazy='dynamic', order_by="desc(MaintenanceEntry.maintenance_date)", cascade="all, delete-orphan")
    consumable_logs = db.relationship('ConsumableLog', backref='motorcycle', lazy='dynamic', order_by="desc(ConsumableLog.change_date)", cascade="all, delete-orphan")
    maintenance_reminders = db.relationship('MaintenanceReminder', backref='motorcycle', lazy=True, cascade="all, delete-orphan")
    general_notes = db.relationship('GeneralNote', backref='motorcycle', lazy=True)
    
    odo_reset_logs = db.relationship(
        'OdoResetLog',
        backref='motorcycle',
        lazy='dynamic',
        order_by="desc(OdoResetLog.reset_date)", 
        cascade="all, delete-orphan" 
    )

    # ▼▼▼ ヘルパーメソッドを追加 ▼▼▼
    def calculate_cumulative_offset_from_logs(self, target_date=None):
        """
        指定された日付（またはそれ以前）のOdoResetLogに基づいて
        累積オフセット値を計算する。
        target_dateがNoneの場合は、すべて（最新）のログを対象とする。
        """
        # OdoResetLog をインポート (メソッド内インポートは必要に応じて)
        # from .models import OdoResetLog # 通常はファイル先頭でインポートされていれば不要

        query = db.session.query(
            db.func.sum(OdoResetLog.offset_increment)
        ).filter(
            OdoResetLog.motorcycle_id == self.id # 対象車両に限定
        )
        if target_date:
             query = query.filter(OdoResetLog.reset_date <= target_date)
        
        result = query.scalar() # 合計値を取得 (結果がない場合はNone)

        return result if result is not None else 0 # 結果がNoneなら0を返す
    # ▲▲▲ ヘルパーメソッドここまで ▲▲▲

    def __repr__(self):
        return f'<Motorcycle id={self.id} name={self.name}>'


class FuelEntry(db.Model):
    # (変更なし)
    __tablename__ = 'fuel_entries'
    id = db.Column(db.Integer, primary_key=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='CASCADE'), nullable=False)
    entry_date = db.Column(db.Date, nullable=False)
    odometer_reading = db.Column(db.Integer, nullable=False)
    total_distance = db.Column(db.Integer, nullable=False, server_default='0')
    fuel_volume = db.Column(db.Float, nullable=False)
    price_per_liter = db.Column(db.Float, nullable=True)
    total_cost = db.Column(db.Float, nullable=True)
    station_name = db.Column(db.String(100), nullable=True)
    fuel_type = db.Column(db.String(20), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    is_full_tank = db.Column(db.Boolean, nullable=False, server_default='true')
    __table_args__ = (Index('ix_fuel_entries_entry_date', 'entry_date'),)

    @property
    def km_per_liter(self):
        # (変更なし)
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
        fuel_consumed = sum(float(entry.fuel_volume) for entry in entries_in_interval if entry.fuel_volume is not None)
        if fuel_consumed > 0 and distance_diff > 0:
            try: return round(float(distance_diff) / fuel_consumed, 2)
            except (ZeroDivisionError, TypeError): return None
        return None

    def __repr__(self):
        return f'<FuelEntry id={self.id} date={self.entry_date}>'


class MaintenanceEntry(db.Model):
    # (変更なし)
    __tablename__ = 'maintenance_entries'
    id = db.Column(db.Integer, primary_key=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='CASCADE'), nullable=False)
    maintenance_date = db.Column(db.Date, nullable=False)
    odometer_reading_at_maintenance = db.Column(db.Integer, nullable=False)
    total_distance_at_maintenance = db.Column(db.Integer, nullable=False, server_default='0')
    description = db.Column(db.Text, nullable=False)
    location = db.Column(db.String(100), nullable=True)
    parts_cost = db.Column(db.Float, nullable=True, default=0.0)
    labor_cost = db.Column(db.Float, nullable=True, default=0.0)
    category = db.Column(db.String(50), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    attachments = db.relationship('Attachment', backref='maintenance_entry', lazy=True, cascade="all, delete-orphan")
    __table_args__ = (Index('ix_maintenance_entries_category', 'category'), Index('ix_maintenance_entries_maintenance_date', 'maintenance_date'),)

    @property
    def total_cost(self):
        cost_parts = self.parts_cost if self.parts_cost is not None else 0.0
        cost_labor = self.labor_cost if self.labor_cost is not None else 0.0
        return cost_parts + cost_labor

    def __repr__(self):
        return f'<MaintenanceEntry id={self.id} date={self.maintenance_date}>'


class ConsumableLog(db.Model):
    # (変更なし)
    __tablename__ = 'consumable_logs'
    id = db.Column(db.Integer, primary_key=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='CASCADE'), nullable=False)
    type = db.Column(db.String(20), nullable=False)
    change_date = db.Column(db.Date, nullable=False)
    brand_name = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    odometer_reading_at_change = db.Column(db.Integer, nullable=True)

    def __repr__(self):
        return f'<ConsumableLog id={self.id} type={self.type}>'


class MaintenanceReminder(db.Model):
    # (変更なし)
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
    # (変更なし)
    __tablename__ = 'attachments'
    id = db.Column(db.Integer, primary_key=True)
    maintenance_entry_id = db.Column(db.Integer, db.ForeignKey('maintenance_entries.id', ondelete='CASCADE'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    filepath = db.Column(db.String(512), nullable=False, unique=True)
    upload_date = db.Column(db.DateTime, nullable=False)

    def __repr__(self):
        return f'<Attachment id={self.id} filename={self.filename}>'

class GeneralNote(db.Model):
    # (変更なし)
    __tablename__ = 'general_notes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='SET NULL'), nullable=True)
    note_date = db.Column(db.Date, nullable=False)
    title = db.Column(db.String(150), nullable=True)
    content = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(20), nullable=False, default='note', server_default='note', index=True)
    todos = db.Column(JSONB, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())

    def __repr__(self):
        return f'<GeneralNote id={self.id} user_id={self.user_id} title="{self.title[:20]}">'

class OdoResetLog(db.Model):
    # (変更なし - フェーズ1で確定した定義)
    __tablename__ = 'odo_reset_logs'
    id = db.Column(db.Integer, primary_key=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='CASCADE'), nullable=False)
    reset_date = db.Column(db.Date, nullable=False, index=True) 
    display_odo_before_reset = db.Column(db.Integer, nullable=False) 
    display_odo_after_reset = db.Column(db.Integer, nullable=False)  
    offset_increment = db.Column(db.Integer, nullable=False) 
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    def __repr__(self):
        return f'<OdoResetLog id={self.id} mc_id={self.motorcycle_id} date={self.reset_date} offset_inc={self.offset_increment}>'