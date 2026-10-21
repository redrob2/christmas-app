from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, send_from_directory, jsonify
from flask_login import login_required, current_user
from datetime import datetime
from werkzeug.utils import secure_filename
import os
import uuid
from app import db
from app.models import User, HOLIDAY_ICONS

profile_bp = Blueprint('profile', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@profile_bp.route('/')
@login_required
def view_profile():
    """View current user's profile"""
    return render_template('profile/view.html', user=current_user)


@profile_bp.route('/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    """Edit current user's profile"""
    if request.method == 'POST':
        # Update basic info
        current_user.name = request.form.get('name', '').strip()
        
        new_email = request.form.get('email', '').lower().strip()
        if new_email != current_user.email:
            # Check if email is already taken
            existing = User.query.filter_by(email=new_email).first()
            if existing:
                flash('That email is already in use.', 'danger')
                return render_template('profile/edit.html', user=current_user, holiday_icons=HOLIDAY_ICONS)
            current_user.email = new_email
        
        
        # Update profile fields
        birthday_str = request.form.get('birthday', '')
        if birthday_str:
            try:
                current_user.birthday = datetime.strptime(birthday_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        else:
            current_user.birthday = None
        
        current_user.address = request.form.get('address', '').strip() or None
        current_user.about_me = request.form.get('about_me', '').strip() or None
        
        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('profile.view_profile'))
    
    return render_template('profile/edit.html', user=current_user, holiday_icons=HOLIDAY_ICONS)


@profile_bp.route('/upload-photo', methods=['POST'])
@login_required
def upload_photo():
    """Upload a photo and transform it with Gemini AI"""
    print("=== Starting photo upload ===")
    
    if 'photo' not in request.files:
        flash('No photo selected.', 'danger')
        return redirect(url_for('profile.edit_profile'))
    
    file = request.files['photo']
    
    if file.filename == '':
        flash('No photo selected.', 'danger')
        return redirect(url_for('profile.edit_profile'))
    
    if not allowed_file(file.filename):
        flash('Invalid file type. Please upload a PNG, JPG, GIF, or WebP image.', 'danger')
        return redirect(url_for('profile.edit_profile'))
    
    try:
        upload_folder = current_app.config.get('UPLOAD_FOLDER', '/app/data/uploads')
        print(f"Upload folder: {upload_folder}")
        os.makedirs(upload_folder, exist_ok=True)
        
        # Save original photo
        ext = file.filename.rsplit('.', 1)[1].lower()
        unique_id = str(uuid.uuid4())[:8]
        original_filename = f"original_{current_user.id}_{unique_id}.{ext}"
        original_path = os.path.join(upload_folder, original_filename)
        print(f"Saving original to: {original_path}")
        file.save(original_path)
        print("Original photo saved successfully")
        
        # Delete old photos if they exist
        try:
            if current_user.profile_photo:
                old_path = os.path.join(upload_folder, current_user.profile_photo)
                if os.path.exists(old_path):
                    os.remove(old_path)
            if current_user.profile_photo_ai:
                old_path = os.path.join(upload_folder, current_user.profile_photo_ai)
                if os.path.exists(old_path):
                    os.remove(old_path)
            if current_user.profile_photo_icon:
                old_path = os.path.join(upload_folder, current_user.profile_photo_icon)
                if os.path.exists(old_path):
                    os.remove(old_path)
        except Exception as e:
            print(f"Warning: Could not delete old photos: {e}")
        
        # Update user with original photo
        current_user.profile_photo = original_filename
        db.session.commit()
        print("Database updated with original photo")
        
        # Transform with Gemini AI
        print("Starting Gemini AI transformation...")
        from app.gemini_service import process_profile_photo
        
        ai_full, ai_icon = process_profile_photo(original_path, upload_folder)
        
        if ai_full and ai_icon:
            print(f"AI transformation successful: {ai_full}, {ai_icon}")
            current_user.profile_photo_ai = ai_full
            current_user.profile_photo_icon = ai_icon
            db.session.commit()
            flash('Your photo has been transformed into a Rudolph-style character! 🦌', 'success')
        else:
            print("AI transformation returned None")
            flash('Photo saved, but AI transformation failed. Check server logs for details.', 'warning')
        
        return redirect(url_for('profile.view_profile'))
        
    except Exception as e:
        print(f"Photo upload error: {e}")
        import traceback
        traceback.print_exc()
        flash(f'Error uploading photo: {str(e)}', 'danger')
        return redirect(url_for('profile.edit_profile'))


@profile_bp.route('/regenerate-ai-photo', methods=['POST'])
@login_required
def regenerate_ai_photo():
    """Regenerate the AI photo from the existing uploaded photo"""
    if not current_user.profile_photo:
        flash('No photo uploaded yet. Please upload a photo first.', 'danger')
        return redirect(url_for('profile.edit_profile'))
    
    try:
        upload_folder = current_app.config.get('UPLOAD_FOLDER', '/app/data/uploads')
        original_path = os.path.join(upload_folder, current_user.profile_photo)
        
        if not os.path.exists(original_path):
            flash('Original photo not found. Please upload a new photo.', 'danger')
            return redirect(url_for('profile.edit_profile'))
        
        # Delete old AI photos
        if current_user.profile_photo_ai:
            old_path = os.path.join(upload_folder, current_user.profile_photo_ai)
            if os.path.exists(old_path):
                os.remove(old_path)
        if current_user.profile_photo_icon:
            old_path = os.path.join(upload_folder, current_user.profile_photo_icon)
            if os.path.exists(old_path):
                os.remove(old_path)
        
        # Transform with Gemini AI
        from app.gemini_service import process_profile_photo
        
        flash('Regenerating your Rudolph character... 🎄', 'info')
        
        ai_full, ai_icon = process_profile_photo(original_path, upload_folder)
        
        if ai_full and ai_icon:
            current_user.profile_photo_ai = ai_full
            current_user.profile_photo_icon = ai_icon
            db.session.commit()
            flash('New character generated! 🦌', 'success')
        else:
            flash('AI transformation failed. Please try again later.', 'warning')
        
        return redirect(url_for('profile.view_profile'))
        
    except Exception as e:
        print(f"Regeneration error: {e}")
        flash(f'Error regenerating photo: {str(e)}', 'danger')
        return redirect(url_for('profile.edit_profile'))


@profile_bp.route('/remove-photo', methods=['POST'])
@login_required
def remove_photo():
    """Remove the user's profile photo and AI-generated images"""
    try:
        upload_folder = current_app.config.get('UPLOAD_FOLDER', '/app/data/uploads')
        
        # Delete all photo files
        for photo_field in [current_user.profile_photo, current_user.profile_photo_ai, current_user.profile_photo_icon]:
            if photo_field:
                path = os.path.join(upload_folder, photo_field)
                if os.path.exists(path):
                    os.remove(path)
        
        # Clear database fields
        current_user.profile_photo = None
        current_user.profile_photo_ai = None
        current_user.profile_photo_icon = None
        db.session.commit()
        
        flash('Profile photo removed - your initials are shown instead.', 'success')
        
    except Exception as e:
        print(f"Remove photo error: {e}")
        flash(f'Error removing photo: {str(e)}', 'danger')
    
    return redirect(url_for('profile.edit_profile'))


@profile_bp.route('/user/<int:user_id>')
@login_required
def view_user_profile(user_id):
    """View another user's profile"""
    user = User.query.get_or_404(user_id)
    return render_template('profile/view.html', user=user, viewing_other=True)


# Serve uploaded files (for wishlist item images and profile photos)
@profile_bp.route('/uploads/<path:filename>')
@login_required
def uploaded_file(filename):
    """Serve uploaded files"""
    upload_folder = current_app.config.get('UPLOAD_FOLDER', '/app/data/uploads')
    return send_from_directory(upload_folder, filename)


@profile_bp.route('/test-gemini-api')
@login_required
def test_gemini_api():
    """Test if Gemini API is accessible (admin only)"""
    import requests
    
    if not current_user.is_admin:
        return jsonify({'status': 'error', 'message': 'Admin access required'}), 403
    
    api_key = current_app.config.get('GEMINI_API_KEY')
    
    if not api_key:
        return jsonify({
            'status': 'error',
            'message': 'GEMINI_API_KEY not configured'
        })
    
    # Test with a simple text generation (no image)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{current_app.config['GEMINI_TEXT_MODEL']}:generateContent"
    
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key
    }
    
    payload = {
        "contents": [{
            "parts": [{"text": "Say hello"}]
        }]
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        
        return jsonify({
            'status': 'success' if response.status_code == 200 else 'error',
            'http_code': response.status_code,
            'model': current_app.config['GEMINI_TEXT_MODEL'],
            'response': response.json() if response.status_code == 200 else response.text
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        })
