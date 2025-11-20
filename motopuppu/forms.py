# motopuppu/forms.py
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired, FileAllowed
from wtforms import StringField, SelectField, DateField, DecimalField, IntegerField, TextAreaField, BooleanField, SubmitField, RadioField, FieldList, FormField, HiddenField, DateTimeField, PasswordField
from wtforms.validators import DataRequired, Optional, NumberRange, Length, ValidationError, InputRequired, EqualTo, URL
from datetime import date, datetime
from wtforms_sqlalchemy.fields import QuerySelectField

from .constants import (
    FUEL_TYPE_CHOICES,
    NOTE_CATEGORIES,
    MAX_TODO_ITEMS,
    JAPANESE_CIRCUITS
)
from .utils.lap_time_utils import is_valid_lap_time_format


class FuelForm(FlaskForm):
    motorcycle_id = SelectField(
        '車両',
        validators=[DataRequired(message='車両を選択してください。')],
        coerce=int
    )
    entry_date = DateField(
        '給油日',
        validators=[DataRequired(message='給油日は必須です。')],
        format='%Y-%m-%d'
    )
    input_mode = BooleanField(
        'トリップメーターで入力する',
        default=False
    )
    odometer_reading = IntegerField(
        'ODOメーター値 (km)',
        validators=[
            Optional(),
            NumberRange(min=0, message='ODOメーター値は0以上で入力してください。')
        ],
        render_kw={"placeholder": "例: 12345"}
    )
    trip_distance = IntegerField(
        'トリップメーター (km)',
        validators=[
            Optional(),
            NumberRange(min=0, message='トリップメーターは0以上で入力してください。')
        ],
        render_kw={"placeholder": "前回給油からの走行距離"}
    )
    fuel_volume = DecimalField(
        '給油量 (L)',
        places=2,
        validators=[
            DataRequired(message='給油量は必須です。'),
            NumberRange(min=0.01, message='給油量は0より大きい数値を入力してください。')
        ],
        render_kw={"step": "0.01", "placeholder": "例: 5.50"}
    )
    price_per_liter = IntegerField(
        'リッター単価 (円/L)',
        validators=[
            Optional(),
            NumberRange(min=0, message='リッター単価は0以上で入力してください。')
        ],
        render_kw={"placeholder": "例: 170"}
    )
    total_cost = IntegerField(
        '合計金額 (円)',
        validators=[
            Optional(),
            NumberRange(min=0, message='合計金額は0以上で入力してください。')
        ],
        render_kw={"placeholder": "例: 1000"}
    )
    station_name = StringField(
        '給油スタンド名',
        validators=[Optional(), Length(max=100, message='給油スタンド名は100文字以内で入力してください。')],
        render_kw={"list": "station-brands-list", "placeholder": "例: ENEOS ○○SS"}
    )
    fuel_type = SelectField(
        '油種',
        validators=[Optional()]
    )
    is_full_tank = BooleanField(
        '満タン給油 (燃費計算に利用)',
        default=True
    )
    exclude_from_average = BooleanField(
        'この記録を平均燃費計算から除外する',
        default=False
    )
    notes = TextAreaField(
        'メモ',
        validators=[Optional(), Length(max=500, message='メモは500文字以内で入力してください。')],
        render_kw={"rows": 3, "placeholder": "給油時の状況や特記事項など"}
    )
    submit = SubmitField('保存する')

    def __init__(self, *args, **kwargs):
        super(FuelForm, self).__init__(*args, **kwargs)
        
        self.fuel_type.choices = list(FUEL_TYPE_CHOICES)

        entry_obj = kwargs.get('obj')
        if entry_obj and entry_obj.fuel_type:
            existing_fuel_type = entry_obj.fuel_type
            choice_values = [choice[0] for choice in self.fuel_type.choices]
            if existing_fuel_type not in choice_values:
                self.fuel_type.choices.insert(1, (existing_fuel_type, existing_fuel_type))


