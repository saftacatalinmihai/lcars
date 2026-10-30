// Cleans what scripts/deck-models/*.py write (RAW/<room>.glb and its
// <room>_{base,norm,orm}.png) into what the deck loads, lcars-ui/deck/
// (docs/design/deck-pipeline.md):
//
//   npm i @gltf-transform/core@4 @gltf-transform/functions@4 @gltf-transform/extensions@4 sharp meshoptimizer
//   node scripts/deck-model-assets.mjs RAW lcars-ui/deck/ [--size ROOM=2048 ...]
//   node scripts/deck-model-assets.mjs --ktx2 lcars-ui/deck/ [ROOM ... | maps]
//
// (scripts/deck-models/build.sh does both, the packages in a cache.) As
// deck-crew-assets.mjs does for the crew: the glb keeps only the attributes
// the page reads (POSITION, NORMAL, TANGENT, TEXCOORD_0), is pruned, deduplicated,
// welded, quantized (positions 14 bits, UVs 12) and meshopt-compressed
// (EXT_meshopt_compression, normals and tangents octahedral at 8 bits): the
// server sends a glb as it is, no gzip, so the file is what the phone
// fetches, and meshopt makes it about 0.4 of the quantized glb's bytes
// (deck-pipeline.md, "Measured: meshopt"); the page decodes it with
// lcars-ui/vendor/meshopt_decoder-*.mjs, the same package's. The atlas
// leaves it as three webp files the page loads itself (base colour q82,
// normal q90, ORM q90), at the size they were baked (finish_room's `size`:
// 1024 a room, 2048 a hero room, 512 a few pieces of dressing) unless
// --size says otherwise. A RAW/<room>.LICENSE.txt (a converted pack's, or a room
// script's with a pack's props in it) becomes that room's section of lcars-ui/deck/LICENSE.txt; a room without one is the
// repo's own work and says so.
//
// KTX2 beside the webp (docs/design/deck-remodel.md, slice 1): a webp is
// small on the wire but a phone's GPU holds it as RGBA8, ~5.6 MB a 1024²
// map with its mips, three a room, every room seen kept; a KTX2 is
// transcoded on the phone to a format the GPU keeps compressed (ETC1S to
// ETC2 at half a byte a pixel, UASTC to ASTC 4x4 at one). Each room's maps
// are written as <room>_{base,norm,orm}.ktx2, mipmapped, at most KTX2_MAX
// (the phone's atlas size, ATLAS_MAX in deck.html: Ten Forward's 2048 is
// 1024 here, and a desktop keeps its webp), with KTX-Software's `ktx create`
// ($KTX, or on the PATH; build.sh keeps one in its cache): the base colour
// ETC1S (sRGB), the normal map UASTC with RDO and zstd (linear), the ORM
// ETC1S (linear: its baked AO is noise UASTC cannot pack, 2.4 MB at 2048²
// against ETC1S's 0.5); a nearly flat normal map ETC1S too (`NORM_ETC1S`).
// A room whose glb and three maps come to more than WIRE_MAX steps down
// until it fits: the normal map ETC1S, then the ORM at half size, then the
// normal map. lcars-ui/deck/atlases.json says what each
// room has (its baked size, the KTX2's, each map's codec); the page loads
// the KTX2 only for a room listed there, and the webp when it is not, or
// when either fails. `--ktx2` makes them from the webps already in OUT
// (no Blender: one more generation of loss, invisible at these settings);
// a build makes them from Blender's PNGs. Without `ktx`, a room's KTX2 and
// its entry are removed, never left stale beside a new atlas.
//
// The bridge's own maps (slice 1's second half): its tiles (carpet, wall:
// base, normal, roughness; scripts/deck-models/tiles.py) and the coffer's
// skylight, loaded by deck.html beside the rooms' atlases, are KTX2 too, at
// their webp's own size, listed under `maps` in atlases.json, made from
// those webps by `--ktx2` alone or `--ktx2 OUT maps` (a room's build leaves
// them be; after tiles.py or a new skylight, run `build.sh --ktx2 maps`, or
// the page shows the old KTX2). Unlike an atlas these load with three's default
// flipY, which a compressed texture cannot have: they are written flipped,
// so each texel sits at the uv it had (the normal map's vectors with it).
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { prune, dedup, weld, meshopt } from '@gltf-transform/functions';
import { MeshoptEncoder } from 'meshoptimizer';
import sharp from 'sharp';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { execFileSync } from 'child_process';
const KTX2_MAX = 1024, WIRE_MAX = 600 * 1024;
const KTX = process.env.KTX || 'ktx';
const hasKtx = (() => { try { execFileSync(KTX, ['--version'], { stdio: 'ignore' }); return true; } catch { return false; } })();
const ETC1S = ['--encode', 'basis-lz', '--clevel', '4', '--qlevel', '255'];
const UASTC = ['--encode', 'uastc', '--uastc-quality', '4', '--uastc-rdo', '--uastc-rdo-l', '0.5', '--zstd', '22'];
// one map: `src` (a PNG or webp, any size) at n² to OUT/<room>_<k>.ktx2
async function ktx2(src, out, n, codec, srgb, flip = false) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'deck-ktx2-'));
  try {
    const png = path.join(tmp, 'in.png');
    await sharp(src).resize(n, n).flip(flip).removeAlpha().png().toFile(png);
    execFileSync(KTX, ['create', '--format', srgb ? 'R8G8B8_SRGB' : 'R8G8B8_UNORM', '--assign-tf', srgb ? 'srgb' : 'linear',
      ...(codec === 'uastc' ? UASTC : ETC1S), '--generate-mipmap', png, out], { stdio: ['ignore', 'ignore', 'inherit'] });
  } finally { fs.rmSync(tmp, { recursive: true, force: true }); }
  return fs.statSync(out).size;
}
// The rooms whose normal map is ETC1S from the start, wire or no: nearly
// flat maps (scripted props, their relief under ~2 degrees at its 99th
// percentile against a flat map), where UASTC paid for what ETC1S drops -
// slice 7's three, built from Blender's PNGs, carried their bake noise into
// 218-261 kB of UASTC against a 5-13 kB webp; the others, 15-133 kB against
// 3-17. ETC1S came to 2-18 kB each and looked the same at high in a close
// look (docs/design/deck-remodel.md, section 6 item 7). Not the bridge's
// tiles (`MAPS`) nor Ten Forward's: their relief is real, and ETC1S
// flattens it.
const NORM_ETC1S = new Set(['arboretum', 'concourse', 'conference', 'engineering', 'lab', 'lounge', 'mess', 'school', 'sickbay']);
// a room's three into OUTd, stepping down until its wire fits WIRE_MAX; `src(k)` its
// map k's source, `n` the size it was baked at
async function roomKtx2(OUTd, room, src, n) {
  const k2 = Math.min(n, KTX2_MAX), glb = fs.statSync(`${OUTd}${room}.glb`).size;
  const plan = { base: ['etc1s', k2], norm: [NORM_ETC1S.has(room) ? 'etc1s' : 'uastc', k2], orm: ['etc1s', k2] };
  const steps = [() => { plan.norm[0] = 'etc1s'; }, () => { plan.orm[1] = k2 / 2; }, () => { plan.norm[1] = k2 / 2; }];
  const bytes = {};
  for (let i = 0; ; i++) {
    for (const k of ['base', 'norm', 'orm'])
      if (!bytes[k] || bytes[k].at !== plan[k].join()) bytes[k] = { at: plan[k].join(), n: await ktx2(src(k), `${OUTd}${room}_${k}.ktx2`, plan[k][1], plan[k][0], k === 'base') };
    const wire = glb + bytes.base.n + bytes.norm.n + bytes.orm.n;
    if (wire <= WIRE_MAX || i === steps.length) {
      if (wire > WIRE_MAX) console.warn(`[deck-model-assets] ${room}: ${(wire / 1024).toFixed(0)} kB on the wire with every step taken`);
      return { size: n, wire, ...Object.fromEntries(Object.entries(plan).map(([k, [c, m]]) => [k, { codec: c, size: m, bytes: bytes[k].n }])) };
    }
    steps[i]();
  }
}
const MANIFEST = 'atlases.json';
function manifest(OUTd) {
  try { return JSON.parse(fs.readFileSync(`${OUTd}${MANIFEST}`, 'utf8')); } catch { return { rooms: {} }; }
}
function saveManifest(OUTd, m) {
  m.note = 'Each room\'s atlas, and under maps the bridge\'s tiles and skylight, as KTX2 (scripts/deck-model-assets.mjs): the page loads these for what is listed here, its webp otherwise.';
  m.rooms = Object.fromEntries(Object.entries(m.rooms).sort());
  if (m.maps) m.maps = Object.fromEntries(Object.entries(m.maps).sort());
  fs.writeFileSync(`${OUTd}${MANIFEST}`, JSON.stringify(m, null, 1) + '\n');
}
function dropKtx2(OUTd, m, room) {
  for (const k of ['base', 'norm', 'orm']) fs.rmSync(`${OUTd}${room}_${k}.ktx2`, { force: true });
  delete m.rooms[room];
}
// the bridge's maps: name -> [codec, sRGB]. The normal maps UASTC, as the
// rooms'; the rest ETC1S. The skylight's panes are smooth warm gradients,
// where ETC1S could band: decoded beside the webp it shows only a 4x4
// block noise with the gradient stretched 4x (37.5 dB), none at its own
// contrast nor in the deck's close look at high; UASTC was 46.4 dB but
// 821 kB with its mips against ETC1S's ~190 (the webp: 67)
const MAPS = {
  bridge_carpet_base: ['etc1s', true], bridge_carpet_norm: ['uastc', false], bridge_carpet_rough: ['etc1s', false],
  bridge_wall_base: ['etc1s', true], bridge_wall_norm: ['uastc', false], bridge_wall_rough: ['etc1s', false],
  bridge_skylight: ['etc1s', true],
};
async function mapsKtx2(OUTd, m) {
  m.maps ??= {};
  for (const [name, [codec, srgb]] of Object.entries(MAPS)) {
    const src = `${OUTd}${name}.webp`;
    if (!fs.existsSync(src)) { fs.rmSync(`${OUTd}${name}.ktx2`, { force: true }); delete m.maps[name]; continue; }
    const n = (await sharp(src).metadata()).width;
    m.maps[name] = { codec, size: n, bytes: await ktx2(src, `${OUTd}${name}.ktx2`, n, codec, srgb, true) };
    console.log(`[deck-model-assets] ${name}: KTX2 ${n}² ${codec} ${(m.maps[name].bytes / 1024).toFixed(0)} kB`);
  }
}
if (process.argv[2] === '--ktx2') {
  const OUTd = (process.argv[3] || '').replace(/\/?$/, '/'), m = manifest(OUTd);
  if (!process.argv[3] || !hasKtx) { console.error(!hasKtx ? `no ${KTX}: set KTX to KTX-Software's ktx` : 'usage: node scripts/deck-model-assets.mjs --ktx2 OUT [ROOM ... | maps]'); process.exit(2); }
  const want = process.argv.slice(4);
  const rooms = want.length ? want.filter(r => r !== 'maps') : fs.readdirSync(OUTd).filter(f => f.endsWith('.glb')).map(f => f.slice(0, -4)).filter(r => fs.existsSync(`${OUTd}${r}_orm.webp`)).sort();
  for (const room of rooms) {
    const n = (await sharp(`${OUTd}${room}_base.webp`).metadata()).width;
    m.rooms[room] = await roomKtx2(OUTd, room, k => `${OUTd}${room}_${k}.webp`, n);
    const e = m.rooms[room];
    console.log(`[deck-model-assets] ${room}: KTX2 ${e.base.size}² base ${e.base.codec} ${(e.base.bytes / 1024).toFixed(0)} kB, norm ${e.norm.codec} ${e.norm.size}² ${(e.norm.bytes / 1024).toFixed(0)} kB, orm ${e.orm.codec} ${e.orm.size}² ${(e.orm.bytes / 1024).toFixed(0)} kB; ${(e.wire / 1024).toFixed(0)} kB with its glb`);
    saveManifest(OUTd, m);
  }
  if (!want.length || want.includes('maps')) { await mapsKtx2(OUTd, m); saveManifest(OUTd, m); }
  process.exit(0);
}
await MeshoptEncoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({ 'meshopt.encoder': MeshoptEncoder });
const [RAW, OUT0, ...rest] = process.argv.slice(2);
if (!RAW || !OUT0) { console.error('usage: node scripts/deck-model-assets.mjs RAW OUT [--size ROOM=N ...]'); process.exit(2); }
const OUT = OUT0.replace(/\/?$/, '/');
const sizes = {};
for (let i = 0; i < rest.length; i++) if (rest[i] === '--size') { const [r, n] = rest[++i].split('='); sizes[r] = +n; }
fs.mkdirSync(OUT, { recursive: true });
// TANGENT too: the normal map is baked in Blender's tangent space
// (MikkTSpace), and three's own per-pixel tangents disagree with it across
// an atlas's rotated islands - a seam along every island on the vase
const KEEP = new Set(['POSITION', 'NORMAL', 'TANGENT', 'TEXCOORD_0']);
const built = { m: manifest(OUT) };
const rooms = fs.readdirSync(RAW).filter(f => f.endsWith('.glb')).map(f => f.slice(0, -4)).sort();
for (const room of rooms) {
  const doc = await io.read(`${RAW}/${room}.glb`);
  const r = doc.getRoot();
  for (const m of r.listMeshes()) for (const p of m.listPrimitives())
    for (const s of p.listSemantics()) if (!KEEP.has(s)) p.setAttribute(s, null);
  for (const t of r.listTextures()) t.dispose();
  // meshopt's 'high' level reorders for size, quantizes positions and UVs,
  // and leaves normals and tangents to its octahedral filter (8 bits, its
  // cap; 10 was the quantizer's): no seam or banding in the deckshots
  await doc.transform(prune({ keepAttributes: true }), dedup(), weld(),
    meshopt({ encoder: MeshoptEncoder, level: 'high', quantizePosition: 14, quantizeNormal: 8, quantizeTangent: 8, quantizeTexcoord: 12 }));
  await io.write(`${OUT}${room}.glb`, doc);
  const n = sizes[room] || (await sharp(`${RAW}/${room}_base.png`).metadata()).width;
  for (const [k, q] of [['base', 82], ['norm', 90], ['orm', 90]])
    await sharp(`${RAW}/${room}_${k}.png`).resize(n, n).webp({ quality: q }).toFile(`${OUT}${room}_${k}.webp`);
  if (hasKtx) built[room] = await roomKtx2(OUT, room, k => `${RAW}/${room}_${k}.png`, n);
  else { dropKtx2(OUT, built.m, room); console.warn(`[deck-model-assets] ${room}: no ${KTX}, so no KTX2 (the page loads its webp)`); }
  let tris = 0;
  for (const m of r.listMeshes()) for (const p of m.listPrimitives()) tris += (p.getIndices()?.getCount() ?? p.getAttribute('POSITION').getCount()) / 3;
  const bytes = ['.glb', '_base.webp', '_norm.webp', '_orm.webp'].reduce((a, s) => a + fs.statSync(OUT + room + s).size, 0);
  console.log(`[deck-model-assets] ${room}: ${r.listNodes().length} props, ${tris} triangles, ${(bytes / 1024).toFixed(0)} kB with its atlas (${n}²)`);
}
for (const [room, e] of Object.entries(built)) if (room !== 'm') built.m.rooms[room] = e;
saveManifest(OUT, built.m);
// LICENSE.txt: one section per room, from the rooms built now and the ones
// already there (a build of one room keeps the others' sections). A section
// that is not a room's (a texture of the page's own, bridge_skylight.webp)
// keeps its heading as written: only a room's is made from its name.
const L = `${OUT}LICENSE.txt`, sect = new Map(), head = new Map();
if (fs.existsSync(L)) for (const part of fs.readFileSync(L, 'utf8').split(/^== /m).slice(1)) {
  const nl = part.indexOf('\n'), h = part.slice(0, nl).trim(), k = h.replace(/\.glb.*$/, '');
  sect.set(k, part.slice(nl + 1).trim());
  if (!h.includes('.glb')) head.set(k, h);
}
for (const room of rooms) {
  const f = `${RAW}/${room}.LICENSE.txt`;
  // a room script may carry a pack's props beside its own (readyroom.py):
  // its licences, then what the script built
  const own = `Built in Blender by scripts/deck-models/${room}.py, part of this repository.`;
  const script = fs.existsSync(new URL(`./deck-models/${room}.py`, import.meta.url));
  sect.set(room, !fs.existsSync(f) ? own : fs.readFileSync(f, 'utf8').trim() +
    (script ? `\nThese converted by common.import_pack; the rest:\n${own}` : `\nConverted by scripts/deck-models/pack.py.`));
}
fs.writeFileSync(L, 'The deck\'s models in this directory, one section per glb and its atlas.\n' +
  'scripts/deck-models/build.sh rebuilds them (docs/design/deck-pipeline.md).\n\n' +
  [...sect].sort().map(([k, v]) => `== ${head.get(k) ?? `${k}.glb, ${k}_{base,norm,orm}.webp`}\n${v}\n`).join('\n'));
