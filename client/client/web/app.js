/* ═══════════════════════════════════════════════════
   Prompt Library — Client Logic (clean rebuild)
   ═══════════════════════════════════════════════════ */

// ─── State ───
const state = {
    token: localStorage.getItem("token"),
    username: localStorage.getItem("username"),
    userId: null,
    currentScreen: "welcome",
    currentFilter: "All",
    editingPromptId: null,
};

const MODELS = {
    Image: ["Midjourney", "DALL·E 3", "Stable Diffusion", "Ideogram", "Flux", "Other"],
    Video: ["Runway Gen-3", "Sora", "Pika", "Kling", "Luma Dream Machine", "Other"],
};

// ─── Debounce helper ───
let _searchTimer;
function debounceSearch() {
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(() => App.loadPrompts(), 300);
}

// ─── API helper ───
function api(url, opts = {}) {
    const headers = opts.headers || {};
    if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
    if (!(opts.body instanceof FormData) && opts.body) {
        headers["Content-Type"] = "application/json";
    }
    return fetch(url, { ...opts, headers }).then(async (r) => {
        const data = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(data.detail || r.statusText);
        return data;
    });
}

function isLoggedIn() {
    return !!state.token;
}

// ─── Toast ───
let _toastContainer;
function ensureToastContainer() {
    if (!_toastContainer) {
        _toastContainer = document.createElement("div");
        _toastContainer.className = "toast-container";
        document.body.appendChild(_toastContainer);
    }
}

