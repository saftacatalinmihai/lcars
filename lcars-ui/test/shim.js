/* ===== a DOM small enough to fit in QuickJS, big enough to boot the app ===== */
"use strict";
var TEST = { confirmAnswer: true, mobile: false, hashFirst: false,
            log: [], fetches: [], asserts: 0, fails: [] };

var VOID = { area:1, base:1, br:1, col:1, embed:1, hr:1, img:1, input:1, link:1,
             meta:1, source:1, track:1, wbr:1 };

var ENT = { amp:"&", lt:"<", gt:">", quot:'"', apos:"'", nbsp:" ",
            lsaquo:"‹", rsaquo:"›", middot:"·" };
function decodeEnt(s) {
  return s.replace(/&(#x?[0-9a-fA-F]+|[a-zA-Z]+);/g, function (m, b) {
    if (b[0] === "#") {
      var n = b[1] === "x" || b[1] === "X" ? parseInt(b.slice(2), 16) : parseInt(b.slice(1), 10);
      return isNaN(n) ? m : String.fromCodePoint(n);
    }
    return ENT[b] !== undefined ? ENT[b] : m;
  });
}

function TextNode(t) { this.nodeType = 3; this.data = String(t); this.parentNode = null; }
Object.defineProperty(TextNode.prototype, "textContent", {
  get: function () { return this.data; },
  set: function (v) { this.data = String(v); },
});
Object.defineProperty(TextNode.prototype, "nodeValue", {
  get: function () { return this.data; },
  set: function (v) { this.data = String(v); },
});

/* Every element ever given an id, by id. The page calls $("#id") tens of
   thousands of times a run, and as a walk each one visited ~600 nodes: that
   was half the suite's time. The index only nominates; idLookup keeps an
   element only if it still has the id and is really in root's subtree (each
   step up is checked against the parent's childNodes, since innerHTML and
   textContent drop children without clearing their parentNode). With exactly
   one such element that is what the walk would return, and with none it would
   return null; two or more (a duplicate id) go back to the walk, which knows
   document order. So the answer is always the walk's. Ids are only ever
   written by the id setter, setAttribute and the parser, all of which note it. */
var __ids = Object.create(null);
function idNote(el) {
  var id = el.attrs.id, a = __ids[id] || (__ids[id] = []);
  if (a.indexOf(el) < 0) a.push(el);
}
function idUnder(n, root) {
  if (n === root) return false;              // the walk looks at descendants only
  for (var p = n; p !== root; p = p.parentNode) {
    var up = p.parentNode;
    if (!up || up.childNodes.indexOf(p) < 0) return false;
  }
  return true;
}
// the element, null, or undefined when only a walk can say (duplicate ids)
function idLookup(root, id) {
  var a = __ids[id];
  if (!a) return null;
  var keep = [], one = null, n = 0;
  for (var i = 0; i < a.length; i++) {
    if (a[i].attrs.id !== id) continue;      // renamed since: forgotten
    keep.push(a[i]);
    if (idUnder(a[i], root)) { one = a[i]; n++; }
  }
  __ids[id] = keep;
  return n > 1 ? undefined : one;
}
function El(tag) {
  this.nodeType = 1;
  this.tagName = String(tag).toUpperCase();
  this.childNodes = [];
  this.parentNode = null;
  this.attrs = {};
  this._on = {};
  this._value = null;
  this.checked = false;
  this.disabled = false;
  this.readOnly = false;
  this._scrollTop = 0; this.scrollHeight = 0; this.clientHeight = 400;
  this.selectionStart = 0; this.selectionEnd = 0;
  var self = this;
  this.style = new Proxy({ _p: {} }, {
    get: function (t, k) {
      if (k === "setProperty") return function (n, v) { t._p[n] = v; };
      if (k === "getPropertyValue") return function (n) { return t._p[n] || ""; };
      if (k === "removeProperty") return function (n) { delete t._p[n]; };
      if (k === "cssText") return JSON.stringify(t._p);
      return t._p[k] === undefined ? "" : t._p[k];
    },
    set: function (t, k, v) { t._p[k] = String(v); return true; },
  });
  this.classList = {
    contains: function (c) { return clsPad(self).indexOf(" " + c + " ") >= 0; },
    add: function () { var l = self._cls();
      for (var i = 0; i < arguments.length; i++) if (l.indexOf(arguments[i]) < 0) l.push(arguments[i]);
      self.attrs["class"] = l.join(" "); },
    remove: function () { var a = Array.prototype.slice.call(arguments);
      self.attrs["class"] = self._cls().filter(function (c) { return a.indexOf(c) < 0; }).join(" "); },
    toggle: function (c, on) {
      var has = self._cls().indexOf(c) >= 0;
      var want = on === undefined ? !has : !!on;
      if (want) this.add(c); else this.remove(c);
      return want; },
  };
  this.dataset = new Proxy({}, {
    get: function (t, k) { return self.attrs["data-" + camel2dash(k)]; },
    set: function (t, k, v) { self.attrs["data-" + camel2dash(k)] = String(v); return true; },
    has: function (t, k) { return ("data-" + camel2dash(k)) in self.attrs; },
    deleteProperty: function (t, k) { delete self.attrs["data-" + camel2dash(k)]; return true; },
  });
}
function camel2dash(k) { return String(k).replace(/[A-Z]/g, function (c) { return "-" + c.toLowerCase(); }); }

