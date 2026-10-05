"""Prompt Library — FastAPI Server (clean rebuild)."""

import os
import re
import sys
import uuid
import shutil
import webbrowser
import threading
import time
from pathlib import Path
from contextlib import asynccontextmanager

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import pyotp
import qrcode
import base64
from io import BytesIO
from datetime import datetime, timedelta

from fastapi import (
    FastAPI, Request, UploadFile, File, Form,
    Depends, HTTPException, Header,
)
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from werkzeug.security import generate_password_hash, check_password_hash

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

GOOGLE_CLIENT_ID = "114433117983-8ndrk5g3k6n4eshc05llgj0m1an5m5cm.apps.googleusercontent.com"

from database import get_db, init_db

# ──────────────────── Paths ────────────────────

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "uploads"
UPLOAD_FOLDER.mkdir(exist_ok=True)
WEB_DIR = BASE_DIR.parent / "client" / "web"

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

TEMP_2FA_SESSIONS = {}  # { temp_token: user_id }

# ──────────────────── Auth helpers ────────────────────

def get_current_user(authorization: str | None = None) -> int | None:
    """Extract user_id from Bearer token. Returns None if invalid."""
    if not authorization:
        return None
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    db = get_db()
    row = db.execute("SELECT user_id FROM tokens WHERE token = ?", (token,)).fetchone()
    db.close()
    return row["user_id"] if row else None


def require_login(authorization: str | None = Header(None)) -> int:
    """FastAPI dependency — raises 401 if not authenticated."""
    user_id = get_current_user(authorization)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


# ──────────────────── Lifespan ────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()


    # Auto-open browser after a short delay
    def _open():
        time.sleep(1.2)
        webbrowser.open("http://127.0.0.1:5000")

    threading.Thread(target=_open, daemon=True).start()
    yield


# ──────────────────── App ────────────────────

app = FastAPI(title="Prompt Library API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════
#  AUTH ROUTES
# ══════════════════════════════════════════════

@app.post("/api/signup")
async def signup(request: Request):
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "")
    email = body.get("email", "").strip()
    if not username or not password:
        raise HTTPException(400, "Username and password required")
    if len(password) < 4:
        raise HTTPException(400, "Password must be at least 4 characters")

    db = get_db()
    if db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
        db.close()
        raise HTTPException(409, "Username already taken")

    hashed = generate_password_hash(password)
    cur = db.execute("INSERT INTO users (username, password, email) VALUES (?, ?, ?)", (username, hashed, email or None))
    user_id = cur.lastrowid
    token = uuid.uuid4().hex
    db.execute("INSERT INTO tokens (token, user_id) VALUES (?, ?)", (token, user_id))
    db.commit()
    db.close()
    return {"token": token, "user_id": user_id, "username": username}


@app.post("/api/login")
async def login(request: Request):
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "")

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not user or not check_password_hash(user["password"], password):
        db.close()
        raise HTTPException(401, "Invalid username or password")

    if user["is_totp_enabled"]:
        temp_token = uuid.uuid4().hex
        TEMP_2FA_SESSIONS[temp_token] = user["id"]
        db.close()
        return {"requires_2fa": True, "temp_token": temp_token}

    token = uuid.uuid4().hex
    db.execute("INSERT INTO tokens (token, user_id) VALUES (?, ?)", (token, user["id"]))
    db.commit()
    db.close()
    return {"token": token, "user_id": user["id"], "username": user["username"]}

@app.post("/api/login/2fa")
async def login_2fa(request: Request):
    body = await request.json()
    temp_token = body.get("temp_token", "")
    code = body.get("code", "")
    
    user_id = TEMP_2FA_SESSIONS.get(temp_token)
    if not user_id:
        raise HTTPException(401, "Invalid or expired 2FA session")
        
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user or not user["totp_secret"]:
        db.close()
        raise HTTPException(400, "2FA not configured")
        
    totp = pyotp.TOTP(user["totp_secret"])
    if not totp.verify(code, valid_window=1):
        db.close()
        raise HTTPException(401, "Invalid 2FA code")
        
    del TEMP_2FA_SESSIONS[temp_token]
    token = uuid.uuid4().hex
    db.execute("INSERT INTO tokens (token, user_id) VALUES (?, ?)", (token, user_id))
    db.commit()
    db.close()
    return {"token": token, "user_id": user_id, "username": user["username"]}


