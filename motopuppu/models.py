# motopuppu/models.py
from . import db
from datetime import datetime, date
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import Index, func

# --- データベースモデル定義 ---

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    misskey_user_id = db.Column(db.String(100), unique=True, nullable=False)
    misskey_username = db.Column(db.String(100), nullable=True)
    # --- ▼▼▼ ここから追加 ▼▼▼ ---
    display_name = db.Column(db.String(100), nullable=True, comment="ユーザーが設定する表示名")
    # --- ▲▲▲ ここまで追加 ▲▲▲ ---
    is_admin = db.Column(db.Boolean, default=False, nullable=False)

    motorcycles = db.relationship('Motorcycle', backref='owner', lazy=True, cascade="all, delete-orphan")
    general_notes = db.relationship('GeneralNote', backref='owner', lazy=True, cascade="all, delete-orphan")
    achievements = db.relationship('UserAchievement', backref='user', lazy='dynamic', cascade="all, delete-orphan")
    # --- ▼▼▼ 活動ログ機能 リレーションシップ追加 ▼▼▼ ---
    setting_sheets = db.relationship('SettingSheet', backref='user', lazy='dynamic', cascade="all, delete-orphan")
    activity_logs = db.relationship('ActivityLog', backref='user', lazy='dynamic', cascade="all, delete-orphan")
    # --- ▲▲▲ 活動ログ機能 リレーションシップ追加 ▲▲▲ ---

    def __repr__(self):
        return f'<User id={self.id} username={self.misskey_username}>'

class Motorcycle(db.Model):
    __tablename__ = 'motorcycles'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    maker = db.Column(db.String(80), nullable=True)
    name = db.Column(db.String(80), nullable=False)
    year = db.Column(db.Integer, nullable=True)
    odometer_offset = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    is_default = db.Column(db.Boolean, nullable=False, server_default='false')

    # --- ▼▼▼ フェーズ1変更点 ▼▼▼ ---
    is_racer = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    total_operating_hours = db.Column(db.Numeric(8, 2), nullable=True, default=0.00)
    # --- ▲▲▲ フェーズ1変更点 ▲▲▲ ---

    fuel_entries = db.relationship('FuelEntry', backref='motorcycle', lazy='dynamic', order_by="desc(FuelEntry.entry_date)", cascade="all, delete-orphan")
    maintenance_entries = db.relationship('MaintenanceEntry', backref='motorcycle', lazy='dynamic', order_by="desc(MaintenanceEntry.maintenance_date)", cascade="all, delete-orphan")
    consumable_logs = db.relationship('ConsumableLog', backref='motorcycle', lazy='dynamic', order_by="desc(ConsumableLog.change_date)", cascade="all, delete-orphan")
    maintenance_reminders = db.relationship('MaintenanceReminder', backref='motorcycle', lazy=True, cascade="all, delete-orphan")
    general_notes = db.relationship('GeneralNote', backref='motorcycle', lazy=True)
    odo_reset_logs = db.relationship(
        'OdoResetLog', backref='motorcycle', lazy='dynamic',
        order_by="desc(OdoResetLog.reset_date)", cascade="all, delete-orphan"
    )
    # --- ▼▼▼ 活動ログ機能 リレーションシップ追加 ▼▼▼ ---
    setting_sheets = db.relationship('SettingSheet', backref='motorcycle', lazy='dynamic', cascade="all, delete-orphan")
    activity_logs = db.relationship('ActivityLog', backref='motorcycle', lazy='dynamic', order_by="desc(ActivityLog.activity_date)", cascade="all, delete-orphan")
    # --- ▲▲▲ 活動ログ機能 リレーションシップ追加 ▲▲▲ ---

    def calculate_cumulative_offset_from_logs(self, target_date=None):
        if self.is_racer:
            return 0
        query = db.session.query(db.func.sum(OdoResetLog.offset_increment)).filter(OdoResetLog.motorcycle_id == self.id)
        if target_date: query = query.filter(OdoResetLog.reset_date <= target_date)
        result = query.scalar()
        return result if result is not None else 0

    def get_display_total_mileage(self):
        latest_fuel_dist = db.session.query(func.max(FuelEntry.total_distance)).filter(FuelEntry.motorcycle_id == self.id).scalar() or 0
        latest_maint_dist = db.session.query(func.max(MaintenanceEntry.total_distance_at_maintenance)).filter(MaintenanceEntry.motorcycle_id == self.id).scalar() or 0
        current_offset = self.odometer_offset if self.odometer_offset is not None else 0
        return max(latest_fuel_dist, latest_maint_dist, current_offset)

    def get_display_average_kpl(self):
        if self.is_racer:
            return None
        all_full_tank_entries = FuelEntry.query.filter(
            FuelEntry.motorcycle_id == self.id,
            FuelEntry.is_full_tank == True
        ).order_by(FuelEntry.total_distance.asc()).all()
        if len(all_full_tank_entries) < 2:
            return None
        total_distance = 0.0
        total_fuel = 0.0
        for i in range(len(all_full_tank_entries) - 1):
            start_entry = all_full_tank_entries[i]
            end_entry = all_full_tank_entries[i+1]
            if start_entry.exclude_from_average or end_entry.exclude_from_average:
                continue
            distance_diff = end_entry.total_distance - start_entry.total_distance
            fuel_in_interval = db.session.query(func.sum(FuelEntry.fuel_volume)).filter(
                FuelEntry.motorcycle_id == self.id,
                FuelEntry.total_distance > start_entry.total_distance,
                FuelEntry.total_distance <= end_entry.total_distance,
                FuelEntry.exclude_from_average == False
            ).scalar() or 0.0
            if distance_diff > 0 and fuel_in_interval > 0:
                total_distance += distance_diff
                total_fuel += fuel_in_interval
        if total_fuel > 0 and total_distance > 0:
            try:
                return round(total_distance / total_fuel, 2)
            except ZeroDivisionError:
                return None
        return None

    def __repr__(self):
        return f'<Motorcycle id={self.id} name={self.name}>'


