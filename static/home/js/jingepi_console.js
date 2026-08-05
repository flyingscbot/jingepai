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

    loadUsers();
})();
