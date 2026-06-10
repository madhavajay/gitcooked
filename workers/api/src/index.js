const JSON_HEADERS = { 'content-type': 'application/json', 'access-control-allow-origin': '*' };

const json = (data, status = 200, headers = {}) =>
  new Response(JSON.stringify(data), { status, headers: { ...JSON_HEADERS, ...headers } });

const err = (message, status) => json({ error: message }, status);

// ---------- session cookies (HMAC-signed, no server state) ----------

const enc = new TextEncoder();

async function hmacKey(secret) {
  return crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, [
    'sign',
    'verify',
  ]);
}

const hex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');

async function signSession(login, secret, days = 30) {
  const exp = Date.now() + days * 86400_000;
  const payload = `${login}.${exp}`;
  const sig = await crypto.subtle.sign('HMAC', await hmacKey(secret), enc.encode(payload));
  return `${payload}.${hex(sig)}`;
}

async function verifySession(cookie, secret) {
  if (!cookie) return null;
  const m = /(?:^|;\s*)gc_session=([^;]+)/.exec(cookie);
  if (!m) return null;
  const parts = m[1].split('.');
  if (parts.length !== 3) return null;
  const [login, exp, sig] = parts;
  if (Number(exp) < Date.now()) return null;
  const expected = await crypto.subtle.sign('HMAC', await hmacKey(secret), enc.encode(`${login}.${exp}`));
  const got = Uint8Array.from(sig.match(/.{2}/g) ?? [], (h) => parseInt(h, 16));
  if (got.length !== new Uint8Array(expected).length) return null;
  if (!crypto.subtle.timingSafeEqual) {
    // workers runtime exposes timingSafeEqual on crypto.subtle; fallback compare
    return hex(expected) === sig ? login : null;
  }
  return crypto.subtle.timingSafeEqual(got.buffer, expected) ? login : null;
}

// ---------- rank lookup from the static site (KV-cached) ----------

async function globalRank(env, login) {
  const key = `rank:${login.toLowerCase()}`;
  const cached = await env.CACHE.get(key, 'json');
  if (cached) return cached;
  const res = await fetch(`${env.SITE_ORIGIN}/data/search.json`, {
    cf: { cacheTtl: 21600, cacheEverything: true },
  });
  if (!res.ok) return null;
  const index = await res.json();
  const hit = index.find(([l]) => l.toLowerCase() === login.toLowerCase());
  const value = hit ? { login: hit[0], rank: hit[1], contributions: hit[2] } : { missing: true };
  await env.CACHE.put(key, JSON.stringify(value), { expirationTtl: 21600 });
  return value;
}

async function countryRank(env, login, slug) {
  if (!/^[a-z_]+$/.test(slug)) return null;
  const res = await fetch(`${env.SITE_ORIGIN}/data/locations/${slug}.json`, {
    cf: { cacheTtl: 21600, cacheEverything: true },
  });
  if (!res.ok) return null;
  const loc = await res.json();
  const u = loc.modes.commits.find((x) => x.login.toLowerCase() === login.toLowerCase());
  return u ? { login: u.login, rank: u.rank, contributions: u.contributions, title: loc.title } : { missing: true, title: loc.title };
}

// ---------- neon SVG badge ----------

function badgeSvg(label, value) {
  const lw = 10 + label.length * 7.2;
  const vw = 14 + value.length * 7.8;
  const w = Math.round(lw + vw);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="24" role="img" aria-label="${label}: ${value}">
  <defs>
    <linearGradient id="g" x1="0" x2="1">
      <stop offset="0" stop-color="#2ee6ff"/><stop offset=".5" stop-color="#8a5cff"/><stop offset="1" stop-color="#ff3df2"/>
    </linearGradient>
  </defs>
  <rect width="${w}" height="24" rx="5" fill="#06070e"/>
  <rect x="${lw.toFixed(1)}" width="${vw.toFixed(1)}" height="24" rx="5" fill="#10132a"/>
  <rect x="${lw.toFixed(1)}" width="2" height="24" fill="url(#g)"/>
  <rect width="${w}" height="24" rx="5" fill="none" stroke="url(#g)" stroke-opacity=".55"/>
  <text x="${(lw / 2).toFixed(1)}" y="16" text-anchor="middle" font-family="Menlo,monospace" font-size="11" fill="#e8ecff">${label}</text>
  <text x="${(lw + vw / 2).toFixed(1)}" y="16" text-anchor="middle" font-family="Menlo,monospace" font-size="11" font-weight="bold" fill="#2ee6ff">${value}</text>
</svg>`;
}

const sanitize = (s) => String(s ?? '').replace(/[^\w .,#/-]/g, '').slice(0, 40);

// ---------- github oauth ----------

async function githubToken(env, code) {
  const res = await fetch('https://github.com/login/oauth/access_token', {
    method: 'POST',
    headers: { 'content-type': 'application/json', accept: 'application/json' },
    body: JSON.stringify({
      client_id: env.GITHUB_CLIENT_ID,
      client_secret: env.GITHUB_CLIENT_SECRET,
      code,
    }),
  });
  const body = await res.json();
  return body.access_token ?? null;
}

async function githubUser(token) {
  const res = await fetch('https://api.github.com/user', {
    headers: { authorization: `bearer ${token}`, 'user-agent': 'gitcooked', accept: 'application/vnd.github+json' },
  });
  return res.ok ? res.json() : null;
}

async function githubSocials(login) {
  const headers = { 'user-agent': 'gitcooked', accept: 'application/vnd.github+json' };
  const [user, accounts] = await Promise.all([
    fetch(`https://api.github.com/users/${login}`, { headers }).then((r) => (r.ok ? r.json() : null)),
    fetch(`https://api.github.com/users/${login}/social_accounts`, { headers }).then((r) => (r.ok ? r.json() : [])),
  ]);
  const socials = {};
  if (user?.blog) socials.website = user.blog;
  if (user?.twitter_username) socials.twitter = `https://twitter.com/${user.twitter_username}`;
  for (const a of accounts) socials[a.provider] = a.url;
  return socials;
}