class FuelEntry(db.Model):
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
    exclude_from_average = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    __table_args__ = (Index('ix_fuel_entries_entry_date', 'entry_date'),)
    @property
    def km_per_liter(self):
        if self.motorcycle and self.motorcycle.is_racer:
            return None
        if not self.is_full_tank: return None
        prev_full_entry = FuelEntry.query.filter(
            FuelEntry.motorcycle_id == self.motorcycle_id, FuelEntry.is_full_tank == True,
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

    @property
    def maintenance_summary_for_select(self):
        """リマインダーの選択肢で表示するための整形済みテキストを返す"""
        # --- ▼▼▼ ここから変更 ▼▼▼ ---
        odo_text = f"({self.odometer_reading_at_maintenance:,}km)" if self.odometer_reading_at_maintenance is not None else ""
        # --- ▲▲▲ ここまで変更 ▲▲▲ ---
        desc_text = f"{self.description[:25]}..." if len(self.description) > 25 else self.description
        return f"{self.maintenance_date.strftime('%Y-%m-%d')} / {desc_text} {odo_text}"

    def __repr__(self):
        return f'<MaintenanceEntry id={self.id} date={self.maintenance_date}>'

class ConsumableLog(db.Model):
    __tablename__ = 'consumable_logs'
    id = db.Column(db.Integer, primary_key=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='CASCADE'), nullable=False)
    type = db.Column(db.String(20), nullable=False)
    change_date = db.Column(db.Date, nullable=False)
    brand_name = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    odometer_reading_at_change = db.Column(db.Integer, nullable=True)
    def __repr__(self): return f'<ConsumableLog id={self.id} type={self.type}>'

