import { readFileSync, mkdirSync } from 'node:fs';
import sharp from 'sharp';

const index = JSON.parse(readFileSync('src/data/index.json', 'utf8'));
const global = JSON.parse(readFileSync('src/data/global.json', 'utf8'));

const esc = (s) =>
  String(s ?? '')
    .replace(/[^\x20-\x7E -ɏḀ-ỿ]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

const card = ({ title, subtitle, rows, footer }) => `
<svg width="1200" height="630" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#2ee6ff"/><stop offset=".5" stop-color="#8a5cff"/><stop offset="1" stop-color="#ff3df2"/>
    </linearGradient>
    <radialGradient id="bg1" cx="80%" cy="0%" r="70%">
      <stop offset="0" stop-color="#2ee6ff" stop-opacity=".14"/><stop offset="1" stop-color="#2ee6ff" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="bg2" cx="10%" cy="100%" r="70%">
      <stop offset="0" stop-color="#ff3df2" stop-opacity=".12"/><stop offset="1" stop-color="#ff3df2" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="1200" height="630" fill="#06070e"/>
  <rect width="1200" height="630" fill="url(#bg1)"/>
  <rect width="1200" height="630" fill="url(#bg2)"/>
  <text x="80" y="120" font-family="Menlo, monospace" font-size="34" fill="url(#g)" font-weight="bold">gitcooked</text>
  <text x="80" y="220" font-family="Helvetica, Arial, sans-serif" font-size="72" font-weight="bold" fill="#e8ecff">${esc(title)}</text>
  <text x="80" y="275" font-family="Helvetica, Arial, sans-serif" font-size="30" fill="#7b84ad">${esc(subtitle)}</text>
  ${rows
    .map(
      (r, i) => `
  <text x="80" y="${365 + i * 58}" font-family="Menlo, monospace" font-size="34" fill="#2ee6ff">#${r.rank}</text>
  <text x="170" y="${365 + i * 58}" font-family="Helvetica, Arial, sans-serif" font-size="34" fill="#e8ecff">${esc(r.label)}</text>
  <text x="1120" y="${365 + i * 58}" text-anchor="end" font-family="Menlo, monospace" font-size="34" fill="#ff3df2">${esc(r.value)}</text>`
    )
    .join('')}
  <text x="80" y="585" font-family="Menlo, monospace" font-size="24" fill="#7b84ad">${esc(footer)}</text>
</svg>`;

const png = (svg, path) => sharp(Buffer.from(svg)).jpeg({ quality: 80, mozjpeg: true }).toFile(path);

mkdirSync('public/og/u', { recursive: true });

const jobs = [];
const locFiles = index.filter((l) => l.slug !== 'worldwide');
for (const l of locFiles) {
  const loc = JSON.parse(readFileSync(`src/data/locations/${l.slug}.json`, 'utf8'));
  jobs.push(
    png(
      card({
        title: loc.title,
        subtitle: `top GitHub committers · ${(loc.totalUserCount ?? 0).toLocaleString()} devs`,
        rows: loc.modes.commits.slice(0, 4).map((u) => ({ rank: u.rank, label: u.login, value: u.contributions.toLocaleString() })),
        footer: `gitcooked.dev/${l.slug}`,
      }),
      `public/og/${l.slug}.jpg`
    )
  );
}

jobs.push(
  png(
    card({
      title: 'global ranking',
      subtitle: `${global.modes.commits.length.toLocaleString()} ranked devs · every country merged`,
      rows: global.modes.commits.slice(0, 4).map((u) => ({ rank: u.rank, label: u.login, value: u.contributions.toLocaleString() })),
      footer: 'gitcooked.dev/global',
    }),
    'public/og/global.jpg'
  )
);

for (const u of global.modes.commits.slice(0, 1000)) {
  jobs.push(
    png(
      card({
        title: u.login,
        subtitle: u.name || 'GitHub committer',
        rows: [
          { rank: u.rank, label: 'global rank', value: `${u.contributions.toLocaleString()} contribs` },
          ...(u.locations || []).slice(0, 3).map((slug) => {
            const loc = JSON.parse(readFileSync(`src/data/locations/${slug}.json`, 'utf8'));
            const lu = loc.modes.commits.find((x) => x.login === u.login);
            return { rank: lu?.rank ?? '—', label: loc.title, value: '' };
          }),
        ],
        footer: `gitcooked.dev/u/${u.login}`,
      }),
      `public/og/u/${u.login}.jpg`
    )
  );
}

await Promise.all(jobs);
console.log(`generated ${jobs.length} OG cards`);
