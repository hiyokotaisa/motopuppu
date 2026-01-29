# motopuppu/models.py
from . import db
from datetime import datetime, date
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import Index, func, text
import uuid
from enum import Enum as PyEnum
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

# --- データベースモデル定義 ---

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    misskey_user_id = db.Column(db.String(100), unique=True, nullable=False)
    misskey_username = db.Column(db.String(100), nullable=True)
    display_name = db.Column(db.String(100), nullable=True, comment="ユーザーが設定する表示名")
    avatar_url = db.Column(db.String(2048), nullable=True, comment="MisskeyのアバターURL")
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    
    dashboard_layout = db.Column(db.JSON, nullable=True, comment="ダッシュボードのウィジェットの並び順")
    public_id = db.Column(db.String(36), unique=True, nullable=True, index=True, comment="公開ガレージ用の一意なID")
    is_garage_public = db.Column(db.Boolean, nullable=False, default=False, server_default='false', comment="ガレージカードを公開するか")
    garage_theme = db.Column(db.String(50), nullable=False, default='default', server_default='default', comment="ガレージカードのデザインテーマ")
    garage_hero_vehicle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='SET NULL'), nullable=True, comment="ガレージの主役車両ID")

    garage_display_settings = db.Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="ガレージカードの表示項目設定")

    show_cost_in_dashboard = db.Column(db.Boolean, nullable=False, default=True, server_default='true', comment="ダッシュボードでコスト関連情報を表示するか")
    nyanpuppu_simple_mode = db.Column(db.Boolean, nullable=False, default=False, server_default='false', comment="にゃんぷっぷーの知能を取り上げるか")
    use_lite_dashboard = db.Column(db.Boolean, nullable=False, default=False, server_default='false', comment="ログイン時に軽量ダッシュボードを表示するか")

    encrypted_misskey_api_token = db.Column(db.Text, nullable=True, comment="暗号化されたMisskey APIトークン")

    completed_tutorials = db.Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="完了したチュートリアルのキーを格納する (例: {'initial_setup': true})")

    motorcycles = db.relationship('Motorcycle', foreign_keys='Motorcycle.user_id', backref='owner', lazy=True, cascade="all, delete-orphan")
    general_notes = db.relationship('GeneralNote', backref='owner', lazy=True, cascade="all, delete-orphan")
    achievements = db.relationship('UserAchievement', backref='user', lazy='dynamic', cascade="all, delete-orphan")
    setting_sheets = db.relationship('SettingSheet', backref='user', lazy='dynamic', cascade="all, delete-orphan")
    activity_logs = db.relationship('ActivityLog', backref='user', lazy='dynamic', cascade="all, delete-orphan")
    
    circuit_targets = db.relationship('UserCircuitTarget', backref='user', lazy='dynamic', cascade="all, delete-orphan")

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
    is_racer = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    total_operating_hours = db.Column(db.Numeric(8, 2), nullable=True, default=0.00)

    image_url = db.Column(db.String(2048), nullable=True, comment="車両画像のURL")
    custom_details = db.Column(db.Text, nullable=True, comment="カスタム箇所のメモ")
    show_in_garage = db.Column(db.Boolean, nullable=False, default=True, server_default='true', comment="ガレージカードに掲載するか")

    primary_ratio = db.Column(db.Numeric(7, 4), nullable=True, comment="一次減速比")
    gear_ratios = db.Column(JSONB, nullable=True, comment="各ギアの変速比 (例: {'1': 2.846, '2': 2.000, ...})")

    fuel_entries = db.relationship('FuelEntry', backref='motorcycle', lazy='dynamic', order_by="desc(FuelEntry.entry_date)", cascade="all, delete-orphan")
    maintenance_entries = db.relationship('MaintenanceEntry', backref='motorcycle', lazy='dynamic', order_by="desc(MaintenanceEntry.maintenance_date)", cascade="all, delete-orphan")
    consumable_logs = db.relationship('ConsumableLog', backref='motorcycle', lazy='dynamic', order_by="desc(ConsumableLog.change_date)", cascade="all, delete-orphan")
    maintenance_reminders = db.relationship('MaintenanceReminder', backref='motorcycle', lazy=True, cascade="all, delete-orphan")
    general_notes = db.relationship('GeneralNote', backref='motorcycle', lazy=True)
    odo_reset_logs = db.relationship(
        'OdoResetLog', backref='motorcycle', lazy='dynamic',
        order_by="desc(OdoResetLog.reset_date)", cascade="all, delete-orphan"
    )
    setting_sheets = db.relationship('SettingSheet', backref='motorcycle', lazy='dynamic', cascade="all, delete-orphan")
    activity_logs = db.relationship('ActivityLog', backref='motorcycle', lazy='dynamic', order_by="desc(ActivityLog.activity_date)", cascade="all, delete-orphan")

    maintenance_spec_sheets = db.relationship('MaintenanceSpecSheet', backref='motorcycle', lazy='dynamic', order_by="desc(MaintenanceSpecSheet.updated_at)", cascade="all, delete-orphan")

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
            
        if not self.is_full_tank:
            return None
        
        prev_entry = FuelEntry.query.filter(
            FuelEntry.motorcycle_id == self.motorcycle_id,
            FuelEntry.total_distance < self.total_distance,
            FuelEntry.is_full_tank == True
        ).order_by(FuelEntry.total_distance.desc()).first()

        if not prev_entry:
            return None

        distance_diff = self.total_distance - prev_entry.total_distance
        
        # 区間内の合計給油量を算出 (途中給油を含む)
        fuel_consumed = db.session.query(func.sum(FuelEntry.fuel_volume)).filter(
            FuelEntry.motorcycle_id == self.motorcycle_id,
            FuelEntry.total_distance > prev_entry.total_distance,
            FuelEntry.total_distance <= self.total_distance
        ).scalar()

        if fuel_consumed is not None and fuel_consumed > 0 and distance_diff > 0:
            try:
                return round(float(distance_diff) / float(fuel_consumed), 2)
            except (ZeroDivisionError, TypeError):
                return None
                
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
        odo_text = f"({self.odometer_reading_at_maintenance:,}km)" if self.odometer_reading_at_maintenance is not None else ""
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
    last_done_km = db.Column(db.Integer, nullable=True, comment="最終実施時の『総走行距離』(計算済み)") 
    last_done_odo = db.Column(db.Integer, nullable=True, comment="最終実施時の『メーターODO値』(手動入力用)") 
    last_maintenance_entry_id = db.Column(db.Integer, db.ForeignKey('maintenance_entries.id', ondelete='SET NULL'), nullable=True)
    auto_update_from_category = db.Column(db.Boolean, nullable=False, default=True, server_default='true', comment="カテゴリ名が一致した整備記録で自動更新するか")

    snoozed_until = db.Column(db.DateTime, nullable=True, comment="スヌーズ期限 (UTC)")
    is_dismissed = db.Column(db.Boolean, nullable=False, default=False, server_default='false', comment="非表示フラグ")

    last_maintenance_entry = db.relationship(
        'MaintenanceEntry', 
        foreign_keys=[last_maintenance_entry_id],
        backref=db.backref('reminders_as_last', lazy='dynamic'), 
        lazy='joined' 
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
    is_pinned = db.Column(db.Boolean, nullable=False, default=False, server_default='false', index=True)
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

class SettingSheet(db.Model):
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
    __tablename__ = 'activity_logs'
    id = db.Column(db.Integer, primary_key=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id', ondelete='SET NULL'), nullable=True, index=True, comment="この活動ログが紐づくイベントのID")
    activity_date = db.Column(db.Date, nullable=False, index=True)
    location_name = db.Column(db.String(150), nullable=True)
    activity_title = db.Column(db.String(200), nullable=True, comment="活動名 (例: 7月の走行会)")
    location_type = db.Column(db.String(20), nullable=True, comment="場所の種別 (例: circuit, custom)")
    circuit_name = db.Column(db.String(150), nullable=True, index=True, comment="location_typeが'circuit'の場合のサーキット名")
    custom_location = db.Column(db.String(200), nullable=True, comment="location_typeが'custom'の場合の自由入力場所名")
    weather = db.Column(db.String(50), nullable=True)
    temperature = db.Column(db.Numeric(4, 1), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())
    sessions = db.relationship('SessionLog', backref='activity', lazy='dynamic', order_by="asc(SessionLog.id)", cascade="all, delete-orphan")
    
    share_with_teams = db.Column(db.Boolean, nullable=False, default=False, server_default='false', comment="この活動ログを所属チームに共有するか")

    @property
    def location_name_display(self):
        if self.location_type == 'circuit' and self.circuit_name:
            return self.circuit_name
        elif self.location_type == 'custom' and self.custom_location:
            return self.custom_location
        elif self.location_name:
            return self.location_name
        return ''
    def __repr__(self):
        return f'<ActivityLog id={self.id} date="{self.activity_date}" location="{self.location_name}">'

class SessionLog(db.Model):
    __tablename__ = 'session_logs'
    id = db.Column(db.Integer, primary_key=True)
    activity_log_id = db.Column(db.Integer, db.ForeignKey('activity_logs.id', ondelete='CASCADE'), nullable=False)
    setting_sheet_id = db.Column(db.Integer, db.ForeignKey('setting_sheets.id', ondelete='SET NULL'), nullable=True)
    session_name = db.Column(db.String(100), nullable=True, default='Session 1')
    lap_times = db.Column(JSONB, nullable=True)
    gps_tracks = db.Column(JSONB, nullable=True, comment="ラップごとのGPS軌跡データ")
    rider_feel = db.Column(db.Text, nullable=True)
    operating_hours_start = db.Column(db.Numeric(8, 2), nullable=True)
    operating_hours_end = db.Column(db.Numeric(8, 2), nullable=True)
    odo_start = db.Column(db.Integer, nullable=True)
    odo_end = db.Column(db.Integer, nullable=True)
    session_duration_hours = db.Column(db.Numeric(8, 2), nullable=True)
    session_distance = db.Column(db.Integer, nullable=True)
    best_lap_seconds = db.Column(db.Numeric(8, 3), nullable=True, index=True, comment="このセッションでのベストラップ（秒）")
    include_in_leaderboard = db.Column(db.Boolean, nullable=False, default=True, server_default='true', comment="この記録をリーダーボードに掲載するか")
    public_share_token = db.Column(db.String(36), unique=True, nullable=True, index=True, comment="外部共有用の一意なトークン (UUID)")
    is_public = db.Column(db.Boolean, nullable=False, default=False, server_default='false', comment="このセッションを外部共有するか")
    setting_sheet = db.relationship('SettingSheet', backref='sessions')
    def __repr__(self):
        return f'<SessionLog id={self.id} activity_id={self.activity_log_id}>'

class ParticipationStatus(PyEnum):
    ATTENDING = 'attending'
    TENTATIVE = 'tentative'
    NOT_ATTENDING = 'not_attending'
    @property
    def label(self):
        return {
            'attending': '参加',
            'tentative': '保留',
            'not_attending': '不参加'
        }.get(self.value, '')

class Event(db.Model):
    __tablename__ = 'events'
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, comment="イベント作成者のID")
    
    # ▼▼▼【追加】チームIDカラム ▼▼▼
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id', ondelete='CASCADE'), nullable=True, index=True, comment="チームイベントの場合のチームID")
    # ▲▲▲【追加】▲▲▲

    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='SET NULL'), nullable=True, comment="関連する車両のID")
    title = db.Column(db.String(200), nullable=False, comment="イベント名")
    description = db.Column(db.Text, nullable=True, comment="イベントの詳細説明")
    location = db.Column(db.String(200), nullable=True, comment="開催場所")
    start_datetime = db.Column(db.DateTime, nullable=False, comment="開始日時 (UTC)")
    end_datetime = db.Column(db.DateTime, nullable=True, comment="終了日時 (UTC)")
    is_public = db.Column(db.Boolean, nullable=False, default=True, server_default='true', index=True, comment="イベント一覧に公開するか")
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())
    
    owner = db.relationship('User', backref=db.backref('events', lazy='dynamic'))
    motorcycle = db.relationship('Motorcycle', backref=db.backref('events', lazy='dynamic'))
    
    # ▼▼▼【追加】チームリレーション ▼▼▼
    team = db.relationship('Team', backref=db.backref('events', lazy='dynamic', cascade="all, delete-orphan"))
    # ▲▲▲【追加】▲▲▲
    
    participants = db.relationship('EventParticipant', backref='event', lazy='dynamic', cascade="all, delete-orphan")
    activity_logs = db.relationship('ActivityLog', backref='origin_event', lazy='dynamic', order_by="desc(ActivityLog.activity_date)")
    def __repr__(self):
        return f'<Event id={self.id} title="{self.title}">'

