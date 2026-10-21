/* Add/edit wishlist item: paste a product link and the form fills itself in.
   Rules: suggestions never overwrite something the person typed, filled fields
   are highlighted so they get checked, and a failed lookup just says so. */
(function () {
    const form = document.getElementById('item-form');
    if (!form) return;

    const urlInput = document.getElementById('url');
    const status = document.getElementById('link-status');
    const pasteBtn = document.getElementById('paste-link');
    const refreshBtn = document.getElementById('refresh-link');
    const imageUrl = document.getElementById('image_url');
    const zone = form.querySelector('[data-dropzone]');
    const fileInput = zone && zone.querySelector('.dropzone-input');
    const editing = form.dataset.mode === 'edit';
    const fields = ['name', 'price', 'color', 'size'].reduce((o, id) => (o[id] = document.getElementById(id), o), {});
    let lastLooked = editing ? urlInput.value.trim() : '';
    let inFlight = null;

    // Anything already filled (editing) or typed by the person is theirs
    Object.values(fields).forEach(el => {
        if (el.value.trim()) el.dataset.mine = '1';
        el.addEventListener('input', () => {
            el.dataset.mine = '1';
            el.classList.remove('autofilled');
        });
    });

    function setStatus(kind, html) {
        status.className = `link-status small ${kind}`;
        status.innerHTML = html;
    }

    // While a lookup runs the whole form is locked (so nothing typed gets overwritten
    // mid-way) and a Cancel button sits next to the progress message.
    let busy = false;
    function setBusy(on, statusEl, abort) {
        busy = on;
        form.classList.toggle('is-busy', on);
        form.querySelectorAll('input:not([type=hidden]), select, textarea, button').forEach(el => {
            if (el.classList.contains('lookup-cancel')) return;
            if (on) {
                el.dataset.wasDisabled = el.disabled ? '1' : '';
                el.disabled = true;
            } else if ('wasDisabled' in el.dataset) {
                el.disabled = el.dataset.wasDisabled === '1';
                delete el.dataset.wasDisabled;
            }
        });
        form.setAttribute('aria-busy', on ? 'true' : 'false');
        if (on && statusEl && abort) {
            const cancel = document.createElement('button');
            cancel.type = 'button';
            cancel.className = 'btn btn-sm btn-outline-secondary lookup-cancel ms-2 py-0';
            cancel.textContent = 'Cancel';
            cancel.addEventListener('click', abort);
            statusEl.appendChild(cancel);
        }
    }
    // Enter key / any submit is ignored while a lookup is running
    form.addEventListener('submit', e => {
        if (busy) { e.preventDefault(); e.stopImmediatePropagation(); }
    }, true);

    function fill(id, value, force) {
        const el = fields[id];
        if (!el || value == null || value === '') return false;
        if (el.dataset.mine && !force) return false;
        el.value = value;
        delete el.dataset.mine;
        el.classList.remove('autofilled');
        void el.offsetWidth;            // restart the highlight animation
        el.classList.add('autofilled');
        return true;
    }

    function showLinkImage(src, site) {
        if (!zone) return;
        const userPickedFile = fileInput && fileInput.files.length;
        const hasPhoto = zone.classList.contains('has-image');
        if (userPickedFile || (hasPhoto && !refreshing)) return;
        imageUrl.value = src;
        const preview = zone.querySelector('.dropzone-preview');
        preview.src = src;
        preview.classList.remove('d-none');
        zone.classList.add('has-image');
        const label = zone.querySelector('.dropzone-file');
        label.textContent = `Photo from ${site} - drop your own to replace it`;
        label.classList.remove('d-none');
    }

    // A different link: drop what the previous link suggested (never what was typed)
    function clearLinkSuggestions() {
        Object.values(fields).forEach(el => {
            if (el.classList.contains('autofilled') && !el.dataset.mine) {
                el.value = '';
                el.classList.remove('autofilled');
            }
        });
        if (imageUrl.value && zone) {
            imageUrl.value = '';
            const preview = zone.querySelector('.dropzone-preview');
            const original = preview.dataset.original || '';
            preview.src = original;
            preview.classList.toggle('d-none', !original);
            zone.classList.toggle('has-image', !!original);
            zone.querySelector('.dropzone-file').classList.add('d-none');
        }
    }
    if (zone) {
        const preview = zone.querySelector('.dropzone-preview');
        preview.dataset.original = preview.getAttribute('src') || '';
    }

    // Choosing your own photo always beats the link's photo
    if (fileInput) fileInput.addEventListener('change', () => { if (fileInput.files.length) imageUrl.value = ''; });

    let refreshing = false;

    async function lookUp(force) {
        const url = urlInput.value.trim();
        if (!url || (!force && url === lastLooked)) return;
        if (!/^https?:\/\//i.test(url) && !/^[\w-]+(\.[\w-]+)+/.test(url)) return;
        lastLooked = url;
        refreshing = !!force;
        if (!force) clearLinkSuggestions();
        if (inFlight) inFlight.abort();
        inFlight = new AbortController();
        const controller = inFlight;
        let focusName = false;

        const site = (() => { try { return new URL(/^https?:/i.test(url) ? url : `https://${url}`).hostname.replace(/^www\./, ''); } catch (e) { return 'that site'; } })();
        setStatus('busy', `<i data-lucide="loader-circle" class="icon-spin"></i> Reading ${site}… this can take a few seconds`);
        setBusy(true, status, () => { controller.cancelled = true; controller.abort(); });

        const body = new FormData();
        body.append('url', url);
        try {
            const r = await csrfFetch(form.dataset.previewUrl, { body, signal: controller.signal });
            const data = await r.json();
            if (!data.ok) {
                setStatus('warn', `<i data-lucide="info"></i> ${data.message || "Couldn't read that link - please fill it in below."} The link will still be saved.`);
                return;
            }
            const f = data.fields;
            const filled = [];
            if (fill('name', f.name)) filled.push('name');
            if (fill('price', f.price, refreshing)) filled.push('price');
            if (fill('color', f.color)) filled.push('color');
            if (fill('size', f.size)) filled.push('size');
            if (f.image_url) { showLinkImage(f.image_url, data.site); if (imageUrl.value) filled.push('photo'); }
            // swap a huge tracking link for the store's clean one
            if (f.canonical_url && url.length > 200) urlInput.value = f.canonical_url;

            const how = {
                'store': '',
                'ai-search': ' <span class="text-muted">(the store blocked us, so this came from a web search - double-check the price)</span>',
            }[data.method] ?? ' <span class="text-muted">(with AI help)</span>';
            if (filled.length) {
                setStatus('ok', `<i data-lucide="circle-check"></i> Filled in ${filled.join(', ')} from ${data.site}${how} - please check it looks right.`);
            } else {
                setStatus('ok', `<i data-lucide="circle-check"></i> Read ${data.site} - your own entries were kept.`);
            }
            focusName = !editing && !!fields.name.value;
        } catch (e) {
            if (e.name === 'AbortError') {
                if (controller.cancelled) {
                    lastLooked = '';     // so the same link can be tried again
                    setStatus('warn', '<i data-lucide="ban"></i> Cancelled - fill it in below, or paste the link again to retry.');
                }
                return;
            }
            setStatus('warn', '<i data-lucide="info"></i> Couldn\'t read that link - please fill it in below.');
        } finally {
            refreshing = false;
            setBusy(false);
            if (focusName) fields.name.focus();
        }
    }

    // Pasting or finishing typing a link triggers the lookup (not on edit until asked)
    urlInput.addEventListener('paste', () => setTimeout(() => lookUp(false), 0));
    urlInput.addEventListener('change', () => { if (!editing || urlInput.value.trim() !== lastLooked) lookUp(false); });
    if (refreshBtn) refreshBtn.addEventListener('click', () => lookUp(true));

    // Arrived via "Share" from a store's app (installed Android app): fill in and look it up
    if (!editing) {
        const shared = new URLSearchParams(window.location.search);
        if (shared.get('link') && !urlInput.value) {
            urlInput.value = shared.get('link');
            lookUp(false);
        } else if (shared.get('name') && !fields.name.value) {
            fields.name.value = shared.get('name');
        }
    }

    // "Paste" button - only where the browser allows reading the clipboard (https)
    if (pasteBtn && window.isSecureContext && navigator.clipboard && navigator.clipboard.readText) {
        pasteBtn.classList.remove('d-none');
        pasteBtn.addEventListener('click', async () => {
            try {
                const text = (await navigator.clipboard.readText()).trim();
                if (text) { urlInput.value = text; lookUp(false); }
            } catch (e) {
                urlInput.focus();
                setStatus('warn', 'Your browser blocked pasting - long-press (or Ctrl+V) in the box instead.');
            }
        });
    }

    // ---------- Screenshot reading: AI reads name/price and crops out the product ----------
    const readBtn = document.getElementById('read-photo');
    const undoCrop = document.getElementById('undo-crop');
    const photoStatus = document.getElementById('photo-status');
    let originalShot = null;    // the picture as chosen, so a crop can be undone
    let swapping = false;       // true while we replace the file ourselves

    function photoMsg(kind, html) {
        photoStatus.className = `link-status small ${kind}`;
        photoStatus.innerHTML = html;
    }

    function setFile(file) {
        const transfer = new DataTransfer();
        transfer.items.add(file);
        swapping = true;
        fileInput.files = transfer.files;
        fileInput.dispatchEvent(new Event('change'));   // dropzone redraws its preview
        swapping = false;
    }

    async function readPhoto() {
        const file = originalShot || (fileInput && fileInput.files[0]);
        if (!file) return;
        const controller = new AbortController();
        photoMsg('busy', '<i data-lucide="loader-circle" class="icon-spin"></i> Reading your picture… this can take a few seconds');
        setBusy(true, photoStatus, () => { controller.cancelled = true; controller.abort(); });
        const body = new FormData();
        body.append('image', file);
        try {
            const r = await csrfFetch(form.dataset.screenshotUrl, { body, signal: controller.signal });
            const data = await r.json();
            if (!data.ok) {
                photoMsg('warn', `<i data-lucide="info"></i> ${data.message} The picture will still be saved as the photo.`);
                return;
            }
            const f = data.fields;
            const filled = [];
            if (fill('name', f.name)) filled.push('name');
            if (fill('price', f.price)) filled.push('price');
            if (fill('color', f.color)) filled.push('color');
            if (fill('size', f.size)) filled.push('size');
            if (data.cropped) {
                const blob = await (await fetch(data.cropped)).blob();
                setFile(new File([blob], 'product.jpg', { type: 'image/jpeg' }));
                filled.push('photo (cropped from your picture)');
                undoCrop.classList.remove('d-none');
            }
            photoMsg('ok', filled.length
                ? `<i data-lucide="circle-check"></i> Filled in ${filled.join(', ')} - please check it, especially the price.`
                : '<i data-lucide="circle-check"></i> Read your picture - your own entries were kept.');
        } catch (e) {
            if (e.name === 'AbortError' && controller.cancelled) {
                photoMsg('warn', '<i data-lucide="ban"></i> Cancelled - the picture will still be saved as the photo.');
                return;
            }
            photoMsg('warn', '<i data-lucide="info"></i> Couldn\'t read that picture - please fill it in below.');
        } finally {
            setBusy(false);
        }
    }

    if (fileInput && readBtn) {
        fileInput.addEventListener('change', () => {
            if (swapping) return;
            const file = fileInput.files[0];
            originalShot = file || null;
            undoCrop.classList.add('d-none');
            photoStatus.innerHTML = '';
            readBtn.classList.toggle('d-none', !file);
            // Nothing typed yet? It's probably a screenshot of the thing they want - read it straight away
            if (file && !fields.name.value.trim() && !urlInput.value.trim()) readPhoto();
        });
        readBtn.addEventListener('click', readPhoto);
        undoCrop.addEventListener('click', () => {
            if (!originalShot) return;
            setFile(originalShot);
            undoCrop.classList.add('d-none');
            photoMsg('ok', 'Using the whole picture as the photo.');
        });
    }
})();
