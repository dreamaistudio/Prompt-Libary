/**
 * Prompt Library - Netlify Serverless API Function
 * 
 * Provides complete REST API endpoints backed by Supabase PostgreSQL,
 * Supabase Auth, and Supabase Storage.
 */

const { createClient } = require('@supabase/supabase-js');
const Busboy = require('busboy');
const bcrypt = require('bcryptjs');
const crypto = require('crypto');

// ─── Environment Variables ───
const SUPABASE_URL = process.env.SUPABASE_URL || '';
const SUPABASE_SERVICE_ROLE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY || '';
const SUPABASE_ANON_KEY = process.env.SUPABASE_ANON_KEY || '';

// ─── Supabase Client Instances ───
let supabaseAdmin = null;
let supabaseAnon = null;

function getSupabaseClients() {
  if (!SUPABASE_URL || !SUPABASE_SERVICE_ROLE_KEY) {
    return { supabaseAdmin: null, supabaseAnon: null, error: 'SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured in Netlify environment variables.' };
  }
  if (!supabaseAdmin) {
    supabaseAdmin = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, {
      auth: { persistSession: false, autoRefreshToken: false }
    });
  }
  if (!supabaseAnon && SUPABASE_ANON_KEY) {
    supabaseAnon = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
      auth: { persistSession: false, autoRefreshToken: false }
    });
  }
  return { supabaseAdmin, supabaseAnon, error: null };
}

// ─── Standard CORS Headers ───
const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With',
  'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
};

// ─── Response Helpers ───
function jsonResponse(statusCode, data, extraHeaders = {}) {
  return {
    statusCode,
    headers: {
      'Content-Type': 'application/json',
      ...CORS_HEADERS,
      ...extraHeaders,
    },
    body: JSON.stringify(data),
  };
}

function redirectResponse(url) {
  return {
    statusCode: 302,
    headers: {
      Location: url,
      ...CORS_HEADERS,
    },
    body: '',
  };
}

// ─── Request Parsers ───
function parseBody(event) {
  if (!event.body) return {};
  try {
    const raw = event.isBase64Encoded
      ? Buffer.from(event.body, 'base64').toString('utf8')
      : event.body;
    return typeof raw === 'string' ? JSON.parse(raw) : raw;
  } catch (err) {
    return {};
  }
}

function parseMultipart(event) {
  return new Promise((resolve, reject) => {
    const contentType = event.headers['content-type'] || event.headers['Content-Type'] || '';
    if (!contentType.toLowerCase().includes('multipart/form-data')) {
      return resolve({ fields: parseBody(event), files: {} });
    }

    const busboy = Busboy({
      headers: { 'content-type': contentType },
      limits: {
        fileSize: 15 * 1024 * 1024, // 15MB max file size
      },
    });

    const fields = {};
    const files = {};

    busboy.on('field', (fieldname, val) => {
      fields[fieldname] = val;
    });

    busboy.on('file', (fieldname, fileStream, info) => {
      const { filename, encoding, mimeType } = info;
      const chunks = [];
      fileStream.on('data', (data) => chunks.push(data));
      fileStream.on('end', () => {
        if (filename) {
          files[fieldname] = {
            filename,
            encoding,
            mimeType,
            buffer: Buffer.concat(chunks),
          };
        }
      });
    });

    busboy.on('finish', () => resolve({ fields, files }));
    busboy.on('error', (err) => reject(err));

    const bodyBuffer = event.isBase64Encoded
      ? Buffer.from(event.body || '', 'base64')
      : Buffer.from(event.body || '', 'binary');

    busboy.end(bodyBuffer);
  });
}

async function getRequestData(event) {
  const contentType = (event.headers['content-type'] || event.headers['Content-Type'] || '').toLowerCase();
  if (contentType.includes('multipart/form-data')) {
    return await parseMultipart(event);
  }
  return { fields: parseBody(event), files: {} };
}

