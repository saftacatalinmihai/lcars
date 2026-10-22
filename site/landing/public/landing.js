// The landing page's one script: the signup forms, and the deletion address.
// Without it the forms still work (a plain POST, answered by a redirect back
// with ?signup=<outcome>, said below); with it a tap shows "Sending…" in the
// same frame, then the thanks or the error where the button is, the text
// left in the fields to fix and send again.
"use strict";

const SAY = {
  ok: "Thanks - you are on the list. We will write once, when hosted LCARS opens.",
  email_missing: "Enter your email.",
  email_invalid: "That email does not look right.",
  use_too_long: "Keep the line to 280 characters.",
  consent_missing: "Tick the box so we may write to you.",
  rate: "Too many tries from here. Try again in a few minutes.",
  offline: "Could not reach the server. Check the connection and try again.",
  server: "Something went wrong on our side. Try again.",
};

function say(form, cls, text) {
  const st = form.querySelector(".status");
  st.className = "status " + cls;
  st.textContent = text;
}

// The same checks as the worker's, so a typo is caught before a round trip;
// the worker checks again whatever this says.
function check(form) {
  const email = form.email.value.trim();
  form.classList.remove("bad-email", "bad-consent");
  if (!email) return (form.classList.add("bad-email"), "email_missing");
  if (email.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@.]{2,}$/.test(email)) return (form.classList.add("bad-email"), "email_invalid");
  if (form.use.value.trim().length > 280) return "use_too_long";
  if (!form.consent.checked) return (form.classList.add("bad-consent"), "consent_missing");
  return "";
}

async function send(form) {
  const btn = form.querySelector(".go"), label = btn.querySelector(".go-t");
  const bad = check(form);
  if (bad) {
    say(form, "err", SAY[bad]);
    (bad === "consent_missing" ? form.consent : bad === "use_too_long" ? form.use : form.email).focus();
    return;
  }
  form.classList.remove("done");
  form.classList.add("sending");
  btn.disabled = true;
  label.textContent = "Sending…";
  say(form, "", "Sending…");
  let outcome = "server";
  try {
    const r = await fetch(form.action, {
      method: "POST",
      headers: { "content-type": "application/json", accept: "application/json" },
      body: JSON.stringify({
        email: form.email.value,
        use: form.use.value,
        consent: form.consent.checked,
        website: form.website.value,
      }),
    });
    const j = await r.json().catch(() => ({}));
    outcome = j.ok ? "ok" : j.error || "server";
    if (!j.ok && j.message && !SAY[outcome]) SAY[outcome] = j.message;
  } catch {
    outcome = "offline";
  }
  form.classList.remove("sending");
  btn.disabled = false;
  if (outcome === "ok") {
    form.classList.add("done");
    label.textContent = "On the list ✓";
    say(form, "ok", SAY.ok);
    // every form on the page says it: the second one is not asked again
    for (const f of document.querySelectorAll(".signup")) if (f !== form) markDone(f);
  } else {
    label.textContent = "Try again";
    say(form, "err", SAY[outcome] || SAY.server);
  }
}

function markDone(form) {
  form.classList.add("done");
  form.querySelector(".go-t").textContent = "On the list ✓";
  say(form, "ok", SAY.ok);
}

for (const form of document.querySelectorAll(".signup")) {
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!form.classList.contains("sending")) send(form);
  });
}

// A form sent without this script comes back as /?signup=<outcome>#join.
const back = new URLSearchParams(location.search).get("signup");
if (back) {
  const first = document.querySelector(".signup");
  if (back === "ok") for (const f of document.querySelectorAll(".signup")) markDone(f);
  else say(first, "err", SAY[back] || SAY.server);
  history.replaceState(null, "", location.pathname + location.hash);
}

// The deletion address is lcars@ the site's own zone, made here rather than
// written in the page, so the page names no host of its own and works on
// any (a preview, the custom domain).
const host = location.hostname.split(".");
if (host.length >= 2 && !/^\d+$/.test(host[host.length - 1])) {
  const addr = "lcars@" + host.slice(-2).join(".");
  for (const a of document.querySelectorAll("a.contact")) {
    a.href = "mailto:" + addr + "?subject=" + encodeURIComponent("Delete me from the LCARS waitlist");
    a.textContent = addr;
  }
}

// The explainer: a poster and a play button until it is tapped, so a phone
// pulls none of its 23 MB on load. The tap swaps in the video, already
// showing the poster, and starts it with sound: inside the tap, so iOS
// allows the sound (a play() started later would be refused or muted).
// The swap is the tap's feedback; the player's own spinner the rest.
const fig = document.querySelector(".player[data-video]");
if (fig && fig.dataset.video) {
  fig.querySelector("a.play").addEventListener("click", (e) => {
    e.preventDefault();
    const v = document.createElement("video");
    v.controls = true;
    v.playsInline = true;
    v.preload = "auto";
    v.poster = fig.querySelector("img").src;
    v.src = fig.dataset.video;
    if (fig.dataset.captions) {
      const t = document.createElement("track");
      t.kind = "captions"; t.srclang = "en"; t.label = "English"; t.src = fig.dataset.captions;
      v.appendChild(t);
    }
    fig.classList.add("playing");
    fig.replaceChildren(v);
    v.play().catch(() => {}); // refused: the controls are there to press
  });
}

// The feature rows' loops: silent, muted, inline. Each is its first frame as
// a picture until the row is near the screen, then a video that plays only
// while it is on it - so a phone loads a loop only for a row it reaches, and
// decodes none it has scrolled past. Reduced motion or Save-Data: the
// pictures stay.
const still = matchMedia("(prefers-reduced-motion: reduce)").matches || (navigator.connection && navigator.connection.saveData);
const loops = document.querySelectorAll(".shots[data-loop]");
if (!still && loops.length && "IntersectionObserver" in window) {
  const io = new IntersectionObserver((seen) => {
    for (const s of seen) {
      let v = s.target.querySelector("video");
      if (!s.isIntersecting) { if (v) v.pause(); continue; }
      if (!v) {
        const img = s.target.querySelector("img");
        v = document.createElement("video");
        v.muted = true; v.loop = true; v.playsInline = true; v.autoplay = true;
        v.setAttribute("muted", ""); v.setAttribute("aria-label", img.alt);
        v.width = img.width; v.height = img.height; v.poster = img.src;
        v.src = s.target.dataset.loop;
        s.target.replaceChildren(v);
      }
      v.play().catch(() => {}); // refused (Low Power Mode): the poster stays
    }
  }, { rootMargin: "200px 0px" });
  for (const l of loops) io.observe(l);
}