class MaintenanceForm(FlaskForm):
    motorcycle_id = SelectField(
        '車両',
        validators=[DataRequired(message='車両を選択してください。')],
        coerce=int
    )
    maintenance_date = DateField(
        '整備日',
        validators=[DataRequired(message='整備日は必須です。')],
        format='%Y-%m-%d'
    )
    input_mode = BooleanField(
        'トリップメーターで入力する',
        default=False
    )
    odometer_reading_at_maintenance = IntegerField(
        '整備時のODOメーター値 (km)',
        validators=[
            Optional(),
            NumberRange(min=0, message='ODOメーター値は0以上で入力してください。')
        ],
        render_kw={"placeholder": "例: 20000"}
    )
    trip_distance = IntegerField(
        '前回整備からの走行距離 (km)',
        validators=[
            Optional(),
            NumberRange(min=0, message='走行距離は0以上で入力してください。')
        ],
        render_kw={"placeholder": "前回整備からの走行距離"}
    )
    description = TextAreaField(
        '整備内容',
        validators=[
            DataRequired(message='整備内容は必須です。'),
            Length(max=500, message='整備内容は500文字以内で入力してください。')
        ],
        render_kw={"rows": 3, "placeholder": "例: エンジンオイル、オイルフィルター交換"}
    )
    location = StringField(
        '整備場所',
        validators=[Optional(), Length(max=100, message='整備場所は100文字以内で入力してください。')],
        render_kw={"placeholder": "例: 自宅、〇〇バイクショップ"}
    )
    category = StringField(
        'カテゴリ',
        validators=[Optional(), Length(max=100, message='カテゴリは100文字以内で入力してください。')],
        render_kw={"list": "category_options", "placeholder": "例: オイル交換"}
    )
    parts_cost = IntegerField(
        '部品代 (円)',
        validators=[
            Optional(),
            NumberRange(min=0, message='部品代は0以上の数値を入力してください。')
        ],
        render_kw={"placeholder": "例: 3000"}
    )
    labor_cost = IntegerField(
        '工賃 (円)',
        validators=[
            Optional(),
            NumberRange(min=0, message='工賃は0以上の数値を入力してください。')
        ],
        render_kw={"placeholder": "例: 1500"}
    )
    notes = TextAreaField(
        'メモ',
        validators=[Optional(), Length(max=1000, message='メモは1000文字以内で入力してください。')],
        render_kw={"rows": 4, "placeholder": "使用した部品の型番、作業の詳細など"}
    )
    submit = SubmitField('保存する')


class VehicleForm(FlaskForm):
    maker = StringField(
        'メーカー名',
        validators=[Optional(), Length(max=20, message='メーカー名は20文字以内で入力してください。')],
        render_kw={"placeholder": "例: ホンダ"}
    )
    name = StringField(
        '車両名',
        validators=[
            DataRequired(message='車両名は必須です。'),
            Length(max=20, message='車両名は20文字以内で入力してください。')
        ],
        render_kw={"placeholder": "例: CBR250RR"}
    )
    year = IntegerField(
        '年式',
        validators=[
            Optional(),
            NumberRange(min=1900, max=datetime.now().year + 1, message=f'年式は1900年から{datetime.now().year + 1}の間で入力してください。')
        ],
        render_kw={"placeholder": "例: 2023"}
    )
    initial_odometer = IntegerField(
        '初期ODOメーター値 (km) (任意)',
        validators=[
            Optional(),
            NumberRange(min=0, message='初期ODOメーター値は0以上で入力してください。')
        ],
        render_kw={"placeholder": "中古購入時のODOメーター値など"}
    )
    is_racer = BooleanField(
        'レーサー車両として登録する (給油記録・ODOメーター管理の対象外となります)',
        default=False
    )
    total_operating_hours = DecimalField(
        '現在の総稼働時間 (時間)',
        places=2,
        validators=[Optional(), NumberRange(min=0, message='総稼働時間は0以上で入力してください。')],
        render_kw={"placeholder": "例: 123.50"},
        default=0.00
    )
    
    show_in_garage = BooleanField(
        'ガレージに掲載する',
        default=True
    )
    image_url = StringField(
        '車両画像URL',
        validators=[
            Optional(),
            URL(message="有効なURL形式で入力してください。"),
            Length(max=2048, message="URLは2048文字以内で入力してください。")
        ]
    )
    custom_details = TextAreaField(
        'カスタム・メモ',
        validators=[Optional(), Length(max=2000)]
    )

    primary_ratio = DecimalField(
        '一次減速比',
        places=3,
        validators=[Optional(), NumberRange(min=0, message='一次減速比は0以上の数値を入力してください。')],
        render_kw={"placeholder": "例: 1.777"}
    )
    gear_ratio_1 = DecimalField('1速', places=3, validators=[Optional(), NumberRange(min=0)])
    gear_ratio_2 = DecimalField('2速', places=3, validators=[Optional(), NumberRange(min=0)])
    gear_ratio_3 = DecimalField('3速', places=3, validators=[Optional(), NumberRange(min=0)])
    gear_ratio_4 = DecimalField('4速', places=3, validators=[Optional(), NumberRange(min=0)])
    gear_ratio_5 = DecimalField('5速', places=3, validators=[Optional(), NumberRange(min=0)])
    gear_ratio_6 = DecimalField('6速', places=3, validators=[Optional(), NumberRange(min=0)])
    gear_ratio_7 = DecimalField('7速', places=3, validators=[Optional(), NumberRange(min=0)])

    submit = SubmitField('登録する')

    def validate_total_operating_hours(self, field):
        pass
    
    def validate_initial_odometer(self, field):
        pass