class EventParticipant(db.Model):
    __tablename__ = 'event_participants'
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # ユーザーとの紐付け用カラムを追加
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True, comment="紐づくユーザーID")
    
    name = db.Column(db.String(100), nullable=False, comment="参加者名")
    status = db.Column(db.Enum(ParticipationStatus, values_callable=lambda x: [e.value for e in x]), nullable=False, comment="出欠ステータス")
    comment = db.Column(db.String(100), nullable=True, comment="参加者の一言コメント")
    vehicle_name = db.Column(db.String(50), nullable=True, comment="参加車両名")
    passcode_hash = db.Column(db.String(255), nullable=True, comment="出欠変更用のパスコードのハッシュ")
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    
    # ユーザーとのリレーションを追加
    user = db.relationship('User', backref=db.backref('event_participations', lazy='dynamic'))
    
    __table_args__ = (db.UniqueConstraint('event_id', 'name', name='uq_event_participant_name'),)
    def set_passcode(self, passcode):
        if passcode:
            self.passcode_hash = generate_password_hash(passcode)
        else:
            self.passcode_hash = None
    def check_passcode(self, passcode):
        if self.passcode_hash is None:
            return True
        if not passcode:
            return False
        return check_password_hash(self.passcode_hash, passcode)
    def __repr__(self):
        return f'<EventParticipant id={self.id} event_id={self.event_id} name="{self.name}" status="{self.status.value}">'

