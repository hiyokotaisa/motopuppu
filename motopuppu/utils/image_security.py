# motopuppu/utils/image_security.py
import io
import os
import uuid
import logging
from PIL import Image, ImageOps

# Google Cloud Storage import
try:
    from google.cloud import storage
except ImportError:
    storage = None

def strip_exif(image_bytes: bytes) -> bytes:
    """
    アップロードされた画像のバイナリデータからEXIF情報（位置情報など）を剥ぎ取り、
    再エンコードしたバイナリデータを返す。
    EXIFのOrientation（回転情報）は再エンコード時に物理的な回転として適用し、
    見た目を維持したままセキュア化する。
    
    Args:
        image_bytes (bytes): 元の画像データ
        
    Returns:
        bytes: EXIFが除去され、向きが補正された画像データ
    """
    try:
        # Pillowで画像をメモリ上に開く
        image_stream = io.BytesIO(image_bytes)
        img = Image.open(image_stream)
        
        # オリジナルのフォーマットを取得 (取得できない場合はJPEGにフォールバック)
        original_format = img.format or 'JPEG'
        
        # EXIFのOrientationタグに従って画像を回転させ、メタデータを反映済みのオブジェクトにする
        # これにより、再保存時にEXIFが欠落しても画像の向きがおかしくならない
        safe_img = ImageOps.exif_transpose(img)
        
        # RGBAなどのアルファチャンネルが含まれていてJPEG保存される場合の対策としてRGBに変換
        # (JPEGはアルファチャンネルをサポートしないため)
        if original_format.upper() in ['JPEG', 'JPG'] and safe_img.mode in ['RGBA', 'P']:
            safe_img = safe_img.convert('RGB')
        
        # 保存用のストリーム
        output_stream = io.BytesIO()
        
        # saveメソッドをデフォルトで使用すると、exif引数を指定しない限りEXIFデータは書き込まれない
        safe_img.save(output_stream, format=original_format)
        
        return output_stream.getvalue()
    except Exception as e:
        # 画像として読み込めなかった場合や変換エラーの場合は、
        # セキュリティ観点で元のデータをそのまま返さず、エラーをログに記録して例外を再送出する
        logging.error(f"Error stripping EXIF data: {e}", exc_info=True)
        raise ValueError("画像のEXIF除去処理に失敗しました。不正な画像ファイルの可能性があります。")


def process_and_upload_image(file_storage, user_id, max_size=(1200, 1200)):
    """
    アップロードされた画像（FileStorageなど）を開き、セキュリティチェック、
    リサイズ（最大1200px）、EXIF削除、WebP変換（軽量化）を行った上で
    Google Cloud Storage (GCS) にアップロードし、その公開パスURLを返します。
    
    Args:
        file_storage: アップロードされたファイル (FileStorageオブジェクト)
        user_id: アップロードするユーザーのID (GCSパスに含めて管理性を向上させる)
        max_size: リサイズの最大サイズ (幅, 高さ)
    """
    try:
        # Pillowで画像として読み込む
        img = Image.open(file_storage)
        
        # EXIFのOrientationを考慮して画像を回転・補正
        safe_img = ImageOps.exif_transpose(img)
        
        # WebP用にRGBへ変換しておく（不透明ならRGB、透明付きならRGBAでOK。ここではRGBA対応のWebPに合わせる）
        if safe_img.mode not in ('RGB', 'RGBA'):
            safe_img = safe_img.convert('RGBA') if 'A' in safe_img.mode else safe_img.convert('RGB')
            
        # サイズ縮小 (LANCZOSアルゴリズムでリサイズ、元の比率を保持しつつmax_size内に収める)
        safe_img.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # WebP形式で保存用ストリームへ出力 (EXIFデータは付与しないため破棄される)
        output_stream = io.BytesIO()
        safe_img.save(output_stream, format='WEBP', quality=85)
        output_stream.seek(0)
        
        # Google Cloud Storageへアップロード
        bucket_name = os.environ.get('GCS_BUCKET_NAME')
        if not storage or not bucket_name:
            logging.warning("GCS_BUCKET_NAME が設定されていない、または google-cloud-storage が読み込めません。")
            return None
            
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        
        # ユーザーIDを含むパスでUUID一意なファイル名(キー)を生成
        # ユーザー単位での管理・一括削除・運用を容易にするため
        unique_filename = f"vehicles/{user_id}/{uuid.uuid4().hex}.webp"
        blob = bucket.blob(unique_filename)
        
        # 一時ストリームからファイルをアップロード
        blob.upload_from_file(output_stream, content_type='image/webp')
        
        # 外部公開可能なURLを生成して返す (デフォルトのstorage.googleapis.comとする)
        return f"https://storage.googleapis.com/{bucket_name}/{unique_filename}"
        
    except Exception as e:
        logging.error(f"Error processing and uploading image: {e}", exc_info=True)
        raise ValueError("画像の処理またはアップロード時にエラーが発生しました。ファイルが破損しているか未対応の形式です。")