class OdoResetLogForm(FlaskForm):
    reset_date = DateField(
        'リセット日',
        validators=[DataRequired(message='リセット日は必須です。')],
        format='%Y-%m-%d'
    )
    display_odo_before_reset = IntegerField(
        'リセット直前のメーター表示値 (km)',
        validators=[
            DataRequired(message='リセット直前のメーター表示値は必須です。'),
            NumberRange(min=0, message='メーター表示値は0以上である必要があります。')
        ]
    )
    display_odo_after_reset = IntegerField(
        'リセット直後のメーター表示値 (km)',
        default=0,
        validators=[
            InputRequired(message='リセット直後のメーター表示値は必須です。'),
            NumberRange(min=0, message='メーター表示値は0以上である必要があります。')
        ]
    )
    submit_odo_reset = SubmitField('リセットを記録')

    def validate_display_odo_before_reset(self, field):
        if self.display_odo_after_reset.data is not None and field.data is not None:
            if field.data < self.display_odo_after_reset.data:
                raise ValidationError('リセット前の値はリセット後の値以上である必要があります。')

    def validate_reset_date(self, field):
        if field.data and field.data > date.today():
            raise ValidationError('リセット日には未来の日付を指定できません。')


class ReminderForm(FlaskForm):
    task_description = StringField(
        'リマインド内容 / カテゴリ',
        validators=[
            DataRequired(message='リマインド内容は必須です。'),
            Length(max=200, message='リマインド内容は200文字以内で入力してください。')
        ],
        render_kw={"placeholder": "例: エンジンオイル交換", "list": "maintenance-category-suggestions"}
    )
    maintenance_entry = QuerySelectField(
        '最終実施記録 (整備ログから選択)',
        query_factory=None,
        allow_blank=True,
        blank_text='--- 手動で入力する / 連携しない ---',
        get_label='maintenance_summary_for_select',
        validators=[Optional()]
    )
    interval_km = IntegerField(
        '距離サイクル (kmごと)',
        validators=[
            Optional(),
            NumberRange(min=1, message='距離サイクルは0より大きい値を入力してください。')
        ],
        render_kw={"placeholder": "例: 3000"}
    )
    interval_months = IntegerField(
        '期間サイクル (ヶ月ごと)',
        validators=[
            Optional(),
            NumberRange(min=1, message='期間サイクルは0より大きい値を入力してください。')
        ],
        render_kw={"placeholder": "例: 6"}
    )
    last_done_date = DateField(
        '最終実施日',
        validators=[Optional()],
        format='%Y-%m-%d'
    )
    
    last_done_odo = IntegerField(
        '最終実施時のメーターODO値 (km)',
        validators=[
            Optional(),
            NumberRange(min=0, message='最終実施時のODO値は0以上の値を入力してください。')
        ],
        render_kw={"placeholder": "例: 15000"}
    )
    
    auto_update_from_category = BooleanField(
        '整備記録のカテゴリ名が一致した場合、このリマインダーを自動的に連携・更新する',
        default=True
    )

    submit = SubmitField('保存する')

    def validate(self, extra_validators=None):
        initial_validation = super(ReminderForm, self).validate(extra_validators)
        if not initial_validation:
            return False
        if not self.interval_km.data and not self.interval_months.data:
            self.interval_km.errors.append('距離または期間のどちらかのサイクルは設定してください。')
            return False
        return True