El.prototype._cls = function () {
  var c = this.attrs["class"];
  return c ? c.split(/\s+/).filter(Boolean) : [];
};
/* The class list is read once per element for every compound a selector walk
   tries, so it is held as a padded string — " a b " — and rebuilt only when the
   attribute itself changes.  Membership is then an indexOf, not a split. */
function clsPad(el) {
  var cv = el.attrs["class"];
  if (!cv) return "";
  if (el.__clsRaw !== cv) {
    el.__clsRaw = cv;
    el.__clsPad = " " + cv.replace(/\s+/g, " ").replace(/^ | $/g, "") + " ";
  }
  return el.__clsPad;
}
Object.defineProperty(El.prototype, "id", {
  get: function () { return this.attrs.id || ""; },
  set: function (v) { this.attrs.id = String(v); idNote(this); },
});
Object.defineProperty(El.prototype, "className", {
  get: function () { return this.attrs["class"] || ""; },
  set: function (v) { this.attrs["class"] = String(v); },
});
Object.defineProperty(El.prototype, "children", {
  get: function () { return this.childNodes.filter(function (n) { return n.nodeType === 1; }); },
});
Object.defineProperty(El.prototype, "firstChild", {
  get: function () { return this.childNodes[0] || null; },
});
// the outline fold reads the <ul> sitting after an <li>: siblings are the
// parent's element children, and a node with no parent has none
Object.defineProperty(El.prototype, "nextElementSibling", {
  get: function () {
    if (!this.parentNode) return null;
    var k = this.parentNode.children, i = k.indexOf(this);
    return i >= 0 ? (k[i + 1] || null) : null;
  },
});
// the date scrubber walks back from a row to the day bar that opened its run
Object.defineProperty(El.prototype, "previousElementSibling", {
  get: function () {
    if (!this.parentNode) return null;
    var k = this.parentNode.children, i = k.indexOf(this);
    return i > 0 ? k[i - 1] : null;
  },
});
Object.defineProperty(El.prototype, "nextSibling", {
  get: function () { return this.nextElementSibling; },
});
Object.defineProperty(El.prototype, "value", {
  get: function () {
    if (this._value !== null) return this._value;
    if (this.tagName === "SELECT") {
      var opts = this.querySelectorAll("option");
      if (this.attrs.multiple !== undefined) {   // the first pick, or nothing
        for (var i = 0; i < opts.length; i++) if (opts[i].selected) return optVal(opts[i]);
        return "";
      }
      return opts[0] ? optVal(opts[0]) : "";
    }
    if (this.tagName === "OPTION") return optVal(this);
    return "";
  },
  set: function (v) {
    v = String(v);
    if (this.tagName === "SELECT") {
      var opts = this.querySelectorAll("option");
      for (var i = 0; i < opts.length; i++) if (optVal(opts[i]) === v) { this._value = v; return; }
      this._value = "";     // the real DOM refuses a value no option carries
      return;
    }
    this._value = v;
  },
});
function optVal(o) {
  return o.attrs.value !== undefined ? o.attrs.value : o.textContent;
}
// a multi-select reports its picks here; options carry .selected as a plain flag
Object.defineProperty(El.prototype, "selectedOptions", {
  get: function () {
    return this.querySelectorAll("option").filter(function (o) { return !!o.selected; });
  },
});
El.prototype.setRangeText = function (t, a, b) {
  var v = this.value;
  this.value = v.slice(0, a) + t + v.slice(b);
};
// the caret, as a field holds it: clamped to the text, start never past end
El.prototype.setSelectionRange = function (a, b) {
  var n = String(this.value || "").length;
  this.selectionStart = Math.max(0, Math.min(n, a | 0));
  this.selectionEnd = Math.max(this.selectionStart, Math.min(n, (b === undefined ? a : b) | 0));
};
El.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); if (k === "id") idNote(this); };
El.prototype.getAttribute = function (k) { return this.attrs[k] === undefined ? null : this.attrs[k]; };
El.prototype.hasAttribute = function (k) { return this.attrs[k] !== undefined; };
El.prototype.removeAttribute = function (k) { delete this.attrs[k]; };
El.prototype.appendChild = function (n) {
  if (n && n.__frag) { var kids = n.childNodes.slice();
    for (var i = 0; i < kids.length; i++) this.appendChild(kids[i]); return n; }
  if (n.parentNode) n.parentNode.removeChild(n);
  n.parentNode = this; this.childNodes.push(n); return n;
};
El.prototype.removeChild = function (n) {
  var i = this.childNodes.indexOf(n);
  if (i >= 0) { this.childNodes.splice(i, 1); n.parentNode = null; }
  return n;
};
El.prototype.remove = function () { if (this.parentNode) this.parentNode.removeChild(this); };
El.prototype.click = function () { dispatch(this, "click"); };
// the list's windowing puts rows in front of others: its spacer goes first, and
// rows scrolled back into view go in right after it
El.prototype.insertBefore = function (n, ref) {
  var ins = n && n.__frag ? n.childNodes.slice() : [n];
  for (var k = 0; k < ins.length; k++) {
    if (ins[k].parentNode) ins[k].parentNode.removeChild(ins[k]);
    ins[k].parentNode = this;
  }
  if (n && n.__frag) n.childNodes = [];
  var i = ref ? this.childNodes.indexOf(ref) : -1;
  if (i < 0) i = this.childNodes.length;
  this.childNodes.splice.apply(this.childNodes, [i, 0].concat(ins));
  return n;
};
El.prototype.prepend = function (n) { this.insertBefore(n, this.childNodes[0] || null); };
El.prototype.after = function (n) {
  var p = this.parentNode;
  if (!p) return;
  var i = p.childNodes.indexOf(this);
  p.insertBefore(n, p.childNodes[i + 1] || null);
};
// the reading pane swaps a marked-up fragment in over a text node it walked to
El.prototype.replaceChild = function (nu, old) {
  if (this.childNodes.indexOf(old) < 0) return old;
  var ins = nu && nu.__frag ? nu.childNodes.slice() : [nu];
  for (var k = 0; k < ins.length; k++) {
    if (ins[k].parentNode) ins[k].parentNode.removeChild(ins[k]);
    ins[k].parentNode = this;
  }
  if (nu && nu.__frag) nu.childNodes = [];
  // re-read the slot: detaching the new nodes may have shifted it
  this.childNodes.splice.apply(this.childNodes, [this.childNodes.indexOf(old), 1].concat(ins));
  old.parentNode = null;
  return old;
};
/* <template> keeps its parse in a fragment rather than among its own children.
   The shim's parser does not know that, so the children are moved across on
   read — which is the only moment anything looks. */
