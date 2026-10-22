"""
Gemini AI Service for Profile Photo Transformation
Transforms user photos into Rudolph the Red-Nosed Reindeer style characters
Using Gemini 3 Pro Image (Nano Banana Pro) for highest quality output
"""

import os
import base64
import requests
from PIL import Image
from io import BytesIO
import uuid
from flask import current_app
import traceback


# The transformation prompt
RUDOLPH_PROMPT = """Turn the person in the image into a character that might have been in the stop motion show Rudolph the Red-Nosed Reindeer. Make the image 500x500. Use the same style and textures as was in that show and only show their face and down to their mid-upper chest. They don't need to be extremely detailed as that style was not that way. Keep them relatively simple and cute. Don't limit making the person into a person character as there were many other types of characters (animals, toys, abominables, etc. in that movie). If there is no person, make up a random character."""


def get_gemini_api_key():
    """The Gemini API key from the settings (already cleaned of stray spaces and quotes)"""
    key = current_app.config.get('GEMINI_API_KEY')
    if not key:
        print("[GEMINI] ERROR: No API key found!")
    return key


def get_model_url(config_key):
    """Build the generateContent URL for the model named in config"""
    model = current_app.config[config_key]
    return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def transform_photo_with_gemini_pro(image_path, upload_folder):
    """
    Transform a user photo using Gemini 3 Pro Image (Nano Banana Pro)
    This is the highest quality model for image generation and editing.

    Args:
        image_path: Path to the uploaded image
        upload_folder: Folder to save the transformed images

    Returns:
        tuple: (ai_full_path, ai_icon_path) - paths to the transformed images
               or (None, None) if transformation failed
    """
    print(f"[GEMINI] Starting transform_photo_with_gemini_pro")
    print(f"[GEMINI] Image path: {image_path}")
    print(f"[GEMINI] Upload folder: {upload_folder}")

    api_key = get_gemini_api_key()
    if not api_key:
        print("[GEMINI] ERROR: Gemini API key not configured")
        return None, None

    # Check if image file exists
    if not os.path.exists(image_path):
        print(f"[GEMINI] ERROR: Image file not found at {image_path}")
        return None, None

    try:
        # Read and encode the image
        print(f"[GEMINI] Reading image file...")
        with open(image_path, 'rb') as f:
            image_data = f.read()
        print(f"[GEMINI] Image size: {len(image_data)} bytes")

        # Determine mime type
        image_path_lower = image_path.lower()
        if image_path_lower.endswith('.png'):
            mime_type = 'image/png'
        elif image_path_lower.endswith('.gif'):
            mime_type = 'image/gif'
        elif image_path_lower.endswith('.webp'):
            mime_type = 'image/webp'
        else:
            mime_type = 'image/jpeg'
        print(f"[GEMINI] MIME type: {mime_type}")

        image_base64 = base64.b64encode(image_data).decode('utf-8')
        print(f"[GEMINI] Base64 encoded length: {len(image_base64)}")

        # Call the Gemini API with Gemini 3 Pro Image (Nano Banana Pro)
        url = get_model_url('GEMINI_IMAGE_MODEL')
        print(f"[GEMINI] API URL: {url}")

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key
        }

        payload = {
            "contents": [{
                "parts": [
                    {"text": RUDOLPH_PROMPT},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": image_base64
                        }
                    }
                ]
            }],
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"]
            }
        }

        print("[GEMINI] Calling Gemini 3 Pro Image API...")
        print(f"[GEMINI] Prompt length: {len(RUDOLPH_PROMPT)} chars")

        response = requests.post(url, headers=headers, json=payload, timeout=180)

        print(f"[GEMINI] Response status code: {response.status_code}")

        if response.status_code != 200:
            print(f"[GEMINI] ERROR: API returned non-200 status")
            print(f"[GEMINI] Response body: {response.text[:2000]}")
            return None, None

        result = response.json()
        print(f"[GEMINI] Response JSON keys: {result.keys()}")

        # Extract the generated image from the response
        generated_image_data = None

        if 'candidates' in result and len(result['candidates']) > 0:
            print(f"[GEMINI] Found {len(result['candidates'])} candidates")
            candidate = result['candidates'][0]
            print(f"[GEMINI] Candidate keys: {candidate.keys()}")

            if 'content' in candidate and 'parts' in candidate['content']:
                parts = candidate['content']['parts']
                print(f"[GEMINI] Found {len(parts)} parts in response")

                for i, part in enumerate(parts):
                    print(f"[GEMINI] Part {i} keys: {part.keys()}")
                    if 'inlineData' in part:
                        generated_image_data = part['inlineData'].get('data')
                        print(f"[GEMINI] Found inlineData in part {i}, data length: {len(generated_image_data) if generated_image_data else 0}")
                        break
                    elif 'text' in part:
                        print(f"[GEMINI] Part {i} text: {part['text'][:200]}...")
        else:
            print(f"[GEMINI] No candidates in response")
            print(f"[GEMINI] Full response: {str(result)[:2000]}")

        if not generated_image_data:
            print("[GEMINI] ERROR: No image generated in response")
            return None, None

        # Decode the generated image
        print("[GEMINI] Decoding generated image...")
        image_bytes = base64.b64decode(generated_image_data)
        generated_image = Image.open(BytesIO(image_bytes))
        print(f"[GEMINI] Generated image size: {generated_image.size}")

        # Generate unique filenames
        unique_id = str(uuid.uuid4())[:8]
        ai_full_filename = f"ai_full_{unique_id}.png"
        ai_icon_filename = f"ai_icon_{unique_id}.png"

        ai_full_path = os.path.join(upload_folder, ai_full_filename)
        ai_icon_path = os.path.join(upload_folder, ai_icon_filename)

        # Ensure the image is 500x500 for full size
        if generated_image.size != (500, 500):
            print(f"[GEMINI] Resizing from {generated_image.size} to 500x500")
            generated_image = generated_image.resize((500, 500), Image.Resampling.LANCZOS)

        # Save the full-size AI image
        print(f"[GEMINI] Saving full image to: {ai_full_path}")
        generated_image.save(ai_full_path, 'PNG', quality=95)

        # Create and save the icon (64x64 for small displays)
        print(f"[GEMINI] Saving icon to: {ai_icon_path}")
        icon_image = generated_image.resize((64, 64), Image.Resampling.LANCZOS)
        icon_image.save(ai_icon_path, 'PNG', quality=95)

        print(f"[GEMINI] SUCCESS! Generated: {ai_full_filename}")
        return ai_full_filename, ai_icon_filename

    except requests.exceptions.Timeout:
        print("[GEMINI] ERROR: API request timed out after 180 seconds")
        return None, None
    except requests.exceptions.RequestException as e:
        print(f"[GEMINI] ERROR: Request exception: {e}")
        traceback.print_exc()
        return None, None
    except Exception as e:
        print(f"[GEMINI] ERROR: Unexpected exception: {e}")
        traceback.print_exc()
        return None, None


