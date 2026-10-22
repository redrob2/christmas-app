from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify, session
from flask_login import login_required, current_user
from datetime import datetime
from collections import OrderedDict
import os
import shutil
import uuid
from app import db, mail
from app.models import (WishList, WishListItem, ItemPurchase, EventParticipant, GiftContribution,
                        SecretSantaAssignment, ChristmasEvent, PURCHASE_STATUSES)
from app.push import link_path, send_push
from app.utils import get_external_url, is_cash_request, parse_money, safe_url
from flask_mail import Message

wishlist_bp = Blueprint('wishlist', __name__)

PRIORITY_LABELS = {0: 'Normal', 1: 'Would Like', 2: 'Really Want', 3: 'Top of List!'}


def allowed_file(filename):
    """Check if file extension is allowed"""
    allowed = current_app.config.get('ALLOWED_EXTENSIONS', {'png', 'jpg', 'jpeg', 'gif', 'webp'})
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed


def save_uploaded_file(file, subfolder):
    """Save uploaded file and return the filename"""
    if file and allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f"{uuid.uuid4().hex}.{ext}"

        upload_folder = current_app.config.get('UPLOAD_FOLDER', '/app/data/uploads')
        folder_path = os.path.join(upload_folder, subfolder)
        os.makedirs(folder_path, exist_ok=True)

        file_path = os.path.join(folder_path, filename)
        file.save(file_path)

        return f"{subfolder}/{filename}"
    return None


def save_image_from_link(image_url):
    """Download the picture the link reader suggested (same safety limits as the
    page fetch). Returns the stored path, or None with a warning flashed."""
    from app.link_preview import LinkError, download_image
    try:
        data, ext = download_image(image_url)
    except LinkError as e:
        flash(f'Item saved, but its picture could not be added: {e}', 'warning')
        return None
    upload_folder = current_app.config.get('UPLOAD_FOLDER', '/app/data/uploads')
    os.makedirs(os.path.join(upload_folder, 'items'), exist_ok=True)
    path = f"items/{uuid.uuid4().hex}.{ext}"
    with open(os.path.join(upload_folder, path), 'wb') as f:
        f.write(data)
    return path


def copy_uploaded_file(filepath):
    """Duplicate an uploaded file (so copied items don't share one image)"""
    if not filepath:
        return None
    upload_folder = current_app.config.get('UPLOAD_FOLDER', '/app/data/uploads')
    source = os.path.join(upload_folder, filepath)
    if not os.path.exists(source):
        return None
    subfolder = os.path.dirname(filepath)
    new_path = f"{subfolder}/{uuid.uuid4().hex}{os.path.splitext(filepath)[1]}"
    shutil.copyfile(source, os.path.join(upload_folder, new_path))
    return new_path


def delete_uploaded_file(filepath):
    """Delete an uploaded file"""
    if filepath:
        upload_folder = current_app.config.get('UPLOAD_FOLDER', '/app/data/uploads')
        full_path = os.path.join(upload_folder, filepath)
        if os.path.exists(full_path):
            os.remove(full_path)


def is_participant(event_id):
    return EventParticipant.query.filter_by(event_id=event_id, user_id=current_user.id).first() is not None


def can_edit_list(wishlist, user=None):
    """Your own list, or the list of someone with no login (e.g. a child) you look after"""
    user = user or current_user
    owner = wishlist.owner
    return owner.id == user.id or (owner.is_managed and owner.managed_by_id == user.id)


def is_my_santa_pick(wishlist):
    """Did the current user draw this wishlist's owner in an event with Secret Santa on?"""
    return (wishlist.event.secret_santa_enabled and SecretSantaAssignment.query.filter_by(
        event_id=wishlist.event_id, giver_id=current_user.id, receiver_id=wishlist.owner_id).first() is not None)


def read_item_form(item):
    """Copy the add/edit form fields onto an item"""
    item.name = request.form.get('name', '').strip()
    item.url = safe_url(request.form.get('url'))
    item.color = request.form.get('color', '').strip() or None
    item.size = request.form.get('size', '').strip() or None
    item.notes = request.form.get('notes', '').strip() or None
    item.price = parse_money(request.form.get('price'))
    item.priority = request.form.get('priority', 0, type=int) or 0
    if request.form.get('url', '').strip() and not item.url:
        flash('That link was ignored - only http(s) links are allowed.', 'warning')


