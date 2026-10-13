(function () {
    const root = document.documentElement;
    const toggle = document.querySelector('[data-sidebar-toggle]');
    const burger = document.querySelector('[data-sidebar-open]');
    const backdrop = document.querySelector('[data-sidebar-close]');
    const mobile = window.matchMedia('(max-width: 767.98px)');

    function setCollapsed(collapsed) {
        root.classList.toggle('sidebar-collapsed', collapsed);
        toggle.setAttribute('aria-expanded', String(!collapsed));
        toggle.setAttribute('aria-label', collapsed ? 'Развернуть меню' : 'Свернуть меню');
        try { localStorage.setItem('sidebar-collapsed', collapsed ? '1' : '0'); } catch (e) {}
    }

    function setOpen(open) {
        root.classList.toggle('sidebar-open', open);
        if (burger) burger.setAttribute('aria-expanded', String(open));
    }

    if (toggle) {
        const collapsed = root.classList.contains('sidebar-collapsed');
        toggle.setAttribute('aria-expanded', String(!collapsed));
        toggle.setAttribute('aria-label', collapsed ? 'Развернуть меню' : 'Свернуть меню');

        toggle.addEventListener('click', function () {
            // На телефоне эта кнопка закрывает выезжающую панель
            if (mobile.matches) {
                setOpen(false);
            } else {
                setCollapsed(!root.classList.contains('sidebar-collapsed'));
            }
        });
    }

    if (burger) burger.addEventListener('click', function () { setOpen(true); });
    if (backdrop) backdrop.addEventListener('click', function () { setOpen(false); });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') setOpen(false);
    });

    mobile.addEventListener('change', function () { setOpen(false); });

    // ---------- Навигация через htmx ----------

    const content = document.getElementById('page-content');

    function markActive(path) {
        // Список ищем заново — история в сайдбаре перерисовывается
        document.querySelectorAll('[data-nav].nav-btn').forEach(function (link) {
            link.classList.toggle('active', new URL(link.href).pathname === path);
        });
    }

    function playBeam() {
        content.classList.remove('is-entering');
        void content.offsetWidth; // перезапуск анимации
        content.classList.add('is-entering');
    }

    if (content) {
        content.addEventListener('animationend', function (e) {
            if (e.target === content) content.classList.remove('is-entering');
        });
    }

    document.body.addEventListener('htmx:beforeRequest', function (e) {
        if (e.detail.elt.closest('#sidebar')) setOpen(false);
    });

    document.body.addEventListener('htmx:afterSwap', function (e) {
        if (e.detail.target === content) {
            markActive(new URL(e.detail.pathInfo.requestPath, location.origin).pathname);
            playBeam();
        }
    });

    // История в сайдбаре обновилась — подсвечиваем текущий чат
    document.body.addEventListener('htmx:afterSettle', function (e) {
        if (e.detail.elt && e.detail.elt.id === 'chat-history') markActive(location.pathname);
    });

    // ---------- Модальное окно профиля ----------

    const profileModal = document.getElementById('profile-modal');
    const profileContent = document.getElementById('profile-modal-content');
    const placeholder = document.getElementById('modal-placeholder');

    function resetProfileModal() {
        if (profileContent && placeholder) profileContent.innerHTML = placeholder.innerHTML;
    }

    if (profileModal) {
        resetProfileModal();
        profileModal.addEventListener('hidden.bs.modal', resetProfileModal);
    }

    // Запоминаем открытую вкладку, чтобы после сохранения вернуться на неё
    document.addEventListener('shown.bs.tab', function (e) {
        const form = e.target.closest('form');
        const input = form && form.querySelector('[data-active-tab]');
        if (input) input.value = e.target.dataset.tabName;
    });

    // Предпросмотр выбранного аватара до сохранения
    document.addEventListener('change', function (e) {
        const input = e.target;
        if (!input.matches('.profile-form input[type="file"]') || !input.files.length) return;
        const preview = input.closest('form').querySelector('[data-avatar-preview]');
        if (!preview) return;
        const img = document.createElement('img');
        img.alt = '';
        img.src = URL.createObjectURL(input.files[0]);
        preview.replaceChildren(img);
        preview.classList.remove('is-updated');
        void preview.offsetWidth;
        preview.classList.add('is-updated');
    });
})();