class MaintenanceReminder(db.Model):
    __tablename__ = 'maintenance_reminders'
    id = db.Column(db.Integer, primary_key=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='CASCADE'), nullable=False)
    task_description = db.Column(db.String(200), nullable=False, comment="リマインド内容/カテゴリ")
    interval_km = db.Column(db.Integer, nullable=True)
    interval_months = db.Column(db.Integer, nullable=True)
    last_done_date = db.Column(db.Date, nullable=True, comment="手動入力または連携された最終実施日")
    
    # last_done_km は「総走行距離」を格納する役割を維持
    last_done_km = db.Column(db.Integer, nullable=True, comment="最終実施時の『総走行距離』(計算済み)") 
    # 新しく「メーターODO値」を保存するカラムを追加
    last_done_odo = db.Column(db.Integer, nullable=True, comment="最終実施時の『メーターODO値』(手動入力用)") 

    # 紐づく整備記録への外部キー
    last_maintenance_entry_id = db.Column(db.Integer, db.ForeignKey('maintenance_entries.id', ondelete='SET NULL'), nullable=True)
    
    auto_update_from_category = db.Column(db.Boolean, nullable=False, default=True, server_default='true', comment="カテゴリ名が一致した整備記録で自動更新するか")

    # 整備記録へのリレーションシップ
    last_maintenance_entry = db.relationship(
        'MaintenanceEntry', 
        foreign_keys=[last_maintenance_entry_id],
        backref=db.backref('reminders_as_last', lazy='dynamic'), # 逆参照
        lazy='joined' # N+1問題対策
    )

    def __repr__(self): return f'<MaintenanceReminder id={self.id} task={self.task_description}>'

class Attachment(db.Model):
    __tablename__ = 'attachments'
    id = db.Column(db.Integer, primary_key=True)
    maintenance_entry_id = db.Column(db.Integer, db.ForeignKey('maintenance_entries.id', ondelete='CASCADE'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    filepath = db.Column(db.String(512), nullable=False, unique=True)
    upload_date = db.Column(db.DateTime, nullable=False)
    def __repr__(self): return f'<Attachment id={self.id} filename={self.filename}>'

class GeneralNote(db.Model):
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
    def __repr__(self): return f'<GeneralNote id={self.id} user_id={self.user_id} title="{self.title[:20]}">'

class OdoResetLog(db.Model):
    __tablename__ = 'odo_reset_logs'
    id = db.Column(db.Integer, primary_key=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='CASCADE'), nullable=False)
    reset_date = db.Column(db.Date, nullable=False, index=True)
    display_odo_before_reset = db.Column(db.Integer, nullable=False)
    display_odo_after_reset = db.Column(db.Integer, nullable=False)
    offset_increment = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    def __repr__(self): return f'<OdoResetLog id={self.id} mc_id={self.motorcycle_id} date={self.reset_date} offset_inc={self.offset_increment}>'

class AchievementDefinition(db.Model):
    __tablename__ = 'achievement_definitions'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), unique=True, nullable=False, index=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    icon_class = db.Column(db.String(100), nullable=True)
    category_code = db.Column(db.String(50), nullable=False, index=True)
    category_name = db.Column(db.String(100), nullable=False)
    share_text_template = db.Column(db.Text, nullable=True)
    trigger_event_type = db.Column(db.String(100), nullable=True, index=True)
    criteria = db.Column(JSONB, nullable=True)
    user_achievements = db.relationship('UserAchievement', backref='definition', lazy='dynamic')
    def __repr__(self): return f'<AchievementDefinition code={self.code} name="{self.name}">'

class UserAchievement(db.Model):
    __tablename__ = 'user_achievements'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    achievement_code = db.Column(db.String(100), db.ForeignKey('achievement_definitions.code', ondelete='CASCADE'), nullable=False, index=True)
    unlocked_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('user_id', 'achievement_code', name='uq_user_achievement'),)
    def __repr__(self): return f'<UserAchievement user_id={self.user_id} achievement_code={self.achievement_code} unlocked_at={self.unlocked_at}>'

# --- ▼▼▼ 活動ログ機能 (ここから) ▼▼▼ ---

