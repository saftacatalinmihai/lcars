# Changelog

The version at the top of this file is **the** version of LCARS. The web UI
shows it under the LCARS badge (`APP_VERSION` in `lcars-ui/index.html`), so a
page showing an older number is running a cached copy. A feature bumps the
minor, a fix the patch, in the same commit as `APP_VERSION`.

## 0.298.3 — 2026-10-22

- **deck:** a phone no longer runs out of memory on a walk: rooms taken down are let go, a phone's room atlases are capped at 1024, and a lost WebGL context comes back (`test/deckmem.py` measures it); the bridge at night watch, the arboretum's pond mirroring a night sky, lighter carpets and greyer gym mats.
- **deck (0.294):** the bridge's second pass (raked stations, rounded conn consoles, LCARS tiles in the rail, generated conn and ops chairs); crouch (Z, or the Crouch pill); the generated rooms' polish: no ceiling glare, crates that read as crates, faces on the glow shapes, the labs' hologram orbs on a projector disc.
- **voice:** quick answers - the ship's computer answers a small spoken question at once (`POST /quick`, a small model through the `claude` CLI), before the crew member asked does, and an "always" setting; a spoken message is answered first in a sentence; the voice never says a line twice, and the chats' screen stays put while it speaks; on an iPhone, spoken replies come out of the loudspeaker.
- **console:** markdown tables in answers and entries; the chats tell the owner's own words from the ship's lines (notices on the left, in their own hues); the Share sheet, a post drafted for each network within its limits.
- **crew:** the social watch (`crew/social.md`, `scripts/social.py`), a read-only role that gathers the comments and the daily numbers from Hacker News, GitHub and Cloudflare Web Analytics, with its notice on the deck and in the console (README, "Features").
- **tests:** the export's own run fixed under the job runner, and the public tree's audit widened.

## 0.287.7 — 2026-10-21

- A snapshot of 0.287.7: the bridge rebuilt (Bridge 9's consoles, rail and chairs), the README's picture and crew lines, and every change since 0.278.4.

## 0.278.4 — 2026-10-20

- The first public release: one static Linux binary - the server, the CLI, and the web console and the 3D deck inside it - as tarballs for x86_64 and arm64 with SHA256SUMS on the Releases page (README.md, "Run it"), with the crew's and the engineers' scripts beside it.