def transform_photo_with_gemini_flash(image_path, upload_folder):
    """
    Fallback method using the GEMINI_IMAGE_FALLBACK_MODEL (a Flash image model)
    Used if the Pro model fails or is unavailable
    """
    print(f"[GEMINI-FLASH] Starting fallback with Flash model")

    api_key = get_gemini_api_key()
    if not api_key:
        print("[GEMINI-FLASH] ERROR: Gemini API key not configured")
        return None, None

    if not os.path.exists(image_path):
        print(f"[GEMINI-FLASH] ERROR: Image file not found at {image_path}")
        return None, None

    try:
        # Read and encode the image
        with open(image_path, 'rb') as f:
            image_data = f.read()
        print(f"[GEMINI-FLASH] Image size: {len(image_data)} bytes")

        # Determine mime type
        image_path_lower = image_path.lower()
        if image_path_lower.endswith('.png'):
            mime_type = 'image/png'
        elif image_path_lower.endswith('.gif'):
            mime_type = 'image/gif'
        elif image_path_lower.endswith('.webp'):
            mime_type = 'image/webp'
        else:
            mime_type = 'image/jpeg'

        image_base64 = base64.b64encode(image_data).decode('utf-8')

        # Fallback to Flash Image model
        url = get_model_url('GEMINI_IMAGE_FALLBACK_MODEL')
        print(f"[GEMINI-FLASH] API URL: {url}")

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key
        }

        payload = {
            "contents": [{
                "parts": [
                    {"text": RUDOLPH_PROMPT},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": image_base64
                        }
                    }
                ]
            }],
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"]
            }
        }

        print("[GEMINI-FLASH] Calling API...")
        response = requests.post(url, headers=headers, json=payload, timeout=120)

        print(f"[GEMINI-FLASH] Response status: {response.status_code}")

        if response.status_code != 200:
            print(f"[GEMINI-FLASH] ERROR: {response.status_code}")
            print(f"[GEMINI-FLASH] Response: {response.text[:2000]}")
            return None, None

        result = response.json()
        print(f"[GEMINI-FLASH] Response keys: {result.keys()}")

        # Extract the generated image
        generated_image_data = None

        if 'candidates' in result and len(result['candidates']) > 0:
            candidate = result['candidates'][0]
            if 'content' in candidate and 'parts' in candidate['content']:
                for part in candidate['content']['parts']:
                    if 'inlineData' in part:
                        generated_image_data = part['inlineData'].get('data')
                        break

        if not generated_image_data:
            print("[GEMINI-FLASH] ERROR: No image in response")
            print(f"[GEMINI-FLASH] Full response: {str(result)[:2000]}")
            return None, None

        # Decode and process
        image_bytes = base64.b64decode(generated_image_data)
        generated_image = Image.open(BytesIO(image_bytes))

        unique_id = str(uuid.uuid4())[:8]
        ai_full_filename = f"ai_full_{unique_id}.png"
        ai_icon_filename = f"ai_icon_{unique_id}.png"

        ai_full_path = os.path.join(upload_folder, ai_full_filename)
        ai_icon_path = os.path.join(upload_folder, ai_icon_filename)

        # Resize to 500x500 if needed
        if generated_image.size != (500, 500):
            generated_image = generated_image.resize((500, 500), Image.Resampling.LANCZOS)

        generated_image.save(ai_full_path, 'PNG', quality=95)

        # Create icon
        icon_image = generated_image.resize((64, 64), Image.Resampling.LANCZOS)
        icon_image.save(ai_icon_path, 'PNG', quality=95)

        print(f"[GEMINI-FLASH] SUCCESS! Generated: {ai_full_filename}")
        return ai_full_filename, ai_icon_filename

    except Exception as e:
        print(f"[GEMINI-FLASH] ERROR: {e}")
        traceback.print_exc()
        return None, None