class TouringLog(db.Model):
    __tablename__ = 'touring_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='CASCADE'), nullable=False, index=True)
    
    title = db.Column(db.String(200), nullable=False)
    touring_date = db.Column(db.Date, nullable=False, index=True)
    memo = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())

    # リレーションシップ
    owner = db.relationship('User', backref=db.backref('touring_logs', lazy='dynamic'))
    motorcycle = db.relationship('Motorcycle', backref=db.backref('touring_logs', lazy='dynamic'))
    spots = db.relationship('TouringSpot', backref='touring_log', cascade="all, delete-orphan", order_by="TouringSpot.order")
    scrapbook_entries = db.relationship('TouringScrapbookEntry', backref='touring_log', cascade="all, delete-orphan")

    def __repr__(self):
        return f'<TouringLog id={self.id} title="{self.title}">'


class TouringSpot(db.Model):
    __tablename__ = 'touring_spots'
    id = db.Column(db.Integer, primary_key=True)
    touring_log_id = db.Column(db.Integer, db.ForeignKey('touring_logs.id', ondelete='CASCADE'), nullable=False, index=True)
    
    spot_name = db.Column(db.String(150), nullable=False)
    memo = db.Column(db.Text, nullable=True)
    order = db.Column(db.Integer, nullable=False, default=0, comment="スポットの順序")
    photo_link_url = db.Column(db.String(2048), nullable=True, comment="外部の写真URL")
    latitude = db.Column(db.Float, nullable=True, comment="緯度")
    longitude = db.Column(db.Float, nullable=True, comment="経度")
    google_place_id = db.Column(db.String(255), nullable=True, comment="Google Place ID")

    def __repr__(self):
        return f'<TouringSpot id={self.id} name="{self.spot_name}">'


