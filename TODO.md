# TODO

The backlog: features, bugs and refactoring ideas worth tracking. Remove
an item in the commit that finishes it (CHANGELOG.md records it).

## The release

- **arm64 decides CI too.** static.yml and release.yml let an arm64
  failure pass (`continue-on-error`) because the private clone's arm64
  runners are metered or absent; once the public repo's arm64 runs have
  proven steady, let them fail the run there.

## Setup

- **Imports from other notes apps.** Logseq's is built (`lcars-cli
  logseq`); Obsidian, a folder of markdown or another app's export is an
  order to the engineers away.
