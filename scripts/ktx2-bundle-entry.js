// The deck's KTX2 loader, a module of its own beside the three bundle
// (three-bundle-entry.js): imported only when a room's atlas is first
// loaded, with "three" left to the page's import map, so the bundle and its
// file name stay as they are. Built (ARCHITECTURE.md, "The deck") with
//   esbuild --bundle --format=esm --minify --external:three \
//     scripts/ktx2-bundle-entry.js --outfile=lcars-ui/vendor/ktx2loader-0.186.1.mjs
// run beside three@0.186.1's node_modules, whose examples/jsm/libs/basis/ is
// lcars-ui/vendor/basis-0.186.1/. The path is relative on purpose: esbuild's
// --external:three also matches "three/addons/...", which would leave the
// loader itself out (an 89-byte re-export); its own `from "three"` stays
// external, its relative imports (ktx-parse, zstddec, WorkerPool) go in.
export { KTX2Loader } from "./node_modules/three/examples/jsm/loaders/KTX2Loader.js";
