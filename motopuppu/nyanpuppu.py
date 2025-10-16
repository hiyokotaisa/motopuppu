# motopuppu/nyanpuppu.py
import random
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import current_app
from sqlalchemy import desc, func
from .models import db, Motorcycle, FuelEntry, MaintenanceEntry, ActivityLog, MaintenanceReminder, SessionLog
# ▼▼▼【ここから追記】ベストラップタイムをフォーマットする関数をインポート ▼▼▼
from .utils.lap_time_utils import format_seconds_to_time
# ▲▲▲【追記はここまで】▲▲▲

def get_advice(user, motorcycles):
    """
    ダッシュボードに表示する「にゃんぷっぷー」のアドバイスと画像を決定して返す。
    発言ロジックはこのファイルに集約する。
    """
    if not user:
        return None

    simple_phrases = [
        "ぷにゃにゃ...！", "ぷにゃあにゃ...！", "ぷにゃんにゃん！", "ぷにゃにゃあにゃん～",
        "ぷにゃにゃにゃにゃん、ぷにゃん～", "ぷにゃにゃあ、ぷにゃんにゃあにゃあ！", "ぷにゃんにゃあ、ぷにゃにゃん！",
        "ぷにゃあにゃあにゃん！", "ぷにゃ、ぷにゃんにゃあにゃんにゃ！", "ぷにゃにゃー！", "ぷにゃにゃん...",
        "ぷにゃにゃんにゃ...", "ぷにゃにゃあにゃん...", "ぷにゃにゃ...", "ぷにゃんにゃん...",
        "ぷにゃあにゃあにゃん...", "ぷにゃんにゃにゃあ...", "ぷにゃんにゃにゃにゃあ！", "ぷにゃんにゃあにゃ～",
        "ぷにゃあにゃあ～", "ぷにゃんにゃ～", "ぷにゃあにゃん...", "ぷにゃにゃん！！", "ぷにゃあにゃにゃん！",
        "ぷにゃ、ぷにゃにゃあ...", "ぷにゃあ、ぷにゃにゃにゃん～", "ぷにゃんにゃ！", "ぷにゃあにゃにゃにゃん、ぷにゃあ！",
        "ぷにゃんにゃん～", "ぷにゃにゃあにゃ...！", "ぷにゃにゃあ！", "ぷにゃんにゃ...！", "ぷにゃあにゃにゃ！",
        "ぷにゃあにゃん...！", "ぷにゃあにゃあにゃにゃ～", "ぷにゃにゃー！", "ぷにゃあにゃ...！",
        "ぷにゃん、ぷにゃあにゃあにゃあにゃあ...！", "ぷにゃあ、ぷにゃにゃあ...！", "ぷにゃあにゃんにゃあ...！",
        "ぷにゃあにゃ...","ぷにゃにゃあにゃあ...","ぷにゃあにゃん、ぷにゃんにゃあ！", "ぷにゃんにゃあにゃ！",
        "ぷにゃんにゃあにゃあ...","ぷにゃあにゃあ...！", "ぷにゃあにゃんにゃん！", "ぷにゃんにゃにゃん～",
        "ぷにゃん、ぷにゃあにゃあ！","ぷにゃあにゃん！","ぷにゃあにゃあにゃ～", "ぷにゃあにゃんにゃあ！",
        "ぷにゃあにゃ、ぷにゃあ！", "ぷにゃんにゃん...？"
    ]

    if user.nyanpuppu_simple_mode:
        selected_advice = random.choice(simple_phrases)
        specific_image = "blobcat.png"
    else:
        # 通常モードでも一定確率でシンプルモードの発言をする (例: 20%の確率)
        if random.randint(1, 5) == 1:
            selected_advice = random.choice(simple_phrases)
            specific_image = "blobcat.png"
        else:
            advice_pool = []
            today = datetime.now(ZoneInfo("Asia/Tokyo"))
            
            # =================================================================
            # カテゴリ1: もとぷっぷーの使い方TIPS
            # =================================================================
            app_tips = [
                ("給油記録を「満タン」で登録すると、自動で燃費が計算されるにゃん。", "blobcat_ago.png"),
                ("整備記録にカテゴリを設定すると、リマインダーと連携できて便利にゃ。", "blobcat_thumbsup.png"),
                ("ダッシュボード右上のギアアイコンから、ウィジェットの配置を自由に変更できるにゃ。", "blobcatuwu.png"),
                ("活動ログ機能で、サーキット走行のセッティングやタイムを記録してみようにゃ。", "blobcat_rider.gif"),
                ("ノート機能は、TODOリストとしても使えるにゃ。忘れがちな作業をメモしておくといいにゃ。", "blobcataco.png"),
                ("ツーリングログ機能で、旅の思い出をスクラップできるにゃん！", "blobcat_binoculars.webp"),
                ("車両編集画面から、愛車の画像を登録できるにゃ。ガレージが華やかになるにゃん。", "rv_blobcat_camera2.webp"),
                ("リマインダー機能のスヌーズを使えば、通知を一時的におやすみさせられるにゃ。", "blobcat_nemunemu.png"),
                ("統計ウィジェットの期間フィルタ、使ってるかにゃ？過去の記録を振り返るのに便利にゃん。", "blobcat_pensive.png"),
                ("Misskey共有ボタンから、実績や活動記録を自慢できるにゃ！", "blobcat_yay.apng"),
                ("活動ログのセッティングシートは一度作れば使い回せるにゃ。基本セットを作っておくと楽ちんにゃん。", None),
                ("ガレージ設定から、君だけの公開プロフィールページを作れるにゃ。テーマも色々選べるにゃん！", "blobcatuwu.png"),
                ("各記録の一覧画面にあるCSVエクスポート機能で、データのバックアップもバッチリにゃ。", None),
            ]
            advice_pool.extend(app_tips)

            # =================================================================
            # カテゴリ2: バイクTIPS (メンテナンス・ライディング・トリビア)
            # =================================================================
            bike_tips = [
                # --- メンテナンス ---
                ("タイヤの空気圧はこまめにチェックするにゃ。安全運転の基本にゃん！", "blobcat_aseri.png"),
                ("チェーンの掃除と注油、忘れてないかにゃ？走りが見違えることもあるにゃん。", "blobcat_mukimuki.png"),
                ("ブレーキフルードは1〜2年で交換するのがおすすめにゃ。色が濃くなってきたら交換のサインにゃん。", "blobcat_aseri2.png"),
                ("ヘルメットの有効期限は3年って言われてるにゃ。定期交換が大事にゃね。", "blobcat_oh.png"),
                ("バッテリーが弱ってないかにゃ？冬は特に上がりやすいから注意にゃ。", "blobcat_aseri.png"),
                ("チェーンのたるみ、大丈夫かにゃ？指二本分くらいが目安にゃん。", "blobcattea.png"),
                ("ブレーキパッドの残量、溝を確認するにゃ。キーキー鳴ったら末期症状にゃん！", "blobcatmeow_ponponpain.png"),
                ("たまにはバイクを洗車してあげるにゃ。汚れの下にトラブルが隠れてることも…にゃんてね。", "blobcat_shower.png"),
                ("エンジンオイルはバイクの血液にゃ。定期的に窓から色と量を確認するクセをつけるにゃ。", "blobcatmeow_ponponpain.png"),
                ("タイヤの製造年月日、見たことあるかにゃ？4桁の数字で週と年がわかるにゃん。古すぎると危険にゃ！", "blobcat_fun.apng"),

                # --- ライディング ---
                ("コーナーの先を見て走ると、スムーズに曲がれるようににゃるにゃん。", "blobcat_binoculars.webp"),
                ("急ブレーキは禁物にゃ。じわーっとかけて、タイヤをロックさせないようにするにゃ。", "blobcattea.png"),
                ("雨の日のマンホールや白線は滑りやすいから気をつけるにゃ。そろーっと通るにゃ。", "ablobcatcomfy_raincoat.apng"),
                ("すり抜けは危ないから、ほどほどににゃ。心と車間に余裕を持つにゃん。", "blobcatpolicepeek.png"),
                ("服装は大事にゃ。「ちょっとそこまで」でも、肌の露出は避けるにゃ。", "blobcattea.png"),
                ("向かい風が強い日は、少し前傾姿勢になると楽になるにゃ。風と友達になるにゃん。", "blobcat_running.gif"),
                ("バイクを曲げたいときは、曲がりたい方向のハンドルを「押す」って意識すると曲がりやすいにゃん。不思議にゃね。", "blobcat_aomuke.webp"),
                ("高速道路を走るときは、耳栓をすると疲れ方が全然違うらしいにゃ。試してみる価値ありにゃ！", "blobcat_nemunemu.png"),
                ("ニーグリップ、しっかりできてるかにゃ？下半身でバイクをホールドすると上半身の力が抜けて楽になるにゃん。", "blobcat_mukimuki.png"),
                ("ヘルメットのシールド、綺麗かにゃ？視界がクリアだと安全性も気分も上がるにゃん！", "blobcatsmile_face.webp"),
                ("ツーリングの荷物は、重いものをなるべく低く、中心に積むのが安定のコツにゃ。", "blobcat_transport.png"),
                ("インカムがあると、仲間とのおしゃべりやナビ音声が聞けてツーリングがもっと楽しくなるにゃん。", "blobcat_sing.png"),
                ("エンジンをかける前の日常点検、「ねん・お・しゃ・ち・え・ぶ・く・とう・ば・しめ」って知ってるかにゃ？", "blobcatthinking.png"),
            ]
            advice_pool.extend(bike_tips)

            # =================================================================
            # カテゴリ3: ユーモア・雑談・甘え
            # =================================================================
            humor_greetings = [
                ("今日も一日、ご安全ににゃ！", "ablobcat_wave.gif"),
                ("記録を続けるの、えらいにゃ！君のバイクライフがもっと豊かになるお手伝いをするにゃ。", "ablobcat_cheer.gif"),
                ("疲れたら無理せず休憩するにゃ。バイクは逃げないにゃん。", "blobcat_tea.png"),
                ("次のツーリングはどこに行くかニャ？計画を立てるのも楽しい時間にゃん。", "blobcatthinking.png"),
                ("にゃんぷっぷー！今日も元気に記録するにゃ！", "ablobcat_eieiou.gif"),
                ("ヤエー！(・∀・)v ってすると、ツーリング仲間が増えるかもしれにゃい！", "ablobcat_wave.gif"),
                ("また新しいパーツを買ったのかにゃ…？ご利用は計画的ににゃん！", "blobcat_tea.png"),
                ("にゃーん（アイドリングの音）", "blobcat_sing.png"),
                ("バイクに乗りたい…乗せてほしいにゃん…", "blobcataww.png"),
                ("ヘルメットについた虫、ちゃんと取ったかにゃ？放置すると取れなくなるにゃん…。", "blobcat_woozy.png"),
                ("四輪は体を運び、二輪は魂を運ぶ…にゃんてね。", "blobcat_tea.png"),
                ("悩み事があるなら、とりあえず走ってみるにゃ。風が何かを教えてくれるかもしれにゃい。", "blobcat_wind_chime.gif"),
                ("ガソリンの匂いって、なんだか落ち着くにゃん…。", "blobcat_uwu.png"),
                ("バイク乗りの朝は早いにゃ。渋滞も暑さも避けるにゃん。冬はちゃんとあったかくするにゃ。", "blobcat_ohayo.png"),
                ("今日はなんだか眠いにゃ…ごろごろ…", "blobcat_8bit_sleep.gif"),
                ("なでなでするにゃ？", "ablobcatfloofpat.gif"),
                ("お腹すいたにゃん…おいしいラーメンが食べたいにゃ。", "blobcat_mogumogu.gif"),
                ("もとぷっぷーを使ってくれてありがとうにゃん！", "blobcat_daisuki.webp"),
                ("時にはなにも考えずにぼーっとするのも大事にゃん。", None),
                ("もしかして、にゃんぷっぷー鬱陶しいにゃ……？ 喋ってほしくないときは「プロフィール」から喋らないようにもできるにゃ……", "blobcatnoplease.png"),
                ("にゃんぷっぷーはここでずっと待ってるにゃん。", "blobcatcomfy.png"),
                ("きゅるるん！ 今日もかわいいにゃんぷっぷーに会えてラッキーだにゃ！", "blobcat_pity.webp"),
                ("なんかおやつ欲しいにゃ…ちゅ～るでもいいにゃん。", "blobcat_mogumogu.gif"),
                ("君のバイク、かっこいいにゃね！にゃんぷっぷーも乗ってみたいにゃ。", "blobcataww.png"),
                ("今日の夜ご飯、何にするかにゃ？にゃんぷっぷーは焼き魚がいいにゃ！", None),
                ("にゃんぷっぷー、いつでも君の味方だにゃ！困ったことがあったら話しかけてにゃん。", "blobcat_uwu.png"),
                ("道の駅たちばなっていうところが一部の界隈で人気らしいにゃん。いつか行ってみたいにゃ！", "blobcataww.png"),
            ]
            advice_pool.extend(humor_greetings)

            # =================================================================
            # カテゴリ4: バイクメーカー・車種トリビア
            # =================================================================
            makers_in_garage = {m.maker.lower() for m in motorcycles if m.maker}
            
            # --- ホンダのトリビア ---
            honda_trivia = [
                ("ホンダのスーパーカブは世界で一番たくさん作られたバイクにゃん。すごい数だにゃ！", "blobcatmeltlove.png"),
                ("ホンダのウイングマークは、ギリシャ神話の勝利の女神「ニケ」の翼がモチーフにゃんだって。かっこいいにゃ！", "blobcatmeltlove.png"),
                ("ホンダのCB400SFのVTECは、ある回転数でバルブの数が変わる魔法の仕組みにゃん。音が変わる瞬間がたまらないにゃ！", "blobcat_yay.apng"),
                ("NSR250Rの「ガルアーム」は、チャンバーの取り回しを良くするために生まれた、ホンダの独創的なスイングアームにゃん。", None),
            ]
            if 'ホンダ' in makers_in_garage or 'honda' in makers_in_garage:
                advice_pool.extend(honda_trivia)
            else:
                advice_pool.append(random.choice(honda_trivia))

            # --- ヤマハのトリビア ---
            yamaha_trivia = [
                ("ヤマハはもともと楽器の会社にゃん。だからロゴが音叉のマークなんだにゃ。エンジン音も調律されてるのかにゃ？", "blobcat_sing.png"),
                ("ヤマハのSR400は、40年以上も基本設計を変えずに作られ続けた伝説のバイクにゃ。キックスタートは儀式にゃん！", "blobcat_doya.png"),
                ("ヤマハのバイクのフレーム番号には、アルファベットの「I」が使われないらしいにゃ。数字の「1」と見間違えないようにするためだとか。", None),
            ]
            if 'ヤマハ' in makers_in_garage or 'yamaha' in makers_in_garage:
                advice_pool.extend(yamaha_trivia)
            else:
                advice_pool.append(random.choice(yamaha_trivia))

            # --- カワサキのトリビア ---
            kawasaki_trivia = [
                ("カワサキのライムグリーンは、昔のアメリカのレースで「不吉な色」をあえて使って勝ったのが始まりらしいにゃ。漢だにゃ！", "blobcat_mukimuki.png"),
                ("「Ninja」っていう名前、最初はアメリカ向けだったのが世界中に広まったんだにゃ。クールにゃん！", "blobcat_rider.gif"),
                ("カワサキのバイクは、川崎重工っていう大きな会社のほんの一部門にゃん。船とか飛行機も作ってるんだにゃ！", None),
            ]
            if 'カワサキ' in makers_in_garage or 'kawasaki' in makers_in_garage:
                advice_pool.extend(kawasaki_trivia)
            else:
                advice_pool.append(random.choice(kawasaki_trivia))

            # --- スズキのトリビア ---
            suzuki_trivia = [
                ("スズキは昔、織物を作る機械の会社だったにゃ。すごい転身だにゃ！", "ablobcat_cheer.gif"),
                ("GSX1100Sカタナのデザインは、日本の「刀」がモチーフにゃん。今見ても斬新だにゃ！", "blobcat_thumbsup.png"),
                ("スズキのハヤブサは日本語の「隼」から来てるにゃ。ホンダのブラックバード(ツグミ)を狩る猛禽類っていう意味が込められてるらしいにゃ！", None),
                ("スズキの「湯呑み」は、イベントとかで配られる非売品だけど、なぜかバイク乗りの間ですごく有名にゃん。", None),
            ]
            if 'スズキ' in makers_in_garage or 'suzuki' in makers_in_garage:
                advice_pool.extend(suzuki_trivia)
            else:
                advice_pool.append(random.choice(suzuki_trivia))

            # --- 海外メーカーのトリビア ---
            foreign_trivia = [
                ("ドゥカティの「デスモドロミック」っていうバルブ機構は、超高回転でも正確に動くための特別な仕組みにゃん。", "ablobcat_cheer.gif"),
                ("ハーレーダビッドソンの「三拍子」と呼ばれるアイドリング音は、独特の点火タイミングから生まれるんだにゃ。", None),
                ("BMWのボクサーエンジンは、重心が低くて安定感があるのが特徴にゃ。独特な見た目もいいにゃ！", "blobcatuwu.png"),
                ("KTMは「READY TO RACE」がスローガンにゃ。オフロードにすごく強いメーカーとして有名にゃん！", "blobcat_rider.gif"),
            ]
            advice_pool.extend(foreign_trivia)
            
            # =================================================================
            # カテゴリ5: ユーザーのデータ状況に応じた動的なアドバイス
            # =================================================================
            
            # --- 初心者・利用頻度が低いユーザー向け ---
            all_logs_count = db.session.query(FuelEntry.id).join(Motorcycle).filter(Motorcycle.user_id == user.id).count() + \
                             db.session.query(MaintenanceEntry.id).join(Motorcycle).filter(Motorcycle.user_id == user.id, MaintenanceEntry.category != '初期設定').count()
            if all_logs_count == 0:
                advice_pool.append(("まずは最初の記録をつけてみようにゃ！給油記録が一番簡単でおすすめにゃん。", "blobcataww.png"))
            elif all_logs_count < 5:
                advice_pool.append(("おっ、記録が増えてきたにゃ！この調子にゃん！", "blobcat_yay.apng"))

            # --- 給油記録関連 ---
            last_fuel_entry = FuelEntry.query.join(Motorcycle).filter(Motorcycle.user_id == user.id).order_by(desc(FuelEntry.entry_date)).first()
            if last_fuel_entry and last_fuel_entry.km_per_liter:
                if last_fuel_entry.km_per_liter > 35:
                    advice_pool.append((f"最近の燃費、すごくいいにゃ！エコ運転の達人にゃん！", "blobcat_zekkoutyou.webp"))
                elif last_fuel_entry.km_per_liter < 15:
                    advice_pool.append((f"最近の燃費、ちょっとお疲れ気味かにゃ…？空気圧とか確認してみるにゃ？", "blobcat_zehhutyou.webp"))

            # --- メンテナンス記録関連 ---
            last_maintenance = MaintenanceEntry.query.join(Motorcycle).filter(Motorcycle.user_id == user.id, MaintenanceEntry.category != '初期設定').order_by(desc(MaintenanceEntry.maintenance_date)).first()
            if last_maintenance:
                if (today.date() - last_maintenance.maintenance_date).days < 7:
                    advice_pool.append(("最近メンテナンスしたんだにゃ！愛車も喜んでるにゃん。", "blobcat_daisuki.webp"))
            
            last_oil_change = MaintenanceEntry.query.join(Motorcycle).filter(Motorcycle.user_id == user.id, MaintenanceEntry.category == 'エンジンオイル交換').order_by(desc(MaintenanceEntry.maintenance_date)).first()
            if last_oil_change and (today.date() - last_oil_change.maintenance_date).days > 365:
                advice_pool.append(("最後にオイル交換してから1年以上経ってるみたいにゃ。そろそろ交換時期かもしれにゃい。", "blobcat_aseri.png"))

            last_tire_change = MaintenanceEntry.query.join(Motorcycle).filter(Motorcycle.user_id == user.id, MaintenanceEntry.category == 'タイヤ交換').order_by(desc(MaintenanceEntry.maintenance_date)).first()
            if last_tire_change and (today.date() - last_tire_change.maintenance_date).days < 30:
                advice_pool.append(("新しいタイヤは気持ちいいにゃ！皮むきが終わるまでは慎重に運転するにゃん。", "blobcat_niko_hohoemi.png"))
            
            # --- サーキット活動関連 ---
            latest_circuit_log = ActivityLog.query.filter(ActivityLog.user_id == user.id, ActivityLog.circuit_name != None).order_by(desc(ActivityLog.activity_date)).first()
            unique_circuit_count = db.session.query(func.count(func.distinct(ActivityLog.circuit_name))).filter(ActivityLog.user_id == user.id).scalar()
            total_circuit_activities = ActivityLog.query.filter(ActivityLog.user_id == user.id, ActivityLog.circuit_name != None).count()

            if not latest_circuit_log:
                advice_pool.append(("サーキット走行の記録がまだないみたいだにゃ。活動ログ機能でセッティングやタイムを記録すると、上達が早まるかもにゃん！", "blobcat_rider.gif"))
            else:
                days_since_circuit = (today.date() - latest_circuit_log.activity_date).days
                
                if total_circuit_activities == 1:
                    advice_pool.append((f"初めてのサーキット走行記録、おめでとうにゃ！また走るのが楽しみだにゃんね！", "blobcat_yay.apng"))
                elif days_since_circuit <= 14:
                    advice_pool.append((f"{latest_circuit_log.circuit_name}での走行、お疲れ様にゃ！ラップタイムの変化を見返してみるにゃ？", "blobcat_yay.apng"))
                elif days_since_circuit > 90 and total_circuit_activities > 1:
                    advice_pool.append(("最近サーキット走ってないのかにゃ？うずうずしてくる頃じゃないかにゃ？", "blobcat_pity.webp"))

                if unique_circuit_count == 1 and total_circuit_activities >= 5:
                    advice_pool.append((f"{latest_circuit_log.circuit_name}は君のホームコースにゃんね！走り込んでてえらいにゃん！", "blobcat_doya.png"))
                elif unique_circuit_count > 1 and total_circuit_activities >= 3:
                    advice_pool.append((f"いろんなサーキットを攻略してるんだにゃ！次はどのコースに挑戦するのかにゃ？", "blobcat_binoculars.webp"))

                # ▼▼▼【ここから修正】エラー箇所を修正 ▼▼▼
                latest_session = SessionLog.query.join(ActivityLog).filter(ActivityLog.user_id == user.id, ActivityLog.id == latest_circuit_log.id).order_by(desc(SessionLog.id)).first()
                if latest_session and latest_session.best_lap_seconds:
                    advice_pool.append((f"この前の{latest_circuit_log.circuit_name}でのベストラップは{format_seconds_to_time(latest_session.best_lap_seconds)}にゃんね！", "blobcat_rider.gif"))
                # ▲▲▲【修正はここまで】▲▲▲
                
                # ユーザーがレース車両を所有している場合
                if any(m.is_racer for m in motorcycles):
                    advice_pool.append(("レース用車両のセッティング、うまくいってるかにゃ？活動ログで微調整を記録するにゃ！", "blobcat_asterisk.png"))

            # --- リマインダー関連 ---
            overdue_reminders_count = MaintenanceReminder.query.join(Motorcycle).filter(
                Motorcycle.user_id == user.id,
                MaintenanceReminder.is_dismissed == False,
                (MaintenanceReminder.snoozed_until == None) | (MaintenanceReminder.snoozed_until <= datetime.now(timezone.utc))
            ).count()
            if overdue_reminders_count > 0:
                advice_pool.append((f"期限が近い（または過ぎた）リマインダーが{overdue_reminders_count}件あるにゃ。確認を忘れずににゃん！", "blobcat_aseri.png"))

            # --- 車両関連 ---
            if any(m.is_racer for m in motorcycles):
                 advice_pool.append(("レーサーの稼働時間、ちゃんと記録してるかにゃ？次のメンテナンス時期の目安になるにゃん。", "blobcat_asterisk.png"))

            if len(motorcycles) > 1:
                advice_pool.append(("たくさん愛車がいてうらやましいにゃ！デフォルト車両の設定はちゃんとしてるかにゃ？", "blobcat_uwu.png"))
            
            for m in motorcycles:
                if not m.is_racer:
                    from .services import get_latest_total_distance
                    mileage = get_latest_total_distance(m.id, m.odometer_offset)
                    if 50000 > mileage > 49500 or 100000 > mileage > 99500:
                        advice_pool.append((f"{m.name}がもうすぐ大台に乗りそうにゃ！記念すべき瞬間を見逃さないようににゃ！", "blobcat_oh.png"))

            # =================================================================
            # カテゴリ6: 日付、時間、季節に基づいたアドバイス
            # =================================================================
            
            # --- 曜日 ---
            weekday = today.weekday()
            if weekday in [4, 5]:
                advice_pool.append(("週末にゃ！絶好のツーリング日和かもしれにゃい！", "blobcat_uwu.png"))
            if weekday == 6:
                advice_pool.append(("日曜の夜はなんだか寂しい気分になるにゃ…明日からまた一週間がんばるにゃん！", "blobcat_tereru.png"))
            if weekday == 0:
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
                advice_pool.extend([
                    ("春はツーリングに最高の季節にゃ！花粉対策は忘れずににゃん。", "blobcat_yay.apng"),
                    ("桜のトンネルを走るの、最高にゃん！でも見とれて脇見運転はダメにゃんよ。", "blobcat_pensive.png"),
                    ("春は虫さんが元気だから、シールドはこまめに拭くにゃ。", "blobcat_woozy.png"),
                ])
            elif month in [6, 7]:
                advice_pool.extend([
                    ("梅雨の季節にゃ。バイクを磨いて次の晴れ間を待つのも一興にゃん。", "ablobcatcomfy_raincoat.apng"),
                    ("雨の日は視界が悪くなりがちにゃ。後続車に気づいてもらえるように、早めにアピールするにゃん。", None),
                ])
            elif month in [8]:
                advice_pool.extend([
                    ("夏は暑いけど、早朝や高原ツーリングが気持ちいいにゃ！水分補給はこまめににゃ。", "ablobcatsweatsip.apng"),
                    ("メッシュジャケットは夏の相棒にゃ！風を感じて走るにゃん！", "blobcat_running.gif"),
                    ("暑い日のアスファルトはタイヤが溶けやすいから気をつけるにゃ。", "blobcat_melting.webp"),
                    ("夕立に注意にゃ。天気予報はしっかり見るにゃん。", "blobcat_aseri.png"),
                ])
            elif month in [9, 10, 11]:
                advice_pool.extend([
                    ("秋は紅葉が綺麗にゃね。美味しいものを食べるツーリングも最高にゃ！", "blobcat_nomming.gif"),
                    ("落ち葉は滑りやすいから気をつけて走るにゃん。", "blobcat_pity.webp"),
                    ("だんだん日が短くなってきたにゃ。早めのライト点灯を心がけるにゃ。", "blobcat_ohayo.png"),
                ])
            elif month in [12, 1, 2]:
                advice_pool.extend([
                    ("冬は空気が澄んでて景色がいいにゃ。でも路面凍結には十分気をつけるにゃん！", "ablobcatsnowjoy.gif"),
                    ("グリップヒーターは冬の神様にゃ。一度使ったらやめられないにゃ…。", "blobcat_daisuki.webp"),
                    ("路面のブラックアイスバーンは本当に見えないから、橋の上とか日陰は特に注意にゃ！", "blobcat_kowaii.png"),
                    ("寒い日のエンジン始動は、少し暖気してあげるとバイクが喜ぶにゃん。", "blobcat_tea.png"),
                ])

            if not advice_pool:
                selected_advice, specific_image = ("今日も一日、ご安全ににゃ！", "ablobcat_wave.gif")
            else:
                selected_advice, specific_image = random.choice(advice_pool)
    
    # =================================================================
    # 7. アドバイスと画像の選択
    # =================================================================
    image_filename = None
    nyanpuppu_dir = os.path.join(current_app.static_folder, 'images', 'nyanpuppu')
    try:
        if os.path.isdir(nyanpuppu_dir):
            available_images = [f for f in os.listdir(nyanpuppu_dir) if f.endswith(('.png', '.webp', '.gif', '.apng'))]
            if available_images:
                if specific_image and specific_image in available_images:
                    image_filename = specific_image
                elif "blobcat.png" in available_images:
                    image_filename = "blobcat.png"
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