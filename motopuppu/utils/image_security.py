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


def process_and_upload_image(file_storage, max_size=(1200, 1200)):
    """
    アップロードされた画像（FileStorageなど）を開き、セキュリティチェック、
    リサイズ（最大1200px）、EXIF削除、WebP変換（軽量化）を行った上で
    Google Cloud Storage (GCS) にアップロードし、その公開パスURLを返します。
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
        
        # UUIDで一意なファイル名(キー)を生成
        unique_filename = f"vehicles/{uuid.uuid4().hex}.webp"
        blob = bucket.blob(unique_filename)
        
        # 一時ストリームからファイルをアップロード
        blob.upload_from_file(output_stream, content_type='image/webp')
        
        # 外部公開可能なURLを生成して返す (デフォルトのstorage.googleapis.comとする)
        return f"https://storage.googleapis.com/{bucket_name}/{unique_filename}"
        
    except Exception as e:
        logging.error(f"Error processing and uploading image: {e}", exc_info=True)
        raise ValueError("画像の処理またはアップロード時にエラーが発生しました。ファイルが破損しているか未対応の形式です。")