@wishlist_bp.route('/<int:wishlist_id>')
@login_required
def view_wishlist(wishlist_id):
    """View a wishlist - different views for owner vs others"""
    wishlist = WishList.query.get_or_404(wishlist_id)

    can_edit = can_edit_list(wishlist)
    if not is_participant(wishlist.event_id) and not current_user.is_admin and not can_edit:
        flash('You do not have access to this wishlist.', 'danger')
        return redirect(url_for('main.dashboard'))

    is_owner = wishlist.owner_id == current_user.id
    items = wishlist.items.order_by(WishListItem.priority.desc(), WishListItem.created_at).all()

    # For non-owners, include purchase and group-gift info
    items_with_purchases = []
    for item in items:
        item_data = {
            'item': item,
            'purchased': item.purchase is not None,
            'purchased_by': None,
            'purchased_by_me': False,
            'contributions': [],
            'my_contribution': None,
        }
        if not is_owner:
            if item.purchase:
                item_data['purchased_by'] = item.purchase.purchaser
                item_data['purchased_by_me'] = item.purchase.purchaser_id == current_user.id
            item_data['contributions'] = item.contributions
            item_data['my_contribution'] = next(
                (c for c in item.contributions if c.user_id == current_user.id), None)
        items_with_purchases.append(item_data)

    # Owner: other lists they could copy unpurchased items from
    copy_sources = []
    if can_edit:
        for other in WishList.query.filter(WishList.owner_id == wishlist.owner_id,
                                           WishList.id != wishlist.id).all():
            count = sum(1 for i in other.items if i.purchase is None)
            if count:
                copy_sources.append({'wishlist': other, 'count': count})
        copy_sources.sort(key=lambda s: (s['wishlist'].event.year, s['wishlist'].event_id), reverse=True)

    # Is the viewer this person's Secret Santa? (to show the budget)
    santa_assignment = None
    if not is_owner and wishlist.event.secret_santa_enabled:
        santa_assignment = SecretSantaAssignment.query.filter_by(
            event_id=wishlist.event_id, giver_id=current_user.id, receiver_id=wishlist.owner_id).first()

    return render_template('wishlist/view.html',
                          wishlist=wishlist,
                          items=items_with_purchases,
                          is_owner=is_owner,
                          can_edit=can_edit,
                          locked=wishlist.event.lists_locked(),
                          copy_sources=copy_sources,
                          santa_assignment=santa_assignment,
                          priority_labels=PRIORITY_LABELS)


@wishlist_bp.route('/<int:wishlist_id>/add', methods=['GET', 'POST'])
@login_required
def add_item(wishlist_id):
    """Add an item to your wishlist"""
    wishlist = WishList.query.get_or_404(wishlist_id)

    # Only the owner (or whoever looks after a managed list) can add items
    if not can_edit_list(wishlist):
        flash('You can only add items to your own wishlist.', 'danger')
        return redirect(url_for('wishlist.view_wishlist', wishlist_id=wishlist_id))
    if wishlist.event.lists_locked():
        flash(f'Wishlists for {wishlist.event.name} are locked - ask the organizer if something needs to change.', 'warning')
        return redirect(url_for('wishlist.view_wishlist', wishlist_id=wishlist.id))

    if request.method == 'POST':
        item = WishListItem(wishlist_id=wishlist_id)
        read_item_form(item)

        if not item.name:
            flash('Item name is required.', 'danger')
            return render_template('wishlist/add_item.html', wishlist=wishlist)

        # An uploaded photo wins; otherwise use the picture found from the link
        file = request.files.get('image')
        if file and file.filename:
            item.image = save_uploaded_file(file, 'items')
            if not item.image:
                flash('Invalid image type. Please upload a valid image.', 'warning')
        elif request.form.get('image_url'):
            item.image = save_image_from_link(request.form['image_url'])

        db.session.add(item)
        db.session.commit()

        if is_cash_request(item.name):
            session['money_rain'] = True
            flash(f'"{item.name}" added to your wishlist! 💸 Bold choice. Small bills preferred.', 'success')
        else:
            flash(f'"{item.name}" added to your wishlist!', 'success')
        if request.form.get('add_another'):
            return redirect(url_for('wishlist.add_item', wishlist_id=wishlist_id))
        return redirect(url_for('wishlist.view_wishlist', wishlist_id=wishlist_id))

    return render_template('wishlist/add_item.html', wishlist=wishlist)


