# motopuppu/utils/image_security.py
import io
import logging
from PIL import Image, ImageOps

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
