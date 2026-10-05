# ── api_client.py ── HTTP wrapper for Prompt Library server ──

import os
import requests
from io import BytesIO

# To connect to your OCI server, replace this URL with your server IP:
# e.g. "http://123.456.78.90:5000"
BASE_URL = os.environ.get("SERVER_URL", "http://127.0.0.1:5000")


class ApiClient:
    """Thin wrapper around the FastAPI server endpoints."""

    def __init__(self):
        self.token: str | None = None
        self.user_id: int | None = None
        self.username: str | None = None

    # ─── helpers ───

    def _headers(self) -> dict:
        h = {}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _get(self, path: str, params: dict | None = None):
        r = requests.get(f"{BASE_URL}{path}", headers=self._headers(), params=params, timeout=10)
        r.raise_for_status()
        return r.json()

    def _post_json(self, path: str, data: dict):
        r = requests.post(f"{BASE_URL}{path}", headers=self._headers(), json=data, timeout=10)
        r.raise_for_status()
        return r.json()

    def _put_json(self, path: str, data: dict):
        r = requests.put(f"{BASE_URL}{path}", headers=self._headers(), json=data, timeout=10)
        r.raise_for_status()
        return r.json()

    def _post_form(self, path: str, fields: dict, file_path: str | None = None):
        files = {}
        if file_path:
            files["thumbnail"] = open(file_path, "rb")
        r = requests.post(
            f"{BASE_URL}{path}", headers=self._headers(),
            data=fields, files=files if files else None, timeout=30,
        )
        if files:
            files["thumbnail"].close()
        r.raise_for_status()
        return r.json()

    def _put_form(self, path: str, fields: dict, file_path: str | None = None):
        files = {}
        if file_path:
            files["thumbnail"] = open(file_path, "rb")
        r = requests.put(
            f"{BASE_URL}{path}", headers=self._headers(),
            data=fields, files=files if files else None, timeout=30,
        )
        if files:
            files["thumbnail"].close()
        r.raise_for_status()
        return r.json()

    def _delete(self, path: str):
        r = requests.delete(f"{BASE_URL}{path}", headers=self._headers(), timeout=10)
        r.raise_for_status()
        return r.json()

    # ─── Auth ───

    def signup(self, username: str, password: str) -> dict:
        data = self._post_json("/api/signup", {"username": username, "password": password})
        self.token = data["token"]
        self.user_id = data["user_id"]
        self.username = data["username"]
        return data

    def login(self, username: str, password: str) -> dict:
        data = self._post_json("/api/login", {"username": username, "password": password})
        self.token = data["token"]
        self.user_id = data["user_id"]
        self.username = data["username"]
        return data

    def me(self) -> dict:
        data = self._get("/api/me")
        self.user_id = data["user_id"]
        self.username = data["username"]
        self.avatar = data.get("avatar")
        return data

    def update_name(self, new_name: str) -> dict:
        data = self._put_json("/api/me", {"username": new_name})
        self.username = data["username"]
        return data

    def update_avatar(self, file_path: str) -> dict:
        files = {"avatar": open(file_path, "rb")}
        r = requests.put(
            f"{BASE_URL}/api/me/avatar",
            headers=self._headers(),
            files=files,
            timeout=30
        )
        files["avatar"].close()
        r.raise_for_status()
        self.avatar = r.json().get("avatar")
        return r.json()

    def logout(self):
        self.token = None
        self.user_id = None
        self.username = None

    @property
    def is_logged_in(self) -> bool:
        return self.token is not None

    # ─── Prompts ───

    def list_prompts(self, search: str = "", category: str = "All") -> list[dict]:
        params = {}
        if search:
            params["search"] = search
        if category and category != "All":
            params["category"] = category
        return self._get("/api/prompts", params)

    def get_prompt(self, prompt_id: int) -> dict:
        return self._get(f"/api/prompts/{prompt_id}")

    def create_prompt(self, title: str, prompt: str, category: str, model: str,
                      tags: str = "", thumbnail_path: str | None = None) -> dict:
        fields = {"title": title, "prompt": prompt, "category": category, "model": model, "tags": tags}
        return self._post_form("/api/prompts", fields, thumbnail_path)

    def update_prompt(self, prompt_id: int, title: str, prompt: str, category: str,
                      model: str, tags: str = "", thumbnail_path: str | None = None) -> dict:
        fields = {"title": title, "prompt": prompt, "category": category, "model": model, "tags": tags}
        return self._put_form(f"/api/prompts/{prompt_id}", fields, thumbnail_path)

    def delete_prompt(self, prompt_id: int) -> dict:
        return self._delete(f"/api/prompts/{prompt_id}")

    # ─── Bookmarks ───

    def list_bookmarks(self) -> list[dict]:
        return self._get("/api/bookmarks")

    def add_bookmark(self, prompt_id: int) -> dict:
        return self._post_json(f"/api/bookmarks/{prompt_id}", {})

    def remove_bookmark(self, prompt_id: int) -> dict:
        return self._delete(f"/api/bookmarks/{prompt_id}")

    def toggle_bookmark(self, prompt_id: int, currently_bookmarked: bool) -> dict:
        if currently_bookmarked:
            return self.remove_bookmark(prompt_id)
        else:
            return self.add_bookmark(prompt_id)

    # ─── Thumbnail ───

    def get_thumbnail_bytes(self, filename: str) -> bytes | None:
        """Download thumbnail image as raw bytes."""
        if not filename:
            return None
        try:
            r = requests.get(f"{BASE_URL}/api/thumbnail/{filename}", timeout=10)
            r.raise_for_status()
            return r.content
        except Exception:
            return None
