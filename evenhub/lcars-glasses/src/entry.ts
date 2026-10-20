// The single entry point index.html loads.
//
// Both halves of the app live behind this import. main.ts drives the glasses
// and boots itself only when the Even App is hosting the page; settings.ts
// renders the phone form and mounts whenever #settings is in the document. In
// the Even App both are true at once, which is the intended arrangement: the
// handset shows the form, the glasses show the journal.
import "./main";
import "./settings";