class TodoItemForm(FlaskForm):
    text = StringField(
        '内容',
        validators=[
            DataRequired(message='TODOアイテムの内容は必須です。'),
            Length(max=100, message='TODOアイテムの内容は100文字以内で入力してください。')
        ],
        render_kw={'placeholder': 'タスク内容 (必須)', 'class': 'form-control todo-item-text'}
    )
    checked = BooleanField(
        '完了',
        default=False,
        render_kw={'class': 'form-check-input mt-0 todo-item-check'}
    )

class NoteForm(FlaskForm):
    motorcycle_id = SelectField(
        '関連車両 (任意)',
        coerce=int,
        validators=[Optional()],
        default=0
    )
    note_date = DateField(
        '日付',
        validators=[DataRequired(message='日付は必須です。')],
        format='%Y-%m-%d',
        default=date.today
    )
    category = RadioField(
        'カテゴリー',
        choices=NOTE_CATEGORIES,
        validators=[DataRequired(message='カテゴリーを選択してください。')],
        default='note'
    )
    title = StringField(
        'タイトル (任意)',
        validators=[Optional(), Length(max=150, message='タイトルは150文字以内で入力してください。')],
        render_kw={"placeholder": "例: 次回ツーリング計画"}
    )
    content = TextAreaField(
        'ノート内容',
        validators=[Optional(), Length(max=2000, message='ノート内容は2000文字以内で入力してください。')],
        render_kw={"rows": 8, "placeholder": "自由記述のメモ内容..."}
    )
    todos = FieldList(
        FormField(TodoItemForm),
        min_entries=0,
        max_entries=MAX_TODO_ITEMS
    )
    submit = SubmitField('保存する')

    def validate_content(self, field):
        if self.category.data == 'note' and not field.data:
            raise ValidationError('ノートカテゴリの場合、ノート内容は必須です。')

    def validate_todos(self, field):
        if self.category.data == 'task':
            if not field.entries:
                raise ValidationError('タスクカテゴリの場合、TODOアイテムを1つ以上入力してください。')


class ProfileForm(FlaskForm):
    """プロフィール編集用フォーム"""
    display_name = StringField('表示名',
                                validators=[DataRequired(message="表示名を入力してください。"),
                                            Length(min=1, max=20, message="表示名は20文字以内で入力してください。")],
                                render_kw={"placeholder": "例: もとぷー太郎"})
    
    nyanpuppu_simple_mode = BooleanField(
        'にゃんぷっぷーから知能を取り上げる',
        description='ONにすると、ダッシュボードのにゃんぷっぷーが知的なアドバイスをしなくなり、「ぷにゃあん」などとしか話さなくなります。'
    )

    submit_profile = SubmitField('更新する')


class DeleteAccountForm(FlaskForm):
    """アカウント削除確認フォーム"""
    confirm_text = StringField(
        '確認のため「削除します」と入力してください。',
        validators=[DataRequired(message="このフィールドは必須です。")]
    )
    submit_delete = SubmitField('退会して全てのデータを削除する')

    def validate_confirm_text(self, field):
        if field.data != "削除します":
            raise ValidationError("入力された文字列が一致しません。「削除します」と正しく入力してください。")


# --- チーム機能関連 ---

class TeamForm(FlaskForm):
    """チーム作成・編集用のフォーム"""
    name = StringField(
        'チーム名',
        validators=[
            DataRequired(message='チーム名は必須です。'),
            Length(max=50, message='チーム名は50文字以内で入力してください。')
        ],
        render_kw={"placeholder": "例: Project D"}
    )
    submit = SubmitField('チームを作成')


# --- 活動ログ機能 (ここから) ---

class TargetLapTimeForm(FlaskForm):
    """サーキット目標タイム設定用のフォーム"""
    target_time = StringField(
        '目標タイム',
        validators=[DataRequired(message="目標タイムを入力してください。")],
        render_kw={"placeholder": "例: 1:58.123"}
    )
    submit = SubmitField('保存する')

    def validate_target_time(self, field):
        if field.data and not is_valid_lap_time_format(field.data):
            raise ValidationError('タイムの形式が正しくありません。(例: 1:23.456 または 83.456)')


