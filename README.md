# 📚 Prompt Library — Serverless Stack

A modern, high-performance, serverless AI Prompt Library web application and Progressive Web App (PWA). Migrated from Python FastAPI/SQLite to **Netlify** (static hosting + serverless functions) and **Supabase** (PostgreSQL, Supabase Auth, and Supabase Storage).

---

## ⚡ Architecture Overview

| Component | Legacy Stack | Serverless Target Stack |
| :--- | :--- | :--- |
| **Frontend Hosting** | Python static file server | **Netlify CDN** (`public/`) |
| **Backend & API** | FastAPI / Flask (`server.py`) | **Netlify Serverless Functions** (`netlify/functions/api.js`) |
| **Database** | SQLite (`prompts.db`) | **Supabase PostgreSQL** (`supabase/schema.sql`) |
| **File Storage** | Local `/uploads` directory | **Supabase Storage** (`thumbnails`, `avatars` buckets) |
| **Authentication** | Custom SQLite Bearer token table | **Supabase Auth** (JWT sessions & RLS) |
| **Client App** | Vanilla JS PWA | **Vanilla JS PWA + Supabase JS SDK** |

---

## 📁 Repository Structure

```text
.
├── netlify/
│   └── functions/
│       └── api.js          # Unified Node.js serverless REST API for all routes
├── public/
│   ├── index.html          # Main SPA entry point with Supabase CDN SDK
│   ├── app.js              # Client state, Supabase auth session & API logic
│   ├── index.css           # Premium dark-theme design system (unchanged)
│   ├── manifest.json       # PWA manifest
│   ├── service-worker.js   # Service worker for offline asset caching
│   ├── icon-192.png        # PWA application icon (192x192)
│   └── icon-512.png        # PWA splash icon (512x512)
├── supabase/
│   └── schema.sql          # PostgreSQL tables, RLS policies, trigger & storage setup
├── netlify.toml            # Netlify build settings, API routing & SPA redirects
├── package.json            # Node.js dependencies for Netlify functions
└── README.md               # Step-by-step setup and deployment documentation
```

---

## 🚀 Step-by-Step Deployment Instructions

Follow these 6 steps to deploy your serverless Prompt Library from scratch.

### Step 1: Create a Supabase Project & Run Schema

