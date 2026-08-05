(function () {
    const config = window.HOME_CONFIG || {};
    const modals = {
        login: document.getElementById("loginModal"),
        register: document.getElementById("registerModal"),
    };

    function openModal(name) {
        const modal = modals[name];
        if (!modal) return;
        closeAllModals();
        modal.classList.add("active");
        modal.setAttribute("aria-hidden", "false");
        document.body.classList.add("modal-open");
    }

    function closeAllModals() {
        Object.values(modals).forEach(function (modal) {
            if (!modal) return;
            modal.classList.remove("active");
            modal.setAttribute("aria-hidden", "true");
        });
        document.body.classList.remove("modal-open");
    }

    function showTip(el, message, type) {
        if (!el) return;
        el.textContent = message;
        el.style.display = message ? "block" : "none";
        if (type === "success") {
            el.className = "modal-tip modal-tip-success";
        } else if (type === "error") {
            el.className = "modal-tip modal-tip-error";
        }
    }

    function clearTips() {
        showTip(document.getElementById("loginError"), "");
        showTip(document.getElementById("registerError"), "");
        showTip(document.getElementById("registerSuccess"), "");
    }

    document.querySelectorAll("[data-modal]").forEach(function (el) {
        el.addEventListener("click", function (e) {
            e.preventDefault();
            openModal(el.dataset.modal);
        });
    });

    document.querySelectorAll("[data-switch-modal]").forEach(function (el) {
        el.addEventListener("click", function () {
            clearTips();
            openModal(el.dataset.switchModal);
        });
    });

    document.querySelectorAll("[data-close-modal]").forEach(function (el) {
        el.addEventListener("click", closeAllModals);
    });

    Object.values(modals).forEach(function (modal) {
        if (!modal) return;
        modal.addEventListener("click", function (e) {
            if (e.target === modal) closeAllModals();
        });
    });

    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") {
            closeAllModals();
            closeAccountMenu();
        }
    });

    /* 账户菜单：触控端点按切换；桌面仍可用 CSS hover，点击也可开关 */
    const account = document.querySelector(".account");
    const avatar = account && account.querySelector(".avatar");

    function closeAccountMenu() {
        if (account) account.classList.remove("is-open");
    }

    if (account && avatar) {
        avatar.addEventListener("click", function (e) {
            e.stopPropagation();
            account.classList.toggle("is-open");
        });

        document.addEventListener("click", function (e) {
            if (!account.contains(e.target)) closeAccountMenu();
        });
    }

    const tryMbtiBtn = document.getElementById("tryMbtiBtn");
    if (tryMbtiBtn) {
        tryMbtiBtn.addEventListener("click", function () {
            openModal("login");
        });
    }

    const loginForm = document.getElementById("loginForm");
    if (loginForm) {
        loginForm.addEventListener("submit", function (e) {
            e.preventDefault();
            const errorTip = document.getElementById("loginError");
            showTip(errorTip, "", "error");

            const username = document.getElementById("loginUsername").value.trim();
            const password = document.getElementById("loginPassword").value.trim();

            fetch("/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username: username, password: password }),
            })
                .then(function (res) { return res.json(); })
                .then(function (resp) {
                    if (resp.success) {
                        window.location.href = "/trade";
                    } else {
                        showTip(errorTip, resp.message, "error");
                    }
                })
                .catch(function () {
                    showTip(errorTip, "请求异常，请检查服务是否启动", "error");
                });
        });
    }

    const registerForm = document.getElementById("registerForm");
    if (registerForm) {
        registerForm.addEventListener("submit", function (e) {
            e.preventDefault();
            const errorTip = document.getElementById("registerError");
            const successTip = document.getElementById("registerSuccess");
            showTip(errorTip, "", "error");
            showTip(successTip, "", "success");

            const username = document.getElementById("registerUsername").value.trim();
            const password = document.getElementById("registerPassword").value.trim();
            const password2 = document.getElementById("registerPassword2").value.trim();

            if (!username || !password || !password2) {
                showTip(errorTip, "账号和密码不能为空", "error");
                return;
            }
            if (password !== password2) {
                showTip(errorTip, "两次输入的密码不一致", "error");
                return;
            }

            fetch("/register", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username: username, password: password }),
            })
                .then(function (res) { return res.json(); })
                .then(function (resp) {
                    if (resp.success) {
                        registerForm.reset();
                        openModal("login");
                        showTip(document.getElementById("loginError"), "注册成功，请登录", "success");
                    } else {
                        showTip(errorTip, resp.message, "error");
                    }
                })
                .catch(function () {
                    showTip(errorTip, "网络请求失败，请检查服务", "error");
                });
        });
    }

    if (config.openModal && !config.isLogin) {
        openModal(config.openModal);
    }
})();