def process_profile_photo(image_path, upload_folder):
    """
    Main entry point for processing a profile photo
    Uses Gemini 3 Pro Image (Nano Banana Pro) as primary model
    Falls back to Gemini 2.5 Flash Image if Pro fails
    """
    print("=" * 60)
    print("[GEMINI] STARTING PROFILE PHOTO PROCESSING")
    print("=" * 60)

    # Try the Pro model first (highest quality)
    result = transform_photo_with_gemini_pro(image_path, upload_folder)

    if result[0] is None:
        # Try the Flash model as fallback
        print("[GEMINI] Pro model failed, trying Flash fallback...")
        result = transform_photo_with_gemini_flash(image_path, upload_folder)

    if result[0] is None:
        print("[GEMINI] ALL MODELS FAILED")
    else:
        print(f"[GEMINI] FINAL SUCCESS: {result}")

    print("=" * 60)
    return result


def generate_gift_poem(item_name, item_color, item_notes, recipient_name, recipient_about):
    """
    Generate a cryptic poem about a gift using Gemini API.

    Args:
        item_name: Name of the gift item
        item_color: Color of the item (optional)
        item_notes: Additional notes about the item (optional)
        recipient_name: Name of the person receiving the gift
        recipient_about: Description/interests of the recipient

    Returns:
        (poem, error): the poem, or None plus a message for the person
    """
    print("=" * 60)
    print("[GEMINI-POEM] STARTING POEM GENERATION")
    print("=" * 60)

    api_key = get_gemini_api_key()
    if not api_key:
        print("[GEMINI-POEM] ERROR: No API key found")
        return None, 'Gift poems need a Gemini API key - ask the organizer to add one.'

    # Build the prompt
    prompt = f"""My family is playing a gift giving game. The gifts are all wrapped and have a poem (roughly 10-20 lines max or so). The poems are supposed to give very cryptic hints what the gift might be and who it might be for. Write this poem. Here are some details. Only reply with the poem and no additional text. The poem should not give away who the recipient is. This is a secret.

Item name: {item_name}
Color: {item_color or 'N/A'}
Gift Additional Notes: {item_notes or 'N/A'}
Recipient: {recipient_name}
About recipient: {recipient_about or 'No additional information provided'}"""

    print(f"[GEMINI-POEM] Prompt:\n{prompt[:500]}...")

    try:
        # Use Gemini Flash for text generation (faster and cheaper)
        url = get_model_url('GEMINI_TEXT_MODEL')

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key
        }

        # Newer Gemini models "think" before answering, and that thinking counts toward
        # maxOutputTokens - a small limit leaves no room for the poem itself. Allow plenty,
        # and ask for brief thinking (a poem doesn't need much).
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": 0.9,
                "maxOutputTokens": 8192,
                "thinkingConfig": {"thinkingLevel": "low"}
            }
        }

        print("[GEMINI-POEM] Calling Gemini API...")
        response = requests.post(url, headers=headers, json=payload, timeout=90)
        if response.status_code == 400 and 'thinking' in response.text.lower():
            # an older model (set in GEMINI_TEXT_MODEL) that doesn't take thinkingLevel
            payload['generationConfig'].pop('thinkingConfig')
            response = requests.post(url, headers=headers, json=payload, timeout=90)

        print(f"[GEMINI-POEM] Response status: {response.status_code}")

        if response.status_code != 200:
            print(f"[GEMINI-POEM] ERROR: {response.text[:1000]}")
            if response.status_code in (402, 429):
                return None, ('The Gemini account is out of credit or over its limit right now - '
                              'ask the organizer to check it, or try again later.')
            if response.status_code in (401, 403) or 'api key not valid' in response.text.lower():
                return None, 'The Gemini API key was refused - ask the organizer to check it.'
            if response.status_code == 404:
                return None, 'The Gemini model in the settings no longer exists - ask the organizer to update GEMINI_TEXT_MODEL.'
            return None, 'Gemini had a problem writing the poem. Please try again in a moment.'

        result = response.json()
        candidate = (result.get('candidates') or [{}])[0]
        finish = candidate.get('finishReason')
        # only the answer itself - never the model's "thought" parts
        poem = ''.join(part.get('text', '') for part in (candidate.get('content') or {}).get('parts', [])
                       if not part.get('thought')).strip()

        if finish == 'STOP' and poem:
            print(f"[GEMINI-POEM] SUCCESS! Generated poem:\n{poem}")
            return poem, None

        print(f"[GEMINI-POEM] ERROR: finishReason={finish}, text={poem[:200]!r}")
        print(f"[GEMINI-POEM] Response: {str(result)[:1000]}")
        if finish in ('SAFETY', 'PROHIBITED_CONTENT', 'BLOCKLIST', 'RECITATION'):
            return None, "Gemini wouldn't write a poem for this gift - try editing the item's notes."
        # a cut-off poem (MAX_TOKENS) or an empty answer is never saved
        return None, 'The poem came back incomplete. Please try again.'

    except requests.exceptions.Timeout:
        print("[GEMINI-POEM] ERROR: Request timed out")
        return None, 'Gemini took too long to answer. Please try again.'
    except Exception as e:
        print(f"[GEMINI-POEM] ERROR: {e}")
        traceback.print_exc()
        return None, 'Something went wrong writing the poem. Please try again.'
