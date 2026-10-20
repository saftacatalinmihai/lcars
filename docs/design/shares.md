# The blog post's shares view (0.259.0)

What the captain asked: how the blog post is doing, as a whole and in each
place he shared it. The data is the shares role's (`crew/shares.md`,
`scripts/shares.py`, ARCHITECTURE.md "The blog post's shares"); this note
is the view's.

## Where it is

- `./shares`, `openShares()` in `index.html` ("the blog post's shares").
  No header button: it is reached from Stats (a "Blog shares" section with
  the latest total and a button), by voice ("computer, blog shares", "how
  is the blog post doing"), and from the palette.
- Drawn from the rows the page holds, like Stats: no endpoint, works
  offline, nothing written but the new share entry.

## What it shows

1. **The post**: the latest `crew_shares` run's total, comments, blog views
   (when Cloudflare is set up) and number of shares, when it was read, and
   one chart of the runs over time - the total, and blog views dashed, each
   on its own scale (they are counts of different sizes; the legend says so).
2. **A card per `share` entry**, newest shared first, the measurement cards'
   look: its name (the title, else the place its link names - `r/X`,
   Hacker News, X, LinkedIn, a host - so an entry saved with a link alone
   reads well), the source, the latest main count and its change, its other
   numbers in words, a time-spaced chart of its readings, and two taps:
   Open (the share's URL, a tab) and Entry (the share entry, in the editor).
   A share the latest run lists `stale` or `missing` is marked so; the
   run's error for it (else its newest reading's) is said in a line; a share
   with no link or no reading yet says what happens next.
3. **Empty**: how to add a share, and the manual line for X and LinkedIn.

`sharesData(rows)` is the whole model, pure over rows (tests.js tests it
on made-up rows); `sharesHtml` draws it.

## Adding a share

**+ Share** (and "computer, add a share") is the editor on a new entry of
kind `share`, the body focused inside the tap so iOS raises the keyboard:
a tap and a paste. An entry saved without a title gets the server's "HTTP
Entry"; the view and `shares.py` both read that as no title (the view names
it from the link, the role uses the link).

## Elsewhere

- Stats leaves the `crew_share_<id>` and `crew_shares` kinds out of
  Measurements (`isShareReading`): a card per share named by a number was
  noise. The section above replaces them.
- The crew's list (Chats, `crewReports()`) and the deck's Crew reports pad
  skip them too: readings are not reports.
- The public demo has no shares: the view is its empty state, without
  + Share.
