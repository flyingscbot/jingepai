(function () {
    "use strict";

    var mainEl = document.querySelector(".console-main");
    var isSuperAdmin =
        mainEl && mainEl.getAttribute("data-is-super-admin") === "1";
    var tbody = document.getElementById("usersTbody");
    var searchInput = document.getElementById("searchInput");
    var listMeta = document.getElementById("listMeta");
    var listTip = document.getElementById("listTip");
    var createModal = document.getElementById("createModal");
    var editModal = document.getElementById("editModal");
    var searchTimer = null;

    function tip(el, text, ok) {
        if (!el) return;
        el.textContent = text || "";
        el.className = "settings-tip" + (text ? (ok ? " is-ok" : " is-err") : "");
    }

    function openModal(el) {
        if (!el) return;
        el.classList.add("active");
        el.setAttribute("aria-hidden", "false");
    }

    function closeModal(el) {
        if (!el) return;
        el.classList.remove("active");
        el.setAttribute("aria-hidden", "true");
    }

    function closeAllModals() {
        closeModal(createModal);
        closeModal(editModal);
    }

    function escapeHtml(s) {
        return String(s == null ? "" : s)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function rolePill(role) {
        if (role === "super_admin") {
            return '<span class="console-pill console-pill-super" data-role="super_admin">最高管理</span>';
        }
        if (role === "admin") {
            return '<span class="console-pill console-pill-admin" data-role="admin">普通管理</span>';
        }
        return '<span class="console-pill console-pill-user" data-role="user">用户</span>';
    }

    function statusPill(active) {
        if (active) {
            return '<span class="console-pill console-pill-on">启用</span>';
        }
        return '<span class="console-pill console-pill-off">停用</span>';
    }

    function actionButtons(u) {
        var parts = [];
        if (isSuperAdmin) {
            parts.push('<button type="button" data-action="edit">编辑</button>');
            if (u.is_active) {
                parts.push(
                    '<button type="button" data-action="deactivate">停用</button>'
                );
            } else {
                parts.push(
                    '<button type="button" data-action="activate">启用</button>'
                );
            }
            parts.push(
                '<button type="button" class="is-danger" data-action="delete">删除</button>'
            );
            return parts.join("");
        }
        // 普通管理：仅可对 user 启停 / 重置密码
        if (u.role !== "user") {
            return '<span class="console-muted">—</span>';
        }
        parts.push(
            '<button type="button" data-action="reset-password">重置密码</button>'
        );
        if (u.is_active) {
            parts.push(
                '<button type="button" data-action="deactivate">停用</button>'
            );
        } else {
            parts.push(
                '<button type="button" data-action="activate">启用</button>'
            );
        }
        return parts.join("");
    }

    function api(url, options) {
        options = options || {};
        options.headers = Object.assign(
            { Accept: "application/json" },
            options.headers || {}
        );
        if (options.body && typeof options.body !== "string") {
            options.headers["Content-Type"] = "application/json";
            options.body = JSON.stringify(options.body);
        }
        return fetch(url, options).then(function (res) {
            return res
                .json()
                .catch(function () {
                    return {
                        success: false,
                        message: "响应解析失败 (" + res.status + ")",
                    };
                })
                .then(function (data) {
                    data._http = res.status;
                    return data;
                });
        });
    }

    function renderUsers(users) {
        if (!tbody) return;
        if (!users || !users.length) {
            tbody.innerHTML =
                '<tr><td colspan="6" class="console-empty">暂无匹配用户</td></tr>';
            return;
        }
        tbody.innerHTML = users
            .map(function (u) {
                return (
                    "<tr data-id=\"" +
                    escapeHtml(u.id) +
                    "\" data-role=\"" +
                    escapeHtml(u.role || "user") +
                    "\">" +
                    "<td>" +
                    escapeHtml(u.username) +
                    "</td>" +
                    "<td>" +
                    rolePill(u.role) +
                    "</td>" +
                    "<td>" +
                    statusPill(!!u.is_active) +
                    "</td>" +
                    "<td>" +
                    escapeHtml(u.created_at || "—") +
                    "</td>" +
                    "<td><div class=\"console-id\" title=\"" +
                    escapeHtml(u.id) +
                    "\">" +
                    escapeHtml(u.id) +
                    "</div></td>" +
                    "<td><div class=\"console-actions\">" +
                    actionButtons(u) +
                    "</div></td>" +
                    "</tr>"
                );
            })
            .join("");
    }

    function loadUsers() {
        var q = (searchInput && searchInput.value) || "";
        var url = "/api/admin/users";
        if (q.trim()) {
            url += "?q=" + encodeURIComponent(q.trim());
        }
        tip(listTip, "");
        return api(url)
            .then(function (data) {
                if (!data.success) {
                    tip(listTip, data.message || "加载失败", false);
                    if (listMeta) listMeta.textContent = "加载失败";
                    tbody.innerHTML =
                        '<tr><td colspan="6" class="console-empty">无法加载用户列表</td></tr>';
                    return;
                }
                renderUsers(data.users || []);
                if (listMeta) {
                    listMeta.textContent = "共 " + (data.total || 0) + " 位用户";
                }
            })
            .catch(function () {
                tip(listTip, "网络错误", false);
            });
    }

    function findUserInRow(btn) {
        var tr = btn.closest("tr");
        if (!tr) return null;
        var rolePillEl = tr.querySelector("[data-role]");
        return {
            id: tr.getAttribute("data-id"),
            username: (tr.cells[0] && tr.cells[0].textContent) || "",
            role:
                tr.getAttribute("data-role") ||
                (rolePillEl && rolePillEl.getAttribute("data-role")) ||
                "user",
            is_active: !!tr.querySelector(".console-pill-on"),
        };
    }

    document.getElementById("btnRefresh") &&
        document.getElementById("btnRefresh").addEventListener("click", loadUsers);

    document.getElementById("btnCreateUser") &&
        document.getElementById("btnCreateUser").addEventListener("click", function () {
            var err = document.getElementById("createError");
            if (err) err.textContent = "";
            var form = document.getElementById("createForm");
            if (form) form.reset();
            var roleEl = document.getElementById("createRole");
            if (roleEl && roleEl.tagName === "INPUT") {
                roleEl.value = "user";
            }
            openModal(createModal);
        });

    document.querySelectorAll("[data-close-console-modal]").forEach(function (btn) {
        btn.addEventListener("click", closeAllModals);
    });

    [createModal, editModal].forEach(function (modal) {
        if (!modal) return;
        modal.addEventListener("click", function (e) {
            if (e.target === modal) closeAllModals();
        });
    });

    if (searchInput) {
        searchInput.addEventListener("input", function () {
            clearTimeout(searchTimer);
            searchTimer = setTimeout(loadUsers, 280);
        });
    }

    if (tbody) {
        tbody.addEventListener("click", function (e) {
            var btn = e.target.closest("button[data-action]");
            if (!btn) return;
            var user = findUserInRow(btn);
            if (!user || !user.id) return;
            var action = btn.getAttribute("data-action");

            if (action === "edit") {
                if (!isSuperAdmin || !editModal) return;
                document.getElementById("editError").textContent = "";
                document.getElementById("editUserId").value = user.id;
                document.getElementById("editUsername").value = user.username;
                document.getElementById("editPassword").value = "";
                document.getElementById("editRole").value = user.role;
                document.getElementById("editActive").value = user.is_active ? "1" : "0";
                document.getElementById("editSubtitle").textContent =
                    "正在编辑：" + user.username;
                openModal(editModal);
                return;
            }

            if (action === "deactivate") {
                if (
                    !window.confirm(
                        "确认停用账号「" + user.username + "」？停用后无法登录。"
                    )
                ) {
                    return;
                }
                api("/api/admin/users/" + encodeURIComponent(user.id), {
                    method: "PATCH",
                    body: { is_active: false },
                }).then(function (data) {
                    tip(
                        listTip,
                        data.message || (data.success ? "已停用" : "失败"),
                        !!data.success
                    );
                    loadUsers();
                });
                return;
            }

            if (action === "activate") {
                api("/api/admin/users/" + encodeURIComponent(user.id), {
                    method: "PATCH",
                    body: { is_active: true },
                }).then(function (data) {
                    tip(
                        listTip,
                        data.message || (data.success ? "已启用" : "失败"),
                        !!data.success
                    );
                    loadUsers();
                });
                return;
            }

            if (action === "reset-password") {
                var pw = window.prompt(
                    "为「" + user.username + "」设置新密码（至少 6 位）：",
                    ""
                );
                if (pw == null) return;
                pw = String(pw);
                if (pw.length < 6) {
                    tip(listTip, "密码至少 6 位", false);
                    return;
                }
                api("/api/admin/users/" + encodeURIComponent(user.id), {
                    method: "PATCH",
                    body: { password: pw },
                }).then(function (data) {
                    tip(
                        listTip,
                        data.message || (data.success ? "密码已重置" : "失败"),
                        !!data.success
                    );
                    loadUsers();
                });
                return;
            }

            if (action === "delete") {
                if (!isSuperAdmin) return;
                if (
                    !window.confirm(
                        "确认永久删除账号「" +
                            user.username +
                            "」？此操作不可恢复，将从数据库移除。"
                    )
                ) {
                    return;
                }
                api("/api/admin/users/" + encodeURIComponent(user.id), {
                    method: "DELETE",
                }).then(function (data) {
                    tip(
                        listTip,
                        data.message || (data.success ? "已删除" : "失败"),
                        !!data.success
                    );
                    loadUsers();
                });
            }
        });
    }

    var createForm = document.getElementById("createForm");
    if (createForm) {
        createForm.addEventListener("submit", function (e) {
            e.preventDefault();
            var err = document.getElementById("createError");
            err.textContent = "";
            var roleEl = document.getElementById("createRole");
            api("/api/admin/users", {
                method: "POST",
                body: {
                    username: document.getElementById("createUsername").value,
                    password: document.getElementById("createPassword").value,
                    role: roleEl ? roleEl.value : "user",
                },
            }).then(function (data) {
                if (!data.success) {
                    err.textContent = data.message || "创建失败";
                    return;
                }
                closeAllModals();
                tip(listTip, data.message || "已创建", true);
                loadUsers();
            });
        });
    }

    var editForm = document.getElementById("editForm");
    if (editForm) {
        editForm.addEventListener("submit", function (e) {
            e.preventDefault();
            var err = document.getElementById("editError");
            err.textContent = "";
            var id = document.getElementById("editUserId").value;
            var body = {
                username: document.getElementById("editUsername").value,
                role: document.getElementById("editRole").value,
                is_active: document.getElementById("editActive").value === "1",
            };
            var pw = document.getElementById("editPassword").value;
            if (pw) body.password = pw;
            api("/api/admin/users/" + encodeURIComponent(id), {
                method: "PATCH",
                body: body,
            }).then(function (data) {
                if (!data.success) {
                    err.textContent = data.message || "保存失败";
                    return;
                }
                closeAllModals();
                tip(listTip, data.message || "已更新", true);
                loadUsers();
            });
        });
    }

    function switchTab(tabId) {
        document.querySelectorAll(".console-tab").forEach(function (btn) {
            var on = btn.getAttribute("data-tab") === tabId;
            btn.classList.toggle("is-active", on);
            btn.setAttribute("aria-selected", on ? "true" : "false");
        });
        document.querySelectorAll(".console-tab-panel").forEach(function (panel) {
            var on = panel.getAttribute("data-tab-panel") === tabId;
            panel.classList.toggle("is-active", on);
            if (on) {
                panel.removeAttribute("hidden");
            } else {
                panel.setAttribute("hidden", "");
            }
        });
        var createBtn = document.getElementById("btnCreateUser");
        if (createBtn) {
            createBtn.style.display = tabId === "users" ? "" : "none";
        }
        // Matrix 主题 Tab 已从控制台 UI 隐藏；API 仍可用，见 ADMIN.txt
        if (tabId === "matrix-theme") {
            loadTheme();
        }
    }

    document.querySelectorAll(".console-tab").forEach(function (btn) {
        btn.addEventListener("click", function () {
            switchTab(btn.getAttribute("data-tab"));
        });
    });

    function normalizeHexInput(v) {
        var s = String(v || "").trim();
        if (!s) return "";
        if (s.charAt(0) !== "#") s = "#" + s;
        if (/^#[0-9a-fA-F]{3}$/.test(s)) {
            s =
                "#" +
                s.charAt(1) +
                s.charAt(1) +
                s.charAt(2) +
                s.charAt(2) +
                s.charAt(3) +
                s.charAt(3);
        }
        if (!/^#[0-9a-fA-F]{6}$/.test(s)) return "";
        return s.toLowerCase();
    }

    function syncThemeRowPreview(row) {
        var hex = row.querySelector(".theme-hex");
        var picker = row.querySelector(".theme-picker");
        var swatch = row.querySelector(".theme-swatch");
        var norm = normalizeHexInput(hex && hex.value);
        if (!norm) return;
        if (hex) hex.value = norm;
        if (picker) picker.value = norm;
        if (swatch) swatch.style.background = norm;
    }

    function renderTheme(items) {
        var root = document.getElementById("themeGroups");
        var meta = document.getElementById("themeMeta");
        if (!root) return;
        if (!items || !items.length) {
            root.innerHTML = '<p class="console-empty">暂无主题色</p>';
            return;
        }
        var byGroup = {};
        var order = [];
        items.forEach(function (it) {
            var g = it.group || "accent";
            if (!byGroup[g]) {
                byGroup[g] = [];
                order.push({ id: g, label: it.group_label || g });
            }
            byGroup[g].push(it);
        });
        root.innerHTML = order
            .map(function (g) {
                var rows = byGroup[g.id]
                    .map(function (it) {
                        var val = escapeHtml(it.value || it.default || "#000000");
                        return (
                            '<tr class="theme-row" data-key="' +
                            escapeHtml(it.key) +
                            '">' +
                            "<td>" +
                            escapeHtml(it.label) +
                            '<div class="theme-key">' +
                            escapeHtml(it.css || it.key) +
                            "</div></td>" +
                            '<td><input type="color" class="theme-picker" value="' +
                            val +
                            '" aria-label="' +
                            escapeHtml(it.label) +
                            '"></td>' +
                            '<td><input type="text" class="theme-hex settings-input" maxlength="7" value="' +
                            val +
                            '" spellcheck="false"></td>' +
                            '<td><span class="theme-swatch" style="background:' +
                            val +
                            '"></span></td>' +
                            "</tr>"
                        );
                    })
                    .join("");
                return (
                    '<div class="theme-group">' +
                    "<h4>" +
                    escapeHtml(g.label) +
                    "</h4>" +
                    '<div class="console-table-scroll"><table class="console-table theme-table">' +
                    "<thead><tr><th>名称</th><th>取色</th><th>十六进制</th><th>预览</th></tr></thead>" +
                    "<tbody>" +
                    rows +
                    "</tbody></table></div></div>"
                );
            })
            .join("");
        if (meta) {
            meta.textContent = "共 " + items.length + " 项可调颜色";
        }
    }

    function collectThemeColors() {
        var colors = {};
        var bad = null;
        document.querySelectorAll(".theme-row").forEach(function (row) {
            var key = row.getAttribute("data-key");
            var hex = row.querySelector(".theme-hex");
            var norm = normalizeHexInput(hex && hex.value);
            if (!norm) {
                bad = key;
                return;
            }
            colors[key] = norm;
        });
        if (bad) {
            return { error: "颜色「" + bad + "」格式无效，请使用 #RRGGBB" };
        }
        return { colors: colors };
    }

    function loadTheme() {
        var themeTip = document.getElementById("themeTip");
        tip(themeTip, "");
        return api("/api/admin/matrix-theme")
            .then(function (data) {
                if (!data.success) {
                    tip(themeTip, data.message || "加载失败", false);
                    return;
                }
                renderTheme(data.items || []);
            })
            .catch(function () {
                tip(themeTip, "网络错误", false);
            });
    }

    var themeGroups = document.getElementById("themeGroups");
    if (themeGroups) {
        themeGroups.addEventListener("input", function (e) {
            var t = e.target;
            var row = t.closest(".theme-row");
            if (!row) return;
            if (t.classList.contains("theme-picker")) {
                var hex = row.querySelector(".theme-hex");
                if (hex) hex.value = t.value;
                syncThemeRowPreview(row);
            } else if (t.classList.contains("theme-hex")) {
                var norm = normalizeHexInput(t.value);
                if (norm) {
                    t.value = norm;
                    syncThemeRowPreview(row);
                }
            }
        });
    }

    document.getElementById("btnThemeSave") &&
        document.getElementById("btnThemeSave").addEventListener("click", function () {
            var themeTip = document.getElementById("themeTip");
            var packed = collectThemeColors();
            if (packed.error) {
                tip(themeTip, packed.error, false);
                return;
            }
            api("/api/admin/matrix-theme", {
                method: "PUT",
                body: { colors: packed.colors },
            }).then(function (data) {
                tip(
                    themeTip,
                    data.message || (data.success ? "已保存" : "保存失败"),
                    !!data.success
                );
                if (data.success && data.items) {
                    renderTheme(data.items);
                }
            });
        });

    document.getElementById("btnThemeReset") &&
        document.getElementById("btnThemeReset").addEventListener("click", function () {
            if (!window.confirm("确认恢复全部主题色为默认值？")) return;
            var themeTip = document.getElementById("themeTip");
            api("/api/admin/matrix-theme/reset", { method: "POST", body: {} }).then(
                function (data) {
                    tip(
                        themeTip,
                        data.message || (data.success ? "已恢复默认" : "失败"),
                        !!data.success
                    );
                    if (data.success && data.items) {
                        renderTheme(data.items);
                    }
                }
            );
        });

    loadUsers();
})();
