# motopuppu/nyanpuppu.py
import random
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import current_app
from .models import db, Motorcycle, FuelEntry, MaintenanceEntry, ActivityLog, MaintenanceReminder

def get_advice(user, motorcycles):
    """
    ダッシュボードに表示する「にゃんぷっぷー」のアドバイスと画像を決定して返す。
    発言ロジックはこのファイルに集約する。
    """
    if not user:
        return None

    advice_pool = []
    today = datetime.now(ZoneInfo("Asia/Tokyo"))
    
    # =================================================================
    # カテゴリ1: 静的なTips (機能紹介・バイクTIPS)
    # =================================================================
    static_tips = [
        # --- 機能紹介 ---
        ("給油記録を「満タン」で登録すると、自動で燃費が計算されるにゃん。", "blobcat_ago.png"),
        ("整備記録にカテゴリを設定すると、リマインダーと連携できて便利にゃ。", "blobcat_thumbsup.png"),
        ("ダッシュボード右上のギアアイコンから、ウィジェットの配置を自由に変更できるにゃ。", "blobcat_doya.png"),
        ("活動ログ機能で、サーキット走行のセッティングやタイムを記録してみようにゃ。", "blobcat_rider.gif"),
        ("ノート機能は、TODOリストとしても使えるにゃ。忘れがちな作業をメモしておくといいにゃ。", "blobcat_rakugaki.webp"),
        ("ツーリングログ機能で、旅の思い出をスクラップできるにゃん！", "blobcat_binoculars.webp"),
        ("車両編集画面から、愛車の画像を登録できるにゃ。ガレージが華やかになるにゃん。", "rv_blobcat_camera2.webp"),
        ("リマインダー機能のスヌーズを使えば、通知を一時的におやすみさせられるにゃ。", "blobcat_nemunemu.png"),
        ("統計ウィジェットの期間フィルタ、使ってるかにゃ？過去の記録を振り返るのに便利にゃん。", "blobcat_pensive.png"),
        ("Misskey共有ボタンから、実績や活動記録を自慢できるにゃ！", "blobcat_yay.apng"),

        # --- バイクTIPS (メンテナンス) ---
        ("タイヤの空気圧はこまめにチェックするにゃ。安全運転の基本にゃん！", "blobcat_aseri.png"),
        ("チェーンの掃除と注油、忘れてないかにゃ？走りが見違えることもあるにゃん。", "blobcat_mukimuki.png"),
        ("雨の日のマンホールや白線は滑りやすいから気をつけるにゃ。するりと行かずに、そーっと通るにゃ。", "ablobcatcomfy_raincoat.apng"),
        ("ブレーキフルードは1〜2年で交換するのがおすすめにゃ。色が濃くなってきたら交換のサインにゃん。", "blobcat_aseri2.png"),
        ("ヘルメットの有効期限は3年って言われてるにゃ。大事な頭を守るものだから、たまには確認してにゃ。", "blobcat_oh.png"),
        ("バッテリーが弱ってないかにゃ？冬は特に上がりやすいから注意にゃ。", "blobcat_zehhutyou.webp"),
        ("チェーンのたるみ、大丈夫かにゃ？指二本分くらいが目安にゃん。", "blobcat_pity.webp"),
        ("ブレーキパッドの残量、溝を確認するにゃ。キーキー鳴ったら末期症状にゃん！", "blobcat_kowaii.png"),
        ("たまにはバイクを洗車してあげるにゃ。汚れの下にトラブルが隠れてることも…にゃんてね。", "blobcat_shower.png"),
        ("エンジンをかける前の日常点検、「ねん・お・しゃ・ち・え・ぶ・く・とう・ば・しめ」って知ってるかにゃ？", "blobcatthinking.png"),

        # --- バイクTIPS (ライディング) ---
        ("コーナーの先を見て走ると、スムーズに曲がれるようににゃるにゃん。", "blobcat_binoculars.webp"),
        ("急ブレーキは禁物にゃ。じわーっとかけて、タイヤをロックさせないようにするにゃ。", "blobcat_frustration.png"),
        ("すり抜けは危ないから、ほどほどににゃ。心と車間に余裕を持つにゃん。", "blobcat_policepeek.png"),
        ("服装は大事にゃ。「ちょっとそこまで」でも、肌の露出は避けるにゃ。", "blobcat_thumbsup.png"),
        ("向かい風が強い日は、少し前傾姿勢になると楽になるにゃ。風と友達になるにゃん。", "blobcat_running.gif"),
    ]
    advice_pool.extend(static_tips)

    # =================================================================
    # カテゴリ2: ユーモア・挨拶・応援
    # =================================================================
    humor_greetings = [
        ("今日も一日、ご安全ににゃ！", "ablobcat_wave.gif"),
        ("記録を続けるの、えらいにゃ！君のバイクライフがもっと豊かになるお手伝いをするにゃ。", "ablobcat_cheer.gif"),
        ("疲れたら無理せず休憩するにゃ。バイクは逃げないにゃん。", "blobcat_tea.png"),
        ("次のツーリングはどこに行くかニャ？計画を立てるのも楽しい時間にゃん。", "blobcatthinking.png"),
        ("にゃんぷっぷー！今日も元気に記録するにゃ！", "ablobcat_eieiou.gif"),
        ("ヤエー！(・∀・)v ってすると、ツーリング仲間が増えるかもしれにゃい！", "ablobcat_wave.gif"),
        ("また新しいパーツを買ったのかにゃ…？ご利用は計画的ににゃん！", "blobcat_ziainokaitou.png"),
        ("にゃーん（エンジンの音）", "blobcat_sing.png"),
        ("バイクに乗りたい…乗せてほしいにゃん…", "blobcataww.png"),
        ("ヘルメットについた虫、ちゃんと取ったかにゃ？放置すると取れなくなるにゃん…。", "blobcat_woozy.png"),
        ("四輪は体を運び、二輪は魂を運ぶ…にゃんてね。", "blobcat_yoyuunoemi.webp"),
        ("悩み事があるなら、とりあえず走ってみるにゃ。風が何かを教えてくれるかもしれにゃい。", "blobcat_wind_chime.gif"),
    ]
    advice_pool.extend(humor_greetings)
    
    # =================================================================
    # カテゴリ3: ユーザーデータに応じた動的なアドバイス
    # =================================================================
    
    # --- 初心者向け ---
    has_any_log = db.session.query(FuelEntry.id).join(Motorcycle).filter(Motorcycle.user_id == user.id).first() or \
                  db.session.query(MaintenanceEntry.id).join(Motorcycle).filter(Motorcycle.user_id == user.id, MaintenanceEntry.category != '初期設定').first()
    if not has_any_log:
        advice_pool.append(("まずは最初の記録をつけてみようにゃ！給油記録が一番簡単でおすすめにゃん。", "blobcataww.png"))

    if not MaintenanceEntry.query.join(Motorcycle).filter(Motorcycle.user_id == user.id, MaintenanceEntry.category != '初期設定').first():
        advice_pool.append(("愛車のメンテナンスは大事にゃ。最初の整備記録としてオイル交換でも記録してみるにゃ？", "blobcat_hamigaki.png"))

    # --- アクティビティ関連 ---
    latest_activity = ActivityLog.query.filter_by(user_id=user.id).order_by(ActivityLog.activity_date.desc()).first()
    if latest_activity:
        days_since = (today.date() - latest_activity.activity_date).days
        if days_since <= 14:
            location = latest_activity.location_name_display or "この間の活動"
            advice_pool.append((f"{location}での活動、お疲れ様にゃ！セッティングや走りの感想を記録しておくと次に繋がるにゃ。", "blobcat_yay.apng"))
        elif days_since > 60:
            advice_pool.append(("最近、活動の記録がないみたいにゃ…？たまにはサーキットや峠で思いっきり走るのもいいにゃん！", "blobcat_pity.webp"))

    # --- リマインダー関連 ---
    overdue_reminders_query = MaintenanceReminder.query.join(Motorcycle).filter(
        Motorcycle.user_id == user.id,
        MaintenanceReminder.is_dismissed == False,
        (MaintenanceReminder.snoozed_until == None) | (MaintenanceReminder.snoozed_until <= datetime.now(timezone.utc))
    )
    overdue_reminders_count = overdue_reminders_query.count()
    if overdue_reminders_count > 0:
        advice_pool.append((f"期限が近い（または過ぎた）リマインダーが{overdue_reminders_count}件あるにゃ。確認を忘れずににゃん！", "blobcat_aseri.png"))

    # --- 車両関連 ---
    if any(m.is_racer for m in motorcycles):
         advice_pool.append(("レーサーの稼働時間、ちゃんと記録してるかにゃ？次のメンテナンス時期の目安になるにゃん。", "blobcat_asterisk.png"))

    if len(motorcycles) > 1:
        advice_pool.append(("たくさん愛車がいてうらやましいにゃ！デフォルト車両の設定はちゃんとしてるかにゃ？", "blobcat_uwu.png"))

    # =================================================================
    # カテゴリ4: 日付、時間、季節に基づいたアドバイス
    # =================================================================
    
    # --- 曜日 ---
    weekday = today.weekday()
    if weekday in [4, 5]: # 金・土
        advice_pool.append(("週末にゃ！絶好のツーリング日和かもしれにゃい！", "blobcat_uwu.png"))
    if weekday == 6: # 日
        advice_pool.append(("日曜の夜はなんだか寂しい気分になるにゃ…明日からまた一週間がんばるにゃん！", "blobcat_tereru.png"))
    if weekday == 0: # 月
        advice_pool.append(("新しい一週間の始まりにゃ！今週はどこか走りに行く予定はあるかにゃ？", "blobcatthinking.png"))

    # --- 時間帯 ---
    hour = today.hour
    if 5 <= hour < 10:
        advice_pool.append(("おはようにゃ！今日の天気はどうかにゃ？", "blobcat_ohayo.png"))
    elif 12 <= hour < 14:
        advice_pool.append(("お昼ごはんは何を食べたかにゃ？腹が減っては戦はできぬにゃ！", "blobcat_mogumogu.gif"))
    elif 18 <= hour < 21:
        advice_pool.append(("おつかれさまにゃ。今日の疲れは今日の内に癒やすにゃん。", "blobcatcomfy.png"))
    elif 22 <= hour or hour < 2:
        advice_pool.append(("そろそろおやすみの時間にゃ。いい夢を見るにゃん…", "blobcat_oyasumi.png"))

    # --- 季節 ---
    month = today.month
    if month in [3, 4, 5]:
        advice_pool.append(("春はツーリングに最高の季節にゃ！花粉対策は忘れずににゃん。", "blobcat_yay.apng"))
    elif month in [6, 7]: # 梅雨
        advice_pool.append(("梅雨の季節にゃ。バイクを磨いて次の晴れ間を待つのも一興にゃん。", "ablobcatcomfy_raincoat.apng"))
    elif month in [8]: # 真夏
        advice_pool.append(("夏は暑いけど、早朝や高原ツーリングが気持ちいいにゃ！水分補給はこまめににゃ。", "ablobcatsweatsip.apng"))
    elif month in [9, 10, 11]:
        advice_pool.append(("秋は紅葉が綺麗にゃね。美味しいものを食べるツーリングも最高にゃ！", "blobcat_nomming.gif"))
    elif month in [12, 1, 2]:
        advice_pool.append(("冬は空気が澄んでて景色がいいにゃ。でも路面凍結には十分気をつけるにゃん！", "ablobcatsnowjoy.gif"))

    # =================================================================
    # 5. アドバイスと画像の選択
    # =================================================================
    if not advice_pool:
        return None
        
    selected_advice, specific_image = random.choice(advice_pool)

    image_filename = None
    nyanpuppu_dir = os.path.join(current_app.static_folder, 'images', 'nyanpuppu')
    try:
        if os.path.isdir(nyanpuppu_dir):
            available_images = [f for f in os.listdir(nyanpuppu_dir) if f.endswith(('.png', '.webp', '.gif', '.apng'))]
            if available_images:
                if specific_image and specific_image in available_images:
                    image_filename = specific_image
                else:
                    image_filename = random.choice(available_images)
    except Exception as e:
        current_app.logger.error(f"Error accessing nyanpuppu image directory: {e}")

    if not image_filename:
        return None

    return {
        'text': selected_advice,
        'image_filename': image_filename
    }