// ─── App Object ───
const App = {

    // ══════════ TOAST ══════════
    toast(msg, type = "success") {
        ensureToastContainer();
        const el = document.createElement("div");
        el.className = `toast ${type}`;
        el.textContent = msg;
        _toastContainer.appendChild(el);
        setTimeout(() => { el.style.opacity = "0"; setTimeout(() => el.remove(), 400); }, 2800);
    },

    // ══════════ NAVIGATION ══════════
    showScreen(name, data) {
        const LOGIN_REQUIRED = new Set(["upload", "myprompts", "profile", "editprofile"]);
        if (LOGIN_REQUIRED.has(name) && !isLoggedIn()) {
            this.toast("Please log in first", "error");
            this.showScreen("login");
            return;
        }

        document.querySelectorAll(".screen").forEach((s) => s.classList.remove("active"));
        const el = document.getElementById(`screen-${name}`);
        if (el) el.classList.add("active");
        state.currentScreen = name;

        // Show/hide bottom nav on non-auth screens
        const nav = document.getElementById("bottom-nav");
        const AUTH_SCREENS = new Set(["welcome", "login", "signup"]);
        if (nav) nav.style.display = AUTH_SCREENS.has(name) ? "none" : "flex";

        // Update nav active state
        document.querySelectorAll(".bottom-nav .nav-item").forEach((b) => {
            b.classList.toggle("active", b.dataset.screen === name);
        });

        this._updateNavVisibility();

        // Screen-specific logic
        if (name === "home") { this.loadPrompts(); this._updateHomeUI(); }
        if (name === "myprompts") this.loadMyPrompts();
        if (name === "profile") this._updateProfileUI();
        if (name === "upload") this._resetUploadForm();
        if (name === "detail" && data) this.loadDetail(data);
    },

    navTo(screen) { this.showScreen(screen); },

    _updateNavVisibility() {
        const logged = isLoggedIn();
        document.querySelectorAll(".bottom-nav .nav-item").forEach((btn) => {
            const screen = btn.dataset.screen;
            if (screen === "myprompts" || screen === "upload" || screen === "profile") {
                btn.style.display = logged ? "flex" : "none";
            }
        });
    },

    _updateHomeUI() {
        const logoutBtn = document.getElementById("logout-btn");
        const actionRow = document.getElementById("action-row");
        const logged = isLoggedIn();

        if (!logged) {
            logoutBtn.textContent = "Login";
            logoutBtn.onclick = () => this.showScreen("login");
        } else {
            logoutBtn.textContent = "Logout";
            logoutBtn.onclick = () => this.logout();
        }

        // Hide favorites & my prompts when not logged in
        actionRow.querySelectorAll(".btn").forEach((btn) => {
            if (btn.id === "logout-btn") return;
            btn.style.display = logged ? "inline-flex" : "none";
        });
    },

    _updateProfileUI() {
        const el = document.getElementById("profile-name");
        if (el) el.textContent = state.username || "GUEST";
    },

    // ══════════ THEME ══════════
    toggleTheme() {
        const html = document.documentElement;
        const current = html.getAttribute("data-theme");
        const next = current === "dark" ? "light" : "dark";
        html.setAttribute("data-theme", next);
        localStorage.setItem("theme", next);
        const btn = document.getElementById("theme-toggle");
        if (btn) btn.textContent = next === "dark" ? "🌙" : "☀️";
    },

    // ══════════ AUTH ══════════
    async login() {
        const user = document.getElementById("login-user").value.trim();
        const pass = document.getElementById("login-pass").value;
        const err = document.getElementById("login-error");
        err.textContent = "";

        if (!user || !pass) { err.textContent = "Fill in all fields"; return; }

        try {
            const data = await api("/api/login", {
                method: "POST",
                body: JSON.stringify({ username: user, password: pass }),
            });
            state.token = data.token;
            state.userId = data.user_id;
            state.username = data.username;
            localStorage.setItem("token", data.token);
            localStorage.setItem("username", data.username);
            this.toast(`Welcome back, ${data.username}!`);
            this.showScreen("home");
        } catch (e) {
            err.textContent = e.message;
        }
    },

    async signup() {
        const user = document.getElementById("signup-user").value.trim();
        const pass = document.getElementById("signup-pass").value;
        const conf = document.getElementById("signup-confirm").value;
        const err = document.getElementById("signup-error");
        err.textContent = "";

        if (!user || !pass) { err.textContent = "Fill in all fields"; return; }
        if (pass !== conf) { err.textContent = "Passwords don't match"; return; }
        if (pass.length < 4) { err.textContent = "Password must be 4+ characters"; return; }

        try {
            const data = await api("/api/signup", {
                method: "POST",
                body: JSON.stringify({ username: user, password: pass }),
            });
            state.token = data.token;
            state.userId = data.user_id;
            state.username = data.username;
            localStorage.setItem("token", data.token);
            localStorage.setItem("username", data.username);
            this.toast(`Account created! Welcome, ${data.username}!`);
            this.showScreen("home");
        } catch (e) {
            err.textContent = e.message;
        }
    },

    logout() {
        state.token = null;
        state.userId = null;
        state.username = null;
        localStorage.removeItem("token");
        localStorage.removeItem("username");
        this.toast("Logged out");
        this.showScreen("welcome");
    },

    // ══════════ PROMPTS ══════════
    async loadPrompts() {
        const search = document.getElementById("search-input").value.trim();
        const params = new URLSearchParams();
        if (search) params.set("search", search);
        if (state.currentFilter !== "All") params.set("category", state.currentFilter);

        try {
            const prompts = await api(`/api/prompts?${params}`);
            this._renderGrid("prompt-grid", prompts, false);
        } catch (e) {
            this.toast("Failed to load prompts", "error");
        }
    },

    setFilter(cat) {
        state.currentFilter = cat;
        document.querySelectorAll(".filter-pill").forEach((p) => {
            p.classList.toggle("active", p.dataset.cat === cat);
        });
        this.loadPrompts();
    },

    async loadMyPrompts() {
        try {
            const all = await api("/api/prompts");
            const mine = all.filter((p) => p.author === state.username);
            this._renderGrid("my-prompts-grid", mine, true);
        } catch (e) {
            this.toast("Failed to load prompts", "error");
        }
    },

    _renderGrid(containerId, prompts, showActions) {
        const grid = document.getElementById(containerId);
        if (!prompts.length) {
            grid.innerHTML = `
        <div class="empty-state" style="grid-column:1/-1">
          <div class="empty-icon">📭</div>
          <p>No prompts found</p>
        </div>`;
            return;
        }

        grid.innerHTML = prompts.map((p) => {
            const thumb = p.thumbnail
                ? `<img class="thumb" src="/api/thumbnail/${p.thumbnail}" alt="${p.title}" loading="lazy">`
                : `<div class="thumb" style="display:flex;align-items:center;justify-content:center;font-size:3rem;color:var(--text-dim)">🎨</div>`;

            const tags = (p.tags || "")
                .split(",")
                .filter(Boolean)
                .map((t) => `<span class="tag">${t.trim()}</span>`)
                .join("");

            const star = isLoggedIn()
                ? `<button class="bookmark-btn" onclick="event.stopPropagation();App.toggleBookmark(${p.id})">${p.bookmarked ? "⭐" : "☆"}</button>`
                : "";

            const shareBtn = `<button class="share-btn" onclick="event.stopPropagation();App.sharePrompt(${p.id},'${p.title.replace(/'/g, "\\'")}')">🔗</button>`;

            const actions = showActions
                ? `<div class="card-actions">
            <button class="btn btn-cyan btn-sm" onclick="event.stopPropagation();App.editPrompt(${p.id})">✏️ Edit</button>
            <button class="btn btn-coral btn-sm" onclick="event.stopPropagation();App.deletePrompt(${p.id})">🗑️ Delete</button>
           </div>`
                : "";

            return `
        <div class="prompt-card" onclick="App.showScreen('detail',${p.id})">
          ${thumb}
          ${star}
          ${shareBtn}
          <div class="card-body">
            <div class="card-title">${p.title}</div>
            <div class="card-meta">${p.category} · ${p.model || "Unknown"} · by ${p.author}</div>
            <div class="card-tags">${tags}</div>
            ${actions}
          </div>
        </div>`;
        }).join("");
    },

    // ══════════ DETAIL ══════════
    async loadDetail(id) {
        try {
            const p = await api(`/api/prompts/${id}`);
            document.getElementById("detail-title-bar").textContent = p.title;

            const thumb = p.thumbnail
                ? `<img class="detail-thumb" src="/api/thumbnail/${p.thumbnail}" alt="${p.title}">`
                : "";

            const tags = (p.tags || "")
                .split(",")
                .filter(Boolean)
                .map((t) => `<span class="tag">${t.trim()}</span>`)
                .join(" ");

            document.getElementById("detail-content").innerHTML = `
        ${thumb}
        <div class="detail-title">${p.title}</div>
        <div class="detail-meta">${p.category} · ${p.model || "Unknown"} · by ${p.author}</div>
        <div class="detail-prompt-box">
          <button class="copy-btn" onclick="App.copyPrompt(this)">📋 Copy</button>
          ${p.prompt}
        </div>
        <div style="margin-top:8px">${tags}</div>
        <div class="detail-actions">
          <button class="btn btn-cyan btn-sm" onclick="App.sharePrompt(${p.id},'${p.title.replace(/'/g, "\\'")}')">🔗 Share</button>
        </div>
      `;
        } catch (e) {
            this.toast("Failed to load prompt", "error");
        }
    },

    copyPrompt(btn) {
        const box = btn.parentElement;
        const text = box.textContent.replace("📋 Copy", "").trim();
        navigator.clipboard.writeText(text).then(() => {
            btn.textContent = "✅ Copied!";
            setTimeout(() => (btn.textContent = "📋 Copy"), 1500);
        });
    },

    // ══════════ BOOKMARKS ══════════
    async toggleBookmark(id) {
        if (!isLoggedIn()) { this.toast("Log in to bookmark", "error"); return; }
        try {
            // Check current state by reloading
            const p = await api(`/api/prompts/${id}`);
            if (p.bookmarked) {
                await api(`/api/bookmarks/${id}`, { method: "DELETE" });
                this.toast("Removed from favorites");
            } else {
                await api(`/api/bookmarks/${id}`, { method: "POST" });
                this.toast("Added to favorites ⭐");
            }
            // Refresh current view
            if (state.currentScreen === "home") this.loadPrompts();
        } catch (e) {
            this.toast(e.message, "error");
        }
    },

    async showBookmarks() {
        if (!isLoggedIn()) { this.toast("Log in to see favorites", "error"); return; }
        try {
            const bms = await api("/api/bookmarks");
            this._renderGrid("prompt-grid", bms, false);
        } catch (e) {
            this.toast("Failed to load bookmarks", "error");
        }
    },

    // ══════════ UPLOAD ══════════
    _resetUploadForm() {
        document.getElementById("upload-title").value = "";
        document.getElementById("upload-prompt").value = "";
        document.getElementById("upload-category").value = "Image";
        document.getElementById("upload-status").textContent = "";
        document.getElementById("thumb-file").value = "";
        if (document.getElementById("upload-tags")) document.getElementById("upload-tags").value = "";

        const box = document.getElementById("thumb-upload");
        box.innerHTML = `<div class="upload-icon">🖼️</div><div class="upload-text">Click to select thumbnail</div>`;

        state.editingPromptId = null;
        this.onCategoryChange();
    },

    onCategoryChange() {
        const cat = document.getElementById("upload-category").value;
        const select = document.getElementById("upload-model");
        select.innerHTML = (MODELS[cat] || []).map((m) => `<option value="${m}">${m}</option>`).join("");
    },

    previewThumb(input) {
        if (!input.files[0]) return;
        const reader = new FileReader();
        reader.onload = (e) => {
            const box = document.getElementById("thumb-upload");
            box.innerHTML = `<img src="${e.target.result}" alt="Preview">`;
        };
        reader.readAsDataURL(input.files[0]);
    },

    async uploadPrompt() {
        const title = document.getElementById("upload-title").value.trim();
        const prompt = document.getElementById("upload-prompt").value.trim();
        const category = document.getElementById("upload-category").value;
        const model = document.getElementById("upload-model").value;
        const status = document.getElementById("upload-status");
        const file = document.getElementById("thumb-file").files[0];

        if (!title || !prompt) {
            status.textContent = "Title and prompt are required";
            status.style.color = "var(--coral)";
            return;
        }

        const fd = new FormData();
        fd.append("title", title);
        fd.append("prompt", prompt);
        const tagsVal = document.getElementById("upload-tags") ? document.getElementById("upload-tags").value.trim() : "";
        fd.append("category", category);
        fd.append("model", model);
        fd.append("tags", tagsVal);
        if (file) fd.append("thumbnail", file);

        status.textContent = "Uploading...";
        status.style.color = "var(--cyan)";

        try {
            const url = state.editingPromptId
                ? `/api/prompts/${state.editingPromptId}`
                : "/api/prompts";
            const method = state.editingPromptId ? "PUT" : "POST";

            await api(url, { method, body: fd });
            this.toast(state.editingPromptId ? "Prompt updated!" : "Prompt uploaded!");
            state.editingPromptId = null;
            this.showScreen("myprompts");
        } catch (e) {
            status.textContent = e.message;
            status.style.color = "var(--coral)";
        }
    },

    async editPrompt(id) {
        try {
            const p = await api(`/api/prompts/${id}`);
            state.editingPromptId = id;
            this.showScreen("upload");
            document.getElementById("upload-title").value = p.title;
            document.getElementById("upload-prompt").value = p.prompt;
            document.getElementById("upload-category").value = p.category;
            this.onCategoryChange();
            document.getElementById("upload-model").value = p.model || "";
            if (document.getElementById("upload-tags")) document.getElementById("upload-tags").value = p.tags || "";

            if (p.thumbnail) {
                const box = document.getElementById("thumb-upload");
                box.innerHTML = `<img src="/api/thumbnail/${p.thumbnail}" alt="Current">`;
            }
        } catch (e) {
            this.toast("Failed to load prompt", "error");
        }
    },

    async deletePrompt(id) {
        if (!confirm("Delete this prompt?")) return;
        try {
            await api(`/api/prompts/${id}`, { method: "DELETE" });
            this.toast("Prompt deleted");
            this.loadMyPrompts();
        } catch (e) {
            this.toast(e.message, "error");
        }
    },

    // ══════════ SHARING ══════════
    async sharePrompt(id, title) {
        const shareUrl = `${window.location.origin}/share/${id}`;
        const shareData = { title: `Prompt: ${title}`, text: `Check out this AI prompt: ${title}`, url: shareUrl };

        if (navigator.share) {
            try {
                await navigator.share(shareData);
            } catch (e) {
                if (e.name !== "AbortError") this.toast("Share failed", "error");
            }
        } else {
            try {
                await navigator.clipboard.writeText(shareUrl);
                this.toast("Share link copied! 🔗");
            } catch {
                // Fallback: select + copy
                const ta = document.createElement("textarea");
                ta.value = shareUrl;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand("copy");
                ta.remove();
                this.toast("Share link copied! 🔗");
            }
        }
    },

    // ══════════ PROFILE ══════════
    async changeName() {
        const name = document.getElementById("new-name").value.trim();
        const status = document.getElementById("edit-status");
        if (!name) { status.textContent = "Enter a name"; return; }

        try {
            const data = await api("/api/me", {
                method: "PUT",
                body: JSON.stringify({ username: name }),
            });
            state.username = data.username;
            localStorage.setItem("username", data.username);
            status.textContent = "Name updated!";
            this.toast("Name updated!");
        } catch (e) {
            status.textContent = e.message;
        }
    },
};


// ──────────────────── Init ────────────────────

(function init() {
    // Restore theme
    const saved = localStorage.getItem("theme") || "dark";
    document.documentElement.setAttribute("data-theme", saved);
    const toggle = document.getElementById("theme-toggle");
    if (toggle) toggle.textContent = saved === "dark" ? "🌙" : "☀️";

    // Splash sequence
    const splash = document.getElementById("splash-screen");

    function showFirstScreen() {
        if (state.token) {
            api("/api/me")
                .then((data) => {
                    state.username = data.username;
                    state.userId = data.user_id;
                    localStorage.setItem("username", data.username);
                    App.showScreen("home");
                })
                .catch(() => {
                    state.token = null;
                    localStorage.removeItem("token");
                    App.showScreen("welcome");
                });
        } else {
            App.showScreen("welcome");
        }
    }

    if (splash) {
        setTimeout(() => {
            splash.classList.add("fade-out");
            setTimeout(() => {
                splash.remove();
                showFirstScreen();
            }, 800);
        }, 1200);
    } else {
        showFirstScreen();
    }
})();