def delete_gcs_image(image_url):
    """
    指定されたURLがGCS上の画像である場合、そのBlobを削除します。
    storage.googleapis.com ドメイン以外のURL（外部リンク）は安全に無視します。
    削除に失敗してもアプリケーションの動作には影響しないため、
    エラーはログに記録するのみで例外は送出しません。
    
    Args:
        image_url (str): 削除対象の画像URL
        
    Returns:
        bool: 削除に成功した場合True、それ以外はFalse
    """
    if not image_url:
        return False
    
    # GCSのURLかどうかを判定 (storage.googleapis.com/<bucket>/<blob_path> 形式)
    GCS_HOST = "storage.googleapis.com"
    if GCS_HOST not in image_url:
        logging.debug(f"GCS以外のURLのため削除をスキップ: {image_url}")
        return False
    
    if not storage:
        logging.warning("google-cloud-storage が読み込めないため、GCS画像の削除をスキップします。")
        return False
    
    bucket_name = os.environ.get('GCS_BUCKET_NAME')
    if not bucket_name:
        logging.warning("GCS_BUCKET_NAME が設定されていないため、GCS画像の削除をスキップします。")
        return False
    
    try:
        # URL形式: https://storage.googleapis.com/{bucket_name}/{blob_path}
        # バケット名の後のパスをBlob名として抽出する
        prefix = f"https://{GCS_HOST}/{bucket_name}/"
        if not image_url.startswith(prefix):
            logging.warning(f"URLが期待するバケットプレフィックスに一致しません: {image_url}")
            return False
        
        blob_name = image_url[len(prefix):]
        if not blob_name:
            logging.warning(f"Blob名が空です: {image_url}")
            return False
        
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        blob.delete()
        
        logging.info(f"GCS画像を削除しました: {blob_name}")
        return True
        
    except Exception as e:
        # 削除失敗はクリティカルではないため、ログ出力のみで処理を継続する
        logging.warning(f"GCS画像の削除に失敗しました ({image_url}): {e}")
        return False


def delete_all_gcs_images_for_user(user_id):
    """
    指定されたユーザーIDに紐づくGCS上の全画像を一括削除します。
    アカウント退会時などに使用し、オーファン画像の発生を防ぎます。
    
    Args:
        user_id (int): 削除対象のユーザーID
        
    Returns:
        int: 削除されたBlobの数
    """
    if not storage:
        logging.warning("google-cloud-storage が読み込めないため、GCS画像の一括削除をスキップします。")
        return 0
    
    bucket_name = os.environ.get('GCS_BUCKET_NAME')
    if not bucket_name:
        logging.warning("GCS_BUCKET_NAME が設定されていないため、GCS画像の一括削除をスキップします。")
        return 0
    
    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        prefix = f"vehicles/{user_id}/"
        
        blobs = list(bucket.list_blobs(prefix=prefix))
        deleted_count = 0
        for blob in blobs:
            try:
                blob.delete()
                deleted_count += 1
            except Exception as e:
                logging.warning(f"GCS画像の削除に失敗 ({blob.name}): {e}")
        
        logging.info(f"ユーザー {user_id} のGCS画像を {deleted_count}/{len(blobs)} 件削除しました。")
        return deleted_count
        
    except Exception as e:
        logging.warning(f"ユーザー {user_id} のGCS画像一括削除中にエラー: {e}")
        return 0
