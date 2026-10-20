// Drawing on a 576x288 monochrome HUD.
//
// The Even Hub display model is containers, not pixels: you declare a page of
// list/text/image containers once with createStartUpPageContainer, then swap
// their contents with rebuildPageContainer. This module owns the three-band
// layout every screen in this app uses (header / body / footer) so no screen
// has to reason about coordinates, and so the container IDs stay stable.
//
// Rules the SDK enforces and this file encodes, rather than discovering them
// at runtime as a returned `invalid`:
//   - containerTotalNum is 1..12, and at most 8 text containers per page.
//   - Exactly one container per page sets isEventCapture: 1.
//   - zOrderIndex is all-or-nothing per page and must be unique.
//   - A menu carries at most 10 items; each itemID must be non-zero, unique,
//     and each itemName at most 32 UTF-8 bytes.

import {
  CreateStartUpPageContainer,
  ListContainerProperty,
  ListItemContainerProperty,
  MenuContainerProperty,
  MenuItemProperty,
  RebuildPageContainer,
  StartUpPageCreateResult,
  TextContainerProperty,
  TextContainerUpgrade,
  utf8ByteLength,
  type EvenAppBridge,
} from "@evenrealities/even_hub_sdk";

// Every container type the SDK exposes is a class with a toJson() the bridge
// calls on the way out, so none of them can be built as an object literal -
// the README's own example does exactly that and would not typecheck.

export const SCREEN_W = 576;
export const SCREEN_H = 288;

// Stable per-role IDs. Reusing them across rebuilds is what lets an event
// carrying a containerID be mapped back to "the list" without bookkeeping.
export const ID_HEADER = 1;
export const ID_LIST = 2;
export const ID_FOOTER = 3;
export const ID_BODY = 4;

const PAD = 8;
const HEADER_H = 36;
const FOOTER_H = 36;
const BODY_Y = HEADER_H + 4;
const BODY_H = SCREEN_H - HEADER_H - FOOTER_H - 8;

/** Roughly what fits on one line of the HUD at the default text size. */
export const CHARS_PER_LINE = 48;
/**
 * Hard firmware limits on a list container, not style choices: the glasses
 * reject a page with more than 20 items outright ("list item count N exceeds
 * limit of 20"), and truncate item text past 63 UTF-8 bytes. Both are enforced
 * here so a page is never built that the device will refuse to render.
 */
export const MAX_LIST_ITEMS = 20;
export const MAX_ITEM_BYTES = 63;
/** Lines of body text per page in the detail view. */
export const BODY_LINES = 5;

export interface MenuAction {
  id: number;
  label: string;
}

function header(content: string): TextContainerProperty {
  return new TextContainerProperty({
    containerID: ID_HEADER,
    containerName: "hdr",
    xPosition: PAD,
    yPosition: 0,
    width: SCREEN_W - PAD * 2,
    height: HEADER_H,
    zOrderIndex: 1,
    isEventCapture: 0,
    content: truncate(content, CHARS_PER_LINE),
  });
}

function footer(content: string): TextContainerProperty {
  return new TextContainerProperty({
    containerID: ID_FOOTER,
    containerName: "ftr",
    xPosition: PAD,
    yPosition: SCREEN_H - FOOTER_H,
    width: SCREEN_W - PAD * 2,
    height: FOOTER_H,
    zOrderIndex: 2,
    isEventCapture: 0,
    // Dimmer than the header: it is context, not content. 0..4, 4 = default.
    textColor: 2,
    content: truncate(content, CHARS_PER_LINE),
  });
}

function menu(actions: MenuAction[]): MenuContainerProperty | undefined {
  if (actions.length === 0) return undefined;
  const items = actions.slice(0, 10).map(
    (a) =>
      new MenuItemProperty({
        itemID: a.id,
        itemName: clampMenuName(a.label),
      }),
  );
  return new MenuContainerProperty({ menuItems: items });
}

/** Menu names are capped at 32 UTF-8 bytes; over that the SDK rejects the
 *  whole page rather than the one item. */
function clampMenuName(label: string): string {
  let out = label;
  while (utf8ByteLength(out) > 32) {
    out = out.slice(0, -1);
  }
  return out;
}

/** Trims to a UTF-8 *byte* budget. The list item limit is in bytes, so a
 *  character count is not good enough - one accented title would overrun it. */
export function truncateBytes(s: string, maxBytes: number): string {
  let out = s.replace(/\s+/g, " ").trim();
  if (utf8ByteLength(out) <= maxBytes) return out;
  while (out.length > 0 && utf8ByteLength(out + "…") > maxBytes) {
    out = out.slice(0, -1);
  }
  return out + "…";
}

export function truncate(s: string, max: number): string {
  const t = s.replace(/\s+/g, " ").trim();
  if (t.length <= max) return t;
  return t.slice(0, Math.max(0, max - 1)) + "…";
}

/** Greedy word wrap. Long unbroken tokens (a URL, a hash) are hard-split
 *  rather than allowed to overflow the container. */
