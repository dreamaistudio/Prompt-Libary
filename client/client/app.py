"""Prompt Library — CustomTkinter Desktop Client."""

import sys
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from io import BytesIO

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

# Add parent so we can import api_client from same dir
sys.path.insert(0, os.path.dirname(__file__))
from api_client import ApiClient

# ─── Constants ───
MODELS = {
    "Image": ["Midjourney", "DALL·E 3", "Stable Diffusion", "Ideogram", "Flux", "Other"],
    "Video": ["Runway Gen-3", "Sora", "Pika", "Kling", "Luma Dream Machine", "Other"],
}

CYAN = "#00e5ff"
CYAN_DARK = "#00b8d4"
GREEN = "#10b981"
ORANGE = "#f59e0b"
CORAL = "#ef4444"
TEAL = "#1a6b5a"
BG_DARK = "#0a0e1a"
BG_CARD = "#162236"
TEXT = "#f1f5f9"
TEXT_DIM = "#64748b"

CARD_WIDTH = 260
CARD_HEIGHT = 240
THUMB_HEIGHT = 140


class PromptLibraryApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.title("Prompt Library")
        self.geometry("1000x700")
        self.minsize(800, 600)

        self.api = ApiClient()
        self._thumb_cache: dict[str, ctk.CTkImage] = {}
        self._current_filter = "All"

        # ── Layout: sidebar + main content ──
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._main_frame.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        self._main_frame.grid_rowconfigure(0, weight=1)
        self._main_frame.grid_columnconfigure(0, weight=1)

        self._frames: dict[str, ctk.CTkFrame] = {}
        self._build_welcome_frame()
        self._build_login_frame()
        self._build_signup_frame()
        self._build_home_frame()
        self._build_detail_frame()
        self._build_upload_frame()
        self._build_my_prompts_frame()
        self._build_profile_frame()

        self._show_frame("welcome")

    # ══════════════════════════════════════════
    #  SIDEBAR
    # ══════════════════════════════════════════

    def _build_sidebar(self):
        self._sidebar = ctk.CTkFrame(self, width=200, corner_radius=0, fg_color=BG_CARD)
        self._sidebar.grid(row=0, column=0, sticky="nsew")
        self._sidebar.grid_rowconfigure(10, weight=1)

        # Logo
        logo_label = ctk.CTkLabel(
            self._sidebar, text="PROMPT\nLIBRARY",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=CYAN,
        )
        logo_label.grid(row=0, column=0, padx=20, pady=(30, 30))

        # Nav buttons
        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        nav_items = [
            ("home", "🏠 Home", 1),
            ("myprompts", "📝 My Prompts", 2),
            ("upload", "📤 Upload", 3),
            ("bookmarks", "⭐ Favorites", 4),
            ("profile", "👤 Profile", 5),
        ]
        for key, text, row in nav_items:
            btn = ctk.CTkButton(
                self._sidebar, text=text, anchor="w",
                font=ctk.CTkFont(size=14),
                fg_color="transparent", text_color=TEXT_DIM,
                hover_color=BG_DARK,
                height=40, corner_radius=8,
                command=lambda k=key: self._nav_to(k),
            )
            btn.grid(row=row, column=0, padx=12, pady=2, sticky="ew")
            self._nav_buttons[key] = btn

        # Theme toggle
        self._theme_btn = ctk.CTkButton(
            self._sidebar, text="🌙 Dark Mode",
            font=ctk.CTkFont(size=12),
            fg_color="transparent", text_color=TEXT_DIM,
            hover_color=BG_DARK, height=32,
            command=self._toggle_theme,
        )
        self._theme_btn.grid(row=11, column=0, padx=12, pady=(0, 8), sticky="ew")

        # Auth button
        self._auth_btn = ctk.CTkButton(
            self._sidebar, text="Login",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=CYAN, text_color=BG_DARK,
            hover_color=CYAN_DARK, height=36,
            command=lambda: self._nav_to("login"),
        )
        self._auth_btn.grid(row=12, column=0, padx=12, pady=(0, 20), sticky="ew")

        self._update_sidebar()

    def _update_sidebar(self):
        logged = self.api.is_logged_in
        for key in ["myprompts", "upload", "bookmarks", "profile"]:
            if key in self._nav_buttons:
                if logged:
                    self._nav_buttons[key].grid()
                else:
                    self._nav_buttons[key].grid_remove()

        if logged:
            self._auth_btn.configure(text="Logout", fg_color=CORAL, hover_color="#b91c1c",
                                     command=self._logout)
        else:
            self._auth_btn.configure(text="Login", fg_color=CYAN, hover_color=CYAN_DARK,
                                     command=lambda: self._nav_to("login"))

    def _set_active_nav(self, key: str):
        for k, btn in self._nav_buttons.items():
            if k == key:
                btn.configure(fg_color=CYAN, text_color=BG_DARK)
            else:
                btn.configure(fg_color="transparent", text_color=TEXT_DIM)

    def _toggle_theme(self):
        current = ctk.get_appearance_mode()
        new_mode = "Light" if current == "Dark" else "Dark"
        ctk.set_appearance_mode(new_mode)
        self._theme_btn.configure(text=f"{'☀️' if new_mode == 'Light' else '🌙'} {new_mode} Mode")

    # ══════════════════════════════════════════
    #  FRAME MANAGEMENT
    # ══════════════════════════════════════════

    def _register_frame(self, name: str, frame: ctk.CTkFrame):
        self._frames[name] = frame
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_remove()

    def _show_frame(self, name: str):
        for f in self._frames.values():
            f.grid_remove()
        if name in self._frames:
            self._frames[name].grid()
        self._set_active_nav(name)

        # Trigger data loads
        if name == "home":
            self._load_prompts()
        elif name == "myprompts":
            self._load_my_prompts()
        elif name == "profile":
            self._update_profile_ui()
        elif name == "upload":
            self._reset_upload_form()

    def _nav_to(self, screen: str):
        login_required = {"myprompts", "upload", "bookmarks", "profile"}
        if screen in login_required and not self.api.is_logged_in:
            self._toast("Please log in first", "error")
            self._show_frame("login")
            return
        if screen == "bookmarks":
            self._show_frame("home")
            self._load_bookmarks()
            return
        self._show_frame(screen)

    # ══════════════════════════════════════════
    #  WELCOME
    # ══════════════════════════════════════════

    def _build_welcome_frame(self):
        frame = ctk.CTkFrame(self._main_frame, fg_color="transparent")
        self._register_frame("welcome", frame)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        center = ctk.CTkFrame(frame, fg_color=BG_CARD, corner_radius=20, width=400)
        center.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(center, text="📚", font=ctk.CTkFont(size=60)).pack(pady=(40, 10))
        ctk.CTkLabel(center, text="PROMPT LIBRARY",
                     font=ctk.CTkFont(size=24, weight="bold"), text_color=CYAN).pack(pady=(0, 4))
        ctk.CTkLabel(center, text="Discover & share AI prompts",
                     font=ctk.CTkFont(size=13), text_color=TEXT_DIM).pack(pady=(0, 20))

        ctk.CTkButton(center, text="Browse without logging in",
                      fg_color=GREEN, hover_color="#059669", text_color="white",
                      height=40, corner_radius=20, width=280,
                      command=lambda: self._nav_to("home")).pack(pady=4)
        ctk.CTkButton(center, text="Login",
                      fg_color=ORANGE, hover_color="#d97706", text_color=BG_DARK,
                      height=40, corner_radius=20, width=280,
                      command=lambda: self._show_frame("login")).pack(pady=4)
        ctk.CTkButton(center, text="Sign Up",
                      fg_color="transparent", border_color=CYAN, border_width=2,
                      text_color=CYAN, height=40, corner_radius=20, width=280,
                      command=lambda: self._show_frame("signup")).pack(pady=(4, 40))

    # ══════════════════════════════════════════
    #  LOGIN
    # ══════════════════════════════════════════

    def _build_login_frame(self):
        frame = ctk.CTkFrame(self._main_frame, fg_color="transparent")
        self._register_frame("login", frame)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        box = ctk.CTkFrame(frame, fg_color=BG_CARD, corner_radius=20, width=380)
        box.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(box, text="Welcome back!",
                     font=ctk.CTkFont(size=22, weight="bold"), text_color=CYAN).pack(pady=(30, 4))
        ctk.CTkLabel(box, text="Log in to your account",
                     font=ctk.CTkFont(size=13), text_color=TEXT_DIM).pack(pady=(0, 16))

        self._login_user = ctk.CTkEntry(box, placeholder_text="Username", width=280, height=40)
        self._login_user.pack(pady=4)
        self._login_pass = ctk.CTkEntry(box, placeholder_text="Password", show="*", width=280, height=40)
        self._login_pass.pack(pady=4)
        self._login_pass.bind("<Return>", lambda e: self._do_login())

        self._login_err = ctk.CTkLabel(box, text="", text_color=CORAL, font=ctk.CTkFont(size=12))
        self._login_err.pack(pady=2)

        ctk.CTkButton(box, text="Login", fg_color=GREEN, hover_color="#059669",
                      text_color="white", height=40, corner_radius=20, width=280,
                      command=self._do_login).pack(pady=4)
        ctk.CTkButton(box, text="< Back", fg_color="transparent",
                      text_color=TEXT_DIM, height=30,
                      command=lambda: self._show_frame("welcome")).pack(pady=(4, 30))

    def _do_login(self):
        user = self._login_user.get().strip()
        pw = self._login_pass.get()
        self._login_err.configure(text="")
        if not user or not pw:
            self._login_err.configure(text="Fill in all fields")
            return
        try:
            self.api.login(user, pw)
            self._toast(f"Welcome back, {self.api.username}!")
            self._update_sidebar()
            self._show_frame("home")
        except Exception as e:
            self._login_err.configure(text=str(e))

    # ══════════════════════════════════════════
    #  SIGNUP
    # ══════════════════════════════════════════

    def _build_signup_frame(self):
        frame = ctk.CTkFrame(self._main_frame, fg_color="transparent")
        self._register_frame("signup", frame)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        box = ctk.CTkFrame(frame, fg_color=BG_CARD, corner_radius=20, width=380)
        box.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(box, text="Create Account",
                     font=ctk.CTkFont(size=22, weight="bold"), text_color=CYAN).pack(pady=(30, 4))
        ctk.CTkLabel(box, text="Join the Prompt Library",
                     font=ctk.CTkFont(size=13), text_color=TEXT_DIM).pack(pady=(0, 16))

        self._signup_user = ctk.CTkEntry(box, placeholder_text="Username", width=280, height=40)
        self._signup_user.pack(pady=4)
        self._signup_pass = ctk.CTkEntry(box, placeholder_text="Password", show="*", width=280, height=40)
        self._signup_pass.pack(pady=4)
        self._signup_conf = ctk.CTkEntry(box, placeholder_text="Confirm Password", show="*", width=280, height=40)
        self._signup_conf.pack(pady=4)
        self._signup_conf.bind("<Return>", lambda e: self._do_signup())

        self._signup_err = ctk.CTkLabel(box, text="", text_color=CORAL, font=ctk.CTkFont(size=12))
        self._signup_err.pack(pady=2)

        ctk.CTkButton(box, text="Sign Up", fg_color=GREEN, hover_color="#059669",
                      text_color="white", height=40, corner_radius=20, width=280,
                      command=self._do_signup).pack(pady=4)
        ctk.CTkButton(box, text="< Back", fg_color="transparent",
                      text_color=TEXT_DIM, height=30,
                      command=lambda: self._show_frame("welcome")).pack(pady=(4, 30))

    def _do_signup(self):
        user = self._signup_user.get().strip()
        pw = self._signup_pass.get()
        conf = self._signup_conf.get()
        self._signup_err.configure(text="")
        if not user or not pw:
            self._signup_err.configure(text="Fill in all fields")
            return
        if pw != conf:
            self._signup_err.configure(text="Passwords don't match")
            return
        if len(pw) < 4:
            self._signup_err.configure(text="Password must be 4+ characters")
            return
        try:
            self.api.signup(user, pw)
            self._toast(f"Welcome, {self.api.username}!")
            self._update_sidebar()
            self._show_frame("home")
        except Exception as e:
            self._signup_err.configure(text=str(e))

    # ══════════════════════════════════════════
    #  HOME (Prompt Grid)
    # ══════════════════════════════════════════

    def _build_home_frame(self):
        frame = ctk.CTkFrame(self._main_frame, fg_color="transparent")
        self._register_frame("home", frame)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        # ─ Top bar: search + filters ─
        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 4))
        top.grid_columnconfigure(0, weight=1)

        search_row = ctk.CTkFrame(top, fg_color="transparent")
        search_row.pack(fill="x")
        search_row.grid_columnconfigure(0, weight=1)

        self._search_entry = ctk.CTkEntry(search_row, placeholder_text="Search prompts...", height=38)
        self._search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._search_entry.bind("<Return>", lambda e: self._load_prompts())

        ctk.CTkButton(search_row, text="Search", fg_color=CYAN, text_color=BG_DARK,
                      hover_color=CYAN_DARK, width=80, height=38,
                      command=self._load_prompts).grid(row=0, column=1)

        # Filter pills
        filter_row = ctk.CTkFrame(frame, fg_color="transparent")
        filter_row.grid(row=1, column=0, sticky="w", padx=16, pady=(4, 8))

        self._filter_buttons: dict[str, ctk.CTkButton] = {}
        for cat in ["All", "Image", "Video"]:
            btn = ctk.CTkButton(
                filter_row, text=cat, width=70, height=30, corner_radius=15,
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color=CYAN if cat == "All" else "transparent",
                text_color=BG_DARK if cat == "All" else TEXT_DIM,
                border_color=CYAN, border_width=1,
                hover_color=CYAN_DARK,
                command=lambda c=cat: self._set_filter(c),
            )
            btn.pack(side="left", padx=3)
            self._filter_buttons[cat] = btn

        # Scrollable grid
        self._home_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self._home_scroll.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0, 8))

    def _set_filter(self, cat: str):
        self._current_filter = cat
        for k, btn in self._filter_buttons.items():
            if k == cat:
                btn.configure(fg_color=CYAN, text_color=BG_DARK)
            else:
                btn.configure(fg_color="transparent", text_color=TEXT_DIM)
        self._load_prompts()

    def _load_prompts(self):
        search = self._search_entry.get().strip() if hasattr(self, "_search_entry") else ""
        threading.Thread(target=self._fetch_prompts, args=(search, self._current_filter, False), daemon=True).start()

    def _load_bookmarks(self):
        threading.Thread(target=self._fetch_bookmarks, daemon=True).start()

    def _fetch_prompts(self, search: str, category: str, mine_only: bool):
        try:
            prompts = self.api.list_prompts(search=search, category=category)
            if mine_only:
                prompts = [p for p in prompts if p.get("author") == self.api.username]
            self.after(0, self._render_prompt_grid, self._home_scroll, prompts, False)
        except Exception as e:
            self.after(0, self._toast, f"Error: {e}", "error")

    def _fetch_bookmarks(self):
        try:
            bms = self.api.list_bookmarks()
            self.after(0, self._render_prompt_grid, self._home_scroll, bms, False)
        except Exception as e:
            self.after(0, self._toast, f"Error: {e}", "error")

    def _render_prompt_grid(self, container, prompts: list[dict], show_actions: bool):
        for w in container.winfo_children():
            w.destroy()

        if not prompts:
            ctk.CTkLabel(container, text="📭 No prompts found",
                         font=ctk.CTkFont(size=16), text_color=TEXT_DIM).pack(pady=60)
            return

        # Create grid layout
        cols = max(1, (container.winfo_width() or 800) // (CARD_WIDTH + 16))
        for i, p in enumerate(prompts):
            row, col = divmod(i, cols)
            card = self._create_card(container, p, show_actions)
            card.grid(row=row, column=col, padx=8, pady=8, sticky="n")

    def _create_card(self, parent, prompt: dict, show_actions: bool) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, width=CARD_WIDTH, height=CARD_HEIGHT,
                            fg_color=BG_CARD, corner_radius=12, border_width=1,
                            border_color="#2a3a52")
        card.grid_propagate(False)
        card.grid_columnconfigure(0, weight=1)

        # Thumbnail placeholder
        thumb_frame = ctk.CTkFrame(card, height=THUMB_HEIGHT, fg_color="#111827", corner_radius=8)
        thumb_frame.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 0))
        thumb_frame.grid_propagate(False)
        thumb_frame.grid_columnconfigure(0, weight=1)
        thumb_frame.grid_rowconfigure(0, weight=1)

        thumb_label = ctk.CTkLabel(thumb_frame, text="🎨", font=ctk.CTkFont(size=36), text_color=TEXT_DIM)
        thumb_label.grid(row=0, column=0)

        # Load thumbnail asynchronously
        if prompt.get("thumbnail"):
            threading.Thread(target=self._load_thumb_async,
                             args=(thumb_label, prompt["thumbnail"]), daemon=True).start()

        # Card body
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.grid(row=1, column=0, sticky="ew", padx=8, pady=(4, 6))

        ctk.CTkLabel(body, text=prompt["title"],
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=TEXT, anchor="w").pack(fill="x")

        meta = f"{prompt['category']} · {prompt.get('model', '')} · {prompt.get('author', '')}"
        ctk.CTkLabel(body, text=meta,
                     font=ctk.CTkFont(size=10), text_color=TEXT_DIM, anchor="w").pack(fill="x")

        # Tags
        tags = [t.strip() for t in (prompt.get("tags", "") or "").split(",") if t.strip()]
        if tags:
            tag_frame = ctk.CTkFrame(body, fg_color="transparent")
            tag_frame.pack(fill="x", pady=(2, 0))
            for t in tags[:4]:
                ctk.CTkLabel(tag_frame, text=t,
                             font=ctk.CTkFont(size=9),
                             text_color=CYAN, fg_color="#0a2a3a",
                             corner_radius=8, padx=6, pady=1).pack(side="left", padx=1)

        # Actions for "my prompts"
        if show_actions:
            act_frame = ctk.CTkFrame(body, fg_color="transparent")
            act_frame.pack(fill="x", pady=(4, 0))
            ctk.CTkButton(act_frame, text="Edit", width=50, height=24,
                          font=ctk.CTkFont(size=11), fg_color=CYAN, text_color=BG_DARK,
                          command=lambda pid=prompt["id"]: self._edit_prompt(pid)).pack(side="left", padx=2)
            ctk.CTkButton(act_frame, text="Delete", width=50, height=24,
                          font=ctk.CTkFont(size=11), fg_color=CORAL, text_color="white",
                          command=lambda pid=prompt["id"]: self._delete_prompt(pid)).pack(side="left", padx=2)

        # Click to view detail
        card.bind("<Button-1>", lambda e, pid=prompt["id"]: self._open_detail(pid))
        for child in card.winfo_children():
            child.bind("<Button-1>", lambda e, pid=prompt["id"]: self._open_detail(pid))

        return card

    def _load_thumb_async(self, label: ctk.CTkLabel, filename: str):
        data = self.api.get_thumbnail_bytes(filename)
        if data:
            try:
                img = Image.open(BytesIO(data))
                img = img.resize((CARD_WIDTH - 12, THUMB_HEIGHT - 8), Image.LANCZOS)
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img,
                                       size=(CARD_WIDTH - 12, THUMB_HEIGHT - 8))
                self.after(0, lambda: label.configure(image=ctk_img, text=""))
                self._thumb_cache[filename] = ctk_img  # prevent GC
            except Exception:
                pass

    # ══════════════════════════════════════════
    #  DETAIL
    # ══════════════════════════════════════════

    def _build_detail_frame(self):
        frame = ctk.CTkFrame(self._main_frame, fg_color="transparent")
        self._register_frame("detail", frame)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        # Top bar
        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 0))
        ctk.CTkButton(top, text="< Back", fg_color=CORAL, text_color="white",
                      hover_color="#b91c1c", width=80, height=32,
                      command=lambda: self._show_frame("home")).pack(side="left")
        self._detail_title_lbl = ctk.CTkLabel(top, text="Prompt Details",
                                              font=ctk.CTkFont(size=18, weight="bold"),
                                              text_color=CYAN)
        self._detail_title_lbl.pack(side="left", padx=16)

        # Scrollable content
        self._detail_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self._detail_scroll.grid(row=1, column=0, sticky="nsew", padx=16, pady=12)

    def _open_detail(self, prompt_id: int):
        self._show_frame("detail")
        threading.Thread(target=self._fetch_detail, args=(prompt_id,), daemon=True).start()

    def _fetch_detail(self, prompt_id: int):
        try:
            p = self.api.get_prompt(prompt_id)
            self.after(0, self._render_detail, p)
        except Exception as e:
            self.after(0, self._toast, f"Error: {e}", "error")

    def _render_detail(self, p: dict):
        for w in self._detail_scroll.winfo_children():
            w.destroy()

        self._detail_title_lbl.configure(text=p["title"])

        # Thumbnail
        if p.get("thumbnail"):
            thumb_label = ctk.CTkLabel(self._detail_scroll, text="Loading...", text_color=TEXT_DIM)
            thumb_label.pack(pady=(0, 12))
            threading.Thread(target=self._load_detail_thumb,
                             args=(thumb_label, p["thumbnail"]), daemon=True).start()

        # Title
        ctk.CTkLabel(self._detail_scroll, text=p["title"],
                     font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w", pady=(0, 4))

        # Meta
        meta = f"{p['category']} · {p.get('model', 'Unknown')} · by {p.get('author', '')}"
        ctk.CTkLabel(self._detail_scroll, text=meta,
                     font=ctk.CTkFont(size=12), text_color=TEXT_DIM).pack(anchor="w", pady=(0, 12))

        # Prompt box
        prompt_frame = ctk.CTkFrame(self._detail_scroll, fg_color=BG_CARD, corner_radius=12)
        prompt_frame.pack(fill="x", pady=(0, 8))

        prompt_text = ctk.CTkTextbox(prompt_frame, height=120, fg_color="transparent",
                                     font=ctk.CTkFont(size=13), wrap="word",
                                     activate_scrollbars=False)
        prompt_text.pack(fill="x", padx=12, pady=(12, 4))
        prompt_text.insert("0.0", p["prompt"])
        prompt_text.configure(state="disabled")

        ctk.CTkButton(prompt_frame, text="📋 Copy Prompt",
                      fg_color=CYAN, text_color=BG_DARK, hover_color=CYAN_DARK,
                      height=30, corner_radius=15,
                      command=lambda: self._copy_text(p["prompt"])).pack(pady=(0, 12))

        # Bookmark button
        if self.api.is_logged_in:
            bm_text = "⭐ Remove Bookmark" if p.get("bookmarked") else "☆ Add Bookmark"
            ctk.CTkButton(self._detail_scroll, text=bm_text,
                          fg_color=ORANGE if p.get("bookmarked") else "transparent",
                          border_color=ORANGE, border_width=2,
                          text_color="white" if p.get("bookmarked") else ORANGE,
                          hover_color="#d97706", height=34, corner_radius=17,
                          command=lambda: self._do_toggle_bookmark(p)).pack(pady=8)

        # Tags
        tags = [t.strip() for t in (p.get("tags", "") or "").split(",") if t.strip()]
        if tags:
            tag_frame = ctk.CTkFrame(self._detail_scroll, fg_color="transparent")
            tag_frame.pack(anchor="w", pady=8)
            for t in tags:
                ctk.CTkLabel(tag_frame, text=t, font=ctk.CTkFont(size=11),
                             text_color=CYAN, fg_color="#0a2a3a",
                             corner_radius=10, padx=10, pady=3).pack(side="left", padx=2)

    def _load_detail_thumb(self, label, filename):
        data = self.api.get_thumbnail_bytes(filename)
        if data:
            try:
                img = Image.open(BytesIO(data))
                w, h = img.size
                new_w = min(600, w)
                new_h = int(h * new_w / w)
                img = img.resize((new_w, new_h), Image.LANCZOS)
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(new_w, new_h))
                self.after(0, lambda: label.configure(image=ctk_img, text=""))
                self._thumb_cache[f"detail_{filename}"] = ctk_img
            except Exception:
                pass

    def _copy_text(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)
        self._toast("Copied to clipboard!")

    def _do_toggle_bookmark(self, p: dict):
        try:
            self.api.toggle_bookmark(p["id"], p.get("bookmarked", False))
            self._toast("Bookmark updated ⭐")
            self._open_detail(p["id"])  # refresh
        except Exception as e:
            self._toast(str(e), "error")

    # ══════════════════════════════════════════
    #  UPLOAD / EDIT
    # ══════════════════════════════════════════

    def _build_upload_frame(self):
        frame = ctk.CTkFrame(self._main_frame, fg_color="transparent")
        self._register_frame("upload", frame)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)

        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew", padx=16, pady=12)
        scroll.grid_columnconfigure(0, weight=1)

        center = ctk.CTkFrame(scroll, fg_color="transparent", width=500)
        center.pack(anchor="center")

        ctk.CTkLabel(center, text="📤 Upload Prompt",
                     font=ctk.CTkFont(size=20, weight="bold"), text_color=CYAN).pack(pady=(12, 16))

        # Thumbnail picker
        self._thumb_preview = ctk.CTkLabel(center, text="🖼️ Click to select thumbnail",
                                           font=ctk.CTkFont(size=14), text_color=TEXT_DIM,
                                           fg_color=BG_CARD, corner_radius=12,
                                           width=300, height=120, cursor="hand2")
        self._thumb_preview.pack(pady=(0, 12))
        self._thumb_preview.bind("<Button-1>", lambda e: self._pick_thumbnail())
        self._thumb_path: str | None = None

        # Form fields
        self._upload_title = ctk.CTkEntry(center, placeholder_text="Title", width=340, height=40)
        self._upload_title.pack(pady=4)

        self._upload_prompt = ctk.CTkTextbox(center, width=340, height=120,
                                             font=ctk.CTkFont(size=13), corner_radius=8)
        self._upload_prompt.pack(pady=4)

        cat_row = ctk.CTkFrame(center, fg_color="transparent")
        cat_row.pack(fill="x", pady=4)
        ctk.CTkLabel(cat_row, text="Category:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 8))
        self._upload_cat = ctk.CTkComboBox(cat_row, values=["Image", "Video"], width=140,
                                           command=self._on_cat_change)
        self._upload_cat.pack(side="left")

        model_row = ctk.CTkFrame(center, fg_color="transparent")
        model_row.pack(fill="x", pady=4)
        ctk.CTkLabel(model_row, text="AI Model:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 8))
        self._upload_model = ctk.CTkComboBox(model_row, values=MODELS["Image"], width=180)
        self._upload_model.pack(side="left")

        self._upload_status = ctk.CTkLabel(center, text="", font=ctk.CTkFont(size=12))
        self._upload_status.pack(pady=4)

        ctk.CTkButton(center, text="Upload Prompt", fg_color=GREEN, hover_color="#059669",
                      text_color="white", height=40, corner_radius=20, width=280,
                      command=self._do_upload).pack(pady=8)
        ctk.CTkButton(center, text="< Back", fg_color="transparent", text_color=TEXT_DIM,
                      command=lambda: self._show_frame("home")).pack(pady=(0, 20))

        self._editing_id: int | None = None

    def _reset_upload_form(self):
        self._upload_title.delete(0, "end")
        self._upload_prompt.delete("0.0", "end")
        self._upload_cat.set("Image")
        self._upload_model.configure(values=MODELS["Image"])
        self._upload_model.set(MODELS["Image"][0])
        self._upload_status.configure(text="")
        self._thumb_path = None
        self._thumb_preview.configure(image=None, text="🖼️ Click to select thumbnail")
        self._editing_id = None

    def _on_cat_change(self, cat: str):
        models = MODELS.get(cat, [])
        self._upload_model.configure(values=models)
        if models:
            self._upload_model.set(models[0])

    def _pick_thumbnail(self):
        path = filedialog.askopenfilename(
            title="Select Thumbnail",
            filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.gif;*.webp")],
        )
        if path:
            self._thumb_path = path
            try:
                img = Image.open(path)
                img = img.resize((280, 110), Image.LANCZOS)
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(280, 110))
                self._thumb_preview.configure(image=ctk_img, text="")
                self._thumb_cache["upload_preview"] = ctk_img
            except Exception:
                self._thumb_preview.configure(text=os.path.basename(path))

    def _do_upload(self):
        title = self._upload_title.get().strip()
        prompt = self._upload_prompt.get("0.0", "end").strip()
        category = self._upload_cat.get()
        model = self._upload_model.get()

        if not title or not prompt:
            self._upload_status.configure(text="Title and prompt required", text_color=CORAL)
            return

        self._upload_status.configure(text="Uploading...", text_color=CYAN)

        def _upload():
            try:
                if self._editing_id:
                    self.api.update_prompt(self._editing_id, title, prompt, category,
                                           model, "", self._thumb_path)
                    self.after(0, self._toast, "Prompt updated!")
                else:
                    self.api.create_prompt(title, prompt, category, model, "", self._thumb_path)
                    self.after(0, self._toast, "Prompt uploaded!")
                self.after(0, lambda: self._show_frame("myprompts"))
            except Exception as e:
                self.after(0, lambda: self._upload_status.configure(text=str(e), text_color=CORAL))

        threading.Thread(target=_upload, daemon=True).start()

    def _edit_prompt(self, prompt_id: int):
        try:
            p = self.api.get_prompt(prompt_id)
            self._show_frame("upload")
            self._editing_id = prompt_id
            self._upload_title.delete(0, "end")
            self._upload_title.insert(0, p["title"])
            self._upload_prompt.delete("0.0", "end")
            self._upload_prompt.insert("0.0", p["prompt"])
            self._upload_cat.set(p["category"])
            self._on_cat_change(p["category"])
            self._upload_model.set(p.get("model", ""))
            if p.get("thumbnail"):
                self._thumb_preview.configure(text="(current thumbnail kept)")
        except Exception as e:
            self._toast(str(e), "error")

    def _delete_prompt(self, prompt_id: int):
        if messagebox.askyesno("Delete", "Delete this prompt?"):
            try:
                self.api.delete_prompt(prompt_id)
                self._toast("Prompt deleted")
                self._load_my_prompts()
            except Exception as e:
                self._toast(str(e), "error")

    # ══════════════════════════════════════════
    #  MY PROMPTS
    # ══════════════════════════════════════════

    def _build_my_prompts_frame(self):
        frame = ctk.CTkFrame(self._main_frame, fg_color="transparent")
        self._register_frame("myprompts", frame)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 0))
        ctk.CTkLabel(top, text="📝 My Prompts",
                     font=ctk.CTkFont(size=18, weight="bold"), text_color=CYAN).pack(side="left")
        ctk.CTkButton(top, text="+ New", fg_color=GREEN, hover_color="#059669",
                      text_color="white", width=80, height=32,
                      command=lambda: self._nav_to("upload")).pack(side="right")

        self._my_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self._my_scroll.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)

    def _load_my_prompts(self):
        threading.Thread(target=self._fetch_my_prompts, daemon=True).start()

    def _fetch_my_prompts(self):
        try:
            all_prompts = self.api.list_prompts()
            mine = [p for p in all_prompts if p.get("author") == self.api.username]
            self.after(0, self._render_prompt_grid, self._my_scroll, mine, True)
        except Exception as e:
            self.after(0, self._toast, f"Error: {e}", "error")

    # ══════════════════════════════════════════
    #  PROFILE
    # ══════════════════════════════════════════

    def _build_profile_frame(self):
        frame = ctk.CTkFrame(self._main_frame, fg_color="transparent")
        self._register_frame("profile", frame)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        center = ctk.CTkFrame(frame, fg_color=BG_CARD, corner_radius=20, width=380)
        center.place(relx=0.5, rely=0.5, anchor="center")

        self._avatar_label = ctk.CTkLabel(center, text="👤", font=ctk.CTkFont(size=50))
        self._avatar_label.pack(pady=(30, 8))

        ctk.CTkButton(center, text="📷 Upload Avatar", fg_color="transparent",
                      border_width=1, border_color=CYAN, text_color=CYAN,
                      width=140, height=28, font=ctk.CTkFont(size=11),
                      command=self._do_upload_avatar).pack(pady=(0, 16))

        self._profile_name_lbl = ctk.CTkLabel(center, text="GUEST",
                                              font=ctk.CTkFont(size=22, weight="bold"),
                                              text_color=CYAN)
        self._profile_name_lbl.pack(pady=(0, 16))

        ctk.CTkLabel(center, text="Change Name",
                     font=ctk.CTkFont(size=12), text_color=TEXT_DIM).pack()
        self._new_name_entry = ctk.CTkEntry(center, placeholder_text="New username", width=250, height=36)
        self._new_name_entry.pack(pady=4)

        self._profile_status = ctk.CTkLabel(center, text="", font=ctk.CTkFont(size=11))
        self._profile_status.pack()

        ctk.CTkButton(center, text="Save", fg_color=GREEN, hover_color="#059669",
                      text_color="white", width=250, height=36, corner_radius=18,
                      command=self._do_change_name).pack(pady=8)
        ctk.CTkButton(center, text="< Back", fg_color="transparent", text_color=TEXT_DIM,
                      command=lambda: self._show_frame("home")).pack(pady=(0, 30))

    def _update_profile_ui(self):
        name = self.api.username or "GUEST"
        self._profile_name_lbl.configure(text=name)
        self._load_profile_avatar()

    def _load_profile_avatar(self):
        filename = getattr(self.api, "avatar", None)
        if filename:
            threading.Thread(target=self._load_avatar_async, args=(filename,), daemon=True).start()
        else:
            self._avatar_label.configure(image=None, text="👤")

    def _load_avatar_async(self, filename):
        data = self.api.get_thumbnail_bytes(filename)
        if data:
            try:
                img = Image.open(BytesIO(data))
                img = img.resize((100, 100), Image.LANCZOS)
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(100, 100))
                self.after(0, lambda: self._avatar_label.configure(image=ctk_img, text=""))
            except Exception:
                pass

    def _do_upload_avatar(self):
        path = filedialog.askopenfilename(
            title="Select Avatar",
            filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.gif;*.webp")],
        )
        if not path:
            return
        
        self._profile_status.configure(text="Uploading...", text_color=CYAN)
        def _upload():
            try:
                self.api.update_avatar(path)
                self.after(0, lambda: self._profile_status.configure(text="Avatar updated!", text_color=GREEN))
                self.after(0, self._toast, "Avatar updated!")
                self.after(0, self._update_profile_ui)
            except Exception as e:
                self.after(0, lambda: self._profile_status.configure(text=str(e), text_color=CORAL))
        
        threading.Thread(target=_upload, daemon=True).start()

    def _do_change_name(self):
        name = self._new_name_entry.get().strip()
        if not name:
            self._profile_status.configure(text="Enter a name", text_color=CORAL)
            return
        try:
            self.api.update_name(name)
            self._profile_name_lbl.configure(text=name)
            self._profile_status.configure(text="Name updated!", text_color=GREEN)
            self._toast("Name updated!")
        except Exception as e:
            self._profile_status.configure(text=str(e), text_color=CORAL)

    # ══════════════════════════════════════════
    #  LOGOUT
    # ══════════════════════════════════════════

    def _logout(self):
        self.api.logout()
        self._update_sidebar()
        self._toast("Logged out")
        self._show_frame("welcome")

    # ══════════════════════════════════════════
    #  TOAST
    # ══════════════════════════════════════════

    def _toast(self, msg: str, kind: str = "success"):
        color = GREEN if kind == "success" else CORAL
        toast = ctk.CTkFrame(self, fg_color=color, corner_radius=8)
        toast.place(relx=0.98, rely=0.02, anchor="ne")
        ctk.CTkLabel(toast, text=msg, text_color="white",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     padx=16, pady=8).pack()
        self.after(3000, toast.destroy)


# ──────────────────── Entry Point ────────────────────

if __name__ == "__main__":
    app = PromptLibraryApp()
    app.mainloop()
