/* ========================================
   FAMILY CHRISTMAS APP - JAVASCRIPT
   ======================================== */

const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// POST with the CSRF token (for fetch() calls; normal forms carry a hidden field)
function csrfFetch(url, options = {}) {
    const token = document.querySelector('meta[name="csrf-token"]')?.content;
    options.method = options.method || 'POST';
    options.headers = Object.assign({ 'X-CSRFToken': token }, options.headers || {});
    return fetch(url, options);
}

// ---------- Icons (Lucide): <i data-lucide="gift"></i> becomes an inline SVG ----------
function renderIcons() {
    if (window.lucide) window.lucide.createIcons();
}

// Icons added later by scripts (status messages, spinners...) are drawn automatically.
// Only un-drawn <i data-lucide> placeholders trigger this (drawn SVGs keep the attribute).
function watchIcons() {
    const pending = n => n.nodeType === 1 &&
        ((n.tagName === 'I' && n.hasAttribute('data-lucide')) || n.querySelector?.('i[data-lucide]'));
    new MutationObserver(mutations => {
        if (mutations.some(m => [...m.addedNodes].some(pending))) renderIcons();
    }).observe(document.body, { childList: true, subtree: true });
}

// ---------- Light / dark theme (dark by default) ----------
function currentTheme() {
    return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
}

function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    try { localStorage.setItem('theme', theme); } catch (e) { /* private mode */ }
    document.querySelectorAll('.theme-toggle').forEach(btn => {
        btn.innerHTML = `<i data-lucide="${theme === 'dark' ? 'sun' : 'moon'}"></i>`;
        btn.setAttribute('aria-label', theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
    });
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = theme === 'dark' ? '#121a33' : '#f3ede0';
}

// ---------- Image lightbox (any element with data-lightbox="url") ----------
function openLightbox(src, caption) {
    const box = document.getElementById('imageLightbox');
    if (!box) return;
    box.querySelector('img').src = src;
    box.querySelector('.lightbox-caption').textContent = caption || '';
    box.style.display = 'flex';
    document.body.style.overflow = 'hidden';
}

function closeLightbox() {
    const box = document.getElementById('imageLightbox');
    if (box && box.style.display === 'flex') {
        box.style.display = 'none';
        document.body.style.overflow = '';
    }
}

