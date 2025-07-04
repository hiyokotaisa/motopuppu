from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, DateField, DecimalField, IntegerField, TextAreaField, BooleanField, SubmitField, RadioField, FieldList, FormField
from wtforms.validators import DataRequired, Optional, NumberRange, Length, ValidationError, InputRequired
from datetime import date, datetime

# スタンド名の候補リスト (FuelForm用)
GAS_STATION_BRANDS = [
    'ENEOS', '出光興産/apollostation', 'コスモ石油', 'キグナス石油', 'JA-SS', 'SOLATO',
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
    # --- ▼▼▼ トグルスイッチへの変更 ▼▼▼ ---
    input_mode = BooleanField(
        'トリップメーターで入力する', # ラベルを分かりやすく変更
        default=False # デフォルトはOFF (ODOメーター入力)
    )
    odometer_reading = IntegerField(
        'ODOメーター値 (km)',
        validators=[
            Optional(), # バリデーションはビュー側で実施するため変更なし
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
    # --- ▲▲▲ トグルスイッチへの変更 ▲▲▲ ---
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
    fuel_type = StringField(
        '油種',
        validators=[Optional(), Length(max=50, message='油種は50文字以内で入力してください。')],
        render_kw={"list": "fuel_type_options", "placeholder": "例: レギュラー"}
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
    odometer_reading_at_maintenance = IntegerField(
        '整備時のODOメーター値 (km)',
        validators=[
            DataRequired(message='整備時のODOメーター値は必須です。'),
            NumberRange(min=0, message='ODOメーター値は0以上で入力してください。')
        ],
        render_kw={"placeholder": "例: 20000"}
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
        validators=[Optional(), Length(max=100, message='メーカー名は100文字以内で入力してください。')],
        render_kw={"placeholder": "例: ホンダ"}
    )
    name = StringField(
        '車両名',
        validators=[
            DataRequired(message='車両名は必須です。'),
            Length(max=100, message='車両名は100文字以内で入力してください。')
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
    # --- ▼▼▼ 変更点 ▼▼▼ ---
    initial_odometer = IntegerField(
        '初期ODOメーター値 (km) (任意)',
        validators=[
            Optional(),
            NumberRange(min=0, message='初期ODOメーター値は0以上で入力してください。')
        ],
        render_kw={"placeholder": "中古購入時のODOメーター値など"}
    )
    # --- ▲▲▲ 変更点 ▲▲▲ ---
    # --- ▼▼▼ フェーズ1変更点 ▼▼▼ ---
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
    # --- ▲▲▲ フェーズ1変更点 ▲▲▲ ---
    submit = SubmitField('登録する')

    # --- ▼▼▼ フェーズ1変更点 (バリデーション追加) ▼▼▼ ---
    def validate_total_operating_hours(self, field):
        """is_racer が True の場合のみ total_operating_hours を必須とするカスタムバリデーション（任意）"""
        # is_racer の値はこのフォームインスタンスからは直接参照しづらいため、
        # テンプレート側での表示制御と、ビュー側での値の処理で対応するのが一般的。
        # もしフォームレベルでバリデーションするなら、ビューで is_racer の状態を渡して条件分岐するなどの工夫が必要。
        # 今回は、Optional() とし、ビュー側で is_racer=True の場合に値がなければ0をセットする方針とします。
        # もし is_racer=True の場合に必須としたいなら、ビュー側でチェックするか、
        # フォームに is_racer の値を渡せるようにして、ここでチェックします。
        # 例:
        # if self.is_racer_input and self.is_racer_input.data and field.data is None:
        #     raise ValidationError('レーサー車両の場合、総稼働時間を入力してください。')
        pass # 今回は具体的なフォームレベルでの条件付き必須バリデーションは追加せず、ビューとテンプレートで制御
    # --- ▲▲▲ フェーズ1変更点 ▲▲▲ ---
    # --- ▼▼▼ 変更点 ▼▼▼ ---
    def validate_initial_odometer(self, field):
        """is_racer が True の場合は initial_odometer が入力されていても無視されることを考慮"""
        # このバリデーションはビュー側で行う方がシンプル。
        # フォーム送信時に is_racer がチェックされていたら、このフィールドの値をNoneにするなど。
        # ここでは何もしない。
        pass
    # --- ▲▲▲ 変更点 ▲▲▲ ---


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
            InputRequired(message='リセット直後のメーター表示値は必須です。'), # InputRequired に変更 (0も有効な値として許可)
            NumberRange(min=0, message='メーター表示値は0以上である必要があります。')
        ]
    )
    submit_odo_reset = SubmitField('リセットを記録') # ボタンのテキストを変更

    def validate_display_odo_before_reset(self, field):
        if self.display_odo_after_reset.data is not None and field.data is not None:
            if field.data < self.display_odo_after_reset.data:
                raise ValidationError('リセット前の値はリセット後の値以上である必要があります。')

    def validate_reset_date(self, field):
        if field.data and field.data > date.today():
            raise ValidationError('リセット日には未来の日付を指定できません。')


class ReminderForm(FlaskForm):
    task_description = StringField(
        'リマインド内容',
        validators=[
            DataRequired(message='リマインド内容は必須です。'),
            Length(max=200, message='リマインド内容は200文字以内で入力してください。')
        ],
        render_kw={"placeholder": "例: エンジンオイル交換"}
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
    last_done_km = IntegerField(
        '最終実施時の総走行距離 (km)',
        validators=[
            Optional(),
            NumberRange(min=0, message='最終実施距離は0以上の値を入力してください。')
        ],
        render_kw={"placeholder": "例: 15000"}
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

class DeleteAccountForm(FlaskForm):
    """アカウント削除確認フォーム"""
    confirm_text = StringField(
        '確認のため「削除します」と入力してください。',
        validators=[DataRequired(message="このフィールドは必須です。")]
    )
    submit = SubmitField('退会して全てのデータを削除する')

    def validate_confirm_text(self, field):
        if field.data != "削除します":
            raise ValidationError("入力された文字列が一致しません。「削除します」と正しく入力してください。")