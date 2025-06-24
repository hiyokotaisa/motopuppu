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
    is_admin = db.Column(db.Boolean, default=False, nullable=False)

    motorcycles = db.relationship('Motorcycle', backref='owner', lazy=True, cascade="all, delete-orphan")
    general_notes = db.relationship('GeneralNote', backref='owner', lazy=True, cascade="all, delete-orphan")
    achievements = db.relationship('UserAchievement', backref='user', lazy='dynamic', cascade="all, delete-orphan")

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
    # consumable_logs は既存のまま
    consumable_logs = db.relationship('ConsumableLog', backref='motorcycle', lazy='dynamic', order_by="desc(ConsumableLog.change_date)", cascade="all, delete-orphan")
    maintenance_reminders = db.relationship('MaintenanceReminder', backref='motorcycle', lazy=True, cascade="all, delete-orphan")
    general_notes = db.relationship('GeneralNote', backref='motorcycle', lazy=True)
    odo_reset_logs = db.relationship(
        'OdoResetLog', backref='motorcycle', lazy='dynamic',
        order_by="desc(OdoResetLog.reset_date)", cascade="all, delete-orphan"
    )

    def calculate_cumulative_offset_from_logs(self, target_date=None):
        # --- ▼▼▼ フェーズ1変更点 (レーサー車両はオフセット計算対象外) ▼▼▼ ---
        if self.is_racer:
            return 0 # レーサー車両は常にオフセット0
        # --- ▲▲▲ フェーズ1変更点 ▲▲▲ ---
        query = db.session.query(db.func.sum(OdoResetLog.offset_increment)).filter(OdoResetLog.motorcycle_id == self.id)
        if target_date: query = query.filter(OdoResetLog.reset_date <= target_date)
        result = query.scalar()
        return result if result is not None else 0

    def get_display_total_mileage(self):
        # --- ▼▼▼ フェーズ1変更点 (このメソッドは公道車専用の総走行距離を返すものとする) ▼▼▼ ---
        # レーサー車両の場合は total_operating_hours を使用するため、このメソッドの呼び出し側で分岐するか、
        # またはこのメソッド自体が is_racer を見て値を返すようにする。
        # 今回は、このメソッドは公道車のODOベースの距離を返し、
        # テンプレート等で is_racer を見て表示を切り替える方針とします。
        # よって、このメソッド内のロジックは変更なし。
        # --- ▲▲▲ フェーズ1変更点 ▲▲▲ ---
        latest_fuel_dist = db.session.query(func.max(FuelEntry.total_distance)).filter(FuelEntry.motorcycle_id == self.id).scalar() or 0
        latest_maint_dist = db.session.query(func.max(MaintenanceEntry.total_distance_at_maintenance)).filter(MaintenanceEntry.motorcycle_id == self.id).scalar() or 0
        current_offset = self.odometer_offset if self.odometer_offset is not None else 0
        return max(latest_fuel_dist, latest_maint_dist, current_offset)

    def get_display_average_kpl(self):
        # --- ▼▼▼ フェーズ1変更点 (レーサー車両は燃費計算対象外) ▼▼▼ ---
        if self.is_racer:
            return None
        # --- ▲▲▲ フェーズ1変更点 ▲▲▲

        # --- ▼▼▼ 計算ロジック修正 ▼▼▼
        # is_full_tank=Trueの記録をすべて取得し、走行距離でソート
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

            # 区間の始点か終点が「除外」設定の場合、この区間は計算に含めない
            if start_entry.exclude_from_average or end_entry.exclude_from_average:
                continue

            distance_diff = end_entry.total_distance - start_entry.total_distance

            # この区間内にある「除外されていない」給油記録の給油量を合計する
            fuel_in_interval = db.session.query(func.sum(FuelEntry.fuel_volume)).filter(
                FuelEntry.motorcycle_id == self.id,
                FuelEntry.total_distance > start_entry.total_distance,
                FuelEntry.total_distance <= end_entry.total_distance,
                FuelEntry.exclude_from_average == False # 区間内の給油も除外フラグを考慮
            ).scalar() or 0.0

            if distance_diff > 0 and fuel_in_interval > 0:
                total_distance += distance_diff
                total_fuel += fuel_in_interval

        if total_fuel > 0 and total_distance > 0:
            try:
                return round(total_distance / total_fuel, 2)
            except ZeroDivisionError:
                return None
        # --- ▲▲▲ 計算ロジック修正 ▲▲▲
        return None

    def __repr__(self):
        return f'<Motorcycle id={self.id} name={self.name}>'


class FuelEntry(db.Model):
    __tablename__ = 'fuel_entries'
    id = db.Column(db.Integer, primary_key=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='CASCADE'), nullable=False)
    entry_date = db.Column(db.Date, nullable=False)
    odometer_reading = db.Column(db.Integer, nullable=False)
    total_distance = db.Column(db.Integer, nullable=False, server_default='0') # 実走行距離 (ODO+オフセット)
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
        # --- ▼▼▼ フェーズ1変更点 (関連するMotorcycleがレーサーなら燃費計算不可) ▼▼▼ ---
        if self.motorcycle and self.motorcycle.is_racer: # self.motorcycle が None の可能性も考慮
            return None
        # --- ▲▲▲ フェーズ1変更点 ▲▲▲ ---
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
    total_distance_at_maintenance = db.Column(db.Integer, nullable=False, server_default='0') # 実走行距離
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

# --- ConsumableLog, MaintenanceReminder, Attachment, GeneralNote, OdoResetLog, AchievementDefinition, UserAchievement モデルは変更なし ---
# (ただし、OdoResetLog はレーサー車両では使用されなくなる点に注意)