Object.defineProperty(El.prototype, "content", {
  get: function () {
    if (this.tagName !== "TEMPLATE") return undefined;   // as in the real DOM
    if (!this.__content) { this.__content = new El("fragment"); this.__content.__frag = true; }
    var kids = this.childNodes.slice();
    for (var i = 0; i < kids.length; i++) this.__content.appendChild(kids[i]);
    return this.__content;
  },
});
El.prototype.focus = function () {
  TEST.focused = this; document.activeElement = this; this._vAtFocus = this.value;
};
/* A text control fires `change` when it loses the focus holding a value other
   than the one it had when it gained it — including when the difference was
   written programmatically in between, which is what a save does. The page has
   to survive that, so the shim reproduces it rather than blurring in silence. */
El.prototype.blur = function () {
  if (document.activeElement !== this) return;
  document.activeElement = document.body;
  if (this._vAtFocus !== undefined && this._vAtFocus !== this.value) {
    this._vAtFocus = this.value;
    dispatch(this, "change", {});
  }
};
Object.defineProperty(El.prototype, "tabIndex", {
  get: function () { return this.attrs.tabindex === undefined ? -1 : +this.attrs.tabindex; },
  set: function (v) { this.attrs.tabindex = String(v); },
});
El.prototype.select = function () {};
El.prototype.scrollIntoView = function () {};
// Enough of HTMLMediaElement for the players (the tape deck, lpToggle): no
// sound and no clock, just paused/play/pause and the events they send.
Object.defineProperty(El.prototype, "paused", { get: function () { return this._playing !== true; },
  set: function (v) { this._playing = !v; } });
El.prototype.ended = false;
El.prototype.currentTime = 0;
El.prototype.duration = NaN;
El.prototype.play = function () { this._playing = true; dispatch(this, "play"); return Promise.resolve(); };
El.prototype.pause = function () { if (this._playing) { this._playing = false; dispatch(this, "pause"); } };
El.prototype.load = function () {};
// Layout does not exist here; a test that needs geometry sets el._rect.
El.prototype.getBoundingClientRect = function () {
  return Object.assign({ left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 }, this._rect);
};
El.prototype.setPointerCapture = function () {};
Object.defineProperty(El.prototype, "textContent", {
  get: function () {
    var out = "";
    (function walk(n) {
      for (var i = 0; i < n.childNodes.length; i++) {
        var c = n.childNodes[i];
        if (c.nodeType === 3) out += c.data; else walk(c);
      }
    })(this);
    return out;
  },
  set: function (v) {
    this.childNodes = [];
    if (v !== "" && v !== null && v !== undefined) this.appendChild(new TextNode(v));
  },
});
Object.defineProperty(El.prototype, "innerHTML", {
  get: function () { return serialize(this); },
  set: function (h) { this.childNodes = []; var kids = parseHTML(String(h));
    for (var i = 0; i < kids.length; i++) this.appendChild(kids[i]); },
});
// a capture listener runs on the way down, before the target's own
// (keepKbTaps drops the click that would press a button twice)
El.prototype.addEventListener = function (t, fn, o) {
  var at = o === true || (o && o.capture) ? (this._cap = this._cap || {}) : this._on;
  (at[t] = at[t] || []).push(fn);
};
// new Event(...) + dispatchEvent, the way setKindField fires an edit as if typed
El.prototype.dispatchEvent = function (ev) { dispatch(this, ev.type, {}); return true; };
function Event(type, init) { this.type = type; this.bubbles = !!(init && init.bubbles); }
El.prototype.removeEventListener = function (t, fn) {
  var a = this._on[t] || []; var i = a.indexOf(fn); if (i >= 0) a.splice(i, 1);
};

