// Builds lcars-ui/crew/ (the deck's crew) from Quaternius's three CC0 packs,
// "Universal Base Characters" and "Universal Animation Library" 1 and 2 (the
// free Standard zips from quaternius.itch.io, scripts/deck-crew-fetch.py),
// unzipped side by side in <packs>, and what Blender made of them in <made>
// (scripts/deck-crew-hair.py's three styles, deck-crew-poses.py's two idles):
//
//   scripts/deck-crew-build.sh      (all of it: fetch, Blender, this)
//   node scripts/deck-crew-assets.mjs <packs> <made> lcars-ui/crew/
//
// Textures leave the glbs and become webp files the page loads itself, the
// bodies lose the attributes nothing reads and are quantized, and the clips
// keep rotations only (plus the pelvis's height), so the mannequin they were
// made on never lends the bodies its bone lengths. Every glb is
// meshopt-compressed (EXT_meshopt_compression, as deck-model-assets.mjs's
// rooms, since 0.248.2): the server sends a glb without gzip, and the crew
// lands at boot on every phone (deck-pipeline.md, "Measured: the crew's
// meshopt"); the page decodes them with the rooms' decoder.
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS, EXTMeshoptCompression } from '@gltf-transform/extensions';
import { prune, dedup, quantize, reorder, resample } from '@gltf-transform/functions';
import { MeshoptEncoder } from 'meshoptimizer';
import sharp from 'sharp';
import fs from 'fs';
await MeshoptEncoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({ 'meshopt.encoder': MeshoptEncoder });
// Meshopt, two ways. A body or hair: meshopt()'s level 'high' by hand -
// reordered for size, quantized, filtered - because meshopt() would quantize
// the UVs too (its pattern is fixed), and they stay floats (strip says why).
// Its filters: normals octahedral at 8 bits (the rooms' too; 10 before), and
// none on JOINTS_0 and WEIGHTS_0, which the codec stores exactly (the
// weights as the quantizer left them, 8 bits). The clips: the codec without
// filters ('medium''s method), so every keyframe decodes to the float it
// was - the filters would store rotations as 16-bit quaternions and the
// pelvis's height with a 12-bit mantissa.
const SKINNED = /^(POSITION|NORMAL|WEIGHTS_0)$/;
const packed = (doc, method) => doc.createExtension(EXTMeshoptCompression).setRequired(true).setEncoderOptions({ method });
const P = process.argv[2].replace(/\/?$/, '/'), MADE = process.argv[3].replace(/\/?$/, '/'), OUT = process.argv[4].replace(/\/?$/, '/');
const UBC = P + 'Universal Base Characters[Standard]/';
fs.mkdirSync(OUT, { recursive: true });
// the bodies' .gltf name three normal maps that the zip ships without the
// "_png" in their names; the reader wants every file a .gltf names to exist
{
  const d = UBC + 'Base Characters/Godot - UE/';
  for (const f of ['T_Hair_1_Normal', 'T_Hair_2_Normal', 'T_Eye_Normal'])
    if (!fs.existsSync(d + f + '_png.png')) fs.copyFileSync(d + f + '.png', d + f + '_png.png');
}
const KEEP = new Set(['POSITION', 'NORMAL', 'TEXCOORD_0', 'JOINTS_0', 'WEIGHTS_0']);
async function strip(doc) {
  const r = doc.getRoot();
  for (const m of r.listMeshes()) for (const p of m.listPrimitives())
    for (const s of p.listSemantics()) if (!KEEP.has(s)) p.setAttribute(s, null);
  for (const t of r.listTextures()) t.dispose();
  // keepAttributes: with the textures gone prune would take the UVs too.
  // They also stay floats: the eyes' run outside 0..1, and quantizing those
  // moves a KHR_texture_transform onto materials the page replaces.
  await doc.transform(prune({ keepAttributes: true }), dedup(), reorder({ encoder: MeshoptEncoder, target: 'size' }),
    quantize({ pattern: SKINNED, quantizePosition: 14, quantizeNormal: 8, quantizeWeight: 8 }));
  packed(doc, EXTMeshoptCompression.EncoderMethod.FILTER);
}
for (const g of ['Male', 'Female']) {
  const doc = await io.read(UBC + `Base Characters/Godot - UE/Superhero_${g}_FullBody.gltf`);
  for (const a of doc.getRoot().listAnimations()) a.dispose();
  await strip(doc);
  await io.write(OUT + g.toLowerCase() + '.glb', doc);
}
// hair: one file per style, each skinned to the head bone
{
  const dir = UBC + 'Hairstyles/Rigged to Head Bone/glTF (Godot -Unreal)/';
  const base = await io.read(dir + 'Hair_SimpleParted.gltf');
  await strip(base);
  await io.write(OUT + 'hair_SimpleParted.glb', base);
  for (const f of ['Hair_Buzzed', 'Hair_Long', 'Hair_Buns', 'Hair_BuzzedFemale', 'Hair_Beard']) {
    const d = await io.read(dir + f + '.gltf'); await strip(d); await io.write(OUT + 'hair_' + f.slice(5) + '.glb', d);
  }
  // and the three made from them, which Blender wrote as glbs
  for (const f of ['Hair_Short', 'Hair_Bob', 'Hair_Ponytail']) {
    const d = await io.read(MADE + f + '.glb'); await strip(d); await io.write(OUT + 'hair_' + f.slice(5) + '.glb', d);
  }
}
// clips: the ones the crew use, rotations only (plus the pelvis's
// translation), so the mannequin's bone lengths never reach the bodies. The
// first library's, and from the second (the same rig, node for node) and
// Blender's poses (made on the first's mannequin) the idles it lacks,
// copied across onto the first's nodes by name.
{
  const WANT = new Set(['Idle_Loop', 'Idle_Talking_Loop', 'Walk_Loop', 'Walk_Formal_Loop', 'Sitting_Idle_Loop', 'Sitting_Talking_Loop', 'Interact', 'PickUp_Table',
                        'Idle_FoldArms_Loop', 'Idle_HandsBehind_Loop', 'Idle_PADD_Loop', 'Sitting_PADD_Loop', 'Idle_Shift_Loop']);
  const doc = await io.read(P + 'Universal Animation Library[Standard]/Unreal-Godot/UAL1_Standard.glb');
  const r = doc.getRoot(), byName = new Map(r.listNodes().map(n => [n.getName(), n]));
  const buf = r.listBuffers()[0];
  const copy = acc => doc.createAccessor().setType(acc.getType()).setArray(acc.getArray().slice()).setBuffer(buf);
  for (const src of [P + 'Universal Animation Library 2[Standard]/Unreal-Godot/UAL2_Standard.glb', MADE + 'poses.glb']) {
    for (const a of (await io.read(src)).getRoot().listAnimations()) {
      if (!WANT.has(a.getName())) continue;
      const b = doc.createAnimation(a.getName());
      for (const c of a.listChannels()) {
        const n = byName.get(c.getTargetNode()?.getName()), s = c.getSampler();
        if (!n) continue;
        const t = doc.createAnimationSampler().setInput(copy(s.getInput())).setOutput(copy(s.getOutput())).setInterpolation(s.getInterpolation());
        b.addSampler(t).addChannel(doc.createAnimationChannel().setTargetNode(n).setTargetPath(c.getTargetPath()).setSampler(t));
      }
    }
  }
  for (const a of r.listAnimations()) {
    if (!WANT.has(a.getName())) { for (const s of a.listSamplers()) { s.dispose(); } a.dispose(); continue; }
    for (const c of a.listChannels()) {
      const n = c.getTargetNode()?.getName(), path = c.getTargetPath();
      if (path === 'scale' || (path === 'translation' && n !== 'pelvis') || /_04_leaf|ball_leaf/.test(n)) { const s = c.getSampler(); s.dispose(); c.dispose(); }
    }
  }
  for (const m of r.listMeshes()) m.dispose();
  for (const s of r.listSkins()) s.dispose();
  for (const mt of r.listMaterials()) mt.dispose();
  await doc.transform(resample({ tolerance: 5e-4 }), prune({ keepLeaves: true }), dedup());
  packed(doc, EXTMeshoptCompression.EncoderMethod.QUANTIZE);
  await io.write(OUT + 'clips.glb', doc);
}
// textures
const T = UBC + 'Base Characters/Textures/', H = UBC + 'Hairstyles/Textures/';
const tex = (src, dst, size, q = 82) => sharp(src).resize(size, size).webp({ quality: q }).toFile(OUT + dst);
await tex(T + 'T_Superhero_Male_Ligh.png', 'skin_m.webp', 1024);
await tex(T + 'T_Superhero_Female_Light_BaseColor.png', 'skin_f.webp', 1024);
await tex(UBC + 'Base Characters/Godot - UE/T_Superhero_Male_Normal.png', 'norm_m.webp', 1024, 90);
await tex(UBC + 'Base Characters/Godot - UE/T_Superhero_Female_Normal.png', 'norm_f.webp', 1024, 90);
await tex(T + 'T_Hair_1_BaseColor.png', 'hair1.webp', 512);
await tex(T + 'T_Hair_2_BaseColor.png', 'hair2.webp', 512);
await tex(T + 'T_Eye_Brown.png', 'eye.webp', 256);