class LapTimeImportForm(FlaskForm):
    """ラップタイムCSVインポート用のフォーム"""
    device_type = SelectField(
        'ラップタイマー機種',
        choices=[
            ('simple_csv', '手入力 / シンプルCSV'),
            ('ziix', 'ZiiX'),
            ('mylaps', 'MYLAPS(Speedhive)'),
            ('drogger', 'Drogger')
        ],
        validators=[DataRequired(message="機種を選択してください。")]
    )
    csv_file = FileField(
        'CSVファイル',
        validators=[
            FileRequired(message="ファイルを選択してください。"),
            FileAllowed(['csv', 'txt'], 'CSVまたはTXTファイルのみアップロードできます')
        ]
    )
    remove_outliers = BooleanField(
        '異常に遅いラップを除外する (ピットイン等)',
        default=True
    )
    outlier_threshold = DecimalField(
        '異常値とみなす閾値 (中央値の倍率)',
        places=1,
        validators=[
            Optional(),
            NumberRange(min=1.1, max=10.0, message='閾値は1.1から10.0の間で設定してください。')
        ],
        default=2.0,
        render_kw={"step": "0.1", "placeholder": "例: 2.0"}
    )
    submit_import = SubmitField('インポート実行')


class SettingSheetForm(FlaskForm):
    """セッティングシート用のフォーム"""
    sheet_name = StringField(
        'セッティングシート名',
        validators=[DataRequired(message='シート名は必須です。'), Length(max=100)],
        render_kw={"placeholder": "例: FSWドライ基本セット"}
    )
    notes = TextAreaField(
        'メモ',
        validators=[Optional(), Length(max=1000)],
        render_kw={"rows": 4, "placeholder": "このセッティングの狙いや特徴など"}
    )
    submit = SubmitField('保存する')

class ActivityLogForm(FlaskForm):
    """活動ログ用のフォーム"""
    motorcycle_id = SelectField(
        '車両',
        coerce=int,
        validators=[DataRequired(message='車両を選択してください。')]
    )
    activity_date = DateField(
        '活動日',
        validators=[DataRequired(message='活動日は必須です。')],
        format='%Y-%m-%d',
        default=date.today
    )
    activity_title = StringField(
        '活動名',
        validators=[DataRequired(message='活動名は必須です。'), Length(max=200)],
        render_kw={"placeholder": "例: 7月の練習走行、夏休みツーリング"}
    )
    location_type = RadioField(
        '場所の種別',
        choices=[('circuit', 'サーキット'), ('custom', 'その他（自由入力）')],
        validators=[DataRequired(message='場所の種別を選択してください。')],
        default='circuit'
    )
    circuit_name = SelectField(
        'サーキット名',
        choices=[('', '--- サーキットを選択 ---')] + [(c, c) for c in JAPANESE_CIRCUITS],
        validators=[Optional()]
    )
    custom_location = StringField(
        '場所名（自由入力）',
        validators=[Optional(), Length(max=200)],
        render_kw={"placeholder": "例: 箱根、ビーナスライン"}
    )
    weather = StringField('天候', validators=[Optional(), Length(max=50)])
    temperature = DecimalField('気温 (℃)', places=1, validators=[Optional(), NumberRange(min=-50, max=60)])
    notes = TextAreaField(
        '1日の活動メモ',
        validators=[Optional(), Length(max=1000)],
        render_kw={"rows": 4}
    )
    submit = SubmitField('保存する')

    def validate(self, extra_validators=None):
        """場所の種別に応じて必須項目をチェックするカスタムバリデーション"""
        if not super(ActivityLogForm, self).validate(extra_validators):
            return False
        
        if self.location_type.data == 'circuit':
            if not self.circuit_name.data:
                self.circuit_name.errors.append('サーキットを選択してください。')
                return False
        elif self.location_type.data == 'custom':
            if not self.custom_location.data:
                self.custom_location.errors.append('場所名を入力してください。')
                return False
        
        return True