function serialize(n) {
  var out = "";
  for (var i = 0; i < n.childNodes.length; i++) {
    var c = n.childNodes[i];
    if (c.nodeType === 3) { out += c.data; continue; }
    var tag = c.tagName.toLowerCase(), at = "";
    for (var k in c.attrs) at += " " + k + '="' + c.attrs[k] + '"';
    out += "<" + tag + at + ">";
    if (!VOID[tag]) out += serialize(c) + "</" + tag + ">";
  }
  return out;
}

/* ---------- selectors ---------- */
function parseCompound(s) {
  var c = { tag: null, id: null, cls: [], attrs: [], not: [] }, i = 0;
  while (i < s.length) {
    var ch = s[i], j;
    if (ch === "#") { j = i + 1; while (j < s.length && /[\w-]/.test(s[j])) j++; c.id = s.slice(i + 1, j); i = j; }
    else if (ch === ".") { j = i + 1; while (j < s.length && /[\w-]/.test(s[j])) j++; c.cls.push(s.slice(i + 1, j)); i = j; }
    else if (ch === "[") { j = s.indexOf("]", i);
      var m = /^([\w-]+)(?:=["']?([\s\S]*?)["']?)?$/.exec(s.slice(i + 1, j));
      c.attrs.push([m[1], m[2]]); i = j + 1; }
    else if (ch === ":") {
      j = i + 1; while (j < s.length && /[\w-]/.test(s[j])) j++;
      var pseudo = s.slice(i + 1, j);
      if (s[j] === "(") {
        var depth = 1, k = j + 1;
        while (k < s.length && depth) { if (s[k] === "(") depth++; else if (s[k] === ")") depth--; k++; }
        var inner = s.slice(j + 1, k - 1);
        if (pseudo === "not") c.not.push(parseCompound(inner));
        j = k;
      }
      i = j;
    }
    else { j = i; while (j < s.length && /[\w-]/.test(s[j])) j++;
      if (j === i) { i++; continue; }
      c.tag = s.slice(i, j).toUpperCase(); i = j; }
  }
  return c;
}
/* A selector is parsed once and kept: the walk below asks the same question of
   every node in the subtree, and re-parsing the string each time is what made a
   querySelectorAll over a few thousand nodes cost seconds. */
var __selCache = Object.create(null);
function parseSelector(sel) {
  var key = String(sel), hit = __selCache[key];
  if (hit) return hit;
  var groups = key.split(",").map(function (g) {
    return g.trim().split(/\s+/).map(parseCompound);
  });
  // a lone "#id": compared by id alone, and found through __ids
  var only = groups.length === 1 && groups[0].length === 1 ? groups[0][0] : null;
  if (only && only.id && !only.tag && !only.cls.length && !only.attrs.length && !(only.not || []).length)
    groups.id = only.id;
  __selCache[key] = groups;
  return groups;
}
function matchCompound(el, c) {
  if (!el || el.nodeType !== 1) return false;
  if (c.tag && el.tagName !== c.tag) return false;
  if (c.id && el.attrs.id !== c.id) return false;
  if (c.cls.length) {
    var pad = clsPad(el);
    for (var i = 0; i < c.cls.length; i++) if (pad.indexOf(" " + c.cls[i] + " ") < 0) return false;
  }
  for (var j = 0; j < c.attrs.length; j++) {
    var k = c.attrs[j][0], v = c.attrs[j][1];
    if (!el.hasAttribute(k)) return false;
    if (v !== undefined && el.getAttribute(k) !== v) return false;
  }
  for (var n = 0; n < (c.not || []).length; n++) if (matchCompound(el, c.not[n])) return false;
  return true;
}
function matchesSel(el, sel) { return matchGroups(el, parseSelector(sel)); }
// The walks below resolve the selector once and test every node against the
// parsed groups; even a cache hit per node was most of the suite's run time.
function matchGroups(el, groups) {
  if (groups.id) return el.attrs.id === groups.id;
  for (var g = 0; g < groups.length; g++) {
    var parts = groups[g];
    if (!matchCompound(el, parts[parts.length - 1])) continue;
    var node = el.parentNode, k = parts.length - 2, ok = true;
    while (k >= 0) {
      var found = false;
      while (node) {
        var hit = matchCompound(node, parts[k]);
        node = node.parentNode;
        if (hit) { found = true; break; }
      }
      if (!found) { ok = false; break; }
      k--;
    }
    if (ok) return true;
  }
  return false;
}
El.prototype.matches = function (s) { return matchesSel(this, s); };
El.prototype.closest = function (s) {
  var n = this;
  while (n && n.nodeType === 1) { if (matchesSel(n, s)) return n; n = n.parentNode; }
  return null;
};
// Node.contains: the node itself or one under it (the course's itinerary
// asks it of the focused field before it repaints)
El.prototype.contains = function (n) {
  for (; n; n = n.parentNode) {
    if (n === this) return true;
    if (n.parentNode && n.parentNode.childNodes.indexOf(n) < 0) return false;
  }
  return false;
};
// Node.isConnected: in the document (the chat's mounts are dropped once a
// dialog redrawn has taken their element away)
Object.defineProperty(El.prototype, "isConnected", { get: function () { return document.body.contains(this); } });
El.prototype.querySelectorAll = function (s) {
  var out = [], groups = parseSelector(s);
  (function walk(n) {
    for (var i = 0; i < n.childNodes.length; i++) {
      var c = n.childNodes[i];
      if (c.nodeType !== 1) continue;
      if (matchGroups(c, groups)) out.push(c);
      walk(c);
    }
  })(this);
  return out;
};
// stops at the first hit; collecting the whole subtree to throw it away was the
// bulk of the cost of a $("#id") lookup, and those happen constantly
El.prototype.querySelector = function (s) {
  var found = null, groups = parseSelector(s);
  if (groups.id) {
    var hit = idLookup(this, groups.id);
    if (hit !== undefined) return hit;
  }
  (function walk(n) {
    for (var i = 0; i < n.childNodes.length; i++) {
      var c = n.childNodes[i];
      if (c.nodeType !== 1) continue;
      if (matchGroups(c, groups)) { found = c; return true; }
      if (walk(c)) return true;
    }
    return false;
  })(this);
  return found;
};

/* ---------- html parser ---------- */
function parseHTML(html) {
  var root = new El("root"), stack = [root], i = 0;
  while (i < html.length) {
    var lt = html.indexOf("<", i);
    if (lt < 0) { addText(stack, html.slice(i)); break; }
    if (lt > i) addText(stack, html.slice(i, lt));
    if (html.substr(lt, 4) === "<!--") { var e = html.indexOf("-->", lt); i = e < 0 ? html.length : e + 3; continue; }
    if (html[lt + 1] === "!") { var e2 = html.indexOf(">", lt); i = e2 < 0 ? html.length : e2 + 1; continue; }
    var gt = lt + 1, q = 0;
    while (gt < html.length) {
      var ch = html[gt];
      if (ch === '"' || ch === "'") { q = q === 0 ? ch.charCodeAt(0) : (q === ch.charCodeAt(0) ? 0 : q); }
      else if (ch === ">" && q === 0) break;
      gt++;
    }
    var raw = html.slice(lt + 1, gt);
    i = gt + 1;
    if (raw[0] === "/") {
      var name = raw.slice(1).trim().toLowerCase();
      for (var s = stack.length - 1; s > 0; s--) {
        if (stack[s].tagName.toLowerCase() === name) { stack.length = s; break; }
      }
      continue;
    }
    var selfClose = /\/$/.test(raw);
    if (selfClose) raw = raw.slice(0, -1);
    var sp = raw.search(/[\s]/);
    var tag = (sp < 0 ? raw : raw.slice(0, sp)).toLowerCase();
    var el = new El(tag);
    if (sp > 0) {
      var ar = /([\w:-]+)(?:\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+)))?/g, m;
      var attrsrc = raw.slice(sp);
      while ((m = ar.exec(attrsrc))) {
        var v = m[3] !== undefined ? m[3] : m[4] !== undefined ? m[4] : m[5] !== undefined ? m[5] : "";
        el.attrs[m[1]] = decodeEnt(v);
      }
    }
    if (el.attrs.id !== undefined) idNote(el);
    if (el.attrs.disabled !== undefined) el.disabled = true;
    // a parsed style="" lands in .style, as in a browser: the list's rows are
    // built as one string, custom properties and all
    if (el.attrs.style) el.attrs.style.split(";").forEach(function (d) {
      var c = d.indexOf(":");
      if (c > 0) el.style.setProperty(d.slice(0, c).trim(), d.slice(c + 1).trim());
    });
    if (el.attrs.value !== undefined && el.tagName !== "OPTION") el._value = el.attrs.value;
    if (el.attrs.checked !== undefined) el.checked = true;
    stack[stack.length - 1].appendChild(el);
    if (!VOID[tag] && !selfClose) stack.push(el);
    // <style>/<script> bodies are raw text
    if (tag === "style" || tag === "script") {
      var close = html.toLowerCase().indexOf("</" + tag, i);
      if (close < 0) close = html.length;
      el.appendChild(new TextNode(html.slice(i, close)));
      i = html.indexOf(">", close) + 1;
      stack.pop();
    }
  }
  return root.childNodes.slice().map(function (n) { n.parentNode = null; return n; });
}
function addText(stack, t) {
  if (!t) return;
  stack[stack.length - 1].appendChild(new TextNode(decodeEnt(t)));
}

