// Cleans what scripts/deck-models/*.py write (RAW/<room>.glb and its
// <room>_{base,norm,orm}.png) into what the deck loads, lcars-ui/deck/
// (docs/design/deck-pipeline.md):
//
//   npm i @gltf-transform/core@4 @gltf-transform/functions@4 @gltf-transform/extensions@4 sharp meshoptimizer
//   node scripts/deck-model-assets.mjs RAW lcars-ui/deck/ [--size ROOM=2048 ...]
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
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { prune, dedup, weld, meshopt } from '@gltf-transform/functions';
import { MeshoptEncoder } from 'meshoptimizer';
import sharp from 'sharp';
import fs from 'fs';
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
  let tris = 0;
  for (const m of r.listMeshes()) for (const p of m.listPrimitives()) tris += (p.getIndices()?.getCount() ?? p.getAttribute('POSITION').getCount()) / 3;
  const bytes = ['.glb', '_base.webp', '_norm.webp', '_orm.webp'].reduce((a, s) => a + fs.statSync(OUT + room + s).size, 0);
  console.log(`[deck-model-assets] ${room}: ${r.listNodes().length} props, ${tris} triangles, ${(bytes / 1024).toFixed(0)} kB with its atlas (${n}²)`);
}
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
