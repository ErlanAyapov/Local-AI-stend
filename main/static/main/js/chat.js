(function () {
    const chat = document.querySelector('.chat');
    if (!chat) return;

    const form = chat.querySelector('[data-chat-form]');
    const input = chat.querySelector('[data-chat-input]');
    const sendBtn = chat.querySelector('[data-chat-send]');
    const messages = chat.querySelector('[data-chat-messages]');
    const deleteBtn = chat.querySelector('[data-chat-delete]');
    const titleEl = chat.querySelector('[data-chat-title]');
    const statusText = chat.querySelector('.status-text');
    const apiInput = chat.querySelector('[data-chat-api]');
    const modelInput = chat.querySelector('[data-chat-model]');
    const modelLabels = chat.querySelectorAll('[data-model-label]');
    const modelMenu = chat.querySelector('[data-model-menu]');
    const aiAvatar = chat.dataset.aiAvatar;

    let busy = false;

    // ---------- Markdown ----------

    let md = null;

    // Библиотеки ищем при каждом рендере, а не один раз при запуске скрипта
    function getMarkdown() {
        if (!md && window.marked) {
            md = new window.marked.Marked({ gfm: true, breaks: true });
            if (window.hljs) window.hljs.configure({ ignoreUnescapedHTML: true });
        }
        return md;
    }

    // Ответ модели — недоверенный текст: Markdown → HTML → очистка DOMPurify
    function renderMarkdown(el, text, final) {
        const md = getMarkdown();
        if (!md || !window.DOMPurify) {
            el.textContent = text;
            return;
        }
        el.classList.add('markdown');
        el.innerHTML = window.DOMPurify.sanitize(md.parse(text));
        if (final) enhanceMarkdown(el);
    }

    function enhanceMarkdown(el) {
        el.querySelectorAll('a[href]').forEach(function (a) {
            a.target = '_blank';
            a.rel = 'noopener noreferrer';
        });

        el.querySelectorAll('pre > code').forEach(function (code) {
            const pre = code.parentElement;
            if (pre.parentElement.classList.contains('code-block')) return;
            if (window.hljs) window.hljs.highlightElement(code);

            const lang = (code.className.match(/language-([\w+#.-]+)/) || [])[1] || 'code';
            const block = document.createElement('div');
            block.className = 'code-block';
            const head = document.createElement('div');
            head.className = 'code-head';
            const label = document.createElement('span');
            label.textContent = lang;
            const copy = document.createElement('button');
            copy.type = 'button';
            copy.className = 'code-copy';
            copy.textContent = 'Копировать';
            copy.addEventListener('click', function () {
                navigator.clipboard.writeText(code.textContent).then(function () {
                    copy.textContent = 'Скопировано';
                    copy.classList.add('is-done');
                    setTimeout(function () {
                        copy.textContent = 'Копировать';
                        copy.classList.remove('is-done');
                    }, 1500);
                });
            });
            head.append(label, copy);
            pre.replaceWith(block);
            block.append(head, pre);
        });
    }

    messages.querySelectorAll('.msg-bubble[data-markdown]').forEach(function (el) {
        renderMarkdown(el, el.textContent, true);
    });

    // ---------- Выбор модели ----------

    function setLabels(text, animate) {
        modelLabels.forEach(function (label) {
            label.textContent = text;
            if (animate) {
                label.classList.remove('model-switched');
                void label.offsetWidth;
                label.classList.add('model-switched');
            }
        });
    }

    function selectModel(option, animate) {
        modelMenu.querySelectorAll('.model-option').forEach(function (o) {
            o.classList.toggle('active', o === option);
        });
        apiInput.value = option.dataset.apiId;
        modelInput.value = option.dataset.modelId;
        setLabels(option.dataset.modelId, animate);
        try { localStorage.setItem('chat-model', option.dataset.key); } catch (e) {}
        autosize();
    }

    // Меню моделей подгружается htmx — после загрузки выбираем модель:
    // модель этого чата → последняя выбранная → первая в списке
    function applyModelOptions() {
        const options = modelMenu.querySelectorAll('.model-option');
        if (!options.length) {
            apiInput.value = '';
            modelInput.value = '';
            setLabels('Нет моделей', false);
            autosize();
            return;
        }
        let saved = '';
        try { saved = localStorage.getItem('chat-model') || ''; } catch (e) {}
        const keys = [modelInput.value && apiInput.value + ':' + modelInput.value, chat.dataset.selected, saved];
        let option = null;
        for (const key of keys) {
            if (!key) continue;
            option = modelMenu.querySelector('.model-option[data-key="' + CSS.escape(key) + '"]');
            if (option) break;
        }
        selectModel(option || options[0], false);
    }

    modelMenu.addEventListener('htmx:afterSettle', applyModelOptions);

    modelMenu.addEventListener('click', function (e) {
        const option = e.target.closest('.model-option');
        if (option) selectModel(option, true);
    });

    // ---------- Сообщения ----------

    function autosize() {
        input.style.height = 'auto';
        input.style.height = input.scrollHeight + 'px';
        sendBtn.disabled = busy || !input.value.trim() || !modelInput.value;
    }

    function scrollDown() {
        messages.scrollTop = messages.scrollHeight;
    }

    function createMessage(role, text, meta) {
        const msg = document.createElement('div');
        msg.className = 'msg ' + (role === 'user' ? 'msg-user' : 'msg-ai');

        if (role !== 'user') {
            const avatar = document.createElement('div');
            avatar.className = 'msg-avatar';
            const img = document.createElement('img');
            img.src = aiAvatar;
            img.alt = '';
            avatar.appendChild(img);
            msg.appendChild(avatar);
        }

        const body = document.createElement('div');
        body.className = 'msg-body';

        const metaEl = document.createElement('div');
        metaEl.className = 'msg-meta';
        metaEl.textContent = meta;

        const bubble = document.createElement('div');
        bubble.className = 'msg-bubble';
        bubble.textContent = text;

        body.append(metaEl, bubble);
        msg.appendChild(body);
        messages.appendChild(msg);
        scrollDown();
        return bubble;
    }

    // Печатает ответ как терминал, сразу с разметкой (длинные ответы — быстрее)
    function typeText(bubble, text) {
        return new Promise(function (resolve) {
            bubble.textContent = '';
            bubble.classList.add('is-typing');
            const step = Math.max(2, Math.ceil(text.length / 300));
            let i = 0;
            const timer = setInterval(function () {
                i = Math.min(text.length, i + step);
                const done = i >= text.length || !bubble.isConnected;
                renderMarkdown(bubble, done ? text : text.slice(0, i), done);
                scrollDown();
                if (done) {
                    clearInterval(timer);
                    bubble.classList.remove('is-typing');
                    resolve();
                }
            }, 16);
        });
    }

    // Расход токенов рядом с именем модели
    function showUsage(bubble, usage) {
        const meta = bubble.closest('.msg').querySelector('.msg-meta');
        const span = document.createElement('span');
        span.className = 'msg-tokens';
        span.title = 'Входные / выходные токены' + (usage.estimated ? ' (оценка)' : '');
        span.textContent = '↑' + usage.prompt_tokens + ' ↓' + usage.completion_tokens + (usage.estimated ? '~' : '');
        meta.appendChild(span);
    }

    function setThinking(on) {
        chat.classList.toggle('is-thinking', on);
        statusText.textContent = on ? 'обработка' : 'онлайн';
    }

    // Первое сообщение создало чат — превращаем страницу в страницу этого чата
    function onChatCreated(data) {
        chat.dataset.sendUrl = data.send_url;
        titleEl.textContent = data.title;
        document.title = data.title + ' — AI Sci-Fi';
        history.replaceState(history.state, '', data.chat_url);

        deleteBtn.setAttribute('hx-post', data.delete_url);
        deleteBtn.setAttribute('hx-confirm', 'Удалить этот чат?');
        deleteBtn.hidden = false;
        htmx.process(deleteBtn);

        htmx.trigger(document.body, 'chatsChanged');
    }

    async function send(text) {
        text = text.trim();
        if (!text || busy || !modelInput.value) return;

        busy = true;
        setThinking(true);

        const suggestions = messages.querySelector('[data-chat-suggestions]');
        if (suggestions) suggestions.remove();

        const body = new FormData(form);
        body.set('message', text);

        createMessage('user', text, 'Вы');
        input.value = '';
        autosize();

        const bubble = createMessage('ai', '', modelInput.value);
        bubble.innerHTML = '<span class="thinking"><span></span><span></span><span></span></span>';

        let data;
        try {
            const response = await fetch(chat.dataset.sendUrl, {
                method: 'POST',
                body: body,
                headers: { 'Accept': 'application/json' },
                credentials: 'same-origin',
            });
            data = await response.json();
        } catch (e) {
            data = { ok: false, error: 'Сервер недоступен. Проверьте соединение.' };
        }

        if (data.created) onChatCreated(data);

        if (data.ok) {
            if (data.usage) showUsage(bubble, data.usage);
            await typeText(bubble, data.reply);
        } else {
            bubble.textContent = data.error || 'Неизвестная ошибка';
            bubble.closest('.msg').classList.add('msg-error');
        }

        busy = false;
        setThinking(false);
        autosize();
        input.focus();
    }

    form.addEventListener('submit', function (e) {
        e.preventDefault();
        send(input.value);
    });

    input.addEventListener('input', autosize);

    input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
            e.preventDefault();
            send(input.value);
        }
    });

    messages.addEventListener('click', function (e) {
        const chip = e.target.closest('.chip');
        if (chip) send(chip.textContent);
    });

    scrollDown();
    autosize();
})();
