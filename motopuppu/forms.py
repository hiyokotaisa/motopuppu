# motopuppu/forms.py
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired, FileAllowed
from wtforms import StringField, SelectField, DateField, DecimalField, IntegerField, TextAreaField, BooleanField, SubmitField, RadioField, FieldList, FormField, HiddenField, DateTimeField, PasswordField
from wtforms.validators import DataRequired, Optional, NumberRange, Length, ValidationError, InputRequired, EqualTo
from datetime import date, datetime
from wtforms_sqlalchemy.fields import QuerySelectField

# スタンド名の候補リスト (FuelForm用)
GAS_STATION_BRANDS = [
    'ENEOS', '出光興産/apollostation', 'コスモ石油', 'キグナス石油', 'JA-SS', 'SOLATO',
]

# --- ▼▼▼ 変更: 日本の二輪走行可能サーキットリストを更新 ▼▼▼ ---
JAPANESE_CIRCUITS = [
    # --- 北海道 / 東北 ---
    "十勝スピードウェイ",
    "スポーツランドSUGO",
    "エビスサーキット東コース",
    "エビスサーキット西コース",
    
    # --- 関東 ---
    "ツインリンクもてぎ ロードコース",
    "筑波サーキット TC2000",
    "筑波サーキット TC1000",
    "袖ヶ浦フォレストレースウェイ",
    "桶川スポーツランド ロングコース",
    "桶川スポーツランド ミドルコース",
    "桶川スポーツランド ショートコース",
    "ヒーローしのいサーキット",
    "日光サーキット",
    "茂原ツインサーキット ショートコース(西)",
    "茂原ツインサーキット ロングコース(東)",
    
    # --- 中部 / 東海 ---
    "富士スピードウェイ 本コース",
    "富士スピードウェイ ショートコース",
    "富士スピードウェイ カートコース",
    "白糸スピードランド",
    "スパ西浦モーターパーク",
    "モーターランド三河",
    "YZサーキット東コース",
    "鈴鹿ツインサーキット",
    
    # --- 近畿 ---
    "鈴鹿サーキット フルコース",
    "鈴鹿サーキット 南コース",
    "近畿スポーツランド",
    "レインボースポーツ カートコース",
    "セントラルサーキット",
    "岡山国際サーキット",
    
    # --- 中国 / 四国 ---
    "TSタカタサーキット",
    "瀬戸内海サーキット",
    
    # --- 九州 / 沖縄 ---
    "オートポリス",
    "HSR九州",
]
# --- ▲▲▲ 変更ここまで ▲▲▲ ---


# 油種の選択肢を定数として定義
FUEL_TYPE_CHOICES = [
    ('', '--- 選択してください ---'), # 未選択時の表示
    ('レギュラー', 'レギュラー'),
    ('ハイオク', 'ハイオク'),
    ('軽油', '軽油'),
    ('混合', '混合')
]

# カテゴリの候補リスト (MaintenanceForm用)
MAINTENANCE_CATEGORIES = [
    'エンジンオイル交換', 'タイヤ交換', 'ブレーキパッド交換', 'チェーンメンテナンス',
    '定期点検', '洗車', 'その他',
]

