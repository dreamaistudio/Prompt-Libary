/* ═══════════════════════════════════════════════════════════════════════════
   Prompt Library — Modern Client Logic (Netlify Functions & Supabase SDK)
   ═══════════════════════════════════════════════════════════════════════════ */

// ─── API Base URL ───
const API_BASE = '/.netlify/functions/api';

// ─── Client State ───
const state = {
    token: null,
    username: localStorage.getItem("username") || null,
    userId: null,
    avatar: null,
    currentScreen: "welcome",
    currentFilter: "All",
    editingPromptId: null,
};

// ─── AI Models List ───
const MODELS = {
    Image: ["Midjourney", "DALL·E 3", "Stable Diffusion", "Ideogram", "Flux", "Other"],
    Video: ["Runway Gen-3", "Sora", "Pika", "Kling", "Luma Dream Machine", "Other"],
};

// ─── Supabase Client Instance ───
let supabaseClient = null;

/**
 * Initialize Supabase JS Client using either remote Netlify config or local globals.
 */
async function initSupabase() {
    if (supabaseClient) return supabaseClient;

    let url = window.__SUPABASE_URL__;
    let key = window.__SUPABASE_ANON_KEY__;

    if (!url || !key) {
        try {
            const res = await fetch(`${API_BASE}/config`);
            if (res.ok) {
                const cfg = await res.json();
                url = cfg.supabaseUrl;
                key = cfg.supabaseAnonKey;
            }
        } catch (err) {
            console.warn('Could not auto-fetch Supabase configuration from Netlify function:', err);
        }
    }

    if (window.supabase && url && key) {
        supabaseClient = window.supabase.createClient(url, key, {
            auth: {
                persistSession: true,
                autoRefreshToken: true,
                detectSessionInUrl: true,
            }
        });
        window.supabaseClient = supabaseClient;

        // Synchronize auth state changes
        supabaseClient.auth.onAuthStateChange(async (event, session) => {
            if (session) {
                state.token = session.access_token;
                state.userId = session.user.id;
            } else if (event === 'SIGNED_OUT') {
                state.token = null;
                state.userId = null;
                state.username = null;
                state.avatar = null;
            }
        });
    }

    return supabaseClient;
}

// ─── Search Debounce ───
let _searchTimer;
function debounceSearch() {
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(() => App.loadPrompts(), 300);
}

// ─── API Request Helper ───
async function api(path, opts = {}) {
    const url = path.startsWith('http') ? path : `${API_BASE}${path}`;
    const headers = opts.headers ? { ...opts.headers } : {};

    // Retrieve active session token from Supabase client SDK
    if (supabaseClient) {
        try {
            const { data: { session } } = await supabaseClient.auth.getSession();
            if (session && session.access_token) {
                headers['Authorization'] = `Bearer ${session.access_token}`;
                state.token = session.access_token;
            }
        } catch (e) {
            console.warn('Error reading Supabase session token:', e);
        }
    } else if (state.token) {
        headers['Authorization'] = `Bearer ${state.token}`;
    }

    // Set JSON header only if body is not FormData
    if (!(opts.body instanceof FormData) && opts.body) {
        headers['Content-Type'] = 'application/json';
    }

    const res = await fetch(url, { ...opts, headers });
    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
        throw new Error(data.detail || data.message || res.statusText || 'API request failed');
    }

    return data;
}

function isLoggedIn() {
    return !!state.token;
}

// ─── Toast Notifications ───
let _toastContainer;
function ensureToastContainer() {
    if (!_toastContainer) {
        _toastContainer = document.createElement("div");
        _toastContainer.className = "toast-container";
        document.body.appendChild(_toastContainer);
    }
}