class SessionLogForm(FlaskForm):
    """セッションログ用のフォーム"""
    session_name = StringField(
        'セッション名',
        validators=[DataRequired(message='セッション名は必須です。'), Length(max=100)],
        default='Session 1'
    )
    setting_sheet_id = SelectField(
        '使用セッティング',
        coerce=int,
        validators=[Optional()]
    )
    rider_feel = TextAreaField(
        '走行メモ・フィーリング',
        validators=[Optional(), Length(max=2000)],
        render_kw={"rows": 5, "placeholder": "このセッションでのマシンの挙動や改善点など"}
    )
    session_duration_hours = DecimalField(
        '稼働時間 (h)',
        places=2,
        validators=[Optional(), NumberRange(min=0, message='稼働時間は0以上の数値を入力してください。')],
        render_kw={"placeholder": "例: 1.5"}
    )
    session_distance = IntegerField(
        '走行距離 (km)',
        validators=[Optional(), NumberRange(min=0, message='走行距離は0以上の数値を入力してください。')],
        render_kw={"placeholder": "例: 150"}
    )
    lap_times_json = HiddenField('Lap Times JSON', validators=[Optional()])

    include_in_leaderboard = BooleanField(
        'このセッションの記録をリーダーボードに掲載することを許可する',
        default=True
    )
    
    submit = SubmitField('セッションを記録')

class TouringLogForm(FlaskForm):
    """ツーリングログ用のフォーム"""
    title = StringField('ツーリング名', validators=[DataRequired(), Length(max=200)])
    touring_date = DateField('日付', validators=[DataRequired()], format='%Y-%m-%d', default=date.today)
    memo = TextAreaField('メモ', validators=[Optional(), Length(max=2000)], render_kw={"rows": 4})
    
    # フロントエンドからJSONでデータを受け取るための隠しフィールド
    spots_data = HiddenField('Spots Data JSON', validators=[Optional()])
    scrapbook_note_ids = HiddenField('Scrapbook Note IDs JSON', validators=[Optional()])

    submit = SubmitField('保存する')

# --- イベント機能 (ここから) ---

class EventForm(FlaskForm):
    """イベント作成・編集用のフォーム"""
    motorcycle_id = SelectField(
        '関連車両 (任意)',
        coerce=int,
        validators=[Optional()]
    )
    title = StringField(
        'イベント名',
        validators=[
            DataRequired(message='イベント名は必須です。'),
            Length(max=200, message='イベント名は200文字以内で入力してください。')
        ],
        render_kw={"placeholder": "例: 夏のビーナスラインツーリング"}
    )
    description = TextAreaField(
        'イベント詳細',
        validators=[Optional(), Length(max=2000)],
        render_kw={"rows": 5, "placeholder": "集合場所、時間、ルート、持ち物などの詳細を記入します。"}
    )
    location = StringField(
        '開催場所 / エリア',
        validators=[Optional(), Length(max=200)],
        render_kw={"placeholder": "例: 八ヶ岳PA (中央道下り)"}
    )
    start_datetime = DateTimeField(
        '開始日時',
        validators=[DataRequired(message='開始日時は必須です。')],
        format='%Y-%m-%dT%H:%M'
    )
    end_datetime = DateTimeField(
        '終了日時 (任意)',
        validators=[Optional()],
        format='%Y-%m-%dT%H:%M'
    )

    is_public = BooleanField(
        'イベント一覧に公開する',
        default=True
    )
    
    submit = SubmitField('イベントを保存')
    
    def validate_end_datetime(self, field):
        if field.data and self.start_datetime.data and field.data < self.start_datetime.data:
            raise ValidationError('終了日時は開始日時より後に設定してください。')

class ParticipantForm(FlaskForm):
    """公開ページでの出欠登録用フォーム"""
    name = StringField(
        'お名前',
        validators=[
            DataRequired(message='お名前は必須です。'),
            Length(max=20, message='お名前は20文字以内で入力してください。')
        ]
    )
    # ▼▼▼【ここから追記】▼▼▼
    vehicle_name = StringField(
        '車種 (任意)',
        validators=[
            Optional(),
            Length(max=50, message='車種は50文字以内で入力してください。')
        ],
        render_kw={"placeholder": "例: YZF-R1 / 徒歩"}
    )
    # ▲▲▲【追記ここまで】▲▲▲
    comment = StringField(
        '一言コメント (任意)',
        validators=[
            Optional(),
            Length(max=50, message='コメントは50文字以内で入力してください。')
        ],
        render_kw={"placeholder": "例: テント持参します / 途中参加です (50文字以内)"}
    )
    passcode = PasswordField(
        'パスコード (4〜20文字)',
        validators=[
            DataRequired(message='パスコードは必須です。'),
            Length(min=4, max=20, message='パスコードは4文字以上20文字以内で設定してください。')
        ]
    )
    status = RadioField(
        '出欠',
        choices=[
            ('attending', '参加'),
            ('tentative', '保留'),
            ('not_attending', '不参加'),
            ('delete', '参加を取り消す')
        ],
        validators=[DataRequired(message='出欠を選択してください。')],
        default='attending'
    )
    submit = SubmitField('出欠を登録・更新する')


