
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
        You are an OCR assistant for gas station receipts.
        Analyze the image and extract the following information into a JSON format:
        
        - date: The date of the transaction in YYYY-MM-DD format.
        - time: The time of the transaction in HH:MM format (24-hour).
        - volume: The fuel volume in liters (float).
        - price_per_unit: The price per liter (float).
        - total_cost: The total cost (integer).
        - station: The name of the gas station (string).
        - fuel_type: The type of fuel (e.g., "Regular", "High Octane", "Diesel") if available.

        If any field is missing or illegible, set it to null.
        Return ONLY the JSON object, no code blocks or markdown.
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