// ---------- Snowfall: every flake gets its own size, shape, speed, sway and drift ----------
function makeSnow() {
    const sky = document.querySelector('.snowflakes');
    if (!sky || prefersReducedMotion) return;
    const rand = (min, max) => min + Math.random() * (max - min);
    const shapes = ['❄', '❅', '❆', '✻', '✼', 'dot', 'dot', 'dot'];  // plenty of soft dots between the crystals
    const tints = ['#ffffff', '#ffffff', '#f2f8ff', '#e3f0ff'];
    const count = Math.round(Math.min(42, Math.max(18, window.innerWidth / 34)));

    sky.innerHTML = '';
    for (let i = 0; i < count; i++) {
        const depth = Math.random();              // 0 = far away, 1 = close to the screen
        const shape = shapes[Math.floor(Math.random() * shapes.length)];
        const isDot = shape === 'dot';
        const fall = rand(16, 30) - depth * 8;    // nearer flakes fall a bit faster
        const flake = document.createElement('div');
        flake.className = 'snowflake';
        flake.style.cssText = [
            `--x:${rand(-3, 100).toFixed(1)}%`,
            `--fall:${fall.toFixed(1)}s`,
            `--delay:${(-rand(0, fall)).toFixed(1)}s`,
            `--drift:${rand(-80, 80).toFixed(0)}px`,
        ].join(';');

        const inner = document.createElement('span');
        if (isDot) {
            inner.className = 'flake-dot';
            inner.style.setProperty('--size', `${(3 + depth * 7).toFixed(1)}px`);
        } else {
            inner.textContent = shape;
            inner.style.setProperty('--size', `${(0.55 + depth * 1.15).toFixed(2)}rem`);
        }
        inner.style.setProperty('--alpha', (0.3 + depth * 0.6).toFixed(2));
        inner.style.setProperty('--blur', depth < 0.2 ? '1px' : (depth > 0.92 ? '0.6px' : '0px'));
        inner.style.setProperty('--tint', tints[Math.floor(Math.random() * tints.length)]);
        inner.style.setProperty('--sway', `${rand(12, 50).toFixed(0)}px`);
        inner.style.setProperty('--sway-time', `${rand(2.8, 6.5).toFixed(1)}s`);
        inner.style.setProperty('--sway-delay', `${(-rand(0, 6)).toFixed(1)}s`);
        inner.style.setProperty('--spin', `${rand(20, 200).toFixed(0)}deg`);
        flake.appendChild(inner);
        sky.appendChild(flake);
    }

    // Easter egg: now and then (about 1 page in 8) one flake is a snowflake-paw.
    // Add ?pawflakes to any page address to see a few on purpose.
    const forced = /[?&]pawflakes\b/.test(location.search);
    if (forced || Math.random() < 0.125) {
        const flakes = [...sky.children];
        for (let i = 0; i < (forced ? 5 : 1) && flakes.length; i++) {
            const flake = flakes.splice(Math.floor(Math.random() * flakes.length), 1)[0];
            const fall = rand(26, 34);                     // drifts down slowly so it gets noticed
            flake.style.setProperty('--fall', `${fall.toFixed(1)}s`);
            flake.style.setProperty('--delay', `${(-rand(0, fall * 0.6)).toFixed(1)}s`);
            const inner = flake.firstChild;
            inner.className = 'flake-paw';
            inner.textContent = '';
            inner.style.setProperty('--size', `${rand(1.9, 2.5).toFixed(2)}rem`);
            inner.style.setProperty('--alpha', '0.95');
            inner.style.setProperty('--blur', '0px');
            inner.style.setProperty('--spin', `${rand(15, 45).toFixed(0)}deg`);
            const img = document.createElement('img');
            img.src = '/static/images/pawflake.svg';
            img.alt = '';
            inner.appendChild(img);
        }
    }
}

