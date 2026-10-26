// Plausible's queue and init stub, from its snippet (plausible.io's
// script-update-guide, October 2025): calls made before its script has
// loaded are queued, and init() is what the per-site pa-*.js script waits
// for. It is a file, not the snippet's inline script, because the page's CSP
// has no 'unsafe-inline'. Uploaded, and named in the pages, only when
// LCARS_LANDING_PLAUSIBLE is set at a deploy (deploy.sh); the preview and a
// self-hoster's copy load none of it.
window.plausible =
  window.plausible ||
  function () {
    (plausible.q = plausible.q || []).push(arguments);
  };
plausible.init =
  plausible.init ||
  function (i) {
    plausible.o = i || {};
  };
plausible.init();