/* ---------- document / window ---------- */
var document = {
  body: new El("body"),
  documentElement: new El("html"),
  _on: {},
  _cap: {},
  createElement: function (t) { return new El(t); },
  createRange: function () { return { selectNodeContents: function () {} }; },
  execCommand: function () { return true; },
  // a capture listener on the document runs before the target's (the only
  // capture phase the page uses: chatSwShut's)
  addEventListener: function (t, fn, o) {
    var at = o === true || (o && o.capture) ? this._cap : this._on;
    (at[t] = at[t] || []).push(fn);
  },
  querySelector: function (s) { return this.body.querySelector(s); },
  querySelectorAll: function (s) { return this.body.querySelectorAll(s); },
  /* The pane marks its hits over the finished render's text nodes. It collects
     the whole walk up front before touching anything, so the nodes are gathered
     eagerly here too — a live walker would buy nothing. */
  createTreeWalker: function (root, show) {
    var want = show === undefined ? -1 : show, q = [];
    (function walk(n) {
      for (var i = 0; i < n.childNodes.length; i++) {
        var c = n.childNodes[i];
        if (want & (c.nodeType === 1 ? 1 : c.nodeType === 3 ? 4 : 0)) q.push(c);
        if (c.nodeType === 1) walk(c);
      }
    })(root);
    var at = -1;
    return {
      root: root, currentNode: root,
      nextNode: function () { this.currentNode = q[++at] || null; return this.currentNode; },
    };
  },
};
var NodeFilter = { SHOW_ALL: -1, SHOW_ELEMENT: 1, SHOW_TEXT: 4 };
document.activeElement = document.body;
document.body.dataset;   // force the proxy