document.addEventListener('DOMContentLoaded', function() {
    makeSnow();
    watchIcons();
    setTheme(currentTheme());
    renderIcons();
    document.querySelectorAll('.theme-toggle').forEach(btn => {
        btn.addEventListener('click', () => setTheme(currentTheme() === 'dark' ? 'light' : 'dark'));
    });

    // Auto-dismiss only "success" flash messages; warnings/errors (which may
    // contain a temporary password) and in-page tips stay until closed
    document.querySelectorAll('.christmas-alert.alert-success').forEach(alert => {
        setTimeout(() => bootstrap.Alert.getOrCreateInstance(alert).close(), 5000);
    });

    // Confirm delete actions
    document.querySelectorAll('[data-confirm]').forEach(button => {
        button.addEventListener('click', function(e) {
            const message = this.getAttribute('data-confirm') || 'Are you sure?';
            if (!confirm(message)) {
                e.preventDefault();
            }
        });
    });

    // Staggered fade-in for cards (capped so long lists don't take seconds to appear)
    if (!prefersReducedMotion) {
        document.querySelectorAll('.christmas-card, .wishlist-item').forEach((card, index) => {
            card.style.animationDelay = `${Math.min(index, 6) * 0.05}s`;
            card.classList.add('fade-in');
        });
    }

    // Lightbox
    document.querySelectorAll('[data-lightbox]').forEach(el => {
        el.addEventListener('click', () => openLightbox(el.dataset.lightbox, el.dataset.caption));
    });
    const lightbox = document.getElementById('imageLightbox');
    if (lightbox) {
        lightbox.addEventListener('click', e => {
            if (e.target === lightbox || e.target.classList.contains('lightbox-close')) closeLightbox();
        });
    }
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeLightbox(); });

    // Drag-and-drop image pickers (see image_dropzone in templates/_macros.html)
    const MAX_UPLOAD = 16 * 1024 * 1024;
    document.querySelectorAll('[data-dropzone]').forEach(zone => {
        const input = zone.querySelector('.dropzone-input');
        const preview = zone.querySelector('.dropzone-preview');
        const fileLabel = zone.querySelector('.dropzone-file');
        const error = zone.querySelector('.dropzone-error');
        const originalSrc = preview.getAttribute('src');

        function showFile() {
            const file = input.files[0];
            error.classList.add('d-none');
            if (!file) {
                fileLabel.classList.add('d-none');
                preview.src = originalSrc || '';
                preview.classList.toggle('d-none', !originalSrc);
                zone.classList.toggle('has-image', !!originalSrc);
                return;
            }
            if (!file.type.startsWith('image/') || file.size > MAX_UPLOAD) {
                error.textContent = file.size > MAX_UPLOAD
                    ? `That file is ${(file.size / 1048576).toFixed(1)} MB - the limit is 16 MB.`
                    : 'That isn\'t an image file.';
                error.classList.remove('d-none');
                input.value = '';
                showFile();
                error.classList.remove('d-none');
                return;
            }
            preview.src = URL.createObjectURL(file);
            preview.classList.remove('d-none');
            zone.classList.add('has-image');
            fileLabel.textContent = `${file.name || 'Pasted image'} · ${Math.max(1, Math.round(file.size / 1024))} KB - click to change`;
            fileLabel.classList.remove('d-none');
            // choosing a new image un-ticks "remove current image"
            const remove = zone.closest('form')?.querySelector('input[name="remove_image"]');
            if (remove) remove.checked = false;
        }

        zone.classList.toggle('has-image', !!originalSrc);
        input.addEventListener('change', showFile);
        ['dragenter', 'dragover'].forEach(ev => input.addEventListener(ev, () => zone.classList.add('dragover')));
        ['dragleave', 'drop'].forEach(ev => input.addEventListener(ev, () => zone.classList.remove('dragover')));

        // Paste a screenshot anywhere on the page (only when the page has one paste-enabled zone)
        if (zone.hasAttribute('data-paste') && document.querySelectorAll('[data-dropzone][data-paste]').length === 1) {
            document.addEventListener('paste', e => {
                const item = [...(e.clipboardData?.items || [])].find(i => i.type.startsWith('image/'));
                if (!item || ['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName) && document.activeElement !== input) return;
                const file = item.getAsFile();
                const transfer = new DataTransfer();
                transfer.items.add(new File([file], `pasted-${Date.now()}.${file.type.split('/')[1] || 'png'}`, { type: file.type }));
                input.files = transfer.files;
                input.dispatchEvent(new Event('change'));   // same path as choosing a file
                e.preventDefault();
            });
        }
    });

    // Switches that show/hide a related field (data-toggles="#selector"),
    // and optionally hide another one while on (data-toggles-off="#selector")
    document.querySelectorAll('input[data-toggles]').forEach(sw => {
        const target = document.querySelector(sw.dataset.toggles);
        const opposite = sw.dataset.togglesOff && document.querySelector(sw.dataset.togglesOff);
        if (!target) return;
        const sync = () => {
            target.classList.toggle('d-none', !sw.checked);
            if (opposite) opposite.classList.toggle('d-none', sw.checked);
        };
        sw.addEventListener('change', sync);
        sync();
    });

    // Announcements on Home can be hidden once read (remembered on this device)
    document.querySelectorAll('[data-announcement]').forEach(note => {
        const key = `announcementHidden:${note.dataset.announcement}`;
        try { if (localStorage.getItem(key)) note.hidden = true; } catch (e) { /* private mode */ }
        note.querySelector('[data-dismiss-announcement]').addEventListener('click', () => {
            note.hidden = true;
            try { localStorage.setItem(key, '1'); } catch (e) { /* private mode */ }
        });
    });

    // URL helper for wishlist items
    document.querySelectorAll('input[type="url"]').forEach(input => {
        input.addEventListener('blur', function() {
            const value = this.value.trim();
            if (value && !value.match(/^https?:\/\//)) {
                this.value = 'https://' + value;
            }
        });
    });

    // Character counter for textareas
    document.querySelectorAll('textarea[maxlength]').forEach(textarea => {
        const maxLength = textarea.getAttribute('maxlength');
        const counter = document.createElement('small');
        counter.className = 'text-muted float-end';
        counter.textContent = `${textarea.value.length} / ${maxLength}`;
        textarea.parentNode.appendChild(counter);
        textarea.addEventListener('input', function() {
            counter.textContent = `${this.value.length} / ${maxLength}`;
        });
    });

    // Toggle password visibility
    document.querySelectorAll('.toggle-password').forEach(toggle => {
        toggle.addEventListener('click', function() {
            const input = document.querySelector(this.getAttribute('data-target'));
            const show = input.type === 'password';
            input.type = show ? 'text' : 'password';
            this.innerHTML = `<i data-lucide="${show ? 'eye-off' : 'eye'}"></i>`;
        });
    });

    // Search/filter functionality for tables
    document.querySelectorAll('[data-search-target]').forEach(input => {
        const target = document.getElementById(input.getAttribute('data-search-target'));
        if (target) {
            input.addEventListener('input', function() {
                const searchTerm = this.value.toLowerCase();
                target.querySelectorAll('tbody tr').forEach(row => {
                    row.style.display = row.textContent.toLowerCase().includes(searchTerm) ? '' : 'none';
                });
            });
        }
    });

    // Copy to clipboard functionality
    document.querySelectorAll('[data-copy]').forEach(button => {
        button.addEventListener('click', function() {
            navigator.clipboard.writeText(this.getAttribute('data-copy')).then(() => {
                const originalText = this.innerHTML;
                this.innerHTML = '<i data-lucide="check"></i> Copied!';
                setTimeout(() => { this.innerHTML = originalText; }, 2000);
            });
        });
    });

    // Disable submit buttons after the first click (no double-posts)
    document.querySelectorAll('form').forEach(form => {
        form.addEventListener('submit', e => {
            if (form.dataset.submitted) return;
            form.dataset.submitted = '1';
            // Slow actions (AI photos) say what's happening instead of just freezing
            const slow = e.submitter && e.submitter.dataset.loadingText;
            if (slow) {
                e.submitter.innerHTML = `<i data-lucide="loader-circle" class="icon-spin"></i> ${slow}`;
            }
            setTimeout(() => form.querySelectorAll('button[type="submit"]').forEach(b => b.disabled = true), 0);
        });
    });
    // ...and re-enable them if the page is restored with the Back button
    window.addEventListener('pageshow', () => {
        document.querySelectorAll('form[data-submitted]').forEach(form => {
            delete form.dataset.submitted;
            form.querySelectorAll('button[type="submit"]').forEach(b => b.disabled = false);
        });
    });

    // Random Christmas greeting
    const greetings = [
        "🎄 Merry Christmas!",
        "🎅 Ho Ho Ho!",
        "❄️ Happy Holidays!",
        "🎁 Season's Greetings!",
        "⭐ Joy to the World!",
        "🦌 Dasher says hi!",
        "🔔 Jingle all the way!"
    ];
    const greetingElement = document.getElementById('random-greeting');
    if (greetingElement) {
        greetingElement.textContent = greetings[Math.floor(Math.random() * greetings.length)];
    }

    // Sparkle on click (skipped for people who prefer reduced motion)
    if (!prefersReducedMotion && document.querySelector('.snowflakes')) {
        const style = document.createElement('style');
        style.textContent = `
            @keyframes sparkle {
                0% { transform: scale(1) rotate(0deg); opacity: 1; }
                100% { transform: scale(0) rotate(180deg); opacity: 0; }
            }`;
        document.head.appendChild(style);

        document.body.addEventListener('click', function(e) {
            const sparkle = document.createElement('div');
            sparkle.textContent = '✨';
            sparkle.style.cssText = `position: fixed; left: ${e.clientX}px; top: ${e.clientY}px;
                pointer-events: none; font-size: 20px; animation: sparkle 1s forwards; z-index: 10000;`;
            document.body.appendChild(sparkle);
            setTimeout(() => sparkle.remove(), 1000);
        });
    }
});

// ======================================================================
// Installable app (PWA) and notifications
// ======================================================================
const isStandalone = () => window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
const isIOS = () => /iPhone|iPad|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);  // iPadOS reports itself as a Mac