// ---------- rate limiting ----------

async function rateLimit(env, request, bucket, limit) {
  const ip = request.headers.get('cf-connecting-ip') ?? 'unknown';
  const day = new Date().toISOString().slice(0, 10);
  const digest = await crypto.subtle.digest('SHA-256', enc.encode(ip));
  const key = `rl:${bucket}:${hex(digest).slice(0, 16)}:${day}`;
  const count = Number((await env.CACHE.get(key)) ?? 0);
  if (count >= limit) return false;
  await env.CACHE.put(key, String(count + 1), { expirationTtl: 86400 });
  return true;
}

// ---------- router ----------

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;
    try {
      if (request.method === 'OPTIONS') {
        return new Response(null, {
          headers: {
            'access-control-allow-origin': '*',
            'access-control-allow-methods': 'GET,POST,PUT,DELETE',
            'access-control-allow-headers': 'content-type',
          },
        });
      }

      if (path === '/api/health') return json({ ok: true });

      // --- badges ---
      let m;
      if ((m = /^\/badge\/([\w-]+)\.svg$/.exec(path))) {
        const login = m[1];
        const scope = url.searchParams.get('scope') ?? 'global';
        const data = scope === 'global' ? await globalRank(env, login) : await countryRank(env, login, scope);
        const label = scope === 'global' ? 'gitcooked global' : `gitcooked ${sanitize(data?.title ?? scope)}`;
        const value = data && !data.missing ? `#${data.rank}` : 'unranked';
        return new Response(badgeSvg(sanitize(label), sanitize(value)), {
          headers: {
            'content-type': 'image/svg+xml',
            'cache-control': 'public, max-age=21600',
            'access-control-allow-origin': '*',
          },
        });
      }
      if ((m = /^\/api\/shield\/([\w-]+)$/.exec(path))) {
        const data = await globalRank(env, m[1]);
        return json({
          schemaVersion: 1,
          label: 'gitcooked',
          message: data && !data.missing ? `#${data.rank} global` : 'unranked',
          color: data && !data.missing ? 'blueviolet' : 'lightgrey',
        });
      }

      // --- index requests ---
      if (path === '/api/index-request' && request.method === 'POST') {
        if (!(await rateLimit(env, request, 'idx', 10))) return err('rate limited — try tomorrow', 429);
        const body = await request.json().catch(() => ({}));
        const login = String(body.login ?? '').trim();
        const location = String(body.location ?? '').trim().slice(0, 120);
        if (!/^[\w-]{1,39}$/.test(login)) return err('invalid login', 400);
        await env.DB.prepare(
          'INSERT INTO index_requests (login, location, created_at) VALUES (?1, ?2, ?3) ON CONFLICT (login) DO NOTHING'
        )
          .bind(login, location, new Date().toISOString())
          .run();
        return json({ ok: true, queued: login });
      }
      if (path === '/api/index-requests' && request.method === 'GET') {
        const { results } = await env.DB.prepare(
          "SELECT * FROM index_requests WHERE status = 'pending' ORDER BY created_at LIMIT 200"
        ).all();
        return json(results);
      }

      // --- auth ---
      if (path === '/api/auth/login') {
        const redirect = `${url.origin}/api/auth/callback`;
        const state = crypto.randomUUID();
        const target = new URL('https://github.com/login/oauth/authorize');
        target.searchParams.set('client_id', env.GITHUB_CLIENT_ID);
        target.searchParams.set('redirect_uri', redirect);
        target.searchParams.set('state', state);
        return new Response(null, {
          status: 302,
          headers: {
            location: target.toString(),
            'set-cookie': `gc_state=${state}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=600`,
          },
        });
      }
      if (path === '/api/auth/callback') {
        const state = url.searchParams.get('state');
        const cookieState = /(?:^|;\s*)gc_state=([^;]+)/.exec(request.headers.get('cookie') ?? '')?.[1];
        if (!state || state !== cookieState) return err('bad oauth state', 400);
        const token = await githubToken(env, url.searchParams.get('code'));
        if (!token) return err('oauth exchange failed', 400);
        const user = await githubUser(token);
        if (!user) return err('github user fetch failed', 400);
        const socials = await githubSocials(user.login);
        await env.DB.prepare(
          `INSERT INTO users (login, github_id, name, avatar_url, claimed_at, socials)
           VALUES (?1, ?2, ?3, ?4, ?5, ?6)
           ON CONFLICT (login) DO UPDATE SET name = ?3, avatar_url = ?4`
        )
          .bind(user.login, user.id, user.name ?? '', user.avatar_url ?? '', new Date().toISOString(), JSON.stringify(socials))
          .run();
        const session = await signSession(user.login, env.SESSION_SECRET);
        return new Response(null, {
          status: 302,
          headers: {
            location: `${env.SITE_ORIGIN}/u/${user.login}?claimed=1`,
            'set-cookie': `gc_session=${session}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${30 * 86400}`,
          },
        });
      }
      if (path === '/api/auth/logout') {
        return new Response(null, {
          status: 302,
          headers: {
            location: env.SITE_ORIGIN,
            'set-cookie': 'gc_session=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0',
          },
        });
      }

      const sessionLogin = await verifySession(request.headers.get('cookie'), env.SESSION_SECRET);

      if (path === '/api/me') {
        if (!sessionLogin) return err('not signed in', 401);
        const me = await env.DB.prepare('SELECT * FROM users WHERE login = ?1').bind(sessionLogin).first();
        return json({ ...me, socials: JSON.parse(me?.socials ?? '{}') });
      }

      // --- profiles ---
      if ((m = /^\/api\/profile\/([\w-]+)$/.exec(path)) && request.method === 'GET') {
        const login = m[1];
        const user = await env.DB.prepare('SELECT login, name, avatar_url, claimed_at, socials FROM users WHERE login = ?1')
          .bind(login)
          .first();
        const { results: vouchedBy } = await env.DB.prepare(
          'SELECT voucher, note, created_at FROM vouches WHERE vouchee = ?1 ORDER BY created_at'
        )
          .bind(login)
          .all();
        return json({
          login,
          claimed: !!user,
          name: user?.name,
          socials: JSON.parse(user?.socials ?? '{}'),
          vouchedBy,
        });
      }
      if (path === '/api/profile' && request.method === 'PUT') {
        if (!sessionLogin) return err('not signed in', 401);
        const body = await request.json().catch(() => ({}));
        const socials = {};
        for (const [k, v] of Object.entries(body.socials ?? {})) {
          if (/^[a-z_]{2,20}$/.test(k) && typeof v === 'string' && /^https?:\/\//.test(v) && v.length < 200) {
            socials[k] = v;
          }
        }
        await env.DB.prepare('UPDATE users SET socials = ?1 WHERE login = ?2')
          .bind(JSON.stringify(socials), sessionLogin)
          .run();
        return json({ ok: true, socials });
      }

      // --- vouches ---
      if (path === '/api/vouch' && request.method === 'POST') {
        if (!sessionLogin) return err('not signed in', 401);
        const body = await request.json().catch(() => ({}));
        const vouchee = String(body.vouchee ?? '').trim();
        if (!/^[\w-]{1,39}$/.test(vouchee)) return err('invalid vouchee', 400);
        if (vouchee.toLowerCase() === sessionLogin.toLowerCase()) return err('cannot vouch for yourself', 400);
        const me = await globalRank(env, sessionLogin);
        if (!me || me.missing) return err('only ranked users can vouch', 403);
        const { cnt } = await env.DB.prepare('SELECT COUNT(*) AS cnt FROM vouches WHERE voucher = ?1')
          .bind(sessionLogin)
          .first();
        if (cnt >= 20) return err('vouch limit reached (20)', 403);
        await env.DB.prepare(
          'INSERT INTO vouches (voucher, vouchee, note, created_at) VALUES (?1, ?2, ?3, ?4) ON CONFLICT (voucher, vouchee) DO NOTHING'
        )
          .bind(sessionLogin, vouchee, String(body.note ?? '').slice(0, 280), new Date().toISOString())
          .run();
        return json({ ok: true });
      }
      if ((m = /^\/api\/vouch\/([\w-]+)$/.exec(path)) && request.method === 'DELETE') {
        if (!sessionLogin) return err('not signed in', 401);
        await env.DB.prepare('DELETE FROM vouches WHERE voucher = ?1 AND vouchee = ?2').bind(sessionLogin, m[1]).run();
        return json({ ok: true });
      }
      if (path === '/api/vouches/graph') {
        const { results } = await env.DB.prepare('SELECT voucher, vouchee FROM vouches').all();
        return json(results);
      }

      return err('not found', 404);
    } catch (e) {
      console.log(JSON.stringify({ level: 'error', path, message: e.message }));
      return err('internal error', 500);
    }
  },
};