function dispatch(target, type, extra) {
  var ev = Object.assign({
    type: type, target: target, defaultPrevented: false,
    preventDefault: function () { this.defaultPrevented = true; },
    stopPropagation: function () { this._stop = true; },
  }, extra || {});
  var cl = document._cap[type] || [];
  for (var c = 0; c < cl.length; c++) cl[c].call(document, ev);
  if (ev._stop) return ev;
  var path = [];
  for (var a = target; a && a.nodeType === 1; a = a.parentNode) path.unshift(a);
  for (var pi = 0; pi < path.length; pi++) {
    var pl = (path[pi]._cap && path[pi]._cap[type]) || [];
    for (var pj = 0; pj < pl.length; pj++) pl[pj].call(path[pi], ev);
    if (ev._stop) return ev;
  }
  var n = target;
  while (n && n.nodeType === 1) {
    var h = n["on" + type];
    if (typeof h === "function") h.call(n, ev);
    var ls = n._on[type] || [];
    for (var i = 0; i < ls.length; i++) ls[i].call(n, ev);
    if (ev._stop) return ev;
    n = n.parentNode;
  }
  var dl = document._on[type] || [];
  for (var j = 0; j < dl.length; j++) dl[j].call(document, ev);
  return ev;
}
function click(el, extra) { return dispatch(el, "click", extra); }
function input(el, val) { if (val !== undefined) el.value = val; return dispatch(el, "input", {}); }
function change(el, val) { if (val !== undefined) el.value = val; return dispatch(el, "change", {}); }
function key(k, extra) {
  var ev = Object.assign({ key: k, ctrlKey: false, metaKey: false, altKey: false,
    target: document.body, type: "keydown", defaultPrevented: false,
    preventDefault: function () { this.defaultPrevented = true; } }, extra || {});
  var ls = document._on.keydown || [];
  for (var i = 0; i < ls.length; i++) ls[i](ev);
  return ev;
}

var window = {
  _on: {},
  addEventListener: function (t, fn) { (this._on[t] = this._on[t] || []).push(fn); },
  isSecureContext: false,
  // the chat dock asks for a desk (min-width:900px, a fine pointer): TEST.desk
  matchMedia: function (q) { return { matches: /max-width:820px/.test(q) ? TEST.mobile : /hover:none/.test(q) ? !!TEST.touch : /min-width:900px/.test(q) ? !!TEST.desk : false }; },
};
var navigator = { clipboard: null };
var location = { protocol: "http:", origin: "http://127.0.0.1:8099", host: "127.0.0.1:8099",
                 pathname: "/", search: "", hash: "", href: "http://127.0.0.1:8099/" };