function storageGet(key, store = localStorage) { try { return store.getItem(key); } catch (e) { return null; } }
function storageSet(key, value, store = localStorage) { try { store.setItem(key, value); } catch (e) { /* private mode */ } }
function storageDel(key, store = localStorage) { try { store.removeItem(key); } catch (e) { /* private mode */ } }

function registerServiceWorker() {
    // Needs https (or localhost) - the plain LAN address can't install the app
    if (!('serviceWorker' in navigator) || !window.isSecureContext) return;
    navigator.serviceWorker.register('/sw.js', { scope: '/', updateViaCache: 'none' }).catch(() => {});
}

// ---------- One-time "put it on your home screen" tip ----------
function setupInstallTip() {
    const tip = document.getElementById('install-tip');
    if (!tip || isStandalone()) return;
    if (Date.now() < Number(storageGet('installTipHiddenUntil') || 0)) return;
    const hide = days => {
        tip.hidden = true;
        storageSet('installTipHiddenUntil', String(Date.now() + days * 864e5));
    };
    tip.querySelector('[data-install-close]').addEventListener('click', () => hide(30));
    window.addEventListener('appinstalled', () => hide(3650));

    if (isIOS()) {
        if (!window.isSecureContext) return;  // Add to Home Screen only makes an app from the https address
        tip.querySelector('[data-install-ios]').hidden = false;
        setTimeout(() => { tip.hidden = false; }, 1500);
        return;
    }
    // Android / Chrome / Edge offer an install prompt we can trigger from a button
    window.addEventListener('beforeinstallprompt', e => {
        // On computers the browser shows its own install icon; only nudge on phones and tablets
        if (!window.matchMedia('(pointer: coarse)').matches) return;
        e.preventDefault();
        const deferred = e;
        tip.querySelector('[data-install-android]').hidden = false;
        const go = tip.querySelector('[data-install-go]');
        go.hidden = false;
        go.onclick = async () => {
            deferred.prompt();
            const choice = await deferred.userChoice;
            hide(choice.outcome === 'accepted' ? 3650 : 30);
        };
        tip.hidden = false;
    });
}

