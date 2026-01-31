
import os
import json
import google.generativeai as genai
from flask import current_app

def parse_receipt_image(image_bytes, mime_type='image/jpeg'):
    """
    Parses a receipt image using Google Gemini API.

    Args:
        image_bytes (bytes): The raw bytes of the image file.
        mime_type (str): The MIME type of the image (e.g., 'image/jpeg', 'image/png').

    Returns:
        dict: A dictionary containing extracted data or error information.
              {
                  'success': bool,
                  'data': {
                      'date': 'YYYY-MM-DD',
                      'time': 'HH:MM',
                      'volume': float,
                      'price_per_unit': float,
                      'total_cost': int,
                      'station': str,
                      'fuel_type': str
                  },
                  'error': str (optional)
              }
    """
    api_key = current_app.config.get('GEMINI_API_KEY') or os.environ.get('GEMINI_API_KEY')
    
    if not api_key:
        return {'success': False, 'error': 'API key is not configured.'}

    try:
        genai.configure(api_key=api_key)
        
        # Use a model that supports vision, e.g., gemini-2.5-flash
        model = genai.GenerativeModel('gemini-2.5-flash')

        prompt = """
        あなたはガソリンスタンドのレシートを読み取るOCRアシスタントです。
        画像を解析し、以下の情報を正確に抽出してJSON形式で返してください。

        【抽出ルール】
        - date (文字列): "YYYY-MM-DD"形式。和暦（例: R6.01.01）の場合は西暦（例: 2024-01-01）に変換してください。「2025/12/13(土)」の場合は「2025-12-13」に変換してください。
        - time (文字列): "HH:MM"形式（24時間表記）。慣例として、日付の横にあることが多いです（例: 2025/12/13(土）11:25) この例の場合は、「11:25」を抽出してください。
        - volume (数値): 給油量（リッター数）。"数量"などの列にあることが多いです。表記として「10.00L」のようにLがついていることが多いです。この場合は、「10.00」を抽出してください。
        - price_per_unit (数値): リッター単価。「@149.0」のように@がついていることが多く、この例の場合は「149.0」を抽出してください。
        - total_cost (数値): 合計金額（支払金額）。「合計」などと記載されていることが多いです。
        - station (文字列): ガソリンスタンドのブランド名や店名（例: ENEOS, シェル, 出光など）。
        - fuel_type (文字列): 油種。以下のいずれかの文字列に正規化してください。
            - "ハイオク" (または "High Octane", "Premium") -> "ハイオク"
            - "レギュラー" (または "Regular") -> "レギュラー"
            - "軽油" (または "Diesel") -> "軽油"

        もし項目が見つからない、または判読不能な場合は null をセットしてください。
        JSONオブジェクトのみを返してください（Markdownのコードブロックは不要です）。
        """

        # Create the content part for the image
        image_part = {
            "mime_type": mime_type,
            "data": image_bytes
        }

        response = model.generate_content([prompt, image_part])
        
        # Extract text from response
        response_text = response.text.strip()
        
        # Clean up code blocks if present (Gemini sometimes adds ```json ... ```)
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
            
        parsed_data = json.loads(response_text.strip())
        
        return {'success': True, 'data': parsed_data}

    except Exception as e:
        current_app.logger.error(f"Gemini API Error: {str(e)}")
        return {'success': False, 'error': f"Failed to process image: {str(e)}"}