class SettingSheet(db.Model):
    """再利用可能なセッティング情報を格納するモデル"""
    __tablename__ = 'setting_sheets'
    id = db.Column(db.Integer, primary_key=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    sheet_name = db.Column(db.String(100), nullable=False, index=True)
    details = db.Column(JSONB, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())

    def __repr__(self):
        return f'<SettingSheet id={self.id} name="{self.sheet_name}">'

class ActivityLog(db.Model):
    """1日の活動（サーキット走行、ツーリング等）の親コンテナとなるモデル"""
    __tablename__ = 'activity_logs'
    id = db.Column(db.Integer, primary_key=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    activity_date = db.Column(db.Date, nullable=False, index=True)
    
    # --- ▼▼▼ 変更 ▼▼▼ ---
    # 既存の location_name は nullable に変更して後方互換性を維持
    location_name = db.Column(db.String(150), nullable=True)
    
    # 新しい構造化されたフィールドを追加
    activity_title = db.Column(db.String(200), nullable=True, comment="活動名 (例: 7月の走行会)")
    location_type = db.Column(db.String(20), nullable=True, comment="場所の種別 (例: circuit, custom)")
    circuit_name = db.Column(db.String(150), nullable=True, index=True, comment="location_typeが'circuit'の場合のサーキット名")
    custom_location = db.Column(db.String(200), nullable=True, comment="location_typeが'custom'の場合の自由入力場所名")
    # --- ▲▲▲ 変更ここまで ▲▲▲ ---
    
    weather = db.Column(db.String(50), nullable=True)
    temperature = db.Column(db.Numeric(4, 1), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())
    
    # ▼▼▼ lazy='dynamic' は元のまま維持 ▼▼▼
    sessions = db.relationship('SessionLog', backref='activity', lazy='dynamic', order_by="asc(SessionLog.id)", cascade="all, delete-orphan")

    # ▼▼▼ 影響のない location_name_display プロパティのみ追加 ▼▼▼
    @property
    def location_name_display(self):
        """共有や表示に使うための場所名を返すプロパティ"""
        if self.location_type == 'circuit' and self.circuit_name:
            return self.circuit_name
        elif self.location_type == 'custom' and self.custom_location:
            return self.custom_location
        # 後方互換性のため、古い location_name フィールドもチェック
        elif self.location_name:
            return self.location_name
        return ''

    def __repr__(self):
        return f'<ActivityLog id={self.id} date="{self.activity_date}" location="{self.location_name}">'

class SessionLog(db.Model):
    """個別の走行セッションの記録モデル"""
    __tablename__ = 'session_logs'
    id = db.Column(db.Integer, primary_key=True)
    activity_log_id = db.Column(db.Integer, db.ForeignKey('activity_logs.id', ondelete='CASCADE'), nullable=False)
    setting_sheet_id = db.Column(db.Integer, db.ForeignKey('setting_sheets.id', ondelete='SET NULL'), nullable=True)
    session_name = db.Column(db.String(100), nullable=True, default='Session 1')
    lap_times = db.Column(JSONB, nullable=True)
    rider_feel = db.Column(db.Text, nullable=True)
    
    # 従来のデータ形式 (後方互換性のために残す)
    operating_hours_start = db.Column(db.Numeric(8, 2), nullable=True)
    operating_hours_end = db.Column(db.Numeric(8, 2), nullable=True)
    odo_start = db.Column(db.Integer, nullable=True)
    odo_end = db.Column(db.Integer, nullable=True)

    # --- ▼▼▼ 新しいデータ形式 ▼▼▼ ---
    session_duration_hours = db.Column(db.Numeric(8, 2), nullable=True) # レーサー用のセッション稼働時間
    session_distance = db.Column(db.Integer, nullable=True)          # 公道車用のセッション走行距離
    
    # --- ▼▼▼ 変更 ▼▼▼ ---
    # 将来のリーダーボード機能のためのフィールド
    best_lap_seconds = db.Column(db.Numeric(8, 3), nullable=True, index=True, comment="このセッションでのベストラップ（秒）")
    include_in_leaderboard = db.Column(db.Boolean, nullable=False, default=True, server_default='true', comment="この記録をリーダーボードに掲載するか")
    # --- ▲▲▲ 変更ここまで ▲▲▲ ---

    setting_sheet = db.relationship('SettingSheet', backref='sessions')

    def __repr__(self):
        return f'<SessionLog id={self.id} activity_id={self.activity_log_id}>'

# --- ▲▲▲ 活動ログ機能 (ここまで) ▲▲▲ ---