// ---------- Offer a reload when a new version has been deployed ----------
// Installed apps can stay open in the background for days; check when they come back.
function watchForUpdates() {
    const mine = document.querySelector('meta[name="app-version"]')?.content;
    const banner = document.getElementById('update-banner');
    if (!mine || !banner) return;
    banner.querySelector('[data-dismiss-banner]').addEventListener('click', () => { banner.hidden = true; });
    banner.querySelector('[data-reload]').addEventListener('click', () => window.location.reload());
    let lastCheck = Date.now();
    document.addEventListener('visibilitychange', async () => {
        if (document.visibilityState !== 'visible' || Date.now() - lastCheck < 60000) return;
        lastCheck = Date.now();
        navigator.serviceWorker?.getRegistration().then(reg => reg && reg.update()).catch(() => {});
        try {
            const response = await fetch('/app-version', { cache: 'no-store' });
            const { version } = await response.json();
            if (version && version !== mine) banner.hidden = false;
        } catch (e) { /* offline - try next time */ }
    });
}

// ---------- Home-screen badge = unread Secret Santa messages ----------
function updateAppBadge() {
    const count = Number(document.querySelector('meta[name="unread-count"]')?.content);
    if (!navigator.setAppBadge || Number.isNaN(count)) return;
    (count > 0 ? navigator.setAppBadge(count) : navigator.clearAppBadge()).catch(() => {});
}