@wishlist_bp.route('/link-preview', methods=['POST'])
@login_required
def link_preview():
    """Read a product link and suggest name/price/photo/color/size (JSON)"""
    from app.link_preview import LinkError, preview
    url = safe_url(request.form.get('url') or (request.get_json(silent=True) or {}).get('url'))
    if not url:
        return jsonify({'ok': False, 'message': 'Please paste a full web link.'}), 400
    try:
        result = preview(url)
    except LinkError as e:
        return jsonify({'ok': False, 'message': str(e)})
    except Exception as e:
        print(f"[link-preview] unexpected error for {url}: {e}", flush=True)
        return jsonify({'ok': False, 'message': "Couldn't read that link - please fill it in below."})
    fields = result['fields']
    if fields.get('price') is not None:
        fields['price'] = f"{fields['price']:.2f}"
    return jsonify({'ok': True, **result})


@wishlist_bp.route('/read-screenshot', methods=['POST'])
@login_required
def read_screenshot():
    """AI reads a product screenshot: suggests fields and crops out the product photo (JSON)"""
    import base64
    from app.link_preview import LinkError, read_screenshot as read
    file = request.files.get('image')
    if not file or not file.filename:
        return jsonify({'ok': False, 'message': 'No picture was sent.'}), 400
    try:
        result = read(file.read())
    except LinkError as e:
        return jsonify({'ok': False, 'message': str(e)})
    except Exception as e:
        print(f"[read-screenshot] unexpected error: {e}", flush=True)
        return jsonify({'ok': False, 'message': "Couldn't read that picture - please fill it in below."})
    fields = result['fields']
    if fields.get('price') is not None:
        fields['price'] = f"{fields['price']:.2f}"
    cropped = result['cropped']
    return jsonify({'ok': True, 'fields': fields,
                    'cropped': 'data:image/jpeg;base64,' + base64.b64encode(cropped).decode() if cropped else None})