@app.post("/api/auth/google")
async def google_login(request: Request):
    body = await request.json()
    credential = body.get("credential", "")
    if not credential:
        raise HTTPException(400, "Missing Google credential")

    try:
        idinfo = id_token.verify_oauth2_token(
            credential, google_requests.Request(), GOOGLE_CLIENT_ID
        )
    except ValueError:
        raise HTTPException(401, "Invalid Google token")

    google_id = idinfo["sub"]
    name = idinfo.get("name", "Google User")
    email = idinfo.get("email", "")

    db = get_db()

    # Check if user with this google_id exists
    user = db.execute("SELECT * FROM users WHERE google_id = ?", (google_id,)).fetchone()

    if not user:
        # Create new user — use email prefix or name as username
        base_name = email.split("@")[0] if email else name
        username = base_name
        counter = 1
        while db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
            username = f"{base_name}{counter}"
            counter += 1

        # Google users get a random password (they'll never use it)
        random_pw = generate_password_hash(uuid.uuid4().hex)
        cur = db.execute(
            "INSERT INTO users (username, password, google_id) VALUES (?, ?, ?)",
            (username, random_pw, google_id),
        )
        user_id = cur.lastrowid
        db.commit()
        username_final = username
    else:
        user_id = user["id"]
        username_final = user["username"]

    token = uuid.uuid4().hex
    db.execute("INSERT INTO tokens (token, user_id) VALUES (?, ?)", (token, user_id))
    db.commit()
    db.close()
    return {"token": token, "user_id": user_id, "username": username_final}


# ──────────────────── 2FA and Password Reset ────────────────────

@app.get("/api/2fa/setup")
async def setup_2fa(user_id: int = Depends(require_login)):
    db = get_db()
    user = db.execute("SELECT username, totp_secret, is_totp_enabled FROM users WHERE id = ?", (user_id,)).fetchone()
    db.close()
    
    if user["is_totp_enabled"]:
        return {"message": "2FA is already enabled", "enabled": True}
        
    secret = user["totp_secret"]
    if not secret:
        secret = pyotp.random_base32()
        db = get_db()
        db.execute("UPDATE users SET totp_secret = ? WHERE id = ?", (secret, user_id))
        db.commit()
        db.close()
        
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=user["username"], issuer_name="Prompt Library")
    
    import qrcode.image.svg
    from urllib.parse import quote
    
    factory = qrcode.image.svg.SvgPathImage
    qr_img = qrcode.make(uri, image_factory=factory, box_size=10, border=4)
    
    buf = BytesIO()
    qr_img.save(buf)
    svg_data = buf.getvalue().decode("utf-8")
    qr_b64 = "data:image/svg+xml;utf8," + quote(svg_data)
    
    return {"secret": secret, "qr": qr_b64, "enabled": False}