// ─── Authentication Helper ───
async function getAuthenticatedUser(event, adminClient) {
  const authHeader = event.headers['authorization'] || event.headers['Authorization'] || '';
  if (!authHeader) return null;
  const token = authHeader.replace(/^Bearer\s+/i, '').trim();
  if (!token) return null;

  try {
    const { data: { user }, error } = await adminClient.auth.getUser(token);
    if (error || !user) return null;
    return { user, token };
  } catch (err) {
    console.error('Token verification error:', err);
    return null;
  }
}

// ─── Normalizer for Route Paths ───
function normalizePath(rawPath) {
  let p = rawPath || '';
  p = p.split('?')[0];
  p = p.replace(/^\/\.netlify\/functions\/api/, '');
  p = p.replace(/^\/api/, '');
  if (p.length > 1 && p.endsWith('/')) {
    p = p.slice(0, -1);
  }
  return p || '/';
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ==============================================================================
// MAIN HANDLER
// ==============================================================================
exports.handler = async (event, context) => {
  // Handle CORS preflight
  if (event.httpMethod === 'OPTIONS') {
    return {
      statusCode: 204,
      headers: CORS_HEADERS,
      body: '',
    };
  }

  const { supabaseAdmin, supabaseAnon, error: clientError } = getSupabaseClients();
  const path = normalizePath(event.path);
  const method = event.httpMethod;

  // ----------------------------------------------------------------------------
  // Public Configuration Endpoint (/config)
  // Allows the frontend to auto-discover Supabase URL and Anon Key dynamically
  // ----------------------------------------------------------------------------
  if (method === 'GET' && path === '/config') {
    return jsonResponse(200, {
      supabaseUrl: SUPABASE_URL,
      supabaseAnonKey: SUPABASE_ANON_KEY,
    });
  }

  // Ensure Supabase is configured for all other database operations
  if (clientError || !supabaseAdmin) {
    return jsonResponse(500, {
      detail: clientError || 'Supabase credentials missing in environment variables (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY).',
    });
  }

  try {
    // ==========================================================================
    // AUTHENTICATION ROUTES
    // ==========================================================================

    // POST /api/signup — Register with username + password (+ optional email)
    if (method === 'POST' && path === '/signup') {
      const body = parseBody(event);
      const username = (body.username || '').trim();
      const password = body.password || '';
      const email = (body.email || '').trim();

      if (!username || !password) {
        return jsonResponse(400, { detail: 'Username and password required' });
      }
      if (password.length < 4) {
        return jsonResponse(400, { detail: 'Password must be at least 4 characters' });
      }

      // Check username availability
      const { data: existingUser } = await supabaseAdmin
        .from('users')
        .select('id')
        .ilike('username', username)
        .maybeSingle();

      if (existingUser) {
        return jsonResponse(409, { detail: 'Username already taken' });
      }

      // Synthesize email if none provided (Supabase Auth requires an email format)
      const sanitizedUsername = username.toLowerCase().replace(/[^a-z0-9_]/g, '');
      const authEmail = email || `${sanitizedUsername}@promptlib.local`;

      // Create user in Supabase Auth via Admin API
      const { data: authData, error: authError } = await supabaseAdmin.auth.admin.createUser({
        email: authEmail,
        password: password,
        email_confirm: true,
        user_metadata: { username },
      });

      if (authError) {
        return jsonResponse(400, { detail: authError.message });
      }

      const userId = authData.user.id;
      const passwordHash = bcrypt.hashSync(password, 10);

      // Create or update public profile in public.users
      const { error: dbError } = await supabaseAdmin
        .from('users')
        .upsert({
          id: userId,
          username: username,
          email: authEmail,
          password_hash: passwordHash,
          avatar: '',
          created_at: new Date().toISOString(),
        });

      if (dbError) {
        console.error('Error inserting into public.users:', dbError);
      }

      // Authenticate to generate JWT session
      const anonClient = supabaseAnon || supabaseAdmin;
      const { data: signInData, error: signInError } = await anonClient.auth.signInWithPassword({
        email: authEmail,
        password: password,
      });

      if (signInError || !signInData.session) {
        return jsonResponse(200, {
          user_id: userId,
          username: username,
          message: 'Account created successfully. Please log in.',
        });
      }

      return jsonResponse(200, {
        token: signInData.session.access_token,
        session: signInData.session,
        user_id: userId,
        username: username,
      });
    }

    // POST /api/login — Login with username + password, return JWT
    if (method === 'POST' && path === '/login') {
      const body = parseBody(event);
      const username = (body.username || '').trim();
      const password = body.password || '';

      if (!username || !password) {
        return jsonResponse(400, { detail: 'Username and password required' });
      }

      // Find user profile by username
      const { data: userProfile } = await supabaseAdmin
        .from('users')
        .select('*')
        .ilike('username', username)
        .maybeSingle();

      if (!userProfile) {
        return jsonResponse(401, { detail: 'Invalid username or password' });
      }

      const anonClient = supabaseAnon || supabaseAdmin;
      const { data: signInData, error: signInError } = await anonClient.auth.signInWithPassword({
        email: userProfile.email,
        password: password,
      });

      if (signInError || !signInData.session) {
        return jsonResponse(401, { detail: 'Invalid username or password' });
      }

      return jsonResponse(200, {
        token: signInData.session.access_token,
        session: signInData.session,
        user_id: userProfile.id,
        username: userProfile.username,
      });
    }

    // ==========================================================================
    // USER PROFILE ROUTES
    // ==========================================================================

    // GET /api/me — Get current user profile
    if (method === 'GET' && path === '/me') {
      const auth = await getAuthenticatedUser(event, supabaseAdmin);
      if (!auth) return jsonResponse(401, { detail: 'Authentication required' });

      const { data: user } = await supabaseAdmin
        .from('users')
        .select('id, username, avatar, email, created_at')
        .eq('id', auth.user.id)
        .maybeSingle();

      if (!user) {
        return jsonResponse(404, { detail: 'User not found' });
      }

      return jsonResponse(200, {
        user_id: user.id,
        username: user.username,
        avatar: user.avatar || '',
        email: user.email || '',
        created_at: user.created_at,
      });
    }

    // PUT /api/me — Update username
    if (method === 'PUT' && path === '/me') {
      const auth = await getAuthenticatedUser(event, supabaseAdmin);
      if (!auth) return jsonResponse(401, { detail: 'Authentication required' });

      const body = parseBody(event);
      const newName = (body.username || '').trim();
      if (!newName) {
        return jsonResponse(400, { detail: 'Username required' });
      }

      // Check if new username is already taken by another user
      const { data: existing } = await supabaseAdmin
        .from('users')
        .select('id')
        .ilike('username', newName)
        .neq('id', auth.user.id)
        .maybeSingle();

      if (existing) {
        return jsonResponse(409, { detail: 'Username already taken' });
      }

      const { error: updateError } = await supabaseAdmin
        .from('users')
        .update({ username: newName })
        .eq('id', auth.user.id);

      if (updateError) {
        return jsonResponse(500, { detail: updateError.message });
      }

      // Sync user_metadata in Supabase Auth
      await supabaseAdmin.auth.admin.updateUserById(auth.user.id, {
        user_metadata: { username: newName },
      });

      return jsonResponse(200, { username: newName });
    }

    // PUT /api/me/avatar — Upload avatar image to Supabase Storage
    if ((method === 'PUT' || method === 'POST') && path === '/me/avatar') {
      const auth = await getAuthenticatedUser(event, supabaseAdmin);
      if (!auth) return jsonResponse(401, { detail: 'Authentication required' });

      const { files } = await getRequestData(event);
      const avatarFile = files.avatar || Object.values(files)[0];

      if (!avatarFile || !avatarFile.buffer) {
        return jsonResponse(400, { detail: 'No avatar image file uploaded' });
      }

      const ext = (avatarFile.filename.split('.').pop() || 'png').toLowerCase();
      const allowedExts = ['png', 'jpg', 'jpeg', 'gif', 'webp'];
      if (!allowedExts.includes(ext)) {
        return jsonResponse(400, { detail: 'Invalid image format. Supported formats: PNG, JPG, GIF, WebP.' });
      }

      const filename = `avatar_${auth.user.id}_${crypto.randomUUID().slice(0, 8)}.${ext}`;
      const contentType = avatarFile.mimeType || `image/${ext === 'jpg' ? 'jpeg' : ext}`;

      const { error: uploadError } = await supabaseAdmin
        .storage
        .from('avatars')
        .upload(filename, avatarFile.buffer, {
          contentType,
          upsert: true,
        });

      if (uploadError) {
        return jsonResponse(500, { detail: 'Avatar storage upload failed: ' + uploadError.message });
      }

      const { data: publicUrlData } = supabaseAdmin
        .storage
        .from('avatars')
        .getPublicUrl(filename);

      const avatarUrl = publicUrlData.publicUrl;

      await supabaseAdmin
        .from('users')
        .update({ avatar: avatarUrl })
        .eq('id', auth.user.id);

      return jsonResponse(200, { avatar: avatarUrl });
    }

    // ==========================================================================
    // PROMPT ROUTES
    // ==========================================================================

    // GET /api/prompts — List/Search prompts
    if (method === 'GET' && path === '/prompts') {
      const auth = await getAuthenticatedUser(event, supabaseAdmin);
      const currentUserId = auth ? auth.user.id : null;

      const params = event.queryStringParameters || {};
      const search = (params.search || '').trim();
      const category = (params.category || 'All').trim();

      let query = supabaseAdmin
        .from('prompts_with_author')
        .select('*')
        .order('created_at', { ascending: false });

      if (category && category !== 'All') {
        query = query.eq('category', category);
      }

      if (search) {
        query = query.or(`title.ilike.%${search}%,prompt.ilike.%${search}%,tags.ilike.%${search}%`);
      }

      const { data: prompts, error: listError } = await query;
      if (listError) {
        return jsonResponse(500, { detail: listError.message });
      }

      // Fetch bookmark status for current user if authenticated
      let bookmarkedIds = new Set();
      if (currentUserId) {
        const { data: bookmarks } = await supabaseAdmin
          .from('bookmarks')
          .select('prompt_id')
          .eq('user_id', currentUserId);

        if (bookmarks) {
          bookmarkedIds = new Set(bookmarks.map((b) => String(b.prompt_id)));
        }
      }

      const result = (prompts || []).map((p) => ({
        ...p,
        bookmarked: bookmarkedIds.has(String(p.id)),
      }));

      return jsonResponse(200, result);
    }

    // POST /api/prompts — Create prompt (multipart with thumbnail upload)
    if (method === 'POST' && path === '/prompts') {
      const auth = await getAuthenticatedUser(event, supabaseAdmin);
      if (!auth) return jsonResponse(401, { detail: 'Authentication required' });

      const { fields, files } = await getRequestData(event);
      const title = (fields.title || '').trim();
      const promptText = (fields.prompt || '').trim();
      const category = (fields.category || 'Image').trim();
      const model = (fields.model || '').trim();
      const tags = (fields.tags || '').trim();
      const instructions = (fields.instructions || '').trim();

      if (!title || !promptText) {
        return jsonResponse(400, { detail: 'Title and prompt text are required' });
      }

      let thumbnailUrl = '';
      if (files.thumbnail && files.thumbnail.buffer) {
        const ext = (files.thumbnail.filename.split('.').pop() || 'png').toLowerCase();
        const allowedExts = ['png', 'jpg', 'jpeg', 'gif', 'webp'];
        if (!allowedExts.includes(ext)) {
          return jsonResponse(400, { detail: 'Invalid thumbnail image type' });
        }

        const thumbFilename = `thumb_${crypto.randomUUID()}.${ext}`;
        const contentType = files.thumbnail.mimeType || `image/${ext === 'jpg' ? 'jpeg' : ext}`;

        const { error: uploadError } = await supabaseAdmin
          .storage
          .from('thumbnails')
          .upload(thumbFilename, files.thumbnail.buffer, {
            contentType,
            upsert: true,
          });

        if (uploadError) {
          return jsonResponse(500, { detail: 'Thumbnail upload failed: ' + uploadError.message });
        }

        const { data: publicUrlData } = supabaseAdmin
          .storage
          .from('thumbnails')
          .getPublicUrl(thumbFilename);

        thumbnailUrl = publicUrlData.publicUrl;
      }

      const { data: newPrompt, error: insertError } = await supabaseAdmin
        .from('prompts')
        .insert({
          user_id: auth.user.id,
          title,
          prompt: promptText,
          category,
          model,
          tags,
          instructions,
          thumbnail: thumbnailUrl,
          reference_images: '',
        })
        .select('id')
        .single();

      if (insertError) {
        return jsonResponse(500, { detail: insertError.message });
      }

      return jsonResponse(200, { id: newPrompt.id, message: 'Prompt created' });
    }

    // Match /prompts/:id
    const promptIdMatch = path.match(/^\/prompts\/([^\/]+)$/);
    if (promptIdMatch) {
      const promptId = promptIdMatch[1];

      // GET /api/prompts/:id — Get single prompt
      if (method === 'GET') {
        const auth = await getAuthenticatedUser(event, supabaseAdmin);
        const currentUserId = auth ? auth.user.id : null;

        const { data: prompt, error } = await supabaseAdmin
          .from('prompts_with_author')
          .select('*')
          .eq('id', promptId)
          .maybeSingle();

        if (error || !prompt) {
          return jsonResponse(404, { detail: 'Prompt not found' });
        }

        let bookmarked = false;
        if (currentUserId) {
          const { data: bm } = await supabaseAdmin
            .from('bookmarks')
            .select('id')
            .eq('user_id', currentUserId)
            .eq('prompt_id', promptId)
            .maybeSingle();
          bookmarked = !!bm;
        }

        return jsonResponse(200, {
          ...prompt,
          bookmarked,
        });
      }

      // PUT /api/prompts/:id — Update prompt
      if (method === 'PUT') {
        const auth = await getAuthenticatedUser(event, supabaseAdmin);
        if (!auth) return jsonResponse(401, { detail: 'Authentication required' });

        const { data: existing } = await supabaseAdmin
          .from('prompts')
          .select('*')
          .eq('id', promptId)
          .maybeSingle();

        if (!existing) {
          return jsonResponse(404, { detail: 'Prompt not found' });
        }
        if (existing.user_id !== auth.user.id) {
          return jsonResponse(403, { detail: 'Not your prompt' });
        }

        const { fields, files } = await getRequestData(event);
        const title = fields.title !== undefined ? fields.title.trim() : existing.title;
        const promptText = fields.prompt !== undefined ? fields.prompt.trim() : existing.prompt;
        const category = fields.category !== undefined ? fields.category.trim() : existing.category;
        const model = fields.model !== undefined ? fields.model.trim() : existing.model;
        const tags = fields.tags !== undefined ? fields.tags.trim() : existing.tags;
        const instructions = fields.instructions !== undefined ? fields.instructions.trim() : existing.instructions;

        let thumbnailUrl = existing.thumbnail;
        if (files.thumbnail && files.thumbnail.buffer) {
          const ext = (files.thumbnail.filename.split('.').pop() || 'png').toLowerCase();
          const allowedExts = ['png', 'jpg', 'jpeg', 'gif', 'webp'];
          if (!allowedExts.includes(ext)) {
            return jsonResponse(400, { detail: 'Invalid thumbnail image type' });
          }

          const thumbFilename = `thumb_${crypto.randomUUID()}.${ext}`;
          const contentType = files.thumbnail.mimeType || `image/${ext === 'jpg' ? 'jpeg' : ext}`;

          const { error: uploadError } = await supabaseAdmin
            .storage
            .from('thumbnails')
            .upload(thumbFilename, files.thumbnail.buffer, {
              contentType,
              upsert: true,
            });

          if (uploadError) {
            return jsonResponse(500, { detail: 'Thumbnail upload failed: ' + uploadError.message });
          }

          const { data: publicUrlData } = supabaseAdmin
            .storage
            .from('thumbnails')
            .getPublicUrl(thumbFilename);

          thumbnailUrl = publicUrlData.publicUrl;

          // Attempt removal of old thumbnail from storage
          if (existing.thumbnail) {
            try {
              const oldFile = existing.thumbnail.split('/').pop();
              if (oldFile) await supabaseAdmin.storage.from('thumbnails').remove([oldFile]);
            } catch (ignore) {}
          }
        }

        const { error: updateError } = await supabaseAdmin
          .from('prompts')
          .update({
            title,
            prompt: promptText,
            category,
            model,
            tags,
            instructions,
            thumbnail: thumbnailUrl,
          })
          .eq('id', promptId);

        if (updateError) {
          return jsonResponse(500, { detail: updateError.message });
        }

        return jsonResponse(200, { message: 'Prompt updated' });
      }

      // DELETE /api/prompts/:id — Delete prompt
      if (method === 'DELETE') {
        const auth = await getAuthenticatedUser(event, supabaseAdmin);
        if (!auth) return jsonResponse(401, { detail: 'Authentication required' });

        const { data: existing } = await supabaseAdmin
          .from('prompts')
          .select('*')
          .eq('id', promptId)
          .maybeSingle();

        if (!existing) {
          return jsonResponse(404, { detail: 'Prompt not found' });
        }
        if (existing.user_id !== auth.user.id) {
          return jsonResponse(403, { detail: 'Not your prompt' });
        }

        // Clean up thumbnail in Supabase Storage
        if (existing.thumbnail) {
          try {
            const oldFile = existing.thumbnail.split('/').pop();
            if (oldFile) await supabaseAdmin.storage.from('thumbnails').remove([oldFile]);
          } catch (ignore) {}
        }

        const { error: deleteError } = await supabaseAdmin
          .from('prompts')
          .delete()
          .eq('id', promptId);

        if (deleteError) {
          return jsonResponse(500, { detail: deleteError.message });
        }

        return jsonResponse(200, { message: 'Prompt deleted' });
      }
    }

    // ==========================================================================
    // BOOKMARK ROUTES
    // ==========================================================================

    // GET /api/bookmarks — List bookmarks for current user
    if (method === 'GET' && path === '/bookmarks') {
      const auth = await getAuthenticatedUser(event, supabaseAdmin);
      if (!auth) return jsonResponse(401, { detail: 'Authentication required' });

      const { data: bms, error: bmError } = await supabaseAdmin
        .from('bookmarks')
        .select('prompt_id')
        .eq('user_id', auth.user.id)
        .order('id', { ascending: false });

      if (bmError) return jsonResponse(500, { detail: bmError.message });
      if (!bms || bms.length === 0) return jsonResponse(200, []);

      const promptIds = bms.map((b) => b.prompt_id);
      const { data: prompts, error: pError } = await supabaseAdmin
        .from('prompts_with_author')
        .select('*')
        .in('id', promptIds);

      if (pError) return jsonResponse(500, { detail: pError.message });

      const promptMap = new Map((prompts || []).map((p) => [String(p.id), p]));
      const result = [];
      for (const b of bms) {
        const p = promptMap.get(String(b.prompt_id));
        if (p) {
          result.push({ ...p, bookmarked: true });
        }
      }

      return jsonResponse(200, result);
    }

    // Match /bookmarks/:id
    const bookmarkIdMatch = path.match(/^\/bookmarks\/([^\/]+)$/);
    if (bookmarkIdMatch) {
      const targetPromptId = bookmarkIdMatch[1];

      // POST /api/bookmarks/:id — Add bookmark
      if (method === 'POST') {
        const auth = await getAuthenticatedUser(event, supabaseAdmin);
        if (!auth) return jsonResponse(401, { detail: 'Authentication required' });

        const { error: insertError } = await supabaseAdmin
          .from('bookmarks')
          .upsert(
            { user_id: auth.user.id, prompt_id: targetPromptId },
            { onConflict: 'user_id,prompt_id' }
          );

        if (insertError) {
          return jsonResponse(500, { detail: insertError.message });
        }

        return jsonResponse(200, { message: 'Bookmarked' });
      }

      // DELETE /api/bookmarks/:id — Remove bookmark
      if (method === 'DELETE') {
        const auth = await getAuthenticatedUser(event, supabaseAdmin);
        if (!auth) return jsonResponse(401, { detail: 'Authentication required' });

        const { error: deleteError } = await supabaseAdmin
          .from('bookmarks')
          .delete()
          .eq('user_id', auth.user.id)
          .eq('prompt_id', targetPromptId);

        if (deleteError) {
          return jsonResponse(500, { detail: deleteError.message });
        }

        return jsonResponse(200, { message: 'Removed' });
      }
    }

    // ==========================================================================
    // THUMBNAIL STORAGE REDIRECT ROUTE
    // GET /api/thumbnail/:filename — Redirect to Supabase Storage public URL
    // ==========================================================================
    const thumbMatch = path.match(/^\/thumbnail\/(.+)$/);
    if (method === 'GET' && thumbMatch) {
      const filename = thumbMatch[1];
      const { data } = supabaseAdmin.storage.from('thumbnails').getPublicUrl(filename);
      const publicUrl = data?.publicUrl || `${SUPABASE_URL}/storage/v1/object/public/thumbnails/${filename}`;
      return redirectResponse(publicUrl);
    }

    // ==========================================================================
    // SOCIAL SHARE PREVIEW ROUTE
    // GET /share/:id — Returns OpenGraph meta preview with SPA deep-link
    // ==========================================================================
    const shareMatch = path.match(/^\/share\/([^\/]+)$/);
    if (method === 'GET' && shareMatch) {
      const shareId = shareMatch[1];
      const { data: p } = await supabaseAdmin
        .from('prompts_with_author')
        .select('*')
        .eq('id', shareId)
        .maybeSingle();

      if (!p) {
        return jsonResponse(404, { detail: 'Prompt not found' });
      }

      const ogImage = p.thumbnail
        ? `<meta property="og:image" content="${escapeHtml(p.thumbnail)}"><meta name="twitter:image" content="${escapeHtml(p.thumbnail)}">`
        : '';

      const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${escapeHtml(p.title)} — Prompt Library</title>
  <meta name="description" content="${escapeHtml(p.prompt.slice(0, 160))}">
  <meta property="og:title" content="${escapeHtml(p.title)}">
  <meta property="og:description" content="${escapeHtml(p.prompt.slice(0, 200))}">
  <meta property="og:type" content="article">
  ${ogImage}
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="${escapeHtml(p.title)}">
  <meta name="twitter:description" content="${escapeHtml(p.prompt.slice(0, 200))}">
  <script>
    window.location.replace('/#prompt-${p.id}');
  </script>
</head>
<body style="background:#0a0e1a;color:#f1f5f9;font-family:system-ui,-apple-system,sans-serif;padding:40px;text-align:center;">
  <h2>${escapeHtml(p.title)}</h2>
  <p style="color:#94a3b8;max-width:600px;margin:20px auto;">${escapeHtml(p.prompt)}</p>
  <p><a href="/#prompt-${p.id}" style="color:#00e5ff;text-decoration:none;font-weight:bold;">Open in Prompt Library →</a></p>
</body>
</html>`;

      return {
        statusCode: 200,
        headers: {
          'Content-Type': 'text/html; charset=utf-8',
          ...CORS_HEADERS,
        },
        body: html,
      };
    }

    // 404 for unhandled routes
    return jsonResponse(404, {
      detail: `Endpoint not found: ${method} ${path}`,
    });

  } catch (err) {
    console.error('Unhandled serverless exception:', err);
    return jsonResponse(500, {
      detail: 'Internal server error: ' + (err.message || String(err)),
    });
  }
};