// ---------- Push notifications ----------
const Push = {
    key() { return document.querySelector('meta[name="push-key"]')?.content || ''; },

    supported() {
        return window.isSecureContext && 'serviceWorker' in navigator && 'PushManager' in window &&
            'Notification' in window && Boolean(this.key());
    },

    keyBytes() {
        const b64 = this.key().replace(/-/g, '+').replace(/_/g, '/');
        const raw = atob(b64 + '='.repeat((4 - b64.length % 4) % 4));
        return Uint8Array.from(raw, c => c.charCodeAt(0));
    },

    // A subscription made with an older server key can't receive messages any more
    sameKey(sub) {
        const theirs = sub.options && sub.options.applicationServerKey;
        if (!theirs) return true;
        const mine = this.keyBytes(), other = new Uint8Array(theirs);
        return mine.length === other.length && mine.every((b, i) => b === other[i]);
    },

    async current() {
        if (!this.supported()) return null;
        const reg = await navigator.serviceWorker.ready;
        const sub = await reg.pushManager.getSubscription();
        if (sub && !this.sameKey(sub)) { await sub.unsubscribe(); return null; }
        return sub;
    },

    async save(sub) {
        const response = await csrfFetch('/push/subscribe', {
            headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(sub.toJSON()),
        });
        if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error || 'Could not save');
        storageSet('pushSynced', sub.endpoint, sessionStorage);
    },

    // Must be called straight from a tap (iPhone only asks for permission then)
    async enable() {
        const permission = await Notification.requestPermission();
        if (permission !== 'granted') throw new Error(permission === 'denied' ? 'blocked' : 'dismissed');
        const reg = await navigator.serviceWorker.ready;
        let sub = await this.current();
        if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: this.keyBytes() });
        await this.save(sub);
        storageSet('pushWanted', '1');
        return sub;
    },

    async disable() {
        storageDel('pushWanted');
        const sub = await this.current();
        if (!sub) return;
        await csrfFetch('/push/unsubscribe', {
            headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ endpoint: sub.endpoint }),
        }).catch(() => {});
        await sub.unsubscribe();
    },

    // Each visit, make sure the server has this device's (possibly renewed) subscription
    // and that it's filed under whoever is signed in now
    async sync() {
        if (!this.supported() || Notification.permission !== 'granted') return;
        let sub = await this.current();
        if (!sub && storageGet('pushWanted')) {
            const reg = await navigator.serviceWorker.ready;
            sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: this.keyBytes() });
        }
        if (sub && storageGet('pushSynced', sessionStorage) !== sub.endpoint) await this.save(sub);
    },
};

// Settings panel on the profile page
function setupPushPanel() {
    const panel = document.querySelector('[data-push-panel]');
    if (!panel) return;
    const status = panel.querySelector('[data-push-status]');
    const btn = name => panel.querySelector(`[data-push-${name}]`);
    const show = (html, buttons = []) => {
        status.innerHTML = html;
        ['enable', 'disable', 'test'].forEach(n => btn(n).classList.toggle('d-none', !buttons.includes(n)));
    };

    async function refresh() {
        if (!Push.supported()) {
            if (isIOS() && !isStandalone() && window.isSecureContext) {
                show('<i data-lucide="smartphone"></i> On iPhone and iPad, notifications work once this app is on your Home Screen: tap <strong>Share</strong>, then <strong>Add to Home Screen</strong>, open it from there and come back to this page.');
            } else if (!window.isSecureContext) {
                show('<i data-lucide="lock"></i> Notifications need the secure <strong>https://</strong> address of this site.');
            } else {
                show('<i data-lucide="bell-off"></i> This browser can\'t show notifications.');
            }
            return;
        }
        if (Notification.permission === 'denied') {
            show('<i data-lucide="bell-off"></i> Notifications are blocked for this site. Allow them in your browser or phone settings, then reload this page.');
            return;
        }
        const sub = await Push.current().catch(() => null);
        if (sub) show('<i data-lucide="bell-ring"></i> <strong>On</strong> for this device.', ['disable', 'test']);
        else show('<i data-lucide="bell"></i> <strong>Off</strong> for this device.', ['enable']);
    }

    btn('enable').addEventListener('click', async () => {
        btn('enable').disabled = true;
        try {
            await Push.enable();
            await csrfFetch('/push/test').catch(() => {});
        } catch (e) {
            if (e.message !== 'dismissed' && e.message !== 'blocked') {
                status.textContent = `Couldn't turn notifications on: ${e.message}`;
                btn('enable').disabled = false;
                return;
            }
        }
        btn('enable').disabled = false;
        refresh();
    });
    btn('disable').addEventListener('click', async () => {
        btn('disable').disabled = true;
        await Push.disable().catch(() => {});
        btn('disable').disabled = false;
        refresh();
    });
    btn('test').addEventListener('click', async () => {
        btn('test').disabled = true;
        const response = await csrfFetch('/push/test').catch(() => null);
        const data = response ? await response.json().catch(() => ({})) : {};
        show(response && response.ok
            ? '<i data-lucide="send"></i> Sent - it should pop up in a moment.'
            : `<i data-lucide="circle-alert"></i> ${data.error || 'Couldn\'t send a test.'}`, ['disable', 'test']);
        btn('test').disabled = false;
    });
    refresh();
}

