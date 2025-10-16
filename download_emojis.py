import os
import requests
import json
import re

# --- 設定 ---
# 保存先ディレクトリ (motopuppu/static/images/nyanpuppu)
OUTPUT_DIR = os.path.join('motopuppu', 'static', 'images', 'nyanpuppu')
# MisskeyインスタンスのURL
MISSKEY_INSTANCE_URL = 'https://misskey.io'
# 検索キーワード
KEYWORD = 'blobcat'
# ----------------

def sanitize_filename(name):
    """ファイル名として無効な文字をアンダースコアに置換する"""
    return re.sub(r'[\\/*?:"<>|]', '_', name)

def download_blobcat_emojis():
    """Misskey.ioからblobcat関連の絵文字をダウンロードする"""
    print(f"[*] '{KEYWORD}'関連の絵文字をダウンロードします...")
    
    # 保存先ディレクトリを作成
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"[+] ディレクトリを作成しました: {OUTPUT_DIR}")

    # Misskey APIから絵文字リストを取得
    try:
        print(f"[*] {MISSKEY_INSTANCE_URL} から絵文字リストを取得中...")
        response = requests.post(f"{MISSKEY_INSTANCE_URL}/api/emojis", json={}, timeout=20)
        response.raise_for_status()
        emojis_data = response.json().get("emojis", [])
        print(f"[+] {len(emojis_data)}件の絵文字情報を取得しました。")
    except requests.RequestException as e:
        print(f"[!] エラー: 絵文字リストの取得に失敗しました。: {e}")
        return
    except json.JSONDecodeError:
        print("[!] エラー: APIからのレスポンスがJSON形式ではありませんでした。")
        return

    # blobcat関連の絵文字をフィルタリング
    target_emojis = [emoji for emoji in emojis_data if KEYWORD in emoji.get('name', '')]

    if not target_emojis:
        print(f"[!] '{KEYWORD}' に一致する絵文字が見つかりませんでした。")
        return

    print(f"[*] {len(target_emojis)}件の '{KEYWORD}' 絵文字が見つかりました。ダウンロードを開始します。")

    # 画像をダウンロード
    downloaded_count = 0
    for emoji in target_emojis:
        name = emoji.get('name')
        url = emoji.get('url')
        if not name or not url:
            continue
        
        try:
            # URLからファイル拡張子を取得
            extension = os.path.splitext(url.split('?')[0])[-1]
            if not extension:
                extension = '.png' # デフォルト

            # ファイル名をサニタイズしてパスを生成
            filename = sanitize_filename(name) + extension
            filepath = os.path.join(OUTPUT_DIR, filename)

            # ダウンロード実行
            img_response = requests.get(url, timeout=10, stream=True)
            img_response.raise_for_status()

            with open(filepath, 'wb') as f:
                for chunk in img_response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            print(f"  -> {filename} を保存しました。")
            downloaded_count += 1
            
        except requests.RequestException as e:
            print(f"  [!] '{name}' のダウンロードに失敗しました: {e}")
        except Exception as e:
            print(f"  [!] 予期せぬエラーが発生しました ({name}): {e}")
    
    print(f"\n[*] ダウンロード完了！ {downloaded_count}/{len(target_emojis)} 件のファイルを保存しました。")
    print(f"[*] 保存先: {os.path.abspath(OUTPUT_DIR)}")

if __name__ == '__main__':
    download_blobcat_emojis()