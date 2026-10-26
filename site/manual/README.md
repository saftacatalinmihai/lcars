# The console's user manual

The source of the user manual of the web console: `pages/*.md` and
`img/*.webp`, with the keys and phrases appendices made from
`lcars-ui/index.html` at every build. How it is built, checked and
published: [docs/design/manual.md](../../docs/design/manual.md).

## Editing

1. Edit a page in `pages/`. Write a label of the console as
   `**label**{ui}`, exactly as it reads on screen; a spoken order as
   `"computer, …"`; a key in bold, `**n**`.
2. `python3 site/manual/build.py`: writes its two committed builds, the
   landing's page, `site/landing/public/manual/`, and the app's copy,
   `lcars-ui/manual/` (served at `/ui/manual/`, short link `/manual`):
   commit both. The third build is the report's, below.
3. `python3 site/manual/test/manual.py`: the check run.sh runs.

A change to the console's keys, spoken orders or labels can fail the
check too: the appendices are made from the page, so rebuild and commit.

To see the report's single file: `python3 site/manual/build.py --inline
/tmp/manual.html` (pictures inline, the version filled).

## The pictures

`site/manual/pictures.sh` makes them again: `lcars-ui/test/shots.py`'s
frames and `shots_crew.py`'s (the chats, a room and open questions, with
made-up crew), against perf.py's made-up journal, cropped and encoded to
WebP with ffmpeg. It is a heavy run; on the crew's box:

```sh
scripts/engineer.py job <name> -- site/manual/pictures.sh
```

Then rebuild, and look at every picture: the crops were chosen for the
views as they were.