class TouringScrapbookEntry(db.Model):
    __tablename__ = 'touring_scrapbook_entries'
    id = db.Column(db.Integer, primary_key=True)
    touring_log_id = db.Column(db.Integer, db.ForeignKey('touring_logs.id', ondelete='CASCADE'), nullable=False)
    misskey_note_id = db.Column(db.String(32), nullable=False, index=True)

    # 同じログに同じノートが重複して登録されないように制約を設ける
    __table_args__ = (db.UniqueConstraint('touring_log_id', 'misskey_note_id', name='uq_touring_log_note'),)

    def __repr__(self):
        return f'<TouringScrapbookEntry log_id={self.touring_log_id} note_id="{self.misskey_note_id}">'

class MaintenanceSpecSheet(db.Model):
    __tablename__ = 'maintenance_spec_sheets'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='CASCADE'), nullable=False)
    sheet_name = db.Column(db.String(100), nullable=False, index=True)
    spec_data = db.Column(JSONB, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())

    __table_args__ = (
        Index('ix_maintenance_spec_sheets_user_id', 'user_id'),
        Index('ix_maintenance_spec_sheets_motorcycle_id', 'motorcycle_id'),
    )

    def __repr__(self):
        return f'<MaintenanceSpecSheet id={self.id} name="{self.sheet_name}">'