class GarageSettingsForm(FlaskForm):
    """ガレージ統合設定画面用のフォーム"""
    is_garage_public = BooleanField(
        'ガレージを公開する',
        description='チェックすると、あなたのガレージページが作成され、誰でも閲覧できるようになります。'
    )
    garage_hero_vehicle_id = SelectField(
        '主役の車両 (Hero Vehicle)',
        coerce=int,
        validators=[Optional()],
        description='ガレージカードで一番大きく表示される車両を選択します。「デフォルト車両に準ずる」を選ぶと、車両管理画面のデフォルト設定が使われます。'
    )
    garage_theme = SelectField(
        'デザインテーマ',
        choices=[
            ('default', 'デフォルト'),
            ('dark', 'ダークモード'),
            ('racing', 'レーシング'),
            ('retro', 'レトロ'),
            ('minimal', 'ミニマル'),
            ('classic', 'クラシック'),
            ('cyber', 'サイバー'),
            ('adventure', 'アドベンチャー')
        ],
        validators=[DataRequired()],
        description='ガレージカードの見た目を変更します。'
    )
    show_hero_stats = BooleanField(
        '統計情報を表示する',
        default=True,
        description='走行距離や平均燃費などの統計データを表示します。'
    )
    show_custom_details = BooleanField(
        'カスタム・メモを表示する',
        default=True,
        description='ヒーロー車両に登録されたカスタム内容やメモを表示します。'
    )
    show_other_vehicles = BooleanField(
        '他の所有車両一覧を表示する',
        default=True,
        description='ヒーロー以外の車両リストを表示します。'
    )
    show_achievements = BooleanField(
        '実績を表示する',
        default=True,
        description='最近解除した実績のリストを表示します。'
    )
    show_circuit_info = BooleanField(
        'サーキット情報を表示する',
        default=True,
        description='サーキットでのベストラップや活動ログへのリンクなどを表示します。'
    )
    submit = SubmitField('設定を保存する')

class GarageVehicleDetailsForm(FlaskForm):
    """ガレージ設定ページで個別の車両詳細を編集するためのフォーム"""
    image_url = StringField(
        '車両画像URL',
        validators=[
            Optional(),
            URL(message="有効なURL形式で入力してください。"),
            Length(max=2048, message="URLは2048文字以内で入力してください。")
        ],
        render_kw={"placeholder": "https://... Misskeyの画像URLなど"}
    )
    custom_details = TextAreaField(
        'カスタム・メモ',
        validators=[Optional(), Length(max=2000)],
        render_kw={"rows": 5, "placeholder": "マフラー:ヨシムラ\nハンドル:ハリケーン\n..."}
    )
    submit_details = SubmitField('保存する')


class FuelCsvUploadForm(FlaskForm):
    """給油記録CSVインポート用のフォーム"""
    csv_file = FileField(
        'CSVファイル',
        validators=[
            FileRequired(message="ファイルを選択してください。"),
            FileAllowed(['csv'], 'CSVファイルのみアップロードできます')
        ]
    )
    submit_upload = SubmitField('アップロードしてインポート')


class MaintenanceCsvUploadForm(FlaskForm):
    """整備記録CSVインポート用のフォーム"""
    csv_file = FileField(
        'CSVファイル',
        validators=[
            FileRequired(message="ファイルを選択してください。"),
            FileAllowed(['csv'], 'CSVファイルのみアップロードできます')
        ]
    )
    submit_upload = SubmitField('アップロードしてインポート')


class MaintenanceSpecSheetForm(FlaskForm):
    """整備情報シート用のフォーム"""
    sheet_name = StringField(
        'シート名',
        validators=[
            DataRequired(message='シート名は必須です。'),
            Length(max=100, message='シート名は100文字以内で入力してください。')
        ],
        render_kw={"placeholder": "例: 標準スペック、サーキット用セット"}
    )
    # フロントエンドからJSON文字列を受け取るための隠しフィールド
    spec_data = HiddenField('Spec Data JSON', validators=[Optional()])
    submit = SubmitField('保存する')