// A real stack, because Back and Forward are behaviour the page has to get
// right: a traversal restores that entry's url and state and then fires the
// events a browser would.  TEST.hashFirst flips their order — browsers have
// disagreed about it, so both orders get tested.
var history = {
  state: null,
  _st: [{ s: null, u: "/" }],
  _i: 0,
  pushState: function (s, t, u) {
    this._st.length = this._i + 1;               // a push drops the forward tail
    this._st.push({ s: s, u: typeof u === "string" ? u : this._st[this._i].u });
    this._i++;
    this.state = s;
    applyUrl(u);
    TEST.log.push("pushState");
  },
  replaceState: function (s, t, u) {
    this.state = s;
    this._st[this._i].s = s;
    if (typeof u === "string") this._st[this._i].u = u;
    applyUrl(u);
  },
  back: function () { TEST.log.push("history.back"); this._go(-1); },
  forward: function () { this._go(1); },
  go: function (d) { this._go(d || 0); },
  _go: function (d) {
    var j = this._i + d;
    if (j < 0 || j >= this._st.length || !d) return;
    this._i = j;
    var e = this._st[j], was = location.hash;
    this.state = e.s;
    applyUrl(e.u);
    var changed = location.hash !== was;
    var evs = [["popstate", { state: e.s }]];
    if (changed) evs[TEST.hashFirst ? "unshift" : "push"](["hashchange", {}]);
    for (var i = 0; i < evs.length; i++) winEvent(evs[i][0], evs[i][1]);
  },
};
function winEvent(type, extra) {
  var ls = (window._on[type] || []).slice();
  var ev = Object.assign({ type: type }, extra || {});
  for (var i = 0; i < ls.length; i++) ls[i](ev);
}
// The page's urls are paths now (./entry/123?q=…), so a push or a step
// moves the path and the query as well as the hash.
function applyUrl(u) {
  if (typeof u !== "string") return;
  var h = u.indexOf("#");
  location.hash = h < 0 ? "" : u.slice(h);
  var rest = h < 0 ? u : u.slice(0, h);
  if (rest === "") return;                       // "#…" alone: the hash only
  var q = rest.indexOf("?");
  var path = q < 0 ? rest : rest.slice(0, q);
  location.search = q < 0 ? "" : rest.slice(q);
  if (path !== "") location.pathname = path.charAt(0) === "/" ? path
    : location.pathname.replace(/[^\/]*$/, "") + path;
  location.href = location.origin + location.pathname + location.search + location.hash;
}
var performance = { now: function () { return Date.now(); } };
// QuickJS has console.log only. The page reports its boot timings through
// console.info; they are for a browser's devtools, so here they go nowhere.
if (!console.info) console.info = function () {};
function getSelection() { return { removeAllRanges: function () {}, addRange: function () {} }; }
function confirm(msg) { TEST.log.push("confirm: " + msg); return TEST.confirmAnswer; }
function alert(m) { TEST.log.push("alert: " + m); }
function btoa(s) {
  var C = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/", out = "";
  for (var i = 0; i < s.length; i += 3) {
    var a = s.charCodeAt(i), b = s.charCodeAt(i + 1), c = s.charCodeAt(i + 2);
    out += C[a >> 2] + C[((a & 3) << 4) | (isNaN(b) ? 0 : b >> 4)]
        + (isNaN(b) ? "=" : C[((b & 15) << 2) | (isNaN(c) ? 0 : c >> 6)])
        + (isNaN(c) ? "=" : C[c & 63]);
  }
  return out;
}

function atob(s) {
  var C = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/", out = "", n = 0, bits = 0;
  s = String(s).replace(/=+$/, "");
  for (var i = 0; i < s.length; i++) {
    var v = C.indexOf(s[i]);
    if (v < 0) throw new Error("atob: not base64");
    n = (n << 6) | v; bits += 6;
    if (bits >= 8) { bits -= 8; out += String.fromCharCode((n >> bits) & 255); }
  }
  return out;
}