# ノート/タスクのカテゴリ (NoteForm用)
NOTE_CATEGORIES = [
    ('note', 'ノート'),
    ('task', 'タスク (TODOリスト)')
]
MAX_TODO_ITEMS = 50


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
        choices=FUEL_TYPE_CHOICES, # choicesは__init__でコピーして使う
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
        
        # choicesが他のインスタンスに影響を与えないようにコピーを使用する
        self.fuel_type.choices = list(FUEL_TYPE_CHOICES)

        # フォームにDBオブジェクトが渡された場合 (編集時) の処理
        entry_obj = kwargs.get('obj')
        if entry_obj and entry_obj.fuel_type:
            existing_fuel_type = entry_obj.fuel_type
            # 現在の選択肢の値のリストを取得
            choice_values = [choice[0] for choice in self.fuel_type.choices]
            # DBに保存されている値が現在の選択肢にない場合
            if existing_fuel_type not in choice_values:
                # 既存の選択肢の先頭から2番目（'--- 選択してください ---'の後）に、
                # DBの値を(値, ラベル)のタプル形式で追加する
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
    # --- ▼▼▼ ここから変更 ▼▼▼ ---
    input_mode = BooleanField(
        'トリップメーターで入力する',
        default=False
    )
    odometer_reading_at_maintenance = IntegerField(
        '整備時のODOメーター値 (km)',
        validators=[
            Optional(), # DataRequiredから変更
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
    # --- ▲▲▲ ここまで変更 ▲▲▲ ---
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
        places=2, # 小数点以下2桁
        validators=[Optional(), NumberRange(min=0, message='総稼働時間は0以上で入力してください。')],
        render_kw={"placeholder": "例: 123.50"},
        default=0.00 # フォーム表示時のデフォルト値
    )
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
    
    # --- ▼▼▼ ここから変更 ▼▼▼ ---
    # last_done_km を last_done_odo に変更し、ラベルも修正
    last_done_odo = IntegerField(
        '最終実施時のメーターODO値 (km)',
        validators=[
            Optional(),
            NumberRange(min=0, message='最終実施時のODO値は0以上の値を入力してください。')
        ],
        render_kw={"placeholder": "例: 15000"}
    )
    # --- ▲▲▲ ここまで変更 ▲▲▲ ---
    
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

# --- ▼▼▼ ここから追加 ▼▼▼ ---
class ProfileForm(FlaskForm):
    """プロフィール編集用フォーム"""
    display_name = StringField('表示名',
                                 validators=[DataRequired(message="表示名を入力してください。"),
                                             Length(min=1, max=20, message="表示名は20文字以内で入力してください。")],
                                 render_kw={"placeholder": "例: もとぷー太郎"})
    submit_profile = SubmitField('表示名を更新')
# --- ▲▲▲ ここまで追加 ▲▲▲ ---

class DeleteAccountForm(FlaskForm):
    """アカウント削除確認フォーム"""
    # --- ▼▼▼ 変更: プレースホルダーと検証ルールをテンプレートに合わせる ▼▼▼ ---
    confirm_text = StringField(
        '確認のため「削除します」と入力してください。',
        validators=[DataRequired(message="このフィールドは必須です。")]
    )
    submit_delete = SubmitField('退会して全てのデータを削除する')

    def validate_confirm_text(self, field):
        if field.data != "削除します":
            raise ValidationError("入力された文字列が一致しません。「削除します」と正しく入力してください。")
    # --- ▲▲▲ ここまで変更 ▲▲▲ ---


# --- ▼▼▼ 活動ログ機能 (ここから) ▼▼▼ ---

class LapTimeImportForm(FlaskForm):
    """ラップタイムCSVインポート用のフォーム"""
    device_type = SelectField(
        'ラップタイマー機種',
        # --- ▼▼▼ 変更 ▼▼▼ ---
        choices=[
            ('simple_csv', '手入力 / シンプルCSV'),
            ('ziix', 'ZiiX'),
            ('mylaps', 'MYLAPS(Speedhive)')
        ],
        # --- ▲▲▲ 変更ここまで ▲▲▲ ---
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
    submit_import = SubmitField('インポート実行')


class SettingSheetForm(FlaskForm):
    """セッティングシート用のフォーム"""
    sheet_name = StringField(
        'セッティングシート名',
        validators=[DataRequired(message='シート名は必須です。'), Length(max=100)],
        render_kw={"placeholder": "例: FSWドライ基本セット"}
    )
    # details_jsonフィールドを削除
    notes = TextAreaField(
        'メモ',
        validators=[Optional(), Length(max=1000)],
        render_kw={"rows": 4, "placeholder": "このセッティングの狙いや特徴など"}
    )
    submit = SubmitField('保存する')

class ActivityLogForm(FlaskForm):
    """活動ログ用のフォーム"""
    activity_date = DateField(
        '活動日',
        validators=[DataRequired(message='活動日は必須です。')],
        format='%Y-%m-%d',
        default=date.today
    )
    # --- ▼▼▼ 変更: フィールドを新しい構造に刷新 ▼▼▼ ---
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
    # --- ▲▲▲ 変更ここまで ▲▲▲ ---
    
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
        # 親クラスのバリデーションを先に実行
        if not super(ActivityLogForm, self).validate(extra_validators):
            return False
        
        # location_type の値に基づいてチェック
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

    # --- ▼▼▼ 変更: リーダーボード設定を追加 ▼▼▼ ---
    include_in_leaderboard = BooleanField(
        'このセッションの記録をリーダーボードに掲載することを許可する',
        default=True
    )
    # --- ▲▲▲ 変更ここまで ▲▲▲ ---
    
    submit = SubmitField('セッションを記録')

# --- ▲▲▲ 活動ログ機能 (ここまで) ▲▲▲ ---


# --- ▼▼▼ イベント機能 (ここから) ▼▼▼ ---

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
    # --- ▼▼▼ ここから修正 ▼▼▼ ---
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
            ('not_attending', '不参加')
        ],
        validators=[DataRequired(message='出欠を選択してください。')],
        default='attending'
    )
    submit = SubmitField('出欠を登録・更新する')
    # --- ▲▲▲ 修正ここまで ▲▲▲ ---
    
# --- ▲▲▲ イベント機能 (ここまで) ▲▲▲ ---