// Small "turn on notifications?" card on the home page (until answered or dismissed)
function setupPushNudge() {
    const nudge = document.querySelector('[data-push-nudge]');
    if (!nudge || !Push.supported() || Notification.permission !== 'default' || storageGet('pushNudgeHidden')) return;
    nudge.hidden = false;
    const hide = () => { nudge.hidden = true; storageSet('pushNudgeHidden', '1'); };
    nudge.querySelector('[data-push-nudge-close]').addEventListener('click', hide);
    nudge.querySelector('[data-push-nudge-go]').addEventListener('click', async () => {
        try {
            await Push.enable();
            await csrfFetch('/push/test').catch(() => {});
        } catch (e) { /* declined - don't ask again */ }
        hide();
    });
}

// Logging out stops this device getting the previous person's notifications
function setupLogoutUnsubscribe() {
    document.querySelectorAll('a[href$="/logout"]').forEach(link => {
        link.addEventListener('click', e => {
            if (!Push.supported() || Notification.permission !== 'granted') return;
            e.preventDefault();
            const go = () => { window.location.href = link.href; };
            setTimeout(go, 2000);  // never hold up logging out for long
            Push.disable().then(go, go);
        });
    });
}

// ---------- Easter egg: ask for cash, get a brief money rain ----------
// (also forced with ?moneyrain on any page)
function makeMoneyRain() {
    if (prefersReducedMotion) return;
    const rand = (min, max) => min + Math.random() * (max - min);
    const sky = document.createElement('div');
    sky.className = 'money-rain';
    sky.setAttribute('aria-hidden', 'true');
    const bills = ['💵', '💵', '💵', '💸', '💰', '🪙'];
    const count = Math.round(Math.min(46, Math.max(22, window.innerWidth / 28)));
    for (let i = 0; i < count; i++) {
        const bill = document.createElement('div');
        bill.className = 'money-bill';
        bill.style.cssText = [
            `--x:${rand(-2, 98).toFixed(1)}%`,
            `--fall:${rand(2.6, 4.4).toFixed(2)}s`,
            `--delay:${rand(0, 2.2).toFixed(2)}s`,
            `--drift:${rand(-90, 90).toFixed(0)}px`,
        ].join(';');
        const inner = document.createElement('span');
        inner.textContent = bills[Math.floor(Math.random() * bills.length)];
        inner.style.setProperty('--size', `${rand(1.4, 2.6).toFixed(2)}rem`);
        inner.style.setProperty('--sway', `${rand(15, 45).toFixed(0)}px`);
        inner.style.setProperty('--spin', `${rand(25, 110).toFixed(0)}deg`);
        inner.style.setProperty('--sway-time', `${rand(0.9, 1.8).toFixed(2)}s`);
        bill.appendChild(inner);
        sky.appendChild(bill);
    }
    document.body.appendChild(sky);
    setTimeout(() => sky.classList.add('done'), 6200);
    setTimeout(() => sky.remove(), 7200);
}

document.addEventListener('DOMContentLoaded', () => {
    registerServiceWorker();
    if (document.querySelector('meta[name="money-rain"]') || /[?&]moneyrain\b/.test(location.search)) {
        makeMoneyRain();
    }
    if (!document.querySelector('meta[name="push-key"]')) return;  // signed-out pages
    setupInstallTip();
    watchForUpdates();
    updateAppBadge();
    setupPushPanel();
    setupPushNudge();
    setupLogoutUnsubscribe();
    Push.sync().catch(() => {});
});