@app.post("/api/2fa/verify")
async def verify_2fa(request: Request, user_id: int = Depends(require_login)):
    body = await request.json()
    code = body.get("code", "")
    
    db = get_db()
    user = db.execute("SELECT totp_secret FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user or not user["totp_secret"]:
        db.close()
        raise HTTPException(400, "No 2FA setup initiated")
        
    totp = pyotp.TOTP(user["totp_secret"])
    if not totp.verify(code, valid_window=1):
        db.close()
        raise HTTPException(401, "Invalid 2FA code (ensure your phone's clock is synced)")
        
    db.execute("UPDATE users SET is_totp_enabled = 1 WHERE id = ?", (user_id,))
    db.commit()
    db.close()
    return {"message": "2FA successfully enabled"}

@app.post("/api/forgot-password-2fa")
async def forgot_password_2fa(request: Request):
    body = await request.json()
    username_or_email = body.get("username", "").strip()
    code = body.get("code", "").strip()
    if not username_or_email or not code:
        raise HTTPException(400, "Username/Email and 2FA code are required")
        
    db = get_db()
    user = db.execute("SELECT id, username, totp_secret, is_totp_enabled FROM users WHERE email = ? OR username = ?", (username_or_email, username_or_email)).fetchone()
    if not user:
        db.close()
        raise HTTPException(400, "User not found")
        
    if not user["is_totp_enabled"] or not user["totp_secret"]:
        db.close()
        raise HTTPException(400, "2FA is not enabled on this account. Cannot reset via 2FA.")
        
    totp = pyotp.TOTP(user["totp_secret"])
    if not totp.verify(code, valid_window=1):
        db.close()
        raise HTTPException(401, "Invalid 2FA code")
        
    reset_token = uuid.uuid4().hex
    expiry = (datetime.utcnow() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("UPDATE users SET reset_token = ?, reset_expires_at = ? WHERE id = ?", (reset_token, expiry, user["id"]))
    db.commit()
    db.close()
    
    return {"reset_token": reset_token}

@app.post("/api/forgot-password")
async def forgot_password(request: Request):
    body = await request.json()
    email_addr = body.get("email", "").strip()
    if not email_addr:
        raise HTTPException(400, "Email required")
        
    db = get_db()
    user = db.execute("SELECT id, username FROM users WHERE email = ?", (email_addr,)).fetchone()
    if not user:
        db.close()
        return {"message": "If that email exists, a reset link has been sent."}
        
    reset_token = uuid.uuid4().hex
    expiry = (datetime.utcnow() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("UPDATE users SET reset_token = ?, reset_expires_at = ? WHERE id = ?", (reset_token, expiry, user["id"]))
    db.commit()
    db.close()
    
    smtp_user = os.environ.get("SMTP_EMAIL")
    smtp_pass = os.environ.get("SMTP_PASSWORD")
    host_header = request.headers.get("host", "promptlib.com")
    protocol = "https" if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https" else "http"
    
    reset_link = f"{protocol}://{host_header}/reset.html?token={reset_token}"
    
    if not smtp_user or not smtp_pass:
        print(f"WARNING: No SMTP set. Password Reset link: {reset_link}")
        return {"message": "If that email exists, a reset link has been sent."}
        
    try:
        msg = MIMEMultipart()
        msg['From'] = smtp_user
        msg['To'] = email_addr
        msg['Subject'] = "Prompt Library Password Reset"
        msg.attach(MIMEText(f"Reset your password by clicking here: {reset_link}", 'plain'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
    except Exception as e:
        print("SMTP Error:", e)
        
    return {"message": "If that email exists, a reset link has been sent."}

@app.post("/api/reset-password")
async def reset_password(request: Request):
    body = await request.json()
    token = body.get("token", "")
    new_password = body.get("password", "")
    if not token or len(new_password) < 4:
        raise HTTPException(400, "Invalid request")
        
    db = get_db()
    user = db.execute("SELECT id, reset_expires_at FROM users WHERE reset_token = ?", (token,)).fetchone()
    if not user:
        db.close()
        raise HTTPException(400, "Invalid or expired reset token")
        
    if user["reset_expires_at"] < datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"):
        db.close()
        raise HTTPException(400, "Reset token has expired")
        
    hashed = generate_password_hash(new_password)
    db.execute("UPDATE users SET password = ?, reset_token = NULL, reset_expires_at = NULL WHERE id = ?", (hashed, user["id"]))
    db.commit()
    db.close()
    return {"message": "Password successfully reset"}


@app.get("/api/me")
async def me(user_id: int = Depends(require_login)):
    db = get_db()
    user = db.execute("SELECT id, username, avatar FROM users WHERE id = ?", (user_id,)).fetchone()
    db.close()
    if not user:
        raise HTTPException(404, "User not found")
    return {"user_id": user["id"], "username": user["username"], "avatar": user["avatar"] or ""}


@app.put("/api/me")
async def update_me(request: Request, user_id: int = Depends(require_login)):
    body = await request.json()
    new_name = body.get("username", "").strip()
    if not new_name:
        raise HTTPException(400, "Username required")

    db = get_db()
    existing = db.execute("SELECT id FROM users WHERE username = ? AND id != ?", (new_name, user_id)).fetchone()
    if existing:
        db.close()
        raise HTTPException(409, "Username already taken")

    db.execute("UPDATE users SET username = ? WHERE id = ?", (new_name, user_id))
    db.commit()
    db.close()
    return {"username": new_name}


@app.put("/api/me/avatar")
async def update_avatar(
    avatar: UploadFile = File(...),
    user_id: int = Depends(require_login)
):
    if not avatar.filename:
        raise HTTPException(400, "No file uploaded")
    
    ext = avatar.filename.split(".")[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, "Invalid image type")
    
    filename = f"avatar_{user_id}_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = UPLOAD_FOLDER / filename
    
    with open(filepath, "wb") as f:
        shutil.copyfileobj(avatar.file, f)
        
    db = get_db()
    # Optional: remove old avatar
    old = db.execute("SELECT avatar FROM users WHERE id = ?", (user_id,)).fetchone()
    if old and old["avatar"]:
        try:
            (UPLOAD_FOLDER / old["avatar"]).unlink(missing_ok=True)
        except Exception:
            pass

    db.execute("UPDATE users SET avatar = ? WHERE id = ?", (filename, user_id))
    db.commit()
    db.close()
    
    return {"avatar": filename}


# ══════════════════════════════════════════════
#  PROMPT ROUTES
# ══════════════════════════════════════════════

@app.get("/api/prompts")
async def list_prompts(
    search: str = "",
    category: str = "All",
    authorization: str | None = Header(None),
):
    db = get_db()
    current_user = get_current_user(authorization)

    sql = "SELECT p.*, u.username AS author FROM prompts p JOIN users u ON p.user_id = u.id"
    params: list = []
    clauses: list = []

    if category and category != "All":
        clauses.append("p.category = ?")
        params.append(category)
    if search:
        clauses.append("(p.title LIKE ? OR p.prompt LIKE ? OR p.tags LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like])

    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY p.created_at DESC"

    rows = db.execute(sql, params).fetchall()

    # Attach bookmark status
    bookmarked_ids = set()
    if current_user:
        bm = db.execute("SELECT prompt_id FROM bookmarks WHERE user_id = ?", (current_user,)).fetchall()
        bookmarked_ids = {r["prompt_id"] for r in bm}

    result = []
    for r in rows:
        d = dict(r)
        d["bookmarked"] = d["id"] in bookmarked_ids
        result.append(d)

    db.close()
    return result


@app.get("/api/prompts/{prompt_id}")
async def get_prompt(prompt_id: int, authorization: str | None = Header(None)):
    db = get_db()
    row = db.execute(
        "SELECT p.*, u.username AS author FROM prompts p JOIN users u ON p.user_id = u.id WHERE p.id = ?",
        (prompt_id,),
    ).fetchone()
    if not row:
        db.close()
        raise HTTPException(404, "Prompt not found")

    d = dict(row)
    current_user = get_current_user(authorization)
    if current_user:
        bm = db.execute(
            "SELECT id FROM bookmarks WHERE user_id = ? AND prompt_id = ?",
            (current_user, prompt_id),
        ).fetchone()
        d["bookmarked"] = bm is not None
    else:
        d["bookmarked"] = False
    db.close()
    return d


@app.post("/api/prompts")
async def create_prompt(
    title: str = Form(...),
    prompt: str = Form(...),
    category: str = Form("Image"),
    model: str = Form(""),
    tags: str = Form(""),
    instructions: str = Form(""),
    thumbnail: UploadFile | None = File(None),
    reference_images: list[UploadFile] = File([]),
    user_id: int = Depends(require_login),
):
    thumb_name = ""
    if thumbnail and thumbnail.filename:
        ext = thumbnail.filename.rsplit(".", 1)[-1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(400, "Invalid image type")
        thumb_name = f"thumb_{uuid.uuid4().hex}.{ext}"
        dest = UPLOAD_FOLDER / thumb_name
        with open(dest, "wb") as f:
            shutil.copyfileobj(thumbnail.file, f)

    ref_names = []
    if reference_images:
        for ref in reference_images[:2]:
            if ref and ref.filename:
                ext = ref.filename.rsplit(".", 1)[-1].lower()
                if ext in ALLOWED_EXTENSIONS:
                    name = f"ref_{uuid.uuid4().hex[:12]}.{ext}"
                    with open(UPLOAD_FOLDER / name, "wb") as f:
                        shutil.copyfileobj(ref.file, f)
                    ref_names.append(name)
    ref_str = ",".join(ref_names)

    db = get_db()
    cur = db.execute(
        "INSERT INTO prompts (user_id, title, prompt, category, model, tags, instructions, thumbnail, reference_images) VALUES (?,?,?,?,?,?,?,?,?)",
        (user_id, title, prompt, category, model, tags, instructions, thumb_name, ref_str),
    )
    db.commit()
    new_id = cur.lastrowid
    db.close()
    return {"id": new_id, "message": "Prompt created"}


@app.put("/api/prompts/{prompt_id}")
async def update_prompt(
    prompt_id: int,
    title: str = Form(...),
    prompt: str = Form(...),
    category: str = Form("Image"),
    model: str = Form(""),
    tags: str = Form(""),
    instructions: str = Form(""),
    thumbnail: UploadFile | None = File(None),
    reference_images: list[UploadFile] = File([]),
    user_id: int = Depends(require_login),
):
    db = get_db()
    existing = db.execute("SELECT * FROM prompts WHERE id = ? AND user_id = ?", (prompt_id, user_id)).fetchone()
    if not existing:
        db.close()
        raise HTTPException(403, "Not your prompt")

    thumb_name = existing["thumbnail"]
    if thumbnail and thumbnail.filename:
        ext = thumbnail.filename.rsplit(".", 1)[-1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(400, "Invalid image type")
        # Remove old thumbnail
        if thumb_name:
            old = UPLOAD_FOLDER / thumb_name
            if old.exists():
                old.unlink()
        thumb_name = f"thumb_{uuid.uuid4().hex}.{ext}"
        with open(UPLOAD_FOLDER / thumb_name, "wb") as f:
            shutil.copyfileobj(thumbnail.file, f)

    ref_str = existing["reference_images"]
    if reference_images and any(r.filename for r in reference_images):
        # Remove old references
        if ref_str:
            for old_ref in ref_str.split(","):
                if old_ref:
                    p = UPLOAD_FOLDER / old_ref
                    if p.exists():
                        p.unlink()
        
        # Save new references
        ref_names = []
        for ref in reference_images[:2]:
            if ref and ref.filename:
                ext = ref.filename.rsplit(".", 1)[-1].lower()
                if ext in ALLOWED_EXTENSIONS:
                    name = f"ref_{uuid.uuid4().hex[:12]}.{ext}"
                    with open(UPLOAD_FOLDER / name, "wb") as f:
                        shutil.copyfileobj(ref.file, f)
                    ref_names.append(name)
        ref_str = ",".join(ref_names)

    db.execute(
        "UPDATE prompts SET title=?, prompt=?, category=?, model=?, tags=?, instructions=?, thumbnail=?, reference_images=? WHERE id=?",
        (title, prompt, category, model, tags, instructions, thumb_name, ref_str, prompt_id),
    )
    db.commit()
    db.close()
    return {"message": "Prompt updated"}


@app.delete("/api/prompts/{prompt_id}")
async def delete_prompt(prompt_id: int, user_id: int = Depends(require_login)):
    db = get_db()
    row = db.execute("SELECT * FROM prompts WHERE id = ? AND user_id = ?", (prompt_id, user_id)).fetchone()
    if not row:
        db.close()
        raise HTTPException(403, "Not your prompt")

    if row["thumbnail"]:
        p = UPLOAD_FOLDER / row["thumbnail"]
        if p.exists():
            p.unlink()

    if row["reference_images"]:
        for ref in row["reference_images"].split(","):
            if ref:
                p = UPLOAD_FOLDER / ref
                if p.exists():
                    p.unlink()

    db.execute("DELETE FROM prompts WHERE id = ?", (prompt_id,))
    db.commit()
    db.close()
    return {"message": "Prompt deleted"}


# ══════════════════════════════════════════════
#  BOOKMARK ROUTES
# ══════════════════════════════════════════════

@app.get("/api/bookmarks")
async def list_bookmarks(user_id: int = Depends(require_login)):
    db = get_db()
    rows = db.execute(
        """SELECT p.*, u.username AS author
           FROM bookmarks b
           JOIN prompts p ON b.prompt_id = p.id
           JOIN users u ON p.user_id = u.id
           WHERE b.user_id = ?
           ORDER BY b.id DESC""",
        (user_id,),
    ).fetchall()
    db.close()
    return [dict(r) | {"bookmarked": True} for r in rows]


@app.post("/api/bookmarks/{prompt_id}")
async def add_bookmark(prompt_id: int, user_id: int = Depends(require_login)):
    db = get_db()
    try:
        db.execute("INSERT INTO bookmarks (user_id, prompt_id) VALUES (?, ?)", (user_id, prompt_id))
        db.commit()
    except Exception:
        pass  # already bookmarked
    db.close()
    return {"message": "Bookmarked"}


@app.delete("/api/bookmarks/{prompt_id}")
async def remove_bookmark(prompt_id: int, user_id: int = Depends(require_login)):
    db = get_db()
    db.execute("DELETE FROM bookmarks WHERE user_id = ? AND prompt_id = ?", (user_id, prompt_id))
    db.commit()
    db.close()
    return {"message": "Removed"}


# ══════════════════════════════════════════════
#  THUMBNAIL
# ══════════════════════════════════════════════

@app.get("/api/thumbnail/{filename}")
async def serve_thumbnail(filename: str):
    path = UPLOAD_FOLDER / filename
    if not path.exists():
        raise HTTPException(404, "Not found")
    return FileResponse(path)


# ══════════════════════════════════════════════
#  SHARE PAGE (public, no login required)
# ══════════════════════════════════════════════

@app.get("/share/{prompt_id}")
async def share_page(prompt_id: int):
    db = get_db()
    row = db.execute(
        "SELECT p.*, u.username AS author FROM prompts p JOIN users u ON p.user_id = u.id WHERE p.id = ?",
        (prompt_id,),
    ).fetchone()
    db.close()
    if not row:
        raise HTTPException(404, "Prompt not found")

    p = dict(row)
    thumb_tag = ""
    og_image = ""
    if p.get("thumbnail"):
        thumb_tag = f'<img class="share-thumb" src="/api/thumbnail/{p["thumbnail"]}" alt="{p["title"]}">'
        og_image = f'<meta property="og:image" content="/api/thumbnail/{p["thumbnail"]}">'

    tags_html = ""
    if p.get("tags"):
        tags_html = " ".join(f'<span class="tag">{t.strip()}</span>' for t in p["tags"].split(",") if t.strip())

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{p["title"]} — Prompt Library</title>
    <meta name="description" content="{p["prompt"][:160]}">
    <meta property="og:title" content="{p["title"]}">
    <meta property="og:description" content="{p["prompt"][:200]}">
    <meta property="og:type" content="article">
    {og_image}
    <style>
        *{{margin:0;padding:0;box-sizing:border-box}}
        body{{font-family:'Segoe UI',system-ui,sans-serif;background:#0a0e1a;color:#e2e8f0;min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:24px 16px}}
        .share-card{{max-width:600px;width:100%;background:rgba(22,34,54,0.65);border-radius:16px;border:1px solid rgba(0,224,255,0.15);padding:24px;backdrop-filter:blur(12px)}}
        .share-thumb{{width:100%;border-radius:12px;margin-bottom:16px;max-height:400px;object-fit:cover}}
        .share-title{{font-size:1.5rem;font-weight:700;color:#00e0ff;margin-bottom:8px}}
        .share-meta{{font-size:0.85rem;color:#94a3b8;margin-bottom:16px}}
        .share-prompt{{background:rgba(0,0,0,0.3);border-radius:10px;padding:16px;font-size:0.95rem;line-height:1.6;white-space:pre-wrap;color:#e2e8f0;border:1px solid rgba(255,255,255,0.06);position:relative}}
        .copy-btn{{position:absolute;top:8px;right:8px;background:#00e0ff;color:#0a0e1a;border:none;border-radius:6px;padding:6px 12px;cursor:pointer;font-size:0.8rem;font-weight:600}}
        .copy-btn:hover{{opacity:0.85}}
        .tag{{display:inline-block;background:rgba(0,224,255,0.1);color:#00e0ff;border-radius:20px;padding:4px 10px;font-size:0.75rem;margin:4px 4px 0 0}}
        .share-header{{text-align:center;margin-bottom:24px}}
        .share-header h1{{font-size:1.1rem;color:#00e0ff}}
        .share-header p{{font-size:0.8rem;color:#64748b;margin-top:4px}}
        .open-app{{display:inline-block;margin-top:16px;background:linear-gradient(135deg,#00e0ff,#0080ff);color:#fff;text-decoration:none;padding:10px 24px;border-radius:10px;font-weight:600;font-size:0.9rem}}
        .open-app:hover{{opacity:0.9}}
    </style>
</head>
<body>
    <div class="share-header">
        <h1>📚 Prompt Library</h1>
        <p>Shared prompt</p>
    </div>
    <div class="share-card">
        {thumb_tag}
        <div class="share-title">{p["title"]}</div>
        <div class="share-meta">{p["category"]} · {p.get("model","Unknown")} · by {p["author"]}</div>
        <div class="share-prompt">
            <button class="copy-btn" onclick="navigator.clipboard.writeText(this.parentElement.textContent.replace('📋 Copy','').trim());this.textContent='✅ Copied!'">📋 Copy</button>
            {p["prompt"]}
        </div>
        <div style="margin-top:10px">{tags_html}</div>
        <div style="text-align:center">
            <a class="open-app" href="/">Open Prompt Library</a>
        </div>
    </div>
</body>
</html>"""
    return Response(html, media_type="text/html")


# ══════════════════════════════════════════════
#  PRIVACY POLICY
# ══════════════════════════════════════════════

@app.get("/privacy")
async def privacy_page():
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Privacy Policy — Prompt Library</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:'Segoe UI',system-ui,sans-serif;background:#0a0e1a;color:#e2e8f0;padding:24px 16px;line-height:1.7}
        .container{max-width:700px;margin:0 auto}
        h1{color:#00e0ff;font-size:1.6rem;margin-bottom:24px}
        h2{color:#00e0ff;font-size:1.1rem;margin:24px 0 8px}
        p,li{font-size:0.9rem;color:#94a3b8;margin-bottom:8px}
        ul{padding-left:20px}
        a{color:#00e0ff}
        .back{display:inline-block;margin-top:24px;color:#00e0ff;text-decoration:none;font-size:0.9rem}
    </style>
</head>
<body>
    <div class="container">
        <h1>Privacy Policy</h1>
        <p><em>Last updated: March 2026</em></p>

        <h2>1. Information We Collect</h2>
        <ul>
            <li><strong>Account data:</strong> Username and hashed password when you sign up.</li>
            <li><strong>Content:</strong> Prompts, tags, and thumbnails you upload.</li>
            <li><strong>Usage data:</strong> Basic server logs (IP address, pages visited).</li>
        </ul>

        <h2>2. Cookies & Advertising</h2>
        <p>We use <strong>Google AdSense</strong> to display ads. Google may use cookies and similar technologies to serve ads based on your browsing activity. You can manage your ad preferences at <a href="https://adssettings.google.com" target="_blank">Google Ad Settings</a>.</p>
        <p>We only load advertising cookies after you click <strong>Accept</strong> on our cookie consent banner.</p>

        <h2>3. How We Use Your Data</h2>
        <ul>
            <li>To provide and maintain the service</li>
            <li>To display your shared prompts</li>
            <li>To show relevant advertisements via Google AdSense</li>
        </ul>

        <h2>4. Your Rights (GDPR & CCPA)</h2>
        <ul>
            <li><strong>Access:</strong> You can request a copy of your data.</li>
            <li><strong>Deletion:</strong> You can delete your account and all associated prompts.</li>
            <li><strong>Opt-out:</strong> You can decline cookies via the consent banner.</li>
            <li><strong>Do Not Sell:</strong> We do not sell your personal information.</li>
        </ul>

        <h2>5. Data Storage</h2>
        <p>Your data is stored on a secured server. Passwords are hashed and never stored in plain text.</p>

        <h2>6. Third-Party Services</h2>
        <p>We use Google AdSense and Cloudflare. Each has its own privacy policy.</p>

        <h2>7. Contact</h2>
        <p>For privacy concerns, email us at the contact provided on the site.</p>

        <a class="back" href="/">← Back to Prompt Library</a>
    </div>
</body>
</html>"""
    return Response(html, media_type="text/html")


# ══════════════════════════════════════════════
#  STATIC FRONTEND
# ══════════════════════════════════════════════

def _minify(code: str, lang: str) -> str:
    """Lightweight minification — strip comments and blank lines."""
    if lang == "js":
        code = re.sub(r"/\*[\s\S]*?\*/", "", code)
        code = re.sub(r'(?<![:"\x27`])//(?!["\x27]).*', "", code)
    elif lang == "css":
        code = re.sub(r"/\*[\s\S]*?\*/", "", code)
    elif lang == "html":
        code = re.sub(r"<!--[\s\S]*?-->", "", code)
    code = re.sub(r"\n\s*\n+", "\n", code)
    code = "\n".join(l.rstrip() for l in code.splitlines())
    return code.strip()


if WEB_DIR.exists():

    @app.get("/")
    async def serve_index():
        raw = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        return Response(_minify(raw, "html"), media_type="text/html")

    @app.get("/reset.html")
    async def serve_reset():
        raw = (WEB_DIR / "reset.html").read_text(encoding="utf-8")
        return Response(raw, media_type="text/html")

    @app.get("/manifest.json")
    async def serve_manifest():
        return FileResponse(WEB_DIR / "manifest.json", media_type="application/manifest+json")

    @app.get("/service-worker.js")
    async def serve_sw():
        raw = (WEB_DIR / "service-worker.js").read_text(encoding="utf-8")
        return Response(_minify(raw, "js"), media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})

    @app.get("/static/{filepath:path}")
    async def serve_static(filepath: str):
        full = WEB_DIR / filepath
        if not full.exists() or not full.is_file():
            raise HTTPException(404, "Not found")
        ext = full.suffix.lower()
        if ext == ".js":
            return Response(_minify(full.read_text("utf-8"), "js"), media_type="application/javascript")
        if ext == ".css":
            return Response(_minify(full.read_text("utf-8"), "css"), media_type="text/css")
        return FileResponse(full)


# ══════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 80))
    print(f"Server starting -> http://localhost:{port}")
    uvicorn.run(app, host=host, port=port)