// ─── Application Controller ───
const App = {

    // ══════════ TOAST NOTIFICATIONS ══════════
    toast(msg, type = "success") {
        ensureToastContainer();
        const el = document.createElement("div");
        el.className = `toast ${type}`;
        el.textContent = msg;
        _toastContainer.appendChild(el);
        setTimeout(() => {
            el.style.opacity = "0";
            setTimeout(() => el.remove(), 400);
        }, 2800);
    },

    // ══════════ SCREEN NAVIGATION ══════════
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

        // Show/hide bottom navigation bar
        const nav = document.getElementById("bottom-nav");
        const AUTH_SCREENS = new Set(["welcome", "login", "signup"]);
        if (nav) nav.style.display = AUTH_SCREENS.has(name) ? "none" : "flex";

        // Update active nav button state
        document.querySelectorAll(".bottom-nav .nav-item").forEach((b) => {
            b.classList.toggle("active", b.dataset.screen === name);
        });

        this._updateNavVisibility();

        // Screen specific triggers
        if (name === "home") {
            this.loadPrompts();
            this._updateHomeUI();
        }
        if (name === "myprompts") this.loadMyPrompts();
        if (name === "profile" || name === "editprofile") this._updateProfileUI();
        if (name === "upload" && !state.editingPromptId) this._resetUploadForm();
        if (name === "detail" && data) this.loadDetail(data);
    },

    navTo(screen) {
        this.showScreen(screen);
    },

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

        if (actionRow) {
            actionRow.querySelectorAll(".btn").forEach((btn) => {
                if (btn.id === "logout-btn") return;
                btn.style.display = logged ? "inline-flex" : "none";
            });
        }
    },

    _updateProfileUI() {
        const nameEl = document.getElementById("profile-name");
        if (nameEl) nameEl.textContent = state.username || "GUEST";

        const avatarDisplay = document.getElementById("profile-avatar-display");
        const editAvatarPreview = document.getElementById("edit-avatar-preview");

        const renderAvatar = (targetEl) => {
            if (!targetEl) return;
            if (state.avatar) {
                targetEl.innerHTML = `<img src="${state.avatar}" alt="Avatar" style="width:100%;height:100%;object-fit:cover;border-radius:50%;">`;
            } else {
                targetEl.textContent = "👤";
            }
        };

        renderAvatar(avatarDisplay);
        renderAvatar(editAvatarPreview);
    },

    // ══════════ THEME MANAGEMENT ══════════
    toggleTheme() {
        const html = document.documentElement;
        const current = html.getAttribute("data-theme");
        const next = current === "dark" ? "light" : "dark";
        html.setAttribute("data-theme", next);
        localStorage.setItem("theme", next);
        const btn = document.getElementById("theme-toggle");
        if (btn) btn.textContent = next === "dark" ? "🌙" : "☀️";
    },

    // ══════════ AUTHENTICATION ══════════
    async login() {
        const user = document.getElementById("login-user").value.trim();
        const pass = document.getElementById("login-pass").value;
        const err = document.getElementById("login-error");
        err.textContent = "";

        if (!user || !pass) {
            err.textContent = "Please fill in all fields";
            return;
        }

        const loginBtn = document.getElementById("login-btn");
        loginBtn.disabled = true;
        loginBtn.textContent = "Logging in...";

        try {
            const data = await api("/login", {
                method: "POST",
                body: JSON.stringify({ username: user, password: pass }),
            });

            // Synchronize with Supabase JS client SDK
            if (supabaseClient && data.session) {
                await supabaseClient.auth.setSession(data.session);
            }

            state.token = data.token;
            state.userId = data.user_id;
            state.username = data.username;
            localStorage.setItem("username", data.username);

            // Fetch avatar from profile
            try {
                const me = await api("/me");
                state.avatar = me.avatar || null;
            } catch (ignore) {}

            this.toast(`Welcome back, ${data.username}!`);
            this.showScreen("home");
        } catch (e) {
            err.textContent = e.message;
        } finally {
            loginBtn.disabled = false;
            loginBtn.textContent = "Login";
        }
    },

    async signup() {
        const user = document.getElementById("signup-user").value.trim();
        const pass = document.getElementById("signup-pass").value;
        const conf = document.getElementById("signup-confirm").value;
        const err = document.getElementById("signup-error");
        err.textContent = "";

        if (!user || !pass) {
            err.textContent = "Please fill in all fields";
            return;
        }
        if (pass !== conf) {
            err.textContent = "Passwords do not match";
            return;
        }
        if (pass.length < 4) {
            err.textContent = "Password must be at least 4 characters";
            return;
        }

        const signupBtn = document.getElementById("signup-btn");
        signupBtn.disabled = true;
        signupBtn.textContent = "Creating account...";

        try {
            const data = await api("/signup", {
                method: "POST",
                body: JSON.stringify({ username: user, password: pass }),
            });

            if (supabaseClient && data.session) {
                await supabaseClient.auth.setSession(data.session);
            }

            state.token = data.token;
            state.userId = data.user_id;
            state.username = data.username;
            localStorage.setItem("username", data.username);

            this.toast(`Account created! Welcome, ${data.username}!`);
            this.showScreen("home");
        } catch (e) {
            err.textContent = e.message;
        } finally {
            signupBtn.disabled = false;
            signupBtn.textContent = "Sign Up";
        }
    },

    async logout() {
        if (supabaseClient) {
            await supabaseClient.auth.signOut().catch(() => {});
        }
        state.token = null;
        state.userId = null;
        state.username = null;
        state.avatar = null;
        localStorage.removeItem("username");
        this.toast("Logged out successfully");
        this.showScreen("welcome");
    },

    // ══════════ PROMPTS BROWSE & SEARCH ══════════
    async loadPrompts() {
        const search = document.getElementById("search-input").value.trim();
        const params = new URLSearchParams();
        if (search) params.set("search", search);
        if (state.currentFilter !== "All") params.set("category", state.currentFilter);

        try {
            const prompts = await api(`/prompts?${params.toString()}`);
            this._renderGrid("prompt-grid", prompts, false);
        } catch (e) {
            this.toast("Failed to load prompts: " + e.message, "error");
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
            const all = await api("/prompts");
            const mine = all.filter((p) => p.user_id === state.userId || p.author === state.username);
            this._renderGrid("my-prompts-grid", mine, true);
        } catch (e) {
            this.toast("Failed to load your prompts", "error");
        }
    },

    _renderGrid(containerId, prompts, showActions) {
        const grid = document.getElementById(containerId);
        if (!grid) return;

        if (!prompts || !prompts.length) {
            grid.innerHTML = `
                <div class="empty-state" style="grid-column:1/-1;text-align:center;padding:40px 20px;">
                    <div class="empty-icon" style="font-size:3rem;margin-bottom:12px;">📭</div>
                    <p style="color:var(--text-dim);font-size:1.1rem;">No prompts found</p>
                </div>`;
            return;
        }

        grid.innerHTML = prompts.map((p) => {
            // Direct Supabase Storage URL or fallback icon
            const thumb = p.thumbnail
                ? `<img class="thumb" src="${p.thumbnail}" alt="${escapeHtml(p.title)}" loading="lazy" onerror="this.parentElement.innerHTML='<div class=\\\'thumb\\\' style=\\\'display:flex;align-items:center;justify-content:center;font-size:3rem;color:var(--text-dim)\\\'>🎨</div>'">`
                : `<div class="thumb" style="display:flex;align-items:center;justify-content:center;font-size:3rem;color:var(--text-dim)">🎨</div>`;

            const tags = (p.tags || "")
                .split(",")
                .filter(Boolean)
                .map((t) => `<span class="tag">${escapeHtml(t.trim())}</span>`)
                .join("");

            const star = isLoggedIn()
                ? `<button class="bookmark-btn" onclick="event.stopPropagation();App.toggleBookmark(${p.id})">${p.bookmarked ? "⭐" : "☆"}</button>`
                : "";

            const shareBtn = `<button class="share-btn" onclick="event.stopPropagation();App.sharePrompt(${p.id},'${escapeHtml(p.title).replace(/'/g, "\\'")}')">🔗</button>`;

            const actions = showActions
                ? `<div class="card-actions" style="margin-top:10px;display:flex;gap:8px;">
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
                        <div class="card-title">${escapeHtml(p.title)}</div>
                        <div class="card-meta">${escapeHtml(p.category)} · ${escapeHtml(p.model || "Unknown")} · by ${escapeHtml(p.author || "Unknown")}</div>
                        <div class="card-tags">${tags}</div>
                        ${actions}
                    </div>
                </div>`;
        }).join("");
    },

    // ══════════ PROMPT DETAILS ══════════
    async loadDetail(id) {
        try {
            const p = await api(`/prompts/${id}`);
            document.getElementById("detail-title-bar").textContent = p.title;

            const thumb = p.thumbnail
                ? `<img class="detail-thumb" src="${p.thumbnail}" alt="${escapeHtml(p.title)}" onerror="this.style.display='none'">`
                : "";

            const tags = (p.tags || "")
                .split(",")
                .filter(Boolean)
                .map((t) => `<span class="tag">${escapeHtml(t.trim())}</span>`)
                .join(" ");

            const instructionsHtml = p.instructions
                ? `<div style="margin-top:16px;background:rgba(255,255,255,0.04);padding:14px;border-radius:var(--radius-sm);border:1px solid var(--border);">
                     <div style="font-weight:600;font-size:0.85rem;color:var(--cyan);margin-bottom:6px;">Instructions / Parameters:</div>
                     <div style="font-size:0.9rem;white-space:pre-wrap;color:var(--text-mid);">${escapeHtml(p.instructions)}</div>
                   </div>`
                : "";

            document.getElementById("detail-content").innerHTML = `
                ${thumb}
                <div class="detail-title">${escapeHtml(p.title)}</div>
                <div class="detail-meta">${escapeHtml(p.category)} · ${escapeHtml(p.model || "Unknown")} · by ${escapeHtml(p.author || "Unknown")}</div>
                <div class="detail-prompt-box">
                    <button class="copy-btn" onclick="App.copyPrompt(this)">📋 Copy</button>
                    ${escapeHtml(p.prompt)}
                </div>
                ${instructionsHtml}
                <div style="margin-top:12px">${tags}</div>
                <div class="detail-actions" style="margin-top:20px;display:flex;gap:10px;">
                    <button class="btn btn-cyan btn-sm" onclick="App.sharePrompt(${p.id},'${escapeHtml(p.title).replace(/'/g, "\\'")}')">🔗 Share</button>
                    ${isLoggedIn() ? `<button class="btn btn-orange btn-sm" onclick="App.toggleBookmark(${p.id})">${p.bookmarked ? "⭐ Favorited" : "☆ Add Favorite"}</button>` : ""}
                </div>
            `;
        } catch (e) {
            this.toast("Failed to load prompt details: " + e.message, "error");
        }
    },

    copyPrompt(btn) {
        const box = btn.parentElement;
        const text = box.textContent.replace("📋 Copy", "").replace("✅ Copied!", "").trim();
        navigator.clipboard.writeText(text).then(() => {
            btn.textContent = "✅ Copied!";
            setTimeout(() => (btn.textContent = "📋 Copy"), 1500);
        });
    },

    // ══════════ BOOKMARKS ══════════
    async toggleBookmark(id) {
        if (!isLoggedIn()) {
            this.toast("Log in to bookmark prompts", "error");
            return;
        }
        try {
            const p = await api(`/prompts/${id}`);
            if (p.bookmarked) {
                await api(`/bookmarks/${id}`, { method: "DELETE" });
                this.toast("Removed from favorites");
            } else {
                await api(`/bookmarks/${id}`, { method: "POST" });
                this.toast("Added to favorites ⭐");
            }
            if (state.currentScreen === "home") this.loadPrompts();
            if (state.currentScreen === "detail") this.loadDetail(id);
        } catch (e) {
            this.toast(e.message, "error");
        }
    },

    async showBookmarks() {
        if (!isLoggedIn()) {
            this.toast("Log in to view favorites", "error");
            return;
        }
        try {
            const bms = await api("/bookmarks");
            this._renderGrid("prompt-grid", bms, false);
        } catch (e) {
            this.toast("Failed to load bookmarks", "error");
        }
    },

    // ══════════ UPLOAD & EDIT PROMPTS ══════════
    _resetUploadForm() {
        document.getElementById("upload-screen-title").textContent = "📤 Upload Prompt";
        document.getElementById("upload-title").value = "";
        document.getElementById("upload-prompt").value = "";
        document.getElementById("upload-category").value = "Image";
        document.getElementById("upload-status").textContent = "";
        document.getElementById("thumb-file").value = "";
        if (document.getElementById("upload-tags")) document.getElementById("upload-tags").value = "";

        const box = document.getElementById("thumb-upload");
        box.innerHTML = `<div class="upload-icon">🖼️</div><div class="upload-text">Click to select thumbnail</div>`;

        state.editingPromptId = null;
        const uploadBtn = document.getElementById("upload-btn");
        if (uploadBtn) uploadBtn.textContent = "Upload Prompt";
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
            box.innerHTML = `<img src="${e.target.result}" alt="Preview" style="max-height:160px;object-fit:cover;border-radius:var(--radius-sm)">`;
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
            status.textContent = "Title and prompt text are required";
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

        status.textContent = state.editingPromptId ? "Updating prompt..." : "Uploading to Supabase Storage...";
        status.style.color = "var(--cyan)";

        const uploadBtn = document.getElementById("upload-btn");
        uploadBtn.disabled = true;

        try {
            const url = state.editingPromptId ? `/prompts/${state.editingPromptId}` : "/prompts";
            const method = state.editingPromptId ? "PUT" : "POST";

            await api(url, { method, body: fd });
            this.toast(state.editingPromptId ? "Prompt updated successfully!" : "Prompt published to library!");
            state.editingPromptId = null;
            this.showScreen("myprompts");
        } catch (e) {
            status.textContent = e.message;
            status.style.color = "var(--coral)";
        } finally {
            uploadBtn.disabled = false;
        }
    },

    async editPrompt(id) {
        try {
            const p = await api(`/prompts/${id}`);
            state.editingPromptId = id;
            this.showScreen("upload");

            document.getElementById("upload-screen-title").textContent = "✏️ Edit Prompt";
            document.getElementById("upload-title").value = p.title;
            document.getElementById("upload-prompt").value = p.prompt;
            document.getElementById("upload-category").value = p.category;
            this.onCategoryChange();
            document.getElementById("upload-model").value = p.model || "";
            if (document.getElementById("upload-tags")) {
                document.getElementById("upload-tags").value = p.tags || "";
            }

            const uploadBtn = document.getElementById("upload-btn");
            if (uploadBtn) uploadBtn.textContent = "Save Changes";

            if (p.thumbnail) {
                const box = document.getElementById("thumb-upload");
                box.innerHTML = `<img src="${p.thumbnail}" alt="Current Thumbnail" style="max-height:160px;object-fit:cover;border-radius:var(--radius-sm)">`;
            }
        } catch (e) {
            this.toast("Failed to load prompt for editing: " + e.message, "error");
        }
    },

    async deletePrompt(id) {
        if (!confirm("Are you sure you want to permanently delete this prompt?")) return;
        try {
            await api(`/prompts/${id}`, { method: "DELETE" });
            this.toast("Prompt deleted");
            this.loadMyPrompts();
        } catch (e) {
            this.toast(e.message, "error");
        }
    },

    // ══════════ SOCIAL SHARING ══════════
    async sharePrompt(id, title) {
        const shareUrl = `${window.location.origin}/#prompt-${id}`;
        const shareData = {
            title: `Prompt: ${title}`,
            text: `Check out this AI prompt: ${title}`,
            url: shareUrl,
        };

        if (navigator.share) {
            try {
                await navigator.share(shareData);
                return;
            } catch (e) {
                if (e.name === "AbortError") return;
            }
        }

        try {
            await navigator.clipboard.writeText(shareUrl);
            this.toast("Share link copied to clipboard! 🔗");
        } catch {
            const ta = document.createElement("textarea");
            ta.value = shareUrl;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand("copy");
            ta.remove();
            this.toast("Share link copied to clipboard! 🔗");
        }
    },

    // ══════════ PROFILE EDITING ══════════
    async changeName() {
        const name = document.getElementById("new-name").value.trim();
        const status = document.getElementById("edit-status");
        if (!name) {
            status.textContent = "Please enter a username";
            return;
        }

        try {
            const data = await api("/me", {
                method: "PUT",
                body: JSON.stringify({ username: name }),
            });
            state.username = data.username;
            localStorage.setItem("username", data.username);
            this._updateProfileUI();
            status.textContent = "Username updated!";
            this.toast("Username updated!");
        } catch (e) {
            status.textContent = e.message;
        }
    },

    async uploadAvatar(input) {
        const file = input.files[0];
        const status = document.getElementById("avatar-status");
        if (!file) return;

        status.textContent = "Uploading avatar to Supabase Storage...";
        status.style.color = "var(--cyan)";

        const fd = new FormData();
        fd.append("avatar", file);

        try {
            const data = await api("/me/avatar", {
                method: "PUT",
                body: fd,
            });
            state.avatar = data.avatar;
            this._updateProfileUI();
            status.textContent = "Avatar updated successfully!";
            status.style.color = "var(--green)";
            this.toast("Avatar updated!");
        } catch (e) {
            status.textContent = e.message;
            status.style.color = "var(--coral)";
        }
    },
};