class ConsumableLog(db.Model):
    __tablename__ = 'consumable_logs'
    id = db.Column(db.Integer, primary_key=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='CASCADE'), nullable=False)
    type = db.Column(db.String(20), nullable=False) # 例: 'oil', 'tire_front', 'tire_rear'
    change_date = db.Column(db.Date, nullable=False)
    brand_name = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    odometer_reading_at_change = db.Column(db.Integer, nullable=True) # 変更時のODOメーター値

    def __repr__(self):
        return f'<ConsumableLog id={self.id} type={self.type}>'


class MaintenanceReminder(db.Model):
    __tablename__ = 'maintenance_reminders'
    id = db.Column(db.Integer, primary_key=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='CASCADE'), nullable=False)
    task_description = db.Column(db.String(200), nullable=False)
    interval_km = db.Column(db.Integer, nullable=True)      # kmごと
    interval_months = db.Column(db.Integer, nullable=True)  # ヶ月ごと
    last_done_date = db.Column(db.Date, nullable=True)      # 最後に実施した日付
    last_done_km = db.Column(db.Integer, nullable=True)     # 最後に実施した時のODOメーター値

    def __repr__(self):
        return f'<MaintenanceReminder id={self.id} task={self.task_description}>'

class Attachment(db.Model):
    __tablename__ = 'attachments'
    id = db.Column(db.Integer, primary_key=True)
    maintenance_entry_id = db.Column(db.Integer, db.ForeignKey('maintenance_entries.id', ondelete='CASCADE'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    filepath = db.Column(db.String(512), nullable=False, unique=True) # アップロードされたファイルの実際のパス
    upload_date = db.Column(db.DateTime, nullable=False)

    def __repr__(self):
        return f'<Attachment id={self.id} filename={self.filename}>'

class GeneralNote(db.Model):
    __tablename__ = 'general_notes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='SET NULL'), nullable=True) # SET NULLに変更
    note_date = db.Column(db.Date, nullable=False)
    title = db.Column(db.String(150), nullable=True)
    content = db.Column(db.Text, nullable=True) # 以前nullable=Falseだったが、タスクリストの場合contentが空でも良いように変更
    category = db.Column(db.String(20), nullable=False, default='note', server_default='note', index=True) # 'note' or 'task'
    todos = db.Column(JSONB, nullable=True) # JSONB型でTODOリストを保存 [{'text': 'タスク1', 'checked': False}, ...]
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())

    def __repr__(self):
        return f'<GeneralNote id={self.id} user_id={self.user_id} title="{self.title[:20]}">'


class OdoResetLog(db.Model):
    __tablename__ = 'odo_reset_logs'
    id = db.Column(db.Integer, primary_key=True)
    motorcycle_id = db.Column(db.Integer, db.ForeignKey('motorcycles.id', ondelete='CASCADE'), nullable=False)
    reset_date = db.Column(db.Date, nullable=False, index=True) # リセット操作を行った日付
    display_odo_before_reset = db.Column(db.Integer, nullable=False) # リセット直前のメーター表示値
    display_odo_after_reset = db.Column(db.Integer, nullable=False)  # リセット直後のメーター表示値 (通常は0)
    offset_increment = db.Column(db.Integer, nullable=False) # このリセットによるオフセットの増分 (before - after)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    def __repr__(self):
        return f'<OdoResetLog id={self.id} mc_id={self.motorcycle_id} date={self.reset_date} offset_inc={self.offset_increment}>'


class AchievementDefinition(db.Model):
    """実績の種類を定義するモデル"""
    __tablename__ = 'achievement_definitions'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), unique=True, nullable=False, index=True) # 実績の一意なコード (例: "FIRST_VEHICLE")
    name = db.Column(db.String(150), nullable=False) # 実績名 (例: "初めての車両登録")
    description = db.Column(db.Text, nullable=False) # 実績の説明
    icon_class = db.Column(db.String(100), nullable=True) # FontAwesomeなどのアイコンクラス
    category_code = db.Column(db.String(50), nullable=False, index=True) # カテゴリコード (例: "vehicle", "fuel", "maintenance")
    category_name = db.Column(db.String(100), nullable=False) # カテゴリ名 (例: "車両関連", "給油記録")
    share_text_template = db.Column(db.Text, nullable=True) # Misskey共有時のテンプレート (例: "{userName}さんが「{achievementName}」を解除しました！ #もとぷっぷー")
    trigger_event_type = db.Column(db.String(100), nullable=True, index=True) # どのイベントでこの実績の評価をトリガーするか (例: "add_vehicle", "add_fuel_log")
    criteria = db.Column(JSONB, nullable=True) # 実績の具体的な条件値 (例: {"type": "count", "target_model": "FuelEntry", "value": 10} -> 給油記録10回)
    user_achievements = db.relationship('UserAchievement', backref='definition', lazy='dynamic')

    def __repr__(self):
        return f'<AchievementDefinition code={self.code} name="{self.name}">'

class UserAchievement(db.Model):
    """ユーザーが解除した実績を記録するモデル"""
    __tablename__ = 'user_achievements'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    achievement_code = db.Column(db.String(100), db.ForeignKey('achievement_definitions.code', ondelete='CASCADE'), nullable=False, index=True)
    unlocked_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow) # 解除日時 (UTC)

    __table_args__ = (db.UniqueConstraint('user_id', 'achievement_code', name='uq_user_achievement'),)

    def __repr__(self):
        return f'<UserAchievement user_id={self.user_id} achievement_code={self.achievement_code} unlocked_at={self.unlocked_at}>'