/* ---------- missing standard bits ---------- */
function TextEncoder() {}
TextEncoder.prototype.encode = function (s) {
  var n = 0;
  for (var i = 0; i < s.length; i++) {
    var c = s.codePointAt(i);
    if (c > 0xffff) { i++; n += 4; }
    else if (c > 0x7ff) n += 3;
    else if (c > 0x7f) n += 2;
    else n += 1;
  }
  var a = new Uint8Array(n);
  a.length; return a;
};
function URLSearchParams(init) {
  this._ = [];
  if (typeof init === "string" && init) {
    var parts = init.replace(/^[?#]/, "").split("&");
    for (var i = 0; i < parts.length; i++) {
      if (!parts[i]) continue;
      var e = parts[i].indexOf("=");
      var k = e < 0 ? parts[i] : parts[i].slice(0, e);
      var v = e < 0 ? "" : parts[i].slice(e + 1);
      this._.push([dec(k), dec(v)]);
    }
  } else if (init && typeof init === "object") {
    // the record form — new URLSearchParams({a: 1, b: 2}) — which is how the
    // voice code builds the Deepgram stream URL
    for (var k2 in init) if (Object.prototype.hasOwnProperty.call(init, k2)) {
      this._.push([String(k2), String(init[k2])]);
    }
  }
}
function dec(s) { try { return decodeURIComponent(String(s).replace(/\+/g, " ")); } catch (e) { return s; } }
function enc(s) { return encodeURIComponent(String(s)).replace(/%20/g, "+"); }
URLSearchParams.prototype.get = function (k) {
  for (var i = 0; i < this._.length; i++) if (this._[i][0] === k) return this._[i][1];
  return null;
};
URLSearchParams.prototype.getAll = function (k) {
  var out = [];
  for (var i = 0; i < this._.length; i++) if (this._[i][0] === k) out.push(this._[i][1]);
  return out;
};
URLSearchParams.prototype.has = function (k) { return this.get(k) !== null; };
URLSearchParams.prototype.append = function (k, v) { this._.push([k, String(v)]); };
URLSearchParams.prototype.set = function (k, v) {
  for (var i = 0; i < this._.length; i++) if (this._[i][0] === k) { this._[i][1] = String(v); return; }
  this._.push([k, String(v)]);
};
URLSearchParams.prototype.toString = function () {
  return this._.map(function (p) { return enc(p[0]) + "=" + enc(p[1]); }).join("&");
};

var localStorage = (function () {
  // a login stored, as on any device past its first open: with none the page
  // boots to the Connection dialog and asks the server nothing (bootGo)
  var m = { "lcars.cfg": JSON.stringify({ user: "test", pass: "test" }) };
  return {
    getItem: function (k) { return m[k] === undefined ? null : m[k]; },
    setItem: function (k, v) { m[k] = String(v); },
    removeItem: function (k) { delete m[k]; },
    clear: function () { m = {}; },
    _all: function () { return m; },
  };
})();

/* A browser never scrolls above the top: scrollTop is clamped at 0. The list
   moves its scrollTop by what goes in above the window, and the shim's took
   it to -10220 in the rail's scroll-up test, run as of a 1st of the month.
   Not clamped at the bottom: the shim has no layout to know where that is. */
Object.defineProperty(El.prototype, "scrollTop", { configurable: true,
  get: function () { return this._scrollTop; },
  set: function (v) { this._scrollTop = Math.max(0, +v || 0); } });

/* ---------- virtual timers ---------- */
var __timers = [], __seq = 1, __now = 0;
function setTimeout(fn, ms) { __timers.push({ id: __seq, at: __now + (ms || 0), fn: fn }); return __seq++; }
function clearTimeout(id) { __timers = __timers.filter(function (t) { return t.id !== id; }); }
function setInterval() { return 0; }
function clearInterval() {}
function runTimers(advance) {
  __now += advance === undefined ? 5000 : advance;
  for (var guard = 0; guard < 500; guard++) {
    var due = [], keep = [];
    for (var k = 0; k < __timers.length; k++) {
      (__timers[k].at <= __now ? due : keep).push(__timers[k]);
    }
    if (!due.length) return;
    due.sort(function (a, b) { return a.at - b.at; });   // only what actually fires
    __timers = keep;
    for (var i = 0; i < due.length; i++) { try { due[i].fn(); } catch (e) { TEST.fails.push("timer: " + e); } }
  }
}
async function pump(n) {
  for (var i = 0; i < (n || 60); i++) await Promise.resolve();
}
async function settle(rounds) {
  for (var i = 0; i < (rounds || 40); i++) { await pump(30); runTimers(); }
}
// The reader's backlinks and related rows arrive a few milliseconds a frame
// (renderExtras); a frame here is a timer round, so run rounds until it is done.
async function drainExtras() {
  for (var i = 0; i < 5000 && extrasJob; i++) { await pump(2); runTimers(20); }
}

/* ---------- assertions ---------- */
function ok(cond, msg) {
  TEST.asserts++;
  if (!cond) { TEST.fails.push(msg); console.log("  FAIL " + msg); }
}
function eq(a, b, msg) {
  ok(String(a) === String(b), msg + "  (got " + JSON.stringify(String(a)).slice(0, 220) +
     " want " + JSON.stringify(String(b)).slice(0, 220) + ")");
}
// A check a later slice makes pass (ui-rules.md, "Every rule ships with its
// check"): it fails today and says so without failing the run; once it
// holds it fails (XPASS), so the slice turns it into an ok().
function xfail(cond, msg, until) {
  TEST.asserts++;
  if (cond) {
    TEST.fails.push(msg + " (XPASS)");
    console.log("  FAIL XPASS " + msg + ": it holds now, make it an ok() (" + until + ")");
  } else console.log("  xfail " + msg + " (expected to fail until " + until + ")");
}
// the whole url the page has written: its path, query and hash
function locUrl() { return location.pathname + location.search + location.hash; }
function has(hay, needle, msg) {
  ok(String(hay).indexOf(needle) >= 0, msg + "  (missing " + JSON.stringify(needle) +
     " in " + JSON.stringify(String(hay)).slice(0, 260) + ")");
}

var Intl = { DateTimeFormat: function () {
  return { resolvedOptions: function () { return { timeZone: "Europe/Helsinki" }; } };
} };

// bounded wait: a suite that never finishes must report, not hang the run
async function waitFlag(name) {
  for (var i = 0; i < 4000; i++) {
    if (globalThis[name]) return true;
    await pump(20);
    if (i % 200 === 0) runTimers(10);
  }
  console.log("TIMED OUT waiting for " + name);
  TEST.fails.push("timed out waiting for " + name);
  return false;
}
window.innerHeight = 900;
window.innerWidth = 1400;