// ─── Application Initialization ───
(async function init() {
    // Restore theme from localStorage
    const saved = localStorage.getItem("theme") || "dark";
    document.documentElement.setAttribute("data-theme", saved);
    const toggle = document.getElementById("theme-toggle");
    if (toggle) toggle.textContent = saved === "dark" ? "🌙" : "☀️";

    // Initialize Supabase JS SDK client
    await initSupabase();

    // Check for existing session in Supabase Auth
    if (supabaseClient) {
        try {
            const { data: { session } } = await supabaseClient.auth.getSession();
            if (session) {
                state.token = session.access_token;
                state.userId = session.user.id;
            }
        } catch (e) {
            console.warn('Session retrieval error:', e);
        }
    }

    // Inspect URL hash for deep-linked prompt (e.g., #prompt-123)
    const hash = window.location.hash;
    let initialPromptId = null;
    if (hash && hash.startsWith('#prompt-')) {
        initialPromptId = hash.replace('#prompt-', '');
    }

    // Initial screen transition
    async function showFirstScreen() {
        if (state.token) {
            try {
                const data = await api("/me");
                state.username = data.username;
                state.userId = data.user_id;
                state.avatar = data.avatar;
                localStorage.setItem("username", data.username);

                if (initialPromptId) {
                    App.showScreen("detail", initialPromptId);
                } else {
                    App.showScreen("home");
                }
            } catch (e) {
                state.token = null;
                if (initialPromptId) {
                    App.showScreen("detail", initialPromptId);
                } else {
                    App.showScreen("welcome");
                }
            }
        } else {
            if (initialPromptId) {
                App.showScreen("detail", initialPromptId);
            } else {
                App.showScreen("welcome");
            }
        }
    }

    const splash = document.getElementById("splash-screen");
    if (splash) {
        setTimeout(() => {
            splash.classList.add("fade-out");
            setTimeout(() => {
                splash.remove();
                showFirstScreen();
            }, 800);
        }, 1000);
    } else {
        showFirstScreen();
    }
})();

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