class UserCircuitTarget(db.Model):
    """ユーザーごとのサーキット目標タイムを格納するモデル"""
    __tablename__ = 'user_circuit_targets'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    circuit_name = db.Column(db.String(150), nullable=False, index=True)
    target_lap_seconds = db.Column(db.Numeric(8, 3), nullable=False, comment="目標ラップタイム（秒）")

    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())

    __table_args__ = (
        db.UniqueConstraint('user_id', 'circuit_name', name='uq_user_circuit_target'),
    )

    def __repr__(self):
        return f'<UserCircuitTarget user_id={self.user_id} circuit="{self.circuit_name}" target={self.target_lap_seconds}>'

# --- ここからチーム機能関連 ---

# UserとTeamの中間テーブル
team_members = db.Table('team_members',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    db.Column('team_id', db.Integer, db.ForeignKey('teams.id', ondelete='CASCADE'), primary_key=True)
)

class Team(db.Model):
    """チーム機能のモデル"""
    __tablename__ = 'teams'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    invite_token = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())

    # リレーションシップ
    owner = db.relationship('User', backref=db.backref('owned_teams', lazy='dynamic'))
    members = db.relationship('User', secondary=team_members, lazy='dynamic',
                              backref=db.backref('teams', lazy='dynamic'))

    def __repr__(self):
        return f'<Team id={self.id} name="{self.name}">'

# --- ▼▼▼ 追加: 走行枠スケジュール管理用モデル ▼▼▼ ---
class TrackSchedule(db.Model):
    """
    サーキットの公式走行枠情報
    ユーザーの予定(Event)とは区別し、パブリックな情報として扱う。
    """
    __tablename__ = 'track_schedules'
    id = db.Column(db.Integer, primary_key=True)
    
    # マスタテーブルを作らず、文字列でサーキット名を持つ（constants.pyと連携）
    circuit_name = db.Column(db.String(150), nullable=False, index=True)
    
    date = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.Time, nullable=True)
    end_time = db.Column(db.Time, nullable=True)
    
    title = db.Column(db.String(100), nullable=False, comment="走行枠名 (例: 2S, R1, 大型枠)")
    notes = db.Column(db.String(200), nullable=True, comment="クラス分けや資格などの補足")
    
    # 将来的にスクレイピングのソース元などを記録する場合用
    source_url = db.Column(db.String(2048), nullable=True)
    
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    # 重複登録を防ぐためのユニーク制約（サーキット、日付、開始時間、タイトル）
    __table_args__ = (
        db.UniqueConstraint('circuit_name', 'date', 'start_time', 'title', name='uq_track_schedule'),
    )

    def __repr__(self):
        return f'<TrackSchedule {self.circuit_name} {self.date} {self.title}>'