1. Go to [supabase.com](https://supabase.com) and log in or create a free account.
2. Click **New Project**, choose an organization, enter a project name (e.g. `prompt-library`), set a secure database password, and choose your preferred region.
3. Once the database is provisioned, navigate to the **SQL Editor** from the left navigation bar.
4. Click **New Query**, copy the entire contents of [`supabase/schema.sql`](supabase/schema.sql), paste it into the editor, and click **Run**.
5. This automatically creates:
   - `public.users` table
   - `public.prompts` table
   - `public.bookmarks` table
   - `public.prompts_with_author` view
   - Indexes and Row Level Security (RLS) policies
   - Auto-sync auth trigger (`handle_new_user`)
   - Storage buckets (`thumbnails` and `avatars`) with public read access

### Step 2: Verify Supabase Storage Buckets

1. In your Supabase dashboard, click **Storage** in the left menu.
2. Confirm that two buckets exist:
   - `thumbnails` (Public Bucket = **ON**)
   - `avatars` (Public Bucket = **ON**)
3. If they are not marked public, click the three dots next to each bucket, select **Edit bucket**, and toggle **Public bucket** to enabled.

### Step 3: Initialize Git & Push to GitHub

If you haven't already pushed this repository to GitHub:

```bash
git init
git add .
git commit -m "feat: migrate Prompt Library to Netlify and Supabase serverless stack"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo-name>.git
git push -u origin main
```

### Step 4: Connect GitHub Repository to Netlify

1. Go to [netlify.com](https://netlify.com) and sign in.
2. Click **Add new site** > **Import an existing project**.
3. Select **GitHub** and authorize Netlify.
4. Select your `prompt-library` repository.
5. In the build settings, Netlify will automatically detect `netlify.toml`:
   - **Publish directory:** `public`
   - **Functions directory:** `netlify/functions`
   - **Build command:** (leave blank or `npm run build`)

### Step 5: Configure Environment Variables in Netlify Dashboard

Before clicking deploy, retrieve your API credentials from Supabase:
1. In the Supabase Dashboard, go to **Project Settings** > **API**.
2. Copy the following values:
   - **Project URL**
   - **Project API keys** > `anon` `public` key
   - **Project API keys** > `service_role` `secret` key (keep this secret!)

3. In your Netlify Site Configuration (or during new site setup), navigate to:
   **Site configuration** > **Environment variables** > **Add a variable** (or **Add multiple variables**):

| Variable Name | Value Description | Where to find in Supabase |
| :--- | :--- | :--- |
| `SUPABASE_URL` | Your Supabase project URL (e.g., `https://xyzcompany.supabase.co`) | Settings > API > Project URL |
| `SUPABASE_ANON_KEY` | Supabase Anonymous public key | Settings > API > Project API Keys > `anon` `public` |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase Service Role secret key | Settings > API > Project API Keys > `service_role` `secret` |

### Step 6: Deploy & Verify

1. Click **Deploy site** in Netlify.
2. Netlify will build your static files and deploy your serverless functions in seconds.
3. Open your production URL (e.g., `https://your-site.netlify.app`):
   - Click **Sign Up** to create an account.
   - Click **Upload Prompt** to upload an image and prompt.
   - Confirm thumbnail renders directly from Supabase Storage.
   - Add/remove favorites (bookmarks).
   - Test offline capability by toggling network offline in DevTools.

---

## 🛠️ Local Development

To run the application locally using the Netlify CLI:

### 1. Install Dependencies
```bash
npm install
```

### 2. Configure Local Environment Variables
Create a `.env` file in the root directory:
```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-supabase-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-supabase-service-role-key
```

### 3. Start Local Serverless Dev Server
```bash
npx netlify dev
```
This serves the frontend at `http://localhost:8888` and automatically mounts Netlify Functions at `http://localhost:8888/.netlify/functions/api` with live hot-reloading!

---

## 📡 API Reference

All endpoints are hosted at `/.netlify/functions/api/*` and also aliased via `netlify.toml` at `/api/*`:

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :---: |
| `GET` | `/api/config` | Returns public Supabase URL and Anon Key for dynamic frontend auto-discovery | No |
| `POST` | `/api/signup` | Register new user with username + password | No |
| `POST` | `/api/login` | Login with username + password, returns JWT session | No |
| `GET` | `/api/me` | Get current user's profile | **Yes** |
| `PUT` | `/api/me` | Update current username | **Yes** |
| `PUT` | `/api/me/avatar` | Upload avatar image to Supabase Storage `avatars` bucket | **Yes** |
| `GET` | `/api/prompts` | List/search prompts (query params: `search`, `category`) | Optional |
| `GET` | `/api/prompts/:id` | Get single prompt details with author and bookmark status | Optional |
| `POST` | `/api/prompts` | Create prompt (multipart form with thumbnail binary upload) | **Yes** |
| `PUT` | `/api/prompts/:id` | Update prompt (owner only; optional new thumbnail) | **Yes** |
| `DELETE`| `/api/prompts/:id` | Delete prompt and remove its thumbnail from storage | **Yes** |
| `GET` | `/api/bookmarks` | List all bookmarked prompts for current user | **Yes** |
| `POST` | `/api/bookmarks/:id` | Add prompt to user's favorites | **Yes** |
| `DELETE`| `/api/bookmarks/:id` | Remove prompt from user's favorites | **Yes** |
| `GET` | `/api/thumbnail/:filename`| Redirects (302) to Supabase Storage public URL | No |
| `GET` | `/share/:id` | OpenGraph social preview page that deep-links into SPA | No |

---

## 🔒 Security & Row Level Security (RLS)

- **Supabase Auth JWT Sessions:** All authenticated API requests require an `Authorization: Bearer <access_token>` header, automatically retrieved from `supabase.auth.getSession()` on the frontend.
- **Row Level Security Policies:**
  - `prompts`: Any user can view all prompts. Only the creator (`auth.uid() = user_id`) can update or delete their prompts.
  - `bookmarks`: Users can only view, insert, and delete their own bookmarks (`auth.uid() = user_id`).
  - `users`: Profiles are publicly viewable; users can only modify their own profile data.
- **Storage Policies:**
  - `thumbnails`: Public read access; uploads restricted to authenticated users.
  - `avatars`: Public read access; uploads restricted to authenticated users.

---

## 📱 Progressive Web App (PWA) Features

- **Installable:** Meets PWA install criteria on desktop (Chrome, Edge) and mobile (iOS Safari, Android Chrome).
- **Service Worker:** [`public/service-worker.js`](public/service-worker.js) implements network-first asset caching while cleanly bypassing API and dynamic database calls.
- **Deep-linking:** Prompts can be shared via native device share sheets or clipboard links (`/#prompt-<id>`), automatically opening prompt detail views.