@wishlist_bp.route('/item/<int:item_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_item(item_id):
    """Edit a wishlist item"""
    item = WishListItem.query.get_or_404(item_id)
    wishlist = item.wishlist

    # Only the owner (or whoever looks after a managed list) can edit items
    if not can_edit_list(wishlist):
        flash('You can only edit items on your own wishlist.', 'danger')
        return redirect(url_for('wishlist.view_wishlist', wishlist_id=wishlist.id))
    if wishlist.event.lists_locked():
        flash(f'Wishlists for {wishlist.event.name} are locked - ask the organizer if something needs to change.', 'warning')
        return redirect(url_for('wishlist.view_wishlist', wishlist_id=wishlist.id))

    if request.method == 'POST':
        old_name = item.name
        read_item_form(item)
        if not item.name:
            item.name = old_name
            flash('Item name is required.', 'danger')
            return render_template('wishlist/edit_item.html', item=item, wishlist=wishlist)

        # A new upload replaces the old image; "remove" only applies when no new one was chosen
        file = request.files.get('image')
        if file and file.filename:
            new_path = save_uploaded_file(file, 'items')
            if new_path:
                delete_uploaded_file(item.image)
                item.image = new_path
            else:
                flash('Invalid image type. Please upload a valid image.', 'warning')
        elif request.form.get('image_url'):
            new_path = save_image_from_link(request.form['image_url'])
            if new_path:
                delete_uploaded_file(item.image)
                item.image = new_path
        elif request.form.get('remove_image') == 'yes' and item.image:
            delete_uploaded_file(item.image)
            item.image = None

        item.updated_at = datetime.utcnow()
        db.session.commit()

        # Let everyone who bought or is chipping in on this item know it changed
        to_notify = {c.user for c in item.contributions}
        if item.purchase:
            to_notify.add(item.purchase.purchaser)
        item_url = get_external_url('wishlist.view_wishlist', wishlist_id=wishlist.id) + f'#item-{item.id}'
        for person in to_notify:
            try:
                msg = Message(f'🎁 Gift Item Updated - {item.name}', recipients=[person.email])
                msg.html = render_template('emails/item_updated.html',
                                          item=item,
                                          old_name=old_name,
                                          recipient=wishlist.owner,
                                          purchaser=person,
                                          item_url=item_url)
                mail.send(msg)
            except Exception as e:
                print(f"Email error: {e}")
        if to_notify:
            send_push(list(to_notify), f'✏️ {wishlist.owner.name.split()[0]} changed a gift you\'re getting',
                      f'"{item.name}" was updated - take a look at what changed.',
                      url=link_path(item_url), tag=f'item-{item.id}')

        if is_cash_request(item.name) and not is_cash_request(old_name):
            session['money_rain'] = True
            flash('Item updated! 💸 Ah, the classic.', 'success')
        else:
            flash('Item updated!', 'success')
        return redirect(url_for('wishlist.view_wishlist', wishlist_id=wishlist.id))

    return render_template('wishlist/edit_item.html', item=item, wishlist=wishlist)


@wishlist_bp.route('/item/<int:item_id>/delete', methods=['POST'])
@login_required
def delete_item(item_id):
    """Delete a wishlist item"""
    item = WishListItem.query.get_or_404(item_id)
    wishlist = item.wishlist

    # Only the owner (or whoever looks after a managed list) can delete items
    if not can_edit_list(wishlist):
        flash('You can only delete items from your own wishlist.', 'danger')
        return redirect(url_for('wishlist.view_wishlist', wishlist_id=wishlist.id))
    if wishlist.event.lists_locked():
        flash(f'Wishlists for {wishlist.event.name} are locked - ask the organizer if something needs to change.', 'warning')
        return redirect(url_for('wishlist.view_wishlist', wishlist_id=wishlist.id))

    name = item.name
    delete_uploaded_file(item.image)

    db.session.delete(item)
    db.session.commit()

    flash(f'"{name}" removed from your wishlist.', 'success')
    return redirect(url_for('wishlist.view_wishlist', wishlist_id=wishlist.id))


@wishlist_bp.route('/<int:wishlist_id>/copy-from', methods=['POST'])
@login_required
def copy_items(wishlist_id):
    """Copy the unpurchased items from one of your earlier lists into this one"""
    wishlist = WishList.query.get_or_404(wishlist_id)
    source = WishList.query.get_or_404(request.form.get('source_id', type=int) or 0)

    if not can_edit_list(wishlist) or source.owner_id != wishlist.owner_id:
        flash('You can only copy between your own wishlists.', 'danger')
        return redirect(url_for('wishlist.view_wishlist', wishlist_id=wishlist_id))
    if wishlist.event.lists_locked():
        flash(f'Wishlists for {wishlist.event.name} are locked - ask the organizer if something needs to change.', 'warning')
        return redirect(url_for('wishlist.view_wishlist', wishlist_id=wishlist.id))

    existing = {i.name.strip().lower() for i in wishlist.items}
    copied = 0
    for old in source.items:
        if old.purchase is not None or old.name.strip().lower() in existing:
            continue
        db.session.add(WishListItem(
            wishlist_id=wishlist.id, name=old.name, url=old.url, color=old.color, size=old.size,
            notes=old.notes, price=old.price, priority=old.priority,
            image=copy_uploaded_file(old.image)))
        copied += 1
    db.session.commit()

    if copied:
        flash(f'Copied {copied} item{"s" if copied != 1 else ""} from {source.event.name} ({source.event.year}).', 'success')
    else:
        flash('Nothing new to copy - those items are already on this list.', 'info')
    return redirect(url_for('wishlist.view_wishlist', wishlist_id=wishlist_id))


@wishlist_bp.route('/item/<int:item_id>/purchase', methods=['POST'])
@login_required
def mark_purchased(item_id):
    """Mark an item as purchased"""
    item = WishListItem.query.get_or_404(item_id)
    wishlist = item.wishlist

    # Cannot purchase your own items
    if wishlist.owner_id == current_user.id:
        flash('You cannot mark items on your own list as purchased.', 'danger')
        return redirect(url_for('wishlist.view_wishlist', wishlist_id=wishlist.id))

    if not is_participant(wishlist.event_id):
        flash('You are not a participant in this event.', 'danger')
        return redirect(url_for('main.dashboard'))

    # Check if already purchased
    if item.purchase:
        flash('This item has already been marked as purchased.', 'warning')
        return redirect(url_for('wishlist.view_wishlist', wishlist_id=wishlist.id))

    purchase = ItemPurchase(
        item_id=item.id,
        purchaser_id=current_user.id,
        notes=request.form.get('notes', ''),
        is_secret_santa=(request.form.get('secret_santa') == '1'
                         and is_my_santa_pick(wishlist))
    )
    db.session.add(purchase)
    db.session.commit()

    flash(f'You marked "{item.name}" as purchased for {wishlist.owner.name}!', 'success')
    return redirect(url_for('wishlist.view_wishlist', wishlist_id=wishlist.id) + f'#item-{item.id}')


@wishlist_bp.route('/item/<int:item_id>/unpurchase', methods=['POST'])
@login_required
def unmark_purchased(item_id):
    """Unmark an item as purchased"""
    item = WishListItem.query.get_or_404(item_id)
    wishlist = item.wishlist

    if not item.purchase:
        flash('This item is not marked as purchased.', 'warning')
        return redirect(url_for('wishlist.view_wishlist', wishlist_id=wishlist.id))

    # Only the purchaser can unmark
    if item.purchase.purchaser_id != current_user.id:
        flash('Only the person who marked this as purchased can unmark it.', 'danger')
        return redirect(url_for('wishlist.view_wishlist', wishlist_id=wishlist.id))

    db.session.delete(item.purchase)
    db.session.commit()

    flash(f'"{item.name}" unmarked as purchased.', 'success')
    return redirect(url_for('wishlist.view_wishlist', wishlist_id=wishlist.id) + f'#item-{item.id}')


@wishlist_bp.route('/item/<int:item_id>/status', methods=['POST'])
@login_required
def update_status(item_id):
    """Move a purchase along: bought -> wrapped -> given"""
    item = WishListItem.query.get_or_404(item_id)
    status = request.form.get('status')
    if not item.purchase or item.purchase.purchaser_id != current_user.id:
        flash('Only the person who bought this can update it.', 'danger')
    elif status not in {s[0] for s in PURCHASE_STATUSES}:
        flash('Unknown status.', 'danger')
    else:
        item.purchase.status = status
        db.session.commit()
    next_page = request.form.get('next', '')
    if not next_page.startswith('/') or next_page.startswith('//'):
        next_page = url_for('wishlist.shopping_list')
    return redirect(next_page)


@wishlist_bp.route('/item/<int:item_id>/secret-santa', methods=['POST'])
@login_required
def set_secret_santa_flag(item_id):
    """Buyer marks / unmarks one of their purchases as their Secret Santa gift"""
    item = WishListItem.query.get_or_404(item_id)
    if not item.purchase or item.purchase.purchaser_id != current_user.id:
        flash('Only the person who bought this can change that.', 'danger')
    else:
        flag = request.form.get('secret_santa') == '1'
        if flag and not is_my_santa_pick(item.wishlist):
            flash("That person isn't your Secret Santa pick for this event.", 'warning')
        else:
            item.purchase.is_secret_santa = flag
            db.session.commit()
    next_page = request.form.get('next', '')
    if not next_page.startswith('/') or next_page.startswith('//'):
        next_page = url_for('wishlist.view_wishlist', wishlist_id=item.wishlist_id) + f'#item-{item.id}'
    return redirect(next_page)


@wishlist_bp.route('/item/<int:item_id>/contribute', methods=['POST'])
@login_required
def contribute(item_id):
    """Chip in on a group gift (or change your amount)"""
    item = WishListItem.query.get_or_404(item_id)
    wishlist = item.wishlist
    back = url_for('wishlist.view_wishlist', wishlist_id=wishlist.id) + f'#item-{item.id}'

    if wishlist.owner_id == current_user.id:
        flash("You can't chip in on your own gifts!", 'danger')
        return redirect(back)
    if not is_participant(wishlist.event_id):
        flash('You are not a participant in this event.', 'danger')
        return redirect(url_for('main.dashboard'))

    amount = parse_money(request.form.get('amount'))
    contribution = GiftContribution.query.filter_by(item_id=item.id, user_id=current_user.id).first()
    # $0 means "not chipping in" (a blank amount still means "count me in, amount to be decided")
    if amount is not None and amount == 0:
        if contribution:
            db.session.delete(contribution)
            db.session.commit()
            flash('You are no longer chipping in on this gift.', 'info')
        else:
            flash('Enter an amount, or leave it blank to count yourself in.', 'warning')
        return redirect(back)
    if contribution:
        contribution.amount = amount
        flash('Your contribution was updated.', 'success')
    else:
        db.session.add(GiftContribution(item_id=item.id, user_id=current_user.id, amount=amount))
        flash(f'You\'re chipping in on "{item.name}"! 🎁', 'success')
    db.session.commit()
    return redirect(back)


@wishlist_bp.route('/item/<int:item_id>/withdraw', methods=['POST'])
@login_required
def withdraw_contribution(item_id):
    """Stop chipping in on a group gift"""
    item = WishListItem.query.get_or_404(item_id)
    contribution = GiftContribution.query.filter_by(item_id=item.id, user_id=current_user.id).first()
    if contribution:
        db.session.delete(contribution)
        db.session.commit()
        flash('You are no longer chipping in on this gift.', 'info')
    return redirect(url_for('wishlist.view_wishlist', wishlist_id=item.wishlist_id) + f'#item-{item.id}')


@wishlist_bp.route('/shopping-list')
@login_required
def shopping_list():
    """Everything I've bought or am chipping in on, grouped by event and recipient"""
    purchases = (ItemPurchase.query.filter_by(purchaser_id=current_user.id)
                 .join(WishListItem).join(WishList).join(ChristmasEvent)
                 .order_by(ChristmasEvent.year.desc(), ChristmasEvent.id.desc()).all())
    contributions = (GiftContribution.query.filter_by(user_id=current_user.id)
                     .join(WishListItem).join(WishList).join(ChristmasEvent)
                     .order_by(ChristmasEvent.year.desc(), ChristmasEvent.id.desc()).all())

    events = OrderedDict()

    def event_entry(event):
        if event.id not in events:
            assignment = None
            if event.secret_santa_enabled:
                assignment = SecretSantaAssignment.query.filter_by(
                    event_id=event.id, giver_id=current_user.id).first()
            events[event.id] = {'event': event, 'people': OrderedDict(), 'total': 0,
                                'santa_receiver_id': assignment.receiver_id if assignment else None}
        return events[event.id]

    def owner_is_pick(entry, owner_id):
        return entry['santa_receiver_id'] == owner_id

    def person_entry(entry, owner):
        if owner.id not in entry['people']:
            entry['people'][owner.id] = {'owner': owner, 'purchases': [], 'contributions': [], 'total': 0,
                                         'santa_total': 0, 'santa_count': 0}
        return entry['people'][owner.id]

    for p in purchases:
        wl = p.item.wishlist
        entry = event_entry(wl.event)
        person = person_entry(entry, wl.owner)
        person['purchases'].append(p)
        person['total'] += p.item.price or 0
        if p.is_secret_santa and owner_is_pick(entry, wl.owner_id):
            person['santa_total'] += p.item.price or 0
            person['santa_count'] += 1
        entry['total'] += p.item.price or 0
    for c in contributions:
        wl = c.item.wishlist
        entry = event_entry(wl.event)
        person = person_entry(entry, wl.owner)
        person['contributions'].append(c)
        person['total'] += c.amount or 0
        entry['total'] += c.amount or 0

    for entry in events.values():
        entry['people'] = sorted(entry['people'].values(),
                                 key=lambda p: (p['owner'].id != entry['santa_receiver_id'], p['owner'].name.lower()))
        statuses = [p.status for person in entry['people'] for p in person['purchases']]
        entry['counts'] = {s: statuses.count(s) for s in ('purchased', 'wrapped', 'given')}
        entry['gift_count'] = len(statuses)

    return render_template('wishlist/shopping_list.html', events=list(events.values()),
                           statuses=PURCHASE_STATUSES)


@wishlist_bp.route('/item/<int:item_id>/generate-poem', methods=['POST'])
@login_required
def generate_poem(item_id):
    """Generate a cryptic poem for a purchased gift using Gemini AI"""
    item = WishListItem.query.get_or_404(item_id)
    wishlist = item.wishlist

    # Must be purchased
    if not item.purchase:
        return jsonify({'error': 'Item is not marked as purchased.'}), 400

    # Only the purchaser can generate a poem
    if item.purchase.purchaser_id != current_user.id:
        return jsonify({'error': 'Only the purchaser can generate a poem.'}), 403

    # Check generation limit (max 10)
    if not item.purchase.can_generate_poem():
        return jsonify({
            'error': 'Maximum poem regenerations reached (10 max).',
            'poem': item.purchase.poem,
            'generation_count': item.purchase.poem_generation_count
        }), 400

    # Get recipient info
    recipient = wishlist.owner

    # Generate the poem using Gemini
    from app.gemini_service import generate_gift_poem

    poem, error = generate_gift_poem(
        item_name=item.name,
        item_color=item.color or '',
        item_notes=item.notes or '',
        recipient_name=recipient.name,
        recipient_about=recipient.about_me or ''
    )

    if poem:
        # Save the poem and increment count
        item.purchase.poem = poem
        item.purchase.poem_generation_count += 1
        db.session.commit()

        return jsonify({
            'poem': poem,
            'generation_count': item.purchase.poem_generation_count,
            'can_regenerate': item.purchase.can_generate_poem()
        })
    else:
        return jsonify({'error': error or 'Failed to generate poem. Please try again.'}), 502