export function wrapLines(text: string, width: number): string[] {
  const out: string[] = [];
  for (const paragraph of text.split(/\r?\n/)) {
    if (paragraph.trim() === "") {
      out.push("");
      continue;
    }
    let line = "";
    for (const word of paragraph.split(/\s+/)) {
      let w = word;
      while (w.length > width) {
        if (line) {
          out.push(line);
          line = "";
        }
        out.push(w.slice(0, width));
        w = w.slice(width);
      }
      if (line.length === 0) {
        line = w;
      } else if (line.length + 1 + w.length <= width) {
        line += " " + w;
      } else {
        out.push(line);
        line = w;
      }
    }
    if (line) out.push(line);
  }
  return out;
}

/** Splits wrapped text into screen-sized pages. Always at least one page, so
 *  an empty entry renders as an empty page rather than nothing at all. */
export function paginate(text: string): string[] {
  const lines = wrapLines(text, CHARS_PER_LINE);
  const pages: string[] = [];
  for (let i = 0; i < lines.length; i += BODY_LINES) {
    pages.push(lines.slice(i, i + BODY_LINES).join("\n"));
  }
  return pages.length > 0 ? pages : [""];
}

export interface ListScreen {
  header: string;
  items: string[];
  footer: string;
  actions: MenuAction[];
}

export interface TextScreen {
  header: string;
  body: string;
  footer: string;
  actions: MenuAction[];
}

/**
 * Owns the one piece of state the SDK requires: the first page of a session
 * must be created with createStartUpPageContainer, and every page after it
 * rebuilt. Getting that backwards is a silent no-op on the glasses.
 */
export class GlassesUI {
  private started = false;

  constructor(private readonly bridge: EvenAppBridge) {}

  async showList(screen: ListScreen): Promise<boolean> {
    // Clamped rather than trusted: a caller that hands over 25 rows gets a
    // page the glasses refuse entirely, which reads as a frozen app.
    const items = screen.items
      .slice(0, MAX_LIST_ITEMS)
      .map((i) => truncateBytes(i, MAX_ITEM_BYTES));
    const listObject: ListContainerProperty[] = [
      new ListContainerProperty({
        containerID: ID_LIST,
        containerName: "list",
        xPosition: PAD,
        yPosition: BODY_Y,
        width: SCREEN_W - PAD * 2,
        height: BODY_H,
        zOrderIndex: 3,
        // The list is where scroll and click land, so it is this page's single
        // event-capturing container.
        isEventCapture: 1,
        itemContainer: new ListItemContainerProperty({
          itemCount: items.length,
          itemWidth: SCREEN_W - PAD * 2,
          isItemSelectBorderEn: 1,
          itemName: items,
        }),
      }),
    ];
    return this.commit({
      containerTotalNum: 3,
      listObject,
      textObject: [header(screen.header), footer(screen.footer)],
      menuObject: menu(screen.actions),
    });
  }

  async showText(screen: TextScreen): Promise<boolean> {
    const textObject: TextContainerProperty[] = [
      header(screen.header),
      footer(screen.footer),
      new TextContainerProperty({
        containerID: ID_BODY,
        containerName: "body",
        xPosition: PAD,
        yPosition: BODY_Y,
        width: SCREEN_W - PAD * 2,
        height: BODY_H,
        zOrderIndex: 3,
        isEventCapture: 1,
        content: screen.body,
      }),
    ];
    return this.commit({
      containerTotalNum: 3,
      textObject,
      menuObject: menu(screen.actions),
    });
  }

  /** Swaps only the body text of the current text page - far cheaper over BLE
   *  than rebuilding the page, which is what makes paging feel instant. */
  async updateBody(content: string): Promise<boolean> {
    return this.bridge.textContainerUpgrade(
      new TextContainerUpgrade({
        containerID: ID_BODY,
        containerName: "body",
        content,
      }),
    );
  }

  async updateFooter(content: string): Promise<boolean> {
    return this.bridge.textContainerUpgrade(
      new TextContainerUpgrade({
        containerID: ID_FOOTER,
        containerName: "ftr",
        content: truncate(content, CHARS_PER_LINE),
        textColor: 2,
      }),
    );
  }

  async close(): Promise<boolean> {
    this.started = false;
    return this.bridge.shutDownPageContainer(0);
  }

  private async commit(page: {
    containerTotalNum: number;
    listObject?: ListContainerProperty[];
    textObject?: TextContainerProperty[];
    menuObject?: MenuContainerProperty;
  }): Promise<boolean> {
    if (!this.started) {
      const result = await this.bridge.createStartUpPageContainer(
        new CreateStartUpPageContainer(page),
      );
      if (result === StartUpPageCreateResult.success) {
        this.started = true;
        return true;
      }
      // A startup page is refused when the glasses already hold one - which
      // happens on every relaunch that did not shut its page down, and on
      // every hot reload in development. Without this fallback the app then
      // retries `create` forever and every screen it draws is silently
      // dropped: input still arrives, but against the *previous* page's list
      // and menu. That looks like a frozen app that occasionally does the
      // wrong thing, and it is the single most confusing failure here.
      //
      // So try to adopt the existing page instead. If the page is genuinely
      // malformed rather than merely already-created, the rebuild fails too
      // and the caller still learns about it.
      const adopted = await this.bridge.rebuildPageContainer(
        new RebuildPageContainer(page),
      );
      if (adopted) {
        this.started = true;
        return true;
      }
      console.error(
        "createStartUpPageContainer failed and the page could not be rebuilt:",
        result,
      );
      return false;
    }
    return this.bridge.rebuildPageContainer(new RebuildPageContainer(page));
  }
}
