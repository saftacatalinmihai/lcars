## 10. Shares and the social side {#social}

The console can post to Mastodon and Bluesky when you tap Post, count how a post is doing where you shared it, and tell you of new comments on your accounts.

Counting and the comments are the work of crew roles that read the networks on a schedule, so they need the crew set up on the server.

### Post to Mastodon and Bluesky

Once the server holds a key for Mastodon or Bluesky, their cards in the Share sheet have **Post**{ui} and **Dry run**{ui}. Until then **Post**{ui} is greyed, and its note names what the server lacks; **Open**{ui} still works.

1. Open the entry's Share sheet (see [Read and share](#read)) and check Mastodon, Bluesky or both.
2. Tap **Post**{ui} on a card, or say "computer, post it" for every checked card at once, or "computer, post to bluesky" for one.
3. The card says "posting…" at once, and the button stays busy until the answer. Then it says "posted to Mastodon", with the post's link on the card, and **Post**{ui} goes away.

**Dry run**{ui} (or "computer, dry run") builds the post and sends nothing: the card says so, and the attempt is kept in the journal. While the server is set to dry runs, the card says "Dry runs only" and **Post**{ui} is a dry run too.

If a post fails, the card says why, in red, and **Post**{ui} becomes **Retry**{ui}. The same text is never posted twice to one network, and each network takes at most five posts a day; a card says so when it stops one.

### Count a shared post

1. Share the post where you want, by hand or with the Share sheet (see [Read and share](#read)).
2. Say "computer, add a share", or tap **+ Share**{ui} in **Blog shares**{ui}. A new entry of the share kind (`share` unless you changed it in Config) opens.
3. Paste the link of the place you shared it, and leave the entry.

The shares role reads each link's numbers every six hours. **Blog shares**{ui} shows them: the post's total over time, and a card for each place, with its latest count and a chart. On a card, **Open**{ui} goes to the place and **Entry**{ui} opens its share entry.

To open **Blog shares**{ui}, find it in **Statistics**{ui}, or say "computer, blog shares".

### See new comments on your posts

The social watch reads your accounts for new comments and replies. Each new one is written into the journal with a reply drafted for you, and a reminder appears in **Open questions**{ui}.

1. Say "computer, show the social comments", or open **Open questions**{ui} and find the social watch's card.
2. Each comment has **Open**{ui}, to go to it on its network, and **Copy reply**{ui}, to copy the drafted reply.
3. Paste the reply on the network yourself, edited as you like.

"Computer, dismiss the social reminder" ticks the reminder off; the comments stay in the journal.

### Related

- [Read and share](#read)
- [The crew](#crew)
- [Find and look back](#find)
