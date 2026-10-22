"""Small helpers shared by the route modules"""
import re
from decimal import Decimal, InvalidOperation
from functools import wraps
from urllib.parse import urlparse

from flask import current_app, flash, redirect, url_for
from flask_login import current_user


def admin_required(f):
    """Decorator to require admin access"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin access required.', 'danger')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


def get_external_url(endpoint, **values):
    """Generate an absolute URL for links in emails"""
    server_name = current_app.config.get('SERVER_NAME_FOR_EMAILS', 'localhost:8123')
    scheme = current_app.config.get('PREFERRED_URL_SCHEME', 'https')
    with current_app.test_request_context():
        path = url_for(endpoint, **values)
    return f"{scheme}://{server_name}{path}"


def get_site_name():
    """Site name from Admin -> Settings"""
    from app.models import AppSettings
    settings = AppSettings.query.first()
    return (settings.site_name if settings and settings.site_name else 'Family Christmas')


def parse_money(value):
    """'$1,234.50' -> Decimal('1234.50'); blank or invalid -> None"""
    value = (value or '').strip().replace('$', '').replace(',', '')
    if not value:
        return None
    try:
        amount = Decimal(value).quantize(Decimal('0.01'))
    except InvalidOperation:
        return None
    if amount < 0 or amount >= Decimal('100000000'):
        return None
    return amount


def safe_url(value):
    """Only allow http(s) links so a wishlist link can't run javascript: code"""
    value = (value or '').strip()
    if not value:
        return None
    if '://' not in value:
        # "javascript:...", "data:..." etc. are rejected; "example.com/x" gets https://
        if re.match(r'^[a-zA-Z][a-zA-Z0-9+-]*:', value):
            return None
        value = 'https://' + value
    parsed = urlparse(value)
    if parsed.scheme not in ('http', 'https'):
        return None
    if len(value) > 500:  # long tracking-laden links (the column holds 500 characters)
        value = parsed._replace(query='', fragment='').geturl()
    return value if len(value) <= 500 else None


# Easter egg: asking for anything money-related (cash, gold bars, gift cards...) makes it rain money

# Money words that count anywhere in the item name ("Cash for a car", "Gold bars", "Amazon gift card")
_MONEY_ANYWHERE = re.compile(
    r"\b(?:cash|money|monies|moolah|dinero|dollars?|euros?|pounds sterling|"
    r"gift ?cards?|gift ?certificates?|e-?gift|"
    r"venmo|paypal|zelle|cash ?app|bitcoins?|crypto(?:currency)?|ethereum|dogecoin|"
    r"gold (?:bars?|bullion|coins?|ingots?|nuggets?)|bars? of gold|bullion|ingots?|krugerrands?|"
    r"silver (?:bars?|coins?|bullion)|pot of gold|"
    r"savings bonds?|lottery tickets?|scratch[- ]?offs?|piggy bank|"
    r"stocks|stock in|shares of|index funds?)\b|\$\s*\d|\$\$|\d+\s*grand\b")

# Slang that's only money when it's the whole request ("Dough" yes, "Cookie dough" no)
_MONEY_SLANG = re.compile(
    r"^(?:(?:some|a little|a lot of|lots of|more|extra|just|plain|cold|hard|good old|straight|real|crisp|actual)\s+)*"
    r"(?:dough|bucks|benjamins|cheddar|bread|bank|bones|clams|loot|paper|greenbacks|coin|bling|\$)"
    r"(?:\s+(?:please|pls|plz|only))*$")


def is_cash_request(name):
    """True for money-related wishes: 'Cash', 'Gold bars', 'Amazon gift card', 'Venmo me',
    '$$$', 'Dough'. False for 'Cookie dough', 'Cashmere sweater', 'Cheddar cheese board'."""
    text = (name or '').lower()
    if _MONEY_ANYWHERE.search(text):
        return True
    words = re.sub(r"[^a-z$ ]", ' ', text)
    words = re.sub(r'\s+', ' ', words).strip()
    return bool(words) and bool(_MONEY_SLANG.match(words))
