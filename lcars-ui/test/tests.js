/* ===================== tests ===================== */

/* Answer the themed confirm that some pending promise is waiting on. The
   discard prompt (a new entry's, and a reload's) is still the browser's own and is
   answered with TEST.confirmAnswer; everything else — delete, the concurrent
   edit — now asks through lcarsConfirm and has to be clicked like a user
   would. Returns false, loudly, if no dialog was actually up: a test that
   expected a question and got none has found something. */
async function answerDialog(yes) {
  await settle(3);
  var b = $(yes ? "#lcOk" : "#lcNo");
  // the panel keeps the last dialog's markup until the next one replaces it,
  // so the buttons alone prove nothing — the overlay has to actually be up
  if (!b || !$("#ov").classList.contains("on")) {
    TEST.fails.push("expected a themed confirm, found none");
    console.log("  FAIL expected a themed confirm, found none");
    return false;
  }
  click(b);
  await settle(3);
  return true;
}
/* A row of the suite's own, through the fake API, for a check that needs the
   journal to hold something: a task line, a long body, two titles nobody else
   carries, a day with several entries. The fixture is the live journal's
   newest rows, so what it holds changes every day, and a check that leaned
   on it failed on the day's data rather than on the page (2026-10-13, twice).
   Written just now, so it is this month's and today's; unplant() takes it out
   of the list and the fake database again, since later sections count the
   journal's top rows. */
async function plant(fields) {
  var at = fmtUtc(new Date());
  var r = await api("/entries", { method: "POST",
    body: Object.assign({ kind: "personal_log", created_at_utc: at }, fields) });
  insertRow(await api("/entries/" + r.id));
  return st.byId.get(r.id);
}
function unplant(e) {
  var i = st.all.indexOf(e);
  if (i >= 0) st.all.splice(i, 1);
  st.byId.delete(e.id);
  DB = DB.filter(function (r) { return r.id !== e.id; });
  if (st.sel === e) st.sel = null;
  st.bodyGen++;
  fillKinds();
  refresh();
}
// The fake clock jumps 5s a round, which would autosave under every test that
// leaves a form dirty; autosave is off except in the tests of it (suite C).
autosaveMs = 0;
(async function () {
  await settle(30);

  /* ---------- boot ---------- */
  console.log("\n-- boot --");
  eq(st.all.length, FIX.length, "every fixture row streamed in");
  ok(!st.loading, "loading finished");
  ok(st.view.length > 0, "view is populated");
  ok($("#list").querySelectorAll(".item").length > 0, "rows rendered");
  has($("#hstat").innerHTML, "cap live", "header shows the live capsule");

  /* ---------- the crew's entries, hidden by default ---------- */
  console.log("-- crew entries: hidden unless asked for --");
  var cwTop = st.all.reduce(function (m, e) { return Math.max(m, e.id); }, 0);
  var cwMk = function (n, kind) {
    var at = new Date(Date.now() - n * 1000).toISOString().slice(0, 19).replace("T", " ");
    return { id: cwTop + n, kind: kind, title: "zebracrew " + kind, content: "zebracrew\n\n- TODO zebracrew " + kind,
             created_at_utc: at, last_modified_at_utc: at, deleted: 0, done_bool: 0, content_length: 30 };
  };
  var cwRows = [cwMk(1, "crew_ops"), cwMk(2, "crew_inbox"), cwMk(3, "no1_log"), cwMk(4, "task_no1"),
                cwMk(5, "task_crew"), cwMk(6, "crew_some_future_role")];
  var cwOwn = cwMk(7, "personal_log");
  cwRows.concat([cwOwn]).forEach(function (r) { st.all.unshift(r); st.byId.set(r.id, r); });
  var cwIn = function (r) { return st.view.indexOf(r) >= 0; };
  var cwNone = function () { return cwRows.every(function (r) { return !cwIn(r); }); };
  var cwAll = function () { return cwRows.every(cwIn); };
  ok(!crewShown(), "a fresh device hides the crew's entries");
  eq($("#bCrewShow").textContent, "crew entries hidden", "the Filters view says so");
  eq($("#bCrewShow").getAttribute("aria-pressed"), "false", "and its button is not pressed");
  ok(["crew_x", "no1_log", "task_no1", "task_crew", "task_crew_ops"].every(crewWritten) &&
     !["personal_log", "task", "task_personal", "crewmate", "no1"].some(crewWritten),
     "crew_*, no1_*, task_crew* and task_no1 are the crew's; nothing else is");
  refresh();
  ok(cwNone() && cwIn(cwOwn), "the list holds the captain's own entry and none of the crew's");
  $("#q").value = "zebracrew"; refresh();
  eq(st.view.map(function (e) { return e.id; }).join(","), String(cwOwn.id), "a search finds only his own");
  $("#q").value = ""; refresh();
  var cwDay = calIndex().get(dayKey(cwOwn.created_at_utc)) || [];
  ok(cwDay.indexOf(cwOwn) >= 0 && cwRows.every(function (r) { return cwDay.indexOf(r) < 0; }),
     "the calendar and the day view leave them out too");
  ok(!cwRows.some(taskNarrow().test) && taskNarrow().test(cwOwn), "and so does the task board");
  var cwStat = statScopeFor(false).src || st.all;
  ok(cwStat.indexOf(cwOwn) >= 0 && cwRows.every(function (r) { return cwStat.indexOf(r) < 0; }),
     "and the statistics of the whole journal");
  setKinds(["crew_ops"]); refresh();
  ok(cwIn(cwRows[0]), "a crew kind picked by name is shown: asking for it means it");
  setKinds([]); refresh();
  ok(crewReports().get("crew_ops").indexOf(cwRows[0]) >= 0 &&
     crewReports().get("crew_inbox").indexOf(cwRows[1]) >= 0, "the crew reports view still lists them");
  chatBadge();
  has($("#bChat").textContent, "\u00b7", "and No.1's open question is still counted on the Chats button");
  click($("#bCrewShow")); await settle(2);
  ok(crewShown() && cwAll() && cwIn(cwOwn), "one tap shows every crew entry");
  eq($("#bCrewShow").getAttribute("aria-pressed"), "true", "the button says it is on");
  eq(lsGetStr(CREW_SHOW_KEY), "1", "the choice is kept in localStorage");
  ok(!activeFilters(), "showing them is not counted as a filter narrowing the list");
  clearFilters();
  applyQS(""); refresh();
  ok(crewShown() && cwAll(), "and Clear, a reset or a link do not undo it");
  setCrew(false);
  ok(!crewShown() && cwNone() && lsGetStr(CREW_SHOW_KEY) === "", "a second tap hides them again, and that is kept");
  eq(vMatch(vWords("show crew entries"), 0).cmd.say, "show crew entries", "\u201cshow crew entries\u201d is an order");
  eq(vMatch(vWords("only my entries"), 0).cmd.say, "hide crew entries", "\u201conly my entries\u201d hides them");
  vMatch(vWords("show crew entries"), 0).cmd.fn(); await settle(2);
  ok(crewShown(), "the order shows them");
  vMatch(vWords("hide crew entries"), 0).cmd.fn(); await settle(2);
  ok(!crewShown(), "and the other hides them");
  cwRows.concat([cwOwn]).forEach(function (r) { st.all.splice(st.all.indexOf(r), 1); st.byId.delete(r.id); });
  // the rest of the suite was written for a list that holds every live row
  setCrew(true);

  /* ---------- 1.2 kind colours ---------- */
  console.log("-- kind colour --");
  eq(kindColor("personal_log"), kindColor("personal_log"), "kind colour is stable");
  ok(KIND_COLORS.indexOf(kindColor("anything")) >= 0, "colour comes from the palette");
  var row = $("#list").querySelector(".item");
  ok(row.style.getPropertyValue("--k"), "row carries its kind colour");

  /* ---------- 1.3 relative stamps ---------- */
  console.log("-- relative stamps --");
  var nowUtc = new Date().toISOString().slice(0, 19).replace("T", " ");
  has(relStamp(nowUtc), "today", "today reads as today");
  // noon of the calendar day before, not 24 hours ago: just after midnight on
  // the day after the clocks go forward (a 23-hour day), 24 hours back is two
  // days back, and this failed (as of 2026-03-30 00:30, UTC+3)
  var yD = new Date(); yD.setDate(yD.getDate() - 1); yD.setHours(12, 0, 0, 0);
  var yUtc = yD.toISOString().slice(0, 19).replace("T", " ");
  has(relStamp(yUtc), "yesterday", "yesterday reads as yesterday");
  var oldUtc = "2020-03-04 10:11:12";
  eq(relStamp(oldUtc), localOf(oldUtc), "anything old keeps the absolute form");

  /* ---------- created_at picker ----------
     Every control is clicked through its real listener: the −15m/−1h chips
     once went dead because the helper they call was deleted, and only the
     click path notices a missing function. */
  console.log("-- created_at picker --");
  var pickBase = "2026-03-04 10:30:00";
  var chipOf = function (off) {
    var bs = $("#dt_chips").querySelectorAll("button");
    for (var i = 0; i < bs.length; i++) if (bs[i].dataset.off === off) return bs[i];
    return null;
  };
  var chipCases = [["-15", "2026-03-04 10:15:00"], ["-60", "2026-03-04 09:30:00"],
                   ["-180", "2026-03-04 07:30:00"], ["-1440", "2026-03-03 10:30:00"]];
  for (var ci = 0; ci < chipCases.length; ci++) {
    $("#e_created_at_utc").value = pickBase;
    var chip = chipOf(chipCases[ci][0]);
    ok(chip, "chip " + chipCases[ci][0] + " exists");
    if (chip) click(chip);
    eq($("#e_created_at_utc").value, chipCases[ci][1],
       "chip " + chipCases[ci][0] + " moves created_at back");
  }
  $("#e_created_at_utc").value = pickBase;
  click($("#dt_dm"));
  // calendar-day step keeps the local wall clock; with no DST edge on
  // 3 Mar in any zone the fixture runs in, that is exactly −24h of UTC too
  eq($("#e_created_at_utc").value, "2026-03-03 10:30:00", "−1d steps back a day");
  click($("#dt_dp"));
  eq($("#e_created_at_utc").value, pickBase, "+1d steps forward again");
  var nowBefore = Date.now();
  click(chipOf("now"));
  var nowSet = parseUtc($("#e_created_at_utc").value);
  ok(nowSet && Math.abs(nowSet.getTime() - nowBefore) < 5000, "'now' chip stamps the current time");
  var fwdCases = [["15", "2026-03-04 10:45:00"], ["60", "2026-03-04 11:30:00"],
                  ["180", "2026-03-04 13:30:00"], ["1440", "2026-03-05 10:30:00"]];
  for (ci = 0; ci < fwdCases.length; ci++) {
    $("#e_created_at_utc").value = pickBase;
    chip = chipOf(fwdCases[ci][0]);
    ok(chip, "chip +" + fwdCases[ci][0] + " exists");
    if (chip) click(chip);
    eq($("#e_created_at_utc").value, fwdCases[ci][1],
       "chip +" + fwdCases[ci][0] + " moves created_at forward");
  }

  /* The fine slider: minutes around the time as it was, an hour either way,
     and its middle is always the original. The wheels over the readout jump
     to any hour or minute of the day. */
  console.log("-- picker: fine slider and the readout's wheels --");
  $("#e_created_at_utc").value = pickBase;
  syncPickers();
  eq(Number($("#dt_fine").value), 0, "the fine slider starts in the middle");
  var fineAt = function (x) { input($("#dt_fine"), String(x)); return $("#e_created_at_utc").value; };
  eq(fineAt(13), "2026-03-04 10:31:00", "a little right of centre is a minute later");
  eq(fineAt(-29), "2026-03-04 10:25:00", "left of it, minutes earlier");
  eq(fineAt(-100), "2026-03-04 09:30:00", "the left end is an hour back");
  eq(fineAt(100), "2026-03-04 11:30:00", "the right end an hour on");
  has($("#dt_fineread").textContent, "+1h from", "the readout says how far from where");
  eq(fineAt(0), pickBase, "and the middle is the original again");
  eq($("#dt_fineread").textContent, "", "with nothing to say");
  for (var fx = -100, mono = true, prev = -1e9; fx <= 100; fx++) {
    var fm = fineOff(fx);
    if (fm < prev) mono = false;
    prev = fm;
  }
  ok(mono, "the scale never runs backwards");
  fineAt(40);
  click(chipOf("60"));
  eq(Number($("#dt_fine").value), 0, "a chip re-centres the fine slider on the new time");
  $("#e_created_at_utc").value = pickBase;
  syncPickers();
  var lh = parseUtc(pickBase).getHours();
  $("#dt_hh").value = String((lh + 5) % 24);
  dispatch($("#dt_hh"), "change", {});
  var moved = parseUtc($("#e_created_at_utc").value);
  eq(moved.getHours(), (lh + 5) % 24, "the hour wheel jumps to that hour");
  eq(moved.getMinutes(), parseUtc(pickBase).getMinutes(), "keeping the minutes");
  $("#dt_mm").value = "7";
  dispatch($("#dt_mm"), "change", {});
  moved = parseUtc($("#e_created_at_utc").value);
  eq(moved.getMinutes(), 7, "the minute wheel sets the minutes");
  eq(moved.getHours(), (lh + 5) % 24, "keeping the hour");
  eq($("#dt_mmv").textContent, "07", "and the readout shows it");
  setClean();

  /* start_date / end_date wear the same picker, plus a clear chip, and a
     blank one reads as unscheduled rather than unparseable. */
  console.log("-- start/end pickers --");
  var spanChip = function (k, off) {
    var bs = $("#" + k + "_chips").querySelectorAll("button");
    for (var i = 0; i < bs.length; i++) if (bs[i].dataset.off === off) return bs[i];
    return null;
  };
  $("#e_start_date").value = ""; $("#e_end_date").value = "";
  syncPickers();
  eq($("#sd_hint").textContent, "unscheduled", "a blank start reads as unscheduled");
  ok(!chipOf("clear"), "created_at has no clear chip");
  $("#e_start_date").value = pickBase;
  click(spanChip("sd", "60"));
  eq($("#e_start_date").value, "2026-03-04 11:30:00", "+1h moves the start forward");
  click(spanChip("sd", "-15"));
  eq($("#e_start_date").value, "2026-03-04 11:15:00", "−15m moves it back");
  click(spanChip("ed", "60"));
  eq($("#e_end_date").value, "2026-03-04 12:15:00", "+1h on a blank end counts from the start");
  has($("#ed_hint").textContent, "1h", "the end's hint gives the duration");
  click($("#ed_dm"));
  has($("#ed_hint").textContent, "ends before it starts", "a backwards range is named");
  click(spanChip("ed", "clear"));
  eq($("#e_end_date").value, "", "clear blanks the end");
  click(spanChip("sd", "clear"));
  eq($("#e_start_date").value, "", "clear blanks the start");
  setClean();

  /* ---------- 1.5 word + byte count ---------- */
  console.log("-- counts --");
  $("#content").value = "one two three\nfour";
  countContent();
  has($("#clen").textContent, "4 words", "words counted");
  has($("#clen").textContent, "18 bytes", "bytes counted");

  /* ---------- 1.7 slash regex ---------- */
  console.log("-- slash syntax --");
  ok(slashQuery("/srv/") === null, "a literal path is not a regex");
  ok(slashQuery("/s.v/") !== null, "a metacharacter makes it a regex");
  ok(slashQuery("/srv/i").ci, "the i flag is honoured");
  ok(slashQuery("/srv/ ") === null, "a trailing space opts out");
  $("#q").value = "/^woke.*up/";
  var mm = buildMatcher();
  ok(mm && mm.re.source === "^woke.*up", "slashes stripped for the regex");
  has($("#qnote").textContent, "regex", "the switch is announced");
  $("#q").value = "";
  refresh();

  /* ---------- 1.10 empty state ---------- */
  console.log("-- empty state --");
  $("#q").value = "zzzzz-nothing-matches-this-zzzzz";
  refresh();
  eq(st.view.length, 0, "nothing matches");
  has($("#list").innerHTML, "no records found", "LCARS empty state");
  ok($("#bClearF"), "clear-filters button offered");
  ok($("#bNewQ"), "a search that found nothing offers to create it");
  $("#q").value = "\"zzzzz nothing\"";
  refresh();
  has($("#bNewQ").textContent, "zzzzz nothing", "the offer names the phrase, quotes dropped");
  var kindsBefore = st.kinds.slice();
  setKinds(["task"]);
  refresh();
  has($("#bNewQ").textContent, "task", "the offer names the one kind filtered to");
  click($("#bNewQ"));
  ok(st.isNew, "the offer opens a new entry");
  eq($("#e_head").value, "zzzzz nothing", "titled with the search");
  eq(formValues().kind, "task", "in the one kind filtered to");
  setKinds(kindsBefore);
  setClean();
  closeEditor();
  $("#q").value = "/zz.zz/";
  refresh();
  ok(!$("#bNewQ"), "a regex is not offered as a title");
  $("#q").value = "zzzzz-nothing-matches-this-zzzzz";
  refresh();
  click($("#bClearF"));
  ok(st.view.length > 0, "clearing filters brings the list back");
  eq($("#q").value, "", "the query was cleared too");

  /* ---------- the LCARS badge resets the view ---------- */
  console.log("-- the badge resets the view --");
  var fullN = st.view.length;
  $("#q").value = "woke";
  $("#fSort").value = "len:desc";
  $("#scope").value = "title";
  $("#fCase").checked = true;
  setSeg("#mode", "regex");
  st.otd = true;
  refresh();
  $("#list").scrollTop = 300;
  click($(".brand"));
  eq($("#q").value, "", "the search is emptied");
  eq($("#fSort").value, "created:desc", "the sort goes back to newest first");
  eq($("#scope").value, "all", "and the scope to everything");
  ok(!$("#fCase").checked && segVal("#mode") === "text", "the search options go too");
  ok(!st.otd, "on-this-day is off");
  eq(st.view.length, fullN, "the whole journal is listed");
  eq($("#list").scrollTop, 0, "from the top");
  var rUndo = $("#toast").querySelector("button");
  ok(rUndo && rUndo.textContent === "Undo", "and it can be undone");
  click(rUndo);
  ok($("#q").value === "woke" && $("#fSort").value === "len:desc" && $("#fCase").checked &&
     segVal("#mode") === "regex" && st.otd, "Undo puts every setting back");
  applyQS(""); refresh();
  $("#list").scrollTop = 300;
  click($(".brand"));
  eq($("#list").scrollTop, 0, "an unfiltered list still goes back to the top");

  /* ---------- 3.2 kind chips ---------- */
  console.log("-- kind chips --");
  /* The filter is the editor's quick row: the first KIND_QUICK kinds by
     kindRows' ranking, then a "more" chip that is the K picker. Check that
     where the fixture puts us, then pin the data down to a handful of kinds
     that all have live rows and test the chips deliberately. */
  var allRows = st.all.slice();
  var fixKinds = kindRows().kinds;
  var fixChips = $("#kindchips").querySelectorAll(".kc[data-k]");
  eq(fixChips.length, Math.min(fixKinds.length, KIND_QUICK), "the top kinds get a chip");
  eq(fixChips[0].dataset.k, kindVal(fixKinds[0]), "in kindRows' order");
  var fixMore = $("#kindchips").querySelector(".kcmore");
  ok(fixKinds.length > KIND_QUICK ? !!fixMore : !fixMore, "and the rest are behind \"more\"");
  // the busiest kinds, so "a second kind with live entries" below is never a coin toss
  var liveBy = {};
  allRows.forEach(function (e) {
    if (e.deleted || !e.kind) return;
    liveBy[e.kind] = (liveBy[e.kind] || 0) + 1;
  });
  var keep = Object.keys(liveBy).sort(function (a, b) { return liveBy[b] - liveBy[a]; }).slice(0, 6);
  st.all = allRows.filter(function (e) { return keep.indexOf(e.kind) >= 0; });
  fillKinds();          // refresh() does not rebuild the picker; only a load does
  refresh();

  var chips = $("#kindchips").children;
  ok(chips.length > 1, "chips rendered (" + chips.length + ")");
  // whichever kind the fixture happens to lead with: naming one meant the suite
  // broke the day an import pushed it out of the newest rows
  var pk = st.view[0].kind, pl = null;
  for (var i = 0; i < chips.length; i++) if (chips[i].dataset.k === pk) pl = chips[i];
  ok(pl, pk + " has a chip");
  click(pl);
  eq(st.kinds.join(","), pk, "chip sets the filter");
  ok(st.view.every(function (e) { return e.kind === pk; }), "view is only that kind");
  ok(pl.classList.contains("on"), "chip shows as active");
  click(pl);
  eq(st.kinds.length, 0, "a second click clears it");

  /* ---------- 3.2b several kinds at once ---------- */
  console.log("-- multi-kind filter --");
  var kv = function (e) { return e.kind || NOKIND; };
  // the second kind has to be one with live rows, or "either kind" proves nothing
  var live = {};
  st.view.forEach(function (e) { live[kv(e)] = 1; });
  var all = [], other = null;
  for (var i2 = 0; i2 < chips.length; i2++) {
    var k2 = chips[i2].dataset.k;
    if (!k2) continue;
    all.push(chips[i2]);
    if (!other && k2 !== pl.dataset.k && live[k2]) other = chips[i2];
  }
  ok(other, "a second kind with live entries has a chip");
  click(pl);
  click(other);
  eq(st.kinds.length, 2, "a tap adds a second kind, like a tag");
  ok(pl.classList.contains("on") && other.classList.contains("on"), "both chips lit");
  ok(st.view.some(function (e) { return kv(e) === pl.dataset.k; }) &&
     st.view.some(function (e) { return kv(e) === other.dataset.k; }),
     "the view carries entries of either kind");
  ok(st.view.every(function (e) {
       return kv(e) === pl.dataset.k || kv(e) === other.dataset.k;
     }), "and nothing else");
  var both = st.view.length;
  click(other);
  eq(st.kinds.join(","), pl.dataset.k, "a second tap takes it back out");
  ok(st.view.length < both, "which narrows the list again");
  click(other);
  click(pl, { metaKey: true });
  eq(st.kinds.join(","), pl.dataset.k, "⌘-click keeps only that one");
  click(pl);

  // shift takes the whole run between the last pick and this one
  click(all[0]);
  click(all[all.length - 1], { shiftKey: true, ctrlKey: true });
  eq(st.kinds.length, all.length, "shift-click picks the range");
  var picked = st.kinds.slice().sort().join(",");
  eq(picked, all.map(function (c) { return c.dataset.k; }).sort().join(","),
     "which is every kind between the two");
  eq($("#kindchips").querySelectorAll(".kc.on").length, all.length, "every chip in it lit");

  // the url has to carry all of them, and bring them back
  var qs = stateQS(false);
  eq((qs.match(/(^|&)k=/g) || []).length, all.length, "every kind is in the url");
  clearFilters();
  eq(st.kinds.length, 0, "clearing drops them");
  applyQS(qs);
  eq(st.kinds.length, all.length, "and the url puts them back");

  clearFilters();

  // hand the whole fixture back: the heatmap and everything downstream count it
  st.all = allRows;
  fillKinds();
  refresh();
  eq(st.all.length, FIX.length, "the full fixture is restored");

  /* ---------- 3.3 heatmap ---------- */
  console.log("-- heatmap --");
  eq($("#heat").children.length, HEAT_WEEKS * 7, "one cell per day");
  var cell = $("#heat").children[HEAT_WEEKS * 7 - 8];
  click(cell);
  eq($("#fSince").value, cell.dataset.d, "clicking a cell sets since");
  eq($("#fUntil").value, cell.dataset.d, "clicking a cell sets until");
  ok(cell.classList.contains("sel"), "the cell marks itself");
  click(cell);
  eq($("#fSince").value, "", "a second click clears the day");

  /* ---------- 3.5 on this day ---------- */
  console.log("-- on this day --");
  click($("#bOtd"));
  ok(st.otd, "on-this-day engaged");
  var md = isoDay(new Date()).slice(5);
  ok(st.view.every(function (e) { return dayKey(e.created_at_utc).slice(5) === md; }),
     "only this month/day survives");
  click($("#bOtd"));
  ok(!st.otd, "toggles back off");

  /* ---------- 3.6/3.7 state ---------- */
  console.log("-- url + persisted state --");
  $("#q").value = "hike";
  $("#fDel").value = "all";
  refresh();
  runTimers();
  has(location.search, "q=hike", "query lands in the url");
  has(location.search, "d=all", "a non-default filter lands in the url");
  ok(localStorage.getItem("lcars.filters").indexOf("q=hike") >= 0, "and in localStorage");
  var saved = location.search;
  clearFilters();
  eq($("#q").value, "", "cleared");
  applyQS(saved.replace(/^\?/, ""));
  eq($("#q").value, "hike", "the url restores the query");
  eq($("#fDel").value, "all", "the url restores the filter");
  clearFilters();
  eq($("#fSort").value, "created:desc", "sort default intact");

  /* The url writer, the url reader, the active-filter count and Clear are all
     derived from CONTROLS, so the way a new filter breaks is by being added to
     the table and wired to nothing. Walk the table rather than naming the
     filters, and a half-wired one fails here instead of silently. */
  console.log("-- every control round-trips through the url --");
  CONTROLS.forEach(function (c) {
    var el = $(c.el);
    ok(el, c.qs + " -> " + c.el + " exists");
    // something that is definitely not the default, whatever the control is
    var alt = null;
    var opts = el.querySelectorAll ? el.querySelectorAll("option") : [];
    for (var i = 0; i < opts.length; i++) if (opts[i].value !== c.dflt) alt = opts[i].value;
    // a date input refuses anything that is not a date, so give it one
    if (alt === null) {
      var type = el.getAttribute ? el.getAttribute("type") : "";
      alt = type === "date" ? "2020-02-02" : "round-trip-" + c.qs;
    }
    el.value = alt;
    var round = stateQS(false);
    clearFilters();
    applyQS(round);
    eq($(c.el).value, alt, c.qs + " survives the round trip through the url");
    if (c.narrow) eq(activeFilters(), 1, c.qs + " counts as one active filter");
    clearFilters();
    if (c.narrow) eq($(c.el).value, c.dflt, c.qs + " is reset by Clear");
  });
  // every filter has to actually narrow something, or it is decoration
  ok(FILTERS.length && FILTERS.every(function (c) { return typeof c.pred === "function"; }),
     "every filter carries a predicate");
  // Clear leaves the scope and the sort alone on purpose, so the walk above has
  // to put them back itself before anything downstream reads them
  CONTROLS.forEach(function (c) { $(c.el).value = c.dflt; });
  clearFilters();
  eq($("#fSort").value, "created:desc", "and the sort is back where it started");

  /* ---------- 3.8 search history ---------- */
  console.log("-- search history --");
  $("#q").value = "radu";
  noteQuery();
  runTimers();
  has(localStorage.getItem("lcars.qhist"), "radu", "query remembered");
  has($("#qhist").innerHTML, "radu", "datalist repainted");
  $("#q").value = "";
  refresh();

  console.log("\nsection A: " + TEST.asserts + " assertions, " + TEST.fails.length + " failures");
  globalThis.__phaseA = true;
})().catch(function (e) { console.log("SUITE A THREW: " + e + "\n" + (e && e.stack)); });

/* ===================== suite B ===================== */
(async function () {
  if (!await waitFlag("__phaseA")) return;
  console.log("\n-- markdown: escaping --");

  var evil = '<img src=x onerror="alert(1)"> & <script>alert(2)</script>';
  var h = mdRender(evil);
  ok(h.indexOf("<img") < 0, "raw img tag never survives");
  ok(h.indexOf("<script") < 0, "raw script tag never survives");
  ok(h.indexOf("onerror") < 0 || h.indexOf("&lt;img") >= 0, "attributes stay inert");
  has(h, "&lt;img", "it is shown as text instead");

  eq(mdRender("[x](javascript:alert(1))").indexOf("href"), -1, "javascript: never becomes a link");
  has(mdRender("[x](javascript:alert(1))"), "mdlink", "it renders as an inert chip");
  has(mdRender("[x](https://a.test/p)"), 'href="https://a.test/p"', "https does become a link");
  has(mdRender("[x](https://a.test/p)"), 'rel="noopener noreferrer"', "and is opened safely");
  has(mdRender('[[a"b]]'), "&quot;", "a quote cannot break out of an attribute");
  has(mdRender("![pic](../assets/x.jpg)"), "mdimg", "local images become chips, not requests");
  ok(mdRender("![pic](../assets/x.jpg)").indexOf("<img") < 0, "and never fetch anything");

  console.log("-- markdown: media in the text --");
  var base = mediaBase();
  h = mdRender("![beach](media/2026/09/24/e1-120000-ab.jpg)");
  has(h, '<img src="' + base + '/media/2026/09/24/e1-120000-ab.jpg"', "a media/ path shows the picture from the API base");
  has(h, 'data-light=', "and opens in the lightbox");
  has(h, ">beach</span>", "with its alt as the caption");
  has(mdRender("![](/media/a/b.png)"), '"' + base + '/media/a/b.png"', "a leading / is the same path");
  has(mdRender("![x](https://pics.test/p/q.webp)"), '<img src="https://pics.test/p/q.webp"', "a full URL is used as written");
  has(mdRender("![x](https://pics.test/photo?id=3&s=2)"), 'src="https://pics.test/photo?id=3&amp;s=2"', "an image URL with no extension is still an image, & kept escaped");
  h = mdRender("[the walk](media/2026/09/24/e1-120000-ab.mp4)");
  has(h, "<video", "a link to a video plays in place");
  has(h, 'e1-120000-ab.mp4#t=0.1"', "painting its first frame on iOS");
  has(h, ">the walk</span>", "captioned with the link text");
  has(mdRender("[memo](https://x.test/a/memo.m4a?dl=1)"), "<audio", "a link to a recording gets a player, query and all");
  has(mdRender("![voice](media/x/rec.webm)"), "<video", "webm is a video element, which plays audio-only webm too");

  console.log("-- the tape player (audioPlayer) --");
  h = mdRender("[memo](https://x.test/a/memo.m4a)");
  has(h, 'class="lplay"', "a recording plays in our own LCARS bar");
  eq(h.indexOf(" controls"), -1, "not in the browser's controls");
  var deck = document.createElement("div");
  deck.innerHTML = audioPlayer("https://x.test/a.m4a") + audioPlayer("https://x.test/b.m4a");
  document.body.appendChild(deck);
  var tapes = deck.querySelectorAll("audio"), plays = [];
  for (var ti = 0; ti < tapes.length; ti++) (function (a) {
    a.paused = true; a.ended = false; a.currentTime = 0; a.duration = 80;
    a.play = function () { a.paused = false; plays.push(a); dispatch(a, "play", {}); };
    a.pause = function () { a.paused = true; dispatch(a, "pause", {}); };
  })(tapes[ti]);
  var p0 = deck.querySelectorAll(".lplay")[0], a0 = tapes[0], a1 = tapes[1];
  dispatch(a0, "loadedmetadata", {});
  eq(p0.querySelector(".lp-time").textContent, "1:20", "an idle tape shows its length");
  click(p0.querySelector(".lp-btn"));
  ok(!a0.paused && plays[0] === a0, "the pill plays it");
  eq(p0.querySelector(".lp-btn").textContent, "Pause", "and then offers to pause");
  a0.currentTime = 20; dispatch(a0, "timeupdate", {});
  eq(p0.querySelector(".lp-bar i").style.transform, "scaleX(0.25)", "the bar fills with the tape");
  eq(p0.querySelector(".lp-time").textContent, "0:20 / 1:20", "the clock runs");
  click(deck.querySelectorAll(".lp-btn")[1]);
  ok(a0.paused && !a1.paused, "starting another tape stops the first");
  var bar = p0.querySelector(".lp-bar");
  bar._rect = { left: 100, width: 200 };
  dispatch(bar, "pointerdown", { clientX: 250, pointerId: 1 });
  eq(a0.currentTime, 60, "pressing the bar seeks to that point");
  dispatch(bar, "pointermove", { clientX: 150, pointerId: 1 });
  eq(a0.currentTime, 20, "and a drag follows the finger");
  dispatch(bar, "pointerup", { pointerId: 1 });
  dispatch(bar, "pointermove", { clientX: 300, pointerId: 1 });
  eq(a0.currentTime, 20, "until it is let go");
  a0.duration = Infinity; a0.currentTime = 0;
  dispatch(bar, "pointerdown", { clientX: 250, pointerId: 1 });
  eq(a0.currentTime, 0, "an unknown length (raw WebM) does not seek");
  a1.tagName = "AUDIO"; dispatch(a1, "error", {});
  eq(deck.querySelectorAll(".lp-time")[1].textContent, "No signal", "a tape that will not play says so");
  deck.parentNode.removeChild(deck);
  has(mdRender("[doc](https://x.test/a.pdf)"), 'href="https://x.test/a.pdf"', "a link to anything else stays a link");
  has(mdRender("[doc](media/a.pdf)"), "mdlink", "and a relative one stays inert");
  eq(mdRender("![x](//evil.test/a.jpg)").indexOf("<img"), -1, "a protocol-relative src is not fetched");
  eq(mdRender("![x](media/../../etc/a.jpg)").indexOf("<img"), -1, "nor one that climbs out with ..");
  eq(mdRender("![x](data:image/png;base64,AAAA)").indexOf("<img"), -1, "nor a data: or any other scheme");
  eq(mdRender("[x](javascript:alert(1).mp4)").indexOf("<video"), -1, "a javascript: link never becomes a player");
  h = mdRender('![a"b](media/q.jpg)');
  ok(h.indexOf('alt="a&quot;b"') >= 0, "a quote in the alt stays inside the attribute");
  h = mdRender("[`clip` one](media/c.mp4)");
  has(h, "<code>clip</code> one</span>", "a code run in a caption is rendered, not left parked");
  ok(!/<\d+>/.test(h), "no placeholder leaks out");
  h = mdRender("![`x`](media/c.jpg)");
  has(h, 'alt=""', "a placeholder never lands in alt text");

  console.log("-- markdown: structure --");
  has(mdRender("# Title"), "<h3>Title</h3>", "# is a heading");
  has(mdRender("### Deep"), "<h5>Deep</h5>", "### nests down");
  ok(mdRender("####### seven x").indexOf("<h") < 0, "seven hashes is not a heading");
  // the parent of a branch carries the fold caret; the branch itself is the
  // <ul> after it, which is what li.fold+ul hides
  eq(mdRender("- a\n\t- b"),
     '<ul><li class="foldable"><button class="fbtn" type="button" aria-expanded="true"' +
     ' aria-label="Fold this branch" title="Fold this branch"></button>a</li>' +
     "<ul><li>b</li></ul></ul>", "a tab nests a bullet");
  eq(mdRender("- a\n- b"), "<ul><li>a</li><li>b</li></ul>", "siblings stay siblings");
  has(mdRender("- TODO buy milk"), 'class="task todo"', "logseq markers become badges");
  has(mdRender("- DONE buy milk"), 'class="task done"', "DONE too");
  has(mdRender("date:: 2024-07-27"), "mdprop", "property lines are recognised");
  has(mdRender("```\nx < y\n```"), "<pre class=\"mdcode\">x &lt; y", "fences are opaque and escaped");
  has(mdRender("> quoted"), "<blockquote>quoted</blockquote>", "blockquote");
  has(mdRender("---"), "<hr>", "rule");
  has(mdRender("a **b** c"), "<b>b</b>", "bold");
  has(mdRender("a `co<de` c"), "<code>co&lt;de</code>", "code span, escaped");
  has(mdRender("see [[My Page]]"), 'data-q="My Page"', "wiki link carries its query");
  has(mdRender("- #Journal"), 'data-q="#Journal"', "tags are clickable");
  has(mdRender("go to https://x.test/a"), 'href="https://x.test/a"', "bare urls autolink");
  eq(mdRender(""), "", "empty content renders to nothing");
  eq(mdRender(null), "", "null is survivable");

  console.log("-- markdown: only allowed tags, over every fixture row --");
  // button: the fold caret on a branch parent — ours, never the entry's;
  // img/video/audio: media the text links to (mdMedia), http(s) sources only
  var ALLOWED = { ul:1, li:1, p:1, h3:1, h4:1, h5:1, h6:1, blockquote:1, pre:1,
                  code:1, a:1, b:1, i:1, s:1, span:1, div:1, hr:1, button:1,
                  img:1, video:1, audio:1 };
  var bad = {}, rendered = 0;
  for (var i = 0; i < FIX.length; i++) {
    var out = mdRender(FIX[i].content || "");
    rendered++;
    var re = /<\/?([a-zA-Z][\w-]*)/g, m;
    while ((m = re.exec(out))) if (!ALLOWED[m[1].toLowerCase()]) bad[m[1]] = (bad[m[1]] || 0) + 1;
    // the one handler the renderer writes itself, on its own <img>
    if (/ on[a-z]+\s*=/.test(out.split(' onerror="mdMediaBroken(this)"').join(""))) bad["EVENT_HANDLER"] = 1;
    var sr = / src="([^"]*)"/g, sm;
    while ((sm = sr.exec(out))) if (!/^https?:\/\//.test(sm[1])) bad["SRC:" + sm[1].slice(0, 20)] = 1;
    if (/javascript:/i.test(out)) bad["JS_URL"] = 1;
  }
  ok(Object.keys(bad).length === 0,
     "no tag outside the allowlist in " + rendered + " real entries: " + JSON.stringify(bad));

  console.log("-- 3.1 read mode --");
  // An outline of the suite's own: the journal's first one is read, timed,
  // made a task and given a due date below, and on 2026-09-24's data it
  // already carried a start_date, so "starts unscheduled" failed and the
  // section threw. Taken out at the end of the section.
  var target = await plant({ title: "Outline probe",
    content: "- morning review of [[Some Page]]\n  - follow up on the arena\n- water the plants" });
  ok(target, "found an outline entry to read");
  select(target.id);
  eq($("#readbody").style.display, "block", "opening an entry shows the reader");
  eq($("#edbody").style.display, "none", "and not the form");
  ok($("#rd_content").innerHTML.indexOf("<li>") >= 0, "the outline is rendered");
  eq($("#rd_title").textContent, target.title || "(untitled)", "title shown");
  has($("#rd_meta").innerHTML, "kbadge", "kind badge shown");
  eq($("#edchip").dataset.s + " " + $("#edchip").textContent, "idle Saved", "the chip says the reader's entry is saved");
  var editBtn = $("#rwmode").children[1];
  click(editBtn);
  eq($("#edbody").style.display, "flex", "Edit switches to the form");
  eq($("#readbody").style.display, "none", "reader hidden");
  $("#content").blur();
  key("e");
  eq(document.activeElement, $("#content"), "e in the editor is back into the text (P13)");
  click($("#rwmode").children[0]);
  eq($("#readbody").style.display, "block", "Read goes back to reading");

  console.log("-- 3.1 wiki links search --");
  // an id link to a row older than the fixture's 400 is refused, not searched
  // (followIdLink), so only a link the fixture can follow is clicked here
  var wiki = [].slice.call($("#rd_content").querySelectorAll("a.wiki")).filter(function (a) {
    return !a.dataset.id || st.byId.has(Number(a.dataset.id));
  })[0];
  if (!wiki) { $("#rd_content").innerHTML = mdRender("see [[Some Page]]"); wiki = $("#rd_content").querySelector("a.wiki"); }
  click(wiki);
  eq($("#q").value, wiki.dataset.q, "clicking a wiki link searches for it");
  eq($("#scope").value, "all", "over title and content");
  clearFilters();

  console.log("-- 3.1 wiki links open an exact title --");
  var titled = st.all.find(e => !e.deleted && /^[\w .,'-]{3,60}$/.test((e.title || "").trim()));
  if (titled) {
    var name = titled.title.trim();
    $("#rd_content").innerHTML = mdRender("see [[" + name.toUpperCase() + "]]");
    click($("#rd_content").querySelector("a.wiki"));
    ok(st.sel && (st.sel.title || "").trim().toLowerCase() === name.toLowerCase(),
       "an exact title opens its entry, whatever its case");
    eq($("#q").value, name.toUpperCase(), "and still searches for the other mentions");
    clearFilters();
  }
  eq(byTitle("no entry is called this 4711"), null, "a title nothing carries opens nothing");

  console.log("-- 3.1 a link to a page nothing carries writes it --");
  clearFilters();
  closeEditor();
  runTimers();
  var newName = "Brindlewick Protocol 4711";
  $("#rd_content").innerHTML = mdRender("see [[" + newName + "]]");
  click($("#rd_content").querySelector("a.wiki"));
  await settle(6);
  var made = byTitle(newName);
  ok(made, "following the link created the entry it names");
  if (made) {
    eq(made.kind, "page", "as a page");
    eq(made.title, newName, "titled with the text inside the brackets");
    eq(made.content, "", "and empty, waiting to be written");
    eq(st.sel && st.sel.id, made.id, "the new page is what the link left open");
    eq($("#edbody").style.display, "flex", "in the editor, since an empty page invites writing");
    has($("#toast").textContent, "created page #" + made.id, "and the toast names it");

    var before = st.all.length;
    $("#rd_content").innerHTML = mdRender("see [[" + newName.toLowerCase() + "]]");
    click($("#rd_content").querySelector("a.wiki"));
    await settle(6);
    eq(st.all.length, before, "the next click opens the page instead of writing a second one");
    eq(st.sel && st.sel.id, made.id, "whatever its case");
  }
  clearFilters();

  /* [Title](((id))): a link that names the row, so renaming the row cannot
     strand it. The rename here is in memory only, and put back. */
  console.log("-- 3.1 id links survive a rename --");
  clearFilters();
  if (titled) {
    var tid = titled.id, oldT = titled.title;
    var ih = mdRender("see [Some old label](((" + tid + ")))");
    has(ih, 'data-id="' + tid + '"', "an id link carries its row");
    has(ih, ">" + esc(oldT.trim()) + "</a>", "and reads as the row's title, not its label");
    ok(ih.indexOf("(((") < 0 && ih.indexOf("Some old label") < 0, "with nothing of the raw form left over");
    has(ih, 'class="wiki"', "styled as the [[page]] link it stands in for");
    titled.title = "Renamed Page 4713";
    $("#rd_content").innerHTML = mdRender("see [" + oldT + "](((" + tid + ")))");
    has($("#rd_content").innerHTML, ">Renamed Page 4713</a>", "a rename carries the link along");
    var idN = st.all.length;
    click($("#rd_content").querySelector("a.wiki"));
    await settle(6);
    eq(st.sel && st.sel.id, tid, "following it opens that row");
    eq($("#q").value, "Renamed Page 4713", "and searches under its current name");
    eq(st.all.length, idN, "no page is written under the old name");
    var linker = { id: 987654321, kind: "page", title: "linker", deleted: 0,
                   content: "see [" + oldT + "](((" + tid + ")))" };
    st.all.push(linker);
    ok(backlinks(titled).indexOf(linker) >= 0, "the row it names counts it as a backlink");
    st.all.pop();
    titled.title = oldT;
    clearFilters();
  }
  $("#rd_content").innerHTML = mdRender("see [Ghost](((999999999)))");
  has($("#rd_content").innerHTML, 'class="wiki gone"', "an id the journal lacks is marked");
  has($("#rd_content").innerHTML, ">Ghost</a>", "and falls back to its label");
  var ghostN = st.all.length;
  click($("#rd_content").querySelector("a.wiki"));
  await settle(6);
  eq(st.all.length, ghostN, "following it writes no page");
  has($("#toast").textContent, "not in the journal", "and says why nothing opened");
  clearFilters();

  console.log("-- 3.1 a page written by a stray click can be taken back --");
  $("#rd_content").innerHTML = mdRender("see [[Stray Click 4712]]");
  click($("#rd_content").querySelector("a.wiki"));
  await settle(6);
  var stray = byTitle("Stray Click 4712");
  ok(stray, "the stray click wrote a page");
  var undoPage = $("#toast").querySelector("button");
  ok(undoPage, "the toast offers an Undo");
  if (stray && undoPage) {
    click(undoPage);
    await settle(6);
    ok(stray.deleted, "Undo soft-deletes it, so the server can still restore it");
    ok(!st.view.some(function (e) { return e.id === stray.id; }), "and it leaves the list");
    eq(st.sel, null, "with the editor closed behind it");
  }
  clearFilters();
  closeEditor();
  runTimers();

  console.log("-- 3.1 tags and empty days are not pages --");
  var nRows = st.all.length;
  $("#rd_content").innerHTML = mdRender("a #notapage4711 here");
  click($("#rd_content").querySelector("a.wiki.tag"));
  await settle(6);
  eq(st.all.length, nRows, "a #tag names a topic, not a page, so nothing is written");
  $("#rd_content").innerHTML = mdRender("see [[Jan 3rd, 1904]]");
  click($("#rd_content").querySelector("a.wiki"));
  await settle(6);
  eq(st.all.length, nRows, "and a journal day with nothing in it stays an empty day");
  clearFilters();
  closeEditor();
  runTimers();

  console.log("-- 3.1 old Logseq date links reach the renamed journal --");
  eq(logseqDay("Sep 1st, 2026"), "2026-09-01", "Logseq's day name reads as its ISO day");
  eq(logseqDay("Dec 28th, 2020"), "2020-12-28", "and so does a two-digit one");
  eq(logseqDay("MAY 5TH, 2021"), "2021-05-05", "whatever its case");
  eq(logseqDay("Brindlewick Project"), null, "a page that is not a day stays a page");
  eq(logseqDay("Sep 41st, 2026"), null, "a day outside the month is not a day");
  var day = st.all.find(e => !e.deleted && /^\d{4}-\d{2}-\d{2}$/.test((e.title || "").trim()));
  if (day) {
    var dp = (day.title || "").trim().split("-");
    var old = MO[+dp[1] - 1] + " " + (+dp[2]) + "th, " + dp[0];
    $("#rd_content").innerHTML = mdRender("see [[" + old + "]]");
    click($("#rd_content").querySelector("a.wiki"));
    eq(st.sel && (st.sel.title || "").trim(), day.title.trim(),
       "clicking the old date link opens the entry now titled " + day.title.trim());
    eq($("#q").value, day.title.trim(), "and searches under the day's name today, not the clicked words");
    clearFilters();
  }
  $("#rd_content").innerHTML = mdRender("a #tag here");
  var tg = $("#rd_content").querySelector("a.wiki.tag");
  var selBefore = st.sel;
  click(tg);
  eq(st.sel, selBefore, "a #tag only searches, it does not jump");
  clearFilters();

  console.log("-- 3.1 Ctrl/Alt + click follows a [[link]] from the editor --");
  /* The reader hit-tests an <a>; the editor has only a textarea, so the link is
     found from the caret the click just moved. Caret 8 is inside the name. */
  var eta = $("#content");
  var atLink = function (name) {
    eta.value = "see [[" + name + "]] here";
    eta.selectionStart = eta.selectionEnd = 8;
    setClean();
  };
  if (titled) {
    var tn = titled.title.trim();
    atLink(tn);
    click(eta, { ctrlKey: true });
    eq($("#q").value, tn, "Ctrl+click searches for the link the caret landed in");
    eq($("#scope").value, "all", "over title and content");
    ok(st.sel && (st.sel.title || "").trim().toLowerCase() === tn.toLowerCase(),
       "and opens the entry it names, just as the reader does");
    ok(!$("#wikiac").classList.contains("on"), "with the suggestion popup shut behind it");
    clearFilters();
    atLink(tn);
    click(eta, { altKey: true });
    eq($("#q").value, tn, "Alt+click does the same");
    clearFilters();
  }
  atLink("Some Page 4711");
  var bare = click(eta, {});
  ok(!bare.defaultPrevented, "a bare click still only places the caret");
  eq($("#q").value, "", "and follows nothing");
  eta.selectionStart = eta.selectionEnd = 8;
  click(eta, { ctrlKey: true });
  eq($("#q").value, "Some Page 4711", "a link with no entry behind it still searches");
  clearFilters();
  eta.value = "no link here at all";
  eta.selectionStart = eta.selectionEnd = 5;
  click(eta, { ctrlKey: true });
  eq($("#q").value, "", "a modifier click off any link follows nothing");
  atLink("Some Page 4711");
  eta.selectionEnd = 14;
  click(eta, { ctrlKey: true });
  eq($("#q").value, "", "a modifier-drag that selected text is a selection, not a jump");
  eta.value = "";
  setClean();

  console.log("-- 3.1 back returns to the entry the link was clicked from --");
  /* Following a [[link]] is a navigation, so it has to leave a history entry
     behind: Back goes to the entry the link sat in, Forward returns. Browsers
     have disagreed on whether popstate or hashchange comes first, so the whole
     walk runs twice, once in each order. */
  function linkWalk(hashFirst) {
    var tag = hashFirst ? " (hashchange first)" : " (popstate first)";
    TEST.hashFirst = hashFirst;
    clearFilters();
    runTimers();
    var target = st.all.find(e => !e.deleted && /^[\w .,'-]{3,60}$/.test((e.title || "").trim()));
    if (!target) return;
    var name = target.title.trim();
    var from = st.view.find(e => e.id !== target.id);
    select(from.id);
    $("#q").value = "before the link";
    refresh();
    runTimers();
    var hashBefore = locUrl(), at = history._i;

    $("#rd_content").innerHTML = mdRender("see [[" + name + "]]");
    click($("#rd_content").querySelector("a.wiki"));
    eq(st.sel.id, target.id, "the link opens its entry" + tag);
    eq(history._i, at + 1, "and pushes exactly one history entry" + tag);
    eq(history._st.length, at + 2, "on top of the one it came from" + tag);
    has(location.pathname, "/entry/" + target.id, "the url is the entry it landed on" + tag);

    history.back();
    eq(st.sel && st.sel.id, from.id, "Back returns to the entry it was clicked from" + tag);
    eq($("#q").value, "before the link", "with the search that was running" + tag);
    eq(locUrl(), hashBefore, "and the url it had" + tag);

    history.forward();
    eq(st.sel && st.sel.id, target.id, "Forward follows the link again" + tag);
    eq($("#q").value, name, "and searches for it again" + tag);

    /* A second hop, then two steps back: the trail is a stack, not one slot.
       The link is written from a title, so the row picked here has to be the
       one that title resolves back to — this journal titles a thousand rows
       "HTTP Entry", and an older twin would be asserted against while the newer
       one is what opens. */
    var second = st.all.find(e => !e.deleted && e.id !== target.id && e.id !== from.id &&
                                 /^[\w .,'-]{3,60}$/.test((e.title || "").trim()) &&
                                 (e.title || "").trim().toLowerCase() !== name.toLowerCase() &&
                                 byTitle(e.title) === e);
    if (second) {
      $("#rd_content").innerHTML = mdRender("then [[" + second.title.trim() + "]]");
      click($("#rd_content").querySelector("a.wiki"));
      eq(st.sel.id, second.id, "a second link hops on" + tag);
      history.back();
      eq(st.sel && st.sel.id, target.id, "Back unwinds one hop" + tag);
      history.back();
      eq(st.sel && st.sel.id, from.id, "and the next Back unwinds the other" + tag);
    }
    TEST.hashFirst = false;
  }
  linkWalk(false);
  linkWalk(true);

  console.log("-- 3.1 back past the first link closes the editor --");
  clearFilters();
  closeEditor();
  runTimers();
  var closedHash = locUrl();
  var jump = st.all.find(e => !e.deleted && /^[\w .,'-]{3,60}$/.test((e.title || "").trim()));
  if (jump) {
    $("#rd_content").innerHTML = mdRender("see [[" + jump.title.trim() + "]]");
    click($("#rd_content").querySelector("a.wiki"));
    eq(document.body.dataset.pane, "edit", "the link opened the editor");
    history.back();
    eq(document.body.dataset.pane, "list", "Back past the link closes it again");
    eq(st.sel, null, "with nothing selected");
    eq(locUrl(), closedHash, "and the url the list had");
  }
  clearFilters();
  closeEditor();
  runTimers();

  console.log("-- pages: every view is a url, Back and Forward walk them --");
  (function () {
    clearFilters();
    closeEditor();
    closeOv();
    runTimers();
    var ovOn = function () { return $("#ov").classList.contains("on"); };
    var at = history._i;
    eq(location.pathname, "/", "the list is the app's own directory");
    openTasks();
    runTimers();
    eq(location.pathname, "/tasks", "the task board is ./tasks");
    eq(history._i, at + 1, "opening it is one step");
    openStats();
    runTimers();
    eq(location.pathname, "/stats", "another view is a page of its own");
    eq(history._i, at + 2, "pushed on top of the board");
    history.back();
    ok(ovOn() && st.route && st.route.v === "tasks", "Back reopens the task board");
    eq(location.pathname, "/tasks", "at its url");
    history.back();
    ok(!ovOn() && !st.route, "the next Back closes it, back on the list");
    history.forward();
    ok(ovOn() && st.route && st.route.v === "tasks", "Forward opens it again");
    // closing a view by hand is the Back it would have been, not a new step
    var len = history._st.length;
    closeOv();
    runTimers();
    eq(location.pathname, "/", "closing the view returns to the list's url");
    eq(history._i, at, "by stepping back onto it");
    eq(history._st.length, len, "and the board stays there for Forward");

    // a month to the next replaces; the calendar is one step however far it walks
    openMonth("2026-03");
    runTimers();
    has(location.pathname, "/calendar/month/2026-03-01", "the calendar names its scale and day");
    var calAt = history._i;
    monthStep(-1);
    runTimers();
    has(location.pathname, "/calendar/month/2026-02", "the previous month replaces it");
    eq(history._i, calAt, "without a step");
    closeOv();
    runTimers();

    // an entry opened from a view: Back returns to the view
    var row = st.view[0];
    openTasks();
    runTimers();
    closeOv(); select(row.id);
    runTimers();
    eq(location.pathname, "/entry/" + row.id, "an entry is ./entry/<id>");
    history.back();
    eq(st.route && st.route.v, "tasks", "Back from it is the board it was opened from");
    closeOv();
    runTimers();

    // clicks push, walking replaces
    closeEditor();
    runTimers();
    var a0 = history._i;
    click(document.querySelector(".item"));
    runTimers();
    var first = st.sel.id;
    eq(history._i, a0 + 1, "a row clicked from the list is a step");
    move(1);
    runTimers();
    ok(st.sel.id !== first, "j walks to the next row");
    eq(history._i, a0 + 1, "and replaces rather than pushing");
    eq(location.pathname, "/entry/" + st.sel.id, "the url follows it");
    history.back();
    eq(st.sel, null, "Back from a walked entry returns to the list");
    closeEditor();
    runTimers();

    // a bookmark of a page opens it once the rows are in
    bootRoute = { v: "readings", a: [] };
    openBootRoute();
    runTimers();
    ok(st.route && st.route.v === "readings", "a bookmarked page opens at boot");
    eq(location.pathname, "/readings", "and keeps its url");
    closeOv();
    runTimers();
    // the url builder and parser agree for every page
    ["tasks", "calendar/week/2026-10-05", "day/2026-10-01", "stats/all", "trend/a%2Fb%20c", "entry/12"].forEach(function (u) {
      var r = parseRel(u + "?q=x");
      eq(r.qs, "q=x", "the query rides along on " + u);
      ok(r.v && u.indexOf(r.v) === 0, "the page is read from " + u);
    });
    eq(parseRel("trend/a%2Fb%20c").a[0], "a/b c", "a term is decoded");
  })();

  console.log("-- 3.1 on a phone the link trail shares the stack with the editor --");
  /* The phone opens the editor as a full-screen layer with a history entry of
     its own, so Back closes it rather than leaving the app. A link trail has to
     unwind through that without either mechanism eating the other's step. */
  TEST.mobile = true;
  clearFilters();
  closeEditor();
  runTimers();
  var mTarget = st.all.find(e => !e.deleted && /^[\w .,'-]{3,60}$/.test((e.title || "").trim()));
  var mFrom = mTarget && st.view.find(e => e.id !== mTarget.id);
  if (mTarget && mFrom) {
    var listHash = locUrl();
    select(mFrom.id);
    runTimers();
    eq(document.body.dataset.pane, "edit", "opening an entry shows the editor layer");
    $("#rd_content").innerHTML = mdRender("see [[" + mTarget.title.trim() + "]]");
    var mAt = history._i;
    click($("#rd_content").querySelector("a.wiki"));
    eq(st.sel.id, mTarget.id, "the link opens its entry");
    eq(history._i, mAt + 1, "one entry for the link, not one per layer");
    history.back();
    eq(st.sel && st.sel.id, mFrom.id, "Back returns to the entry it was clicked from");
    eq(document.body.dataset.pane, "edit", "still in the editor layer");
    history.back();
    eq(document.body.dataset.pane, "list", "the next Back closes the layer");
    eq(locUrl(), listHash, "landing on the list it came from");
  }
  // and a link followed from the list opens the layer on the link's own entry
  if (mTarget) {
    closeEditor();
    runTimers();
    var fromList = locUrl(), listAt = history._i;
    $("#rd_content").innerHTML = mdRender("see [[" + mTarget.title.trim() + "]]");
    click($("#rd_content").querySelector("a.wiki"));
    eq(document.body.dataset.pane, "edit", "a link from the list opens the editor");
    eq(history._i, listAt + 1, "on one history entry, not two");
    history.back();
    eq(document.body.dataset.pane, "list", "and one Back closes it");
    eq(locUrl(), fromList, "back on the list's own url");
  }
  TEST.mobile = false;
  clearFilters();
  closeEditor();
  runTimers();

  console.log("-- 3.4 day view --");
  ok(st.dayOf, "a date sort gives day dividers");
  var dayk = st.dayOf(st.view[0]);
  openDay(dayk);
  ok($("#ov").classList.contains("on"), "dialog opened");
  eq(dayOpen, dayk, "dialog knows its day");
  has($("#dayout").textContent, "entr", "day text rendered");
  click($("#daymode").children[2]);
  eq(dayMode, "md", "switched to rendered");
  has($("#dayout").innerHTML, "dayent", "entries rendered as markdown");
  // a click on a rendered entry opens it in the editor, not the reader
  var dent = $("#dayout").querySelector(".dayent .dbody");
  ok(dent, "a rendered entry has a body to click");
  var dentId = Number(dent.parentNode.dataset.id);
  click(dent);
  ok(!$("#ov").classList.contains("on"), "clicking an entry's text closes the day");
  eq(st.sel && st.sel.id, dentId, "and opens that entry");
  eq(st.read, false, "in the editor");
  closeEditor();
  runTimers();
  openDay(dayk);
  click($("#dayout").querySelector(".dedit"));
  eq(st.read, false, "its header opens the editor too");
  var dtxt = st.sel.content || "";
  closeEditor();
  runTimers();
  if (dtxt.length > 4) {
    editEntry(dentId, 3);
    eq($("#content").selectionStart, 3, "the caret goes where the click was");
    closeEditor();
    runTimers();
  }
  openDay(dayk);
  // the ＋ between two entries starts one stamped halfway between them
  var dins = $("#dayout").querySelector(".dins");
  if (dins) {
    var ia = st.byId.get(Number(dins.dataset.a)), ib = st.byId.get(Number(dins.dataset.b));
    var lo = ia.created_at_utc < ib.created_at_utc ? ia : ib, hi = lo === ia ? ib : ia;
    click(dins);
    ok(st.isNew, "the ＋ between two entries starts a new one");
    var at = $("#e_created_at_utc").value;
    ok(at >= lo.created_at_utc && at <= hi.created_at_utc, "stamped between them (" + at + ")");
    eq(at, utcBetween(lo.created_at_utc, hi.created_at_utc), "halfway");
    setClean();
    closeEditor();
    runTimers();
    select(lo.id);
    ok(newAfterSel(), "o starts one after the open entry");
    var nx = entryAfter(lo);
    ok($("#e_created_at_utc").value > lo.created_at_utc && (!nx || $("#e_created_at_utc").value <= nx.created_at_utc),
       "before the next one written");
    setClean();
    closeEditor();
    runTimers();
  }
  openDay(dayk);
  has(dayMarkdown(dayk), "## ", "markdown export has entry headings");
  var nextk = dayNav(dayk, 1);
  ok(nextk && nextk !== dayk, "there is a next day");
  click($("#daynext"));
  eq(dayOpen, nextk, "next walks to it");
  var backk = dayNav(nextk, -1);
  eq(backk, dayk, "and prev walks back");
  key("ArrowLeft");
  eq(dayOpen, dayk, "left arrow does the same");
  click($("#dayclose"));
  ok(!$("#ov").classList.contains("on"), "dialog closed");
  eq(dayOpen, null, "and forgets its day");
  dayMode = "full";

  console.log("-- 3.4b ‹ goes back where the entry came from (design P10) --");
  (function () {
    var ovOn = function () { return $("#ov").classList.contains("on"); };
    var back = function () { $("#bBack").onclick(); };
    closeOv(); runTimers();
    eq($("#bBack").textContent, "‹ List", "nothing open: the ‹ is the list's");
    // the day: an entry's text tapped, ‹ Day back to the day at its scroll
    openDay(dayk);
    runTimers();
    click($("#daymode").children[2]);
    $("#dayout").scrollTop = 137;
    var at = history._i;
    var d = $("#dayout").querySelector(".dayent .dbody"), did = Number(d.parentNode.dataset.id);
    click(d);
    runTimers();
    eq(st.sel && st.sel.id, did, "the day's entry is open");
    eq($("#bBack").textContent, "‹ Day", "its ‹ is labelled for the day");
    eq($("#bBack").getAttribute("aria-label"), "Back to the day", "and says so to a reader");
    eq(history._i, at + 1, "the entry is a step over the day");
    back();
    ok(ovOn() && dayOpen === dayk, "‹ Day reopens that day, in the tap");
    ok(!st.sel, "the entry closed");
    eq($("#dayout").scrollTop, 137, "at the scroll it was left at");
    runTimers();
    eq(history._i, at, "by the Back step: the button and the gesture are one");
    eq(location.pathname, "/day/" + dayk, "at the day's url");
    eq($("#bBack").textContent, "‹ List", "closed, the ‹ is the list's again");
    // the gesture: the same day, the same scroll
    $("#dayout").scrollTop = 61;
    click($("#dayout").querySelector('.dayent[data-id="' + did + '"] .dbody'));
    runTimers();
    history.back();
    runTimers();
    ok(ovOn() && dayOpen === dayk && !st.sel, "Back from it is the day as well");
    eq($("#dayout").scrollTop, 61, "at its scroll too");
    history.forward();
    runTimers();
    eq(st.sel && st.sel.id, did, "Forward is the entry again");
    eq($("#bBack").textContent, "‹ Day", "still labelled for the day");
    // walking on to the next entry keeps where they came from
    select(st.view.find(function (e) { return e.id !== did; }).id);
    runTimers();
    eq($("#bBack").textContent, "‹ Day", "j/k to another entry keeps ‹ Day");
    // the voice's close is the same step
    VCMDS.find(function (c) { return c.say === "close"; }).fn();
    ok(ovOn() && dayOpen === dayk && !st.sel, '"computer, go back" goes back to the day');
    runTimers();
    closeOv(); runTimers();
    dayMode = "full";

    // the task board
    openTasks();
    runTimers();
    var tkr = $("#tkrows").querySelector(".tkrow");
    if (tkr) {
      at = history._i;
      click(tkr);
      runTimers();
      eq($("#bBack").textContent, "‹ Tasks", "an entry from the board: ‹ Tasks");
      back();
      ok(ovOn() && st.route && st.route.v === "tasks" && !st.sel, "‹ Tasks is the board again, in the tap");
      runTimers();
      eq(history._i, at, "by the Back step");
      eq(location.pathname, "/tasks", "at the board's url");
      closeOv(); runTimers();
    } else ok(true, "(no task in this journal to open)");

    // a search
    $("#q").value = "the"; refresh();
    runTimers();
    var hit = st.view[0];
    ok(hit, "the search finds something");
    var hitRow = $("#list").querySelector('.item[data-id="' + hit.id + '"]');
    if (hitRow) click(hitRow); else openRow(hit.id);
    runTimers();
    eq($("#bBack").textContent, "‹ Search", "an entry from a search: ‹ Search");
    back();
    runTimers();
    ok(!st.sel && !ovOn(), "‹ Search closes it onto the list");
    eq($("#q").value, "the", "searched as it was");
    eq($("#bBack").textContent, "‹ List", "and the ‹ is the list's again");

    // the list, and anything else
    clearFilters();
    runTimers();
    openRow(st.view[0].id);
    runTimers();
    eq($("#bBack").textContent, "‹ List", "an entry from the list: ‹ List");
    back();
    runTimers();
    ok(!st.sel && !ovOn() && location.pathname === "/", "‹ List is the list");
    openStats();
    runTimers();
    closeOv(); select(st.view[0].id);
    runTimers();
    eq($("#bBack").textContent, "‹ List", "from any other view: ‹ List");
    closeEditor();
    runTimers();
  })();

  console.log("-- 3.5 the stopwatch --");
  await settle(6);
  setRead(true);
  select(target.id);
  eq(st.sel, target, "the outline entry is open again");
  ok(!target.start_date, "the outline entry starts unscheduled");
  click($("#rd_meta").querySelector("[data-watch]"));
  await settle(3);
  ok($("#ov").classList.contains("on") && $("#dlg").classList.contains("watch"),
     "tapping the reader's time opens the stopwatch");
  ok($("#wFromWrote"), "which offers to start from when it was written");
  click($("#wFromWrote"));
  await settle(6);
  eq(dbFind(target.id).start_date, target.created_at_utc, "start_date is the written stamp");
  eq(dbFind(target.id).end_date || "", "", "and end_date is empty: running");
  ok($("#wStop"), "the panel turns into the running clock");
  closeOv();
  ok($("#rd_meta").querySelector("[data-wstop]"), "a running timer has a STOP in the reader");
  has($("#rd_meta").querySelector(".wrun").textContent, ":", "and ticks there");
  click($("#rd_meta").querySelector("[data-wstop]"));
  await settle(6);
  ok(dbFind(target.id).end_date, "STOP writes end_date");
  ok(!$("#rd_meta").querySelector("[data-wstop]"), "and the chip goes");
  click($("#rd_meta").querySelector("[data-watch]"));
  await settle(3);
  ok($("#wResume") && $("#wClear"), "a finished span offers resume and clear");
  click($("#wClear"));
  await settle(6);
  eq(dbFind(target.id).start_date || "", "", "Clear unschedules it again");
  closeOv();

  console.log("-- 3.6 reminders: a task's CalDAV fields --");
  var cdWas = target.kind;
  await api("/entries/" + target.id, { method: "PUT", body: { kind: "task_personal" } });
  await refetchInto(target);
  select(target.id);
  await settle(3);
  ok($("#rd_meta").querySelector("[data-cdav]"), "a task_* entry has a reminders chip in the reader");
  click($("#rd_meta").querySelector("[data-cdav]"));
  await settle(6);
  ok($("#dlg").classList.contains("cdav"), "which opens the reminders panel");
  ok($("#cdDue"), "a task_personal is a list of its own in Reminders: the fields, straight away");
  has($(".cdsub").textContent, "list Personal", "and the panel names its list");
  closeOv();
  // Its list deleted in Reminders: hidden there, and the panel says how back.
  CDAV_HIDDEN.task_personal = true;
  click($("#rd_meta").querySelector("[data-cdav]"));
  await settle(6);
  has($("#dlg").textContent, "was deleted in Reminders", "a task whose list was deleted says so");
  click($("#cdMake"));
  await settle(10);
  eq(dbFind(target.id).kind, "task", "Make it a task changes the kind");
  ok($("#cdDue") && $("#cdRaw"), "and the panel shows the fields");
  eq($("#cdRaw").value, "", "a task nobody synced keeps no lines");
  change($("#cdDue"), "2026-10-07T09:00");
  has($("#cdRaw").value, "DUE:2026", "setting the due date writes a DUE line into the text");
  has($("#cdRaw").value, "Z", "in UTC");
  change($("#cdPri"), "1");
  has($("#cdRaw").value, "PRIORITY:1", "priority high is PRIORITY:1");
  click($("#cdAtDue"));
  has($("#cdRaw").value, "BEGIN:VALARM", "At due adds an alert");
  has($("#cdRaw").value, "TRIGGER;VALUE=DATE-TIME:", "an absolute one, as Reminders writes them");
  eq($("#cdAlarms").querySelectorAll("[data-alarm]").length, 1, "and lists it");
  // the other way: typed text drives the fields
  input($("#cdRaw"), $("#cdRaw").value.replace("PRIORITY:1", "PRIORITY:9") + "\nRRULE:FREQ=WEEKLY\nX-APPLE-SORT-ORDER:5");
  eq($("#cdPri").value, "9", "typing PRIORITY:9 sets the priority to low");
  eq($("#cdRep").value, "WEEKLY", "and an RRULE the repeat");
  click($("#cdSave"));
  await settle(10);
  var cdLast = DBLOG.filter(function (l) { return /^PUT \/entries\/\d+\/caldav/.test(l); }).pop() || "";
  has(cdLast, '"etag":"\\"' + target.id + '-0\\""', "the save sends the ETag it read");
  has(CDAV[target.id].extra, "X-APPLE-SORT-ORDER:5", "every line is saved, the unknown ones too");
  has(CDAV[target.id].extra, "DUE:2026", "with the due date");
  ok($("#cdSave").disabled, "and the panel is clean again");
  has($("#cdIcs").textContent, "DUE:2026", "what Reminders receives shows the new line");
  // a TZID due, as Reminders sends it, reads as that zone's wall clock
  eq(cdavWhen(cdavLine("DUE;VALUE=DATE:20261010")).allDay, true, "a DATE is all day");
  eq(cdavWhen(cdavLine("DUE:20261010T090000Z")).date.getTime(), Date.UTC(2026, 9, 10, 9), "a Z is UTC");
  ok(cdavWhen(cdavLine("DUE;TZID=Europe/Helsinki:20261010T090000")).date instanceof Date, "a TZID parses");
  eq(cdavTrigger(["BEGIN:VALARM", "TRIGGER;RELATED=END:-PT15M", "END:VALARM"], { from: 0, to: 2 }),
     "15m before due", "a relative alert reads in words");
  // Reminders wrote in between: theirs is reloaded, mine is offered back
  input($("#cdRaw"), "DUE:20261111T090000Z");
  CDAV_NEXT = 412;
  click($("#cdSave"));
  await settle(12);
  has($("#toast").textContent, "changed", "a 412 says Reminders changed it meanwhile");
  has($("#cdRaw").value, "X-APPLE-SORT-ORDER", "and shows what the server holds");
  // a refused line is the server's message, and nothing is lost
  input($("#cdRaw"), "SUMMARY:nope");
  click($("#cdSave"));
  await settle(8);
  has($("#toast").textContent, "SUMMARY", "a line the entry owns is refused with the server's reason");
  eq($("#cdRaw").value, "SUMMARY:nope", "and the text stays as typed");
  closeOv();
  has($("#toast").textContent, "not saved", "closing with unsaved edits offers them back");
  ok(cd === null, "and the panel's state goes with it");
  // spoken
  setForm(target); setClean(); hideToast();
  voiceHeard("computer due tomorrow at 9 30");
  await settle(10);
  var cdTom = new Date(); cdTom.setDate(cdTom.getDate() + 1); cdTom.setHours(9, 30, 0, 0);
  has(CDAV[target.id].extra, "DUE:" + cdavDateVal(cdTom, false).value, "'due tomorrow at 9 30' sets DUE to tomorrow 09:30");
  has(CDAV[target.id].extra, "X-APPLE-SORT-ORDER", "keeping every other line");
  eq(cdavSpoken("friday at 5 pm").getHours(), 17, "'friday at 5 pm' is 17:00");
  eq(cdavSpoken("friday at 5 pm").getDay(), 5, "on a friday");
  eq(cdavSpoken("at nine thirty").getMinutes(), 30, "'nine thirty' is :30");
  eq(cdavSpoken("whenever"), null, "no time, no date");
  voiceHeard("computer clear the due date");
  await settle(10);
  ok(!/DUE:/.test(CDAV[target.id].extra), "'clear the due date' drops DUE");
  voiceHeard("computer reminders");
  await settle(8);
  ok($("#dlg").classList.contains("cdav"), "'computer, reminders' opens the panel");
  closeOv();
  await api("/entries/" + target.id, { method: "PUT", body: { kind: cdWas } });
  await refetchInto(target);
  delete CDAV[target.id];
  unplant(target);

  console.log("\nsection B: " + TEST.asserts + " assertions, " + TEST.fails.length + " failures");
  globalThis.__phaseB = true;
})().catch(function (e) { console.log("SUITE B THREW: " + e + "\n" + (e && e.stack)); });

/* ===================== suite C: editing + data safety ===================== */
(async function () {
  if (!await waitFlag("__phaseB")) return;
  TEST.confirmAnswer = true;

  console.log("\n-- autosave: a pause in the typing saves it, quietly --");
  autosaveMs = 3000;
  var asRow = st.all.filter(function (e) { return !e.deleted; })[5];
  select(asRow.id);
  await settle(4);
  setRead(false);
  hideToast();
  var asTa = $("#content"), asBefore = DBLOG.length;
  var asPuts = function () {
    return DBLOG.slice(asBefore).filter(function (l) { return l.indexOf("PUT") === 0; });
  };
  input(asTa, asRow.content + " one");
  runTimers(2000);
  await pump(100);
  eq(asPuts().length, 0, "two seconds into the pause nothing is sent");
  input(asTa, asRow.content + " one two");
  runTimers(2000);
  await pump(100);
  eq(asPuts().length, 0, "and each keystroke starts the wait over");
  runTimers(1100);
  eq(document.body.dataset.save, "saving", "the head says SAVING while it is on the wire");
  await settle(3);
  eq(asPuts().length, 1, "three seconds of quiet send one PUT");
  eq(dbFind(asRow.id).content, asRow.content, "carrying what was typed");
  ok(!document.body.classList.contains("dirty"), "and the form is clean again");
  ok($("#toast").textContent.indexOf("saved #") < 0, "without a toast");
  eq(asTa.value, asRow.content, "the text is left as it was typed");

  console.log("-- typing on while it is in flight keeps the new words --");
  var asBase = asRow.content;
  asBefore = DBLOG.length;
  input(asTa, asBase + " three");
  runTimers(3100);                   // the autosave starts ...
  input(asTa, asBase + " three four");   // ... and they are still typing
  await settle(6);
  eq(asTa.value, asBase + " three four", "the landing save did not rewrite the form");
  eq(dbFind(asRow.id).content, asBase + " three four", "the next pause saved the rest");
  ok(!document.body.classList.contains("dirty"), "and then it is clean");
  ok(asPuts().length >= 1, "each pause was a PUT of its own");

  console.log("-- a new entry: never empty, then autosaved like any other (design P8) --");
  asBefore = DBLOG.length;
  var asPosts = function () { return DBLOG.slice(asBefore).filter(function (l) { return l.indexOf("POST") === 0; }).length; };
  newEntry();
  eq(document.activeElement, asTa, "+ puts the caret in the text box, in the tap");
  eq($("#edchip").textContent, "Write something first", "an empty draft's chip says what it needs");
  click($("#edchip"));
  await settle(2);
  runTimers(3100);
  await settle(2);
  eq(asPosts(), 0, "nothing to save: no POST, not from the chip, not from a pause");
  input(asTa, "   ");
  runTimers(3100);
  await settle(2);
  eq(asPosts(), 0, "blanks are not words");
  input(asTa, "a draft worth a row");
  eq($("#edchip").textContent, "● Editing", "with words it is Editing, like any entry");
  runTimers(3100);
  input(asTa, "a draft worth a row, and more");   // still typing while the create is on the wire
  await settle(6);
  eq(asPosts(), 1, "a pause creates the row, once");
  ok(!st.isNew && st.sel && dbFind(st.sel.id), "the editor is that row now");
  var asNewId = st.sel.id;
  eq(asTa.value, "a draft worth a row, and more", "the create did not rewrite the form");
  eq(document.activeElement, asTa, "nor take the caret away");
  ok(st.byId.has(asNewId), "the list has the row");
  runTimers(3100);
  await settle(6);
  eq(dbFind(asNewId).content, "a draft worth a row, and more", "what was typed in flight went as an update");
  eq(asPosts(), 1, "not as a second row");
  ok(!document.body.classList.contains("dirty"), "and then it is clean");

  console.log("-- a scaffold waits for a first edit (design P8) --");
  asBefore = DBLOG.length;
  duplicate();
  runTimers(3100);
  await settle(4);
  eq(asPosts(), 0, "a copy is not written by a pause");
  eq($("#edchip").textContent, "● New · Save", "its chip still asks for the Save");
  input(asTa, asTa.value + " edited");
  runTimers(3100);
  await settle(6);
  eq(asPosts(), 1, "a first edit makes it the writer's, and the pause saves it");
  ok(!st.isNew, "it is a row");

  console.log("-- leaving a new entry: words saved on the way, a scaffold not --");
  asBefore = DBLOG.length;
  newEntry();
  input(asTa, "left at once");
  var asAsked = TEST.log.length;
  ok(closeEditor(), "the door opens, nothing asks");
  ok(!st.isNew && !st.sel, "out of it in the same tap");
  await settle(6);
  eq(asPosts(), 1, "and the words were created on the way");
  ok(!TEST.log.slice(asAsked).some(function (l) { return l.indexOf("confirm:") === 0; }), "with no browser question");
  ok(st.all.some(function (e) { return e.content === "left at once"; }), "into the list");
  asBefore = DBLOG.length;
  newEntry();
  closeEditor();
  continueEntry(st.all[0]);
  closeEditor();
  await settle(4);
  eq(asPosts(), 0, "an empty draft and an untouched continuation are not written");
  has($("#toast").textContent, "not kept", "the scaffold's toast says so");
  ok($("#toast").querySelector(".tact") && $("#toast").querySelector(".tact").textContent === "Reopen", "with a way back");
  click($("#toast").querySelector(".tact"));
  ok(st.isNew && /continues/.test(asTa.value), "which reopens it");
  setClean(); closeEditor(); hideToast();
  autosaveMs = 0;

  // iOS Safari reads a field's id, name, placeholder and aria-label for its
  // contact AutoFill; one contact word makes the page a contact form
  // (test/check.py has the full rule, over the source; this is the open editor)
  console.log("\n-- 4.x the open editor's fields carry no contact word (iOS AutoFill Contact) --");
  var acLive = st.all.filter(function (e) { return !e.deleted; })[2];
  select(acLive.id);
  setRead(false);
  ok(!$("#e_title"), "the heading field is no longer #e_title");
  var acRe = /(^|[^a-z])(name|title|first|last|surname|email|phone|tel|address|street|city|zip|postal|country|company|organi[sz]ation|job|location)/i;
  var acBad = [];
  document.querySelectorAll("input, textarea").forEach(function (el) {
    if (/^(checkbox|radio|file|range|hidden|button|color)$/.test(el.getAttribute("type") || "")) return;
    ["id", "name", "placeholder", "aria-label"].forEach(function (a) {
      var v = el.getAttribute(a) || "";
      if (acRe.test(v.replace(/([a-z])([A-Z])/g, "$1 $2"))) acBad.push(a + "=" + v);
    });
  });
  eq(acBad.join(" · "), "", "no text field in the page says name, title or another contact word");
  eq($("#e_head").getAttribute("placeholder"), "Heading", "the heading reads Heading, not Title");
  eq(fieldEl("title"), $("#e_head"), "and the title column still finds its field");
  closeEditor();

  console.log("\n-- 4.x save sends only what changed --");
  var live = st.all.filter(function (e) { return !e.deleted; })[3];
  select(live.id);
  setRead(false);
  var before = DBLOG.length;
  $("#e_head").value = "harness title " + live.id;
  markDirty();
  await save();
  await settle(6);
  var puts = DBLOG.slice(before).filter(function (l) { return l.indexOf("PUT") === 0; });
  eq(puts.length, 1, "exactly one PUT");
  has(puts[0], '"title"', "the changed field is in the body");
  ok(puts[0].indexOf("content") < 0, "untouched fields are not");
  ok(DBLOG.indexOf("!! PUT carried last_modified_at_utc") < 0,
     "last_modified_at_utc is never sent on PUT");
  eq(dbFind(live.id).title, "harness title " + live.id, "the server row changed");
  eq($("#edbody").style.display, "flex", "saving leaves an open editor open");
  var other = st.all.filter(function (e) { return !e.deleted && e.id !== live.id; })[0];
  select(other.id);
  eq($("#readbody").style.display, "block", "but a different entry opens in the reader");
  select(live.id);

  /* Ctrl+S then Escape, with the focus still in the content box: the blur
     Escape does fires one last `change` carrying the value the save just wrote,
     and taking that at face value used to re-dirty a form that was already on
     the server — so the first Escape refused to move and the entry had to be
     saved twice. */
  console.log("-- 4.2 Escape leaves a saved entry on the first press --");
  select(live.id);
  setRead(false);
  eq(document.activeElement, $("#content"), "editing puts the focus in the content box");
  input($("#content"), "escape test body " + live.id);
  ok(document.body.classList.contains("dirty"), "typing marks it unsaved");
  await save();
  await settle(6);
  ok(!document.body.classList.contains("dirty"), "the save leaves the form clean");
  key("Escape", { target: $("#content") });
  ok(!document.body.classList.contains("dirty"),
     "and the change fired by the blur does not re-dirty what was just saved");
  ok($("#edbody").style.display === "flex" && document.activeElement !== $("#content"),
     "the first Escape lets go of the text and stays in the editor (P13)");
  ok(!$("#eschint").hidden, "saying press e to type");
  key("l"); key("o");
  ok(document.body.dataset.pane === "edit" && !st.isNew && st.sel.id === live.id,
     "letters straight after it are not commands");
  key("Escape");
  eq($("#readbody").style.display, "block", "and the second Escape reads, no save owed");
  eq(dbFind(live.id).content, "escape test body " + live.id, "the edit did reach the server");

  /* No write path drops the completion index by hand any more: the index keys
     itself on st.all's shape and st.bodyGen, and every write either adds a row
     or lands a body. If that ever stops being true, the popup starts offering
     names out of a journal that has moved on. */
  /* ---------- threads ----------
     Continue writes a new entry whose first line links back; saved, the two
     are a thread the reader shows, the list flags, and a third continues. */
  console.log("-- threads --");
  eq(threadParentOf("↪ continues [The start](((42)))\n\nmore"), 42, "the line Continue writes is read as the link back");
  eq(threadParentOf("  - continues [x](((7))) and so on"), 7, "a bulleted one typed by hand too");
  eq(threadParentOf("Some text first.\n↪ continues [x](((7)))"), 0, "but only on the first line");
  eq(threadParentOf("it continues [x](((7)))"), 0, "and only when it says so at the start");
  var tA = st.all.filter(function (e) { return !e.deleted && !needsBody(e) && (e.title || "").trim() &&
                                               e.title !== "HTTP Entry" && !threadParentOf(e.content); })[5];
  TEST.confirmAnswer = true;
  closeEditor();
  select(tA.id);
  ok($("#bCont").style.display !== "none", "a saved entry offers Continue");
  click($("#bCont"));
  ok(st.isNew, "Continue opens a new entry");
  has($("#content").value, "continues [" + tA.title.trim().replace(/[[\]\n]/g, " ").slice(0, 120) + "](((" + tA.id + ")))",
      "whose first line links back by id, under the entry's title");
  eq($("#e_kind").value, tA.kind || "personal_log", "in the same kind");
  eq($("#e_head").value, "", "with the title left to the writer");
  ok(!document.body.classList.contains("dirty"), "and nothing to discard until something is written");
  has($("#edtitle").textContent, "continues #" + tA.id, "the header says what it continues");
  ok($("#bCont").style.display === "none", "a new entry has nothing to continue yet");
  input($("#content"), $("#content").value + "The second part of the story.");
  $("#e_head").value = "Part two " + tA.id;
  markDirty();
  await save();
  await settle(6);
  var tB = st.sel;
  ok(tB && tB.id !== tA.id && !st.isNew, "saved as an entry of its own (#" + (tB && tB.id) + ")");
  eq(threadParentOf(tB.content), tA.id, "carrying the link back");
  setRead(true);
  await drainExtras();
  var thrIds = function () {
    var ids = [];
    $("#rd_thread").querySelectorAll(".blrow").forEach(function (b) { ids.push(+b.dataset.id); });
    return ids.join(",");
  };
  eq(thrIds(), tA.id + "," + tB.id, "the reader shows the thread, from its start");
  ok($("#rd_thread").querySelector(".blrow.here[data-id=\"" + tB.id + "\"]"), "with this entry marked");
  has(flagSpans(tB), "#" + tA.id, "a continuation's row is flagged with what it continues");
  // the third, by key
  key("w");
  ok(st.isNew && $("#content").value.indexOf("(((" + tB.id + ")))") >= 0, "w continues the open entry");
  input($("#content"), $("#content").value + "And the third.");
  await save();
  await settle(6);
  var tC = st.sel;
  select(tA.id);
  await drainExtras();
  eq(thrIds(), tA.id + "," + tB.id + "," + tC.id, "the start lists every entry after it, in order");
  ok(!$("#rd_back").querySelector(".blrow[data-id=\"" + tB.id + "\"]"),
     "and its continuation is not listed again under “Linked from”");
  has($("#rd_thread").textContent, "1 of 3", "it says where in the thread this entry is");
  // a branch: the start continued a second time
  click($("#bCont"));
  input($("#content"), $("#content").value + "A different direction.");
  await save();
  await settle(6);
  var tD = st.sel;
  setRead(true);
  await drainExtras();
  eq(thrIds(), [tA.id, tB.id, tC.id, tD.id].join(","), "a branch joins the thread after the older one's line");
  // read the thread
  click($("#rd_thread").querySelector("[data-thr=\"read\"]"));
  ok($("#ov").classList.contains("on") && $("#throut"), "Read the thread opens it as one read");
  eq($("#throut").querySelectorAll(".dayent").length, 4, "every entry of it");
  ok($("#throut").textContent.indexOf("And the third.") >= 0, "with their bodies");
  ok($("#throut").textContent.indexOf("continues") < 0, "minus the link lines, which the order already says");
  click($("#throut").querySelector(".thrgo[data-id=\"" + tC.id + "\"]"));
  ok(!$("#ov").classList.contains("on") && st.sel === tC, "a header opens its entry");
  await drainExtras();
  click($("#rd_thread").querySelector("[data-thr=\"cont\"]"));
  ok(st.isNew && $("#content").value.indexOf("(((" + tD.id + ")))") >= 0,
     "Continue the thread continues its newest entry, wherever it is opened from");
  closeEditor();
  // a deleted middle entry splits it
  tB.deleted = 1;
  st.bodyGen++;
  select(tC.id);
  await drainExtras();
  eq($("#rd_thread").innerHTML, "", "with the entry it continued deleted, an entry stands alone");
  tB.deleted = 0;
  st.bodyGen++;
  closeEditor();

  console.log("-- the [[link]] index invalidates itself on a save --");
  var idxBefore = wikiIndex();
  var linkName = "Harness Index Target " + live.id;
  select(live.id);
  setRead(false);
  input($("#content"), "a link to [[" + linkName + "]]");
  await save();
  await settle(6);
  var idxAfter = wikiIndex();
  ok(idxAfter !== idxBefore, "a save rebuilds the index rather than serving the old one");
  ok(idxAfter.some(function (it) { return it.lc === linkName.toLowerCase(); }),
     "and the name the save wrote is a link target from now on");

  console.log("-- 4.3 concurrent-edit guard --");
  select(live.id);
  setRead(false);
  dbFind(live.id).last_modified_at_utc = "2088-08-08 08:08:08";   // someone else wrote
  dbFind(live.id).title = "written by the cli";
  $("#e_head").value = "my version";
  markDirty();
  var before2 = DBLOG.length;
  var saving2 = save();                // "Load theirs" — keep the server version
  ok(await answerDialog(false), "the conflict asks through the themed dialog");
  await saving2;
  await settle(6);
  ok(DBLOG.slice(before2).every(function (l) { return l.indexOf("PUT") !== 0; }),
     "cancelling the conflict sends no PUT");
  eq(st.byId.get(live.id).title, "written by the cli", "the server version was loaded instead");
  eq($("#e_head").value, "written by the cli", "and shown in the form");
  ok(!document.body.classList.contains("dirty"), "no longer dirty");

  select(live.id);
  setRead(false);
  dbFind(live.id).last_modified_at_utc = "2077-07-07 07:07:07";
  $("#e_head").value = "mine wins";
  markDirty();
  var saving3 = save();                // "Overwrite"
  ok(await answerDialog(true), "and asks again on the next clash");
  await saving3;
  await settle(6);
  eq(dbFind(live.id).title, "mine wins", "confirming the conflict does overwrite");

  console.log("-- 4.4 undo after delete --");
  var victim = st.all.filter(function (e) { return !e.deleted; })[7];
  select(victim.id);
  var deleting = delOrRestore();
  ok(await answerDialog(true), "delete asks through the themed dialog too");
  await deleting;
  await settle(6);
  eq(dbFind(victim.id).deleted, 1, "soft-deleted on the server");
  var undo = $("#toast").querySelector("button");
  ok(undo, "the toast offers an Undo");
  eq(undo.textContent, "Undo", "labelled Undo");
  click(undo);
  await settle(6);
  eq(dbFind(victim.id).deleted, 0, "Undo restored it");
  eq(st.byId.get(victim.id).deleted, 0, "and the cached row agrees");

  /* ---------- 4.4b joining several entries into one ----------
     The oldest of the picked rows keeps everything that identifies it — its id,
     its kind, its creation time — and gains the others' text, each behind the
     stamp it was written at. The rest leave the journal the soft way, so the
     whole thing is one Undo away from never having happened. */
  console.log("-- 4.4b join several entries --");
  // from the list as shown: a row of st.all a filter or the default view
  // leaves out is never drawn, and has no box to tick (picked from st.all,
  // run as of 2026-09-01 00:30, the picked row had no element and this threw)
  var jpool = st.view.filter(function (e) { return !e.deleted && e.content; }).slice(30, 33);
  eq(jpool.length, 3, "three entries to join");
  var jsorted = jpool.slice().sort(function (a, b) {
    return a.created_at_utc < b.created_at_utc ? -1 : a.created_at_utc > b.created_at_utc ? 1 : a.id - b.id;
  });
  var jold = jsorted[0], jnew = jsorted[jsorted.length - 1];
  var oldContent = jold.content, oldCreated = jold.created_at_utc, oldKind = jold.kind;
  var newContent = jnew.content;

  pickMode(true);
  // one screen is drawn at once and the rest a frame at a time as the list is
  // scrolled, which the shim cannot do (it has no layout); draw these by hand
  for (var jr = 0; jr < jpool.length; jr++) renderTo(st.view.indexOf(jpool[jr]));
  ok(st.picking, "the list goes into picking mode");
  ok($("#list").querySelector(".pkbox"), "and every row grows a box");
  for (var jp = 0; jp < jpool.length; jp++) pickToggle(jpool[jp].id);
  eq(st.pick.size, 3, "three rows picked");
  has($("#pkcount").textContent, "3", "the bar counts them");
  ok(!$("#pkjoin").disabled, "and offers the join");
  ok($("#list").querySelector('.item[data-id="' + jold.id + '"]').classList.contains("pick"),
     "a picked row says so");
  pickToggle(jold.id);
  eq(st.pick.size, 2, "picking the same row again unpicks it");
  pickToggle(jold.id);

  var joining = mergePicked();
  ok(await answerDialog(true), "the join asks before it writes");
  await joining;
  await settle(6);

  var joined = dbFind(jold.id);
  eq(joined.deleted, 0, "the oldest entry stays in the journal");
  eq(joined.created_at_utc, oldCreated, "keeping its creation time");
  eq(joined.kind, oldKind, "and its kind");
  eq(dbFind(jnew.id).deleted, 1, "the newer ones are soft-deleted");
  has(joined.content, oldContent.replace(/\s+$/, ""), "its own text is still there");
  has(joined.content, newContent.replace(/\s+$/, ""), "with the newer entry's text folded in");
  has(joined.content, localOf(jnew.created_at_utc), "behind the stamp that entry was written at");
  has(joined.content, "#" + jnew.id, "and the id it used to have");
  ok(!st.picking, "the mode drops once the join is done");
  eq(st.pick.size, 0, "and the picks with it");
  eq(st.sel.id, jold.id, "the joined entry is the one left open");

  var junk = $("#toast").querySelector("button");
  ok(junk && junk.textContent === "Undo", "the toast offers an Undo");
  click(junk);
  await settle(6);
  eq(dbFind(jold.id).content, oldContent, "Undo put the original text back");
  eq(dbFind(jnew.id).deleted, 0, "and the entries it swallowed are back in the journal");

  /* ---------- changing several at once ----------
     Kind, schedule and delete over the picks: one write per row, only the
     field that changes, and an Undo that writes every old value back. */
  console.log("-- bulk kind, schedule, delete --");
  closeEditor();
  var bpool = st.all.filter(function (e) { return !e.deleted && e.kind !== "bulk_kind"; }).slice(40, 43);
  var bKinds = bpool.map(function (e) { return e.kind; });
  pickMode(true);
  paintPick();
  ok($("#pkkind").disabled && $("#pksched").disabled && $("#pkdel").disabled, "with nothing picked, nothing to change");
  bpool.forEach(function (e) { pickToggle(e.id); });
  ok(!$("#pkkind").disabled && !$("#pksched").disabled && !$("#pkdel").disabled, "three picked: kind, schedule and delete are offered");
  has($("#pkdel").textContent, "3", "the delete counts what it would take");
  // the kind
  click($("#pkkind"));
  ok($("#ov").classList.contains("on") && $("#bk_kind"), "Kind… asks for the kind");
  ok($("#bk_chips").querySelector(".kc"), "with the quick kinds to tap");
  var before = DBLOG.length;
  input($("#bk_kind"), "bulk_kind");
  click($("#bk_ok"));
  await settle(6);
  var bPuts = DBLOG.slice(before).filter(function (l) { return l.indexOf("PUT") === 0; });
  eq(bPuts.length, 3, "one PUT a row");
  ok(bPuts.every(function (l) { return /\{"kind":"bulk_kind"\}$/.test(l); }), "carrying the kind and nothing else");
  ok(bpool.every(function (e) { return dbFind(e.id).kind === "bulk_kind"; }), "every row is the new kind on the server");
  ok(bpool.every(function (e) { return st.byId.get(e.id).kind === "bulk_kind"; }), "and here");
  ok(st.picking && st.pick.size === 3, "the picks stay, for the next change");
  var kUndo = $("#toast").querySelector("button");
  ok(kUndo && kUndo.textContent === "Undo", "the toast offers an Undo");
  click(kUndo);
  await settle(6);
  ok(bpool.every(function (e, i) { return dbFind(e.id).kind === bKinds[i]; }), "which gives each row its own kind back");
  // the schedule
  var bSched = bpool.map(function (e) { var r = dbFind(e.id); return (r.start_date || "") + "|" + (r.end_date || ""); });
  click($("#pksched"));
  ok($("#bs_day") && $("#bs_from"), "Schedule… asks for a day and a time");
  $("#bs_day").value = "2026-11-07"; $("#bs_from").value = "10:30"; $("#bs_to").value = "09:00";
  click($("#bs_ok"));
  has($("#bs_err").textContent, "after", "an end before the start is refused");
  $("#bs_to").value = "12:00";
  before = DBLOG.length;
  click($("#bs_ok"));
  await settle(6);
  var wantS = utcOfDate(new Date(2026, 10, 7, 10, 30)), wantE = utcOfDate(new Date(2026, 10, 7, 12, 0));
  ok(bpool.every(function (e) { return dbFind(e.id).start_date === wantS && dbFind(e.id).end_date === wantE; }),
     "every row is scheduled for that span, in UTC (" + wantS + ")");
  eq(DBLOG.slice(before).filter(function (l) { return l.indexOf("PUT") === 0; }).length, 3, "one PUT a row");
  click($("#toast").querySelector("button"));
  await settle(6);
  ok(bpool.every(function (e, i) { var r = dbFind(e.id); return (r.start_date || "") + "|" + (r.end_date || "") === bSched[i]; }),
     "Undo puts each row's old schedule back");
  click($("#pksched"));
  click($("#bs_clear"));
  await settle(6);
  ok(bpool.every(function (e) { return dbFind(e.id).start_date === ""; }), "Unschedule clears them");
  // delete, and its undo
  var bDel = bulkDelete();
  ok(await answerDialog(true), "a bulk delete asks first");
  await bDel;
  await settle(6);
  ok(bpool.every(function (e) { return dbFind(e.id).deleted === 1; }), "every picked row is soft-deleted");
  ok(!st.picking, "and the mode drops");
  click($("#toast").querySelector("button"));
  await settle(6);
  ok(bpool.every(function (e) { return dbFind(e.id).deleted === 0; }), "Undo brings them all back");
  // All, and the ceiling
  pickMode(true);
  click($("#pkall"));
  eq(st.pick.size, st.view.length, "All picks every row the list shows");
  if (st.view.length > BULK_MAX) {
    before = DBLOG.length;
    bulkKind();
    eq(DBLOG.length, before, "and more than " + BULK_MAX + " is refused before anything is written");
    ok(!$("#ov").classList.contains("on"), "without asking for a kind");
  }
  pickMode(false);

  console.log("-- 4.5 duplicate --");
  var srcE = st.all.filter(function (e) { return !e.deleted && e.content; })[2];
  select(srcE.id);
  duplicate();
  ok(st.isNew, "duplicate opens a new entry");
  eq($("#content").value, srcE.content, "content carried over");
  eq($("#e_kind").value, srcE.kind, "kind carried over");
  eq($("#e_deleted").value, "0", "the copy is live");
  ok(document.body.classList.contains("dirty"), "and starts dirty, so it cannot be lost");
  eq($("#edbody").style.display, "flex", "a new entry always shows the form");
  eq($("#rwmode").style.display, "none", "with no read toggle");
  eq($("#bDup").style.display, "none", "and no duplicate button");

  console.log("-- 4.1 drafts --");
  $("#content").value = "draft body that must survive";
  markDirty();
  runTimers();
  var draft = JSON.parse(localStorage.getItem("lcars.draft"));
  ok(draft, "a draft was written");
  eq(draft.v.content, "draft body that must survive", "with the content");
  eq(draft.id, null, "marked as a new entry");
  setClean();
  ok(!localStorage.getItem("lcars.draft"), "going clean clears the draft");

  localStorage.setItem("lcars.draft", JSON.stringify(
    { id: srcE.id, v: { kind: srcE.kind, title: "restored title", content: "restored body",
      value_int: 0, value_float: 0, done_bool: "0", deleted: "0",
      created_at_utc: srcE.created_at_utc, last_modified_at_utc: "" }, at: Date.now() - 120000 }));
  draftOffered = false;
  offerDraft();
  var rest = $("#toast").querySelector("button");
  ok(rest && rest.textContent === "Restore", "a stored draft is offered back");
  has($("#toast").textContent, "#" + srcE.id, "naming the entry it belongs to");
  click(rest);
  eq($("#e_head").value, "restored title", "restoring fills the form");
  eq($("#content").value, "restored body", "including the content");
  ok(document.body.classList.contains("dirty"), "and it counts as unsaved");
  eq($("#edbody").style.display, "flex", "a dirty entry always shows the form");
  setClean();
  select(srcE.id);

  console.log("-- 1.4 boolean toggles --");
  // an entry not yet done: Done on a done one changes nothing, so nothing is
  // dirty. The fixture is the journal's newest rows, and those are often the
  // crew's inbox messages, ticked done when delivered (0.154.0's deploy).
  var togE = st.all.filter(function (e) { return !e.deleted && !Number(e.done_bool); })[0];
  select(togE.id);
  setRead(false);
  var togDone = $("#tog_done");
  eq(togDone.children[0].classList.contains("on") || togDone.children[1].classList.contains("on"),
     true, "one side of the toggle is always lit");
  click(togDone.children[1]);
  eq($("#e_done_bool").value, "1", "clicking Done writes the hidden field");
  ok(togDone.children[1].classList.contains("on"), "and lights that side");
  ok(document.body.classList.contains("dirty"), "and marks the form dirty");
  click(togDone.children[0]);
  eq($("#e_done_bool").value, "0", "clicking Open writes it back");
  setClean();

  console.log("-- 4.7 a new entry hidden by filters --");
  setKinds(["sleep"]);
  refresh();
  newEntry();
  $("#e_kind").value = "harness_kind";
  $("#content").value = "hidden by filters";
  markDirty();
  await save();
  await settle(6);
  has($("#toast").textContent, "hidden by the current filters", "the user is told");
  var show = $("#toast").querySelector("button");
  ok(show && show.textContent === "Show it", "with a way out");
  click(show);
  await settle(4);
  eq(st.kinds.length, 0, "which clears the offending filter");
  ok(st.view.some(function (e) { return e.kind === "harness_kind"; }), "and reveals the entry");

  console.log("-- 4.2 stats --");
  openStats();
  ok($("#ov").classList.contains("on"), "stats dialog opens");
  has($("#dlg").innerHTML, "scard", "summary cards present");
  has($("#dlg").innerHTML, "sbar", "bars present");
  has($("#dlg").textContent, "longest streak", "streaks reported");
  var kbar = $("#dlg").querySelector(".sbar[data-k]");
  ok(kbar, "kind bars are clickable");
  click(kbar);
  eq(st.kinds.join(","), kbar.dataset.k, "clicking one filters to that kind");
  ok(!$("#ov").classList.contains("on"), "and closes the dialog");
  clearFilters();

  console.log("-- 4.3 the statistics read the journal as data --");
  // The chart over time needs two months, and the newest 400 real rows can
  // all sit in one (they did, in September 2026). The oldest live row is moved
  // back a quarter for this block and put back after it.
  var liveRows = st.all.filter(function (e) { return !e.deleted && e.created_at_utc; });
  var aged = liveRows[liveRows.length - 1], agedAt = aged.created_at_utc;
  var span = {};
  liveRows.forEach(function (e) { span[localOf(e.created_at_utc).slice(0, 7)] = 1; });
  if (Object.keys(span).length < 2) {
    var ay = +agedAt.slice(0, 4), am = +agedAt.slice(5, 7) - 3;
    if (am < 1) { am += 12; ay--; }
    aged.created_at_utc = ay + "-" + (am < 10 ? "0" : "") + am + agedAt.slice(7);
  }
  openStats();
  has($("#dlg").textContent, "Findings", "the findings come first, in sentences");
  has($("#dlg").textContent, "fullest day", "including the fullest day");
  ok($("#dlg").querySelector(".sdonut path[data-k]"), "the kinds are a donut whose slices filter");
  ok($("#dlg").querySelector("svg[data-mode=share]") && $("#dlg").querySelector("svg[data-mode=count]"),
     "the journal over time, as shares and as counts");
  var segBtn = $("#dlg").querySelector('[data-seg="count"]');
  click(segBtn);
  ok(!$("#dlg").querySelector("svg[data-mode=count]").hidden, "the toggle shows the counts");
  ok($("#dlg").querySelector("svg[data-mode=share]").hidden, "and hides the shares");
  ok($("#st_words"), "the words are read after the dialog is up");
  for (var w = 0; w < 400 && $("#st_words"); w++) { await pump(2); runTimers(5); }
  ok(!$("#st_words"), "and filled in once read");
  var hday = $("#dlg").querySelector("rect[data-day]");
  ok(hday, "the year is a heatmap of days");
  click(hday);
  eq(dayOpen, hday.dataset.day, "and a day of it opens that day");
  closeOv();
  aged.created_at_utc = agedAt;

  // the statistics answer the question the list is asking
  var liveN = st.all.filter(function (e) { return !e.deleted; }).length;
  var someKind = st.all.filter(function (e) { return !e.deleted && e.kind; })[0].kind;
  var kindN = st.all.filter(function (e) { return !e.deleted && e.kind === someKind; }).length;
  setKinds([someKind]);
  refresh();
  openStats();
  ok($("#dlg").querySelector(".sfilt"), "a filtered list gets filtered statistics, and says so");
  has($("#dlg").querySelector(".sfilt").textContent, someKind, "naming the filter");
  eq($("#dlg").querySelector(".scard b").textContent, kindN.toLocaleString(), "counting only that kind's entries");
  has($("#dlg").querySelector(".sfilt").textContent, "of " + liveN.toLocaleString(), "out of the whole journal");
  click($("#dlg").querySelector('[data-act="whole"]'));
  eq($("#dlg").querySelector(".scard b").textContent, liveN.toLocaleString(), "the banner's button shows the whole journal");
  ok($("#dlg").querySelector('[data-act="scoped"]'), "and offers the filters back");
  click($("#dlg").querySelector('[data-act="scoped"]'));
  eq($("#dlg").querySelector(".scard b").textContent, kindN.toLocaleString(), "which it applies again");
  closeOv();
  clearFilters();
  openStats();
  ok(!$("#dlg").querySelector(".sfilt"), "with nothing filtered there is no banner");
  closeOv();

  // import bursts: a few hundred rows stamped with one minute are not writing
  var keepAll = st.all;
  var mk = function (id, kind, at, content, title) {
    return { id: id, kind: kind, title: title || "HTTP Entry", content: content || "x", created_at_utc: at,
             last_modified_at_utc: at, deleted: 0, content_length: (content || "x").length };
  };
  var fake = [];
  for (var b = 0; b < 8; b++) fake.push(mk(900 + b, "page", "2026-03-04 10:15:0" + b));
  fake.push(mk(950, "personal_log", "2026-03-05 09:00:00", "one two  three\nfour"));
  fake.push(mk(951, "personal_log", "2026-03-05 18:30:00", ""));
  st.all = fake;
  var core = statsCore();
  st.all = keepAll;
  eq(core.rows.length, 10, "every live row is counted");
  eq(core.written.length, 2, "but eight rows in one minute are an import, not writing");
  eq(core.day.has(dayKey("2026-03-04 10:15:00")), false, "so the import's day is not a day written");
  eq(core.words, 4 + 9, "words are runs of non-space (" + core.words + ")");

  // sleep: a start and the end after it are a night; a lone end is not
  // stamps from the local clock: a night is a night where the sleeper is
  var at = function (d, h, m) { return fmtUtc(new Date(2026, 8, d, h, m || 0)); };
  var sl = [
    mk(1, kindOf("child_sleep"), at(1, 21), "start"), mk(2, kindOf("child_sleep"), at(2, 7), "end"),
    mk(3, kindOf("child_sleep"), at(2, 21, 30), "start"), mk(4, kindOf("child_sleep"), at(3, 7), "end"),
    mk(5, kindOf("child_sleep"), at(3, 21), "start"), mk(6, kindOf("child_sleep"), at(4, 6), "end"),
    mk(7, kindOf("child_sleep"), at(4, 8), "end"),
    mk(8, kindOf("child_sleep"), at(5, 21), "start"), mk(9, kindOf("child_sleep"), at(5, 21, 5), "end"),
    mk(10, "work_log", at(5, 21), "start"),
  ];
  var who = statSleep(sl);
  eq(who.length, 1, "one sleeper, read off the kind's shape");
  eq(who[0].nights.length, 3, "three nights: a stray end and a five-minute tap are not");
  eq(statClock(who[0].bed + 1020), "21:10", "to bed on average at ten past nine");
  var mins = who[0].nights.map(function (n) { return n.mins; }).sort().join(",");
  eq(mins, "540,570,600", "each as long as from its start to its end");
  // the roles' kinds are sleepers, vocabularies, drives and people whatever
  // they are named, beside the conventions (kinds.md 2.2)
  var stWas = kindMap.map;
  kindMap.map = new Map(roleRows().map(function (r) { return [r.role, Object.assign({}, r)]; }));
  [["child_sleep", "zz_naps"], ["child_vocab", "zz_words"], ["drive", "zz_car"], ["person", "zz_folk"]].forEach(function (p) {
    kindMap.map.get(p[0]).kind = p[1]; kindMap.map.get(p[0]).kinds = [p[1]];
  });
  eq(statSleep(sl.map(function (e) { return Object.assign({}, e, { kind: "zz_naps" }); })).length, 1,
     "a child_sleep role pointed at zz_naps is a sleeper");
  eq(statVocab([mk(1, "zz_words", "2026-09-01 10:00:00", "roșu", "roșu"), mk(2, "zz_words", "2026-09-02 10:00:00", "gaben", "galben"),
                mk(3, "zz_words", "2026-09-03 10:00:00", "foca", "foca")]).length, 1, "a child_vocab role's kind a vocabulary");
  eq(statDrives([mk(1, "zz_car", "2026-09-01 10:00:00", "start Home"), mk(2, "zz_car", "2026-09-01 10:40:00", "end Work")]).length, 1,
     "a drive role's kind a drive");
  kindMap.map = stWas;

  // drives: the place is its name, not its street or its postcode
  eq(statPlace("Willow Park Strada Fagului 100001 Exampleton Romania"), "Willow Park", "a named place loses its street");
  eq(statPlace("900001 900001 Valea Mare Romania"), "Valea Mare", "a postcode alone leaves the town");
  var tr = statDrives([mk(1, "drive", "2026-09-01 10:00:00", "start Home 123456 X Romania"),
                       mk(2, "drive", "2026-09-01 10:40:00", "end Northgate Strada Y 7 Z Romania")]);
  eq(tr.length, 1, "a start and an end are a trip");
  eq(tr[0].mins + " " + tr[0].to, "40 Northgate", "of their minutes, to where it ended");

  // vocabulary: the word and how it was said
  var vv = statVocab([mk(1, kindOf("child_vocab"), "2026-09-01 10:00:00", "roșu", "roșu"),
                      mk(2, kindOf("child_vocab"), "2026-09-02 10:00:00", "gaben", "galben"),
                      mk(3, kindOf("child_vocab"), "2026-09-03 10:00:00", "foca", "HTTP Entry")]);
  eq(vv.length, 1, "a vocab kind is a vocabulary");
  eq(vv[0].uniq + " " + vv[0].exact, "3 2", "three words, two said exactly (a placeholder title means the body is the word)");
  ok(vv[0].list[1].close > 0.8 && vv[0].list[1].close < 1, "and gaben is close to galben");
  eq(statPerson("Wilson, M. (Matthew)"), "Matthew Wilson", "an address-book name reads as a name");
  eq(statPerson("Marinescu, E.I. (Elena - Ioana)"), "Elena Marinescu", "first of a double first name");

  console.log("-- keyboard --");
  closeEditor();
  key("j");
  ok(st.sel, "j selects the first row");
  var firstId = st.sel.id;
  key("j");
  ok(st.sel.id !== firstId, "j moves on");
  key("k");
  eq(st.sel.id, firstId, "k moves back");
  key("n");
  ok(st.isNew, "n starts a new entry");
  setClean();
  closeEditor();

  /* The bindings and the "?" sheet are one table, so the way they break is a
     row that is half-filled: a binding with no key to dispatch on, or a help
     line with nothing to print in its <kbd>. */
  console.log("-- the shortcut sheet and the bindings are the same table --");
  ok(KEYMAP.size > 8, "the table binds a real set of keys (" + KEYMAP.size + ")");
  ok(KEYS.every(function (k) { return !k.fn || k.key; }), "every binding names a key");
  ok(KEYS.every(function (k) { return !k.help || k.key || k.label; }),
     "every help line has something to show in its kbd");
  ok(KEYS.filter(function (k) { return k.head; }).length >= 3, "the sheet is sectioned");
  key("?");
  ok($("#ov").classList.contains("on"), "? opens the sheet");
  has($("#dlg").textContent, "focus the search box", "rendered from the same table");
  has($("#dlg").textContent, "Browsing", "headings and all");
  has($("#dlg").textContent, "Filters", "the filter section is in the sheet");
  has($("#dlg").textContent, "the kind picker", "K is documented");
  has($("#dlg").textContent, "the command palette", "so is p");
  has($("#dlg").textContent, "toggle every kind the typed word matched",
      "and Tab, which has no binding of its own outside a picker");
  closeOv();
  // a guarded binding falls through with its default intact when the guard says no
  closeEditor();
  eq(st.sel, null, "nothing is open");
  var guarded = key("y");
  ok(!guarded.defaultPrevented, "y does nothing with no entry open");

  /* ---------- the kind picker ----------
     The whole point is that a kind can be reached with the hands on the keys,
     so every assertion here goes through a dispatched key rather than through
     the functions underneath it. The search term is taken out of the data, so
     the test says nothing about which kinds happen to be in the fixture. */
  console.log("-- the kind picker: type, Tab, toggle --");
  clearFilters();
  key("K");
  ok($("#ov").classList.contains("on"), "K opens the kind picker");
  ok($("#dlg").classList.contains("pick"), "in the picker's own frame");
  ok(pk && pk.opts.stay, "a picker that stays open");
  var kAll = pk.rows.length;
  ok(kAll > 1, "every kind is offered (" + kAll + ")");
  eq($("#pkrows").querySelectorAll(".pkr").length, kAll, "one row drawn per kind");
  has($("#pknote").textContent, "all kinds", "the read-out says nothing is pinned");

  input($("#pkq"), "zzqqzz");
  eq(pk.rows.length, 0, "a word nothing carries leaves no rows");
  ok($("#pkrows").querySelector(".pkempty"), "and says so");

  var term = pk.opts.rows()[0].label.slice(0, 3).toLowerCase();
  input($("#pkq"), term);
  ok(pk.rows.length >= 1 && pk.rows.length <= kAll, "typing narrows to the matches");
  var carries = function (r) { return r.label.toLowerCase().indexOf(term) >= 0; };
  var nExact = pk.rows.filter(carries).length;
  ok(nExact >= 1, "the rows carrying what was typed are offered");
  ok(pk.rows.slice(0, nExact).every(carries), "and they come first, ahead of any fuzzy match");
  ok(pk.rows.slice(nExact).every(function (r) { return r.m.fz; }), "which are all that follow");
  var matched = pk.rows.filter(carries).map(function (r) { return r.v; }).sort();

  var tabEv = dispatch($("#pkq"), "keydown", { key: "Tab" });
  ok(tabEv.defaultPrevented && tabEv._stop, "Tab belongs to the picker, not the focus trap");
  eq(st.kinds.slice().sort().join(","), matched.join(","),
     "Tab pins every kind carrying the word — not its fuzzy matches");
  ok(st.view.every(function (e) { return matched.indexOf(e.kind || NOKIND) >= 0; }),
     "and the list behind the dialog is already filtered");
  ok($("#ov").classList.contains("on"), "with the picker still up");
  has($("#pknote").textContent, "pinned", "the read-out counts them");
  dispatch($("#pkq"), "keydown", { key: "Tab" });
  eq(st.kinds.length, 0, "a second Tab takes the same matches off again");

  // shift-Tab is the narrowing move: whatever was pinned before, only these
  var cursorWas = pk.rows[pk.i].v;
  dispatch($("#pkq"), "keydown", { key: "Enter" });
  eq(st.kinds.join(","), cursorWas, "Enter pins the row under the cursor");
  dispatch($("#pkq"), "keydown", { key: "Enter" });
  eq(st.kinds.length, 0, "and Enter again takes it off");
  dispatch($("#pkq"), "keydown", { key: "Enter" });
  input($("#pkq"), "");
  dispatch($("#pkq"), "keydown", { key: "Tab", shiftKey: true });
  eq(st.kinds.length, pk.rows.length, "shift-Tab pins only what matched — here, all of them");
  input($("#pkq"), term);
  dispatch($("#pkq"), "keydown", { key: "Tab", shiftKey: true });
  eq(st.kinds.slice().sort().join(","), matched.join(","), "and drops everything else");

  input($("#pkq"), "");
  dispatch($("#pkq"), "keydown", { key: "Backspace" });
  eq(st.kinds.length, 0, "Backspace on an empty box goes back to all kinds");

  eq(pk.i, 0, "the cursor starts at the top");
  dispatch($("#pkq"), "keydown", { key: "ArrowDown" });
  eq(pk.i, 1, "ArrowDown moves it");
  dispatch($("#pkq"), "keydown", { key: "ArrowUp" });
  eq(pk.i, 0, "ArrowUp moves it back");
  dispatch($("#pkq"), "keydown", { key: "ArrowUp" });
  eq(pk.i, pk.rows.length - 1, "and it wraps round the end");

  // a click is the same act as Enter, on the row clicked rather than the cursor
  pk.i = 0;
  pickPaint();
  var second = pk.rows[1].v;
  click($("#pkrows").querySelectorAll(".pkr")[1]);
  eq(st.kinds.join(","), second, "clicking a row toggles that row");
  ok($("#ov").classList.contains("on"), "without closing the picker");
  closeOv();
  eq(pk, null, "closing drops the picker");
  clearFilters();

  /* ---------- the command palette ---------- */
  console.log("-- the command palette --");
  key("p");
  ok($("#ov").classList.contains("on"), "p opens the palette");
  ok(pk && !pk.opts.stay, "a picker that closes on a pick");
  ok(pk.rows.length > 20, "it offers the whole surface (" + pk.rows.length + " rows)");
  has($("#dlg").textContent, "sort · ", "the sorts are in it");
  has($("#dlg").textContent, "state · ", "so are the state filters");
  has($("#dlg").textContent, "kind · ", "and the kinds, one row each");
  ok(pk.rows.some(function (r) { return r.label === "sort · created ↓" && r.on; }),
     "the row matching the live value is ticked");

  input($("#pkq"), "sort len");
  eq(pk.rows.filter(function (r) { return !r.m.fz; }).length, 1,
     "two words narrow to the one row carrying both");
  has(pk.rows[0].label, "length", "the length sort, on top");
  dispatch($("#pkq"), "keydown", { key: "Enter" });
  eq($("#fSort").value, "len:desc", "Enter runs it");
  ok(!$("#ov").classList.contains("on"), "and the palette closes behind it");
  $("#fSort").value = "created:desc";
  refresh();

  /* ---------- fuzzy: letters in order, not necessarily adjacent ----------
     The matcher on its own first, on labels the test writes, then through
     the palette on rows the test puts there. */
  console.log("-- fuzzy matching in the pickers --");
  ok(pickMatch("tb", "task board"), "tb finds task board");
  ok(pickMatch("tlog", "travel_log"), "tlog finds travel_log");
  ok(pickMatch("tlog", "kind · travel_log"), "and still does behind a palette prefix");
  eq(pickMatch("tlog", "travel_log").hit.join(","), "0,7,8,9",
     "on the word start of log, not the l of travel — t, then l-o-g");
  eq(pickMatch("log", "blood_log").hit.join(","), "6,7,8",
     "a word typed whole lands on the word, not inside blood");
  ok(!pickMatch("log", "blood_log").fz, "and counts as typed, not fuzzy");
  ok(pickMatch("tb", "task board").fz, "tb is a fuzzy match");
  eq(pickMatch("bt", "task board"), null, "the letters have to come in order");
  eq(pickMatch("tbx", "task board"), null, "and every one of them has to be there");
  eq(pickMatch("ab", "a_b_ab").hit.join(","), "4,5", "a run beats initials when it is there as typed");
  eq(pickMatch("acl", "a catalog_list").hit.join(","), "0,2,10",
     "a later word start is preferred to a letter mid-word");
  eq(pickMatch("lz", "xlaz_lb").hit.join(","), "1,3",
     "but not when the rest of the word would no longer fit after it");
  ok(pickMatch("tb", "task board").score > pickMatch("tb", "the rabbit").score,
     "initials outrank the same letters scattered mid-word");
  eq(pickMatch("", "anything").hit.length, 0, "an empty query matches all, marking nothing");
  eq(pickLabel("a<b", [0, 2]), "<mark>a</mark>&lt;<mark>b</mark>", "marks are drawn around the letters, escaped");

  var realViews = views;
  views = [{ name: "task board", qs: "zz=1" }, { name: "the rabbit hole", qs: "zz=2" }];
  key("p");
  input($("#pkq"), "tb");
  eq(pk.rows[0].label, "view · task board", "tb puts the task board view first in the palette");
  var tbRow = $("#pkrows").querySelector(".pkr");
  eq(tbRow.querySelectorAll("mark").length, 2, "with its two letters marked");
  ok(pk.rows.some(function (r) { return r.label === "view · the rabbit hole"; }),
     "the scattered match is still offered, lower down");
  views = realViews;
  closeOv();

  // the kind picker: every kind is fuzzy-reachable by its initials, and a
  // query with rows carrying it as typed draws the line where they stop
  key("K");
  var anyKind = pk.rows.filter(function (r) { return /_/.test(r.label); })[0];
  if (anyKind) {
    var ini = anyKind.label.split("_").map(function (p) { return p[0]; }).join("");
    input($("#pkq"), ini);
    ok(pk.rows.some(function (r) { return r.v === anyKind.v; }),
       "a kind is found by its initials (" + ini + " → " + anyKind.label + ")");
  }
  input($("#pkq"), "o");
  var firstFz = pk.rows.findIndex(function (r) { return r.m.fz; });
  eq(firstFz, -1, "one letter is always a match as typed, never fuzzy");
  closeOv();
  clearFilters();

  // a row is allowed to hand over to a dialog of its own
  key("p");
  input($("#pkq"), "pick from a list");
  dispatch($("#pkq"), "keydown", { key: "Enter" });
  ok($("#ov").classList.contains("on"), "the overlay stays up");
  has($("#dlg").textContent, "Filter by kind", "because the row opened the kind picker");
  closeOv();

  /* ---------- c clears, and offers it back ---------- */
  console.log("-- clearing is survivable --");
  var someKind = kindRows().kinds[0];
  chooseKind(kindVal(someKind), null);
  $("#q").value = "woke";
  refresh();
  eq(st.kinds.length, 1, "a kind is pinned");
  // ⌘C and ctrl-C are the browser's copy: no binding fires with a chord held
  var copyEv = key("c", { metaKey: true });
  eq(st.kinds.length, 1, "⌘C leaves the filters alone");
  ok(!copyEv.defaultPrevented, "and keeps the browser's copy");
  key("c", { ctrlKey: true });
  eq(st.kinds.length, 1, "ctrl-C leaves them too");
  key("c", { altKey: true });
  eq(st.kinds.length, 1, "and so does alt-C");
  key("C", { metaKey: true, shiftKey: true });
  eq(st.kinds.length, 1, "⌘⇧C leaves the kinds pinned");
  key("c");
  eq(st.kinds.length, 0, "c clears the kinds");
  eq($("#q").value, "", "and the search box");
  var undo = $("#toast").querySelector("button");
  ok(undo && undo.textContent === "Undo", "the toast offers it back");
  click(undo);
  eq(st.kinds.length, 1, "undo puts the kinds back");
  eq($("#q").value, "woke", "and the search with them");
  clearFilters();


  /* ---------- [[link]] autocomplete ---------- */
  // a hand-built journal, so the ranking is asserted against known names
  // rather than against whatever the newest 400 real rows happen to contain
  var realAll = st.all;
  st.all = [
    { id: 3, title: "Zulu Title Only", content: "#Reading again" },
    { id: 2, title: "notes", content: "[[German course]] x [[German course]] y [[German cheese]]" +
                                      " #german #german #reading" },
    { id: 1, title: "German course", content: "[[Gymnastics Club]] #german #gym/indoor" },
  ];
  wikiIdx = null;
  tagIdx = null;

  console.log("-- [[link]] autocomplete: the index --");
  var idx = wikiIndex();
  var by = {};
  idx.forEach(function (it) { by[it.lc] = it; });
  eq(by["german course"].links, 2, "a link counts every time it was written");
  ok(by["german course"].title, "and the same name is also an entry title");
  eq(by["german course"].n, 3, "popularity is links plus the title");
  eq(by["zulu title only"].n, 1, "a title nobody links to still counts once");
  eq(by["gymnastics club"].links, 1, "a link with no entry behind it is still a target");
  ok(wikiIndex() === idx, "the index is cached until the journal changes");

  console.log("-- [[link]] autocomplete: the trigger --");
  eq(wikiTrigger("see [[Ger", 9).q, "Ger", "an open [[ before the caret triggers");
  eq(wikiTrigger("see [[Ger", 9).start, 6, "the query starts after the brackets");
  eq(wikiTrigger("see [[", 6).q, "", "bare [[ triggers with an empty query");
  ok(wikiTrigger("see [[Ger]] more", 16) === null, "a finished link does not");
  ok(wikiTrigger("plain text", 10) === null, "and neither does plain text");
  ok(wikiTrigger("see [[Ger\nmore", 14) === null, "a newline ends the trigger");

  console.log("-- [[link]] the caret is in --");
  var linkAt = function (t, c) { var r = wikiLinkAt(t, c); return r && r.name; };
  eq(linkAt("see [[German course]] end", 10), "German course", "a caret inside a link finds it");
  eq(linkAt("see [[German course]] end", 4), "German course", "so does one on the opening bracket");
  eq(linkAt("see [[German course]] end", 21), "German course", "and one just past the closing pair");
  ok(wikiLinkAt("see [[German course]] end", 24) === null, "text after the link is not the link");
  ok(wikiLinkAt("see [[German course]] end", 2) === null, "nor is text before it");
  ok(wikiLinkAt("see [[unclosed and on", 12) === null, "an unfinished link is nothing to follow");
  eq(linkAt("[[A]][[B]] x", 7), "B", "adjacent links are told apart");
  eq(linkAt("x [[ spaced ]] y", 8), "spaced", "the name comes back trimmed");
  eq(linkAt("- " + Array(300).join("z") + " [[Far Away]] tail", 305 + 6), "Far Away",
     "a link far into a long entry is still found");
  ok(wikiLinkAt("", 0) === null, "an empty box has no link");
  eq(wikiLinkAt("see [[German course]] end", 10).id, null, "a [[name]] carries no id");
  var idAt = wikiLinkAt("see [Old label](((1))) end", 8);
  eq(idAt && idAt.id, 1, "an id link is found by its id");
  eq(idAt && idAt.name, idLinkName(1, "Old label"), "and goes by the name it renders under");
  eq(wikiLinkAt("see [Old label](((1))) end", 20).id, 1, "the caret in its (((id))) half counts too");
  ok(wikiLinkAt("[A](((1)))[[B]] x", 12).id === null, "an id link and a [[name]] side by side are told apart");

  console.log("-- [[link]] autocomplete: ranking --");
  eq(wikiRank("german c")[0].name, "German course", "the most-linked prefix match leads");
  ok(wikiRank("german c").length >= 2, "and the near miss comes with it");
  eq(wikiRank("course")[0].name, "German course", "a word-boundary match ranks");
  ok(wikiRank("gc").some(function (x) { return x.name === "German course"; }),
     "an initialism finds it by subsequence");
  eq(wikiRank("")[0].name, "German course", "an empty query offers the most-linked first");
  eq(wikiRank("qqqq").length, 0, "nothing matches nonsense");
  ok(wikiRank("e").length <= WIKI_MAX, "the list is capped");

  console.log("-- [[link]] autocomplete: the popup --");
  var ta = $("#content");
  var open = function (v, caret) {
    ta.focus();
    ta.value = v;
    ta.selectionStart = ta.selectionEnd = caret === undefined ? v.length : caret;
    input(ta);
  };
  open("linking to [[ger");
  ok($("#wikiac").classList.contains("on"), "typing [[ opens the popup");
  ok($("#wikiac").querySelectorAll(".wac").length >= 2, "with more than one candidate");
  has($("#wikiac").innerHTML, "<b>", "the matched run is marked in the label");
  eq($("#content").getAttribute("aria-expanded"), "true", "the textarea announces it");
  eq($("#wikiac").querySelector(".wac.on").dataset.i, "0", "the best match starts selected");
  dispatch(ta, "keydown", { key: "ArrowDown" });
  eq($("#wikiac").querySelector(".wac.on").dataset.i, "1", "ArrowDown moves the highlight");
  dispatch(ta, "keydown", { key: "ArrowUp" });
  eq($("#wikiac").querySelector(".wac.on").dataset.i, "0", "ArrowUp moves it back");
  var tab = dispatch(ta, "keydown", { key: "Tab" });
  ok(tab.defaultPrevented, "Tab is taken by the popup, not by the indent");
  eq(ta.value, "linking to [German course](((1)))",
     "a name an entry wears lands as a link to that entry, by id");
  eq(ta.selectionStart, ta.value.length, "with the caret past the brackets");
  ok(!$("#wikiac").classList.contains("on"), "and the popup is gone");
  eq($("#content").getAttribute("aria-expanded"), "false", "which the textarea announces too");

  open("x [[ger]] y", 7);
  ok($("#wikiac").classList.contains("on"), "a half-typed link inside its own brackets opens it");
  dispatch(ta, "keydown", { key: "Enter" });
  eq(ta.value, "x [German course](((1))) y", "an existing ]] is taken in, not left dangling");

  // a [[name]] already written out, caret inside its "]]": Enter is a new line
  open("x [[German course]]", 17);
  ok(wac && wac.mode === "wiki", "a complete [[name]] still shows its row");
  var wEnter = dispatch(ta, "keydown", { key: "Enter" });
  ok(!wEnter.defaultPrevented, "Enter on it is left to the textarea - the line breaks");
  eq(ta.value, "x [[German course]]", "nothing is rewritten");
  eq(ta.selectionStart, 19, "the caret steps past the ]] first, so the brackets stay on their line");
  ok(!$("#wikiac").classList.contains("on"), "and the popup is shut");
  open("x [[German course]]", 17);
  dispatch(ta, "keydown", { key: "Tab" });
  eq(ta.value, "x [German course](((1)))", "Tab still takes the row, for the id link");

  open("x [[gymn");
  dispatch(ta, "keydown", { key: "Tab" });
  eq(ta.value, "x [[Gymnastics Club]]", "a name no entry wears yet stays a [[name]], closed");

  open("x [[ger");
  var esc = dispatch(ta, "keydown", { key: "Escape" });
  ok(esc.defaultPrevented, "Escape is swallowed by the popup");
  ok(!$("#wikiac").classList.contains("on"), "which closes");
  ok(document.activeElement === ta, "and leaves the caret where it was");

  open("plain");
  ok(!$("#wikiac").classList.contains("on"), "plain text keeps it shut");
  dispatch(ta, "keydown", { key: "Tab" });
  eq(ta.value, "plain  ", "with the popup closed Tab still indents");

  open("x [[ger");
  var row = $("#wikiac").querySelectorAll(".wac")[1];
  var picked = row.querySelector(".wacn").textContent;
  dispatch(row, "mousedown", {});
  eq(ta.value, "x [[" + picked + "]]", "clicking a row inserts that one");

  open("x [[ger");
  dispatch(ta, "blur", {});
  ok(!$("#wikiac").classList.contains("on"), "leaving the field closes it");

  console.log("-- #tag autocomplete: the index --");
  var tidx = tagIndex();
  var tby = {};
  tidx.forEach(function (it) { tby[it.lc] = it; });
  eq(tby["german"].n, 3, "a tag counts every time it was written");
  eq(tby["reading"].name, "Reading", "the first spelling seen — the newest — is the one offered");
  eq(tby["reading"].n, 2, "however it was cased on the way in");
  eq(tby["gym/indoor"].n, 1, "a slash is part of the tag, not the end of it");
  ok(!tby["german course"], "a [[page]] is not a tag");
  ok(tagIndex() === tidx, "the index is cached until the journal changes");

  console.log("-- #tag autocomplete: the trigger --");
  eq(tagTrigger("a #ger", 6).q, "ger", "a # after a space triggers");
  eq(tagTrigger("a #ger", 6).start, 3, "the query starts after the hash");
  eq(tagTrigger("#ger", 4).q, "ger", "so does one opening the line");
  eq(tagTrigger("#", 1).q, "", "a bare hash triggers with an empty query");
  eq(tagTrigger("a #gym/in", 9).q, "gym/in", "a slash stays inside the name");
  ok(tagTrigger("issue a#b", 9) === null, "a hash inside a word does not");
  ok(tagTrigger("a #ger x", 8) === null, "a space ends the name");
  ok(tagTrigger("plain text", 10) === null, "and neither does plain text");
  ok(tagTrigger("a #" + Array(60).join("x"), 62) === null, "an overlong one is not a tag");

  console.log("-- #tag autocomplete: ranking --");
  var tnames = function (q) { return tagRank(q).map(function (x) { return x.name; }); };
  eq(tnames("ger")[0], "german", "a prefix match leads");
  eq(tnames("")[0], "german", "an empty query offers the most-used first");
  ok(tnames("read").indexOf("Reading") === 0, "a match is offered in the spelling it is written in");
  eq(tagRank("qqqq").length, 0, "nothing matches nonsense");
  ok(tagRank("g").length <= WIKI_MAX, "the list is capped");

  console.log("-- #tag autocomplete: the popup --");
  open("note #ger");
  ok($("#wikiac").classList.contains("on"), "typing # opens the popup");
  eq($("#wikiac").getAttribute("aria-label"), "Tag suggestions", "announced as tags, not links");
  has($("#wikiac").innerHTML, "wacs", "the rows wear their hash");
  has($("#wikiac").querySelector(".wac.on .wacu").textContent, "3", "and say how often it is used");
  dispatch(ta, "keydown", { key: "Enter" });
  eq(ta.value, "note #german", "Enter finishes the tag in place");
  eq(ta.selectionStart, ta.value.length, "with the caret after it");
  ok(!$("#wikiac").classList.contains("on"), "and the popup is gone, not reopened on the finished word");

  // the tag already complete: Enter breaks the line instead of re-inserting it
  open("note #german");
  ok(wac && wac.mode === "tag", "a complete tag still shows its row");
  var tEnter = dispatch(ta, "keydown", { key: "Enter" });
  ok(!tEnter.defaultPrevented, "Enter after a complete #tag is the textarea's new line");
  eq(ta.value, "note #german", "nothing inserted");
  ok(!$("#wikiac").classList.contains("on"), "the popup closed");
  open("note #german");
  var tTab = dispatch(ta, "keydown", { key: "Tab" });
  ok(tTab.defaultPrevented, "Tab still inserts");

  open("note #ger");
  var trow = $("#wikiac").querySelectorAll(".wac")[0];
  dispatch(trow, "mousedown", {});
  eq(ta.value, "note #german", "clicking a row inserts that one");

  open("x [[a #ger");
  ok(!wac || wac.mode === "wiki",
     "inside an open [[ the hash belongs to the page name");
  ok(tagTrigger("x [[a #ger", 10) !== null, "though on its own that hash would have triggered");

  open("colour #ff00aa");
  ok(!$("#wikiac").classList.contains("on"), "a hash nothing answers keeps it shut");

  console.log("-- @role autocomplete: the trigger --");
  eq(noteTrigger("@", 1).q, "", "a bare @ opening the body triggers");
  eq(noteTrigger("@", 1).start, 1, "the query starts after the @");
  eq(noteTrigger("first\n@hi", 9).q, "hi", "so does one opening a later line");
  eq(noteTrigger("x\n  - @yeo", 10).q, "yeo", "after an indent and a list bullet, as NOTE_RE reads it");
  eq(noteTrigger("\t* @", 4).q, "", "a tab and a * bullet too");
  ok(noteTrigger("ask @yeo", 8) === null, "a mid-sentence @ does not");
  ok(noteTrigger("radu1@gmail", 11) === null, "nor one after a word character");
  ok(noteTrigger("- @yeoman log", 13) === null, "a space ends the name");
  ok(noteTrigger("> @yeo", 6) === null, "a quoted line is never a note");
  ok(noteTrigger("```\n@yeo", 8) === null, "nor a line inside a code fence");
  eq(noteTrigger("```\nx\n```\n@yeo", 14).q, "yeo", "one after the fence closes is");
  ok(noteTrigger("@9", 2) === null, "a role starts with a letter");
  ok(noteTrigger("@" + Array(40).join("x"), 40) === null, "and is never overlong");

  console.log("-- @role autocomplete: ranking --");
  var rnames = function (q) { return noteRank(q).map(function (x) { return x.name; }); };
  // the journal's own names row (the watcher's, on the live rows) adds
  // people after the roles: only the roles' head is fixed
  eq(rnames("").slice(0, Object.keys(NOTE_ROLES).length).join(" "), ["yeoman"].concat(Object.keys(NOTE_ROLES).filter(function (r) { return r !== "yeoman"; })).join(" "),
     "an empty query offers every role, yeoman first, the rest in NOTE_ROLES order");
  eq(rnames("hi")[0], "historian", "@hi finds the historian");
  eq(rnames("Sci")[0], "science", "case does not matter");
  eq(noteRank("qqqq").length, 0, "nothing matches nonsense");
  eq(Object.keys(NOTE_HINTS).sort().join(" "), Object.keys(NOTE_ROLES).sort().join(" "),
     "every role that takes notes has a hint, and no other");

  console.log("-- @role autocomplete: the popup --");
  open("today\n- @");
  ok($("#wikiac").classList.contains("on"), "typing @ at the head of a line opens the popup");
  ok(wac && wac.mode === "note", "in the roles' mode");
  eq($("#wikiac").getAttribute("aria-label"), "Crew roles", "announced as crew roles");
  eq($("#wikiac").querySelector(".wac.on .wacn").textContent, "@yeoman", "yeoman leads, with its @");
  has($("#wikiac").querySelector(".wac.on .wacu").textContent, NOTE_HINTS.yeoman, "and says what it does");
  dispatch(ta, "keydown", { key: "ArrowDown" });
  eq($("#wikiac").querySelector(".wac.on .wacn").textContent, "@" + noteRank("")[1].name, "ArrowDown moves the highlight");
  dispatch(ta, "keydown", { key: "ArrowUp" });
  var nEnter = dispatch(ta, "keydown", { key: "Enter" });
  ok(nEnter.defaultPrevented, "Enter is taken by the popup");
  eq(ta.value, "today\n- @yeoman ", "the role lands with one space after it");
  eq(ta.selectionStart, ta.value.length, "the caret after the space, ready for the order");
  ok(!$("#wikiac").classList.contains("on"), "and the popup is gone");
  eq(noteScan(ta.value + "log a gym session").map(function (n) { return n.role; }).join(), "yeoman",
     "the line it starts is a note by the watcher's rule");

  open("@hi");
  dispatch(ta, "keydown", { key: "Tab" });
  eq(ta.value, "@historian ", "Tab inserts too, the filtered row");

  open("@yeo log it", 4);
  dispatch(ta, "keydown", { key: "Enter" });
  eq(ta.value, "@yeoman log it", "a name already followed by a space is finished, the space not doubled");
  eq(ta.selectionStart, 8, "with the caret past that space");

  open("@");
  var nrow = $("#wikiac").querySelectorAll(".wac")[1];
  dispatch(nrow, "mousedown", {});
  eq(ta.value, "@" + noteRank("")[1].name + " ", "a tap on a row inserts that one");

  open("@sc");
  var nEsc = dispatch(ta, "keydown", { key: "Escape" });
  ok(nEsc.defaultPrevented, "Escape is swallowed by the popup");
  ok(!$("#wikiac").classList.contains("on"), "which closes");
  eq(ta.value, "@sc", "leaving the text as typed");

  open("write to @yeo");
  ok(!$("#wikiac").classList.contains("on"), "a mid-sentence @ keeps it shut");
  open("```\n@yeo");
  ok(!$("#wikiac").classList.contains("on"), "so does one in a code fence");
  open("> @yeo");
  ok(!$("#wikiac").classList.contains("on"), "and one on a quoted line");

  var ttl = $("#e_head"), ttlWas = ttl.value;
  ttl.focus();
  ttl.value = "@";
  ttl.selectionStart = ttl.selectionEnd = 1;
  input(ttl);
  ok(!$("#wikiac").classList.contains("on"), "the title is never a note: @ there opens nothing");
  ttl.value = ttlWas;
  input(ttl);
  ta.focus();

  console.log("-- ISO week --");
  eq(isoWeek(new Date(2026, 8, 16)), "2026-W38", "a midweek day");
  eq(isoWeek(new Date(2026, 0, 1)), "2026-W01", "a Thursday 1 January opens its own week 1");
  eq(isoWeek(new Date(2021, 0, 1)), "2020-W53", "a January Friday belongs to the year before");
  eq(isoWeek(new Date(2019, 11, 30)), "2020-W01", "and a December Monday to the year after");

  console.log("-- /command autocomplete: the trigger --");
  eq(cmdTrigger("/tim", 4).q, "tim", "a / opening a line triggers");
  eq(cmdTrigger("/tim", 4).start, 1, "the name starts after the slash");
  eq(cmdTrigger("- note /da", 10).q, "da", "so does one after a space");
  eq(cmdTrigger("/", 1).q, "", "a bare slash triggers with an empty name");
  ok(cmdTrigger("see http://x", 12) === null, "a slash inside a URL does not");
  ok(cmdTrigger("~/lcars", 7) === null, "nor one in a path");
  ok(cmdTrigger("9/16", 4) === null, "nor one in a date");
  ok(cmdTrigger("/two words", 10) === null, "a space ends the name");
  ok(cmdTrigger("/" + Array(20).join("x"), 20) === null, "and so does an overlong one");

  console.log("-- /command autocomplete: ranking --");
  var names = function (q) { return cmdRank(q).map(function (c) { return c.name; }); };
  eq(names("").slice(0, 6).join(" "), "todo log now day time location",
     "a bare slash leads with what is written most, the other dates after");
  eq(names("to")[0], "todo", "/to is /todo before /tomorrow");
  eq(cmdRank("").length, WIKI_MAX, "filling the popup");
  eq(names("time")[0], "time", "a name matches itself");
  eq(names("yes")[0], "yesterday", "yesterday is one prefix away");
  eq(names("tom")[0], "tomorrow", "and so is tomorrow");
  eq(names("clock")[0], "time", "an alias finds the command it belongs to");
  eq(names("today")[0], "date", "and /today is one of them, not a command of its own");
  eq(names("day")[0], "day", "a name still beats every alias that also matched");
  eq(cmdRank("qqqq").length, 0, "nothing matches nonsense");

  console.log("-- /command autocomplete: the values --");
  var cmd = {};
  cmdList().forEach(function (c) { cmd[c.name] = c; });
  var when = new Date();
  var d0 = isoDay(when);
  var off = function (n) {
    return isoDay(new Date(when.getFullYear(), when.getMonth(), when.getDate() + n));
  };
  eq(cmd.date.make(""), d0, "/date is today, plain");
  eq(cmd.yesterday.make(""), off(-1), "/yesterday is the day before");
  eq(cmd.tomorrow.make(""), off(1), "/tomorrow is the day after");
  eq(cmd.day.make(""), "[[" + d0 + "]]", "/day is today as a day page instead");
  ok(/^\d\d:\d\d$/.test(cmd.time.make("")), "/time is a wall clock");
  eq(cmd.now.make(""), d0 + " " + cmd.time.make(""), "/now is the date and the clock");
  eq(cmd.weekday.make(""), WDFULL[when.getDay()], "/weekday names the day");

  console.log("-- /command autocomplete: the line it lands on --");
  eq(cmd.todo.make(""), "- TODO ", "a marker on an empty line brings its bullet");
  eq(cmd.todo.make("\t"), "- TODO ", "indent alone is still an empty line");
  eq(cmd.todo.make("- "), "TODO ", "a bullet already there is not doubled");
  eq(cmd.todo.make("- see "), "TODO ", "and a line with prose on it just gets the word");
  eq(cmd.hr.make(""), "---\n", "a rule hands back a fresh line to carry on in");
  eq(cmd.hr.make("text "), "\n---\n", "and breaks the line it interrupted");
  has(cmd.code.make(""), "```", "a fence is a fence");
  eq(cmd.link.make("").indexOf(CMD_CARET), 2, "the caret marker sits inside the brackets");

  console.log("-- /command autocomplete: the popup --");
  open("/tim");
  ok($("#wikiac").classList.contains("on"), "typing / opens the popup");
  eq($("#wikiac").getAttribute("aria-label"), "Editor commands", "announced as commands, not links");
  has($("#wikiac").innerHTML, "wacs", "the rows wear their slash");
  ok(/^\d\d:\d\d$/.test($("#wikiac").querySelector(".wac.on .wacu").textContent),
     "and show the value they are about to insert");
  dispatch(ta, "keydown", { key: "Enter" });
  ok(/^\d\d:\d\d$/.test(ta.value), "Enter inserts it, the slash and name consumed: " + ta.value);
  ok(!$("#wikiac").classList.contains("on"), "and the popup is gone");

  open("- note /yes");
  dispatch(ta, "keydown", { key: "Tab" });
  eq(ta.value, "- note " + off(-1), "Tab completes one mid-line");

  open("/todo");
  dispatch(ta, "keydown", { key: "Enter" });
  eq(ta.value, "- TODO ", "a marker command brings its own bullet");
  eq(ta.selectionStart, 7, "and leaves the caret ready for the task");

  open("/link");
  dispatch(ta, "keydown", { key: "Enter" });
  eq(ta.value, "[[]]", "/link lands empty brackets");
  eq(ta.selectionStart, 2, "with the caret between them");
  ok($("#wikiac").classList.contains("on"), "and hands straight over to the page list");
  eq($("#wikiac").getAttribute("aria-label"), "Link suggestions", "which says so");

  console.log("-- /location --");
  eq(names("loc")[0], "location", "/loc finds it");
  eq(names("where")[0], "location", "and so does /where");
  ok(cmdRank("loc", TITLE_CMDS).every(function (c) { return c.name !== "location"; }), "the title is not offered it");
  var realFetch = fetch, realGeo = navigator.geolocation, realPerm = navigator.permissions;
  var geoCalls = 0, geoAnswer = null, rev = { name: "Cismigiu" };
  navigator.geolocation = { getCurrentPosition: function (ok_, bad) {
    geoCalls++;
    if (geoAnswer === "hang") return;
    setTimeout(function () {
      if (geoAnswer) bad({ code: geoAnswer });
      else ok_({ timestamp: Date.now(), coords: { latitude: 44.4375, longitude: 26.091666, accuracy: 12.4 } });
    }, 0);
  } };
  fetch = function (url, init) {
    if (String(url).indexOf("nominatim.openstreetmap.org/reverse") < 0) return realFetch(url, init);
    if (!rev) return Promise.reject(new Error("offline"));
    return Promise.resolve({ ok: true, status: 200, json: function () { return Promise.resolve(rev); } });
  };
  crs.key = null;
  open("walked to /loc");
  has($("#wikiac").querySelector(".wac.on .wacu").textContent, "where you are", "the row says what it will type");
  dispatch(ta, "keydown", { key: "Enter" });
  eq(ta.value, "walked to ", "the command goes at once");
  await settle(3);
  eq(ta.value, "walked to Cismigiu (44.43750, 26.09167 ±12 m)", "and the place lands where it stood");
  has($("#toast").textContent, "Cismigiu", "the toast says where");
  rev = null;
  open("/location");
  dispatch(ta, "keydown", { key: "Enter" });
  await settle(3);
  eq(ta.value, "44.43750, 26.09167 ±12 m", "a failed place lookup still types the coordinates");
  geoAnswer = 1;
  open("x /location");
  dispatch(ta, "keydown", { key: "Enter" });
  await settle(3);
  eq(ta.value, "x ", "a refusal types nothing");
  has($("#toast").textContent, "may not ask where you are", "and says why");
  geoAnswer = "hang";
  open("y /location");
  dispatch(ta, "keydown", { key: "Enter" });
  await settle(6);
  eq(ta.value, "y ", "a fix that never comes types nothing");
  has($("#toast").textContent, "no fix came", "and is given up on rather than waited for");
  geoAnswer = null;
  geoCalls = 0;
  navigator.permissions = { query: function () { return Promise.resolve({ state: "denied" }); } };
  open("z /location");
  dispatch(ta, "keydown", { key: "Enter" });
  await settle(3);
  eq(ta.value, "z ", "a page already refused types nothing");
  eq(geoCalls, 0, "and does not ask again");
  navigator.permissions = realPerm;
  rev = { name: "Cismigiu" };
  open("noted ");
  var vloc = vMatch(vWords("insert my location"), 0);
  eq(vloc && vloc.cmd.say, "insert my location", "the voice order is its own, not show my location");
  vloc.cmd.fn();
  await settle(3);
  eq(ta.value, "noted Cismigiu (44.43750, 26.09167 ±12 m)", "and types the same at the caret");
  fetch = realFetch;
  navigator.geolocation = realGeo;

  open("/todo");
  var cesc = dispatch(ta, "keydown", { key: "Escape" });
  ok(cesc.defaultPrevented, "Escape is swallowed by the command popup too");
  ok(!$("#wikiac").classList.contains("on"), "which closes");

  open("see http://example.com/x");
  ok(!$("#wikiac").classList.contains("on"), "a URL never opens it");
  open("x [[ /tim");
  ok(!$("#wikiac").classList.contains("on"),
     "and inside an open [[ the slash belongs to the page name");
  ok(cmdTrigger("x [[ /tim", 9) !== null, "though on its own that slash would have triggered");

  console.log("-- /command autocomplete: the title --");
  var tnames = function (q) { return cmdRank(q, TITLE_CMDS).map(function (c) { return c.name; }); };
  eq(tnames("")[0], "date", "a bare slash in the title offers the date first");
  eq(tnames("today")[0], "date", "aliases still answer");
  ok(tnames("").indexOf("todo") < 0 && tnames("").indexOf("link") < 0 && tnames("").indexOf("day") < 0,
     "and only one-line values are offered: " + tnames("").join(","));
  eq(names("")[0], "todo", "while the body's order is untouched");
  var ti = $("#e_head");
  var topen = function (v) {
    ti.focus();
    ti.value = v;
    ti.selectionStart = ti.selectionEnd = v.length;
    input(ti);
  };
  topen("Standup /");
  ok($("#wikiac").classList.contains("on"), "typing / in the title opens the popup");
  eq(ti.getAttribute("aria-expanded"), "true", "and the title announces it");
  eq($("#wikiac").querySelector(".wac.on .wacu").textContent, d0, "with today's date selected");
  var tent = dispatch(ti, "keydown", { key: "Enter" });
  ok(tent.defaultPrevented, "Enter is taken by the popup");
  eq(ti.value, "Standup " + d0, "and inserts the date in place of the slash");
  eq(ti.selectionStart, ti.value.length, "leaving the caret after it");
  ok(!$("#wikiac").classList.contains("on"), "and the popup is gone");
  eq(ti.getAttribute("aria-expanded"), "false", "which the title says too");
  topen("/yes");
  dispatch(ti, "keydown", { key: "Tab" });
  eq(ti.value, off(-1), "Tab completes yesterday");
  topen("/tod");
  var ttab = dispatch(ti, "keydown", { key: "Escape" });
  ok(ttab.defaultPrevented && !$("#wikiac").classList.contains("on"), "Escape dismisses it");
  eq(ti.value, "/tod", "leaving the text alone");
  topen("a [[x /da");
  ok($("#wikiac").classList.contains("on"), "a [[ in the title is just text, the slash still triggers");
  wikiClose();
  topen("no slash");
  var tplain = dispatch(ti, "keydown", { key: "Tab" });
  ok(!tplain.defaultPrevented, "with the popup shut Tab still leaves the title");
  ti.value = "";

  st.all = realAll;
  wikiIdx = null;
  tagIdx = null;
  ta.value = "";
  setClean();
  closeEditor();

  console.log("\nsection C: " + TEST.asserts + " assertions, " + TEST.fails.length + " failures");
  globalThis.__phaseC = true;
})().catch(function (e) { console.log("SUITE C THREW: " + e + "\n" + (e && e.stack)); });

/* ===================== suite D: phases 5 and 6 ===================== */
(async function () {
  if (!await waitFlag("__phaseC")) return;

  console.log("\n-- 5.2 warm boot cache --");
  saveCache();
  var cached = JSON.parse(localStorage.getItem("lcars.cache"));
  ok(cached && cached.rows.length > 0, "cache written (" + (cached ? cached.rows.length : 0) + " rows)");
  ok(cached.rows.length <= CACHE_ROWS, "capped at " + CACHE_ROWS + " rows");
  eq(cached.rows[0].id, st.all[0].id, "newest first, same as st.all");
  var keepAll = st.all, keepById = st.byId;
  st.all = []; st.byId = new Map();
  ok(paintCache(), "cache paints on a cold start");
  eq(st.all.length, cached.rows.length, "rows restored");
  has($("#hstat").textContent, "cached", "and the header says so");
  ok($("#list").querySelectorAll(".item").length > 0, "rows on screen with no network");
  st.all = keepAll; st.byId = keepById;
  refresh();

  console.log("-- 5.5 sticky day headers are a setting --");
  eq(document.body.dataset.sticky, "off", "off by default, as the old workaround was");
  cfg.sticky = true; applySticky();
  eq(document.body.dataset.sticky, "on", "the switch reaches the body");
  cfg.sticky = false; applySticky();

  console.log("-- 5.6 the whole day bar opens the day --");
  var bar = $("#list").querySelector(".day");
  ok(bar, "a day bar is on screen");
  ok(bar.dataset.day, "it knows its day");
  has(bar.innerHTML, "Read day", "the button says what it does");
  click(bar);
  ok($("#ov").classList.contains("on"), "tapping the bar opens the day view");
  eq(dayOpen, bar.dataset.day, "the right day");
  click($("#dayclose"));

  console.log("-- 6.1 dialog focus --");
  var invoker = $("#bStats");
  invoker.focus();
  openStats();
  ok(document.activeElement !== invoker, "focus moved off the invoker");
  ok($("#dlg").querySelectorAll("*").indexOf(document.activeElement) >= 0,
     "and into the dialog");
  eq($("#dlg").getAttribute("role"), "dialog", "the dialog announces itself");
  eq($("#ov").querySelector(".dlg").getAttribute("aria-modal"), "true", "aria-modal set");
  eq($("#dlg").querySelector("h2").id, "dlgh", "the heading names the dialog");
  var kb = $("#dlg").querySelector(".sbar[data-k]");
  eq(kb.tabIndex, 0, "stat bars are keyboard reachable");
  kb.focus();
  dispatch(kb, "keydown", { key: "Enter" });
  eq(st.kinds.join(","), kb.dataset.k, "Enter on a stat bar filters too");
  clearFilters();
  closeOv();
  eq(document.activeElement, invoker, "closing hands focus back");

  // the config dialog is the one with several controls, so test the trap there
  invoker = $("#bCfg");
  invoker.focus();
  openCfg();
  var f = $("#dlg").querySelectorAll(FOCUSABLE);
  ok(f.length > 2, "config dialog has several controls (" + f.length + ")");
  eq(document.activeElement, f[0], "focus starts on the first");
  dispatch($("#dlg"), "keydown", { key: "Tab", shiftKey: false });
  eq(document.activeElement, f[1], "Tab goes to the next");
  f[f.length - 1].focus();
  dispatch($("#dlg"), "keydown", { key: "Tab", shiftKey: false });
  eq(document.activeElement, f[0], "and wraps round at the end");
  dispatch($("#dlg"), "keydown", { key: "Tab", shiftKey: true });
  eq(document.activeElement, f[f.length - 1], "shift-Tab wraps the other way");
  click($("#c_cancel"));
  eq(document.activeElement, invoker, "cancel hands focus back");

  console.log("-- 6.2 rows are reachable by keyboard --");
  refresh();
  var it = $("#list").querySelector(".item");
  eq(it.tabIndex, 0, "rows are focusable");
  eq(it.getAttribute("role"), "button", "and announce themselves");
  ok(it.getAttribute("aria-label"), "with a label: " + it.getAttribute("aria-label"));
  st.sel = null;
  dispatch(it, "keydown", { key: "Enter" });
  ok(st.sel && st.sel.id === +it.dataset.id, "Enter selects the row");
  eq($("#list").querySelector(".item.sel").getAttribute("aria-current"), "true",
     "the selected row is marked");
  closeEditor();

  console.log("-- 6.3 keyboard additions --");
  key("G");
  eq(st.sel.id, st.view[st.view.length - 1].id, "G jumps to the last entry");
  key("g"); key("g");
  eq(st.sel.id, st.view[0].id, "gg jumps to the first");
  key("g");
  lastKeyAt = 0;          // let the window lapse
  key("g");
  ok(st.sel.id === st.view[0].id, "a lapsed gg does not misfire");

  var d0 = st.dayOf(st.sel);
  key("]");
  ok(st.dayOf(st.sel) !== d0, "] moves to the next day");
  var d1 = st.dayOf(st.sel);
  key("[");
  ok(st.dayOf(st.sel) === d1 || st.dayOf(st.sel) === d0, "[ walks back up");

  key("?");
  ok($("#ov").classList.contains("on"), "? opens the cheat sheet");
  has($("#dlg").textContent, "duplicate the open entry", "which lists the bindings");
  has($("#dlg").innerHTML, "<kbd>", "as real keys");
  click($("#h_close"));
  ok(!$("#ov").classList.contains("on"), "and closes again");

  console.log("-- escape unwinds one layer at a time --");
  openHelp();
  key("Escape");
  ok(!$("#ov").classList.contains("on"), "Escape closes the dialog");
  openDrawer();
  key("Escape");
  eq(document.body.dataset.drawer, "off", "then the drawer");
  select(st.view[0].id);
  setRead(false);
  key("Escape");
  ok(st.read, "then editing, which steps back to the reader");
  eq(document.body.dataset.pane, "edit", "with the entry still open");
  key("Escape");
  eq(document.body.dataset.pane, "list", "and only then the editor");

  console.log("-- escape out of editing --");
  select(st.view[0].id);
  setRead(false);
  key("Escape", { target: $("#content") });
  ok(!st.read, "one press from inside the content box lets go of it (P13)");
  key("Escape");
  ok(st.read, "the second reaches the reader");
  ok(document.activeElement !== $("#content"), "and the focus leaves the form with it");

  setRead(false);
  key("Escape", { target: $("#q") });
  ok(!st.read, "Escape in the search box only lets go of that field");
  eq(document.body.dataset.pane, "edit", "the entry stays where it was");

  /* Unsaved text is not a reason to stand still: Escape writes it and then
     reads it, so the key that means "back" never asks a question about the
     typing it is stepping away from. */
  await settle(6);                          // any body fetch lands before the write
  var escId = st.sel.id;
  $("#e_head").value = "escape saves " + escId;
  markDirty();
  key("Escape");
  await settle(8);
  ok(!document.body.classList.contains("dirty"),
     "Escape saves unsaved text instead of asking about it");
  eq(dbFind(escId).title, "escape saves " + escId, "and the edit did reach the server");
  ok(st.read, "only then does it step back to the reader");
  eq(document.body.dataset.pane, "edit", "with the entry still open");
  key("Escape");
  eq(document.body.dataset.pane, "list", "and a second press closes it, nothing left to discard");

  /* Escape is pressed twice out of habit, and the save takes a round trip:
     the second press must not send the same edit at a row the first one has
     already moved. */
  select(escId);
  setRead(false);
  $("#e_head").value = "escape saves once " + escId;
  markDirty();
  var putsBefore = DBLOG.filter(function (l) { return l.indexOf("PUT") === 0; }).length;
  key("Escape");
  key("Escape");
  await settle(8);
  eq(DBLOG.filter(function (l) { return l.indexOf("PUT") === 0; }).length - putsBefore, 1,
     "two presses of Escape send one PUT");
  ok(st.read && !document.body.classList.contains("dirty"), "and still end in the reader");

  /* Leaving saves (design P2): another row, ‹ List, Back, Duplicate … take
     the edit with them and open at once - no question, a mark on the row
     while the write is on its way. */
  console.log("-- leaving an edited entry saves it --");
  select(escId);
  setRead(false);
  $("#e_head").value = "left with a save " + escId;
  markDirty();
  TEST.confirmAnswer = false;               // a question would be answered "no"
  var lvLog = TEST.log.length;
  var otherId = st.view.find(function (e) { return e.id !== escId; }).id;
  ok(select(otherId), "opening another entry over unsaved text opens it at once");
  ok(TEST.log.slice(lvLog).every(function (l) { return l.indexOf("confirm:") < 0; }), "without the browser's question");
  eq(st.sel.id, otherId, "the other entry is the open one");
  eq(st.byId.get(escId).title, "left with a save " + escId, "the left row shows the new title in the same frame");
  var lvRow = function () { return document.querySelector('#list .item[data-id="' + escId + '"]'); };
  if (lvRow()) has(lvRow().innerHTML, "saving…", "and says saving… on its row");
  await settle(8);
  eq(dbFind(escId).title, "left with a save " + escId, "the edit reached the server");
  if (lvRow()) ok(lvRow().innerHTML.indexOf("svmark") < 0, "and then the row says nothing");
  ok(!away.size, "nothing is left owed");

  // each door: ‹ List, Duplicate, Continue, a new entry, the voice close
  var doors = [
    ["‹ List", function () { $("#bBack").onclick ? $("#bBack").onclick() : click($("#bBack")); }],
    ["Duplicate", function () { duplicate(); }],
    ["Continue", function () { continueEntry(); }],
    ["a new entry", function () { newEntry(); }],
    ['"computer, close"', function () { VCMDS.find(function (c) { return c.say === "close"; }).fn(); }],
  ];
  for (var di = 0; di < doors.length; di++) {
    select(escId);
    setRead(false);
    $("#content").value = "door " + di + " " + escId;
    markDirty();
    lvLog = TEST.log.length;
    doors[di][1]();
    ok(TEST.log.slice(lvLog).every(function (l) { return l.indexOf("confirm:") < 0; }) &&
       !(st.sel && st.sel.id === escId), doors[di][0] + " leaves at once, no question");
    await settle(8);
    eq(dbFind(escId).content, "door " + di + " " + escId, doors[di][0] + " saved the text on the way out");
    if (st.isNew) { setClean(); closeEditor(); }
  }

  // a write that fails: the row says so, Retry sends it, the text is kept
  console.log("-- a save on the way out that fails --");
  select(escId);
  setRead(false);
  var lvWas = dbFind(escId).content;
  $("#content").value = "will fail " + escId;
  markDirty();
  var realFetch = fetch;
  fetch = function (url, init) {
    if (init && init.method === "PUT") return Promise.resolve({ ok: false, status: 500, statusText: "err",
      text: function () { return Promise.resolve('{"error":"disk on fire"}'); } });
    return realFetch(url, init);
  };
  closeEditor();
  await settle(8);
  eq(dbFind(escId).content, lvWas, "the server still has the old text");
  eq(st.byId.get(escId).content, lvWas, "and so does the row, again");
  ok(away.get(escId) && away.get(escId).state === "failed", "the row is marked not saved");
  if (lvRow()) has(lvRow().innerHTML, "Retry", "with a Retry on it");
  has($("#toast").textContent, "not saved", "and a toast says so");
  eq((lsGet("lcars.draft", {}) || {}).v && lsGet("lcars.draft", {}).v.content, "will fail " + escId, "the text is in the local draft");
  fetch = realFetch;
  awayRetry(escId);
  eq(st.byId.get(escId).content, "will fail " + escId, "Retry lays the text back over the row");
  await settle(8);
  eq(dbFind(escId).content, "will fail " + escId, "and sends it");
  ok(!away.size, "nothing owed after it lands");

  // failed again, then the entry opened: the text comes back into the form
  var fail500 = function (url, init) {
    if (init && init.method === "PUT") return Promise.resolve({ ok: false, status: 500, statusText: "err",
      text: function () { return Promise.resolve('{"error":"disk on fire"}'); } });
    return realFetch(url, init);
  };
  fetch = fail500;
  select(escId); setRead(false);
  $("#content").value = "comes back " + escId;
  markDirty();
  closeEditor();
  await settle(8);
  fetch = realFetch;
  ok(away.get(escId) && away.get(escId).state === "failed", "failed again");
  {
    select(escId);
    eq($("#content").value, "comes back " + escId, "reopening a not-saved entry puts its text back in the form");
    ok(document.body.classList.contains("dirty") && !st.read, "unsaved, in the editor");
    eq($("#edchip").dataset.s, "failed", "the chip says Not saved");
    await save();
    await settle(6);
    eq(dbFind(escId).content, "comes back " + escId, "and the chip's save sends it");
  }

  // Read with unsaved text: the reader at once, the chip carries the save
  console.log("-- Read switches at once --");
  select(escId); setRead(false);
  $("#content").value = "read at once " + escId;
  markDirty();
  setRead(true);
  ok(st.read && $("#readbody").style.display === "block", "Read shows the reader in the same frame");
  has($("#rd_content").innerHTML, "read at once", "showing what was written");
  eq($("#edchip").dataset.s, "saving", "the chip says Saving…");
  await settle(8);
  eq(dbFind(escId).content, "read at once " + escId, "the save lands");
  ok(["saved", "idle"].indexOf($("#edchip").dataset.s) >= 0, "and the chip says Saved");
  // and failing: back to the editor, the text and the chip's Retry
  setRead(false);
  $("#content").value = "read fails " + escId;
  markDirty();
  fetch = fail500;
  setRead(true);
  await settle(8);
  fetch = realFetch;
  ok(!st.read && document.body.classList.contains("dirty"), "a failed save on Read goes back to the editor, unsaved");
  eq($("#content").value, "read fails " + escId, "with the text");
  has($("#edchip").textContent, "Retry", "the chip red with its Retry");
  click($("#edchip"));
  eq($("#edchip").dataset.s, "saving", "a tap on the chip is Saving… in the same frame");
  await settle(8);
  eq(dbFind(escId).content, "read fails " + escId, "and saves it");

  // Revert has an Undo
  console.log("-- Revert's Undo --");
  $("#content").value = "reverted text " + escId;
  markDirty();
  $("#bRevert").onclick();
  eq($("#content").value, dbFind(escId).content, "Revert puts the server's text back");
  ok(!document.body.classList.contains("dirty"), "clean");
  var undoBtn = $("#toast").querySelector(".tact");
  ok(undoBtn && undoBtn.textContent === "Undo", "with an Undo in its toast");
  if (undoBtn) undoBtn.onclick();
  eq($("#content").value, "reverted text " + escId, "Undo puts the edit back");
  ok(document.body.classList.contains("dirty"), "unsaved, as it was");
  TEST.confirmAnswer = true;
  setClean();
  closeEditor();

  newEntry();
  key("Escape");
  eq(document.body.dataset.pane, "list", "a new entry has nothing to read, so Escape closes it");
  setClean();
  closeEditor();

  console.log("-- 4.9 ((id)) references one entry --");
  var ref = st.all.find(e => !e.deleted);
  $("#rd_content").innerHTML = mdRender("- see ((" + ref.id + "))");
  var er = $("#rd_content").querySelector("a.eref");
  ok(er, "((123)) renders as an entry reference");
  eq(er.textContent, "#" + ref.id, "showing the id it was written with");
  has(er.getAttribute("title"), ref.kind, "and what that row is, on hover");
  eq(er.getAttribute("href"), BASE + "entry/" + ref.id, "with the entry's url as its href, for a new tab");
  // a chat message's #123, and a crew report's, are the same link
  $("#rd_content").innerHTML = mdRender(chatRefs("see #" + ref.id + ", not `#" + ref.id + "`"));
  eq($("#rd_content").querySelectorAll("a.eref").length, 1, "a chat's #123 is that link, a code span's is not");
  eq($("#rd_content").querySelector("a.eref").getAttribute("href"), BASE + "entry/" + ref.id, "with the same href");
  has(crewLogHtml({ e: { id: 1, content: "- due: #" + ref.id } }), 'href="' + BASE + "entry/" + ref.id + '"', "a crew report's #123 too");
  $("#rd_content").innerHTML = mdRender("((999999999))");
  has($("#rd_content").innerHTML, "gone", "an id the journal does not hold is marked, not dropped");
  $("#rd_content").innerHTML = mdRender("a uuid ref ((5fe9f3a3-e2c0-4fd6-a135-4f986526bf3e))");
  eq($("#rd_content").querySelector("a.eref"), null, "Logseq's own uuid refs are left alone");
  $("#q").value = "";
  refresh();
  $("#rd_content").innerHTML = mdRender("- see ((" + ref.id + "))");
  click($("#rd_content").querySelector("a.eref"));
  eq(st.sel && st.sel.id, ref.id, "clicking one opens that entry");
  eq($("#q").value, "", "and searches for nothing — the row was already named");
  closeEditor();

  console.log("-- 4.10 the day page --");
  var perDay = new Map();
  st.all.forEach(e => {
    if (e.deleted) return;
    var k = dayKey(e.created_at_utc);
    perDay.set(k, (perDay.get(k) || 0) + 1);
  });
  // the fixture's busiest day, so the grouping has something to group
  var busiest = [...perDay.entries()].sort((a, b) => b[1] - a[1])[0][0];
  var drows = dayPageRows(busiest);
  var want = st.all.filter(e => !e.deleted && dayKey(e.created_at_utc) === busiest &&
                                !(e.kind === kindOf("page") && (e.title || "").trim() === busiest));
  eq(drows.length, want.length, "the day's live rows, all of them");
  ok(drows.every(e => !e.deleted), "and none that were deleted");
  ok(!drows.some(e => e.kind === kindOf("page") && (e.title || "").trim() === busiest),
     "nor the day's own page, which would only link to itself");
  var stamps = drows.map(e => e.created_at_utc);
  eq(stamps.join("|"), stamps.slice().sort().join("|"), "in clock order");

  var dtext = dayPageText(drows);
  ok(drows.every(e => dtext.indexOf("((" + e.id + "))") >= 0),
     "every entry of the day is linked");
  var heads = dtext.split("\n").filter(l => l.slice(0, 3) === "## ");
  var dkinds = [...new Set(drows.map(e => e.kind || "(no kind)"))];
  eq(heads.length, dkinds.length, "one heading per kind, and no kind twice");
  ok(dkinds.every(k => dtext.indexOf("## " + k + " · " +
       drows.filter(e => (e.kind || "(no kind)") === k).length) >= 0),
     "each heading counts its own rows");
  var lines = dtext.split("\n").filter(l => l.slice(0, 2) === "- ");
  eq(lines.length, drows.length, "one line per entry");
  var mins = lines.map(l => l.slice(2, 7));
  ok(mins.every(t => /^\d\d:\d\d$/.test(t)), "each line opens with a local time");

  // the whole point: it links, it does not quote
  var fat = drows.find(e => (e.content || "").length > 120 &&
                            (e.content || "").indexOf(e.title || "\u0000") !== 0);
  if (fat) ok(dtext.indexOf(fat.content.trim().slice(0, 60)) < 0, "no content is copied in");
  var shared = drows.find(e => {
    var t = (e.title || "").trim();
    return t && st.all.filter(x => !x.deleted &&
           (x.title || "").trim().toLowerCase() === t.toLowerCase()).length > 1;
  });
  if (shared) {
    ok(dtext.indexOf("[[" + shared.title.trim() + "]]") < 0,
       "a title several entries share is not a page name, so it is not bracketed");
    has(dtext, "((" + shared.id + "))", "its id still links it");
  }
  var own = drows.find(e => {
    var t = (e.title || "").trim();
    return t && t.length <= WIKI_TITLE_MAX && !/[[\]\n]/.test(t) &&
           st.all.filter(x => !x.deleted &&
             (x.title || "").trim().toLowerCase() === t.toLowerCase()).length === 1;
  });
  if (own) has(dtext, "[[" + own.title.trim() + "]]", "a title only one entry carries is bracketed");

  console.log("-- 4.10 the button --");
  TEST.confirmAnswer = true;
  setClean();
  closeEditor();
  hideToast();
  var today = isoDay(new Date());
  var mine = dayPageRows(today);
  click($("#bDayPage"));
  if (mine.length) {
    ok(st.isNew, "the day page opens as an entry that exists nowhere else yet");
    eq($("#e_kind").value, kindOf("page"), "of kind page");
    eq($("#e_head").value, today, "titled with the day itself, so [[2026-01-01]] finds it");
    ok(document.body.classList.contains("dirty"), "and dirty, so it cannot be lost by a stray key");
    has($("#content").value, "((" + mine[0].id + "))", "carrying links to the day");
    has($("#toast").textContent, "not saved yet", "the toast says it is still a draft");
    eq($("#edbody").style.display, "flex", "and it opens in the form, not the reader");
    setClean();
    closeEditor();
  } else {
    ok(!st.isNew, "a day with nothing in it makes no page");
    has($("#toast").textContent, "nothing logged", "and says so");
  }
  hideToast();

  console.log("\nsection D: " + TEST.asserts + " assertions, " + TEST.fails.length + " failures");
  globalThis.__phaseD = true;
})().catch(function (e) { console.log("SUITE D THREW: " + e + "\n" + (e && e.stack)); });

/* ===================== suite F: the month, related, trends, templates,
                         capture, views and ambient ===================== */

/* lcarsPrompt is a themed dialog like lcarsConfirm, but it answers with a
   string: fill the box, then press its OK. Returns false, loudly, if nothing
   was actually up — a test that expected to be asked and was not has found
   something. */
async function answerPrompt(text) {
  await settle(3);
  if (!$("#lcIn") || !$("#ov").classList.contains("on")) {
    TEST.fails.push("expected a prompt, found none");
    console.log("  FAIL expected a prompt, found none");
    return false;
  }
  if (text === null) { click($("#lcNo")); await settle(3); return true; }
  // a browser cuts typed or pasted text at maxlength without a word; the
  // shim does not, so it is done here, or a box too short would pass
  var max = Number($("#lcIn").getAttribute("maxlength")) || 0;
  $("#lcIn").value = max ? String(text).slice(0, max) : text;
  click($("#lcOk"));
  await settle(3);
  return true;
}

(async function () {
  if (!await waitFlag("__phaseD")) return;
  closeEditor();
  setClean();
  clearFilters();

  /* ---------- the month grid ---------- */
  console.log("\n-- the month: a calendar of what each day holds --");
  // Two rows of today's: the month and the calendar below need a day of this
  // month with something in it, and one with several. The journal's own
  // rows have neither in a month's first hours; taken out with the
  // calendar's drawn entry, before the sections that count the top rows.
  var calPlanted = [await plant({ title: "Calendar probe one", content: "morning" }),
                    await plant({ kind: "work_log", title: "Calendar probe two", content: "noon" })];
  var nowMonth = isoDay(new Date()).slice(0, 7);
  openMonth();
  eq(monthAt, nowMonth, "with no argument it opens on this month");
  has($("#dlgh").textContent, MO[+nowMonth.slice(5) - 1], "headed with the month's name");
  eq($("#mogrid").querySelectorAll(".mcalh").length, 7, "seven weekday headers");

  var y = +nowMonth.slice(0, 4), mo = +nowMonth.slice(5);
  var len = new Date(y, mo, 0).getDate();
  var lead = new Date(y, mo - 1, 1).getDay();
  eq($("#mogrid").querySelectorAll(".mcd:not(.pad)").length, len, "one cell per day of the month");
  eq($("#mogrid").querySelectorAll(".mcd.pad").length, lead, "and a spacer for each day before the 1st");
  ok($("#mogrid").querySelector(".mcd.today"), "today is marked");
  ok($("#monext").disabled, "there is no month after this one to turn to");
  ok($("#motoday").disabled, "and nowhere for This month to go");

  var withRows = $("#mogrid").querySelectorAll(".mcd.has");
  ok(withRows.length > 0, "a day of this month with rows in it is marked");
  var cell = withRows[withRows.length - 1];
  ok(cell.querySelector(".mcdc"), "a day that holds something prints its count");
  ok(cell.querySelector(".mcdd i"), "and a dot for each kind that wrote in it");
  ok(!cell.disabled, "it can be clicked");
  var empty = $("#mogrid").querySelector(".mcd:not(.pad):not(.has)");
  if (empty) ok(empty.disabled, "a day with nothing in it is not a button");
  has($("#monote").textContent, "busiest", "the note names the busiest day");

  console.log("-- the month: turning the page --");
  click($("#moprev"));
  eq(monthAt, monthShift(nowMonth, -1), "back one month");
  ok(!$("#monext").disabled, "and now there is one to turn forward to");
  ok(!$("#motoday").disabled, "This month has somewhere to go");
  click($("#moprev"));
  click($("#moprev"));
  eq(monthAt, monthShift(nowMonth, -3), "three back");
  key("ArrowRight");
  eq(monthAt, monthShift(nowMonth, -2), "the right arrow walks forward");
  key("ArrowLeft");
  eq(monthAt, monthShift(nowMonth, -3), "and the left arrow back");
  click($("#motoday"));
  eq(monthAt, nowMonth, "This month returns");
  key("ArrowRight");
  eq(monthAt, nowMonth, "and the arrow refuses to walk past it, like the button does");
  // the year boundary is the one piece of date arithmetic worth pinning down
  eq(monthShift("2026-01", -1), "2025-12", "December is the month before January");
  eq(monthShift("2025-12", 1), "2026-01", "and January the month after December");
  eq(monthLabel("2026-03"), "Mar 2026", "a month reads as a name and a year");

  console.log("-- the month: a day hands over to the reader --");
  // the grid was rebuilt by every step above, so the cell is re-found here:
  // the one captured earlier belongs to a render that no longer exists
  cell = $("#mogrid").querySelectorAll(".mcd.has").pop();
  var dayKeyClicked = cell.dataset.d;
  ok(!!st.dayOf && dayEntries(dayKeyClicked).length > 0,
     "with the filters clear, the list can already show that day");
  click(cell);
  eq(dayOpen, dayKeyClicked, "clicking it opens the day reader on it");
  eq($("#fSince").value, "", "and a day the list could already show leaves the filters alone");
  closeOv();
  eq(monthAt, null, "closing the overlay takes the month's arrow keys with it");

  // the other branch: the reader reads st.view, so a day the filters are
  // hiding has to be put in front of them or it would open empty
  clearFilters();
  $("#fSince").value = "2099-01-01";
  refresh();
  eq(dayEntries(dayKeyClicked).length, 0, "that day is now filtered away");
  monthGo(dayKeyClicked);
  eq($("#fSince").value, dayKeyClicked, "so it is put in front of the filters");
  eq($("#fUntil").value, dayKeyClicked, "as a range of exactly that one day");
  eq(dayOpen, dayKeyClicked, "and then it opens");
  closeOv();

  // and the third: a sort that cannot be cut into days at all
  clearFilters();
  $("#fSort").value = "len:desc";
  refresh();
  ok(!st.dayOf, "a length sort scatters a day all over the list");
  monthGo(dayKeyClicked);
  eq($("#fSort").value, "created:desc", "so clicking a day puts the list back into date order");
  eq(dayOpen, dayKeyClicked, "and the day opens after all");
  closeOv();
  $("#fSort").value = "created:desc";
  clearFilters();
  hideToast();

  /* ---------- the calendar: the other three scales ---------- */
  console.log("\n-- the calendar: its own arithmetic --");
  eq(calShiftDays("2026-09-21", 7), "2026-09-28", "a week on");
  eq(calShiftDays("2026-03-01", -1), "2026-02-28", "and back over a month boundary");
  eq(calShiftDays("2024-02-28", 1), "2024-02-29", "a leap day is a day");
  eq(calWeekStart("2026-09-21"), "2026-09-20", "a week starts on its Sunday");
  eq(calWeekStart("2026-09-20"), "2026-09-20", "and a Sunday starts its own");
  // the whole reason months are stepped with a clamp rather than by setMonth
  eq(calShiftMonths("2026-01-31", 1), "2026-02-28", "the 31st into a short month is its last day");
  eq(calShiftMonths("2026-03-31", -1), "2026-02-28", "in either direction");
  eq(calShiftMonths("2026-09-21", -12), "2025-09-21", "and a year is twelve of them");
  eq(calMonthLen(2024, 2), 29, "February is longer in a leap year");
  eq(calMonthLen(2026, 2), 28, "and is not in this one");
  eq(calWeekLabel("2026-09-21"), "20 – 26 Sep 2026", "a week inside one month names it once");
  has(calWeekLabel("2026-09-30"), "Sep", "one that straddles two names both");
  has(calWeekLabel("2026-09-30"), "Oct", "both ends, that is");
  has(calWeekLabel("2026-01-01"), "2025", "and one that straddles a year names both years");
  eq(calLevel(0), 0, "no entries is no colour");
  eq(calLevel(1), 1, "one is the faintest");
  eq(calLevel(99), 4, "and a heavy day tops out");

  console.log("-- the calendar: four scales over one anchor --");
  var todayK = calToday();
  calOpen("year", todayK);
  eq(calScale, "year", "it opens on the scale it was asked for");
  eq($("#dlgh").textContent, todayK.slice(0, 4), "headed with the year");
  eq($("#mogrid").querySelectorAll(".calmo").length, 12, "twelve months are drawn");
  eq($("#mogrid").querySelectorAll(".calmoh").length, 12, "each with a heading that opens it");
  eq($("#motoday").textContent, "This year", "and This-year is what the button now says");
  ok($("#monext").disabled, "there is no year after this one");
  // every square of every month, and one spacer per lead-in day
  var jan = $("#mogrid").querySelectorAll(".calmg")[0];
  eq(jan.querySelectorAll("button:not(.pad)").length, 31, "January has its 31 days");
  eq(jan.querySelectorAll("button.pad").length, new Date(+todayK.slice(0, 4), 0, 1).getDay(),
     "and a spacer for each day before the 1st");
  ok($("#mogrid").querySelector(".calmg button.today"), "today is marked in the year too");

  calOpen("week", todayK);
  eq(calScale, "week", "the week scale");
  eq($("#mogrid").querySelectorAll(".calcol").length, 7, "seven columns");
  eq($("#mogrid").querySelectorAll(".calch").length, 7, "each with a header that zooms to the day");
  eq($("#dlgh").textContent, calWeekLabel(todayK), "headed with the span it covers");
  eq($("#motoday").textContent, "This week", "This-week");
  eq($("#mogrid").querySelector(".calcol[data-drop]").dataset.drop, calWeekStart(todayK),
     "the first column is the week's Sunday");
  ok($("#mogrid").querySelector(".calcol.today"), "today's column is marked");

  calOpen("day", todayK);
  eq(calScale, "day", "the day scale");
  eq($("#mogrid").querySelectorAll(".calhr").length, 24, "twenty-four hours");
  eq($("#mogrid").querySelectorAll(".calhr[data-hour]").length, 24, "every one of them a place to drop on");
  eq($("#mogrid").querySelectorAll(".calhr")[13].dataset.hour, "13", "in order, from midnight");
  eq($("#dlgh").textContent, dayLabelText(todayK), "headed with the day");
  eq($("#motoday").textContent, "Today", "Today");
  ok($("#mogrid").querySelector(".calhr.now"), "and the hour it is now is marked");

  console.log("-- the calendar: stepping by whatever the scale is --");
  calOpen("week", todayK);
  click($("#moprev"));
  eq(calAt, calShiftDays(todayK, -7), "the week steps by seven days");
  key("ArrowRight");
  eq(calAt, todayK, "and the arrow walks back the same distance");
  key("ArrowRight");
  eq(calAt, todayK, "but never past the week we are in");
  calOpen("day", todayK);
  click($("#moprev"));
  eq(calAt, calShiftDays(todayK, -1), "the day steps by one");
  calOpen("year", todayK);
  click($("#moprev"));
  eq(calAt, calShiftMonths(todayK, -12), "and the year by twelve months");
  ok(!$("#monext").disabled, "there is a year to walk forward to now");

  console.log("-- the calendar: switching scale keeps the anchor --");
  calOpen("month", "2026-06-11");
  click($("#moscale").querySelector('button[data-v="week"]'));
  eq(calScale, "week", "the segmented control switches scale");
  eq(calAt, "2026-06-11", "without moving off the day it was anchored on");
  eq($("#dlgh").textContent, calWeekLabel("2026-06-11"), "so the heading is that day's week");
  key("y");
  eq(calScale, "year", "y is the year");
  key("m");
  eq(calScale, "month", "m the month");
  key("w");
  eq(calScale, "week", "w the week");
  key("d");
  eq(calScale, "day", "and d the day");
  eq(calAt, "2026-06-11", "none of which moved the anchor");
  eq(monthAt, "2026-06", "and monthAt follows the anchor's month wherever it goes");
  closeOv();
  ok(!calRepaint && !calGo, "closing takes the repaint and the scale switch with the arrow keys");
  key("w");
  ok(calScale === "day", "so w means nothing once the calendar is down");

  console.log("-- the calendar: an entry, drawn and named --");
  // a day the fixture certainly wrote in, found through the index the grid uses
  var calIdx = calIndex();
  var busiest = null;
  // A scheduled row is drawn as a block in the lane rather than as a chip, so
  // the day chosen is one with none: this block is about the chips.
  calIdx.forEach(function (rows, k) {
    if (rows.some(function (e) { return e.start_date; })) return;
    if (!busiest || rows.length > calIdx.get(busiest).length) busiest = k;
  });
  ok(!!busiest && calIdx.get(busiest).length > 1, "a day with several entries is found");
  calOpen("day", busiest);
  var chips = $("#mogrid").querySelectorAll(".mce");
  eq(chips.length, calIdx.get(busiest).length, "every entry of the day is drawn");
  eq(chips[0].dataset.id, String(calIdx.get(busiest)[0].id), "oldest first");
  ok(chips[0].querySelector("b").textContent.indexOf(":") === 2, "each carrying its wall-clock time");
  eq(calName({ title: "  Named  ", content: "body" }), "Named", "a title is what an entry is called");
  eq(calName({ title: "", content: "\n\n- first line\nsecond" }), "first line",
     "without one, the first line that says anything, unbulleted");
  eq(calName({ title: "", content: "   \n  " }), "#undefined",
     "and an entry with nothing at all is its own number");
  eq(calName({ id: 7, title: "" }), "#7", "as is one whose body has not been swept in yet");

  console.log("-- the calendar: a month cell names what it has room for --");
  calOpen("month", busiest);
  var full = $("#mogrid").querySelector('.mcd[data-d="' + busiest + '"]');
  ok(!!full, "the busiest day has a cell");
  ok(full.querySelectorAll(".mce").length <= MONTH_CHIPS, "which names at most MONTH_CHIPS entries");
  if (calIdx.get(busiest).length > MONTH_CHIPS)
    has(full.querySelector(".mcdx").textContent, "more", "and counts the rest");
  eq(full.dataset.drop, busiest, "and is a place another entry can be dropped");

  console.log("-- the calendar: moving an entry rewrites one column --");
  var mover = calIdx.get(busiest)[0];
  var wasAt = mover.created_at_utc;
  var wasHm = localOf(wasAt).slice(11);
  var target = calShiftDays(busiest, -3);
  // the restamp on its own first: this is the part with the calendar arithmetic
  eq(dayKey(calRestamp(mover, target)), target, "a move lands on the day it was dropped on");
  eq(localOf(calRestamp(mover, target)).slice(11), wasHm, "keeping the time of day it was written at");
  eq(calRestamp(mover, dayKey(wasAt)), null, "and a drop back where it started is not a move");
  eq(localOf(calRestamp(mover, target, 5)).slice(11, 13), "05", "an hour drop retimes it");
  eq(localOf(calRestamp(mover, target, 5)).slice(14), wasHm.slice(3), "minutes and all survive it");

  TEST.fetches.length = 0;
  await calMove(mover.id, target);
  await settle(6);
  eq(dayKey(mover.created_at_utc), target, "the row really moved");
  var puts = TEST.fetches.filter(function (f) { return f.indexOf("PUT") === 0; });
  eq(puts.length, 1, "one PUT, no more");
  // the refetch that follows the write is the last line in the log; the write
  // itself is the one before it
  var sent = DBLOG.filter(function (l) { return l.indexOf("PUT") === 0; }).pop();
  has(sent, "created_at_utc", "carrying the date");
  ok(sent.indexOf("content") < 0 && sent.indexOf("\"kind\"") < 0,
     "and nothing else — a move is not an edit");
  has($("#toast").textContent, "moved to", "the toast says so");

  var undoMove = $("#toast").querySelector("button");
  ok(!!undoMove, "and offers it back");
  click(undoMove);
  await settle(6);
  eq(mover.created_at_utc, wasAt, "which puts the entry back exactly where it was");

  // a drop on the day it already sits in is refused before any request is made
  TEST.fetches.length = 0;
  await calMove(mover.id, dayKey(wasAt));
  await settle(3);
  eq(TEST.fetches.length, 0, "a drop that moves nothing never reaches the server");
  has($("#toast").textContent, "already there", "and says why");
  hideToast();

  /* ---------- the day view as a schedule ----------
     start_date/end_date say what an entry is *for*; created_at_utc says when it
     was written. The day view is the one place both are on screen at once, so
     it is the one place the difference has to be visible. */
  console.log("-- the calendar: scheduled blocks in the day view --");
  var schedDay = calShiftDays(calToday(), 5);   // a future day, so nothing was written in it
  // a local 14:00–15:30 on that day, expressed the way the column stores it
  var blkStart = fmtUtc(new Date(calDate(schedDay).getFullYear(), calDate(schedDay).getMonth(),
                                 calDate(schedDay).getDate(), 14, 0, 0));
  var blkEnd = fmtUtc(new Date(calDate(schedDay).getFullYear(), calDate(schedDay).getMonth(),
                               calDate(schedDay).getDate(), 15, 30, 0));
  var blk = st.all[3];
  blk.start_date = blkStart;
  blk.end_date = blkEnd;

  calOpen("day", schedDay);
  var blocks = $("#mogrid").querySelectorAll(".calblk");
  eq(blocks.length, 1, "a scheduled entry draws a block on the day it is for");
  eq(blocks[0].dataset.id, String(blk.id), "the entry it belongs to");
  ok($("#mogrid").querySelector(".calday.sched"), "and the hour rows go to a fixed height to line up with it");
  // the geometry is read off the emitted attribute, not el.style: the shim's
  // style object is a JS-side bag that parsed markup never fills
  has(blocks[0].getAttribute("style"), "top:" + (14 * CAL_HOUR_PX).toFixed(1) + "px",
      "positioned at the hour it starts");
  has(blocks[0].getAttribute("style"), "height:" + (90 * CAL_HOUR_PX / 60).toFixed(1) + "px",
      "and as tall as it lasts");
  has($("#monote").textContent, "1 scheduled", "the note counts it");
  has($("#mohint").textContent, "schedule it", "and the hint says what a drag here does");
  has(flagSpans(blk), localOf(blk.start_date).slice(5),
      "a scheduled entry carries its time wherever it is listed");
  ok(flagSpans(st.all.find(function (x) { return !x.start_date; })).indexOf(":") < 0,
     "while an unscheduled one says nothing at all");
  eq($("#mogrid").querySelectorAll(".calhr").length, 24, "the hour rows are still all there");
  eq($("#mogrid").querySelectorAll(".calhr[data-hour]").length, 24, "still every one a place to drop on");

  // an open-ended start is a marker, not a span it never claimed
  blk.end_date = "";
  calOpen("day", schedDay);
  ok($("#mogrid").querySelector(".calblk.open"), "a start with no end draws as an open block");
  blk.end_date = blkEnd;

  console.log("-- the calendar: written and scheduled are two different questions --");
  // the same entry, scheduled for the day it was also written in
  var both = calIdx.get(busiest)[0];
  var bothWas = { s: both.start_date, e: both.end_date };
  both.start_date = fmtUtc(new Date(calDate(busiest).getFullYear(), calDate(busiest).getMonth(),
                                    calDate(busiest).getDate(), 8, 0, 0));
  both.end_date = "";
  calOpen("day", busiest);
  eq($("#mogrid").querySelectorAll('.calblk[data-id="' + both.id + '"]').length, 1,
     "an entry scheduled today shows as a block");
  eq($("#mogrid").querySelectorAll('.mce[data-id="' + both.id + '"]').length, 0,
     "and not also as a chip — one entry, one mark");
  ok($("#mogrid").querySelectorAll(".mce").length > 0,
     "while everything else written that day still is a chip");
  both.start_date = bothWas.s; both.end_date = bothWas.e;

  console.log("-- the calendar: a block that runs past midnight --");
  var nightA = calShiftDays(calToday(), 8), nightB = calShiftDays(nightA, 1);
  blk.start_date = fmtUtc(new Date(calDate(nightA).getFullYear(), calDate(nightA).getMonth(),
                                   calDate(nightA).getDate(), 23, 0, 0));
  blk.end_date = fmtUtc(new Date(calDate(nightB).getFullYear(), calDate(nightB).getMonth(),
                                 calDate(nightB).getDate(), 1, 0, 0));
  calOpen("day", nightA);
  eq($("#mogrid").querySelectorAll(".calblk").length, 1, "it is on the day it starts");
  has($("#mogrid").querySelector(".calblk").getAttribute("style"),
      "height:" + (60 * CAL_HOUR_PX / 60).toFixed(1) + "px", "drawn only as far as midnight");
  calOpen("day", nightB);
  eq($("#mogrid").querySelectorAll(".calblk").length, 1, "and on the day it ends");
  has($("#mogrid").querySelector(".calblk").getAttribute("style"), "top:0.0px",
      "picked up again at midnight");

  console.log("-- the calendar: dragging in the day view schedules, it does not rewrite history --");
  blk.start_date = blkStart;
  blk.end_date = blkEnd;
  calOpen("day", schedDay);
  eq(calMoveField(), "start_date", "a day-view drag moves when the entry is for");
  calOpen("month", schedDay);
  eq(calMoveField(), "created_at_utc", "every other scale still moves when it was written");
  has($("#mohint").textContent, "when it was written", "and says so");
  calOpen("day", schedDay);
  var wroteAt = blk.created_at_utc;
  TEST.fetches.length = 0;
  await calMove(blk.id, schedDay, 9);
  await settle(6);
  eq(localOf(blk.start_date).slice(11, 13), "09", "the block lands on the hour it was dropped on");
  eq(blk.created_at_utc, wroteAt, "and when it was written is untouched");
  eq(Math.round((new Date(blk.end_date.replace(" ", "T") + "Z") -
                 new Date(blk.start_date.replace(" ", "T") + "Z")) / 60000), 90,
     "the block is still ninety minutes long — a move is not a resize");
  var schedPut = DBLOG.filter(function (l) { return l.indexOf("PUT") === 0; }).pop();
  has(schedPut, "start_date", "the PUT carries the start");
  has(schedPut, "end_date", "and the end, so the duration travels with it");
  ok(schedPut.indexOf("created_at_utc") < 0, "and not created_at_utc — that is not what was moved");
  has($("#toast").textContent, "scheduled for", "the toast says scheduled, not moved");

  var undoSched = $("#toast").querySelector("button");
  ok(!!undoSched, "with an undo");
  click(undoSched);
  await settle(6);
  eq(blk.start_date, blkStart, "which puts the start back");
  eq(blk.end_date, blkEnd, "and the end with it");

  console.log("-- the calendar: dropping an unscheduled entry is how it gets a time --");
  var fresh = st.all[4];
  fresh.start_date = ""; fresh.end_date = "";
  eq(dayKey(calRestamp(fresh, schedDay, 11, "start_date")), schedDay,
     "an entry with no start_date still restamps, onto the day it was dropped on");
  eq(localOf(calRestamp(fresh, schedDay, 11, "start_date")).slice(11, 13), "11",
     "taking the dropped hour as the whole answer, since there was no time to keep");
  // the other column is never invented the same way: a row with no
  // created_at_utc is a corrupt row, not an entry waiting to be scheduled
  var noStamp = { id: -1, created_at_utc: "", start_date: "" };
  eq(calRestamp(noStamp, schedDay, 11), null, "an unparseable created_at_utc restamps to nothing");
  eq(dayKey(calRestamp(noStamp, schedDay, 11, "start_date")), schedDay,
     "while the same row can still be scheduled");
  console.log("-- the calendar: reading a time back off the day grid --");
  eq(calMinutesAt(0), 0, "the top of the lane is midnight");
  eq(calMinutesAt(24 * CAL_HOUR_PX), 1440, "and the bottom is the far end of the day");
  eq(calMinutesAt(14 * CAL_HOUR_PX), 840, "an hour down is that hour");
  eq(calMinutesAt(14 * CAL_HOUR_PX + CAL_HOUR_PX / 4), 855, "a quarter into it is quarter past");
  eq(calMinutesAt(14 * CAL_HOUR_PX + 2), 840, "and a couple of stray pixels snap back to it");
  eq(calMinutesAt(-500), 0, "a drag off the top stops at midnight");
  eq(calMinutesAt(99999), 1440, "and one off the bottom stops at the other midnight");
  eq(calMinutesAt(0) % CAL_SNAP_MIN, 0, "every answer is on the snap grid");

  eq(calRangeOf(540, 600).from, 540, "a range keeps the earlier end as its start");
  eq(calRangeOf(600, 540).from, 540, "however the drag ran");
  eq(calRangeOf(600, 540).to, 600, "and the later one as its end");
  eq(calRangeOf(540, 540).to, 540 + CAL_MIN_BLOCK, "a drag that barely moved still makes a block");
  eq(calRangeOf(1440, 1440).to, 1440, "one drawn at the bottom cannot run past midnight");
  eq(calRangeOf(1440, 1440).from, 1440 - CAL_MIN_BLOCK, "it is pushed back up to fit instead");

  eq(calNewRange(600).from, 600, "a click starts its block where it landed");
  eq(calNewRange(600).to, 600 + CAL_NEW_MINS, "and ends it the default length later");
  eq(CAL_NEW_MINS, 30, "which is half an hour");
  ok(calNewRange(600).to > calNewRange(600).from,
     "so the block has a lower edge to grab straight away");
  eq(calNewRange(1430).to, 1440, "one clicked in the last minutes stops at midnight");
  eq(calNewRange(1430).from, 1440 - CAL_NEW_MINS, "and is pushed back up to its full length");
  eq(localOf(calStampAt(schedDay, 840)).slice(11), "14:00", "a time on the grid stamps as that local time");
  eq(dayKey(calStampAt(schedDay, 840)), schedDay, "on the day it was drawn on");

  console.log("-- the calendar: drawing a new entry on empty hours --");
  var before = st.all.length;
  TEST.fetches.length = 0;
  await calCreate(schedDay, 600, 690);
  await settle(8);
  eq(st.all.length, before + 1, "the drag made an entry");
  var made = st.all.find(function (x) { return x.kind === kindOf("log") && x.start_date; });
  ok(!!made, "in the kind a drawn block defaults to");
  eq(kindOf("log"), KINDMAP.log ? KINDMAP.log.kind : "personal_log", "which is the log role's kind (personal_log by default)");
  eq(localOf(made.start_date).slice(11), "10:00", "starting where the drag did");
  eq(localOf(made.end_date).slice(11), "11:30", "and ending where it stopped");
  // the server fills an empty title with its own placeholder, so the gesture
  // cannot leave the field blank — it leaves it selected instead
  eq(made.title, "HTTP Entry", "carrying the placeholder the server gives an untitled row");
  // Sketching a day is draw-name-draw-name, so the calendar keeps the screen
  // and the naming happens on the block itself.
  ok(monthAt !== null, "the calendar is still up");
  eq(st.sel, null, "nothing was opened in the editor");
  var ren = $("#mogrid").querySelector(".calren");
  ok(!!ren, "the new block carries a name field");
  eq(TEST.focused, ren, "with the cursor already in it");
  eq(ren.value, "HTTP Entry", "on the placeholder the server gave it, ready to be typed over");
  eq(crename && crename.id, made.id, "and it is that block's, not another's");

  ren.value = "Deep work";
  dispatch(ren, "keydown", { key: "Enter" });
  await settle(8);
  eq(made.title, "Deep work", "Enter writes the name and nothing else");
  var renPut = DBLOG.filter(function (l) { return l.indexOf("PUT") === 0; }).pop();
  has(renPut, "title", "the PUT carries the title");
  ok(renPut.indexOf("content") < 0, "and not the body — this field edits one column");
  eq($("#mogrid").querySelector(".calren"), null, "the field is gone once it has been said");
  eq(crename, null, "and nothing is left holding it");
  has($("#mogrid").textContent, "Deep work", "the block says what it is");

  // Escape is the way out that writes nothing — and it must not take the
  // calendar with it, which is what that key means everywhere else up there.
  ok(calRenameOpen(made.id), "the field opens again on a block");
  var ren2 = $("#mogrid").querySelector(".calren");
  ren2.value = "thrown away";
  var esc = dispatch(ren2, "keydown", { key: "Escape" });
  ok(esc.defaultPrevented, "Escape is taken by the field");
  eq(made.title, "Deep work", "and drops what was typed");
  ok(monthAt !== null, "leaving the calendar where it was");
  eq($("#mogrid").querySelector(".calren"), null, "with the field closed");

  var undoNew = $("#toast").querySelector("button");
  ok(!!undoNew, "the toast offers it back");
  click(undoNew);
  await settle(8);
  eq(made.deleted, 1, "taking it back soft-deletes it, so it is still there to restore");
  hideToast();
  // and then out of the fixture entirely: this is the only test that adds a
  // row, insertRow puts it at the head of st.all, and later sections reach for
  // st.all[0] expecting a journal entry they can write into
  st.all.splice(st.all.indexOf(made), 1);
  st.byId.delete(made.id);
  DB.splice(DB.findIndex(function (r) { return r.id === made.id; }), 1);
  st.sel = null;
  refresh();
  calPlanted.forEach(unplant);

  console.log("-- the calendar: dragging one edge retimes one end --");
  blk.start_date = blkStart;
  blk.end_date = blkEnd;
  calOpen("day", schedDay);
  var keepEnd = blk.end_date;
  TEST.fetches.length = 0;
  await calResize(blk.id, "start", 780);          // 13:00
  await settle(6);
  eq(localOf(blk.start_date).slice(11), "13:00", "the top edge moves the start");
  eq(blk.end_date, keepEnd, "and leaves the end exactly where it was");
  var rz = DBLOG.filter(function (l) { return l.indexOf("PUT") === 0; }).pop();
  has(rz, "start_date", "the PUT carries the edge that moved");
  ok(rz.indexOf("end_date") < 0, "and not the one that did not");

  var keepStart = blk.start_date;
  await calResize(blk.id, "end", 1020);           // 17:00
  await settle(6);
  eq(localOf(blk.end_date).slice(11), "17:00", "the bottom edge moves the end");
  eq(blk.start_date, keepStart, "leaving the start alone");
  var rz2 = DBLOG.filter(function (l) { return l.indexOf("PUT") === 0; }).pop();
  ok(rz2.indexOf("start_date") < 0, "and sends only end_date");

  // the block is now 13:00-17:00; the grips have to be on it
  calOpen("day", schedDay);
  var live = $("#mogrid").querySelector('.calblk[data-id="' + blk.id + '"]');
  ok(!!live, "the block is drawn");
  eq(live.querySelectorAll(".calgrip").length, 2, "with a grip at each end to take hold of");
  eq(live.querySelector('.calgrip[data-grip="start"]') ? "start" : "", "start", "one for the start");
  eq(live.querySelector('.calgrip[data-grip="end"]') ? "end" : "", "end", "one for the end");

  console.log("-- the calendar: an edge that is only where midnight cut it is not a grip --");
  blk.start_date = fmtUtc(new Date(calDate(nightA).getFullYear(), calDate(nightA).getMonth(),
                                   calDate(nightA).getDate(), 23, 0, 0));
  blk.end_date = fmtUtc(new Date(calDate(nightB).getFullYear(), calDate(nightB).getMonth(),
                                 calDate(nightB).getDate(), 1, 0, 0));
  calOpen("day", nightA);
  var spill = $("#mogrid").querySelector(".calblk");
  ok(!!spill.querySelector('.calgrip[data-grip="start"]'), "the day it starts on offers the start");
  ok(!spill.querySelector('.calgrip[data-grip="end"]'), "but not an end it does not have here");
  calOpen("day", nightB);
  spill = $("#mogrid").querySelector(".calblk");
  ok(!spill.querySelector('.calgrip[data-grip="start"]'), "and the day it ends on offers no start");
  ok(!!spill.querySelector('.calgrip[data-grip="end"]'), "only the end");

  console.log("-- the calendar: the grid is uniform so a drag on it means a time --");
  calOpen("day", calShiftDays(calToday(), 12));   // a day with nothing at all in it
  eq($("#mogrid").querySelectorAll(".calhr").length, 24, "an empty day still draws all of it");
  ok($("#mogrid").querySelector(".calday.sched"), "on the fixed hour scale");
  ok($("#mogrid").querySelector(".calsched"), "with a lane to draw a new block on");

  console.log("-- the calendar: it shows what the filters show --");
  var calTotal = function () {
    var n = 0;
    calIndex().forEach(function (a) { n += a.length; });
    return n;
  };
  clearFilters();
  var allN = calTotal();
  ok(allN > 0, "unfiltered, the calendar has the journal in it");

  // narrow to one kind: the calendar has to come down with the list. The
  // kind is one the calendar holds, and how many it holds is counted off the
  // unfiltered index: st.all[0]'s kind could be a crew one the calendar
  // hides, or the journal's only kind that day.
  var calKinds = new Map();
  calIndex().forEach(function (a) { a.forEach(function (e) {
    if (e.kind) calKinds.set(e.kind, (calKinds.get(e.kind) || 0) + 1); }); });
  var oneKind = calKinds.keys().next().value;
  setKinds([oneKind]);
  refresh();
  var kindN = calTotal();
  eq(kindN, calKinds.get(oneKind), "pinning a kind narrows the calendar to that kind's entries");
  ok(kindN < allN || calKinds.size === 1, "and to fewer than all of them");
  var offKind = 0;
  calIndex().forEach(function (a) {
    for (var i = 0; i < a.length; i++) if (a[i].kind !== oneKind) offKind++;
  });
  eq(offKind, 0, "and nothing of another kind is left in it");
  eq($("#mogrid") && calScale, "day", "still on the scale it was on");

  // the month grid is built from the same index, so it comes down with it
  calOpen("month", busiest);
  var shownIds = [];
  var cells = $("#mogrid").querySelectorAll(".mce[data-id]");
  for (var ci = 0; ci < cells.length; ci++) shownIds.push(+cells[ci].dataset.id);
  var wrongKind = shownIds.filter(function (id) {
    var e = st.byId.get(id);
    return e && e.kind !== oneKind;
  });
  eq(wrongKind.length, 0, "the month grid names only entries of that kind");
  has($("#monote").textContent, "filtered (1)",
      "and the note says the grid is narrowed, not that the month was quiet");

  // state, the other half of what was asked for
  setKinds([]);
  $("#fDel").value = "all";
  refresh();
  ok(calTotal() >= allN, "asking for deleted rows as well puts them in the calendar");
  $("#fDel").value = "del";
  refresh();
  var delOnly = 0, delWrong = 0;
  calIndex().forEach(function (a) {
    for (var i = 0; i < a.length; i++) { delOnly++; if (!a[i].deleted) delWrong++; }
  });
  eq(delWrong, 0, "and asking for only the deleted ones shows only those");
  ok(delOnly < allN, "which is fewer than the whole journal");
  $("#fDel").value = "live";
  refresh();

  console.log("-- the calendar: except the date range, which is its own axis --");
  $("#fSince").value = "2099-01-01";
  $("#fUntil").value = "2099-01-02";
  refresh();
  eq(st.view.length, 0, "a date range nothing falls in empties the list");
  eq(calTotal(), allN, "but the calendar keeps its grid — monthGo sets those two itself");
  calOpen("month", busiest);
  ok($("#monote").textContent.indexOf("filtered") < 0,
     "and does not claim to be narrowed by a filter it ignored");
  clearFilters();
  eq(calTotal(), allN, "and clearing the filters puts everything back");

  blk.start_date = ""; blk.end_date = "";
  closeOv();
  hideToast();

  console.log("-- the calendar: clicking through it --");
  calOpen("day", busiest);
  click($("#mogrid").querySelector(".mce"));
  await settle(3);
  eq(st.sel && st.sel.id, calIdx.get(busiest)[0].id, "clicking an entry opens it");
  eq(monthAt, null, "and closes the calendar behind it");

  calOpen("year", busiest);
  click($("#mogrid").querySelector('.calmoh[data-mo="' + busiest.slice(0, 7) + '"]'));
  eq(calScale, "month", "a month's name in the year view opens that month");
  eq(calAt.slice(0, 7), busiest.slice(0, 7), "on the month it named");

  calOpen("week", busiest);
  click($("#mogrid").querySelector('.calch[data-zoom="' + busiest + '"]'));
  eq(calScale, "day", "a week column's header zooms into that day");
  eq(calAt, busiest, "the one it belongs to");
  closeOv();
  hideToast();

  /* ---------- possibly related ---------- */
  console.log("\n-- related: the vocabulary index --");
  // Two long entries of the suite's own that share rare words and a [[link]]:
  // the related block, the trend chart and the stack below each need the
  // journal to hold such a thing, and the day's newest rows may not (a long
  // row, a link written this year, two titles nobody else carries). Taken
  // out after the stack.
  var relText = "The greenhouse survey counted quorvex seedlings, brimlet vines and " +
    "the tallow irrigation manifold. [[Greenhouse Survey]] notes: humidity readings " +
    "drifted, the quorvex trays dried first, the brimlet trellis needs splinting. ";
  var vic = await plant({ title: "Greenhouse survey notes", content: relText + relText + relText });
  var relKin = await plant({ kind: "work_log", title: "Greenhouse survey, second pass",
    content: "Back to the quorvex trays and the brimlet trellis: [[Greenhouse Survey]] again, " +
             "the tallow irrigation manifold rerouted." });
  ok(vic.content.length > 600, "an entry long enough to relate");
  var bag = relTake(vic);
  ok(bag.terms.size > 0, "an entry has a vocabulary");
  ok(!bag.terms.has("the") && !bag.terms.has("and"), "stop words are not part of it");
  var tooShort = Array.from(bag.terms).filter(function (t) { return t.length < REL_MIN_LEN; });
  eq(tooShort.length, 0, "nor are words too short to mean anything");
  ok(relTake(vic) === bag, "a second look at an unchanged entry reads the cached bag");
  // a rename leaves the length as it was: the title is part of the key too
  var wasTitle = vic.title;
  vic.title = (wasTitle || "") + " zyxwvut";
  var bagR = relTake(vic);
  ok(bagR !== bag && bagR.terms.has("zyxwvut"), "a renamed entry is read again");
  vic.title = wasTitle;
  bag = relTake(vic);
  ok(!bag.terms.has("zyxwvut") && !relDf.has("zyxwvut"), "and its old title leaves the vocabulary");

  var beforeDocs = relDocs;
  var wasLen = vic.content_length;
  var hadTerm = Array.from(bag.terms)[0];
  vic.content_length = wasLen + 1;             // what an edit looks like from here
  var bag2 = relTake(vic);
  ok(bag2 !== bag, "an edited entry is read again");
  eq(relDocs, beforeDocs, "and is still one document, not two");
  ok(relDf.get(hadTerm) >= 1, "its terms did not get double-counted");
  vic.content_length = wasLen;
  relTake(vic);

  console.log("-- related: what the reader offers --");
  // the reader asks a slice at a time: an over() that is always true makes the
  // job yield at every check it has, and it must still get to the end
  var job = relatedJob(vic, function () { return true; }), yields = 0, step;
  while (!(step = job.next()).done && yields < 100000) yields++;
  ok(yields > 1, "the scan yields when its share of the frame is spent (" + yields + " times)");
  ok(step.done && Array.isArray(step.value.rows), "and still finishes with an answer");
  var R = related(vic);
  eq(JSON.stringify(step.value.rows.map(function (x) { return x.r.id; })),
     JSON.stringify(R.rows.map(function (x) { return x.r.id; })), "the same one related() gives at once");
  ok(Array.isArray(R.rows), "related answers with rows");
  ok(R.rows.length <= REL_MAX, "never more than the cap");
  ok(R.rows.every(function (r) { return r.r.id !== vic.id; }), "and never the entry itself");
  ok(R.rows.some(function (x) { return x.r.id === relKin.id; }), "the entry sharing its words and link is offered");
  if (R.rows.length > 1) {
    ok(R.rows[0].score >= R.rows[1].score, "best guess first");
  }
  ok(R.rows.every(function (r) { return r.shared > 0 || r.viaLink > 0; }),
     "every row has a reason to be there");

  select(vic.id);
  await drainExtras();
  has($("#rd_rel").innerHTML, "Possibly related", "the reader heads the block");
  eq($("#rd_rel").querySelectorAll(".blrow").length, R.rows.length, "one row per guess");
  ok($("#rd_rel").querySelector(".blwhy"), "and each says why it is there");
  // an entry with nothing in common with anything draws nothing at all
  var lonely = { id: 999001, kind: "test", title: "zqxjkv",
                 content: "zqxjkvwp hraxlmn bffgttu", content_length: 24, deleted: 0,
                 value_int: 0, value_float: 0, done_bool: 0,
                 created_at_utc: "2020-01-01 00:00:00", last_modified_at_utc: "" };
  eq(related(lonely).rows.length, 0, "a page nothing echoes gets no guesses");
  paintRelated(related(lonely));
  eq($("#rd_rel").innerHTML, "", "and the block disappears rather than saying 'none'");
  closeEditor();

  /* ---------- topic trends ---------- */
  console.log("\n-- trends: counting a name by month --");
  // the link the two entries above share, written today: the journal's
  // most-linked name may not have been written in the chart's months
  var term = "Greenhouse Survey";
  var s = trendSeries(term);
  ok(s.entries >= 2, "a linked name turns up in the journal");
  ok(s.hits >= s.entries, "mentions are counted, not just entries");
  ok(s.links > 0, "and the ones written as [[links]] are counted apart");
  ok(s.links <= s.hits, "a link is a mention too, never more than all of them");
  ok(s.first <= s.last, "the first mention is not after the last");
  eq(trendSeries("").entries, 0, "nothing asked, nothing counted");

  // a term nobody has written, and one that is nothing but metacharacters
  eq(trendSeries("zqxjkvwp-no-such-term").entries, 0, "a name nobody wrote scores nothing");
  var safe = trendSeries("c++ (a|b) [x]");
  eq(safe.entries, 0, "a term full of metacharacters is escaped, not compiled");
  ok(true, "and searching for it did not throw");

  console.log("-- trends: the months in between --");
  // months back from today, not fixed ones: the chart holds the last
  // TREND_MONTHS, and January 2025 fell out of it in March 2027
  var monthAgo = function (n) { var d = new Date(); d.setDate(1); d.setMonth(d.getMonth() - n);
    return d.getFullYear() + "-" + pad2(d.getMonth() + 1); };
  var gap = { first: monthAgo(6) + "-15", last: monthAgo(1) + "-02", months: new Map() };
  gap.months.set(monthAgo(6), 3);
  gap.months.set(monthAgo(1), 1);
  var ms = trendMonths(gap);
  ok(ms.length >= 6, "every month from the first mention to now is a column");
  ok(ms.indexOf(monthAgo(4)) >= 0, "including the ones nothing was written in");
  ok(ms.length <= TREND_MONTHS, "and never more than the chart can hold");

  console.log("-- trends: the chart --");
  openTrend(term);
  has($("#dlgh").textContent, term.slice(0, 20), "the dialog is headed with the term");
  var bars = $("#trbars").querySelectorAll(".trcol");
  var axis = $("#traxis").querySelectorAll("span");
  ok(bars.length > 0, "it has columns");
  eq(bars.length, axis.length, "and exactly one axis label per column");
  eq(bars.length, trendMonths(s).length, "one column per month in the span");
  has($("#trstats").innerHTML, "as a link", "the cards separate mentions from links");
  has($("#trnote").textContent, "first written", "and the note dates the span");
  var live = null;
  for (var bi = 0; bi < bars.length; bi++) if (!bars[bi].classList.contains("nil")) live = bars[bi];
  ok(!!live, "at least one month has something in it");
  var m0 = live.dataset.m;
  click(live);
  eq($("#q").value, term, "clicking a column searches for the term");
  eq($("#fSince").value, m0 + "-01", "from the first of that month");
  has($("#fUntil").value, m0, "to its last day");
  ok(!$("#ov").classList.contains("on"), "and the chart gets out of the way");
  clearFilters();
  hideToast();

  console.log("-- trends: alt-clicking a [[link]] charts it instead of searching --");
  $("#rd_content").innerHTML = mdRender("- see [[" + term + "]] for the rest");
  var wl = $("#rd_content").querySelector("a.wiki");
  ok(!!wl, "the reader renders the link");
  $("#q").value = "";
  $("#dlg").innerHTML = "";          // so the last dialog's heading cannot answer for this one
  click(wl, { altKey: true });
  await settle(3);
  has($("#dlgh").textContent, "Trend", "alt-click opens the trend");
  eq($("#q").value, "", "and leaves the search box alone");
  closeOv();

  /* ---------- the stack ----------
     Shift is the other half of that gesture: the entry a [[link]] names,
     pinned beside the one it was read from rather than opened in place of it.
     The suite drives it through the same markup a reader clicks. */
  console.log("\n-- stack: shift-clicking a [[link]] pins it --");
  stackClear();
  hideToast();
  // the two planted above: titles nobody else carries (an ambiguous one
  // proves nothing)
  var pinA = vic, pinB = relKin;
  ok(byTitle(pinA.title) === pinA && byTitle(pinB.title) === pinB, "two unambiguously titled entries");
  eq(document.body.dataset.stack, "off", "the column is not there until something is pinned");
  var held = st.sel;
  var linkTo = function (e) {
    $("#rd_content").innerHTML = mdRender("- see [[" + e.title + "]] for the rest");
    return $("#rd_content").querySelector("a.wiki");
  };
  $("#q").value = "";
  click(linkTo(pinA), { shiftKey: true });
  await settle(3);
  eq(document.body.dataset.stack, "on", "the column appears");
  eq(stack.ids.length, 1, "one panel is pinned");
  eq(stack.ids[0], pinA.id, "and it holds the entry the link named");
  ok(st.sel === held, "the entry being read did not move");
  eq($("#q").value, "", "and the search box was left alone");
  var cards = $("#stackwrap").querySelectorAll(".stk");
  eq(cards.length, 1, "one card is drawn");
  has(cards[0].innerHTML, "#" + pinA.id, "its bar says which entry it is holding");
  ok(cards[0].className.indexOf("on") >= 0, "a freshly pinned panel is the open one");
  has(cards[0].innerHTML, "stkbody", "and the open one shows the entry");

  console.log("-- stack: several at once, one of them open --");
  click(linkTo(pinB), { shiftKey: true });
  await settle(3);
  eq(stack.ids.length, 2, "the second link stacks rather than replacing the first");
  eq(stack.on, pinB.id, "the newest pin is the open one");
  eq($("#stackwrap").querySelectorAll(".stk.on").length, 1, "exactly one panel is open");
  click(linkTo(pinB), { shiftKey: true });
  await settle(3);
  eq(stack.ids.length, 2, "pinning the same link twice is one panel, not two");

  console.log("-- stack: flipping through them --");
  var bars = $("#stackwrap").querySelectorAll(".stkpick");
  click(bars[0]);
  eq(stack.on, pinA.id, "clicking a bar opens that panel");
  eq($("#stackwrap").querySelectorAll(".stk.on").length, 1, "and closes the one that was open");
  click($("#stackwrap").querySelectorAll(".stkpick")[0]);
  eq(stack.on, null, "clicking the open bar again closes it — all bars, no body");
  key("3");
  eq(stack.on, stack.ids[0], "3 flips to the next panel");
  key("3");
  eq(stack.on, stack.ids[1], "and on round the stack");

  console.log("-- stack: what is pinned survives the tab --");
  eq(JSON.stringify(lsGet("lcars.stack", {}).ids), JSON.stringify(stack.ids),
     "the pins are written down");

  console.log("-- stack: unpinning, and promoting into the main pane --");
  var drop = $("#stackwrap").querySelectorAll(".stkdrop");
  click(drop[0]);
  eq(stack.ids.length, 1, "the ✕ on a bar unpins that panel");
  var last = stack.ids[0];
  click($("#stackwrap").querySelectorAll(".stkmain")[0]);
  await settle(3);
  eq(st.sel && st.sel.id, last, "the other button opens it in the main pane");
  eq(stack.ids.length, 0, "and it stops being a pin — nothing is on screen twice");
  eq(document.body.dataset.stack, "off", "so the column goes away again");

  console.log("-- stack: a link to a page nobody has written --");
  var rows0 = st.all.length;
  $("#rd_content").innerHTML = mdRender("- see [[no such page 98217]] for the rest");
  click($("#rd_content").querySelector("a.wiki"), { shiftKey: true });
  await settle(3);
  eq(stack.ids.length, 0, "there is nothing to pin");
  eq(st.all.length, rows0, "and Shift does not create the page a plain click would");
  has($("#toast").textContent, "no such page 98217", "the toast says so");
  hideToast();

  console.log("-- stack: Escape takes the layer off before the entry --");
  setRead(true);                       // the ladder reaches the stack past the editor
  stackOpen(pinA.id, true);
  stackOpen(pinB.id, true);
  var keptSel = st.sel;
  key("Escape");
  eq(stack.on, null, "Escape closes the open panel down to its bar");
  key("Escape");
  eq(stack.ids.length, 0, "and again takes the whole shelf away");
  ok(st.sel === keptSel, "without disturbing the entry in the main pane");
  hideToast();
  unplant(vic);
  unplant(relKin);

  /* ---------- column widths ---------- */
  console.log("\n-- columns: the grips drag the filters, entries and stack widths --");
  var rootStyle = document.documentElement.style;
  function drag(grip, x) {
    dispatch(grip, "pointerdown", { button: 0, pointerId: 1, clientX: x });
    dispatch(grip, "pointermove", { pointerId: 1, clientX: x });
    dispatch(grip, "pointerup", { pointerId: 1, clientX: x });
  }
  $("#side")._rect = { left: 0 };
  drag($("#sidegrip"), 300);
  eq(rootStyle.getPropertyValue("--sidew"), "300px", "the filters column follows the pointer");
  eq(lsGetStr("lcars.sidew"), "300", "and the width is remembered");
  drag($("#sidegrip"), 5000);
  eq(rootStyle.getPropertyValue("--sidew"), SIDE_W.max + "px", "it stops at its maximum");
  drag($("#sidegrip"), 10);
  eq(rootStyle.getPropertyValue("--sidew"), SIDE_W.min + "px", "and at its minimum");
  $("#listpane")._rect = { left: 250 };
  drag($("#listgrip"), 750);
  eq(rootStyle.getPropertyValue("--listw"), "500px",
     "the entries column is measured from its own left edge");
  eq(lsGetStr("lcars.listw"), "500", "and remembered too");
  dispatch($("#listgrip"), "pointermove", { pointerId: 1, clientX: 900 });
  eq(rootStyle.getPropertyValue("--listw"), "500px", "a pointer that is not dragging moves nothing");
  dispatch($("#listgrip"), "pointerdown", { button: 2, pointerId: 1, clientX: 700 });
  dispatch($("#listgrip"), "pointermove", { pointerId: 1, clientX: 700 });
  eq(rootStyle.getPropertyValue("--listw"), "500px", "a right-button press is not a drag");
  drag($("#stackgrip"), window.innerWidth - 400);
  eq(rootStyle.getPropertyValue("--stackw"), "400px", "the stack still sizes from the right edge");
  dispatch($("#sidegrip"), "dblclick", {});
  dispatch($("#listgrip"), "dblclick", {});
  dispatch($("#stackgrip"), "dblclick", {});
  eq(rootStyle.getPropertyValue("--sidew") + rootStyle.getPropertyValue("--listw") +
     rootStyle.getPropertyValue("--stackw"), "", "double-click hands each back to the stylesheet");
  eq(lsGetStr("lcars.sidew"), null, "and forgets the preference");

  /* ---------- templates ---------- */
  console.log("\n-- templates: the placeholders --");
  var now = new Date();
  var filled = tplFill("{date}|{time}|{day}|{weekday}|{month}|{year}|{week}|{nope}");
  var bits = filled.split("|");
  eq(bits[0], isoDay(now), "{date} is today, on the local clock");
  ok(/^\d\d:\d\d$/.test(bits[1]), "{time} is the wall clock");
  eq(bits[2], WDFULL[now.getDay()], "{day} is the weekday, spelled out");
  eq(bits[3], WD[now.getDay()], "{weekday} is the short form");
  eq(bits[4], MO[now.getMonth()], "{month} is the month");
  eq(bits[5], String(now.getFullYear()), "{year} is the year");
  eq(bits[6], isoWeek(now), "{week} is the ISO week, as /week writes it");
  eq(bits[7], "{nope}", "a placeholder nobody defined is left exactly as written");
  eq(tplFill("{yesterday}"), isoDay(new Date(Date.now() - 86400000)), "{yesterday} counts back a day");

  console.log("-- templates: starting an entry from one --");
  /* The counts below are absolute — none, then the one this section makes — so
     they only hold while the fixture brings no templates of its own. It used to
     bring none; it does now, the day somebody wrote one. Park whatever it has
     for the length of the section and hand them back at the end. */
  var tplParked = templateRows();
  tplParked.forEach(function (t) { t.deleted = 1; });
  eq(templateRows().length, 0, "the fixture carries no templates");
  openTemplates();
  has($("#toast").textContent, "no templates yet", "so the picker says so rather than opening empty");
  hideToast();

  var tpl = { id: 999002, kind: kindOf("template"), title: "Weekly review {week}",
              content: "kind:: work_log\n\n## Week {week}\n\n- wins\n- " + TPL_CURSOR + "\n",
              content_length: 64, deleted: 0, value_int: 0, value_float: 0, done_bool: 0,
              created_at_utc: "2026-01-01 09:00:00", last_modified_at_utc: "" };
  st.all.unshift(tpl);
  st.byId.set(tpl.id, tpl);
  eq(templateRows().length, 1, "an entry of kind template is one");

  setClean();
  useTemplate(tpl);
  await settle(3);
  ok(st.isNew, "it starts a new entry");
  eq($("#e_kind").value, "work_log", "the kind:: header sets the kind");
  ok($("#content").value.indexOf("kind::") < 0, "and the header itself is not copied");
  ok($("#content").value.indexOf(TPL_CURSOR) < 0, "{cursor} is a marker, never text");
  has($("#content").value, "## Week " + isoWeek(new Date()), "the body's placeholders are substituted");
  eq($("#content").value.slice(0, 2), "##", "the blank line under the header goes with it");
  eq($("#e_head").value, "Weekly review " + isoWeek(new Date()), "so are the title's");
  ok(document.body.classList.contains("dirty"), "it starts dirty: it exists nowhere else");
  ok(!st.read, "and in the form, which is where writing happens");

  setClean();
  closeEditor();
  newTemplate();
  await settle(3);
  eq($("#e_kind").value, kindOf("template"), "the blank template is one");
  has($("#content").value, "kind::", "pre-filled with the syntax");
  has($("#content").value, TPL_CURSOR, "and with the caret marker");
  setClean();
  closeEditor();

  var defaulted = { id: 999003, kind: kindOf("template"), title: "Standup",
                    content: "- yesterday\n- today\n", content_length: 20, deleted: 0,
                    value_int: 0, value_float: 0, done_bool: 0,
                    created_at_utc: "2026-01-01 09:00:00", last_modified_at_utc: "" };
  st.all.unshift(defaulted);
  st.byId.set(defaulted.id, defaulted);
  useTemplate(defaulted);
  await settle(3);
  eq($("#e_kind").value, "personal_log", "a template with no kind:: falls back to the default");
  eq($("#content").value, "- yesterday\n- today\n", "and its body is copied whole");
  setClean();
  closeEditor();

  console.log("-- templates: the picker --");
  openTemplates();
  await settle(3);
  eq($("#dlgh").textContent, "New from a template", "now there are templates to pick from");
  ok(pk && pk.rows.length === 2, "both of them are rows");
  eq(pk.rows[0].v, defaulted.id, "the one used last leads (both used once, it more lately)");
  closeOv();
  localStorage.removeItem(TPL_USE_KEY);
  // a row of its kind written just now: the live fixture has one only if the
  // journal had a work_log in the last TPL_RECENT_DAYS, which it need
  // not (run as of 2026-10-25, it had none, and this failed)
  var tplRecent = { id: 999004, kind: "work_log", title: "lately", content: "", deleted: 0,
                    created_at_utc: new Date().toISOString().slice(0, 19).replace("T", " ") };
  st.all.push(tplRecent);
  eq(templateRowsByUse()[0].t.id, tpl.id,
     "with no uses, the template whose kind was written into lately leads");
  st.all.pop();
  useTemplate(tpl); await settle(3); setClean(); closeEditor();
  useTemplate(defaulted); await settle(3); setClean(); closeEditor();
  useTemplate(defaulted); await settle(3); setClean(); closeEditor();
  eq(templateRowsByUse()[0].t.id, defaulted.id, "the most used comes first");
  fdGo("tpl");
  await settle(3);
  eq($("#dlgh").textContent, "New from a template", "the speed dial's template option opens the picker");
  eq(pk.rows[0].v, defaulted.id, "with the most used on top");
  closeOv();
  localStorage.removeItem(TPL_USE_KEY);
  tplParked.forEach(function (t) { t.deleted = 0; });

  /* ---------- quick capture ---------- */
  console.log("\n-- capture: one line, no editor --");
  localStorage.removeItem("lcars.qckind");
  var wasSel = st.sel;
  var before = st.all.length;
  openCapture();
  eq($("#dlgh").textContent, "Quick capture", "the box opens");
  eq($("#qc_kind").value, "personal_log", "with a default kind");
  eq($("#qc_text").value, "", "and nothing typed yet");
  click($("#qc_ok"));
  await settle(3);
  has($("#toast").textContent, "nothing to capture", "an empty capture is refused");
  ok($("#ov").classList.contains("on"), "and the box stays up with the cursor in it");

  $("#qc_text").value = "  the arena is a megabyte now  ";
  $("#qc_kind").value = "work_log";
  click($("#qc_ok"));
  await settle(6);
  eq(st.all.length, before + 1, "a captured line is a row");
  eq(st.all[0].content, "the arena is a megabyte now", "trimmed, and the text is the content");
  eq(st.all[0].kind, "work_log", "under the kind that was typed");
  // There was nowhere to type a title, so the server's placeholder is what the
  // row comes back with — lcars_http.h fills an empty one in. This asserted ""
  // for a while, which only passed because the fake API skipped that step.
  eq(st.all[0].title, "HTTP Entry", "under the placeholder title the server gives an untitled row");
  eq(st.sel, wasSel, "the editor was never opened");
  ok(!$("#ov").classList.contains("on"), "and the box is gone");
  has($("#toast").textContent, "captured #", "the toast names the row");
  eq(localStorage.getItem("lcars.qckind"), "work_log", "the kind is remembered");
  hideToast();

  openCapture();
  eq($("#qc_kind").value, "work_log", "and comes back next time");
  $("#qc_text").value = "a thought that turned out to be a bigger one";
  click($("#qc_full"));
  await settle(3);
  ok(st.isNew, "Open editor hands it over instead");
  has($("#content").value, "bigger one", "with the text intact");
  ok(document.body.classList.contains("dirty"), "and unsaved");
  setClean();
  closeEditor();

  console.log("-- capture: the share sheet lands in it --");
  var realSearch = location.search;
  location.search = "?title=A%20page&text=worth%20reading&url=https%3A%2F%2Fexample.com";
  ok(shareTarget(), "a share is recognised");
  await settle(3);
  eq($("#dlgh").textContent, "Quick capture", "and opens the capture box");
  has($("#qc_text").value, "A page", "carrying the shared title");
  has($("#qc_text").value, "https://example.com", "and the shared url");
  closeOv();
  location.search = "";
  ok(!shareTarget(), "a plain visit is not a share");
  location.search = realSearch;

  console.log("-- capture: /log writes a reading --");
  eq(parseLog("the arena is a megabyte", "x"), null, "prose is not a /log");
  eq(parseLog("/logbook 3", "x"), null, "nor is a word that only starts with it");
  var lg = parseLog("/log weight 72,4 kg after the run\nfelt heavy", "personal_log");
  eq(lg.kind, "weight", "the first word is the kind");
  eq(lg.value, 72.4, "a decimal comma is a decimal point");
  eq(lg.title, "72.4 kg after the run", "the number heads the title, the rest of the line follows");
  eq(lg.content, "felt heavy", "further lines are the body");
  lg = parseLog("/log 7.5", "sleep_h");
  eq(lg.kind, "sleep_h", "no kind given: the kind field's");
  eq(lg.value, 7.5, "with the number");
  eq(parseLog("/log -3", "t").value, -3, "a negative is a number, not a kind");
  has(parseLog("/log weight", "x").error, "needs a number", "a /log with no number is an error");
  has(parseLog("/log weight heavy", "x").error, "needs a number", "and so is one with a word where it goes");
  has(parseLog("/log 5", "").error, "needs a kind", "a number with nowhere to go is too");

  localStorage.setItem("lcars.qckind", "work_log");
  before = st.all.length;
  openCapture();
  input($("#qc_text"), "/log harness_weight 72.4 kg");
  ok(!$("#qc_log").hidden, "the box says what a /log is about to write");
  has($("#qc_log").textContent, "harness_weight", "naming the kind");
  has($("#qc_log").textContent, "72.4", "and the number");
  click($("#qc_ok"));
  await settle(6);
  eq(st.all.length, before + 1, "a /log is a row");
  eq(st.all[0].kind, "harness_weight", "under the kind it named");
  eq(st.all[0].value_float, 72.4, "with the number in value_float");
  eq(st.all[0].title, "72.4 kg", "and the reading as its title");
  eq(st.all[0].content, "", "and no body");
  has($("#toast").textContent, "logged harness_weight 72.4", "the toast reads it back");
  eq(localStorage.getItem("lcars.qckind"), "work_log",
     "a log's kind is not remembered as the capture kind");
  hideToast();
  ok(!measureSeries().has("harness_weight"), "one reading is not a series yet");

  openCapture();
  input($("#qc_text"), "/log harness_weight heavy");
  has($("#qc_log").textContent, "needs a number", "a /log that will not parse is flagged while typing");
  ok($("#qc_log").classList.contains("bad"), "in red");
  before = st.all.length;
  click($("#qc_ok"));
  await settle(3);
  eq(st.all.length, before, "and refused on Enter rather than kept as prose");
  ok($("#ov").classList.contains("on"), "with the box still up to fix it");
  input($("#qc_text"), "/log harness_weight 71.9");
  click($("#qc_ok"));
  await settle(6);
  hideToast();
  var zero = parseLog("/log harness_weight 0", "x");
  await captureSave("x", "/log harness_weight 0", zero);
  await settle(3);
  hideToast();
  eq(st.all[0].value_float, 0, "a reading of zero is stored as 0");
  var ser = measureSeries().get("harness_weight");
  ok(ser && ser.length === 3, "three readings are a series");
  eq(ser.map(function (p) { return p.v; }).join(","), "72.4,71.9,0",
     "oldest first, and the zero counts: its title says it was a reading");
  eq(reading({ value_float: 0, value_int: 0, title: "HTTP Entry" }), null,
     "an ordinary row with zero columns is no reading");
  eq(reading({ value_float: 0, value_int: 12, title: "" }), 12, "value_int stands in when value_float is 0");
  eq(reading({ value_float: 0, value_int: 0, title: "01 - Intro" }), null,
     "a title that merely starts with a 0 digit is not a zero");

  fillKinds();
  ok(!$("#series").hidden, "the readings strip appears under the kind filter");
  var srow = $("#series").querySelector('.srow[data-k="harness_weight"]');
  ok(srow && srow.querySelector("svg.kcs"), "with the series drawn as a sparkline");
  eq(srow.querySelector(".srv").textContent, "0", "beside its latest reading");
  has(srow.getAttribute("title"), "3 readings", "and the tooltip counts them");
  ok(!$("#series").querySelector('.srow[data-k="work_log"]'), "a kind without numbers has no row");
  click(srow);
  eq(st.kinds.join(","), "harness_weight", "a row is a kind filter");
  ok(srow.classList.contains("on"), "and lights up while it stands");
  click(srow);
  eq(st.kinds.length, 0, "a second click lets it go");

  openStats();
  has($("#dlg").textContent, "Measurements", "the statistics grow a measurements section");
  var mc = $("#dlg").querySelector(".mcard");
  ok(mc, "one card per series");
  has(mc.textContent, "3 readings", "counting them");
  has(mc.textContent, "max 72.4", "with the range");
  has(mc.querySelector(".mdl").innerHTML, "71.9", "and the change since the reading before");
  var dot = mc.querySelector("circle[data-id]");
  ok(dot, "each reading is a dot");
  var dotId = Number(dot.getAttribute("data-id"));
  click(dot);
  await settle(3);
  ok(!$("#ov").classList.contains("on"), "a dot closes the statistics");
  eq(st.sel && st.sel.id, dotId, "and opens the entry holding that reading");
  closeEditor();
  openStats();
  click($("#dlg").querySelector(".mk[data-k]"));
  eq(st.kinds.join(","), "harness_weight", "the card's name filters to that kind");
  clearFilters();

  console.log("-- the series explorer: PromQL-lite over the readings --");
  var q1 = xpParse("avg_over_time(harness_weight[1w]); diff(\"my kind\")");
  eq(q1.length, 2, "a ; separates two series");
  eq(q1[0].node.fn, "avg_over_time", "a function call parses");
  eq(q1[0].node.args[0].kind, "harness_weight", "around a kind");
  eq(q1[0].node.args[0].range.src, "1w", "with its range");
  eq(q1[1].node.args[0].kind, "my kind", "a quoted kind may hold a space");
  eq(xpParse("quantile_over_time(0.9, w[1mo])")[0].node.args[0], 0.9, "a number argument comes first");
  eq(xpParse("count_over_time(w[auto])")[0].node.args[0].range.auto, true, "[auto] follows the zoom");
  var perr = function (q) { try { xpParse(q); return ""; } catch (e) { return e.message; } };
  has(perr("avg_over_time(w[1w]"), "expected , or )", "an unclosed call says what it wanted");
  has(perr("nope(w[1d])"), "no function called nope", "an unknown function is named");
  has(perr("w[3q]"), "not a range", "a bad range is refused");
  // a hand-made series: three readings on one day, one the next, one a week on
  var d0 = new Date(2026, 0, 5, 8).getTime();   // a Monday, local
  var fake = new Map([["w", [
    { t: d0, v: 10, id: 1 }, { t: d0 + 3600e3, v: 20, id: 2 }, { t: d0 + 7200e3, v: 30, id: 3 },
    { t: d0 + 864e5, v: 40, id: 4 }, { t: d0 + 7 * 864e5, v: 50, id: 5 }]]]);
  var ctx = function () { return { series: fake, from: new Date(2026, 0, 1).getTime(),
    to: new Date(2026, 0, 31).getTime(), step: null, auto: xpDur("1d"), note: new Set() }; };
  var byDay = xpEval(xpParse("avg_over_time(w[1d])")[0].node, ctx());
  eq(byDay.pts.map(function (p) { return p.v; }).join(","), "20,40,50", "a daily mean is a bucket per day that has readings");
  eq(byDay.pts[0].n, 3, "each bucket knows how many readings it holds");
  eq(byDay.pts[0].t, new Date(2026, 0, 5).getTime(), "and starts at local midnight");
  var byWeek = xpEval(xpParse("sum_over_time(w[1w])")[0].node, ctx());
  eq(byWeek.pts.map(function (p) { return p.v; }).join(","), "100,50", "weeks start on Monday");
  var cnt = xpEval(xpParse("count_over_time(w[1w])")[0].node, ctx());
  ok(cnt.pts.some(function (p) { return p.v === 0; }), "a count says zero for an empty week rather than leaving a gap");
  eq(xpEval(xpParse("diff(w)")[0].node, ctx()).pts.map(function (p) { return p.v; }).join(","),
     "10,10,10,10", "diff is reading-by-reading");
  eq(xpEval(xpParse("cumsum(w)")[0].node, ctx()).pts.pop().v, 150, "cumsum is the running total");
  eq(xpEval(xpParse("delta(w[1w])")[0].node, ctx()).pts[0].v, 30, "delta is last minus first in the window");
  var c7 = ctx(); c7.step = xpDur("1d");
  var roll = xpEval(xpParse("avg_over_time(w[7d])")[0].node, c7);
  eq(roll.pts.filter(function (p) { return p.t === new Date(2026, 0, 7).getTime(); })[0].v, 25,
     "a 7d window at a 1d step is a rolling mean");
  var ev0 = function (q) { try { xpEval(xpParse(q)[0].node, ctx()); return ""; } catch (e) { return e.message; } };
  has(ev0("w[1w]"), "put a function round it", "a bare range asks for a function");
  has(ev0("avg_over_time(w)"), "takes a range", "a range function without a range says so");
  has(ev0("nothing_here"), "no readings", "an unknown kind says so");
  // the title is a reading's one label: one kind, several metrics
  var lr = new Map([["lift", [
    { t: d0, v: 60, id: 11, ti: "60 bench press" }, { t: d0 + 36e5, v: 100, id: 12, ti: "100 Squat" },
    { t: d0 + 864e5, v: 65, id: 13, ti: "65 bench press" }, { t: d0 + 2 * 864e5, v: 110, id: 14, ti: "110 squat deep" }]]]);
  var lctx = function () { var c = ctx(); c.series = lr; return c; };
  var lv = function (q) { return xpEval(xpParse(q)[0].node, lctx()).pts.map(function (p) { return p.v; }).join(","); };
  eq(lv('lift{"bench"}'), "60,65", "{\"words\"} keeps the readings whose title holds them");
  eq(lv('lift{"press bench"}'), "60,65", "every word, in any order");
  eq(lv("lift{/squat$/}"), "100", "{/regex/} is a regex, ignoring case");
  eq(lv('lift{title=~"sq"}'), "100,110", "title=~ is the PromQL spelling");
  eq(lv('lift{title!~"sq"}'), "60,65", "and !~ its negation");
  eq(lv('lift{title="110 squat deep"}'), "110", "title= is the whole title");
  eq(lv('lift{title!="110 squat deep", "squat"}'), "100", "matchers separated by commas must all hold");
  eq(lv('sum_over_time(lift{"squat"}[1w])'), "210", "a matched selector takes a range like any other");
  eq(xpSelSrc(xpSelOf(xpParse('avg_over_time(lift{"bench"}[1w])')[0].node)), 'lift{"bench"}',
     "the selector keeps its matcher, which the quick chips rewrite around");
  ok(xpSelColor(xpParse('lift{"bench"}')[0].node) !== undefined, "a matched series has a colour of its own");
  has(perr('lift{kind="x"}'), "its title", "title is the only label");
  has(perr("lift{/(/}"), "not a regex", "a regex that will not compile is refused");
  has(perr('lift{"a"'), "expected , or }", "an unclosed matcher says so");
  var lev = function (q) { try { xpEval(xpParse(q)[0].node, lctx()); return ""; } catch (e) { return e.message; } };
  has(lev('lift{"deadlift"}'), "no lift reading has a title matching", "a matcher nothing passes says so");

  fillKinds();
  click($("#series").querySelector('.sx[data-x="harness_weight"]'));
  ok($("#ov").classList.contains("on"), "the strip's arrow opens the explorer");
  has($("#dlgh").textContent, "explore", "under its own heading");
  var xpan = $("#xpanels").querySelector(".xpanel");
  eq(xpan.querySelector(".xq").value, "harness_weight", "one panel, querying that kind");
  ok(xpan.querySelector("svg.xsvg path.xline"), "drawn as a line");
  eq(xpan.querySelectorAll("circle.xdot").length, 3, "with a dot per reading");
  has(xpan.querySelector(".xstats").textContent, "max 72.4", "and the range's numbers under it");
  click(xpan.querySelectorAll(".xchips [data-q]").filter(function (c) {
    return c.getAttribute("data-q").indexOf("count_over_time") === 0; })[0]);
  ok(xpan.querySelector("rect.xbarr"), "a chip rewrites the query, and a count is bars");
  has(xpan.querySelector(".xq").value, "harness_weight", "about the same kind");
  input(xpan.querySelector(".xq"), "avg_over_time(harness_weight[1d]");
  await settle(2);
  xpDrawAll();
  ok(!xpan.querySelector(".xerr").hidden, "a query that will not parse says so");
  has(xpan.querySelector(".xerr").textContent, "expected", "saying what it expected");
  input(xpan.querySelector(".xq"), "harness_weight");
  xp.panels[0].q = "harness_weight";
  click(xpan.querySelector('[data-view="table"]'));
  var trs = xpan.querySelectorAll("tr[data-open]");
  eq(trs.length, 3, "the table lists every reading in range");
  click($("#x_add"));
  eq($("#xpanels").querySelectorAll(".xpanel").length, 2, "a panel is added");
  click($("#xpanels").querySelectorAll(".xpanel")[1].querySelector("[data-rm]"));
  eq($("#xpanels").querySelectorAll(".xpanel").length, 1, "and removed");
  xpSetRange(xp.from, xp.from + 1);
  eq(xp.preset, null, "a zoom leaves the presets");
  click($("#x_pre").querySelector('[data-pre="all"]'));
  eq(xp.preset, "all", "and a preset takes it back");
  ok(lsGet(XP_KEY, null).panels.length === 1, "the panels are remembered for next time");
  var openId = Number($("#xpanels").querySelector("tr[data-open]").getAttribute("data-open"));
  click($("#xpanels").querySelector("tr[data-open] td"));
  await settle(3);
  ok(!$("#ov").classList.contains("on"), "a table row closes the explorer");
  eq(st.sel && st.sel.id, openId, "and opens the entry holding that reading");
  closeEditor();
  openStats();
  click($("#dlg").querySelector('.mcard [data-xk="harness_weight"]'));
  ok($("#xpanels"), "the statistics card's explore button opens the explorer too");
  closeOv();
  openExplore();
  ok($("#x_cat").hasAttribute("open"), "opened from nowhere in particular, the explorer lists the metrics there are");
  var crow = $("#x_cats").querySelectorAll(".xcrow").filter(function (r) { return r.textContent.indexOf("harness_weight") >= 0; })[0];
  ok(crow, "one row per series");
  has(crow.textContent, "3 readings", "saying how many readings it has");
  ok(crow.querySelector("svg.kcs"), "with its line");
  var catq = $("#x_catq");
  ok(catq, "the metrics can be filtered");
  input(catq, "kg");
  var kgrow = $("#x_cats").querySelectorAll(".xcrow").filter(function (r) { return r.textContent.indexOf("harness_weight") >= 0; })[0];
  ok(kgrow, "by a word in a reading's title");
  has(kgrow.textContent, "1 reading ", "cut down to the readings that match");
  eq(kgrow.querySelector("[data-cshow]").getAttribute("data-cshow"), 'harness_weight{"kg"}',
     "charting the kind with a title matcher");
  click(kgrow.querySelector("[data-cadd]"));
  eq(xp.panels[xp.panels.length - 1].q, 'harness_weight{"kg"}', "which + panel adds as its own panel");
  eq($("#xpanels").querySelectorAll(".xpanel")[xp.panels.length - 1].querySelectorAll("circle.xdot").length, 1,
     "drawing only that reading");
  $("#x_cat").open = true;
  input(catq, "/^7/");
  has($("#x_cats").textContent, "2 readings", "a /regex/ filters titles too");
  input(catq, "harness");
  has($("#x_cats").textContent, "3 readings", "a kind whose name matches is kept whole");
  input(catq, "zzqx");
  has($("#x_cats").textContent, "no kind is called that", "and nothing matching says so");
  input(catq, "");
  click($("#x_cat").querySelector('[data-cadd="harness_weight"]'));
  eq(xp.panels[xp.panels.length - 1].q, "harness_weight", "+ panel adds it");
  click($("#x_cat").querySelector('[data-cshow="harness_weight"]'));
  eq(xp.panels.length, 1, "show makes it the only panel");
  eq($("#xpanels").querySelector(".xq").value, "harness_weight", "and charts it");
  closeOv();
  openExplore("harness_weight");
  ok(!$("#x_cat").hasAttribute("open"), "opened on one kind, the list stays folded");
  closeOv();
  // a search in the entry list carries into the explorer as a title matcher
  $("#q").value = "kg";
  openExplore("harness_weight");
  eq(xp.panels[0].q, 'harness_weight{"kg"}', "a kind opened while searching is charted through the search");
  eq($("#x_catq").value, "kg", "and the metrics filter starts from it");
  closeOv();
  $("#q").value = "/^7/";
  openExplore("harness_weight");
  eq(xp.panels[0].q, "harness_weight{/^7/}", "a /regex/ search stays a regex");
  closeOv();
  $("#q").value = '"72.4 kg"';
  openExplore("harness_weight");
  eq(xp.panels[0].q, "harness_weight{/72\\.4 kg/}", "a quoted phrase becomes an escaped regex");
  closeOv();
  $("#q").value = "harness";
  openExplore("harness_weight");
  eq(xp.panels[0].q, "harness_weight", "a search naming the kind keeps it whole");
  closeOv();
  $("#q").value = "zzqx";
  openExplore("harness_weight");
  eq(xp.panels[0].q, "harness_weight", "and so does one no title matches");
  closeOv();
  $("#fInv").checked = true;
  $("#q").value = "kg";
  openExplore("harness_weight");
  eq(xp.panels[0].q, "harness_weight", "an inverted search is not carried over");
  closeOv();
  $("#fInv").checked = false;
  $("#q").value = "";
  openMore();
  var rtile = $("#dlg").querySelectorAll(".shtile").filter(function (b) { return b.textContent.indexOf("Readings") >= 0; })[0];
  ok(rtile, "the phone's ⋯ sheet has a Readings tile");
  eq(MORE_TILES[Number(rtile.getAttribute("data-i"))][0], "#bExplore", "pressing the Readings button");
  closeOv();
  // the header's buttons are the reader's choice; the sheet keeps the rest
  var qx = $("header").querySelectorAll(".qx").filter(function (b) { return b.dataset.q === "#bExplore"; })[0];
  ok(qx && qx.classList.contains("qoff"), "Readings is not a header button by default");
  ok($("#bChat") && !$("#bChat").classList.contains("qoff"), "Ask is");
  openQuick();
  click($("#quickgrid").querySelectorAll(".shtile").filter(function (b) { return b.textContent.indexOf("Readings") >= 0; })[0]);
  ok(!qx.classList.contains("qoff"), "chosen, its stand-in shows in the header");
  ok(quick.indexOf("#bExplore") >= 0 && JSON.parse(localStorage.getItem("lcars.quick")).indexOf("#bExplore") >= 0,
     "and the choice is kept");
  click($("#quickgrid").querySelectorAll(".shtile").filter(function (b) { return b.textContent.indexOf("Chats") >= 0; })[0]);
  ok($("#bChat").classList.contains("qoff"), "a header button taken off is hidden in place");
  closeOv();
  openMore();
  var mt = $("#dlg").querySelectorAll(".shtile").map(function (b) { return b.textContent; }).join("|");
  ok(mt.indexOf("Readings") < 0 && mt.indexOf("Chats") >= 0, "the sheet holds what the header does not");
  closeOv();
  openQuick();
  click($("#quickDef"));
  closeOv();
  ok(qx.classList.contains("qoff") && !$("#bChat").classList.contains("qoff"), "Defaults puts it back");
  click($("#bExplore"));
  ok($("#xpanels"), "which opens the explorer");
  closeOv();
  // out of every later count: the rows go, and with them the series
  st.all.forEach(function (e) { if (e.kind === "harness_weight") e.deleted = 1; });
  fillKinds();
  refresh();
  ok(!measureSeries().has("harness_weight"), "deleted readings leave the series");
  // the fixture is the live journal's newest rows, which may carry real series
  ok(!$("#series").innerHTML.includes("harness_weight"), "and the strip lets go of it");
  eq($("#series").hidden, measureSeries().size === 0, "a journal with no series has no strip");

  console.log("-- date scrubber: a rail of months beside the list --");
  clearFilters();
  $("#fSort").value = "created:desc";
  refresh();
  var months = [];
  st.view.forEach(function (e) {
    var m = st.dayOf(e).slice(0, 7);
    if (months[months.length - 1] !== m) months.push(m);
  });
  ok(months.length >= 3, "the fixture spans several months (" + months.length + ")");
  ok(!$("#rail").hidden, "a date-sorted list gets a rail");
  ok($("#listwrap").classList.contains("railed"), "and gives up a gutter for it");
  eq(rail.groups.map(function (g) { return g.key; }).join(","), months.join(","),
     "one slot per month present, in list order");
  eq(rail.groups.reduce(function (a, g) { return a + g.n; }, 0), st.view.length,
     "and together they hold every row");
  eq($("#rail").getAttribute("aria-valuemax"), String(months.length - 1), "a slider over them");
  has($("#rail").innerHTML, months[0].slice(0, 4), "the newest year is labelled");
  // Laid out, a year whose label would print on its neighbour's is left
  // unlabelled (RAIL_LABEL_GAP) — so how many show depends on how many months
  // the live fixture spans. Unlaid out (h 0), every year is labelled.
  var yearsN = new Set(months.map(function (m) { return m.slice(0, 4); })).size;
  ok($("#rail").querySelectorAll(".ry").length <= yearsN, "never more than one label per year");
  var keepRailH = rail.h;
  rail.h = 0;
  paintRail();
  has($("#rail").innerHTML, months[months.length - 1].slice(0, 4), "unlaid out, the oldest year is labelled too");
  eq($("#rail").querySelectorAll(".ry").length, yearsN, "and every year has its label");
  rail.h = keepRailH;
  paintRail();

  // No layout in the shim: give every child of a box a 30px row, in order.
  // (The day bars used to be sticky, and a stuck bar reports the scroll
  // position as its offsetTop; they are not any more — #daystick pins a copy —
  // and nothing here may depend on it, so the fake no longer pretends.)
  // The list's spacer (#lpad) is as tall as its style says, standing in for the
  // rows above the rendered window.
  function fakeH(el) { return el.id === "lpad" ? (parseFloat(el.style.height) || 0) : 30; }
  function fakeTop(el) {
    var k = el.parentNode.children, y = 0;
    for (var i = 0; k[i] !== el; i++) y += fakeH(k[i]);
    return y;
  }
  Object.defineProperty(El.prototype, "offsetTop", { configurable: true, get: function () {
    // #list is the origin its rows are measured from
    if (!this.parentNode || this.id === "list") return 0;
    return fakeTop(this);
  } });
  Object.defineProperty(El.prototype, "offsetHeight", { configurable: true, get: function () { return fakeH(this); } });
  // Read once rows have places: with none, every row was at the top, the
  // thumb took the last month drawn for the top one, and on the 1st of a
  // month, a newest month of a row or two, this failed (TODO.md, 2026-10-01).
  $("#list").scrollTop = 0;
  markRail();
  eq(rail.at, 0, "the thumb starts on the newest month");
  has($("#rail").getAttribute("aria-valuetext"), railName(months[0]), "and says which");
  var last = rail.groups.length - 1, lastG = rail.groups[last];
  ok(st.shown <= lastG.start, "the oldest month is not rendered yet (" + st.shown + " rows are)");
  var kev = dispatch($("#rail"), "keydown", { key: "End" });
  ok(kev.defaultPrevented && kev._stop, "End is the rail's, not the list's");
  ok(st.shown > lastG.start, "End renders down to the oldest month");
  var bar = $("#list").querySelector('.day[data-day="' + st.dayOf(st.view[lastG.start]) + '"]');
  ok(bar, "whose first day bar is drawn");
  eq($("#list").scrollTop, fakeTop(bar), "and lifted to the top edge");
  // ...without drawing every row on the way: that was ~80,000 nodes and a
  // phone tab killed for its memory
  ok(st.from > 0, "the window starts past the top (row " + st.from + ")");
  ok($("#list").querySelectorAll(".item").length <= listWindow(),
     "and holds at most listWindow() rows (" + $("#list").querySelectorAll(".item").length + ")");
  ok(padH() > 0, "a spacer stands in for the rows above it");
  eq(st.dayOf(st.view[st.from - 1]) !== st.dayOf(st.view[st.from]), true, "the window opens on a day");
  eq(rail.at, last, "the thumb is on it");
  dispatch($("#rail"), "keydown", { key: "ArrowUp" });
  eq(rail.at, last - 1, "↑ steps a month back toward now");
  dispatch($("#rail"), "keydown", { key: "Home" });
  eq(rail.at, 0, "Home is the newest month");
  eq($("#list").scrollTop, 0, "at the top of the list");
  eq(st.from, 0, "drawn from the first row again");
  eq(padH(), 0, "with no spacer above it");
  dispatch($("#rail"), "keydown", { key: "PageDown" });
  var y0 = months[0].slice(0, 4), pd = rail.groups[rail.at].key.slice(0, 4);
  ok(pd !== y0 || rail.at === last, "PageDown leaves the year (" + y0 + " → " + pd + ")");
  eq(rail.groups[rail.at - 1].key.slice(0, 4), y0, "landing on the next one's first month");
  dispatch($("#rail"), "keydown", { key: "PageUp" });
  eq(rail.at, 0, "PageUp goes back to the top of the year above");
  var kx = dispatch($("#rail"), "keydown", { key: "F7" });
  ok(!kx._stop, "a key the rail has no use for passes through");

  // a drag: the slot under the finger, a frame later
  $("#rail")._rect = { top: 100, height: 400 };
  var slot = 400 / rail.groups.length, mid = Math.floor(rail.groups.length / 2);
  dispatch($("#rail"), "pointerdown", { pointerId: 1, clientY: 100 + slot * (mid + 0.5) });
  ok($("#rail").classList.contains("drag"), "pressing the rail starts a drag");
  has($("#rail .rbub").textContent, railName(rail.groups[mid].key), "the bubble names the month under it");
  has($("#rail .rbub").textContent, String(rail.groups[mid].n), "and how many rows it holds");
  await settle(3);
  eq(rail.at, mid, "and the list follows");
  dispatch($("#rail"), "pointermove", { pointerId: 1, clientY: 100 + slot * (last + 0.9) });
  dispatch($("#rail"), "pointermove", { pointerId: 1, clientY: 99999 });
  await settle(3);
  eq(rail.at, last, "past the end is the last month, and a frame only moves the list once");
  dispatch($("#rail"), "pointermove", { pointerId: 1, clientY: 100 + slot * 1.5 });
  await settle(3);
  eq(rail.at, 1, "and a drag back up goes back up");
  var bar1 = $("#list").querySelector('.day[data-day="' + st.dayOf(st.view[rail.groups[1].start]) + '"]');
  eq($("#list").scrollTop, fakeTop(bar1), "to where that month's bar sits");
  dispatch($("#rail"), "pointermove", { pointerId: 1, clientY: 100 + slot * (last + 0.5) });
  await settle(3);
  dispatch($("#rail"), "pointerup", { pointerId: 1 });
  ok(!$("#rail").classList.contains("drag"), "letting go ends it");
  dispatch($("#rail"), "pointermove", { pointerId: 1, clientY: 101 });
  eq(rail.at, last, "a hover afterwards reads a month out without going there");
  has($("#rail .rbub").textContent, railName(rail.groups[0].key), "(the bubble says it)");
  dispatch($("#rail"), "pointerleave", {});
  has($("#rail .rbub").textContent, railName(rail.groups[last].key), "and leaving puts it back on the thumb");

  // the list's own scrolling moves the thumb
  function listH() { var k = $("#list").children, y = 0; for (var i = 0; i < k.length; i++) y += fakeH(k[i]); return y; }
  $("#list").scrollHeight = listH();
  $("#list").scrollTop = 0;
  dispatch($("#list"), "scroll", {});
  await settle(3);
  // (the jump to the last month left rows above unrendered; scrolling up
  // draws them back a page at a time)
  for (var up = 0; up < 200 && st.from; up++) {
    $("#list").scrollTop = 0;
    dispatch($("#list"), "scroll", {}); runTimers(20);   // the window follows a frame later
  }
  // The last fill moved scrollTop itself, which in a browser fires a scroll
  // event of its own (and the rail follows it); the shim fires none, so one
  // is sent here. Without it the thumb kept the month read before that fill:
  // the same month on most days, the one below on the 1st of a month.
  dispatch($("#list"), "scroll", {});
  await settle(3);
  eq(st.from, 0, "scrolled back up, the window reaches the first row");
  eq(rail.at, 0, "scrolled back to the top, the thumb follows");

  // The pinned day: a copy of the bar scrolled past, pushed up by the next.
  // (Desktop always; a phone only when Config asks — the shim is a phone.)
  // Rendered until there are two: the fixture is the live journal's newest
  // rows, and a busy day can hold more than a page of them (127 rows on
  // 2026-10-10 left the first 200 rows with one bar past the top, and this
  // failed on unchanged code).
  refresh();
  while (st.shown < Math.min(200, st.view.length)) renderMore();
  var kidsL = $("#list").children, b1 = -1, b2 = -1, q = 4;
  for (;;) {
    for (; q < kidsL.length && b2 < 0; q++) if (kidsL[q].classList.contains("day")) {
      if (b1 < 0) b1 = q; else if (q > b1 + 2) b2 = q;
    }
    if (b2 >= 0 || st.shown >= st.view.length) break;
    renderMore();
    kidsL = $("#list").children;
  }
  ok(b1 > 0 && b2 > 0, "two day bars a few rows apart to scroll between");
  $("#list").scrollTop = fakeTop(kidsL[b1]) + 5;
  paintStick();
  ok($("#daystick").hidden, "a phone pins nothing unless asked");
  document.body.dataset.sticky = "on";
  $("#list").scrollTop = 0;
  paintStick();
  ok($("#daystick").hidden, "at the top there is nothing to pin");
  $("#list").scrollTop = fakeTop(kidsL[b1]);
  paintStick();
  ok($("#daystick").hidden, "nor while the day's own bar is still in view");
  $("#list").scrollTop = fakeTop(kidsL[b1]) + 5;
  paintStick();
  ok(!$("#daystick").hidden, "once it scrolls away, it is pinned");
  eq($("#daystick .day").dataset.day, kidsL[b1].dataset.day, "that day's bar");
  has($("#daystick").innerHTML, "Read day", "with its button");
  eq($("#daystick").style.transform, "", "sitting at the top");
  $("#list").scrollTop = fakeTop(kidsL[b2]) - 10;
  paintStick();
  eq($("#daystick .day").dataset.day, kidsL[b2 - 1].classList.contains("day") ? kidsL[b2 - 1].dataset.day
     : (function () { for (var z = b2 - 1; z >= 0; z--) if (kidsL[z].classList.contains("day")) return kidsL[z].dataset.day; })(),
     "still the day above until the next bar arrives");
  eq($("#daystick").style.transform, "translateY(-20px)", "which pushes it up as it comes");
  var opened = null, wasOpen = openDay;
  openDay = function (d) { opened = d; };
  dispatch($("#daystick"), "click", {});
  openDay = wasOpen;
  eq(opened, $("#daystick .day").dataset.day, "and a click on it opens that day");
  document.body.dataset.sticky = "off";
  paintStick();
  ok($("#daystick").hidden, "switching it off unpins it");

  // Scrolling down a long way keeps the window to listWindow() rows, and the
  // rows dropped off the top leave exactly their height behind in the spacer:
  // what is on screen does not move, so the scroll position is never touched.
  refresh();
  var guard = 0;
  while (st.shown < st.view.length && guard++ < 100) {
    $("#list").scrollHeight = listH();
    $("#list").scrollTop = listH() - $("#list").clientHeight;
    var onScreen = $("#list").querySelector('.item[data-id="' + st.view[st.shown - 1].id + '"]');
    var wrap = onScreen.parentNode.id === "list" ? onScreen : onScreen.parentNode;
    var before = fakeTop(wrap), top0 = $("#list").scrollTop;
    dispatch($("#list"), "scroll", {}); runTimers(20);
    if (fakeTop(wrap) !== before || $("#list").scrollTop !== top0) break;
  }
  // a day longer than the window is held whole (trimTop, renderUp): it can add
  // itself to the window once, so the bound grows by that day and no more
  var longDay = 0;
  for (var ld = 0, run = 0; ld < st.view.length; ld++) {
    run = ld && st.dayOf(st.view[ld - 1]) === st.dayOf(st.view[ld]) ? run + 1 : 1;
    longDay = Math.max(longDay, run);
  }
  var bound = listWindow() + (longDay > listWindow() ? longDay : 0);
  eq(st.shown, st.view.length, "scrolling down reaches the last row");
  ok(guard < 100 && st.shown === st.view.length, "with the rows under the finger never moving");
  ok(st.shown - st.from <= bound, "the window stays bounded (" + (st.shown - st.from) + " rows)");
  var drawn = $("#list").children.length - 1;   // everything but the spacer
  var rowsAbove = 0;
  for (var ra = 0; ra < st.from; ra++) rowsAbove += (ra === 0 || st.dayOf(st.view[ra - 1]) !== st.dayOf(st.view[ra])) ? 2 : 1;
  eq(padH(), rowsAbove * 30, "the spacer is exactly the height of the rows and bars dropped");
  ok(drawn < 2 * listWindow(), "and the DOM holds only the window (" + drawn + " nodes)");
  // a refresh (more data landing, a save) keeps the window where it is
  var from0 = st.from, top1 = $("#list").scrollTop;
  refresh();
  eq(st.from, from0, "a refresh keeps the window's first row");
  eq($("#list").scrollTop, top1, "and the scroll position");
  ok(st.shown - st.from <= bound + FILL_ROWS, "without redrawing everything above it");
  // and back up to the top: the spacer gives its height back row for row
  guard = 0;
  while (st.from && guard++ < 100) {
    $("#list").scrollTop = padH();
    var first = $("#lpad").nextElementSibling, ft = fakeTop(first), t0 = $("#list").scrollTop;
    dispatch($("#list"), "scroll", {}); runTimers(20);
    if (fakeTop(first) - $("#list").scrollTop !== ft - t0) break;
  }
  eq(st.from, 0, "scrolling up redraws the rows above");
  ok(guard < 100 && !st.from, "without shifting what is on screen");
  eq(padH(), 0, "and the spacer is gone");
  // on the way up renderUp() draws the day above whole, and trimBottom()
  // keeps three screens under what was the top, out to the end of their day:
  // two long days in a row are both held until the scroll is past (121 and
  // 129 rows on 2026-10-11; 108 and 93 on 2026-10-13, under the window each,
  // 201 together). So the bound is read off today's days, at every boundary:
  // the day above (six rows at least) plus three screens rounded out to a day
  var upBound = listWindow();
  var dayOfRow = function (i) { return st.dayOf(st.view[i]); };
  var dayFrom = function (i) { while (i > 0 && dayOfRow(i - 1) === dayOfRow(i)) i--; return i; };
  var dayEnd = function (i) { while (i < st.view.length && dayOfRow(i) === dayOfRow(i - 1)) i++; return i; };
  for (var ub = 1; ub < st.view.length; ub++) {
    if (dayOfRow(ub) === dayOfRow(ub - 1)) continue;
    var upKeep = ub + 3 * screenRows();
    var upEnd = upKeep >= st.view.length ? st.view.length : dayEnd(upKeep + 1);
    upBound = Math.max(upBound, upEnd - dayFrom(Math.max(0, ub - FILL_ROWS)));
  }
  ok(st.shown - st.from <= Math.max(upBound, bound),
     "the bottom was let go on the way up (" + (st.shown - st.from) + " rows, bound " + Math.max(upBound, bound) + ")");
  refresh();

  // The same walk over made-up days, so the checks above do not depend on
  // whether today's journal happens to hold a day longer than the window:
  // one at the very top (0.146.3), and a short day above one (0.147.1).
  // Each is its own kind, picked, and taken out again at the end.
  var lwTop = st.all.reduce(function (m, e) { return Math.max(m, e.id); }, 0), lwN = 0;
  var lwMade = [];
  var lwDay = function (day, n, kind) {          // day: "2001-03-31"; n rows, newest first
    for (var i = 0; i < n; i++) {
      var at = day + " 12:" + pad2(Math.floor((59 - i % 60))) + ":" + pad2(59 - Math.floor(i / 60));
      var r = { id: lwTop + (++lwN), kind: kind, title: "long day " + day + " #" + i, content: "x",
                created_at_utc: at, last_modified_at_utc: at, deleted: 0, done_bool: 0, content_length: 1 };
      st.all.push(r); st.byId.set(r.id, r); lwMade.push(r);
    }
  };
  var lwOlder = function (kind) {                // two months of four-row days below
    for (var d = 0; d < 60; d++) lwDay(isoDay(new Date(Date.UTC(2001, 2, 29 - d))), 4, kind);
  };
  var lwLong = listWindow() + 10;
  lwDay("2001-03-31", lwLong, "zz_longtop"); lwOlder("zz_longtop");
  lwDay("2001-03-31", 15, "zz_longunder"); lwDay("2001-03-30", lwLong, "zz_longunder"); lwOlder("zz_longunder");
  // a row taken out of the list has moved as far as the finger is concerned
  var lwAt = function (el) { return el && el.parentNode ? fakeTop(el) : NaN; };
  var lwWalk = async function (kind, what) {
    setKinds([kind]); refresh();
    $("#list").scrollTop = 0;
    eq(st.view.length, lwLong + 240 + (kind === "zz_longunder" ? 15 : 0), what + ": the made-up rows are the list");
    ok(st.dayOf && st.dayOf(st.view[0]) === "2001-03-31", what + ": in days, newest first");
    var bnd = listWindow() + lwLong, g = 0, still = true, most = 0;
    while (st.shown < st.view.length && g++ < 200) {
      $("#list").scrollHeight = listH();
      $("#list").scrollTop = listH() - $("#list").clientHeight;
      var it = $("#list").querySelector('.item[data-id="' + st.view[st.shown - 1].id + '"]');
      var w = it.parentNode.id === "list" ? it : it.parentNode, b = lwAt(w), t = $("#list").scrollTop;
      dispatch($("#list"), "scroll", {}); runTimers(20);
      most = Math.max(most, st.shown - st.from);
      if (lwAt(w) !== b || $("#list").scrollTop !== t) { still = false; break; }
    }
    eq(st.shown, st.view.length, what + ": scrolling down reaches the last row");
    ok(still, what + ": with the rows under the finger never moving");
    ok(most <= bnd, what + ": the window stays within its bound plus the long day (" + most + " rows at most)");
    g = 0; still = true; most = 0;
    while (st.from && g++ < 200) {
      $("#list").scrollTop = padH();
      var f = $("#lpad").nextElementSibling, ft = lwAt(f), t0 = $("#list").scrollTop;
      dispatch($("#list"), "scroll", {}); runTimers(20);
      most = Math.max(most, st.shown - st.from);
      if (lwAt(f) - $("#list").scrollTop !== ft - t0) { still = false; break; }
    }
    eq(st.from, 0, what + ": scrolling back up reaches the first row");
    ok(still, what + ": without shifting what is on screen");
    ok(most <= bnd, what + ": and bounded on the way up too (" + most + " rows at most)");
    eq(padH(), 0, what + ": the spacer is gone");
    // and from the far end straight to the top, the way a flick gets there
    $("#list").scrollHeight = listH();
    renderAt(st.view.length - 1); await settle(3);
    for (g = 0; g < 300 && st.from; g++) {
      $("#list").scrollTop = 0;
      dispatch($("#list"), "scroll", {}); runTimers(20);
    }
    eq(st.from, 0, what + ": a flick to the top from the end gets there");
  };
  await lwWalk("zz_longtop", "a long day at the top");
  await lwWalk("zz_longunder", "a short day above a long one");
  lwMade.forEach(function (r) { st.all.splice(st.all.indexOf(r), 1); st.byId.delete(r.id); });
  setKinds([]); refresh();

  // a month jump from the keyboard, for when the rows have the focus
  select(st.view[0].id);
  key("}");
  eq(st.dayOf(st.sel).slice(0, 7), months[1], "} opens the first entry of the month below");
  key("}");
  eq(st.dayOf(st.sel).slice(0, 7), months[2], "and again");
  key("{");
  eq(st.dayOf(st.sel).slice(0, 7), months[1], "{ goes back up a month");
  eq(st.sel.id, st.view[rail.groups[1].start].id, "to its first entry");
  key("]");
  eq(st.dayOf(st.sel).slice(0, 7) <= months[1], true, "] still walks days");
  closeEditor();
  delete El.prototype.offsetTop;
  delete El.prototype.offsetHeight;

  // only a timeline gets one
  $("#fSort").value = "len:desc";
  refresh();
  ok($("#rail").hidden, "a sort by length has no months to scrub");
  ok(!$("#listwrap").classList.contains("railed"), "and hands the gutter back");
  key("}");
  has($("#toast").textContent, "month jumps need a date sort", "} explains itself");
  $("#fSort").value = "id:desc";
  refresh();
  var seen = new Set(), mono = true, prev = null;
  st.view.forEach(function (e) {
    var m = st.dayOf(e).slice(0, 7);
    if (m !== prev) { if (seen.has(m)) mono = false; seen.add(m); prev = m; }
  });
  eq(!$("#rail").hidden, mono, "id order gets one only if its months never come back");
  $("#fSort").value = "created:desc";
  $("#q").value = "zzqqxx-nothing-matches";
  refresh();
  ok($("#rail").hidden, "an empty list has none");
  $("#q").value = "";
  refresh();
  ok(!$("#rail").hidden, "and it returns with the rows");

  /* ---------- saved views ---------- */
  console.log("\n-- views: a filter combination, named --");
  views = [];
  saveViews();
  paintViews();
  eq($("#views").innerHTML, "", "nothing pinned, nothing drawn");
  has($("#viewhint").textContent, "no views", "and the hint says so");

  clearFilters();
  $("#q").value = "arena";
  $("#fDone").value = "0";
  refresh();
  var qs = stateQS(false);
  var p = saveView();
  ok(await answerPrompt("open arena"), "saving asks what to call it");
  await p;
  eq(views.length, 1, "and remembers one view");
  eq(views[0].name, "open arena", "under that name");
  eq(views[0].qs, qs, "holding the query string the url already writes");
  eq(JSON.parse(localStorage.getItem("lcars.views"))[0].name, "open arena", "in localStorage");
  ok($("#views").querySelector(".vc.on"), "the chip lights up: the filters are standing on it");

  p = saveView();
  await settle(3);
  has($("#toast").textContent, "already", "the same view twice is refused");
  ok(!$("#ov").classList.contains("on"), "without even asking for a name");
  await p;
  hideToast();

  clearFilters();
  ok(!$("#views").querySelector(".vc.on"), "clearing the filters puts the chip out");
  click($("#views").querySelector(".vcl"));
  await settle(3);
  eq($("#q").value, "arena", "clicking it brings the search back");
  eq($("#fDone").value, "0", "and the filters with it");
  ok($("#views").querySelector(".vc.on"), "and the chip is lit again");
  has($("#toast").textContent, "view · open arena", "the toast names it");
  hideToast();

  console.log("-- views: forgetting one --");
  click($("#views").querySelector(".vcx"));
  await settle(3);
  eq(views.length, 0, "the cross forgets it");
  eq($("#views").innerHTML, "", "and the chip goes");
  has($("#toast").textContent, "forgot", "with an undo offered");
  click($("#toast").querySelector(".tact"));
  await settle(3);
  eq(views.length, 1, "which puts it back");
  ok($("#views").querySelector(".vcl"), "chip and all");

  console.log("-- views: the cap --");
  views = [];
  for (var vi = 0; vi < VIEW_MAX; vi++) views.push({ name: "v" + vi, qs: "q=v" + vi });
  saveViews();
  paintViews();
  eq($("#views").querySelectorAll(".vc").length, VIEW_MAX, "every saved view is a chip");
  clearFilters();
  $("#q").value = "one too many";
  refresh();
  p = saveView();
  await settle(3);
  has($("#toast").textContent, "forget one first", "past the cap it refuses");
  ok(!$("#ov").classList.contains("on"), "rather than asking for a name it will not use");
  await p;
  views = [];
  saveViews();
  paintViews();
  clearFilters();
  hideToast();

  console.log("-- views: a name can be declined --");
  $("#q").value = "declined";
  refresh();
  p = saveView();
  ok(await answerPrompt(null), "Cancel answers the prompt");
  await p;
  eq(views.length, 0, "and nothing is saved");
  clearFilters();

  console.log("-- views: kept in the journal, for every device --");
  ok(views$.ready, "a whole load has settled, so the entry may be written");
  var vrow = viewsFind();
  if (vrow) { vrow.deleted = 1; dbFind(vrow.id).deleted = 1; }
  views$.row = null;
  views = [{ name: "tasks", qs: "k=task" }];
  saveViews();
  await views$.q;
  vrow = viewsFind();
  ok(vrow, "the first save creates a settings entry");
  eq(vrow && vrow.kind, "settings", "of kind settings");
  eq(vrow && vrow.title, "views", "titled views");
  eq(vrow && JSON.parse(dbFind(vrow.id).content).views[0].qs, "k=task", "holding the list as JSON on the server");
  var vcount = DB.filter(function (r) { return r.kind === "settings" && !r.deleted; }).length;
  views = [{ name: "tasks", qs: "k=task" }, { name: "logs", qs: "k=log" }];
  saveViews();
  await views$.q;
  eq(DB.filter(function (r) { return r.kind === "settings" && !r.deleted; }).length, vcount,
     "a second save updates it rather than adding another");
  eq(JSON.parse(dbFind(vrow.id).content).views.length, 2, "with both views");

  // another device changed it: the rows bring it, the chips follow
  vrow.content = viewsDoc([{ name: "elsewhere", qs: "q=far" }]);
  paintViews(true);
  eq(views.length, 1, "a change arriving with the rows is taken up");
  eq(views[0].name, "elsewhere", "whole");
  eq(JSON.parse(localStorage.getItem("lcars.views"))[0].name, "elsewhere", "and kept locally too");

  // a first boot on a device that already had views of its own: merged in
  views = [{ name: "mine", qs: "q=mine" }, { name: "dupe", qs: "q=far" }];
  localStorage.removeItem("lcars.viewsSync");
  await viewsSettle();
  await views$.q;
  eq(views.map(function (v) { return v.name; }).join(","), "elsewhere,mine",
     "the device's own views join the entry's, a duplicate once");
  eq(JSON.parse(dbFind(vrow.id).content).views.length, 2, "and are written back");
  ok(localStorage.getItem("lcars.viewsSync"), "once: the device is marked as merged");
  views = [{ name: "gone", qs: "q=gone" }];
  await viewsSettle();
  eq(views[0].name, "elsewhere", "after which the entry is the truth");

  // an app left open: another device edits the entry on the server only
  dbFind(vrow.id).content = viewsDoc([{ name: "phone", qs: "q=phone" }]);
  dbFind(vrow.id).last_modified_at_utc = "2099-02-02 00:00:00";
  views$.pollAt = 0;
  await viewsPoll();
  eq(views[0] && views[0].name, "phone", "coming back to the front fetches the entry and takes it up");
  var before = DBLOG.length;
  await viewsPoll();
  eq(DBLOG.length, before, "and does not ask again within 30s");

  // an entry that only appears after this page settled is still found
  var vrowWas = vrow;
  vrow.deleted = 1; dbFind(vrow.id).deleted = 1;
  views$.pollAt = 0;
  await viewsPoll();
  ok(!views$.row, "an entry deleted elsewhere is let go");
  eq(views[0] && views[0].name, "phone", "keeping the views it held");
  var r2 = await api("/entries", { method: "POST", body: { kind: "settings", title: "views",
    content: viewsDoc([{ name: "later", qs: "q=later" }]) } });
  var late = await api("/entries/" + r2.id);
  st.all.unshift(late); st.byId.set(late.id, late);
  paintViews(true);
  eq(views$.row, late, "a views row arriving with a sync is picked up");
  eq(views[0] && views[0].name, "later", "and its list taken");
  vrow = vrowWas;
  vrow.deleted = 0; dbFind(vrow.id).deleted = 0;
  late.deleted = 1; dbFind(late.id).deleted = 1;
  views$.row = vrow; views$.seen = vrow.content;

  // a hand edit the page cannot read is left alone
  var heldName = views[0].name;
  vrow.content = "not json";
  paintViews(true);
  eq(views[0].name, heldName, "an unreadable entry changes nothing");
  vrow.deleted = 1; dbFind(vrow.id).deleted = 1;
  views$.row = null;
  views = [];
  lsSet("lcars.views", views);
  // the rows this section created are taken out again: later tests read
  // st.all[0] as "the newest entry" and count what the journal holds
  var vmade = function (r) {
    return r.kind === "settings" && r.title === "views" &&
           !FIX.some(function (f) { return f.id === r.id; });
  };
  st.all.filter(vmade).forEach(function (r) { st.byId.delete(r.id); });
  st.all = st.all.filter(function (r) { return !vmade(r); });
  DB = DB.filter(function (r) { return !vmade(r); });
  fillKinds();
  paintViews(true);
  refresh();

  /* ---------- a child's naps, from a sentence ---------- */
  console.log("\n-- naps: a sentence about the child's nap offers a row of the child_sleep role's kind --");
  // The mapping as it stands (the journal's, or $LCARS_TEST_KINDS): its kind
  // and its name. With no name (the defaults) the suite gives the role one of
  // its own for these checks and takes it back after, so both the named and
  // the nameless forms are read whichever mapping the run has.
  var napKind = kindOf("child_sleep"), napMapWas = kindMap.map, napName = roleName("child_sleep");
  var napUse = function (name) {
    var m = new Map(roleRows().map(function (r) { return [r.role, Object.assign({}, r)]; }));
    m.get("child_sleep").name = name;
    kindMap.map = m; kindMap.gen++; napVoice();
  };
  if (!napName) {
    napUse("");
    eq(napWho(), "the nap", "with no name the chip says “the nap”");
    eq(napParse("Ada slept 13:35-14:39"), null, "and a name it was not given is not a nap");
    eq(napParse("nap from 13:35 to 14:39") && napParse("nap from 13:35 to 14:39").from, "13:35", "but a line about a nap is");
    napName = "Ada";
    napUse(napName);
  }
  var napLow = napName.toLowerCase();
  (function () {
    var n1 = napParse(napLow + " slept 1 h from 13:35 to 14:39");
    eq(n1 && n1.from + "-" + n1.to, "13:35-14:39", "“<name> slept 1 h from 13:35 to 14:39” is a nap, the 1 h not a time");
    var n2 = napParse("lunch, then\n- " + napName + " napped 13:35-14:39 in the pram");
    eq(n2 && n2.from + "-" + n2.to, "13:35-14:39", "“<name> napped 13:35-14:39”, on a bullet of its own");
    eq(n2 && n2.line, "- " + napName + " napped 13:35-14:39 in the pram", "naming the line it read");
    var n3 = napParse("nap from 13:35 to 14:39");
    eq(n3 && n3.from + "-" + n3.to, "13:35-14:39", "“nap from 13:35 to 14:39”");
    var n4 = napParse(napLow + "'s nap 1:35 pm to 2:39 p.m.");
    eq(n4 && n4.from + "-" + n4.to, "13:35-14:39", "pm is read");
    eq(napParse("the meeting ran from 13:35 to 14:39"), null, "times with no nap in the line are not one");
    eq(napParse(napLow + " slept well, a nap after lunch"), null, "a nap with no times is not one");
    eq(napParse("snap from 13:35 to 14:39"), null, "nor is a snap");
    eq(napParse("nap 25:10-26:00"), null, "nor a time of day that is none");
    var ov = napSpan({ from: "23:30", to: "01:10" }, "2026-10-14");
    eq(ov.start, utcOfDate(new Date(2026, 9, 14, 23, 30)), "a nap starts on the entry's local day");
    eq(ov.end, utcOfDate(new Date(2026, 9, 15, 1, 10)), "and one ending before it started ends the next day");
  })();
  closeEditor(); setClean(); hideToast();
  var napDay = new Date(); napDay.setDate(napDay.getDate() - 1); napDay.setHours(15, 0, 0, 0);
  startNew({ kind: kindOf("log"), title: "", content: "quiet afternoon\n" + napLow + " napped 13:35-14:39",
             value_int: 0, value_float: 0, done_bool: 0, deleted: 0,
             created_at_utc: utcOfDate(napDay), last_modified_at_utc: "" }, "NEW ENTRY", true);
  setRead(false);
  input($("#content"), $("#content").value);
  await settle(4);
  var napChip = $("#esug").querySelector(".sgnap");
  ok(napChip && !$("#esug").hidden, "the suggestions offer the nap");
  has(napChip && napChip.textContent, "13:35–14:39", "with its times");
  has(napChip && napChip.textContent, napName + "'s nap", "and the role's name");
  has(napChip && napChip.textContent, napKind, "and the kind it writes");
  var napBefore = DB.length;
  click(napChip);
  eq($("#esug").querySelector(".sgnap") && $("#esug").querySelector(".sgnap").getAttribute("aria-busy"), "true",
     "a tap says logging… in the same frame");
  await settle(6);
  var napRow = DB.filter(function (r) { return r.kind === napKind && !r.deleted; }).pop();
  eq(DB.length, napBefore + 1, "one row is created");
  var napStart = utcOfDate(new Date(napDay.getFullYear(), napDay.getMonth(), napDay.getDate(), 13, 35));
  eq(napRow && napRow.start_date, napStart, "a row of the role's kind starting at 13:35 on the entry's day");
  eq(napRow && napRow.end_date, utcOfDate(new Date(napDay.getFullYear(), napDay.getMonth(), napDay.getDate(), 14, 39)),
     "ending at 14:39");
  has($("#toast").textContent, "logged " + napName + "'s nap 13:35–14:39", "the toast says so");
  eq($("#toast").querySelector(".tact") && $("#toast").querySelector(".tact").textContent, "Undo", "with Undo");
  eq($("#content").value, "quiet afternoon\n" + napLow + " napped 13:35-14:39", "the sentence stays as written");
  ok(!$("#esug").querySelector(".sgnap"), "and the nap is no longer offered");
  napCheck();
  ok(!sg.nap, "nor offered again: it is logged");
  click($("#toast").querySelector(".tact"));
  await settle(6);
  ok(dbFind(napRow.id).deleted, "Undo deletes the row (soft)");
  ok(sg.nap && $("#esug").querySelector(".sgnap"), "and the nap is offered again");
  closeEditor(); setClean(); hideToast();
  // spoken: today's, by the role's name
  voiceHeard("computer log " + napName + "'s nap from 13:35 to 14:39");
  await settle(6);
  var napSaidRow = DB.filter(function (r) { return r.kind === napKind && !r.deleted; }).pop();
  var napToday = new Date();
  eq(napSaidRow && napSaidRow.start_date, utcOfDate(new Date(napToday.getFullYear(), napToday.getMonth(), napToday.getDate(), 13, 35)),
     "“log <name>'s nap from 13:35 to 14:39” logs today's nap");
  voiceHeard("computer log the nap from 13:35 to 14:39");
  await settle(4);
  has($("#toast").textContent, "logged already", "and says so, rather than logging it twice (“log the nap …”)");
  [napRow, napSaidRow].forEach(function (r) { if (r && st.byId.get(r.id)) unplant(st.byId.get(r.id)); });
  hideToast();
  // A mapping moves the chip's writes: the role pointed at another kind
  napUse(napName);
  kindMap.map.get("child_sleep").kind = "zz_naptime"; kindMap.map.get("child_sleep").kinds = ["zz_naptime"];
  var napMoved = await napLog(napOffer("nap from 09:10 to 09:40") || Object.assign({ from: "09:10", to: "09:40" },
    napSpan({ from: "09:10", to: "09:40" }, isoDay(new Date()))), 0);
  eq(napMoved && napMoved.kind, "zz_naptime", "a set child_sleep role moves where the nap is written");
  if (napMoved && st.byId.get(napMoved.id)) unplant(st.byId.get(napMoved.id));
  kindMap.map = napMapWas; kindMap.gen++; napVoice();
  hideToast();

  /* ---------- counters ---------- */
  console.log("\n-- counters: “log a diaper” is a counter row, counted in Stats --");
  eq(counterThing("a diaper"), "diaper", "“a diaper” is a diaper");
  eq(counterThing("diapers"), "diaper", "in the singular");
  eq(counterThing("nappies"), "nappy", "nappies, a nappy");
  eq(counterThing("an Ear Infection"), "ear infection", "two words, lower case");
  eq(counterThing("glass"), "glass", "a glass stays one");
  eq(counterThing("two feeds"), "", "two of something is not a thing called “two feed”");
  eq(counterThing("a reactor breach in engineering"), "", "more than three words is not a counter");
  closeEditor(); setClean(); hideToast();
  var cntBefore = DB.length;
  voiceHeard("computer log a diaper");
  has($("#toast").textContent, "counting a diaper", "the order shows “counting a diaper…” in the same frame");
  await settle(6);
  var cntRow = DB.filter(function (r) { return r.kind === "counter" && !r.deleted; }).pop();
  eq(DB.length, cntBefore + 1, "one row is created");
  eq(cntRow && [cntRow.title, +cntRow.value_int, cntRow.content || ""].join("|"), "diaper|1|",
     "kind counter, titled diaper, value_int 1, no body");
  has($("#toast").textContent, "counted a diaper", "the toast says so");
  has($("#toast").textContent, "today", "with today's count");
  eq($("#toast").querySelector(".tact") && $("#toast").querySelector(".tact").textContent, "Undo", "with Undo");
  click($("#toast").querySelector(".tact"));
  await settle(6);
  ok(dbFind(cntRow.id).deleted, "Undo deletes the row (soft)");
  voiceHeard("computer count a feed");
  await settle(6);
  var cntFeed = DB.filter(function (r) { return r.kind === "counter" && !r.deleted; }).pop();
  eq(cntFeed && cntFeed.title, "feed", "“count a feed” counts a feed");
  voiceHeard("computer count falls");
  await settle(6);
  var cntFall = DB.filter(function (r) { return r.kind === "counter" && !r.deleted; }).pop();
  eq(cntFall && cntFall.title, "fall", "“count falls”, a fall");
  var cntN = DB.filter(function (r) { return r.kind === "counter"; }).length;
  voiceHeard("computer log a reactor breach on deck four again");
  await settle(6);
  eq(DB.filter(function (r) { return r.kind === "counter"; }).length, cntN, "a long “log a …” is not counted");
  var cntCap = DB[DB.length - 1];
  has(cntCap && cntCap.content.toLowerCase(), "a reactor breach", "it is captured as a line, as “log …” was");
  if (cntCap && st.byId.get(cntCap.id)) unplant(st.byId.get(cntCap.id));
  ok(!measureSeries().has("counter"), "counters are not a measurement series");
  var cntD2 = await plant({ kind: "counter", title: "diaper", value_int: 1, content: "" });
  var cntD3 = await plant({ kind: "counter", title: "diaper", value_int: 1, content: "" });
  var wkAgo = new Date(); wkAgo.setDate(wkAgo.getDate() - 3);
  var cntOld = await plant({ kind: "counter", title: "diaper", value_int: 1, content: "", created_at_utc: fmtUtc(wkAgo) });
  var cntTal = counterTally(st.all).filter(function (c) { return c.title === "diaper"; })[0];
  eq(cntTal && cntTal.today + "/" + cntTal.week, "2/3", "two diapers today, three in seven days (the undone one not counted)");
  openStats();
  var cntCard = $("#dlg").querySelector('[data-counter="diaper"]');
  ok(/Counters/.test($("#dlg").innerHTML) && cntCard, "Stats has a Counters section, a card per thing");
  has(cntCard && cntCard.textContent, "2diaper today · 3 in 7 days", "today and the week");
  ok($("#dlg").querySelector('[data-counter="feed"]'), "and the feed");
  closeOv();
  // the palette's "count …": which, as chips of the ones counted before
  ok(paletteRows().some(function (r) { return /^count …/.test(r.label); }), "a palette row “count …”");
  openCounter();
  var cntChip = $("#cnt_known").querySelector('[data-cnt="diaper"]');
  ok(cntChip, "it offers the things counted before");
  click($("#cnt_ok"));
  ok(!$("#cnt_err").hidden, "Count with nothing typed says what it wants");
  click(cntChip);
  eq(cntChip.getAttribute("aria-busy"), "true", "a chip's tap shows counting… in the same frame");
  await settle(6);
  var cntPal = DB.filter(function (r) { return r.kind === "counter" && !r.deleted; }).pop();
  eq(cntPal && cntPal.title, "diaper", "the chip counts one");
  ok(!$("#ov").classList.contains("on"), "and the panel closes");
  [cntRow, cntFeed, cntFall, cntD2, cntD3, cntOld, cntPal].forEach(function (r) { if (r && st.byId.get(r.id)) unplant(st.byId.get(r.id)); });
  DB = DB.filter(function (r) { return r.kind !== "counter"; });
  hideToast();

  /* ---------- the map of a day ---------- */
  console.log("\n-- the map of a day: a pin per place written, opened by a tap --");
  (function () {
    var p1 = dmPlaces("lunch at\nCafe Central (45.12345, 24.54321 ±12 m)\nthen home");
    eq(p1.length === 1 && [p1[0].name, p1[0].lat, p1[0].lon].join("|"), "Cafe Central|45.12345|24.54321",
       "a place as /location types it: name, latitude, longitude");
    var p2 = dmPlaces("here: 44.43210, 26.10987 ±8 m and back at - Home (44.4, 26.1)");
    eq(p2.length === 1 && p2[0].name + "|" + p2[0].lat, "|44.4321", "bare coordinates, with no name; too few decimals is no place");
    eq(dmPlaces("3.5, 4.25 and 12.50, 7.75").length, 0, "nor are numbers in a sentence");
    eq(dmPlaces("(95.12345, 24.54321)").length, 0, "nor a latitude past the pole");
  })();
  var fakeMap = { markers: [], lines: 0, views: 0 };
  var realL = window.L;
  window.L = {
    Map: { prototype: {} },
    map: function () { return { stop: function () {}, remove: function () { fakeMap.removed = true; },
      setView: function () { fakeMap.views++; }, fitBounds: function () { fakeMap.views++; }, invalidateSize: function () {} }; },
    tileLayer: function (u) { fakeMap.tiles = u; return { addTo: function () { return this; } }; },
    divIcon: function () { return {}; },
    marker: function (ll, o) { var m = { ll: ll, o: o, on: function (ev, fn) { this.tap = fn; return this; },
      addTo: function () { fakeMap.markers.push(this); return this; } }; return m; },
    polyline: function () { return { addTo: function () { fakeMap.lines++; return this; } }; },
  };
  var dmDay = new Date(2001, 0, 2, 12, 0, 0), dmKey = isoDay(dmDay);
  var dmA = await plant({ title: "dm none", content: "a quiet day, nowhere in particular", created_at_utc: fmtUtc(dmDay) });
  refresh();
  crs.key = null;
  lsSet(DM_KEEP, false);
  openDay(dmKey);
  has($("#dmsay").textContent, "no places written this day", "no coordinates that day: one line says so");
  ok($("#dmbtn").hidden && $("#dmbox").hidden, "and there is no map to open");
  closeOv();
  var dmB = await plant({ title: "dm cafe", content: "coffee\nCafe Central (45.12345, 24.54321 ±12 m)",
                          created_at_utc: fmtUtc(new Date(2001, 0, 2, 13, 0, 0)) });
  var dmC = await plant({ title: "dm park", content: "44.43210, 26.10987 ±8 m",
                          created_at_utc: fmtUtc(new Date(2001, 0, 2, 15, 0, 0)) });
  refresh();
  openDay(dmKey);
  has($("#dmsay").textContent, "2 places this day", "a day with places counts them");
  has($("#dmsay").textContent, "no map key", "and with no key says the tiles are OpenStreetMap's");
  ok(!$("#dmbtn").hidden && $("#dmbox").hidden, "the map waits for Map");
  click($("#dmbtn"));
  ok(!$("#dmbox").hidden, "Map shows the map's box in the same frame");
  await settle(6);
  eq(fakeMap.markers.length, 2, "a pin per place");
  has(fakeMap.tiles, "openstreetmap", "on OpenStreetMap's tiles without a key");
  eq(lsGet(DM_KEEP, false), true, "the map's choice is kept");
  var dmPin = fakeMap.markers.filter(function (m) { return /Cafe Central/.test(m.o.title); })[0];
  ok(dmPin && dmPin.tap, "the pin is titled with its place");
  dmPin.tap();
  await settle(4);
  eq(st.sel && st.sel.id, dmB.id, "a tap on a pin opens its entry");
  ok(!$("#ov").classList.contains("on"), "and the day page gives way to it");
  navigator.onLine = false;
  openDay(dmKey);
  has($("#dmsay").textContent, "offline", "offline, the line says the map needs the network");
  ok($("#dmbtn").hidden && $("#dmbox").hidden, "and draws nothing");
  closeOv();
  delete navigator.onLine;
  lsSet(DM_KEEP, false);
  fakeMap.markers = [];
  closeEditor(); setClean();
  // spoken: the open entry's day, with its map
  select(dmC.id);
  voiceHeard("computer show the map of the day");
  await settle(6);
  eq(dayOpen, dmKey, "“show the map of the day” opens the open entry's day");
  eq(fakeMap.markers.length, 2, "with its map drawn");
  closeOv();
  voiceHeard("computer map of today");
  await settle(4);
  eq(dayOpen, isoDay(new Date()), "“map of today” opens today");
  closeOv();
  // a trip: the same over its days
  fakeMap.markers = [];
  var dmT = await plant({ kind: "trip", title: "dm trip", content: "```json trip\n{\"v\":1,\"depart\":\"2001-01-01T09:00\",\"points\":[]}\n```",
                          start_date: fmtUtc(new Date(2001, 0, 1, 9, 0, 0)), end_date: fmtUtc(new Date(2001, 0, 2, 20, 0, 0)),
                          created_at_utc: fmtUtc(new Date(2000, 11, 20, 9, 0, 0)) });
  eq(tripDays(dmT).join(), "2001-01-01,2001-01-02", "a trip's days run from its start to its end");
  select(dmT.id);
  voiceHeard("computer map of the trip");
  await settle(6);
  has($("#dmsay").textContent, "2 places on this trip", "“map of the trip” maps the trip's days");
  eq(fakeMap.markers.length, 2, "at once");
  ok(st.route && st.route.v === "places", "with a url of its own");
  closeOv();
  window.L = realL;
  crs.key = undefined;
  lsSet(DM_KEEP, false);
  closeEditor(); setClean();
  [dmA, dmB, dmC, dmT].forEach(function (r) { if (r && st.byId.get(r.id)) unplant(st.byId.get(r.id)); });
  hideToast();

  /* ---------- pinned entries ---------- */
  console.log("\n-- pins: favourite pages, kept with the views, eight at most --");
  ok(views$.ready, "the settings entry may be written");
  pins = []; pinsSave(); await views$.q;
  var pinRows = [];
  for (var pi = 0; pi < 9; pi++) pinRows.push(await plant({ title: "zebrapin page " + ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"][pi] }));
  select(pinRows[0].id); setRead(true); await settle(2);
  ok($("#bPin").style.display !== "none", "the reader has a Pin button");
  eq($("#bPin").getAttribute("aria-pressed"), "false", "not pressed");
  click($("#bPin"));
  eq($("#bPin").getAttribute("aria-pressed"), "true", "a tap pins it, the button pressed in the same frame");
  has($("#toast").textContent, "pinned “zebrapin page one”", "the toast says so");
  ok(!$("#pinrow").hidden, "the list has its row of pins");
  eq($("#pinrow").querySelectorAll("[data-pin]").length, 1, "one chip");
  has($("#pinrow").textContent, "zebrapin page one", "titled");
  await views$.q;
  var pinDoc = viewsFind();
  ok(pinDoc, "the settings entry exists");
  eq(pinDoc && JSON.stringify(JSON.parse(dbFind(pinDoc.id).content).pins), JSON.stringify([pinRows[0].id]),
     "and holds the pin on the server");
  // the cap
  for (pi = 1; pi < 8; pi++) pinSet(pinRows[pi].id, true, true);
  eq(pins.length, 8, "eight pins");
  select(pinRows[8].id); setRead(true); await settle(2);
  click($("#bPin"));
  eq(pins.length, 8, "a ninth is refused");
  has($("#toast").textContent, "8 pins is the lot", "and the toast says why");
  ok($("#toast").classList.contains("bad"), "as a refusal");
  eq($("#bPin").getAttribute("aria-pressed"), "false", "its button stays unpressed");
  await views$.q;
  eq(JSON.parse(dbFind(pinDoc.id).content).pins.length, 8, "the server holds the eight");
  // round trip: another device's change arrives with the rows
  pinDoc.content = viewsDoc(views, [pinRows[2].id, pinRows[8].id]);
  paintViews(true);
  eq(JSON.stringify(pins), JSON.stringify([pinRows[2].id, pinRows[8].id]), "another device's pins are taken up");
  eq(JSON.stringify(lsGet("lcars.pins", [])), JSON.stringify(pins), "and kept locally too");
  eq($("#pinrow").querySelectorAll("[data-pin]").length, 2, "the row follows");
  eq($("#bPin").getAttribute("aria-pressed"), "true", "and so does the open entry's button");
  // a fresh device: its own pins merge into the entry's
  pins = [pinRows[5].id, pinRows[2].id];
  localStorage.removeItem("lcars.viewsSync");
  await viewsSettle(); await views$.q;
  eq(JSON.stringify(pins), JSON.stringify([pinRows[2].id, pinRows[8].id, pinRows[5].id]), "a first load merges a device's pins in, once each");
  eq(JSON.stringify(JSON.parse(dbFind(pinDoc.id).content).pins), JSON.stringify(pins), "and writes them back");
  // the chips
  click($("#pinrow").querySelector('[data-pin="' + pinRows[5].id + '"]'));
  await settle(2);
  eq(st.sel && st.sel.id, pinRows[5].id, "a chip opens its entry");
  click($("#pinrow").querySelector('[data-unpin="' + pinRows[5].id + '"]'));
  ok(pins.indexOf(pinRows[5].id) < 0, "its ✕ unpins it");
  eq($("#toast").querySelector(".tact") && $("#toast").querySelector(".tact").textContent, "Undo", "with Undo");
  click($("#toast").querySelector(".tact"));
  ok(pins.indexOf(pinRows[5].id) >= 0, "which pins it back");
  // the palette
  var pinPal = paletteRows().map(function (r) { return r.label; });
  ok(pinPal.indexOf("pinned · zebrapin page three") >= 0, "the palette has a row per pin");
  ok(pinPal.indexOf("pinned · unpin this entry") >= 0, "and the open entry's unpin");
  // the voice
  select(pinRows[0].id); await settle(2);
  voiceHeard("computer open zebrapin page nine");
  await settle(2);
  eq(st.sel && st.sel.id, pinRows[8].id, "“open zebrapin page nine” opens the pinned page by title");
  voiceHeard("computer open entry " + pinRows[0].id);
  await settle(2);
  eq(st.sel && st.sel.id, pinRows[0].id, "“open entry N” is still by id");
  voiceHeard("computer open zebrapin page four");
  has($("#toast").textContent, "nothing pinned is called", "a title nothing pinned has is refused");
  voiceHeard("computer pin this page");
  ok(pins.indexOf(pinRows[0].id) >= 0, "“pin this page” pins the open one");
  voiceHeard("computer unpin this page");
  ok(pins.indexOf(pinRows[0].id) < 0, "“unpin this page” unpins it");
  eq(vMatch(vWords("pin it to the stack"), 0).cmd.say, "pin it to the stack", "“pin it to the stack” is still the stack's");
  // the sheet
  ok(ED_MORE.some(function (x) { return x[0] === "#bPin"; }), "the ⋯ sheet has the pin");
  // clean up: the pins, the settings row and the planted pages
  await views$.q;
  pins = []; lsSet("lcars.pins", pins);
  pinDoc.deleted = 1; dbFind(pinDoc.id).deleted = 1; views$.row = null;
  var pmade = function (r) { return r.kind === "settings" && r.title === "views" && !FIX.some(function (f) { return f.id === r.id; }); };
  st.all.filter(pmade).forEach(function (r) { st.byId.delete(r.id); });
  st.all = st.all.filter(function (r) { return !pmade(r); });
  DB = DB.filter(function (r) { return !pmade(r); });
  pinRows.forEach(unplant);
  closeEditor(); setClean(); hideToast();
  views = []; lsSet("lcars.views", views);
  paintViews(true);
  ok($("#pinrow").hidden, "no pins, no row");

  /* ---------- alert conditions ---------- */
  console.log("\n-- alert: the palette follows the ship's condition, after a hold --");
  var alT = Date.now();
  // the fixture's own overdue tasks set aside, so each condition is tried alone
  var alOd = st.all.filter(function (e) {
    return e.start_date && !e.deleted && !Number(e.done_bool) && taskKind(e.kind) && !crewWritten(e.kind) && utcMs(e.start_date) < alT;
  });
  alOd.forEach(function (e) { e.done_bool = 1; });
  st.bodyGen++;
  var alSettle = function (t) { alertTick(t); alertTick(t + ALERT_HOLD_MS); };
  alSettle(alT);
  ok(!document.body.dataset.alert, "condition green: no alert");
  ok($("#halert").hidden, "and no line in the header");
  ob.offline = true;
  alertTick(alT + 3000);
  ok(!document.body.dataset.alert, "the link lost: nothing at once");
  alertTick(alT + 4000);
  ok(!document.body.dataset.alert, "nor a second later");
  ob.offline = false;
  alertTick(alT + 4500);
  alertTick(alT + 7000);
  ok(!document.body.dataset.alert, "back before the hold: the palette never moved");
  ob.offline = true;
  alertTick(alT + 8000);
  alertTick(alT + 10000);
  eq(document.body.dataset.alert, "red", "unreachable for the hold: red alert");
  ok(!$("#halert").hidden, "the header has its line");
  eq($("#halert").textContent, "offline", "saying offline");
  ob.offline = false;
  alertTick(alT + 10500);
  eq(document.body.dataset.alert, "red", "clear again: red holds on");
  alertTick(alT + 12500);
  ok(!document.body.dataset.alert, "until the clear has held too");
  ok($("#halert").hidden, "the line goes with it");
  // an outbox write: waiting is yellow, refused is red
  var alOp = { id: 1999999999, stuck: false, held: false };
  ob.ops.set(alOp.id, alOp);
  alSettle(alT + 20000);
  eq(document.body.dataset.alert, "yellow", "an outbox write waiting: yellow alert");
  eq($("#halert").textContent, "1 waiting", "saying so");
  alOp.stuck = true;
  alSettle(alT + 30000);
  eq(document.body.dataset.alert, "red", "one it could not send: red");
  eq($("#halert").textContent, "1 not sent", "saying so");
  ob.ops.delete(alOp.id);
  alSettle(alT + 40000);
  ok(!document.body.dataset.alert, "gone: green");
  // a save on the wire
  document.body.dataset.save = "saving";
  alSettle(alT + 50000);
  eq(document.body.dataset.alert, "yellow", "a save pending: yellow alert");
  eq($("#halert").textContent, "saving", "saying saving");
  delete document.body.dataset.save;
  alSettle(alT + 60000);
  ok(!document.body.dataset.alert, "saved: green");
  // a task overdue
  var alTask = await plant({ kind: "task", title: "zebra alert task", start_date: fmtUtc(new Date(alT - 3600e3)), done_bool: 0 });
  var alCrew = await plant({ kind: "task_no1", title: "zebra alert crew task", start_date: fmtUtc(new Date(alT - 3600e3)), done_bool: 0 });
  alSettle(alT + 70000);
  eq(document.body.dataset.alert, "red", "a task past due: red alert");
  eq($("#halert").textContent, "1 overdue", "one overdue: the crew's own tasks are not counted");
  hideToast();
  voiceHeard("computer why the alert");
  has($("#toast").textContent, "red alert · 1 overdue", "“why the alert” says it in a toast");
  hideToast();
  click($("#halert"));
  has($("#toast").textContent, "1 overdue", "and so does a tap on the line");
  alTask.done_bool = 1; st.bodyGen++;
  alSettle(alT + 80000);
  ok(!document.body.dataset.alert, "done: green");
  hideToast();
  voiceHeard("computer why the alert");
  has($("#toast").textContent, "condition green", "and asked why, it says all clear");
  unplant(alTask); unplant(alCrew);
  alOd.forEach(function (e) { e.done_bool = 0; });
  st.bodyGen++;
  hideToast();

  /* ---------- ambient mode ---------- */
  console.log("\n-- ambient: the console with nobody at it --");
  closeEditor();
  setClean();
  ok(!ambOn, "it starts down");
  ambStart();
  ok(ambOn, "and comes up");
  eq(document.body.dataset.amb, "on", "the body says so");
  eq($("#amb").getAttribute("aria-hidden"), "false", "and it is readable while it is up");
  ok(/^\d\d:\d\d$/.test($("#ambclock").textContent), "the clock is set");
  ok($("#ambdate").textContent.length > 0, "and dated");
  eq($("#ambstats").querySelectorAll(".scard").length, 5, "five numbers");
  has($("#ambstats").innerHTML, "day streak", "including the streak");
  eq($("#ambheat").children.length, AMB_HEAT_WEEKS * 7, "the heatmap is whole weeks");
  ok($("#ambheat").querySelector("i.today"), "with today marked");
  ok($("#ambmem").innerHTML.length > 0, "and a memory up");
  has($("#ambfoot").textContent, "any key", "the way out is written down");

  key("z");
  ok(!ambOn, "any key hands the console back");
  eq(document.body.dataset.amb, "off", "the body says so");
  eq($("#amb").getAttribute("aria-hidden"), "true", "and it is hidden from the reader again");

  ambToggle();
  ok(ambOn, "the toggle brings it up");
  ambToggle();
  ok(!ambOn, "and puts it down");

  console.log("-- ambient: what holds it back --");
  startNew({ kind: "personal_log", title: "", content: "half a thought",
             value_int: 0, value_float: 0, done_bool: 0, deleted: 0,
             created_at_utc: utcNow(), last_modified_at_utc: "" }, "NEW ENTRY", true);
  ambStart();
  ok(!ambOn, "it refuses to blank the screen over unsaved work");
  has($("#toast").textContent, "unsaved", "and says why");
  setClean();
  closeEditor();
  hideToast();

  cfg.amb = 0;
  idleArm();
  ok(idleTmr === null, "with no interval set, no idle timer is armed");
  cfg.amb = 5;
  idleArm();
  ok(idleTmr !== null, "an interval arms one");
  cfg.amb = 0;
  idleArm();

  // the fixture rows the suites after this one read are put back as they were
  st.all = st.all.filter(function (e) { return e.id < 999000; });
  st.byId.delete(999002);
  st.byId.delete(999003);
  clearFilters();
  hideToast();

  console.log("\nsection F: " + TEST.asserts + " assertions, " + TEST.fails.length + " failures");
  globalThis.__phaseF = true;
})().catch(function (e) { console.log("SUITE F THREW: " + e + "\n" + (e && e.stack)); });

/* ===================== suite E: failure modes ===================== */
(async function () {
  if (!await waitFlag("__phaseF")) return;
  closeEditor();
  setClean();

  console.log("\n-- file://: replaceState refuses, everything else carries on --");
  var realReplace = history.replaceState;
  histOk = true;
  history.replaceState = function () { throw new Error("SecurityError: origin null"); };
  $("#q").value = "swim";
  refresh();
  runTimers();
  ok(!histOk, "the first refusal turns url state off for good");
  ok(st.view !== undefined, "and the app keeps working");
  ok(localStorage.getItem("lcars.filters").indexOf("q=swim") >= 0,
     "filters are still remembered locally");
  history.replaceState = realReplace;
  histOk = true;
  clearFilters();

  console.log("-- a fat page falls back to halves (the 1MB arena) --");
  var realRoute = route, refusals = 0;
  route = function (method, path, qs, body) {
    if (path === "/entries" && method === "GET" && +qs.get("limit") > 40) {
      refusals++;
      return { code: 500, data: { error: "response too large" } };
    }
    return realRoute(method, path, qs, body);
  };
  st.all = []; st.byId = new Map();
  await loadAll();
  await settle(20);
  ok(refusals > 0, "the server refused fat pages (" + refusals + " times)");
  eq(st.all.length, DB.length, "every row still arrived, via halving");
  var ids = st.all.map(function (e) { return e.id; });
  eq(new Set(ids).size, ids.length, "with no duplicates");
  var sortedDesc = ids.every(function (v, i) { return i === 0 || ids[i - 1] > v; });
  ok(sortedDesc, "and still newest-first");
  route = realRoute;

  console.log("-- offline: the list says so and offers a way back --");
  var realFetch = fetch, deadTries = 0;
  // the outbox's link probe (/health, every OB_RETRY) is not the load retrying
  fetch = function (u) { if (!/\/health$/.test(String(u))) deadTries++; return Promise.reject(new Error("Failed to fetch")); };
  st.all = []; st.byId = new Map();
  refresh();
  await loadAll();
  await settle(10);
  // a dead host is answered once, not split into halves sixty times
  ok(deadTries <= 3, "a dead host is given up on quickly (" + deadTries + " requests)");
  has($("#hstat").textContent, "offline", "the header says offline");
  has($("#list").textContent, "no link", "so does the list");
  ok($("#bRetry"), "with a Retry");
  ok($("#bOffCfg"), "and a way into Config");
  fetch = realFetch;
  click($("#bRetry"));
  await settle(20);
  eq(st.all.length, DB.length, "Retry brings the journal back");

  console.log("-- a failed reload does not wipe what is already on screen --");
  var shown = $("#list").querySelectorAll(".item").length;
  ok(shown > 0, "rows are on screen");
  fetch = function () { return Promise.reject(new Error("Failed to fetch")); };
  await loadAll();
  await settle(10);
  eq(st.all.length, DB.length, "the cached rows survive a failed reload");
  eq($("#list").querySelectorAll(".item").length, shown, "and stay on screen");
  fetch = realFetch;

  console.log("-- a full localStorage cannot break editing --");
  var realSet = localStorage.setItem;
  localStorage.setItem = function () { throw new Error("QuotaExceededError"); };
  newEntry();
  $("#content").value = "written while storage is full";
  markDirty();
  runTimers();
  eq($("#content").value, "written while storage is full", "typing still works");
  saveCache();
  refresh();
  ok(true, "cache, drafts and url state all swallow the quota error");
  localStorage.setItem = realSet;
  setClean();
  closeEditor();

  console.log("-- an entry that vanished from the server --");
  await loadAll();
  await settle(20);
  var ghost = st.all.filter(function (e) { return !e.deleted; })[5];
  select(ghost.id);
  var keepDb = DB;
  DB = DB.filter(function (r) { return r.id !== ghost.id; });
  await refreshSel();
  await settle(8);
  ok(!st.byId.has(ghost.id), "it is dropped from the cache");
  eq(document.body.dataset.pane, "list", "and the editor closes");
  has($("#toast").textContent, "gone from the server", "with an explanation");
  DB = keepDb;

  console.log("-- a deep link to a missing entry --");
  st.wantSel = 999999;
  await loadAll();
  await settle(20);
  eq(st.wantSel, null, "the request is dropped");
  has($("#toast").textContent, "not in this journal", "and reported");
  // There is one toast and a load can have two things to say. The count of
  // what arrived while you were away is on the sidebar button anyway; a
  // deep link that went nowhere is only said here, so it wins.
  ok($("#toast").textContent.indexOf("since your last visit") < 0,
     "and is not talked over by the routine news");

  console.log("-- a bad regex is reported, not thrown --");
  for (var b of $("#mode").children) b.classList.toggle("on", b.dataset.v === "regex");
  $("#q").value = "foo(";
  refresh();
  ok($("#qerr").textContent.length > 0, "the error is shown: " + $("#qerr").textContent);
  ok(st.view.length > 0, "and the list is not emptied by it");
  clearFilters();
  for (var b2 of $("#mode").children) b2.classList.toggle("on", b2.dataset.v === "text");

  console.log("-- an entry with no kind is reachable --");
  DB.push({ id: 999001, kind: "", title: "kindless", content: "x", content_length: 1,
            value_int: 0, value_float: 0, done_bool: 0, deleted: 0,
            created_at_utc: "2026-09-01 10:00:00", last_modified_at_utc: "2026-09-01 10:00:00" });
  await loadAll();
  await settle(20);
  setKinds([NOKIND]);
  refresh();
  ok(st.view.length > 0, "the (no kind) filter finds them");
  ok(st.view.every(function (e) { return e.kind === "" || e.kind === null; }),
     "and only them");
  clearFilters();
  // and then it goes away again, like every other row invented for one test.
  // Left in, it is a row with an impossible id and an ordinary date: newest in
  // the journal by id, buried by date, which is exactly the pair of orders the
  // fresh marks are read against further down.
  DB.splice(DB.indexOf(dbFind(999001)), 1);
  st.all = st.all.filter(function (e) { return e.id !== 999001; });
  st.byId.delete(999001);
  refresh();

  console.log("-- a sort with no days degrades instead of throwing --");
  $("#fSort").value = "len:desc";
  refresh();
  ok(st.dayOf === null, "length order has no days");
  eq($("#list").querySelectorAll(".day").length, 0, "so no day dividers are drawn");
  key("d");
  has($("#toast").textContent, "needs a date sort", "d explains itself");
  jumpDay(1);
  has($("#toast").textContent, "a date sort", "so does ]");
  ok($("#list").querySelectorAll(".item").length > 0, "and the list still renders");
  $("#fSort").value = "created:desc";
  refresh();
  ok(st.dayOf !== null, "day dividers come back");

  console.log("-- the list comes in without the bodies, and the bodies follow --");
  var realRoute3 = route, metaReq = 0, bodyReq = 0, holdBodies = true;
  route = function (method, path, qs, body) {
    if (path === "/entries" && method === "GET") {
      if (qs.get("content") === "0") metaReq++;
      else {
        bodyReq++;
        if (holdBodies) return { code: 500, data: { error: "held" } };
      }
    }
    return realRoute3(method, path, qs, body);
  };
  st.all = []; st.byId = new Map();
  closeEditor();
  await loadAll();
  await settle(20);
  eq(metaReq, 1, "the whole journal's metadata came in one request");
  ok(bodyReq > 0, "the bodies were asked for separately (" + bodyReq + " tries)");
  eq(st.all.length, DB.length, "every row is in the list");
  ok(st.all.every(function (e) { return needsBody(e); }), "and every body is still missing");
  eq(st.bodies, st.all.length, "the tally agrees");
  ok($("#list").querySelectorAll(".item").length > 0, "the list renders anyway");
  ok($("#list").querySelector(".sn.pend"), "with the snippets marked as pending");
  has($("#count").textContent, "bodies loading", "and the count says what is missing");

  console.log("-- a bodiless row is never cached, edited or copied blind --");
  saveCache();
  var cold = JSON.parse(localStorage.getItem("lcars.cache"));
  eq(cold.rows.length, 0, "the warm-boot cache refuses rows with no body");
  var pend = st.view[0];
  select(pend.id);
  runTimers();
  ok($("#content").readOnly, "the editor will not let the empty box be typed into");
  has($("#rd_content").textContent, "loading", "and the reader says why");
  setRead(false);
  await save();
  has($("#toast").textContent, "still loading its content", "save refuses to flatten it");
  await settle(10);
  ok(!needsBody(pend), "selecting it fetched that one body by id");
  ok(!$("#content").readOnly, "and the box opens up once it lands");
  eq($("#content").value, DB.filter(function (r) { return r.id === pend.id; })[0].content,
     "with the real content in it");
  closeEditor();
  runTimers();

  console.log("-- a day view fills its own holes --");
  st.read = true;
  var dayBar = $("#list").querySelector(".day");
  openDay(dayBar.dataset.day);
  await settle(10);
  ok(dayEntries(dayBar.dataset.day).every(function (e) { return !needsBody(e); }),
     "opening a day fetched the bodies it needed");
  ok($("#dayout").textContent.length > 0, "and the day has text in it");
  click($("#dayclose"));

  console.log("-- once the bodies are let through, the sweep completes --");
  holdBodies = false;
  st.all = []; st.byId = new Map();
  await loadAll();
  await settle(30);
  eq(st.bodies, 0, "nothing is left pending");
  ok(st.all.every(function (e) { return !needsBody(e); }), "every row has its body");
  eq($("#list").querySelectorAll(".sn.pend").length, 0, "no pending snippets on screen");
  ok($("#count").textContent.indexOf("bodies loading") < 0, "and the count stops saying so");
  var cached2 = JSON.parse(localStorage.getItem("lcars.cache"));
  ok(cached2.rows.length > 0, "now the warm-boot cache fills (" + cached2.rows.length + " rows)");
  route = realRoute3;

  /* ---------- the mirror ---------- */
  // IndexedDB does not exist in this engine, so the mirror's three calls are
  // answered by a Map — the same shape idbStore() returns, and the same
  // structured-clone copying, so nothing the page holds is shared with it.
  var clone = function (v) { return v == null ? v : JSON.parse(JSON.stringify(v)); };
  var memMirror = function () {
    var m = { rows: new Map(), meta: null, writes: 0 };
    m.read = function () {
      var rows = Array.from(m.rows.values()).sort(function (a, b) { return a.id - b.id; });
      return Promise.resolve({ meta: clone(m.meta), rows: rows.map(clone) });
    };
    m.write = function (rows, meta, replace) {
      m.writes++;
      if (replace) m.rows.clear();
      rows.forEach(function (r) { m.rows.set(r.id, clone(r)); });
      m.meta = clone(meta);
      return Promise.resolve();
    };
    return m;
  };
  var mem = memMirror();
  var savedStore = mirrorStore;
  mirrorStore = mem;
  var gets = function (pfx) {
    return TEST.fetches.filter(function (f) { return f.indexOf("GET " + pfx) === 0; }).length;
  };
  var dbMaxStamp = function () {
    return DB.reduce(function (m, r) { return r.last_modified_at_utc > m ? r.last_modified_at_utc : m; }, "");
  };
  var dbMaxId = function () { return DB.reduce(function (m, r) { return Math.max(m, r.id); }, 0); };

  console.log("\n-- a server with /dump: the whole journal in one answer --");
  DUMP_ON = true;
  dumpMissing = false;
  hideToast();
  closeEditor();
  localStorage.setItem("lcars.cache", JSON.stringify({ at: 1, rows: [] }));
  st.all = []; st.byId = new Map();
  var mPages = gets("/entries?"), mDumps = gets("/dump?");
  await loadAll();
  await settle(20);
  eq(gets("/dump?") - mDumps, 1, "one /dump");
  eq(gets("/entries?") - mPages, 1, "beside the one metadata page that paints the list first");
  eq(st.all.length, DB.length, "every row is in");
  ok(st.all.every(function (e) { return !needsBody(e); }), "each with its body");
  eq(st.bodies, 0, "so there is no sweep left to run");
  var mDesc = true;
  for (var mi = 1; mi < st.all.length; mi++) if (st.all[mi - 1].id <= st.all[mi].id) mDesc = false;
  ok(mDesc, "st.all is id-desc with no duplicates");
  eq(mem.rows.size, DB.length, "the mirror holds the whole journal");
  eq(mem.meta.mark, dbMaxStamp(), "marked with the server's newest stamp");
  eq(mem.meta.maxId, dbMaxId(), "and its highest id");
  ok(!Object.prototype.hasOwnProperty.call(mem.rows.get(st.all[0].id), "zz"), "stored as plain rows");
  eq(localStorage.getItem("lcars.cache"), null, "the old warm cache is dropped as redundant");

  console.log("-- a boot paints from the mirror without asking the network --");
  st.all = []; st.byId = new Map();
  var mWas = TEST.fetches.length;
  ok(await mirrorPaint(), "the mirror painted");
  eq(TEST.fetches.length - mWas, 0, "with no request at all");
  eq(st.all.length, DB.length, "the whole journal");
  ok(st.all.every(function (e) { return !needsBody(e); }), "bodies included");
  ok($("#list").querySelectorAll(".item").length > 0, "on screen");
  has($("#hstat").textContent, "syncing", "and the header says it is catching up");

  console.log("-- the sync brings down edits, deletes and backdated rows, and nothing else --");
  var live = st.all.filter(function (e) { return !e.deleted; });
  var mA = live[3], mB = live[7];
  var keepA = clone(dbFind(mA.id)), keepB = clone(dbFind(mB.id));
  dbFind(mA.id).content = "edited by the CLI overnight";
  dbFind(mA.id).last_modified_at_utc = "2099-12-01 00:00:01";
  dbFind(mB.id).deleted = 1;
  dbFind(mB.id).last_modified_at_utc = "2099-12-01 00:00:02";
  var mC = clone(DB[0]);
  mC.id = dbMaxId() + 1; mC.deleted = 0; mC.kind = "mirror_probe";
  mC.title = "imported with an old stamp"; mC.content = "from 2001";
  mC.created_at_utc = mC.last_modified_at_utc = "2001-01-01 00:00:00";
  DB.push(mC);
  var mObjA = mA;
  mWas = TEST.fetches.length;
  var mR = await deltaSync();
  await settle(4);
  eq(TEST.fetches.length - mWas, 3, "two small /dumps and /stats");
  eq(mR.added, 1, "the backdated row came down (min_id found what modified_since cannot)");
  ok(mR.changed >= 2, "and the two changed rows (" + mR.changed + ")");
  ok(st.byId.get(mA.id) === mObjA, "the row object on screen was written into, not replaced");
  eq(mA.content, "edited by the CLI overnight", "with the new body");
  eq(mB.deleted, 1, "the delete arrived");
  eq(st.all[0].id, mC.id, "the new row sits at the top of an id-desc list");
  eq(st.all.length, DB.length, "and the count now agrees with the server");
  eq(mem.meta.mark, "2099-12-01 00:00:02", "the mark moved to the newest change");
  eq(mem.meta.maxId, mC.id, "the id ceiling to the new row");
  eq(mem.rows.get(mA.id).content, "edited by the CLI overnight", "the mirror has the edit");
  ok(mem.rows.has(mC.id), "and the new row");
  ok(kindRank.kinds.indexOf("mirror_probe") >= 0, "a kind nobody had seen joins the filter");

  console.log("-- a second sync over an unchanged server is the same three requests --");
  mWas = TEST.fetches.length;
  mR = await deltaSync();
  eq(TEST.fetches.length - mWas, 3, "three requests");
  eq(mR.added, 0, "nothing new");
  ok(mR.changed <= 2, "only the rows sharing the mark's second are re-read (" + mR.changed + ")");

  console.log("-- an unsaved entry is never overwritten under the writer --");
  hideToast();
  select(mA.id);
  await settle(6);
  setRead(false);
  input($("#e_head"), "mid-sentence");
  ok(document.body.classList.contains("dirty"), "the form is dirty");
  var mTitle = mA.title;
  dbFind(mA.id).title = "their title, not yours";
  dbFind(mA.id).last_modified_at_utc = "2099-12-01 00:00:03";
  await deltaSync();
  await settle(4);
  eq(mA.title, mTitle, "the held row kept what the editor is holding");
  eq($("#e_head").value, "mid-sentence", "and the form still has the unsaved words");
  eq(mem.rows.get(mA.id).title, "their title, not yours", "while the mirror records what the server says");
  $("#bRevert").onclick();
  closeEditor();

  console.log("-- a row both queries miss is caught by the count --");
  var mLost = clone(DB[DB.length - 1]);
  mLost.id = DB.reduce(function (m, r) { return Math.min(m, r.id); }, 1e9) - 1;
  mLost.last_modified_at_utc = "2001-01-01 00:00:00";
  mLost.kind = "mirror_probe"; mLost.title = "invisible to both filters";
  DB.push(mLost);
  mR = await deltaSync();
  ok(mR.reload, "the sync admits it cannot vouch for the mirror");
  await bootSync();
  await settle(20);
  ok(st.byId.has(mLost.id), "and the full load that follows finds the row");
  eq(mem.rows.size, DB.length, "and rewrites the mirror whole");

  console.log("-- a mirror is only ever read back by the journal it came from --");
  var mBase = cfg.base;
  cfg.base = "https://another.journal.example";
  ok(!(await mirrorPaint()), "another server's page does not boot into this one");
  cfg.base = mBase;
  ok(await mirrorPaint(), "while its own still does");
  mA = st.byId.get(mA.id);           // a repaint hands out fresh row objects

  console.log("-- against a server without /dump the sync pages instead --");
  DUMP_ON = false;
  dumpMissing = false;
  dbFind(mA.id).content = "edited against an old server";
  dbFind(mA.id).last_modified_at_utc = "2099-12-01 00:00:04";
  mR = await deltaSync();
  await settle(4);
  ok(!mR.error && !mR.reload, "the sync still works");
  eq(mA.content, "edited against an old server", "and lands the edit");
  ok(dumpMissing, "having learned, once, that /dump is not there");
  DUMP_ON = true;
  dumpMissing = false;

  console.log("-- offline, the boot shows what the device holds --");
  var mFetch = fetch;
  fetch = function () { return Promise.reject(new Error("Failed to fetch")); };
  st.all = []; st.byId = new Map();
  await mirrorPaint();
  await bootSync();
  await settle(6);
  eq(st.all.length, DB.length, "the whole mirror stays on screen");
  has($("#hstat").textContent, "offline", "the header says offline");
  ok($("#hRetry"), "with a Retry");
  has($("#toast").textContent, "showing what this device holds", "and the toast says what is shown");
  fetch = mFetch;
  click($("#hRetry"));
  await settle(10);
  ok(!$("#hstat").textContent.match(/offline/), "Retry syncs once the server is back");
  hideToast();

  // put everything back the way it was found: the fixture rows, the paged
  // sweep the rest of the suite was written against, and no mirror
  DB.splice(DB.indexOf(dbFind(mC.id)), 1);
  DB.splice(DB.indexOf(dbFind(mLost.id)), 1);
  Object.assign(dbFind(mA.id), keepA);
  Object.assign(dbFind(mB.id), keepB);
  DUMP_ON = false;
  dumpMissing = false;
  mirrorStore = savedStore;
  mirror.mark = ""; mirror.maxId = 0;
  st.all = []; st.byId = new Map();
  await loadAll();
  await settle(30);
  eq(st.all.length, DB.length, "the journal is back to the fixture");

  console.log("-- the search says so while the bodies are still coming --");
  st.bodies = 7;
  $("#scope").value = "both";
  $("#q").value = "log";
  refresh();
  has($("#qnote").textContent, "content matches may be missing", "a content search warns it is partial");
  st.bodies = 0;
  clearFilters();
  $("#scope").value = "both";

  console.log("-- served from /ui, the pwa sidecars simply 404 --");
  eq(location.pathname, "/", "harness serves from the root");
  ok(true, "sw registration is wrapped in catch(); a 404 manifest is silent");

  console.log("-- the left columns fold down to a rail --");
  closeEditor();
  runTimers();
  clearFilters();
  eq(document.body.dataset.side, "on", "the filters column starts open");
  eq(document.body.dataset.list, "on", "so does the entries column");
  $("#list").scrollTop = 140;
  click($("#bListHide"));
  eq(document.body.dataset.list, "off", "the fold button folds the list away");
  eq($("#bListHide").getAttribute("aria-expanded"), "false", "and announces it");
  ok(st.view.length > 0 && $("#list").querySelectorAll(".item").length > 0,
     "the rows stay rendered behind the rail");
  click($("#listrail"));
  eq(document.body.dataset.list, "on", "the rail brings the column back");
  eq($("#list").scrollTop, 140, "carrying the scroll position across the fold");
  click($("#bSideHide"));
  eq(document.body.dataset.side, "off", "the filters fold the same way");
  var lay = JSON.parse(localStorage.getItem("lcars.layout"));
  eq(lay.side, false, "the choice is remembered");
  eq(lay.list, true, "one column at a time");
  key("1");
  eq(document.body.dataset.side, "on", "1 toggles the filters column");
  key("2");
  eq(document.body.dataset.list, "off", "2 toggles the entries column");
  key("2");
  eq(document.body.dataset.list, "on", "and back again");
  ok(key("1").defaultPrevented, "the digits are claimed, not typed through");

  console.log("-- on a phone 1 means the drawer, and 2 means nothing --");
  TEST.mobile = true;
  closeDrawer();
  key("1");
  eq(document.body.dataset.drawer, "on", "1 opens the filter drawer instead");
  key("1");
  eq(document.body.dataset.drawer, "off", "and closes it");
  var wasList = document.body.dataset.list;
  key("2");
  eq(document.body.dataset.list, wasList, "there is no list column to fold");
  TEST.mobile = false;

  console.log("-- focus mode gives the open entry the window --");
  closeOv();          // Esc belongs to any open dialog first
  closeEditor();
  runTimers();
  eq(document.body.dataset.focus, "off", "off to begin with");
  key("f");
  eq(document.body.dataset.focus, "off", "f does nothing with no entry open");
  select(st.view[0].id);
  runTimers();
  key("f");
  eq(document.body.dataset.focus, "on", "f turns it on for the open entry");
  eq($("#bFocus").getAttribute("aria-pressed"), "true", "the toggle reads as pressed");
  ok($("#bFocus").classList.contains("on"), "and is lit");
  key("Escape");
  eq(document.body.dataset.focus, "off", "Esc leaves focus mode first");
  eq(document.body.dataset.pane, "edit", "without closing the entry");
  key("Escape");
  eq(document.body.dataset.pane, "list", "the next Esc closes it");
  select(st.view[0].id);
  runTimers();
  click($("#bFocus"));
  eq(document.body.dataset.focus, "on", "the header button toggles it too");
  click($("#bFocus"));
  eq(document.body.dataset.focus, "off", "both ways");
  click($("#bFocus"));
  closeEditor();
  runTimers();
  eq(document.body.dataset.focus, "off", "closing the entry lifts focus mode");
  ok(localStorage.getItem("lcars.layout").indexOf("focus") < 0,
     "and it is never written to the remembered layout");

  console.log("-- the [[links]] are read as a page graph --");
  var keepAll = st.all, keepBodies = st.bodies;
  st.bodies = 0;
  st.all = [                                   // id desc, the way st.all always is
    { id: 6, kind: "personal_log", deleted: 0, content: "[[Alpha]]",
      title: "a dictated log whose own first sentence became its title, much too long to be a page name" },
    { id: 5, kind: "page", title: "Zeta", content: "[[Alpha]]", deleted: 1 },
    { id: 4, kind: "logseq_journal", title: "2026-09-02", content: "[[Alpha]] again", deleted: 0 },
    { id: 3, kind: "logseq_journal", title: "2026-09-01", content: "[[Alpha]] and [[Delta]]", deleted: 0 },
    { id: 2, kind: "page", title: "Beta", content: "back to [[Alpha]]", deleted: 0 },
    { id: 1, kind: "page", title: "Alpha", content: "[[Beta]] twice: [[Beta]]. also [[Gamma]], and [[Alpha]]",
      deleted: 0 },
  ];
  var g = graphBuild(false);
  var N = function (lc) { return g.nodes.filter(function (p) { return p.lc === lc; })[0]; };
  eq(g.nodes.length, 3, "three pages take part once the days are left out");
  eq(g.edges.length, 3, "and three distinct links join them");
  eq(N("alpha").out, 3, "a page's out-count counts every link it writes");
  eq(N("alpha").into, 1, "and its in-count every link written to it");
  eq(g.edges.filter(function (e) { return e.t.lc === "beta"; })[0].w, 2,
     "the same link written twice is one edge of weight two");
  ok(!N("alpha").day && !N("2026-09-01"), "a journal day is not a page here");
  ok(!N("delta"), "and nothing only a day links to comes with it");
  ok(!N("zeta"), "a deleted entry writes no links");
  eq(N("alpha").id, 1, "a page an entry carries the title of knows that entry");
  eq(N("alpha").kind, "page", "and its kind, which is the colour it is drawn in");
  eq(N("gamma").id, 0, "a page nobody has written yet has no entry");
  ok(!g.edges.some(function (e) { return e.s === e.t; }), "a page never links to itself");
  ok(N("alpha").adj.indexOf(N("gamma")) >= 0 && N("gamma").adj.indexOf(N("alpha")) >= 0,
     "and a link is walkable from either end of it");
  ok(!g.nodes.some(function (p) { return p.name.length > 60; }),
     "a dictated log's own first sentence is prose, not a page name");

  var gd = graphBuild(true);
  ok(gd.nodes.length > g.nodes.length, "the days bring their own pages in");
  ok(gd.nodes.filter(function (p) { return p.lc === "2026-09-01"; })[0].day,
     "and are marked as days");
  eq(gd.nodes.filter(function (p) { return p.lc === "alpha"; })[0].into, 3,
     "which is where most of the links to a busy page come from");
  ok(gd.nodes.filter(function (p) { return p.lc === "delta"; })[0], "a day-only page appears too");
  st.bodies = 4;
  ok(graphBuild(false).partial, "a graph built before the bodies land says so");
  st.bodies = 0;

  console.log("-- the layout settles without falling apart --");
  graphSeed(g);
  ok(g.nodes.every(function (p) { return isFinite(p.x) && isFinite(p.y); }), "the seed is finite");
  for (var gi = 0, ga = 1; gi < 60; gi++, ga *= 0.96) graphTick(g, ga);
  ok(g.nodes.every(function (p) { return isFinite(p.x) && isFinite(p.y); }),
     "and so is everything the simulation does to it");
  var apart = true;
  for (var a1 = 0; a1 < g.nodes.length; a1++)
    for (var a2 = a1 + 1; a2 < g.nodes.length; a2++)
      if (Math.hypot(g.nodes[a1].x - g.nodes[a2].x, g.nodes[a1].y - g.nodes[a2].y) < 5) apart = false;
  ok(apart, "no two pages end up on the same spot");
  var pinned = g.nodes[0], px = pinned.x, py = pinned.y;
  pinned.pin = true;
  graphTick(g, 1);
  ok(pinned.x === px && pinned.y === py, "a page being dragged stays where it is put");
  pinned.pin = false;

  console.log("-- the graph view over the real journal --");
  st.all = keepAll;
  st.bodies = keepBodies;
  closeOv();
  closeEditor();
  key("v");
  ok($("#ov").classList.contains("on"), "v opens the graph");
  ok($("#gcanvas"), "with a canvas to draw on");
  ok(gv.open && gv.data && gv.data.nodes.length > 0,
     "built from the journal in memory (" + gv.data.nodes.length + " pages)");
  has($("#gnote").textContent, "pages", "the frame says how much is in it");
  ok(gv.data.nodes.every(function (p) { return !p.day; }), "journal days stay out until asked for");
  ok(gv.data.edges.every(function (e) {
    return gv.data.nodes.indexOf(e.s) >= 0 && gv.data.nodes.indexOf(e.t) >= 0;
  }), "every link joins two pages that are actually drawn");
  // this fixture is the newest slice of the journal and carries no day pages of
  // its own, so what is checked here is the rebuild; the days themselves are
  // covered by the fixture above, which has them
  var wasNode = gv.data.nodes[0], before = gv.data.nodes.length;
  $("#gdays").checked = true;
  change($("#gdays"));
  ok(gv.days, "the checkbox lets the days in");
  ok(gv.data.nodes[0] !== wasNode && gv.data.nodes.length >= before,
     "and the graph is rebuilt around them");
  $("#gdays").checked = false;
  change($("#gdays"));
  ok(!gv.days && gv.data.nodes.every(function (p) { return !p.day; }),
     "unchecking it puts them back out");

  console.log("-- picking a page narrows the picture to its neighbourhood --");
  ok(gv.view === gv.data, "with nothing picked the whole journal is drawn");
  var hub = gv.data.nodes[0];                  // the busiest page: the most to show
  var ring = [];
  for (var hi = 0; hi < hub.adj.length; hi++)
    if (ring.indexOf(hub.adj[hi]) < 0) ring.push(hub.adj[hi]);
  ok(ring.length > 0, "the busiest page is joined to something (" + ring.length + " pages)");
  graphSelect(hub);
  eq(gv.depth, 1, "one link out is where the depth starts");
  eq(gv.view.nodes.length, ring.length + 1, "so the picture is that page and what it is joined to");
  ok(gv.view.nodes.indexOf(hub) >= 0, "the page itself included");
  ok(gv.view.nodes.every(function (p) { return p === hub || ring.indexOf(p) >= 0; }),
     "and nothing that is not joined to it");
  ok(gv.view.edges.length > 0 && gv.view.edges.every(function (e) {
    return gv.view.nodes.indexOf(e.s) >= 0 && gv.view.nodes.indexOf(e.t) >= 0;
  }), "every link drawn joins two pages that are drawn");
  has($("#gnote").textContent, "of " + gv.data.nodes.length + " pages",
      "the frame says how much of the journal is left out");
  has($("#gnote").textContent, "depth 1", "and how far out it reached");
  ok(graphHit(-9999, -9999) === null, "nothing is hit outside the picture");

  $("#gdepth").value = "2";
  change($("#gdepth"));
  eq(gv.depth, 2, "the depth picker reaches further");
  var d2 = gv.view.nodes;
  ok(d2.length >= ring.length + 1, "which can only bring more pages in (" + d2.length + ")");
  ok(d2.indexOf(hub) >= 0 && ring.every(function (p) { return d2.indexOf(p) >= 0; }),
     "and keeps everything one link out already had");
  $("#gdepth").value = "0";
  change($("#gdepth"));
  ok(gv.view === gv.data, "\"all\" is the whole journal again, selection and all");
  $("#gdepth").value = "1";
  change($("#gdepth"));
  ok(gv.view !== gv.data, "and the neighbourhood comes back with the depth");
  graphSelect(null);
  ok(gv.view === gv.data, "a click on the canvas's empty space widens it out again");
  ok(!$("#gcard").classList.contains("on"), "and closes the card with it");

  console.log("-- and so does a word in the find box --");
  input($("#gq"), hub.name);
  ok(gv.view !== gv.data, "the find box filters the pages, not just the rings");
  ok(gv.view.nodes.some(function (p) { return p.lc.indexOf(gv.q) >= 0; }),
     "down to what matches it");
  ok(gv.view.nodes.every(function (p) {
    return p.lc.indexOf(gv.q) >= 0 ||
           p.adj.some(function (n) { return n.lc.indexOf(gv.q) >= 0; });
  }), "and what a match is joined to");
  input($("#gq"), "zzz nothing is called this");
  eq(gv.view.nodes.length, 0, "a word nothing matches leaves nothing to draw");
  ok($("#gempty").classList.contains("on"), "so the frame says as much");
  has($("#gempty").textContent, "no page matches", "in those words");
  input($("#gq"), "");
  ok(gv.view === gv.data && !$("#gempty").classList.contains("on"),
     "and clearing it brings the journal back");

  var top = gv.data.nodes.filter(function (p) { return p.id && !p.day; })[0];
  input($("#gq"), top.name);
  eq(gv.q, top.lc, "the find box takes a name");
  eq(graphFind(gv.q).lc, top.lc, "and Enter's target is that page");
  graphSelect(graphFind(gv.q));
  ok($("#gcard").classList.contains("on"), "picking a page opens its card");
  has($("#gcard").textContent, top.name, "with the name in full");
  has($("#gcard").textContent, "#" + top.id, "and the entry behind it");
  eq($("#gopen").textContent, "Open", "which can be opened");

  console.log("-- following a page out of the graph is following its [[link]] --");
  click($("#gopen"));
  runTimers();
  ok(!$("#ov").classList.contains("on"), "the graph closes behind it");
  ok(!gv.open && !gv.data, "and stops simulating");
  eq($("#q").value, top.name, "the search is left holding the page name");
  eq(st.sel && st.sel.id, top.id, "with its entry open");
  clearFilters();
  closeEditor();

  openGraph();
  key("Escape");
  ok(!$("#ov").classList.contains("on"), "Escape closes the graph too");
  ok(!gv.open, "leaving nothing running behind it");

  /* ---------- multi-word AND search ---------- */
  console.log("\n-- several words all have to match --");
  clearFilters();
  closeEditor();
  // a row of our own, so the words are known rather than hoped for
  var andRow = st.all[0];
  var andWas = { c: andRow.content, t: andRow.title };
  andRow.title = "zebra quokka";
  andRow.content = "the zebra sleeps · a quokka waves · narwhal";
  var otherRow = st.all[1];
  var otherWas = { c: otherRow.content, t: otherRow.title };
  otherRow.title = "zebra only";
  otherRow.content = "the zebra sleeps alone";

  input($("#q"), "zebra quokka");
  refresh();
  ok(st.matcher && st.matcher.res.length === 2, "two words make two patterns");
  ok(st.view.indexOf(andRow) >= 0, "the row carrying both words matches");
  ok(st.view.indexOf(otherRow) < 0, "the row carrying only one does not");

  input($("#q"), "quokka zebra");
  refresh();
  ok(st.view.indexOf(andRow) >= 0, "the words may come in any order");

  input($("#q"), "narwhal");
  refresh();
  eq(st.matcher.res.length, 1, "one word is still one pattern");
  ok(st.view.indexOf(andRow) >= 0, "and still matches");

  console.log("-- a quoted phrase is searched whole --");
  input($("#q"), '"zebra sleeps"');
  refresh();
  eq(st.matcher.res.length, 1, "quotes make one pattern");
  ok(st.view.indexOf(andRow) >= 0 && st.view.indexOf(otherRow) >= 0,
     "both rows carry the phrase");
  input($("#q"), '"quokka zebra"');
  refresh();
  ok(st.view.indexOf(andRow) < 0, "a phrase in the wrong order matches nothing");

  console.log("-- marking, snippets and the other modes --");
  var marked = mark("the zebra and the quokka");
  input($("#q"), "zebra quokka");
  refresh();
  marked = mark("the zebra and the quokka");
  eq((marked.match(/<mark>/g) || []).length, 2, "both words are marked");
  has(marked, "<mark>zebra</mark>", "the first by name");
  has(marked, "<mark>quokka</mark>", "the second too");
  // overlapping terms must not nest one <mark> inside another
  input($("#q"), "zeb ebra");
  refresh();
  var over = mark("zebra");
  eq((over.match(/<mark>/g) || []).length, 1, "overlapping hits merge into one mark");
  has(over, "<mark>zebra</mark>", "covering the whole run");

  input($("#q"), "quokka");
  refresh();
  has(snippet(andRow), "quokka", "the snippet excerpts around the hit");

  input($("#q"), "/zebra.*quokka/");
  refresh();
  eq(st.matcher.res.length, 1, "a slash regex stays one pattern");
  ok(st.view.indexOf(andRow) >= 0, "and still finds the row");
  setSeg("#mode", "regex");
  input($("#q"), "zebra (sleeps|runs)");
  refresh();
  eq(st.matcher.res.length, 1, "regex mode is never split on spaces");
  ok(st.view.indexOf(andRow) >= 0, "so its spaces still mean what regex says");
  setSeg("#mode", "text");

  $("#fInv").checked = true;
  input($("#q"), "zebra quokka");
  refresh();
  ok(st.view.indexOf(andRow) < 0, "-v drops the row that matches every word");
  ok(st.view.indexOf(otherRow) >= 0, "and keeps the one that does not");
  $("#fInv").checked = false;

  $("#fWord").checked = true;
  input($("#q"), "zeb quokka");
  refresh();
  ok(st.view.indexOf(andRow) < 0, "\\b applies to each word (zeb is not a word here)");
  $("#fWord").checked = false;

  input($("#q"), "   ");
  refresh();
  ok(!st.matcher, "a box holding only spaces is not a search");

  andRow.content = andWas.c; andRow.title = andWas.t;
  otherRow.content = otherWas.c; otherRow.title = otherWas.t;
  clearFilters();

  /* ---------- relevance ranking ---------- */
  console.log("\n-- the title answers first --");
  clearFilters();
  closeEditor();
  // four rows carrying the same word in four different places, so the tiers are
  // the only thing that can be ordering them
  var relWas = [];
  var relRows = [st.all[0], st.all[1], st.all[2], st.all[3]];
  relRows.forEach(function (e) { relWas.push({ t: e.title, c: e.content, d: e.deleted }); e.deleted = 0; });
  var rExact = relRows[0], rOpens = relRows[1], rInside = relRows[2], rBody = relRows[3];
  rExact.title  = "radu";                  rExact.content  = "nothing to see";
  rOpens.title  = "Radu Ionescu";           rOpens.content  = "nothing to see";
  rInside.title = "Andrei Radu-Ionescu";   rInside.content = "nothing to see";
  rBody.title   = "someone else entirely";   rBody.content   = "met radu on tuesday";

  input($("#q"), "radu");
  refresh();
  eq(relevance(rExact, st.matcher), 3, "the title that IS the query scores top");
  eq(relevance(rOpens, st.matcher), 2, "a title opening with it comes next");
  eq(relevance(rInside, st.matcher), 1, "a title carrying it further in, next");
  eq(relevance(rBody, st.matcher), 0, "a content-only hit scores nothing");
  var at = function (e) { return st.view.indexOf(e); };
  ok(at(rExact) >= 0 && at(rBody) >= 0, "all four rows matched");
  ok(at(rExact) < at(rOpens), "the exact title outranks the one that opens with it");
  ok(at(rOpens) < at(rInside), "which outranks the one carrying it further in");
  ok(at(rInside) < at(rBody), "and every title beats a content-only hit");
  ok(st.ranked, "the header says the list is ranked");
  has($("#count").innerHTML, "title matches first", "and says so in words");
  ok(!st.dayOf, "a ranked list drops the day dividers");

  console.log("-- the sort still decides inside a tier --");
  // two rows in the same tier: the chosen sort, not the ranking, orders them
  var tieA = rOpens, tieB = rInside;
  tieB.title = "Radu Popescu";             // both now open with the word
  input($("#q"), "radu");
  refresh();
  eq(relevance(tieA, st.matcher), relevance(tieB, st.matcher), "same tier");
  // whatever created ↓ would have said about the pair is what the tier must say
  var newer = (function (a, b) {
    return a.created_at_utc > b.created_at_utc ? a
         : a.created_at_utc < b.created_at_utc ? b
         : (a.id > b.id ? a : b);
  })(tieA, tieB);
  ok(at(newer) < at(newer === tieA ? tieB : tieA),
     "created ↓ still orders the pair inside the tier");
  tieB.title = "Andrei Radu-Ionescu";

  console.log("-- ranking knows when to stay out of the way --");
  $("#scope").value = "content";
  input($("#q"), "radu");
  refresh();
  ok(!st.ranked, "a content-only search is not reordered by title");
  ok(st.dayOf, "so its day dividers survive");
  $("#scope").value = "all";

  $("#fInv").checked = true;
  input($("#q"), "radu");
  refresh();
  ok(!st.ranked, "an inverted search has nothing to rank");
  $("#fInv").checked = false;

  input($("#q"), "zzzz-one-tier-only-zzzz");
  refresh();
  ok(!st.ranked, "and a single tier orders nothing");

  console.log("-- exactness reads the whole query --");
  rExact.title = "Andrei Radu";
  input($("#q"), "andrei radu");
  refresh();
  eq(relevance(rExact, st.matcher), 3, "several words are exact in the order typed");
  input($("#q"), "radu andrei");
  refresh();
  ok(relevance(rExact, st.matcher) < 3, "and only in that order");
  input($("#q"), "/^radu/");
  refresh();
  ok(relevance(rOpens, st.matcher) >= 2, "a slash regex ranks too");
  input($("#q"), "RADU");
  refresh();
  eq(relevance(rOpens, st.matcher), 2, "case is ignored unless Aa says otherwise");
  $("#fCase").checked = true;
  input($("#q"), "RADU");
  refresh();
  eq(relevance(rOpens, st.matcher), 0, "with Aa on, the wrong case is no title match");
  $("#fCase").checked = false;

  relRows.forEach(function (e, i) {
    e.title = relWas[i].t; e.content = relWas[i].c; e.deleted = relWas[i].d;
  });
  clearFilters();

  /* ---------- backlinks ---------- */
  console.log("\n-- what links here --");
  clearFilters();
  closeEditor();
  var target = st.all[0], from1 = st.all[1], from2 = st.all[2], away = st.all[3];
  var blWas = [target.title, from1.content, from2.content, away.content,
               from1.deleted, from2.deleted, away.deleted];
  target.title = "Quokka Sanctuary";
  from1.content = "went to the [[Quokka Sanctuary]] today";
  from2.content = "see [[quokka sanctuary]] — lower case, same page";
  away.content = "no links here at all";
  from1.deleted = 0; from2.deleted = 0; away.deleted = 0;

  var bl = backlinks(target);
  eq(bl.length, 2, "both linking entries are found");
  ok(bl.indexOf(from1) >= 0 && bl.indexOf(from2) >= 0, "by name, whatever the case");
  ok(bl.indexOf(away) < 0, "an entry that links nothing is left out");
  ok(bl.indexOf(target) < 0, "and an entry never backlinks itself");

  from2.deleted = 1;
  eq(backlinks(target).length, 1, "a deleted entry stops counting");
  from2.deleted = 0;

  eq(backlinks({ title: "" }).length, 0, "an untitled entry has no backlinks");
  eq(backlinks({ title: "nothing links to this name at all" }).length, 0,
     "nor does a name nobody wrote");

  console.log("-- and the reader shows them --");
  select(target.id);
  await drainExtras();
  has($("#rd_back").innerHTML, "Linked from · 2", "the reader heads the section with a count");
  has($("#rd_back").innerHTML, "#" + from1.id, "listing the entry that links here");
  var blrow = $("#rd_back").querySelector(".blrow");
  ok(blrow, "each backlink is a row");
  click(blrow);
  await settle(4);
  eq(st.sel && st.sel.id, Number(blrow.dataset.id), "clicking one opens it");

  select(away.id);
  eq($("#rd_back").innerHTML, "", "another entry's links are gone at once, not a frame later");
  await drainExtras();
  eq($("#rd_back").innerHTML, "", "an entry nothing links to shows no section");

  target.title = blWas[0]; from1.content = blWas[1]; from2.content = blWas[2];
  away.content = blWas[3];
  from1.deleted = blWas[4]; from2.deleted = blWas[5]; away.deleted = blWas[6];
  closeEditor();

  /* ---------- outline folding ---------- */
  console.log("\n-- folding an outline branch --");
  var md = mdRender("- parent\n  - child one\n  - child two\n- leaf\n");
  has(md, 'class="foldable"', "a branch parent is marked foldable");
  has(md, "fbtn", "and carries a fold button");
  eq((md.match(/fbtn/g) || []).length, 1, "only the parent gets one");
  has(md, "<li>leaf</li>", "a leaf item is left exactly as it was");
  ok(mdRender("- one\n- two\n").indexOf("fbtn") < 0, "a flat list has nothing to fold");

  var deep = mdRender("- a\n  - b\n    - c\n");
  eq((deep.match(/fbtn/g) || []).length, 2, "every parent in a chain is foldable");

  // the click handler works on whatever rendered it, so drive it through the reader
  var fold = st.all.find(function (e) { return e !== target; });
  var foldWas = fold.content;
  fold.content = "- parent\n  - child one\n  - child two\n";
  select(fold.id);
  await settle(6);
  var li = $("#rd_content").querySelector("li.foldable");
  ok(li, "the reader renders the foldable item");
  var btn = li.querySelector(".fbtn");
  ok(btn, "with its button");
  eq(btn.getAttribute("aria-expanded"), "true", "open to begin with");
  click(btn);
  ok(li.classList.contains("fold"), "clicking folds the branch");
  eq(btn.getAttribute("aria-expanded"), "false", "which is announced");
  eq(li.dataset.n, "2", "and says how many items it is holding");
  has(btn.getAttribute("aria-label"), "Unfold", "the label offers the way back");
  click(btn);
  ok(!li.classList.contains("fold"), "a second click unfolds it");
  eq(btn.getAttribute("aria-expanded"), "true", "announced again");
  ok(!li.dataset.n, "and the count goes away with the fold");

  fold.content = foldWas;
  closeEditor();
  clearFilters();

  /* ---------- the staleness probe ---------- */
  console.log("\n-- the probe notices the other writers --");
  clearFilters();
  closeEditor();
  hideToast();
  ok(served, "a full load recorded what the server looked like");
  eq(served.count, DB.length, "which is the row count it answered with");

  await probeServer();
  await settle(4);
  eq($("#toast").className, "", "an unchanged server says nothing");

  // somebody else writes a row — the CLI, a cron job, a second browser
  var outside = JSON.parse(JSON.stringify(DB[0]));
  outside.id = 999999;
  outside.created_at_utc = "2099-06-06 06:06:06";
  outside.title = "written by somebody else";
  DB.push(outside);

  await probeServer();
  await settle(4);
  has($("#toast").textContent, "1 new entry", "a new row is reported");
  ok($("#toast").querySelector(".tact"), "with a way to act on it");
  eq(served.count, DB.length, "and the new state is taken as the baseline");

  hideToast();
  await probeServer();
  await settle(4);
  eq($("#toast").className, "", "the same change is not reported twice");

  console.log("-- and it keeps out of the way of an unsaved entry --");
  DB.push(JSON.parse(JSON.stringify(outside)));
  DB[DB.length - 1].id = 999998;
  select(st.all[0].id);
  await settle(4);
  input($("#e_head"), "half a thought");
  ok(document.body.classList.contains("dirty"), "the form is dirty");
  hideToast();
  await probeServer();
  await settle(4);
  eq($("#toast").className, "", "a dirty form is never interrupted");
  var stale = served.count;
  $("#bRevert").onclick();            // back to clean without touching the server
  ok(!document.body.classList.contains("dirty"), "reverted");
  await probeServer();
  await settle(4);
  has($("#toast").textContent, "new", "and the news keeps until it can be told");
  ok(served.count !== stale, "the baseline moves only once it has been reported");

  // put the fixture back the way it was found
  DB.pop(); DB.pop();
  served = { count: DB.length, newest: served.newest };
  hideToast();
  closeEditor();
  clearFilters();

  /* ---------- the cheap catch-up ---------- */
  console.log("\n-- pull to sync: nothing new costs one page --");
  hideToast();
  var syReqs = function () { return TEST.fetches.length; };
  var syWas = syReqs();
  var syR = await syncNew();
  await settle(4);
  eq(syR.added, 0, "an unchanged server adds nothing");
  eq(syR.freshened, SYNC_TOUCH, "but the newest few are re-read anyway");
  ok(syReqs() - syWas <= 2, "for one page and one /stats (" + (syReqs() - syWas) + " requests)");
  // syncNew() is silent; the gesture is what speaks, through syncReport()
  syncReport(syR);
  has($("#toast").textContent, "up to date", "and it says so");

  console.log("-- the newest entries are re-read for their latest content --");
  hideToast();
  var syTop = st.all[0];
  dbFind(syTop.id).content = "rewritten by the CLI while the tab sat open";
  await syncNew();
  await settle(4);
  has(syTop.content, "rewritten by the CLI", "the top row picked up the new body");
  var syDeep = st.all[SYNC_TOUCH + 4], syDeepWas = syDeep.content;
  dbFind(syDeep.id).content = "this one is nobody's business";
  await syncNew();
  await settle(4);
  eq(syDeep.content, syDeepWas, "a row well below the boundary is left alone");

  console.log("-- new rows arrive, and only the new ones --");
  hideToast();
  var syBefore = st.all.length, syMax = st.all[0].id;
  for (var syI = 1; syI <= 3; syI++) {
    var syNew = JSON.parse(JSON.stringify(DB[0]));
    syNew.id = syMax + syI; syNew.deleted = 0; syNew.kind = "sync_probe";
    syNew.title = "arrived while you were reading " + syI;
    syNew.created_at_utc = "2099-07-0" + syI + " 07:07:07";
    DB.push(syNew);
  }
  syWas = syReqs();
  syR = await syncNew();
  await settle(6);
  eq(syR.added, 3, "the three new rows came down");
  eq(st.all.length, syBefore + 3, "and nothing else did");
  ok(syReqs() - syWas <= 2, "still one page (" + (syReqs() - syWas) + " requests)");
  eq(st.all[0].id, syMax + 3, "newest first, ahead of everything held");
  eq(st.all[3].id, syMax, "with the old top row right behind them");
  var syDesc = true;
  for (var syD = 1; syD < st.all.length; syD++) if (st.all[syD - 1].id < st.all[syD].id) syDesc = false;
  ok(syDesc, "st.all is still a contiguous id-desc prefix");
  ok(!needsBody(st.all[0]), "a synced row arrives with its body");
  syncReport(syR);
  has($("#toast").textContent, "3 new entries", "and the count is announced");
  ok(kindRank.kinds.indexOf("sync_probe") >= 0, "a kind nobody had seen joins the filter");

  console.log("-- an unsaved entry is never overwritten under the writer --");
  hideToast();
  var syHeld = st.all[1], syHeldTitle = syHeld.title;
  select(syHeld.id);
  await settle(6);
  setRead(false);
  input($("#e_head"), "mid-sentence");
  ok(document.body.classList.contains("dirty"), "the form is dirty");
  dbFind(syHeld.id).title = "their title, not yours";
  await syncNew();
  await settle(6);
  eq(syHeld.title, syHeldTitle, "the held row kept what the editor is holding");
  eq($("#e_head").value, "mid-sentence", "and the form still has the unsaved words");
  $("#bRevert").onclick();
  closeEditor();
  // now that it is clean, the same sync does land it
  await syncNew();
  await settle(6);
  eq(syHeld.title, "their title, not yours", "and takes it once there is nothing to lose");

  console.log("-- a pull past the top runs it; a nudge does not --");
  hideToast();
  var syList = $("#list"), syInd = $("#pull");
  var syDrag = function (dy) {
    dispatch(syList, "touchstart", { touches: [{ clientX: 100, clientY: 300 }] });
    dispatch(syList, "touchmove", { touches: [{ clientX: 100, clientY: 300 + dy }] });
  };
  var syTravel = function () {
    return parseFloat($("#listshift").style.transform.replace(/[^0-9.-]/g, "")) || 0;
  };
  syDrag(20);
  ok(!syInd.classList.contains("armed"), "20px is a nudge, not a pull");
  has($("#pulltxt").textContent, "pull", "though the indicator has come into view");
  eq(syTravel(), 20, "and the rows came down with it, one pixel per pixel");
  dispatch(syList, "touchend", { changedTouches: [{ clientX: 100, clientY: 320 }] });
  await settle(4);
  eq($("#toast").className, "", "and letting go of it syncs nothing");

  var syPulled = JSON.parse(JSON.stringify(DB[0]));
  syPulled.id = st.all[0].id + 1; syPulled.deleted = 0; syPulled.kind = "sync_probe";
  syPulled.title = "pulled down for"; syPulled.created_at_utc = "2099-08-08 08:08:08";
  DB.push(syPulled);
  syDrag(160);
  ok(syInd.classList.contains("armed"), "a long pull arms");
  has($("#pulltxt").textContent, "release", "and says what releasing will do");
  ok(syTravel() > 64 && syTravel() <= 96,
     "the travel goes stiff past the arming point and is capped (" + syTravel() + "px)");
  dispatch(syList, "touchend", { changedTouches: [{ clientX: 100, clientY: 460 }] });
  await settle(10);
  has($("#toast").textContent, "1 new entry", "releasing fetched the new row");
  eq(st.all[0].id, syPulled.id, "which is now at the top of the list");
  eq($("#listshift").style.transform, "translateY(0px)", "and the list sprang back to its top");

  console.log("-- a pull from halfway down the list is a scroll --");
  hideToast();
  syList.scrollTop = 500;
  syDrag(160);
  ok(!syInd.classList.contains("armed"), "the gesture was never claimed");
  dispatch(syList, "touchend", { changedTouches: [{ clientX: 100, clientY: 460 }] });
  await settle(4);
  eq($("#toast").className, "", "and nothing was fetched");
  syList.scrollTop = 0;

  console.log("-- a journal that has moved on asks for a real reload --");
  hideToast();
  var syKept = st.all.length, syKeptTop = st.all[0].id, syFlood = 0;
  for (var syF = 1; syF <= SYNC_MAX + 20; syF++) {
    var syFr = JSON.parse(JSON.stringify(DB[0]));
    syFr.id = syKeptTop + syF; syFr.deleted = 0; syFr.kind = "flood";
    syFr.created_at_utc = "2099-09-09 09:09:09";
    DB.push(syFr); syFlood++;
  }
  syR = await syncNew();
  syncReport(syR);
  await settle(6);
  ok(syR.adrift, "the sweep gave up rather than guess");
  eq(st.all.length, syKept, "nothing was spliced in, so the list keeps its invariant");
  has($("#toast").textContent, "full reload", "and the honest answer is offered");
  eq($("#toast").querySelector(".tact").textContent, "Reload", "offered as a button");

  // the flood goes; the handful of rows that were legitimately synced stay, so
  // the fake database and the list still agree for everything that follows
  DB.length = DB.length - syFlood;
  served = { count: DB.length, newest: served.newest };
  hideToast();
  closeEditor();
  clearFilters();

  /* ---------- asking in the app's own voice ---------- */
  console.log("\n-- the themed confirm --");
  clearFilters();
  closeEditor();
  var answer = lcarsConfirm({ title: "Plain question", body: "<p>well?</p>", ok: "Yes" });
  await settle(2);
  ok($("#ov").classList.contains("on"), "the overlay opens");
  has($("#dlg").innerHTML, "Plain question", "carrying the question");
  ok($("#lcOk") && $("#lcNo"), "with both answers");
  click($("#lcOk"));
  eq(await answer, "true", "OK resolves true");
  ok(!$("#ov").classList.contains("on"), "and closes behind itself");

  answer = lcarsConfirm({ title: "Again", body: "" });
  await settle(2);
  click($("#lcNo"));
  eq(await answer, "false", "Cancel resolves false");

  answer = lcarsConfirm({ title: "Escaped", body: "" });
  await settle(2);
  key("Escape");
  eq(await answer, "false", "Escape answers no");
  ok(!$("#ov").classList.contains("on"), "leaving nothing open");

  answer = lcarsConfirm({ title: "Scrimmed", body: "" });
  await settle(2);
  closeOv();
  eq(await answer, "false", "and so does closing the overlay any other way");

  answer = lcarsConfirm({ title: "Dangerous", body: "", danger: true });
  await settle(2);
  ok($("#lcOk").classList.contains("danger"), "a destructive OK is marked");
  ok(document.activeElement === $("#lcNo"), "and the safe answer holds the focus");
  click($("#lcNo"));
  await answer;

  console.log("-- delete asks through it --");
  // a row with a kind: save() refuses a kindless one before it ever reaches a
  // dialog, and the fixture's first live row happens to be exactly that
  var victim = st.all.filter(function (e) { return !e.deleted && e.kind; })[0];
  select(victim.id);
  await settle(4);
  click($("#bDel"));
  await settle(2);
  has($("#dlg").innerHTML, "Delete this entry", "Delete opens the themed question");
  has($("#dlg").innerHTML, "#" + victim.id, "naming the entry");
  has($("#dlg").innerHTML, "deleted = 1", "and saying what a soft delete is");
  ok(await answerDialog(false), "which can be answered no");
  await settle(6);
  ok(!dbFind(victim.id).deleted, "answering no leaves the row alone");

  click($("#bDel"));
  ok(await answerDialog(true), "and yes");
  await settle(10);
  ok(dbFind(victim.id).deleted, "answering yes soft-deletes it");
  has($("#toast").textContent, "deleted #" + victim.id, "and says so");
  // put it back the way the suite found it
  await api("/entries/" + victim.id, { method: "PUT", body: { deleted: 0 } });
  await refetchInto(victim);
  hideToast();
  closeEditor();

  console.log("-- and so does a concurrent edit --");
  var row = st.all.filter(function (e) {
    return !e.deleted && e.kind && !needsBody(e);
  })[0];
  select(row.id);
  await settle(6);
  // somebody else writes the row we are holding
  var srv = dbFind(row.id);
  srv.title = "their title";
  srv.last_modified_at_utc = "2099-05-05 05:05:05";
  setRead(false);
  input($("#e_head"), "my title");
  var saving = save();
  await settle(4);
  has($("#dlg").innerHTML, "Changed on the server", "the conflict is a themed question");
  has($("#dlg").innerHTML, "they changed", "listing what they touched");
  has($("#dlg").innerHTML, "title", "which is the title");
  has($("#dlg").innerHTML, "both changed", "and naming the column in dispute");
  click($("#lcNo"));                        // "Load theirs"
  await saving;
  await settle(8);
  eq(row.title, "their title", "answering 'load theirs' takes the server's row");
  eq($("#e_head").value, "their title", "and the form shows it");
  ok(!document.body.classList.contains("dirty"), "with nothing left unsaved");

  // and the other way: overwrite
  srv.last_modified_at_utc = "2099-06-06 06:06:06";
  setRead(false);
  input($("#e_head"), "mine wins");
  saving = save();
  await settle(4);
  has($("#dlg").innerHTML, "Changed on the server", "asked again on the next clash");
  ok(await answerDialog(true), "answered Overwrite");
  await saving;
  await settle(8);
  eq(dbFind(row.id).title, "mine wins", "answering 'overwrite' sends the edit");

  // a clash found by a save on the way out asks after the move, about the row
  srv.last_modified_at_utc = "2099-07-07 07:07:07";
  srv.title = "theirs again";
  setRead(false);
  input($("#e_head"), "left behind");
  closeEditor();
  eq(document.body.dataset.pane, "list", "leaving does not wait for the clash");
  await settle(4);
  has($("#dlg").innerHTML, "Changed on the server", "the question comes after the move");
  click($("#lcNo"));                        // "Load theirs"
  await settle(8);
  eq(row.title, "theirs again", "load theirs lands on the row");
  ok(!away.size, "and nothing is owed");
  srv.last_modified_at_utc = "2099-08-08 08:08:08";
  select(row.id); setRead(false);
  input($("#e_head"), "left and kept");
  closeEditor();
  ok(await answerDialog(true), "and Overwrite, from the list");
  await settle(8);
  eq(dbFind(row.id).title, "left and kept", "sends the edit that left");

  console.log("-- the diff names only the columns in play --");
  var a = { kind: "k", title: "t", content: "c", value_int: 0, value_float: 0,
            done_bool: 0, deleted: 0, created_at_utc: "x" };
  var b2 = JSON.parse(JSON.stringify(a));
  b2.content = "theirs";
  var d1 = conflictDiff(a, b2, { title: "mine" });
  has(d1, "they changed", "their column is named");
  has(d1, "content", "by name");
  has(d1, "no column is in dispute", "a disjoint edit says so");
  var d2 = conflictDiff(a, b2, { content: "mine" });
  has(d2, "both changed", "an overlapping edit is called a dispute");
  eq(conflictDiff(a, JSON.parse(JSON.stringify(a)), {}), "", "and nothing at all draws nothing");

  hideToast();
  closeEditor();
  clearFilters();

  /* ---------- the task board ----------
     The markers live at the head of a bullet inside an ordinary entry, so the
     two things worth proving are that a marker is only read as one where it
     actually is one, and that the board hands over to the entry rather than
     pretending a task can be worked on in a dialog. */
  console.log("\n-- tasks: what counts as one --");
  ok(TASK_WORDS.indexOf("TODO") >= 0 && TASK_WORDS.indexOf("DONE") >= 0,
     "the markers are one list");
  ok(TASK_OPEN.indexOf("DONE") < 0, "DONE is not an open state");
  eq(TASK_LINE.test("- TODO ring the bank"), true, "a bulleted marker is a task");
  eq(TASK_LINE.test("TODO ring the bank"), true, "a bare one is too");
  eq(TASK_LINE.test("\t\t- DOING the thing"), true, "however deep it is indented");
  eq(TASK_LINE.test("I left the TODO marker in"), false, "mid-sentence it is prose");
  eq(TASK_LINE.test("- TODOS for later"), false, "and TODOS is a different word");
  eq(TASK_LINE.test("- TODO   "), false, "a marker with nothing after it is not a task");
  // the renderer and the board have to agree, or a task exists in one and not the other
  ok(TASK_RE.test("TODO ring the bank"), "the renderer reads the same markers");
  ok(TASK_WORDS.every(function (w) { return TASK_RE.test(w + " x"); }),
     "every marker on the list renders as one");

  console.log("-- tasks: the index --");
  // Open and finished task lines of the suite's own, in two kinds: the board,
  // its search (a word of five letters on an open line) and its kind row
  // below need them, and the journal's newest rows may carry none of one
  // sort. Taken out with the tap test's entry, at the end of the tasks.
  var tkPlanted = [
    await plant({ title: "Chores", content: "Chores\n- TODO replace the furnace filter\n- DONE sweep the porch" }),
    await plant({ kind: "work_log", title: "Build list",
                  content: "- TODO profile the renderer\n- LATER rewrite the shelving notes\n- DONE ship the patch" })];
  var ti = taskIndex();
  ok(ti.length >= 5, "the journal carries tasks (" + ti.length + " lines)");
  ok(taskIndex() === ti, "the index is cached");
  ok(ti.every(function (t) { return !t.e.deleted; }), "deleted entries hold no tasks");
  ok(ti.every(function (t) { return TASK_WORDS.indexOf(t.word) >= 0; }), "every row carries a marker");
  ok(ti.every(function (t) { return t.text.length > 0; }), "and text after it");
  // a body landing is exactly the thing that can add tasks
  st.bodyGen++;
  ok(taskIndex() !== ti, "a body landing drops the cached index");

  console.log("-- tasks: the board --");
  openTasks();
  await settle(3);
  ok($("#ov").classList.contains("on"), "the board opens");
  var open0 = taskRows("open");
  ok(open0.every(function (t) { return TASK_OPEN.indexOf(t.word) >= 0; }),
     "the open scope holds no finished tasks");
  // oldest first is the whole point: a board is a list of what has been rotting
  var ages = open0.map(function (t) { return t.e.created_at_utc; });
  ok(ages.every(function (v, i) { return !i || ages[i - 1] <= v; }),
     "open tasks climb out oldest first");
  var done0 = taskRows("done");
  ok(done0.every(function (t) { return TASK_SHUT.indexOf(t.word) >= 0; }),
     "the done scope holds only finished ones");
  var dAges = done0.map(function (t) { return t.e.created_at_utc; });
  ok(dAges.every(function (v, i) { return !i || dAges[i - 1] >= v; }),
     "finished ones read newest first, like the journal");
  eq(taskRows("all").length, taskIndex().length, "all means all of them");
  has($("#tkrows").innerHTML, 'class="task', "rows are painted by the renderer itself");
  has($("#tknote").textContent, "entries", "the note counts the entries behind the lines");

  console.log("-- tasks: the board hands over --");
  var tkr = $("#tkrows").querySelector(".tkrow");
  ok(tkr, "a row is there to click");
  var tkId = Number(tkr.dataset.id);
  click(tkr);
  await settle(3);
  ok(!$("#ov").classList.contains("on"), "clicking a task closes the board");
  eq(st.sel && st.sel.id, tkId, "and opens the entry the task lives in");

  console.log("-- tasks: the scope segment --");
  openTasks();
  await settle(3);
  click($("#tkscope").querySelector('[data-v="done"]'));
  await settle(2);
  eq(taskScope, "done", "the segment switches scope");
  ok($("#tkscope").querySelector('[data-v="done"]').classList.contains("on"),
     "and says which one it is on");
  click($("#tkscope").querySelector('[data-v="open"]'));
  await settle(2);
  closeOv();
  await settle(2);

  /* The board's own filter strip: a search read by the list's rules but asked
     of the task line only, and kind and period rows that are the page's own
     filters — so the board and the list behind it stay one question. */
  console.log("-- tasks: searching the board --");
  var kinds0 = st.kinds.slice(), qs0 = stateQS(false);
  openTasks();
  await settle(3);
  var all0 = taskRows("open");
  var probe = null;
  for (var tq = 0; tq < all0.length && !probe; tq++) {
    var wds = all0[tq].text.split(/\s+/).filter(function (w) { return /^[A-Za-z]{5,}$/.test(w); });
    if (wds.length) probe = wds[0];
  }
  ok(probe, "an open task carries a word to search for (" + probe + ")");
  input($("#tkq"), probe);
  await settle(4);
  eq(taskQuery, probe, "the box is the board's query");
  var hitRows = $("#tkrows").querySelectorAll(".tkrow").length;
  var wantRows = all0.filter(function (t) { return t.raw.toLowerCase().indexOf(probe.toLowerCase()) >= 0; }).length;
  eq(hitRows, Math.min(wantRows, TASK_ROWS), "only the lines carrying the word are left");
  has($("#tkrows").innerHTML, "<mark>", "and the word is marked in them");
  has($("#tknote").textContent, "matching", "the note names the search");
  eq($("#q").value, "", "the page's own search is left alone");
  input($("#tkq"), "/[/");
  await settle(4);
  ok($("#tkqerr").textContent.length > 0, "a regex that does not parse says so");
  input($("#tkq"), "zzqqxxnothing");
  await settle(4);
  has($("#tkrows").textContent, "no open tasks", "a search nothing matches says so");
  input($("#tkq"), "");
  await settle(4);

  console.log("-- tasks: the kind row --");
  var kc = $("#tkkinds").querySelector(".kc[data-k]");
  ok(kc, "the kinds carrying tasks get chips");
  has(kc.textContent, String(taskRows("open").filter(function (t) {
    return kindVal(t.e.kind) === kc.dataset.k; }).length), "each counting its open tasks");
  var pickK = kc.dataset.k;
  click(kc);
  await settle(4);
  eq(st.kinds.join(","), pickK, "a tap pins the kind on the page's own filter");
  eq(taskWhere, "view", "and puts the board under it");
  ok($("#tkwhere").style.display !== "none", "the in-view switch is offered once something is pinned");
  ok($("#tkkinds").querySelector('.kc[data-k="' + pickK + '"]').classList.contains("on"),
     "the chip is lit");
  ok(Array.prototype.every.call($("#tkrows").querySelectorAll(".tkrow"), function (r) {
    return kindVal(dbFind(Number(r.dataset.id)).kind) === pickK; }),
     "every row left is from that kind");
  ok(st.view.every(function (e) { return kindVal(e.kind) === pickK; }),
     "and the list behind the board is narrowed with it");
  click($("#tkkinds").querySelector('.kc[data-k="' + pickK + '"]'));
  await settle(4);
  eq(st.kinds.length, 0, "a second tap takes it off again");

  console.log("-- tasks: the period row --");
  var r7 = $("#tkrange").querySelector('[data-r="30"]');
  ok(r7, "the sidebar's period presets are on the board");
  ok(!$("#tkrange").querySelector("#bOtd"), "copied without their ids");
  click(r7);
  await settle(4);
  ok($("#fSince").value && $("#fUntil").value, "a preset sets the page's dates");
  ok(r7.classList.contains("on"), "and lights on the board");
  ok($("#fRange").querySelector('[data-r="30"]').classList.contains("on"), "and in the sidebar");
  var since30 = $("#fSince").value;
  ok(Array.prototype.every.call($("#tkrows").querySelectorAll(".tkrow"), function (r) {
    return TASK_DATE_CTLS[0].pred(dbFind(Number(r.dataset.id)), since30); }),
     "the rows are from inside it");
  click($("#tkrange").querySelector('[data-r=""]'));
  await settle(4);
  eq($("#fSince").value + $("#fUntil").value, "", "clear clears it");
  closeOv();
  await settle(2);
  applyQS(qs0); setKinds(kinds0); refresh();
  await settle(2);

  /* ---------- the media view ----------
     The task board's filters over GET /media: the same chips and period row,
     so what is proved here is that they reach the attachments, plus what only
     this view has — the type segment, and an attachment on an entry the page
     cannot show being left out rather than drawn without one. */
  console.log("\n-- media view --");
  var mvKinds0 = st.kinds.slice(), mvQs0 = stateQS(false);
  MEDIA = null;
  media.all = null;
  openMediaView();
  await settle(4);
  has($("#mvrows").textContent, "no GET /media", "a server without the route says so");
  closeOv();
  await settle(2);
  var live = st.all.filter(function (e) { return !e.deleted; });
  var eA = live[0], eB = live[live.length - 1];
  var gone = st.all.filter(function (e) { return e.deleted; })[0];
  ok(eA && eB && eA.kind !== eB.kind, "two live entries of different kinds to hang files off");
  var mrow = function (id, eid, mime, name, at) {
    return { id: id, entry_id: eid, path: "media/2026/09/24/e" + eid + "-" + id + "." + name.split(".").pop(),
             mime: mime, bytes: 1000 * id, name: name, created_at_utc: at };
  };
  MEDIA = [
    mrow(1, eA.id, "image/jpeg", "harbour.jpg", "2026-09-20 10:00:00"),
    mrow(2, eA.id, "audio/mp4", "recording-1.m4a", "2026-09-21 10:00:00"),
    mrow(3, eB.id, "video/mp4", "walk.mp4", "2026-08-02 10:00:00"),
    mrow(4, eB.id, "application/pdf", "invoice.pdf", "2026-08-01 10:00:00"),
  ];
  if (gone) MEDIA.push(mrow(5, gone.id, "image/jpeg", "ghost.jpg", "2026-09-22 10:00:00"));
  else MEDIA.push(mrow(5, 999999, "image/jpeg", "ghost.jpg", "2026-09-22 10:00:00"));
  mvType = "all"; mvWhere = "view"; mvQuery = "";
  openMediaView();
  await settle(4);
  ok(DBLOG.some(function (l) { return l === "GET /media"; }), "it asks for every attachment at once");
  eq($("#mvrows").querySelectorAll(".mtile").length, 4, "every attachment of a live entry is a tile");
  eq($("#mvrows").innerHTML.indexOf("ghost.jpg"), -1, "and one whose entry is gone is not");
  var names = Array.prototype.map.call($("#mvrows").querySelectorAll(".mname"), function (n) { return n.textContent; });
  eq(names.join(","), "recording-1.m4a,harbour.jpg,walk.mp4,invoice.pdf", "newest first");
  eq($("#mvrows").querySelectorAll(".shead").length, 2, "a heading per month");
  ok(!$("#mvrows").querySelector(".mdel"), "no remove button: that is the entry's own grid's");
  has($("#mvtype").querySelector('[data-v="image"]').textContent, "1", "the type segment counts");

  console.log("-- media view: the type segment --");
  click($("#mvtype").querySelector('[data-v="video"]'));
  await settle(3);
  eq(mvType, "video", "the segment switches type");
  eq($("#mvrows").querySelectorAll(".mtile").length, 1, "only the films are left");
  ok($("#mvrows").querySelector("video"), "drawn as a player");
  click($("#mvtype").querySelector('[data-v="all"]'));
  await settle(3);

  console.log("-- media view: search --");
  input($("#mvq"), "invoice");
  await settle(4);
  eq($("#mvrows").querySelectorAll(".mtile").length, 1, "the box searches the file names");
  has($("#mvnote").textContent, "matching", "and the note names the search");
  input($("#mvq"), "");
  await settle(4);

  console.log("-- media view: the board's kind row --");
  var mkc = $("#mvkinds").querySelector('.kc[data-k="' + kindVal(eB.kind) + '"]');
  ok(mkc, "the kinds carrying files get the board's chips");
  click(mkc);
  await settle(4);
  eq(st.kinds.join(","), kindVal(eB.kind), "a tap pins the kind on the page's own filter");
  var mvIds = Array.prototype.map.call($("#mvrows").querySelectorAll(".ment"), function (b) { return Number(b.dataset.id); });
  ok(mvIds.length === 2 && mvIds.every(function (id) { return id === eB.id; }), "and only that kind's files are left");
  click($("#mvwhere").querySelector('[data-v="all"]'));
  await settle(3);
  eq($("#mvrows").querySelectorAll(".mtile").length, 4, "the whole journal ignores the pin");
  click($("#mvwhere").querySelector('[data-v="view"]'));
  await settle(3);
  ok($("#mvrange").querySelector('[data-r="30"]'), "the period presets are here too");

  console.log("-- media view: hands over to the entry --");
  click($("#mvrows").querySelector(".ment"));
  await settle(3);
  ok(!$("#ov").classList.contains("on"), "the entry link closes the view");
  eq(st.sel && st.sel.id, eB.id, "and opens the entry the file hangs off");
  closeEditor();
  MEDIA = null;
  mvType = "all"; mvWhere = "view";
  applyQS(mvQs0); setKinds(mvKinds0); refresh();
  await settle(2);

  /* ---------- the blog post's shares ----------
     Share entries (kind share) and the role's readings (crew_share_<id>, and
     the run's crew_shares), made up here: no real ones exist yet. The view
     draws the run's numbers and a card per share; Stats and the crew's list
     leave the readings out. */
  console.log("\n-- the blog post's shares: the data --");
  eq(shareUrl("on reddit https://www.reddit.com/r/ClaudeAI/comments/abc/x/. and more"),
     "https://www.reddit.com/r/ClaudeAI/comments/abc/x/", "the first URL in a body is the share, its full stop left off");
  eq(shareUrl("no link"), "", "a body with none has none");
  eq(sharePlace("https://old.reddit.com/r/ClaudeAI/comments/abc/x/"), "r/ClaudeAI", "a reddit thread is its subreddit");
  eq(sharePlace("https://news.ycombinator.com/item?id=1"), "Hacker News", "HN is named");
  eq(sharePlace("https://x.com/me/status/1"), "X", "and X");
  eq(sharePlace("https://www.linkedin.com/posts/me"), "LinkedIn", "and LinkedIn");
  eq(sharePlace("https://mastodon.social/@me/1"), "mastodon.social", "anything else is its host");
  eq(sharePlace("not a url"), "", "and junk nothing");
  eq(JSON.stringify(shareJson({ content: "not json" })), "{}", "a reading that is not JSON reads as nothing");
  ok(isShareReading("crew_shares") && isShareReading("crew_share_12") && !isShareReading("crew_share") &&
     !isShareReading("crew_ops"), "the readings' kinds are told from the crew's reports");
  eq(shareFacts({ main: "score", score: 9, comments: 4, upvote_ratio: 0.92, blog_views: 30 }),
     "4 comments · 92% upvoted · 30 blog views", "a reading's other numbers, as words, the main one left out");

  // the journal's own shares and their readings (the captain's first, #8388,
  // came after the view) would join the planted ones: out for this section
  var shOwn = st.all.filter(function (e) { return !e.deleted && (e.kind === "share" || isShareReading(e.kind)); });
  shOwn.forEach(function (e) { e.deleted = 1; });
  var shDay = function (d) { return fmtUtc(new Date(Date.now() - d * 86400000)); };
  var shA = await plant({ kind: "share", title: "r/ClaudeAI", created_at_utc: shDay(3),
    content: "https://www.reddit.com/r/ClaudeAI/comments/abc/my_post/" });
  var shB = await plant({ kind: "share", title: "", created_at_utc: shDay(2), content: "https://news.ycombinator.com/item?id=42" });
  var shC = await plant({ kind: "share", title: "X", created_at_utc: shDay(1), content: "posted it, link later" });
  var shRows = [];
  var shRead = async function (sid, d, v, extra) {
    var j = Object.assign({ share: sid, value: v, main: "score", source: "reddit", fetched_at: shDay(d) }, extra || {});
    shRows.push(await plant({ kind: "crew_share_" + sid, title: v + " score", value_int: v,
      created_at_utc: shDay(d), content: JSON.stringify(j) }));
  };
  await shRead(shA.id, 2.5, 10);
  await shRead(shA.id, 1.5, 40, { comments: 3 });
  await shRead(shA.id, 0.5, 52, { comments: 7, upvote_ratio: 0.9, blog_views: 120 });
  await shRead(shB.id, 1.5, 5, { main: "points", source: "hn", points: 5, error: "HTTP 503 from Algolia" });
  await shRead(999999, 1, 77);    // a share entry that is gone
  shRows.push(await plant({ kind: "crew_shares", title: "45 · blog post, 3 shares", value_int: 45, created_at_utc: shDay(1.5),
    content: JSON.stringify({ value: 45, comments: 3, shares: 3, blog_views: 180, by_share: {} }) }));
  var shG = {};
  shG[shB.id] = "HTTP 429 from Algolia";
  shRows.push(await plant({ kind: "crew_shares", title: "57 · blog post, 3 shares", value_int: 57, created_at_utc: shDay(0.5),
    content: JSON.stringify({ value: 57, comments: 7, shares: 3, blog_views: 300, blog_views_from_shares: 120,
      stale: [shB.id], missing: [shC.id], errors: shG }) }));
  var shD = sharesData();
  eq(shD.runs.length, 2, "the run's readings are the global series");
  eq(shD.latest.value, 57, "and the newest is the headline");
  eq(shD.cards.map(function (c) { return c.id; }).join(","), [shC.id, shB.id, shA.id].join(","),
     "a card per share, newest shared first, a gone share's readings dropped");
  var cA = shD.cards[2], cB = shD.cards[1], cC = shD.cards[0];
  eq(cA.pts.map(function (p) { return p.v; }).join(","), "10,40,52", "a share's readings, oldest first");
  eq(cA.name, "r/ClaudeAI", "named by its title");
  eq(cB.name, "Hacker News", "an untitled one by the place its link names");
  ok(cB.stale && !cB.missing && cC.missing && !cA.stale, "stale and missing are the latest run's");
  eq(cB.error, "HTTP 429 from Algolia", "the run's error beats the older reading's own");
  eq(cC.url, "", "a share with no link has none");

  console.log("-- the blog post's shares: the view --");
  openShares();
  await settle(3);
  eq(st.route && st.route.v, "shares", "it has a url of its own");
  var shCards = $("#shrows").querySelectorAll(".shcard");
  eq(shCards.length, 3, "a card per share");
  has($("#shrows").querySelector(".sgrid").textContent, "57", "the headline is the latest total");
  has($("#shrows").querySelector(".sgrid").textContent, "300", "and its blog views");
  ok($("#shrows").querySelector("svg.shch .shviews"), "the global chart carries the blog views as a second line");
  var shCardOf = function (id) { return $("#shrows").querySelector('.shcard[data-share="' + id + '"]'); };
  has(shCardOf(shA.id).querySelector(".mhd").textContent, "52", "a card's latest number");
  has(shCardOf(shA.id).textContent, "7 comments", "and its other numbers");
  ok(shCardOf(shA.id).querySelector("svg.shch polyline"), "and the chart of its readings");
  eq(shCardOf(shA.id).querySelector(".shopen").getAttribute("href"), "https://www.reddit.com/r/ClaudeAI/comments/abc/my_post/",
     "a tap opens the share's URL");
  eq(shCardOf(shA.id).querySelector(".shopen").getAttribute("target"), "_blank", "in a tab of its own");
  has(shCardOf(shB.id).querySelector(".shmark").textContent, "stale", "a stale share is marked so");
  has(shCardOf(shB.id).querySelector(".sherr").textContent, "last read failed: HTTP 429", "and its error is said in words");
  has(shCardOf(shC.id).querySelector(".shmark").textContent, "missing", "a missing one too");
  has(shCardOf(shC.id).textContent, "no link in its body yet", "and one with no link says what to do");
  ok(!shCardOf(shC.id).querySelector(".shopen"), "with nothing to open");
  click(shCardOf(shA.id).querySelector(".shopen"));
  ok(shCardOf(shA.id).querySelector(".shopen").classList.contains("pressing"), "a tap on the link shows at once");
  click(shCardOf(shA.id).querySelector("[data-entry]"));
  await settle(3);
  ok(!$("#ov").classList.contains("on"), "Entry closes the view");
  eq(st.sel && st.sel.id, shA.id, "and opens the share's entry");
  closeEditor();
  await settle(2);

  console.log("-- the blog post's shares: Stats and the crew --");
  openStats(true);
  await settle(3);
  ok(!Array.prototype.some.call($("#dlg").querySelectorAll(".mcard .mk"), function (m) { return isShareReading(m.dataset.k); }),
     "Stats draws no share reading as a measurement card");
  has($("#dlg").querySelector(".sshare").textContent, "57", "but a Blog shares line with the latest total");
  click($("#s_shares"));
  await settle(3);
  eq(st.route && st.route.v, "shares", "whose button opens the view");
  closeOv();
  await settle(2);
  var shCrew = crewReports();
  ok(!shCrew.has("crew_shares") && !shCrew.has("crew_share_" + shA.id), "the crew's list has no share readings as rows");
  eq(vMatch(vWords("blog shares"), 0).cmd.say, "blog shares", "“blog shares” is an order");
  eq(vMatch(vWords("how is the blog post doing"), 0).cmd.say, "blog shares", "and so is asking after the post");
  eq(vMatch(vWords("add a share"), 0).cmd.say, "add a share", "“add a share” too");

  console.log("-- the blog post's shares: + Share and the empty state --");
  openShares();
  await settle(2);
  click($("#sh_add"));
  await settle(2);
  ok(st.isNew && !$("#ov").classList.contains("on"), "+ Share is the editor on a new entry");
  eq($("#e_kind").value, "share", "of kind share");
  eq(document.activeElement, $("#content"), "the body focused for the URL");
  setClean();
  closeEditor();
  await settle(2);
  [shA, shB, shC].concat(shRows).forEach(unplant);
  await settle(2);
  openShares();
  await settle(2);
  ok(!$("#shrows").querySelector(".shcard"), "with no shares there are no cards");
  has($("#shrows").querySelector(".shempty").textContent, "+ Share", "and the empty state says how to add one");
  closeOv();
  await settle(2);
  shOwn.forEach(function (e) { e.deleted = 0; });

  /* ---------- the reports ----------
     GET /reports, drawn as the server sends it (newest first): a link per
     report to its file under /media/, opening a tab of its own, and a tap
     marked at once. */
  console.log("\n-- reports --");
  REPORTS = null;
  reportsAll = null;
  openReports();
  await settle(4);
  has($("#rprows").textContent, "no GET /reports", "a server without the route says so");
  closeOv();
  await settle(2);
  REPORTS = [
    { path: "media/reports/2026/10/fleet-status-1a2b3c4d.html", title: "Fleet <status>", type: "html",
      bytes: 2048, published_utc: "2026-10-15 09:30:00" },
    { path: "media/reports/2026/09/weights-9f8e7d6c.csv", title: "Weights", type: "csv",
      bytes: 512, published_utc: "2026-09-02 08:00:00" },
    { path: "media/reports/2026/08/audit-0a0b0c0d.pdf", title: "Audit", type: "pdf",
      bytes: 9000, published_utc: "2026-08-01 08:00:00" },
  ];
  openReports();
  await settle(4);
  ok(DBLOG.some(function (l) { return l === "GET /reports"; }), "it asks the server for the list");
  eq(st.route && st.route.v, "reports", "it has a url of its own");
  var rps = $("#rprows").querySelectorAll(".rprow");
  eq(rps.length, 3, "a row per report");
  has(rps[0].getAttribute("href"), "/media/reports/2026/10/fleet-status-1a2b3c4d.html", "each a link to its file");
  eq(rps[0].getAttribute("target"), "_blank", "opened in a tab of its own");
  eq(rps[0].querySelector(".rptitle").textContent, "Fleet <status>", "the title, as text");
  has(rps[1].textContent, "CSV", "and its type");
  has($("#rpnote").textContent, "3 reports", "the note counts them");
  eq(rps[0].dataset.report, "media/reports/2026/10/fleet-status-1a2b3c4d.html", "an HTML row is the viewer's");
  eq(rps[1].dataset.report, "media/reports/2026/09/weights-9f8e7d6c.csv", "and a text one");
  ok(!rps[2].dataset.report, "a PDF's is not: Chromium will not open it sandboxed");
  click(rps[2]);
  ok(rps[2].classList.contains("pressing"), "a tap on a PDF shows at once");
  eq(rps[2].querySelector(".rpwhen").textContent, "opening…", "and says it is opening in its tab");
  ok(!$("#rview"), "and opens no viewer");

  console.log("\n-- the report viewer --");
  var rvHist = history._st.length;
  var rvEv = click(rps[0]);
  ok(rvEv.defaultPrevented, "a viewer row's tap is not a tab");
  ok($("#rview"), "the viewer opens in the same frame");
  eq($("#rvh").textContent, "Fleet <status>", "with the report's title");
  eq($("#rvtype").textContent, "HTML", "and its type");
  eq($("#rvnote").textContent, "loading the report…", "saying it is loading");
  has($("#rvtab").getAttribute("href"), "/media/reports/2026/10/fleet-status-1a2b3c4d.html", "Open in a tab is the file's link");
  has(location.pathname, "/report/2026/10/fleet-status-1a2b3c4d.html", "it is a step of its own, ./report/<path>");
  eq(history._st.length, rvHist + 1, "pushed over the Reports page");
  ok(!$("#rview").querySelector("iframe"), "no frame before the HEAD has answered");
  await settle(1);
  ok(DBLOG.indexOf("HEAD /media/reports/2026/10/fleet-status-1a2b3c4d.html") >= 0, "the file is asked for with a HEAD first");
  var rvf = $("#rview").querySelector("iframe");
  ok(rvf, "then framed");
  eq(rvf && rvf.getAttribute("sandbox"), "allow-scripts allow-popups allow-popups-to-escape-sandbox allow-downloads",
     "sandboxed, never allow-same-origin");
  has(rvf && rvf.src, "/media/reports/2026/10/fleet-status-1a2b3c4d.html", "on the report");
  ok(!$("#rvnote").hidden, "the loading line stays until the frame has loaded");
  rvf.onload();
  ok($("#rvnote").hidden, "and goes when it has");
  ok($("#rprows"), "the Reports page is still under it");
  history.back();
  await settle(1);
  ok(!$("#rview"), "Back closes the viewer");
  ok($("#rprows") && st.route && st.route.v === "reports", "and leaves the Reports page as it was");
  history.forward();
  await settle(1);
  ok($("#rview"), "Forward opens it again");
  click($("#rvclose"));
  ok(!$("#rview"), "Close closes it");
  await settle(1);
  ok(!/\/report\//.test(location.pathname), "and takes its step back off");
  ok($("#rprows"), "back on the Reports page");
  click($("#rprows").querySelectorAll(".rprow")[1]);
  eq($("#rvtype").textContent, "CSV", "a text report opens here too");
  window._on.keydown.forEach(function (f) { f({ key: "Escape", stopImmediatePropagation: function () {}, preventDefault: function () {} }); });
  ok(!$("#rview"), "Escape closes it");
  await settle(1);
  ok($("#rprows"), "and only it");
  // a report gone from the store: said where the report would be
  reportView("media/reports/2026/10/gone-11111111.html", "Gone");
  await settle(1);
  has($("#rvnote").textContent, "not in the store", "a 404 is said on the viewer's line");
  ok($("#rvnote").classList.contains("bad"), "as a failure");
  reportClose();
  await settle(1);
  // an iframe fires no error: a load that never ends is the timeout's
  reportView("media/reports/2026/10/fleet-status-1a2b3c4d.html");
  await settle(6);
  has($("#rvnote").textContent, "did not finish loading", "a load that never ends is said");
  reportClose();
  await settle(1);
  closeOv();
  await settle(2);

  console.log("\n-- report links in markdown, and the chat's card --");
  eq(reportRel("https://debian.example.ts.net/media/reports/2026/10/fleet-status-1a2b3c4d.html"),
     "media/reports/2026/10/fleet-status-1a2b3c4d.html", "a link on any host is the report's path");
  eq(reportRel("/media/reports/2026/10/a-b.csv?x=1"), "media/reports/2026/10/a-b.csv", "a path from the root, the query dropped");
  eq(reportRel("media/reports/2026/10/.a-b.csv.json"), null, "a sidecar is not a report");
  eq(reportRel("https://x/media/2026/10/a.html"), null, "nor an attachment");
  var rvMd = document.createElement("div");
  rvMd.innerHTML = mdRender("Done: [Fleet status](https://debian.example.ts.net/media/reports/2026/10/fleet-status-1a2b3c4d.html), " +
    "the [audit](https://debian.example.ts.net/media/reports/2026/08/audit-0a0b0c0d.pdf) and " +
    "https://debian.example.ts.net/media/reports/2026/09/weights-9f8e7d6c.csv");
  var rvAs = rvMd.querySelectorAll("a");
  eq(rvAs.length, 3, "three links");
  eq(rvAs[0].dataset.report, "media/reports/2026/10/fleet-status-1a2b3c4d.html", "a [link] to an HTML report is the viewer's");
  eq(rvAs[0].getAttribute("target"), "_blank", "its href and tab kept, for a long-press");
  ok(!rvAs[1].dataset.report, "a PDF's stays a tab's");
  eq(rvAs[2].dataset.report, "media/reports/2026/09/weights-9f8e7d6c.csv", "a bare URL to one too");
  document.body.appendChild(rvMd);
  click(rvAs[0]);
  ok($("#rview"), "a tap on one opens the viewer");
  eq($("#rvh").textContent, "Fleet <status>", "titled as the list has it");
  reportClose();
  await settle(1);
  rvMd.remove();
  var rvCards = document.createElement("div");
  rvCards.innerHTML = reportCards("Published [Fleet status](https://debian.example.ts.net/media/reports/2026/10/fleet-status-1a2b3c4d.html)" +
    " and https://debian.example.ts.net/media/reports/2026/08/audit-0a0b0c0d.pdf, again: https://debian.example.ts.net/media/reports/2026/10/fleet-status-1a2b3c4d.html");
  var rvc = rvCards.querySelectorAll(".rpcard");
  eq(rvc.length, 2, "a card per report linked, each once");
  eq(rvc[0].querySelector(".rptype").textContent, "HTML", "a card says the type");
  eq(rvc[0].querySelector(".rptitle").textContent, "Fleet status", "the link's own title");
  eq(rvc[0].querySelector(".rpview").textContent, "View", "and View");
  eq(rvc[0].dataset.report, "media/reports/2026/10/fleet-status-1a2b3c4d.html", "which opens the viewer");
  ok(!rvc[1].dataset.report && rvc[1].getAttribute("target") === "_blank", "a PDF's card is a tab's");
  eq(reportCards("no reports here"), "", "a message without one has none");
  var rvLog = document.createElement("div");
  chatLogPaint(rvLog, [{ role: "asst", parts: [{ t: "text", s: "See [Weights](https://h/media/reports/2026/09/weights-9f8e7d6c.csv)." }] }], "");
  ok(rvLog.querySelector(".rpcard[data-report]"), "the chat draws the card under the message");
  document.body.appendChild(rvLog);
  click(rvLog.querySelector(".rpview"));
  eq($("#rvtype").textContent, "CSV", "and its View opens the report");
  reportClose();
  await settle(1);
  rvLog.remove();

  console.log("\n-- report viewer: voice --");
  eq(vMatch(vWords("show the latest report"), 0).cmd.say, "show the latest report", "\u201cshow the latest report\u201d is an order");
  eq(vMatch(vWords("open the report"), 0).cmd.say, "open the report", "\u201copen the report\u201d is one");
  eq(vMatch(vWords("close the report"), 0).cmd.say, "close the report", "\u201cclose the report\u201d is one");
  reportsAll = null;
  vMatch(vWords("show the latest report"), 0).cmd.fn();
  ok($("#rview"), "the viewer opens at once");
  has($("#rvnote").textContent, "finding the latest report", "finding the report meanwhile");
  await settle(2);
  eq($("#rvh").textContent, "Fleet <status>", "then the newest one");
  vMatch(vWords("close the report"), 0).cmd.fn();
  ok(!$("#rview"), "and the order closes it");
  await settle(1);
  eq(vMatch(vWords("show reports"), 0).cmd.say, "reports", "\u201cshow reports\u201d is an order");
  vMatch(vWords("show reports"), 0).cmd.fn(); await settle(3);
  ok($("#rprows"), "and it opens the page");
  closeOv();
  await settle(2);
  REPORTS = null;

  /* ---------- the tape deck ----------
     A row holding a recording or a video has a play button that plays it in
     the deck at the foot of the screen, without opening the entry. Where the
     tape is known from: the text's own link (a dictation), else GET /media. */
  console.log("\n-- tape deck: a dictation's row has a play button --");
  // Three rows of the suite's own: the journal's newest hold dictations of
  // their own, and on 2026-10-02's data the row meant to have "nothing
  // linked" linked a tape. Taken out once the deck is closed.
  var tN = await plant({ title: "Tape probe, none",
    content: "no tape here, only [a page](https://example.com/x.html) and ![](media/a/b.jpg)" });
  var tV = await plant({ title: "Tape probe, attached", content: "the files hang off this one" });
  var tA = await plant({ title: "Tape probe, dictated", content: "what was said" });
  tA.content = "what was said\n[dictation](media/2026/09/24/e" + tA.id + "-1.m4a)";
  media.byEntry.delete(tA.id); media.byEntry.delete(tV.id); media.byEntry.delete(tN.id);
  media.tapes = new Map();
  refresh();
  await settle(2);
  var tRow = function (e) { return $("#list").querySelector('.item[data-id="' + e.id + '"]'); };
  var tBtn = function (e) { var r = tRow(e); return r && r.querySelector(".tplay"); };
  ok(tBtn(tA), "a row whose text links a recording gets a play button");
  ok(tBtn(tA).classList.contains("audio"), "drawn as sound");
  ok(tRow(tA).classList.contains("tape"), "and the row makes room for it");
  ok(!tBtn(tN), "a link to a page or a picture is no tape");
  has(entryTape(tA).url, "/media/2026/09/24/e" + tA.id + "-1.m4a", "the link resolves against the API base");

  console.log("-- tape deck: the button plays in place --");
  var tSel0 = st.sel;
  click(tBtn(tA));
  await settle(2);
  ok(!$("#tdeck").hidden, "the deck comes up");
  eq(document.body.dataset.tape, "on", "and says so on the body");
  ok(st.sel === tSel0, "the entry is not opened");
  ok(!tapeEl().paused, "the tape plays");
  has(tapeEl().getAttribute("src"), "e" + tA.id + "-1.m4a", "the entry's tape");
  ok(tBtn(tA).classList.contains("on"), "the row's button says it is playing");
  has($("#tdeck .tdopen").textContent, "#" + tA.id, "the deck names the entry");
  click(tBtn(tA));
  await settle(2);
  ok(tapeEl().paused, "a second press pauses");
  ok(!tBtn(tA).classList.contains("on"), "and the button says so");

  console.log("-- tape deck: opening the entry, and l --");
  click($("#tdeck .tdopen"));
  await settle(3);
  eq(st.sel && st.sel.id, tA.id, "the deck's name opens the entry");
  ok(!$("#tdeck").hidden, "and the deck stays");
  key("l");
  await settle(2);
  ok(!tapeEl().paused, "l plays the open entry's tape");
  key("l");
  await settle(2);
  ok(tapeEl().paused, "and pauses it");
  closeEditor();
  await settle(2);

  console.log("-- tape deck: an attachment the text does not link --");
  ok(!tBtn(tV), "a row with nothing linked has no button");
  MEDIA = [
    { id: 11, entry_id: tV.id, path: "media/2026/09/24/e" + tV.id + "-11.jpg", mime: "image/jpeg", bytes: 1, name: "a.jpg", created_at_utc: "2026-09-24 10:00:00" },
    { id: 13, entry_id: tV.id, path: "media/2026/09/24/e" + tV.id + "-13.mp4", mime: "video/mp4", bytes: 1, name: "b.mp4", created_at_utc: "2026-09-24 10:00:00" },
    { id: 12, entry_id: tV.id, path: "media/2026/09/24/e" + tV.id + "-12.webm", mime: "video/webm", bytes: 1, name: "c.webm", created_at_utc: "2026-09-24 10:00:00" },
  ];
  tapeIndexGone = false;
  tapeIndexLoad();
  await settle(3);
  ok(tBtn(tV), "GET /media gives the row its button, without redrawing the list");
  ok(tBtn(tV).classList.contains("video"), "drawn as pictures");
  has(entryTape(tV).url, "-12.webm", "the first of several is the oldest");
  click(tBtn(tV));
  await settle(2);
  eq(tapeEl().tagName, "VIDEO", "a video plays with its picture");
  ok($("#tdeck").classList.contains("video"), "which the deck makes room for");
  ok(!tBtn(tA).classList.contains("cur"), "the other row lets go of the deck");
  media.byEntry.set(tV.id, []);
  mediaPaint();
  ok(!tBtn(tV), "an entry whose own list holds no tape loses the button");

  console.log("-- tape deck: closing --");
  click($("#tdeck .tdx"));
  await settle(2);
  ok($("#tdeck").hidden, "the deck goes");
  eq(document.body.dataset.tape, undefined, "and the body forgets it");
  media.byEntry.delete(tV.id);
  MEDIA = null; media.all = null; media.tapes = new Map();
  [tA, tV, tN].forEach(unplant);
  await settle(2);

  /* ---------- moving a task from where it is written ----------
     The board says what is open; this is the other half of the same thought —
     changing one without opening the editor, finding the line and retyping the
     word. The gestures themselves are pointer events the shim has no notion
     of, so what is tested here is everything underneath them: the ring, the
     control the renderer emits, and the write it makes. */
  console.log("\n-- tasks: the marker is the control --");
  eq(nextTaskWord("TODO"), "DOING", "a tap sends TODO on to DOING");
  eq(nextTaskWord("DOING"), "DONE", "and DOING to DONE");
  eq(nextTaskWord("DONE"), "TODO", "and round again from the end");
  eq(nextTaskWord("LATER"), "NOW", "LATER/NOW is its own spelling of the same ring");
  eq(nextTaskWord("NOW"), "DONE", "and ends in the same place");
  eq(nextTaskWord("WAITING"), "TODO", "a parked marker leads out into the usual ring");
  eq(nextTaskWord("CANCELED"), "TODO", "so does a cancelled one");
  eq(taskRing("WAITING")[taskRing("WAITING").length - 1], "DONE",
     "and comes back round to itself rather than stranding the line");
  ok(TASK_RINGS.every(function (r) { return r.every(function (w) {
       return TASK_WORDS.indexOf(w) >= 0; }); }),
     "every word in a ring is a marker the renderer and the board both know");

  console.log("-- tasks: what the renderer offers --");
  ok(mdRender("- TODO buy milk").indexOf("<button") < 0,
     "with no entry behind it the marker stays a plain chip");
  var tmk = mdRender("a line\n- TODO buy milk\n- DONE ring back", { eid: 7 });
  has(tmk, 'data-eid="7" data-ln="1" data-w="TODO"', "the chip carries its entry and its line");
  has(tmk, 'data-eid="7" data-ln="2" data-w="DONE"', "one handle per task line, by line number");
  ok(mdRender("- just a bullet", { eid: 7 }).indexOf("tsw") < 0,
     "a bullet that is not a task gets no control");
  has(mdRender("Notes\n\nWAITING on the captain", { eid: 7 }), 'data-eid="7" data-ln="2" data-w="WAITING"',
      "a marker heading a line with no bullet is a control too, as the board counts it");
  ok(mdRender("we are WAITING on it", { eid: 7 }).indexOf("tsw") < 0, "but not one mid-sentence");

  console.log("-- tasks: a tap writes the line --");
  // An entry of the suite's own, through the fake API: which journal row
  // happens to carry the first task line (and in what state the page is when
  // it is selected) changes with every day's data, and a chip missing for a
  // reason that is the day's, not the reader's, blocked deploys (2026-10-13).
  var tskRow = await api("/entries", { method: "POST", body: { kind: "personal_log", title: "Errands",
    content: "Errands for Saturday\n- TODO buy milk\n- DONE post the letter" } });
  insertRow(await api("/entries/" + tskRow.id));
  var tsk = { e: st.byId.get(tskRow.id), ln: 1, word: "TODO" };
  ok(tsk.e && TASK_LINE.exec(String(tsk.e.content).split("\n")[tsk.ln]), "the fixture has a task line to move");
  select(tsk.e.id, true);
  await settle(5);
  var chip = $("#rd_content").querySelector('button.task.tsw[data-ln="' + tsk.ln + '"]');
  ok(chip, "the reader paints that line as a control");
  eq(chip && chip.dataset.w, tsk.word, "reading the word that is actually on the line");
  var lines0 = String(tsk.e.content).replace(/\r\n?/g, "\n").split("\n");
  var want = nextTaskWord(tsk.word);
  var puts = function () {
    return TEST.fetches.filter(function (f) { return f.slice(0, 3) === "PUT"; }).length;
  };
  await setTaskWord(tsk.e.id, tsk.ln, want, chip);
  await settle(5);
  var lines1 = String(dbFind(tsk.e.id).content).replace(/\r\n?/g, "\n").split("\n");
  eq(lines1.length, lines0.length, "no line was added or lost");
  var moved = 0;
  for (var k9 = 0; k9 < lines0.length; k9++) if (lines0[k9] !== lines1[k9]) moved++;
  eq(moved, 1, "exactly one line of the entry changed");
  eq(lines1[tsk.ln], lines0[tsk.ln].replace(tsk.word, want),
     "and what changed on it is the marker");
  eq(chip.dataset.w, want, "the chip in the reader says so without a re-render");
  eq(chip.textContent, want, "in words as well as colour");
  ok(!chip.classList.contains("busy"), "and is live again");

  // the press is a pointer gesture, but an activation with nothing behind it —
  // a screen reader, or another part of the page — is the same plain tap
  click(chip);
  await settle(6);
  eq(chip.dataset.w, nextTaskWord(want), "an activation with no pointer behind it taps too");
  var at = chip.dataset.w;

  console.log("-- tasks: what it refuses to write --");
  var p0 = puts();
  await setTaskWord(tsk.e.id, 9999, "DONE", null);
  await settle(3);
  eq(puts(), p0, "a line that is not a task any more is not written to");
  await setTaskWord(tsk.e.id, tsk.ln, at, null);
  await settle(3);
  eq(puts(), p0, "and neither is a marker already sitting where it was asked to go");

  // the CLI and the cron jobs write this database too
  var trow = st.byId.get(tsk.e.id);
  trow.last_modified_at_utc = "1999-01-01 00:00:00";
  await setTaskWord(trow.id, tsk.ln, "WAITING", null);
  await settle(3);
  eq(puts(), p0, "a row that moved on the server is read back, never written over");
  eq(trow.last_modified_at_utc, dbFind(trow.id).last_modified_at_utc,
     "and what is actually there is what the reader ends up holding");

  // an unsaved edit to the same entry must not be flattened by a one-word write
  select(trow.id, true);
  await settle(4);
  input($("#e_head"), "half a thought");
  ok(document.body.classList.contains("dirty"), "the form is dirty");
  await setTaskWord(trow.id, tsk.ln, "CANCELED", null);
  await settle(3);
  eq(puts(), p0, "an unsaved edit to that entry stops the write");
  has($("#toast").textContent, "save or revert", "and says which way out there is");
  $("#bRevert").onclick();
  await settle(3);
  hideToast();
  // the fixture goes again: the sections after count the journal's top rows
  st.all.splice(st.all.indexOf(tsk.e), 1);
  st.byId.delete(tsk.e.id);
  dbFind(tsk.e.id).deleted = 1;
  tkPlanted.forEach(unplant);
  refresh();
  await settle(3);

  /* ---------- new since the last visit ---------- */
  console.log("\n-- fresh: the water mark --");
  var realSeen = seenId;
  eq(typeof seenId, "number", "the mark is a number");
  // a first-ever visit must not declare the whole journal unread
  seenId = 0;
  eq(freshCount(), 0, "with no mark inherited, nothing is new");
  ok(!isFresh(st.all[0]), "not even the newest row");
  noteSeen();
  eq(seenId, st.all[0].id, "a first visit starts the clock at the top");

  console.log("-- fresh: marking --");
  seenId = st.all[5].id;              // pretend the last visit stopped five rows down
  refresh();
  eq(freshCount(), 5, "five rows arrived since");
  eq($("#list").querySelectorAll(".item.fresh").length, 5, "and five rows are marked");
  has($("#list").innerHTML, "newtag", "the rows say so in words as well as colour");
  ok(!isFresh(st.all[5]), "the row the mark sits on is not itself new");
  has($("#bFresh").textContent, "5 new", "the sidebar counts them");

  console.log("-- fresh: the filter is an ordinary control --");
  toggleFresh();
  eq(st.view.length, 5, "the filter narrows to them");
  ok(st.view.every(isFresh), "and to nothing else");
  eq(activeFilters() > 0, true, "it counts as a filter");
  has(stateQS(false), "u=1", "the url carries it");
  var backQS = stateQS(false);
  clearFilters();
  eq($("#fFresh").value, "", "clear turns it off with the rest");
  ok(st.view.length > 5, "and the list comes back");
  applyQS(backQS);
  refresh();
  eq(st.view.length, 5, "a url that carries it restores it");
  clearFilters();
  // it is a mark, not a date: a backdated import is still something that arrived
  var back = st.all[0];
  var wasCreated = back.created_at_utc;
  back.created_at_utc = "2001-01-01 00:00:00";
  ok(isFresh(back), "an entry backdated to 2001 is still new if its id is");
  back.created_at_utc = wasCreated;
  seenId = realSeen;
  refresh();

  /* ---------- resurface ---------- */
  console.log("\n-- resurface --");
  resurfaced = [];
  var picks = {}, n = 0;
  for (var ri = 0; ri < 15; ri++) {
    var was = st.sel && st.sel.id;
    resurface();
    if (st.sel && st.sel.id !== was) { picks[st.sel.id] = 1; n++; }
  }
  ok(Object.keys(picks).length > 1, "it does not keep offering the same entry");
  ok(Object.keys(picks).every(function (id) {
       var e = st.byId.get(Number(id));
       return !e.deleted && entryAge(e) >= RESURF_MIN_AGE &&
              (e.content_length || 0) >= RESURF_MIN_LEN;
     }), "everything it offers is old enough, long enough and not deleted");
  ok(resurfaced.length > 0, "the session remembers what it has already shown");
  // and it must not be able to run itself out and then do nothing for ever
  resurfaced = st.all.map(function (e) { return e.id; });
  hideToast();
  resurface();
  eq(resurfaced.length, 0, "having been through them all, it starts over");
  has($("#toast").textContent, "starting over", "and says so");
  hideToast();
  closeEditor();

  /* the pick is weighted: this week of the year in an earlier year 4x, media
     2x, linked to 2x, multiplied; a stubbed draw shows the walk */
  console.log("\n-- resurface: weighted --");
  var rw = [{ w: 1, n: "a" }, { w: 4, n: "b" }, { w: 2, n: "c" }];
  eq(resurfPick(rw, 0).n, "a", "the draw walks the weights end to end: 0 is the first");
  eq(resurfPick(rw, 0.2).n, "b", "1.4 of 7 lands in the 4x one");
  eq(resurfPick(rw, 0.7).n, "b", "and so does 4.9 of 7");
  eq(resurfPick(rw, 0.75).n, "c", "5.25 of 7 is the last");
  eq(resurfPick(rw, 0.9999).n, "c", "and the top of the range never falls off the end");
  var rnow = todayStart(), ry = rnow.getFullYear() - 2;
  var rThen = new Date(ry, rnow.getMonth(), rnow.getDate(), 12, 0, 0);
  var rOff = new Date(ry, rnow.getMonth(), rnow.getDate(), 12, 0, 0);
  rOff.setDate(rOff.getDate() + 60);
  var rLong = " A day worth reading again, long enough to resurface by the length rule, and then some more words.";
  var rWeek = await plant({ title: "Resurf week probe", created_at_utc: fmtUtc(rThen),
    content: "![view](/media/x/view.jpg)" + rLong });
  var rPlain = await plant({ title: "Resurf plain probe", created_at_utc: fmtUtc(rOff), content: rLong });
  var rLinked = await plant({ title: "Resurf linked probe", created_at_utc: fmtUtc(rOff), content: rLong });
  var rLinker = await plant({ title: "Resurf linker", content: "see [[Resurf linked probe]]" });
  var rWs = resurfWeights([rWeek, rPlain, rLinked]);
  eq(rWs[0].w, 8, "this week in an earlier year with a photo: 4 x 2");
  eq(rWs[0].why.join("; "), "this week in " + ry + "; has photos", "and it says why");
  eq(rWs[1].w, 1, "two months off the date, no media, no links: 1");
  eq(rWs[1].why.length, 0, "with nothing to say");
  eq(rWs[2].w, 2, "an entry another links to by title: 2");
  eq(rWs[2].why.join(), "linked to", "and says so");
  // the whole order: with only the anniversary left, the toast carries its reasons
  resurfaced = st.all.filter(function (x) { return x !== rWeek; }).map(function (x) { return x.id; });
  var rRand = Math.random;
  Math.random = function () { return 0.5; };
  try { hideToast(); resurface(); } finally { Math.random = rRand; }
  eq(st.sel && st.sel.id, rWeek.id, "the one candidate comes up");
  has($("#toast").textContent, "this week in " + ry, "the toast says it is this week in " + ry);
  has($("#toast").textContent, "has photos", "and that it has photos");
  hideToast();
  closeEditor();
  resurfaced = [];
  [rLinker, rLinked, rPlain, rWeek].forEach(unplant);
  refresh();

  /* An untitled quick capture is drawn by its first words, dimmer; the stored
     title and the editor's field keep the placeholder */
  console.log("\n-- derived titles --");
  var dLong = "Walked the dog along the river this morning and the light on the water was something else entirely";
  var dRow = await plant({ title: "HTTP Entry", content: "id:: 1234-abcd\n- " + dLong + "\nsecond line" });
  var dEmpty = await plant({ title: "", content: "Short note\nmore" });
  var dNamed = await plant({ title: "Named probe", content: "body" });
  var dt = shownTitle(dRow);
  ok(dt.derived, "the placeholder title is derived");
  ok(dt.t.length <= SHOWN_TITLE_MAX + 1 && /…$/.test(dt.t), "cut at about sixty characters with an ellipsis: " + dt.t);
  eq(dt.t.indexOf("Walked the dog"), 0, "from the first line, past the property line and the bullet");
  ok(dLong.indexOf(dt.t.slice(0, -1)) === 0 && dt.t.slice(-2, -1) !== " ", "cut at a word, not mid-space");
  eq(shownTitle(dEmpty).t, "Short note", "an empty title is the first line, whole when short");
  ok(shownTitle(dEmpty).derived, "and derived too");
  eq(shownTitle(dNamed).t, "Named probe", "a real title is itself");
  ok(!shownTitle(dNamed).derived, "and not derived");
  eq(shownTitle({ id: 9, title: "HTTP Entry" }).t, "(untitled)", "a row with no body yet is (untitled) until it has one");
  refresh();
  var dItem = $("#list").querySelector('.item[data-id="' + dRow.id + '"]');
  ok(!!dItem, "the capture is in the list");
  if (dItem) {
    eq(dItem.querySelector(".t").textContent, dt.t, "the list row shows its first words");
    ok(dItem.querySelector(".t").classList.contains("tder"), "dimmed as derived");
    has(dItem.getAttribute("aria-label"), "Walked the dog", "and is read out by them too");
  }
  var nItem = $("#list").querySelector('.item[data-id="' + dNamed.id + '"]');
  ok(nItem && !nItem.querySelector(".t").classList.contains("tder"), "a titled row is not dimmed");
  select(dRow.id);
  eq($("#rd_title").textContent, dt.t, "the reader's heading is the first words");
  ok($("#rd_title").classList.contains("tder"), "dimmed as derived");
  eq(st.byId.get(dRow.id).title, "HTTP Entry", "the stored title is untouched");
  setRead(false);
  eq($("#e_head").value, "HTTP Entry", "and the editor's title field shows the stored value");
  closeEditor();
  select(dNamed.id);
  ok(!$("#rd_title").classList.contains("tder"), "a titled entry's heading is not dimmed");
  closeEditor();
  [dNamed, dEmpty, dRow].forEach(unplant);
  refresh();

  /* the screen kept awake while dictating, reading aloud or ambient */
  console.log("\n-- wake lock --");
  var wlWas = navigator.wakeLock, wlReq = 0, wlRel = 0;
  function FakeLock() { this.on = {}; }
  FakeLock.prototype.addEventListener = function (t, fn) { this.on[t] = fn; };
  FakeLock.prototype.release = function () { wlRel++; if (this.on.release) this.on.release(); return Promise.resolve(); };
  navigator.wakeLock = { request: function (t) { wlReq++; eq(t, "screen", "a screen lock"); return Promise.resolve(new FakeLock()); } };
  try {
    setClean();
    ambStart();
    await settle(3);
    eq(wlReq, 1, "ambient mode asks for the lock");
    ok(!!wake.lock, "and holds it");
    document.hidden = true; wakeSync();
    eq(wlRel, 1, "the page hidden lets it go");
    await settle(2);
    document.hidden = false; wakeSync();
    await settle(3);
    eq(wlReq, 2, "shown again while still ambient, it asks again");
    wakeWant("tts", true);
    await settle(2);
    eq(wlReq, 2, "a second reason shares the one lock");
    ambStop();
    eq(wlRel, 1, "the lock stays while reading aloud still wants it");
    ttsStop(true);
    eq(wlRel, 2, "and goes when reading aloud stops");
    ok(!wake.lock && !wake.why.size, "nothing held, nothing wanted");
    wakeWant("voice", true);
    await settle(3);
    eq(wlReq, 3, "dictation asks for it");
    voiceStop();
    eq(wlRel, 3, "and stopping it lets go");
    // a request still out when everything stops is let go as it lands
    wakeWant("amb", true); wakeWant("amb", false);
    await settle(3);
    eq(wlRel, 4, "a lock that lands after the stop is released at once");
    ok(!wake.lock, "and not kept");
    // missing, throwing or refusing: nothing breaks
    delete navigator.wakeLock;
    var wlOk = true;
    try { wakeWant("amb", true); wakeWant("amb", false); } catch (e) { wlOk = false; }
    navigator.wakeLock = { request: function () { throw new Error("NotAllowedError"); } };
    try { wakeWant("amb", true); wakeWant("amb", false); } catch (e) { wlOk = false; }
    navigator.wakeLock = { request: function () { return Promise.reject(new Error("NotAllowedError")); } };
    try { wakeWant("amb", true); await settle(2); wakeWant("amb", false); } catch (e) { wlOk = false; }
    ok(wlOk, "no API, a throwing or a refusing one: nothing throws");
    ok(!wake.asking, "and nothing is left waiting");
  } finally {
    delete document.hidden;
    wake.why.clear(); wakeSync();
    if (wlWas === undefined) delete navigator.wakeLock; else navigator.wakeLock = wlWas;
  }

  /* ---------- reading aloud ----------
     QuickJS has no speech synthesiser, which is the same position a browser
     without one is in — so the button has to be absent rather than broken, and
     the tests install a fake to drive the rest. */
  console.log("\n-- aloud: markup is not speech --");
  eq(ttsText("- TODO ring [[Radu]] about #work"), "TODO ring Radu about work.",
     "brackets and hashes are unwrapped, not spoken");
  eq(ttsText("id:: 66f0-dead-beef\n- real text"), "real text.",
     "logseq property lines are machine state, not prose");
  eq(ttsText("see https://example.com/x now"), "see link now.", "a url reads as a word");
  eq(ttsText("```\nnot speech\n```"), "Code block.", "a code block is named, not read");
  eq(ttsText("- see ((1234)) there"), "see there.", "an entry reference is not speech");
  eq(ttsText("**bold** and *thin*"), "bold and thin.", "emphasis is dropped");
  eq(ttsText("## A heading"), "A heading.", "a heading is a sentence");
  eq(ttsText("already ends."), "already ends.", "a full stop is not doubled");
  eq(ttsText(""), "", "nothing in, nothing out");

  console.log("-- aloud: chunking --");
  eq(ttsChunks("One. Two.").length, 1, "short text is one piece");
  var many = ttsChunks(new Array(20).join("A sentence of a certain length. "));
  ok(many.length > 1, "long text is split");
  ok(many.every(function (c) { return c.length <= TTS_CHUNK + 40; }),
     "no piece is far past the chunk size");
  eq(ttsChunks("").length, 0, "empty text is no pieces");

  console.log("-- aloud: with no synthesiser --");
  ok(!ttsApi(), "QuickJS has none");
  paintMode(true);
  eq($("#bAloud").style.display, "none", "so the button is not offered");
  hideToast();
  ttsAloud();
  ok(!tts.on, "and asking for it is survivable");
  has($("#toast").textContent, "cannot speak", "it says why");

  console.log("-- aloud: driving a fake one --");
  var spoke = [], cancels = 0, pending = [];
  window.SpeechSynthesisUtterance = function (t) { this.text = t; };
  window.speechSynthesis = {
    // deliberately NOT instant: a real one ends its utterance much later, and
    // the state while it is talking is the part worth asserting
    speak: function (u) { spoke.push(u.text); pending.push(u); },
    cancel: function () { cancels++; pending = []; },
  };
  /* What gets chunked is the spoken text, not the stored one: ttsText() drops
     the markdown first, so a fat row of links and syntax can still come out
     under a single TTS_CHUNK. So the row is the suite's own, judged by what
     would actually be said, rather than the journal's first long one, whose
     kind and state change with the day's data. */
  var aloudText = "- The **morning** watch logged a quiet sensor sweep and a [[Ship's garden]] check.\n";
  var longRow = await plant({ title: "Aloud probe", content: aloudText + aloudText + aloudText + aloudText });
  ok(ttsChunks("Aloud probe. " + ttsText(longRow.content)).length > 1, "an entry worth reading out");
  select(longRow.id);
  await settle(3);
  st.read = true;
  paintMode(true);
  ok($("#bAloud").style.display !== "none", "the button appears in the reader");
  click($("#bAloud"));
  await settle(2);
  ok(tts.on, "it starts talking");
  ok(tts.chunks.length > 1, "in pieces (" + tts.chunks.length + ")");
  eq(spoke.length, 1, "only the first piece has been handed over");
  has(spoke[0], (longRow.title || "").trim().slice(0, 12) || spoke[0],
      "and it opens with the title");
  eq($("#bAloud").getAttribute("aria-pressed"), "true", "the button says it is talking");
  has($("#bAloud").querySelector(".lg").innerHTML, "Stop", "and offers the way out");
  // each piece queues the next one, which is what keeps Chrome from truncating
  pending.shift().onend();
  await settle(2);
  eq(spoke.length, 2, "finishing a piece queues the next");

  console.log("-- aloud: everything that should stop it --");
  click($("#bAloud"));
  await settle(2);
  ok(!tts.on, "the button stops it");
  ok(cancels > 0, "and the synthesiser is actually cancelled");

  click($("#bAloud"));
  await settle(2);
  ok(tts.on, "talking again");
  setRead(false);
  await settle(2);
  ok(!tts.on, "leaving the reader for the form stops it");
  eq($("#bAloud").style.display, "none", "and the button goes with it");

  st.read = true;
  paintMode(true);
  click($("#bAloud"));
  await settle(2);
  var otherRow = null;
  for (var oi = 0; oi < st.all.length; oi++) {
    if (st.all[oi].id !== longRow.id && !st.all[oi].deleted) { otherRow = st.all[oi]; break; }
  }
  select(otherRow.id);
  await settle(3);
  ok(!tts.on, "opening another entry stops it");

  select(longRow.id);
  await settle(3);
  st.read = true;
  paintMode(true);
  click($("#bAloud"));
  await settle(2);
  ok(tts.on, "talking once more");
  closeEditor();
  await settle(2);
  ok(!tts.on, "closing the editor stops it");

  // a saved entry re-selects itself, and must not be cut off mid-sentence
  select(longRow.id);
  await settle(3);
  st.read = true;
  paintMode(true);
  click($("#bAloud"));
  await settle(2);
  select(longRow.id, true);
  await settle(3);
  ok(tts.on, "re-selecting the entry already open leaves it talking");
  ttsStop(true);

  console.log("-- aloud: it runs itself to the end --");
  st.read = true;
  paintMode(true);
  spoke = [];
  click($("#bAloud"));
  await settle(2);
  var guard = 0;
  while (pending.length && guard++ < 500) { pending.shift().onend(); await settle(1); }
  ok(!tts.on, "the last piece ends the reading");
  eq($("#bAloud").getAttribute("aria-pressed"), "false", "and the button steps back down");

  console.log("-- aloud: a log is read as one --");
  var kindWas = longRow.kind;
  longRow.kind = kindOf("work_log");
  st.read = true;
  paintMode(true);
  spoke = [];
  click($("#bAloud"));
  await settle(2);
  eq(spoke[0].indexOf("Captain's log, " + ttsDate(longRow.created_at_utc) + ". "), 0,
     "the work_log role's kind opens the way the show opens one, with the day it was written");
  ok(/^[A-Z][a-z]+day \d{1,2} [A-Z][a-z]+ \d{4}$/.test(ttsDate(longRow.created_at_utc)),
     "said as a plain date: " + ttsDate(longRow.created_at_utc));
  ttsStop(true);
  // not kindWas: the row picked may well be a work_log already
  longRow.kind = "harness_note";
  spoke = [];
  click($("#bAloud"));
  await settle(2);
  ok(spoke[0].indexOf("Captain's log") < 0, "any other kind is just read");
  ttsStop(true);
  longRow.kind = kindWas;
  closeEditor();
  unplant(longRow);

  console.log("-- the computer, out loud --");
  closeEditor();
  await settle(2);
  var citeRow = null;
  for (var ci = 0; ci < st.all.length; ci++) {
    if (!st.all[ci].deleted && st.all[ci].id !== longRow.id) { citeRow = st.all[ci]; break; }
  }
  var sse = function (o) { return "data: " + JSON.stringify(o) + "\n\n"; };
  var chatReplies = 0, chatFetch = fetch, chatBodies = [], chatBriefKey = "";
  fetch = function (url, o) {
    if (/\/engineer\/yeoman\/brief$/.test(String(url))) {
      chatBriefKey = (o && o.headers && o.headers["X-LCARS-Engineer-Key"]) || "";
      var bj = JSON.stringify({ role: "yeoman", title: "Yeoman", brief: "Each night, look for untidiness." });
      return Promise.resolve({ ok: true, status: 200, headers: { get: function () { return "application/json"; } },
        json: function () { return Promise.resolve(JSON.parse(bj)); }, text: function () { return Promise.resolve(bj); } });
    }
    if (String(url).indexOf("/chat") < 0) return chatFetch.apply(this, arguments);
    chatReplies++;
    chatBodies.push(JSON.parse(o.body));
    var body = sse({ type: "system", subtype: "init", session_id: "s-1" }) +
      sse({ type: "stream_event", event: { type: "content_block_start", content_block: { type: "text", text: "Let me look that up." } } }) +
      sse({ type: "stream_event", event: { type: "content_block_start", content_block: { type: "tool_use", id: "t1", name: "Bash" } } }) +
      sse({ type: "user", message: { content: [{ type: "tool_result", tool_use_id: "t1" }] } }) +
      sse({ type: "stream_event", event: { type: "content_block_start", content_block: { type: "text", text: "" } } }) +
      sse({ type: "stream_event", event: { type: "content_block_delta", delta: { type: "text_delta",
            text: "You last went **running** on Tuesday (#" + citeRow.id + ")." } } }) +
      sse({ type: "result", session_id: "s-1", duration_ms: 1200 }) +
      sse({ type: "lcars_exit", code: 0 });
    return Promise.resolve({ ok: true, status: 200, text: function () { return Promise.resolve(body); } });
  };
  // the chat panel paints once per frame, and this DOM has no frames
  var hadRaf = typeof requestAnimationFrame !== "undefined";
  if (!hadRaf) globalThis.requestAnimationFrame = function (f) { return setTimeout(f, 16); };
  var chatWas = chat.msgs, sidWas = chat.sid;
  chat.msgs = []; chat.sid = null;
  spoke = [];
  voiceHeard("computer ask when did I last go running");
  await settle(6);
  eq(chatReplies, 1, "a spoken question goes to the computer");
  eq(chat.msgs[0].text, "when did I last go running", "as it was said, bar the order");
  ok(st.sel && st.sel.id === citeRow.id, "the entry the answer cites opens");
  ok(tts.on && tts.chat, "and the answer is being said");
  has(spoke[0], "running on Tuesday", "the answer is what is said");
  ok(spoke[0].indexOf("Let me look") < 0, "not the narration on the way to a tool");
  has(spoke[0], "entry " + citeRow.id, "a citation is said as an entry number");
  ok(spoke[0].indexOf("**") < 0, "and the markdown is not read out");

  var selWas = st.sel.id;
  voiceHeard("computer next entry");
  eq(st.sel.id, selWas, "while it speaks, what the microphone hears is not an order");
  has(vx.note, "speaking", "the read-out says why");
  voiceHeard("be quiet");
  ok(!tts.on, "except being told to stop");
  voiceHeard("computer next entry");
  eq(st.sel.id, selWas, "the tail of the answer is still ignored just after");
  tts.hush = 0;

  has(String(voiceStart), "ttsUnlock()", "opening the microphone unlocks speech for later (Safari)");
  tts.unlocked = false;
  ttsUnlock();
  ok(tts.unlocked, "the unlock takes with a synthesiser present");
  pending = []; spoke = [];           // its silent utterance is not part of what follows

  console.log("-- the computer, out loud: the phone lets go of the microphone --");
  vHoldForTts = true;
  vx.on = true;
  chat.msgs = []; chat.sid = null;
  spoke = [];
  voiceHeard("computer ask when did I last go running");
  await settle(6);
  ok(vx.held, "the microphone is let go of before the answer is said");
  ok(tts.on && tts.chat, "and then it is said");
  has(spoke[spoke.length - 1], "running on Tuesday", "the answer, as before");
  vListen();
  ok(!vx.live && !vx.rec, "nothing reopens the microphone underneath the voice");
  var guard2 = 0;
  while (pending.length && guard2++ < 50) { pending.shift().onend(); await settle(1); }
  ok(!tts.on, "the answer runs to its end");
  ok(!vx.held, "and the microphone is taken back up");
  vx.on = false;
  vHoldForTts = false;
  tts.hush = 0;
  runTimers(1000);
  await settle(2);

  spoke = [];
  await chatSend("what about swimming");
  await settle(4);
  eq(chatReplies, 3, "a typed question is sent too");
  eq(spoke.length, 0, "but its answer is not spoken");
  closeOv();

  console.log("-- a crew role's report, talked over through the computer --");
  var yRep = { id: 990001, kind: "crew_yeoman", title: "Three things due", content: "- the boiler", created_at_utc: "2026-10-11 04:00:00" };
  lsSet("lcars.deck.engkey", "");
  var yNoKey = crewChat(yRep);
  await settle(2);
  ok(!$("#lcIn"), "without an engineer key none is asked for: no question between the tap and the thread");
  await yNoKey;
  await settle(3);
  eq(chat.role && chat.role.kind, "crew_yeoman", "the chat opens as the role");
  ok(chat.pre.indexOf("Each night") < 0, "only without the brief");
  chatNew(); closeOv();
  lsSet("lcars.deck.engkey", "k-123");
  await crewChat(yRep);
  await settle(3);
  ok($("#ov").classList.contains("on") && st.route && st.route.v === "chats", "Chat with Yeoman opens the computer's chat");
  has($(".chth .chtitle").textContent, "Yeoman", "headed as the role");
  eq(chat.id, "role-crew_yeoman", "in a thread of the role's own");
  eq(chat.msgs.length, 0, "a fresh thread");
  has(chat.pre, "Each night, look for untidiness.", "the role's brief is its context");
  eq(chatBriefKey, "k-123", "fetched from /engineer/<role>/brief with the engineer key");
  ok(!$(".chth .chctx").hidden, "with a context card");
  has($(".chth .chctx").textContent, "#990001", "naming the report");
  has($(".chth .chctx").textContent, "next message", "that goes with the next message");
  eq($(".chth .chbox").value, "", "the box is left for the captain's words");
  await chatSend("why the boiler?");
  await settle(4);
  var yBody = chatBodies[chatBodies.length - 1].message;
  has(yBody, "ship's Yeoman", "the first message carries who the computer speaks as");
  has(yBody, "- the boiler", "and the report");
  has(yBody, "why the boiler?", "then the captain's words");
  has(chat.msgs[0].text, "why the boiler?", "the bubble shows only the captain's words");
  ok(chat.msgs[0].text.indexOf("Each night") < 0, "not the context");
  eq(chat.pre, "", "the context is spent on the first message");
  await chatSend("and the dentist?");
  await settle(4);
  ok(chatBodies[chatBodies.length - 1].message.indexOf("Each night") < 0, "a follow-up goes alone, in the same thread");
  ok($(".chth .chctx").textContent.indexOf("next message") < 0, "the card stays, no longer pending");
  eq(chatFind("role-crew_yeoman").msgs.length, 4, "the role's thread holds its talk");
  ok(chatComputer().msgs.every(function (m) { return String(m.text || "").indexOf("boiler") < 0; }),
     "and the computer's thread is untouched by it");

  console.log("-- one chat: the thread, its feedback and its model --");
  closeOv();
  openChat();
  ok($(".chth .chlog") && $(".chth .chbox") && $(".chth .chsend"), "the computer's thread has a log, a box and Send");
  ok($("#dlg").className.indexOf("chats") >= 0, "drawn as a screen of its own");
  ok(/^computer-\d+$/.test(st.route && st.route.a[0]), "at chats/computer-<n>");
  ok($("#chclose"), "with a way back (buttons.py's Close)");
  ok($(".chth .chsend").disabled, "Send is not offered with nothing to send");
  $(".chth .chbox").value = "hello"; $(".chth .chbox").oninput();
  ok(!$(".chth .chsend").disabled, "and is once there is");
  has($(".chth .chmodel").textContent, chatModelName(chat.model), "the chip names the model");
  // the bubble before the network: chatSend's first frame is synchronous
  var c1 = chatSend();
  var c1u = chat.msgs[chat.msgs.length - 2];
  eq(c1u.state, "sending", "a sent message is marked sending at once");
  has($(".chth .chlog").innerHTML, "sending", "and shows it");
  eq($(".chth .chbox").value, "", "the box clears at once");
  eq($(".chth .chsend").textContent, "Stop", "Send is Stop while it works");
  has($(".chth .chhdr .chstat").textContent, "working", "and the header says it works");
  await c1; await settle(4);
  eq(c1u.state, "", "the first word back is delivery: the mark goes");
  eq($(".chth .chsend").textContent, "Send", "Send again when it is done");
  var c1kids = $(".chth .chlog").children.length;
  eq(c1kids, chat.msgs.length, "a child of the log per message");
  var c1first = $(".chth .chlog").children[0];
  ok(c1first._m === chat.msgs[0], "drawn from its message");
  has($(".chth .chlog").innerHTML, "1 step", "an answer's tool calls fold into one chip");
  ok($(".chth .chlog").innerHTML.indexOf("$ ") < 0, "folded, the commands are not shown");
  click($(".chth .chlog").querySelector("[data-tools]"));
  has($(".chth .chlog").innerHTML, "ctool", "a tap on the chip opens it");
  ok($(".chth .chlog").children[0] === c1first, "and redraws only that message, not the log");

  // the model: the chip at once, a line in the thread, the next POST carries it
  var mWas = chat.model, mTo = mWas === "opus" ? "haiku" : "opus";
  click($(".chth .chmodel"));
  ok(!$(".chth .chscrim").hidden, "the chip opens the picker");
  eq($(".chth .chsheet").querySelectorAll("[data-model]").length, CHAT_MODELS.length, "every model the server takes");
  click($(".chth .chsheet").querySelector('[data-model="' + mTo + '"]'));
  ok($(".chth .chscrim").hidden, "a choice closes it");
  eq(chat.model, mTo, "and is the thread's model");
  has($(".chth .chmodel").textContent, chatModelName(mTo), "the chip changes at once");
  has(chat.msgs[chat.msgs.length - 1].text, "from here", "the thread says so where it happened");
  await chatSend("and now?"); await settle(4);
  eq(chatBodies[chatBodies.length - 1].model, mTo, "the next message goes with it");
  chatModelSet("Sonnet");
  eq(chat.model, "sonnet", "a model is chosen by name too (the voice order)");
  chatModelSet("gpt");
  eq(chat.model, "sonnet", "and a name that is none changes nothing");

  // not delivered: the bubble says so with Retry, and the words come back
  var cOk = fetch;
  fetch = function (url) {
    if (String(url).indexOf("/chat") >= 0) return Promise.reject(new Error("offline"));
    return cOk.apply(this, arguments);
  };
  await chatSend("are you there?"); await settle(2);
  var cFail = chat.msgs[chat.msgs.length - 1];
  eq(cFail.role + ":" + cFail.state, "user:failed", "a message that never got there is marked failed");
  has($(".chth .chlog").innerHTML, "not sent", "on its bubble");
  ok($(".chth .chlog").querySelector("[data-retry]"), "with Retry");
  eq($(".chth .chbox").value, "are you there?", "and its words are back in the box");
  fetch = cOk;
  var cN = chat.msgs.length;
  click($(".chth .chlog").querySelector("[data-retry]"));
  await settle(4);
  ok(chat.msgs.every(function (m) { return m.state !== "failed"; }), "Retry sends it again");
  eq(chat.msgs.length, cN + 1, "as the same bubble, now answered");
  eq($(".chth .chbox").value, "", "and takes it out of the box");

  // Stop: says it is stopping, then the answer says stopped
  var hadAc = typeof AbortController !== "undefined";
  if (!hadAc) globalThis.AbortController = function () {
    var sg = { aborted: false, fns: [], addEventListener: function (t, f) { this.fns.push(f); } };
    this.signal = sg;
    this.abort = function () { sg.aborted = true; sg.fns.forEach(function (f) { f(); }); };
  };
  fetch = function (url, o) {
    if (String(url).indexOf("/chat") < 0) return cOk.apply(this, arguments);
    return new Promise(function (res, rej) {
      o.signal.addEventListener("abort", function () { var e = new Error("aborted"); e.name = "AbortError"; rej(e); });
    });
  };
  var cStop = chatSend("a long one");
  eq($(".chth .chsend").textContent, "Stop", "working: Send is Stop");
  $(".chth .chbox").value = "x"; $(".chth .chbox").oninput();
  eq($(".chth .chsend").textContent, "Send", "something typed: Send again");
  $(".chth .chbox").value = ""; $(".chth .chbox").oninput();
  click($(".chth .chsend"));
  eq($(".chth .chsend").textContent, "Stopping…", "Stop says it is stopping at once");
  await cStop; await settle(2);
  eq(chat.msgs[chat.msgs.length - 1].err, "stopped", "and the answer is marked stopped");
  eq(chat.msgs[chat.msgs.length - 2].state, "", "a stopped question was delivered, not failed");
  fetch = cOk;
  if (!hadAc) delete globalThis.AbortController;

  // the voice orders, and that none takes another's phrase
  [["send it", "send it"], ["stop the answer", "stop the answer"], ["switch model to opus", "switch model to {*}"],
   ["use model haiku", "switch model to {*}"], ["which model", "which model"], ["read the last message", "read the last message"],
   ["new chat", "new chat"], ["stop the timer", "stop the timer"], ["read aloud", "read aloud"],
   ["dismiss reyes", "dismiss {*}"], ["dismiss this engineer", "dismiss {*}"], ["dismiss engineer reyes", "dismiss engineer {*}"],
   ["dismiss", "dismiss"], ["stand down", "stand down"], ["dismiss the suggestions", "dismiss the suggestions"],
   ["bring back this chat", "bring back this chat"], ["unarchive this chat", "bring back this chat"],
   ["mark read", "mark read"], ["mark this chat read", "mark read"], ["mark all read", "mark all read"],
   ["clear the conversation", "clear the conversation"], ["clear the field", "clear the field"],
   ["earlier conversation first job", "earlier conversation {*}"], ["earlier conversations", "earlier conversations"],
   ["the current conversation", "current conversation"],
   ["close the chat", "close the chat window"], ["close the chats", "close the chats"], ["close", "close"], ["read it out", "read aloud"]].forEach(function (x) {
    var hit = vMatch(vWords(x[0]), 0);
    eq(hit && hit.cmd.say, x[1], "\"" + x[0] + "\" is " + x[1]);
  });

  console.log("-- a phone's voice: through the speaker or the earpiece --");
  [["voice through the speaker", "voice through the speaker"], ["use the speaker", "voice through the speaker"],
   ["use the loudspeaker", "voice through the speaker"], ["voice through the earpiece", "voice through the earpiece"],
   ["use the earpiece", "voice through the earpiece"], ["voice on", "voice on"], ["voice off", "voice off"]].forEach(function (x) {
    var hit = vMatch(vWords(x[0]), 0);
    eq(hit && hit.cmd.say, x[1], "\"" + x[0] + "\" is " + x[1]);
  });
  ok(VCMDS.some(function (c) { return c.say === "voice through the earpiece" && /microphone stays open/.test(c.help); }), "the help says what each does");
  var outGum = navigator.mediaDevices, outN = 0, outStops = 0, outConv = conv.cur, outPhone = convHoldForTts;
  var outStream = function () { return { getTracks: function () { return [{ stop: function () { outStops++; } }]; } }; };
  navigator.mediaDevices = { getUserMedia: function () { outN++; return Promise.resolve(outStream()); } };
  var oc = { conv: true, down: true, open: true, held: false, takeT: 0, heard: false, final: [], interim: "", stream: outStream(), node: { n: 1 },
             src: { disconnect: function () { oc.srcGone = true; } },
             ctx: { createMediaStreamSource: function (st) { return { st: st, connect: function (nd) { this.to = nd; }, disconnect: function () {} }; } } };
  conv.cur = oc;
  convHoldForTts = false;
  ok(!paletteRows().some(function (r) { return /voice through the/.test(r.label); }), "off a phone the palette has no output row");
  var oRun = chatSayRun(chat);
  sayState(oRun, "pending");
  ok(!oc.held && oc.stream && !outStops, "off a phone a reply leaves the conversation's microphone open");
  sayState(oRun, "");
  convHoldForTts = true;     // the phone's path
  convSetOutput("speaker");
  ok(paletteRows().some(function (r) { return r.label === "chat · voice through the earpiece"; }), "on a phone, a palette row for the other way");
  var quietWas = sayQuiet, quiets = 0;   // counted: this suite has a say of its own, so the page's is out of reach
  sayQuiet = function (ms) { quiets++; return quietWas(ms); };
  oRun = chatSayRun(chat);
  sayState(oRun, "pending");
  ok(oc.held && !oc.stream && oc.srcGone && outStops === 1, "the speaker: a reply begun drops the capture, its tracks stopped");
  ok(quiets === 1 && sayQuietS() > 0, "and holds the reply's first sound for the switch (sayQuiet)");
  sayState(oRun, "playing");
  ok(outN === 0, "not taken again while it plays");
  sayState(oRun, "");
  await pump();
  ok(!oc.stream && outN === 0, "the run over: not taken again before the settle");
  runTimers(V_HOLD_SETTLE); await settle(3);
  ok(oc.stream && outN === 1 && !oc.held && oc.src.to === oc.node, "taken again after V_HOLD_SETTLE, into the same graph");
  oRun = chatSayRun(chat);
  sayState(oRun, "pending");
  sayStop();
  runTimers(V_HOLD_SETTLE); await settle(3);
  ok(oc.stream && outN === 2 && outStops === 2, "a reply stopped: dropped, then taken again");
  vMatch(vWords("voice through the earpiece"), 0).cmd.fn();
  eq(conv.out, "earpiece", "said: the earpiece, at once");
  eq(lsGet("lcars.deck.convout", ""), "earpiece", "remembered on this device");
  oRun = chatSayRun(chat);
  sayState(oRun, "pending");
  ok(!oc.held && oc.stream && outStops === 2, "the earpiece: a reply leaves the capture open");
  convSetOutput("speaker");
  ok(oc.held && !oc.stream && outStops === 3, "the speaker chosen mid-reply: dropped at once");
  convSetOutput("earpiece");
  await settle(3);
  ok(!oc.held && oc.stream && outN === 3, "the earpiece chosen mid-reply: taken again at once");
  sayStop();
  vMatch(vWords("voice through the speaker"), 0).cmd.fn();
  eq(conv.out, "speaker", "said: the speaker");
  conv.cur = outConv; convHoldForTts = outPhone; navigator.mediaDevices = outGum; sayQuiet = quietWas;
  runTimers(1000); await settle(2);
  console.log("-- one chat: quoting a part of an earlier message (docs/design/chat.md 2.10) --");
  eq(chatQuoteBlock("  two\n\n\n\nlines  "), "> two\n>\n> lines", "a quote is '> ' lines, trimmed, blank runs closed up");
  var qLong = chatQuoteBlock(new Array(120).join("word "));
  ok(/…$/.test(qLong) && qLong.length <= CHAT_QUOTE_MAX + 4, "a long one is cut with an ellipsis, near " + CHAT_QUOTE_MAX);
  ok(/word…$/.test(qLong), "on a word");
  eq(chatUnquoted("> theirs\n\nmine"), "mine", "a message's words outside its quotes");
  // a thread of its own: a question and two answers
  chat.msgs.push({ role: "user", text: "what is on the rail?" },
                 { role: "asst", parts: [{ t: "text", s: "The **rail** holds the years.\n\nIt can be dragged." }] },
                 { role: "asst", parts: [{ t: "text", s: "A second answer, about the calendar." }] });
  chatDraw();
  var qKids = $(".chth .chlog").children, qN = qKids.length;
  var qA = qKids[qN - 2], qB = qKids[qN - 1];
  ok(qA.querySelector("[data-quote]") && qA.querySelector("[data-reply]"), "a finished message has Quote and Reply");
  $(".chth .chbox").value = "";
  $(".chth .chbox").blur();
  click(qA.querySelector("[data-reply]"));
  eq($(".chth .chbox").value, "> The **rail** holds the years.\n>\n> It can be dragged.\n\n", "Reply quotes the message whole, a blank line after it");
  ok(document.activeElement === $(".chth .chbox"), "the box has the focus, in the same tap");
  ok(!$(".chth .chquotes").hidden && $(".chth .chquotes").querySelectorAll(".chqchip").length === 1, "the box's quote shows as a chip above it");
  $(".chth .chbox").value += "my answer"; $(".chth .chbox").oninput();
  // a selection inside the second answer: Quote takes those words
  var qSelWas = window.getSelection;
  window.getSelection = function () {
    return { isCollapsed: false, rangeCount: 1, toString: function () { return " the calendar "; },
             getRangeAt: function () { return { startContainer: qB.querySelector(".chbub"), getBoundingClientRect: function () { return {}; } }; } };
  };
  click(qB.querySelector("[data-quote]"));
  window.getSelection = qSelWas;
  eq($(".chth .chbox").value, "> The **rail** holds the years.\n>\n> It can be dragged.\n\nmy answer\n\n> the calendar\n\n",
     "Quote takes the selected words, after what is typed");
  eq($(".chth .chquotes").querySelectorAll(".chqchip").length, 2, "two quotes, two chips");
  // and a selection the tap just cleared (a phone's) still counts
  chatSelLast = { el: qA, text: "dragged", gone: Date.now() };
  click(qA.querySelector("[data-quote]"));
  ok(/> dragged\n\n$/.test($(".chth .chbox").value), "Quote on a phone takes the selection its tap cleared");
  chatSelLast = null;
  click($(".chth .chquotes").querySelectorAll("[data-unq]")[2]);
  eq($(".chth .chquotes").querySelectorAll(".chqchip").length, 2, "x on a chip takes that quote out");
  ok($(".chth .chbox").value.indexOf("dragged\n") < 0 && $(".chth .chbox").value.indexOf("my answer") >= 0, "and only it");
  $(".chth .chbox").value += "and this"; $(".chth .chbox").oninput();
  var qSent = $(".chth .chbox").value.trim();
  await chatSend(); await settle(4);
  eq(chatBodies[chatBodies.length - 1].message, qSent, "what is sent is plain markdown");
  ok($(".chth .chquotes").hidden, "and the chips go with the box's words");
  var qMe = Array.from($(".chth .chlog").children).filter(function (k) { return k._m && k._m.text === qSent; })[0];
  eq(qMe.querySelectorAll(".chquote").length, 2, "the sent bubble draws its two quotes as quotes");
  has(qMe.innerHTML, "my answer", "and the words between them as words");
  eq(chatPreview({ msgs: [{ role: "user", text: qSent }] }), "You: my answer\n\nand this", "the list's preview is the answer, not the quote");
  click(qMe.querySelectorAll(".chquote")[1]);
  ok(qB.classList.contains("chflash"), "a tap on a quote goes to the message it came from");
  click(qMe.querySelectorAll(".chquote")[0]);
  ok(qA.classList.contains("chflash"), "the markdown's bold is no bar to finding it");
  // one block of a crew report at a time: a swipe or the margin's handle
  var bRep = "Morning report.\n\n- the **kettle** is due\n- the boiler\n  - its valve\n  - its pump\n- the dentist";
  chat.msgs.push({ role: "asst", report: 9000001, e: { id: 9000001, kind: "crew_ops", content: bRep, created_at_utc: "2026-10-14 08:00:00" },
                   parts: [{ t: "text", s: bRep }] });
  chatDraw();
  var bEl = $(".chth .chlog").children[$(".chth .chlog").children.length - 1], bLis = bEl.querySelectorAll("li");
  ok(bEl.querySelector(".chrep") && bLis.length === 5, "a crew report in the log, its bullets drawn");
  eq(chatBlockAt(bLis[0].firstChild || bLis[0]), bLis[0], "a bullet is a block of its own");
  eq(chatBlockText(bLis[0]), "the kettle is due", "a bullet quotes itself, not its siblings");
  eq(chatBlockText(bLis[1]), "the boiler\n- its valve\n- its pump", "a bullet with a branch quotes it with its children");
  eq(chatBlockText(bLis[2]), "its valve", "a nested bullet quotes itself");
  eq(chatBlockText(bEl.querySelector(".md p")), "Morning report.", "a paragraph quotes itself");
  ok(chatBlockAt(bEl.querySelector(".chrepid")) === null, "the report's header line is no block");
  $(".chth .chbox").value = ""; $(".chth .chbox").oninput();
  ok(chatBlockQuote(bLis[0]), "the first bullet quoted");
  $(".chth .chbox").value += "answer one"; $(".chth .chbox").oninput();
  chatBlockQuote(bLis[1]);
  $(".chth .chbox").value += "answer two"; $(".chth .chbox").oninput();
  chatBlockQuote(bLis[4]);
  eq($(".chth .chbox").selectionStart, $(".chth .chbox").value.length, "the caret on the answer line of the block just quoted");
  $(".chth .chbox").value += "answer three"; $(".chth .chbox").oninput();
  var bWant = "> the kettle is due\n\nanswer one\n\n> the boiler\n> - its valve\n> - its pump\n\nanswer two\n\n> the dentist\n\nanswer three";
  eq($(".chth .chbox").value, bWant, "three bullets in turn, each answered under it, the answers untouched");
  eq($(".chth .chquotes").querySelectorAll(".chqchip").length, 3, "a chip for each");
  hideToast();
  ok(!chatBlockQuote(bLis[0]), "the same bullet again is not quoted twice");
  eq($(".chth .chbox").value, bWant, "the box unchanged");
  has($("#toast").textContent, "already quoted", "and a toast says so");
  eq($(".chth .chbox").selectionStart, bWant.indexOf("answer one") + 10, "the caret to its answer");
  click($(".chth .chquotes").querySelector('[data-qcar="1"]'));
  eq($(".chth .chbox").selectionStart, bWant.indexOf("answer two") + 10, "a tap on a chip: the caret at that quote's answer");
  $(".chth .chbox").value = "> x\n\n> y\n\n"; $(".chth .chbox").oninput();
  click($(".chth .chquotes").querySelector('[data-qcar="0"]'));
  eq($(".chth .chbox").value, "> x\n\n\n\n> y\n\n", "a quote with no answer gets a line for it");
  eq($(".chth .chbox").selectionStart, 5, "and the caret there");
  // a swipe: sideways past the mark quotes; up and down is the log's scroll
  $(".chth .chbox").value = ""; $(".chth .chbox").oninput();
  var bT = function (el, type, x, y) { return dispatch(el, type, { touches: type === "touchend" ? [] : [{ clientX: x, clientY: y }] }); };
  bT(bLis[4], "touchstart", 20, 100); bT(bLis[4], "touchmove", 26, 160); bT(bLis[4], "touchmove", 30, 220); bT(bLis[4], "touchend");
  eq($(".chth .chbox").value, "", "a vertical move is a scroll, not a quote");
  bT(bLis[4], "touchstart", 20, 100); bT(bLis[4], "touchmove", 50, 102); bT(bLis[4], "touchend");
  eq($(".chth .chbox").value, "", "a short swipe springs back unquoted");
  bT(bLis[4], "touchstart", 20, 100); bT(bLis[4], "touchmove", 50, 102);
  bT(bLis[4], "touchmove", 110, 104);
  ok(/translateX/.test(bLis[4].style.transform), "the bullet follows the finger");
  ok(!$(".chth .chqblk").hidden && $(".chth .chqblk").classList.contains("ready"), "the quote mark shows past the mark");
  bT(bLis[4], "touchend");
  eq($(".chth .chbox").value, "> the dentist\n\n", "let go past it: that bullet quoted");
  ok(!bLis[4].style.transform && $(".chth .chqblk").hidden, "and it springs back");
  $(".chth .chbox").value = ""; $(".chth .chbox").oninput();
  await chatSend(bWant); await settle(4);
  eq(chatBodies[chatBodies.length - 1].message, bWant, "sent: three quotes and three answers, in order");

  // "quote that": the last answer when nothing is selected
  $(".chth .chbox").value = ""; $(".chth .chbox").oninput();
  chatQuoteSaid();
  ok(/^> /.test($(".chth .chbox").value), "\"quote that\" quotes the last answer");
  ok($(".chth .chbox").value.indexOf("my answer") < 0, "the answer's words, not the captain's");
  $(".chth .chbox").value = ""; $(".chth .chbox").oninput();
  [["quote that", "quote that"], ["reply to that", "quote that"], ["quote the last answer", "quote that"]].forEach(function (x) {
    var hit = vMatch(vWords(x[0]), 0);
    eq(hit && hit.cmd.say, x[1], "\"" + x[0] + "\" is " + x[1]);
  });
  ok(KEYMAP.get(">") && KEYMAP.get(">").when(), "> quotes in a chat");

  closeOv();
  chatNew();

  console.log("-- the thread's mount: several up at once (docs/design/chat-dock.md 0) --");
  closeOv(); runTimers(); await settle(1);
  openChat();
  var mFull = chatFull(), tA = chatShown();
  ok(mFull && mFull.mode === "full" && chatFm() === mFull, "the full view is a mount, and the focused one");
  ok(!$("#chq") && !$("#chlog") && !$("#chsend") && !$("#chth"), "the pane has no fixed ids: its elements are the mount's");
  ok(tA && mFull.id === tA.id && chat === tA, "chat is the focused mount's conversation");
  var mHost = document.createElement("section");
  mHost.className = "chpane chth";
  document.body.appendChild(mHost);
  var tB = chatNewThread();
  var mB = chatsMount(mHost, tB, { mode: "test" });
  eq(chatLive().length, 2, "two mounts alive at once");
  ok(mB.log !== mFull.log && mB.box !== mFull.box && mB.send !== mFull.send, "each with its own log, box and Send");
  ok(chat === tB && chatShown() === tB, "the newest mounted is focused: chat is its conversation");
  eq(mFull.id, tA.id, "and the full view still shows its own");
  chatFocus(mFull);
  ok(chat === tA && chatShown() === tA, "focusing the other moves chat to its conversation");
  mB.box.value = "typed in B"; mB.box.oninput();
  ok(!mB.send.disabled && mFull.send.disabled, "a box's words enable its own Send only");
  ok(chat === tA, "typing in a mount's box does not take chat from the focused one by itself");
  mB.box.value = ""; mB.box.oninput();
  // a stream into each: one frame paints both, each only its own thread
  var aKids = mFull.log.children.length, aFirst = mFull.log.children[0], aHad = tA.msgs.length;
  tA.msgs.push({ role: "user", text: "only in A" }, { role: "asst", parts: [{ t: "text", s: "streaming A" }], live: true });
  tB.msgs.push({ role: "user", text: "only in B" }, { role: "asst", parts: [{ t: "text", s: "streaming B" }], live: true });
  chatPaint(tA); chatPaint(tB);
  ok(mFull.dirty && mB.dirty, "a stream marks the mount showing its thread dirty");
  eq(mFull.log.children.length, aKids, "and paints nothing until the frame");
  await settle(2);
  ok(!mFull.dirty && !mB.dirty, "one frame painted every dirty mount");
  has(mFull.log.innerHTML, "only in A", "A's thread in A's log");
  has(mB.log.innerHTML, "only in B", "B's thread in B's log");
  ok(mFull.log.innerHTML.indexOf("only in B") < 0 && mB.log.innerHTML.indexOf("only in A") < 0, "neither in the other's");
  ok(!aHad || mFull.log.children[0] === aFirst, "the bubbles already there are kept, not redrawn");
  var bLive = mB.log.children[mB.log.children.length - 1], aLive = mFull.log.children[mFull.log.children.length - 1];
  tB.msgs[tB.msgs.length - 1].parts[0].s += " more";
  chatPaint(tB);
  ok(mB.dirty && !mFull.dirty, "a delta in B marks only B's mount");
  await settle(2);
  has(mB.log.innerHTML, "streaming B more", "and B's live bubble grows");
  ok(mFull.log.children[mFull.log.children.length - 1] === aLive, "A's log untouched by B's delta");
  ok(bLive.isConnected !== undefined, "(the shim knows isConnected)");
  tA.msgs.splice(-2); tB.msgs.splice(-2);
  // engineers' polls are each their own: stopping one leaves the other's
  var eX = engThread("mtx1", "Mount X"), eY = engThread("mtx2", "Mount Y");
  engStop(eX);
  ok((eX.eng.gen || 0) === 1 && !(eY.eng.gen || 0), "an engineer's poll is stopped by itself, another's left running");
  engStop();
  ok(eY.eng.gen === 1 && eX.eng.gen === 2, "and closeOv's stops every one");
  chats.list.splice(chats.list.indexOf(eX), 1); chats.list.splice(chats.list.indexOf(eY), 1);
  // a mount whose element goes is dropped, and the focus with it
  chatFocus(mB);
  document.body.removeChild(mHost);
  eq(chatLive().length, 1, "a mount whose element is gone is no longer alive");
  ok(chatFm() === null && chatShown() === null, "the focused one gone: no chat on screen until another is focused");
  chatFocus(mFull);
  ok(chatShown() === tA, "focused again: the full view's thread");
  chats.list.splice(chats.list.indexOf(tB), 1);
  chatSave();

  console.log("-- the chat dock (docs/design/chat-dock.md Part 1) --");
  closeOv(); runTimers(); await settle(1);
  TEST.desk = false; dockSync();
  ok(!dockAllowed() && !$("#dock"), "no desk (a phone, a narrow window, a touch screen): no dock at all");
  TEST.desk = true;
  var dA = chatNewThread(), dB = chatNewThread(), dC = chatNewThread(), dD = chatNewThread();
  dA.msgs.push({ role: "user", text: "dock question A" }, { role: "asst", parts: [{ t: "text", s: "dock answer A" }] });
  dA.unread = 2;
  lsSet("lcars.dock", { list: "pill", wins: [{ id: dA.id }, { id: dB.id, min: true }, { id: "computer-gone-9" }], focus: [dB.id, dA.id] });
  dockLoad(); dockSync(); runTimers(); await settle(1);
  ok($("#dock") && !$("#dock").hidden && dock.shown, "lcars.dock restored at a desk: the dock is up");
  eq(dock.wins.map(function (w) { return w.id; }).join(","), dA.id + "," + dB.id, "its windows in order, an unknown id dropped");
  eq($("#dock").querySelectorAll(".dkwins .dkwin").length, 1, "the open one a window");
  eq($("#dock").querySelectorAll(".dktabs .dktab").length, 1, "the minimised one a tab");
  eq($("#dock").querySelector(".dktab").dataset.tab, dB.id, "B's");
  var dmA = dockMounts.get(dA.id);
  ok(dmA && dmA.mode === "dock" && dmA.el.isConnected, "the window is a mount of the thread pane");
  has(dmA.log.innerHTML, "dock answer A", "drawn with its conversation");
  ok(!dmA.el.querySelector("#chtalk") && !dmA.el.querySelector("#talkptt"), "a window has no talk row (one microphone, the full view's)");
  eq(dA.unread, 2, "restored without the focus, it is not read by being shown");
  ok(!chatSees(dA), "nor counted as on screen");
  has($("#dock").querySelector(".dkpill").textContent, "Chats", "the pill");
  ok(/·\s*\d/.test($("#dock").querySelector(".dkpill").textContent), "with the count waiting");
  eq(dmA.el.querySelector(".dkun").textContent, "2", "the window's header says its unread");
  // the focus into it: read (the shim's log is at its end), and "the chat"
  dmA.box.focus(); dockFocusIn(dmA);
  ok(chatSees(dA) && dA.unread === 0, "focused at its end: read");
  ok(chat === dA && chatShown() === dA, "and chat is its conversation, for the voice orders");
  // a reply in a conversation with no window: the pill counts it, nothing opens
  dD.unread = 1; chatListPaint();
  ok(!dockHas(dD.id) && !dockMounts.get(dD.id), "a message in a closed conversation opens no window");
  has($("#dock").querySelector(".dkpill").textContent, String(chatUnreadTotal() + engAnswerCount()), "the pill counts it");
  dD.unread = 0;
  // acts change no route
  var dH = history._i, dU = curRel();
  dockOpen(dC.id); runTimers(); await settle(1);
  ok(dockMounts.get(dC.id) && document.activeElement === dockMounts.get(dC.id).box, "a window opened by an act takes the focus, in its box");
  eq(dock.focus[0], dC.id, "the most recently focused");
  dockMin(dC.id); runTimers(); await settle(1);
  ok(!dockMounts.get(dC.id) && dockWin(dC.id).min, "minimised to its tab");
  dockOpen(dC.id); runTimers(); await settle(1);
  ok(dockMounts.get(dC.id) && !dockWin(dC.id).min, "a tab opens again");
  dockMounts.get(dC.id).box.value = "half a thought";
  dockClose(dC.id); runTimers(); await settle(1);
  ok(!dockHas(dC.id), "closed: gone from the dock");
  eq(dC.draft, "half a thought", "its draft kept on the conversation");
  ok(chatFind(dC.id), "the conversation untouched");
  var dUndo = $("#toast").querySelector("button");
  ok(dUndo && dUndo.textContent === "Undo", "Closed · Undo");
  click(dUndo); runTimers(); await settle(1);
  ok(dockHas(dC.id), "Undo brings the window back");
  eq(dockMounts.get(dC.id) && dockMounts.get(dC.id).box.value, "half a thought", "with the draft");
  eq(history._i, dH, "opening, minimising, closing: nothing on the history");
  eq(curRel(), dU, "nor in the url");
  eq(lsGet("lcars.dock", {}).wins.length, 3, "lcars.dock written on every change");
  // overflow: the least recently focused fold first
  var dW = window.innerWidth;
  window.innerWidth = 1000;
  dock.focus = [dC.id, dB.id, dA.id];
  dockRender();
  ok(!$("#dock").querySelector(".dkovf").hidden, "too narrow for all: the overflow tab");
  has($("#dock").querySelector(".dkovf").textContent, "+1 more", "+1 more");
  eq(dock.folded.join(","), dA.id, "the least recently focused folded");
  dockOpen(dA.id); runTimers(); await settle(1);
  ok(dockMounts.get(dA.id) && dock.folded.indexOf(dA.id) < 0, "picked, it opens");
  eq(dock.folded.join(","), dC.id, "and the least recently focused open one folds in its stead");
  window.innerWidth = dW;
  dockRender();
  ok($("#dock").querySelector(".dkovf").hidden, "room again: no overflow");
  // the list panel
  click($("#dock").querySelector(".dkpill")); runTimers(); await settle(1);
  ok($("#dock").querySelector(".dklist") && dock.list === "open", "the pill opens the list panel");
  ok(document.activeElement === $("#dock").querySelector(".dkfind"), "its search focused");
  ok($("#dock").querySelector('.dkrows .chrow[data-id="' + dA.id + '"]'), "the same rows as the full list");
  ok($("#dock").querySelector('.dkrows .chrow.dkon[data-id="' + dA.id + '"]'), "a row whose window is open is marked");
  click($("#dock").querySelector('.dkrows .chrow[data-id="' + dD.id + '"]')); runTimers(); await settle(1);
  ok(dockMounts.get(dD.id) && dock.list === "open", "a row opens its window; the list stays open");
  // the full view hides the dock, and it comes back as it was
  dockFull(dD.id); runTimers(); await settle(1);
  ok(chatUp() && !dock.shown && $("#dock").hidden, "⤢: the full view, the dock hidden");
  eq(chatShown(), dD, "on that conversation");
  ok(!dockMounts.size, "its windows unmounted meanwhile");
  closeOv(); runTimers(); await settle(1);
  ok(dock.shown && dockMounts.get(dD.id) && dockMounts.get(dA.id), "closed: the dock back as it was");
  ok(chatFm() && chatFm().mode === "dock", "and \"the chat\" is a window again");
  // the keys
  ok(KEYMAP.get("B") && /dockKey/.test(String(KEYMAP.get("B").fn)), "B is the dock");
  ok(VCMDS.some(function (c) { return c.fn && /dockKey/.test(String(c.fn)); }), "and has a voice order");
  // the voice orders (1.9), and what they must not collide with
  [["open the chat window for reyes", "open the chat window for {*}"], ["chat window for number one", "open the chat window for {*}"],
   ["pop out the yeoman", "open the chat window for {*}"], ["dock reyes", "open the chat window for {*}"],
   ["minimise the chat", "minimise the chat"], ["minimize it", "minimise the chat"], ["minimize the chat window", "minimise the chat"],
   ["close the chat window", "close the chat window"], ["close the window", "close the chat window"],
   ["close the chat", "close the chat window"], ["close the chats", "close the chats"],
   ["restore the chat", "restore the chat"], ["unminimize the chat", "restore the chat"], ["open the chat again", "restore the chat"],
   ["expand the chat", "expand the chat"], ["open it full", "expand the chat"], ["full screen chat", "expand the chat"],
   ["show the dock", "show the dock"], ["open the dock", "show the dock"], ["the dock", "show the dock"], ["dock", "show the dock"],
   ["hide the dock", "hide the dock"], ["collapse the dock", "hide the dock"],
   ["next chat window", "next chat window"], ["next window", "next chat window"], ["switch window", "next chat window"],
   ["close all chat windows", "close all chat windows"], ["close all the windows", "close all chat windows"],
   ["into the dock", "into the dock"],
   ["close the conversation", "end conversation"], ["talk to reyes", "talk to {*}"], ["open a chat with reyes", "talk to {*}"],
   ["next unread", "next unread"], ["dismiss", "dismiss"], ["show only tasks", "show only {*}"]].forEach(function (x) {
    var hit = vMatch(vWords(x[0]), 0);
    eq(hit && hit.cmd.say, x[1], "\"" + x[0] + "\" is " + x[1]);
  });
  // by voice: the focused window
  dockMounts.get(dD.id).box.focus(); dockFocusIn(dockMounts.get(dD.id));
  vMatch(vWords("minimise it"), 0).cmd.fn(); runTimers(); await settle(1);
  ok(dockWin(dD.id).min, "\"minimise it\": the focused window to its tab");
  vMatch(vWords("restore the chat"), 0).cmd.fn(); runTimers(); await settle(1);
  ok(!dockWin(dD.id).min && dockMounts.get(dD.id), "\"restore the chat\": the last minimised open again");
  vMatch(vWords("close the chat"), 0).cmd.fn(); runTimers(); await settle(1);
  ok(!dockHas(dD.id), "\"close the chat\" with no full view up: the chat window");
  await vMatch(vWords("chat window for worf"), 0).cmd.fn({ text: "worf" }); runTimers(); await settle(1);
  has($("#toast").textContent, "no chat with worf", "a name not found says so");
  vMatch(vWords("hide the dock"), 0).cmd.fn(); runTimers(); await settle(1);
  ok(dock.list === "pill" && dock.shown, "\"hide the dock\": the list to its pill");
  vMatch(vWords("hide the dock"), 0).cmd.fn(); runTimers(); await settle(1);
  ok(dock.hidden && !dock.shown && lsGet("lcars.dock", {}).hidden === true, "again: the whole dock hidden, and kept so");
  vMatch(vWords("show the dock"), 0).cmd.fn(); runTimers(); await settle(1);
  ok(!dock.hidden && dock.shown && dock.list === "open", "\"show the dock\": back, the list open");
  vMatch(vWords("close all chat windows"), 0).cmd.fn(); runTimers(); await settle(1);
  ok(!dock.wins.length && !dockMounts.size, "\"close all chat windows\"");
  // Esc on a window's header minimises it
  dockOpen(dA.id); runTimers(); await settle(1);
  var dEv = { key: "Escape", target: dockMounts.get(dA.id).box, preventDefault: function () {}, stopPropagation: function () {} };
  dockKeydown(dEv);
  ok(document.activeElement === dockMounts.get(dA.id).el.querySelector(".chhdr"), "Esc in a window's box: the focus to its header");
  dEv.target = document.activeElement;
  dockKeydown(dEv); runTimers(); await settle(1);
  ok(dockWin(dA.id).min, "Esc on the header: minimised");
  dock.wins = []; dock.focus = []; dock.list = "pill"; dockSave(); dockRender();
  TEST.desk = false; dockSync();
  ok(!dock.shown, "the dock folds away when the desk goes (a narrowed window)");
  [dA, dB, dC, dD].forEach(function (t) { chats.list.splice(chats.list.indexOf(t), 1); });
  chatSave();

  console.log("-- one chat: the list, several threads, and Back --");
  closeOv(); runTimers(); await settle(1);
  var h0 = history._i;
  chatsList(); runTimers(); await settle(1);
  eq(curRel().split("?")[0], "chats", "Chats opens the list, at ./chats");
  eq(history._i, h0 + 1, "a step on the stack");
  ok(!$("#dlg").classList.contains("th-open"), "the list, not a thread");
  has($("#bChat").textContent, "Chats", "the header's button is Chats");
  // the version on every screen: buttons.py sees it drawn; here, its one source
  eq($("#verMark").textContent, "v" + APP_VERSION, "the mark over a covered header is APP_VERSION");
  eq($("#appVer").textContent, $("#verMark").textContent, "the header's says the same");
  var compRow = $("#chrows").querySelector('.chrow[data-id="' + chatComputer().id + '"]');
  ok(compRow, "the computer's thread has a row");
  ok($("#chrows").querySelector('.chrow[data-id="role-crew_yeoman"]'), "and so has the Yeoman's, under Reports");
  has($("#chrows").innerHTML, "Reports", "a section of its own");
  click(compRow); runTimers(); await settle(1);
  ok($("#dlg").classList.contains("th-open"), "a row opens its thread at once");
  eq(curRel().split("?")[0], "chats/" + chat.id, "at ./chats/<id>");
  eq(history._i, h0 + 2, "one more step");
  history.back(); runTimers(); await settle(1);
  ok($("#ov").classList.contains("on") && !$("#dlg").classList.contains("th-open"), "Back from a thread is the list");
  eq(curRel().split("?")[0], "chats", "at ./chats again");
  history.back(); runTimers(); await settle(1);
  ok(!$("#ov").classList.contains("on"), "and Back from the list leaves the chats");
  eq(history._i, h0, "where it started");

  openChat(); runTimers(); await settle(1);
  ok($("#dlg").classList.contains("th-open"), "Ask opens the computer's thread");
  eq(history._i, h0 + 2, "with the list put under it");
  history.back(); runTimers(); await settle(1);
  ok($("#ov").classList.contains("on") && !$("#dlg").classList.contains("th-open"), "so its Back is the list too");
  history.forward(); runTimers(); await settle(1);
  ok($("#dlg").classList.contains("th-open"), "Forward goes into the thread again");
  click($(".chth .chhdr .chback")); runTimers(); await settle(1);
  ok($("#ov").classList.contains("on") && !$("#dlg").classList.contains("th-open"), "the thread's ‹ is the list");
  eq(history._i, h0 + 1, "taken as a Back, not a new step");
  click($("#chrows").querySelector('.chrow[data-id="' + chat.id + '"]')); runTimers(); await settle(1);
  chatKey({ key: "Escape", preventDefault: function () {}, stopPropagation: function () {} });
  runTimers(); await settle(1);
  ok($("#ov").classList.contains("on") && !$("#dlg").classList.contains("th-open"), "Escape in a thread is the list as well");
  click($("#chrows").querySelector('.chrow[data-id="' + chat.id + '"]')); runTimers(); await settle(1);
  closeOv(); runTimers(); await settle(1);
  ok(!$("#ov").classList.contains("on"), "closing from a thread closes the chats");
  eq(history._i, h0, "and both steps come off, so Back does not reopen them");

  // several computer threads: + makes one, the last is kept
  openChat(); runTimers(); await settle(1);
  var tOld = chat;
  if (!tOld.msgs.length) tOld.msgs.push({ role: "user", text: "keep me" });
  var nThreads = chats.list.length;
  click($(".chth .chhdr .chback")); runTimers(); await settle(1);
  click($("#chnew")); runTimers(); await settle(1);
  eq(chats.list.length, nThreads + 1, "+ starts another thread");
  ok(chat !== tOld && chat.msgs.length === 0 && $("#dlg").classList.contains("th-open"), "empty, and open at once");
  eq(chat.model, chats.model, "with the model last chosen");
  ok(chatFind(tOld.id) && chatFind(tOld.id).msgs.length > 0, "the one before is kept");
  var tNew = chat;
  await chatSend("a second thread"); await settle(4);
  ok(tNew.msgs.length === 2 && tOld.msgs.every(function (m) { return m.text !== "a second thread"; }), "and each holds its own");
  eq(JSON.parse(localStorage.getItem("lcars.chats")).list.filter(function (t) { return t.id === tNew.id; }).length, 1,
     "kept in lcars.chats");

  // answered while elsewhere: unread on its row and on the Chats button
  chatsOpen(tOld.id); runTimers(); await settle(1);
  chat = tNew;
  var pUnread = chatSend("answer while I look away");
  chat = tOld;
  await pUnread; await settle(4);
  eq(tNew.unread, 1, "an answer to a thread not on screen is unread");
  has($("#bChat").textContent, String(chatUnreadTotal() + engAnswerCount()), "counted on the Chats button");
  chatsBack(); runTimers(); await settle(1);
  ok($("#chrows").querySelector('.chrow[data-id="' + tNew.id + '"] .chbadge'), "and marked on its row");
  chatNextUnread(); runTimers(); await settle(1);
  eq(chat, tNew, "\"next unread\" opens it");
  eq(tNew.unread, 0, "which reads it");

  // archive, from the thread's ⋯, and back
  click($(".chth .chmore"));
  click($(".chth .chsheet").querySelector('[data-act="arch"]')); runTimers(); await settle(1);
  ok(tNew.archived && !$("#dlg").classList.contains("th-open"), "Archive takes it off the list, back to the list");
  ok(!$("#chrows").querySelector('.chrow[data-id="' + tNew.id + '"]') ||
     $("#chrows").querySelector(".chold").innerHTML.indexOf(tNew.id) >= 0, "into Archived");
  chatArchive(tNew.id, false);
  ok(!tNew.archived, "and Bring back undoes it");

  // search
  $("#chfind").value = "a second thread"; $("#chfind").oninput();
  eq($("#chrows").querySelectorAll(".chrow").length, 1, "search finds a thread by what was said in it");
  $("#chfind").value = ""; $("#chfind").oninput();

  console.log("-- a row's swipe: a tap on its action is the action (docs/qa/chat.md 1-4, 9, 10, 12) --");
  var swRowl = function (id) { var b = $("#chrows").querySelector('.chrow[data-id="' + id + '"]'); return b && b.parentNode; };
  var swT = function (el, type, x, y) {
    var t = [{ clientX: x, clientY: y || 300 }];
    return dispatch(el, type, { touches: type === "touchend" ? [] : t, changedTouches: t });
  };
  var swDrag = function (el, dx) { swT(el, "touchstart", 200); swT(el, "touchmove", 200 + dx / 2); swT(el, "touchmove", 200 + dx); swT(el, "touchend", 200 + dx); };
  // a tap as a browser lands it: touchstart, touchend, then the click on
  // whatever is under the finger by then - the action while its row is
  // open, the row itself once it has closed over it
  var swTap = function (rowl, sel) {
    var a = rowl.querySelector(sel);
    swT(a, "touchstart", 360); swT(a, "touchend", 360);
    click(rowl.classList.contains("swiped") ? a : rowl.querySelector(".chrow"));
  };
  tNew.unread = 2; chatSave(); chatListPaint();
  var swR = swRowl(tNew.id);
  swT(swR.querySelector(".chrow"), "touchstart", 200);
  swT(swR.querySelector(".chrow"), "touchmove", 170);
  ok(swR.classList.contains("drag"), "a drag left shows the row's actions from its start");
  has(swR.querySelector(".chrow").style.transform, "-30px", "and the row follows the finger");
  chatListPaint();
  ok(swRowl(tNew.id) === swR, "a repaint mid-drag waits: the row under the finger stays");
  swT(swR.querySelector(".chrow"), "touchmove", 150); swT(swR.querySelector(".chrow"), "touchend", 150);
  ok(swR.classList.contains("swiped"), "50px is enough to leave it open");
  swR = swRowl(tNew.id);
  ok(swR.classList.contains("swiped"), "the repaint it waited for, once let go, keeps it open");
  chatListPaint();
  swR = swRowl(tNew.id);
  ok(swR.classList.contains("swiped"), "and so does any later repaint");
  swTap(swR, '[data-arch]');
  ok(tNew.archived, "a tap on Archive archives (0.162.1 closed the row on the tap and opened the thread)");
  ok(!$("#dlg").classList.contains("th-open"), "and opens nothing");
  ok(!chatSw.open && !$("#chrows").querySelector(".chrowl.swiped"), "and no row is left open to eat the next tap (QA bug C)");
  chatArchive(tNew.id, false);
  eq(tNew.unread, 2, "Undo brings it back with its unread count");
  swR = swRowl(tNew.id);
  swT(swR.querySelector(".chrow"), "touchstart", 200); swT(swR.querySelector(".chrow"), "touchmove", 260);
  ok(swR.classList.contains("dr") && swR.dataset.rd === "read", "a drag right shows Mark read");
  swT(swR.querySelector(".chrow"), "touchend", 260);
  eq(tNew.unread, 0, "and marks it read");
  swR = swRowl(tNew.id);
  eq(swR.dataset.rd, "unread", "a read row's swipe right is Mark unread");
  var unreadWas = chatUnreadTotal();
  swDrag(swR.querySelector(".chrow"), 60);
  ok(tNew.mark && !tNew.unread, "a swipe right on a read thread marks it unread");
  swR = swRowl(tNew.id);
  has(swR.innerHTML, "&bull;", "its row has the dot at once");
  eq(chatUnreadTotal(), unreadWas + 1, "and it is counted");
  ok(JSON.parse(localStorage.getItem("lcars.chats")).list.some(function (t) { return t.id === tNew.id && t.mark; }), "kept across a reload");
  eq(swR.dataset.rd, "read", "and its next swipe right is Mark read");
  swDrag(swR.querySelector(".chrow"), 60);
  ok(!tNew.mark, "which clears the mark");
  tNew.mark = true; chatSave();
  chatsOpen(tNew.id); runTimers(); await settle(1);
  ok(!tNew.mark, "opening a thread marked unread reads it");
  chatsBack(); runTimers(); await settle(1);
  var swRole = chatFind("role-crew_yeoman");
  if (swRole) {
    swRole.unread = 1; chatListPaint();
    swDrag(swRowl(swRole.id).querySelector(".chrow"), 70);
    eq(swRole.unread, 0, "a role's thread is marked read by a swipe right too");
    swDrag(swRowl(swRole.id).querySelector(".chrow"), 70);
    ok(swRole.mark, "and marked unread by the next");
    swRole.mark = false; chatSave(); chatListPaint();
  }
  // a course's navigator: a thread with an unread count too, both ways
  var swNavE = st.all.find(function (e) { return !e.deleted; });
  var swNav = chatThread({ id: "nav-" + swNavE.id, nav: swNavE.id, msgs: [{ role: "user", text: "plot it" }], at: Date.now(), unread: 1 });
  chats.list.push(swNav); chatListPaint();
  swDrag(swRowl(swNav.id).querySelector(".chrow"), 60);
  eq(chatUnread(swNav), 0, "a navigator's row is marked read by a swipe right");
  swDrag(swRowl(swNav.id).querySelector(".chrow"), 60);
  ok(swNav.mark, "and marked unread by the next");
  chats.list.splice(chats.list.indexOf(swNav), 1); chatSave(); chatListPaint();
  swR = swRowl(tNew.id);
  swR = swRowl(tNew.id);
  swDrag(swR.querySelector(".chrow"), -25);
  ok(!swR.classList.contains("swiped"), "25px springs back");
  swT(swR.querySelector(".chrow"), "touchstart", 200); swT(swR.querySelector(".chrow"), "touchmove", 185, 340);
  swT(swR.querySelector(".chrow"), "touchend", 185, 340);
  ok(!swR.classList.contains("swiped") && !swR.classList.contains("drag"), "a drag mostly down is the list's scroll");
  swDrag(swR.querySelector(".chrow"), -80);
  ok(swR.classList.contains("swiped"), "open again");
  var swOther = swRowl(tOld.id);
  swTap(swOther, ".chrow");
  ok(!swR.classList.contains("swiped"), "a tap on another row closes the open one");
  ok(!$("#dlg").classList.contains("th-open"), "and does nothing else");
  swDrag(swR.querySelector(".chrow"), -80);
  swT($("#chfind"), "touchstart", 100, 50); swT($("#chfind"), "touchend", 100, 50);
  ok(!swR.classList.contains("swiped"), "so does a touch outside the list");
  chatSw.ate = 0;
  var swRep = $("#chrows").querySelector(".chrow[data-report]");
  if (swRep) {
    swDrag(swRep, -80);
    ok(!swRep.parentNode.classList.contains("swiped") && !swRep.parentNode.classList.contains("drag"), "a row with no actions does not slide");
  }

  console.log("-- the chats' small fixes (docs/qa/chat.md 6, 7, 11, 13-15) --");
  // 7: named once, after its first question, so CHAT_KEEP cannot rename it
  var tLong = chatNewThread();
  for (var qi = 0; qi < 30; qi++) tLong.msgs.push({ role: "user", text: "question " + qi }, { role: "asst", parts: [{ t: "text", s: "answer" }] });
  chatSave();
  eq(chatTitle(tLong), "question 0", "a thread is named after its first question");
  ok(tLong.msgs.length === 60 && JSON.parse(localStorage.getItem("lcars.chats")).list.some(function (t) { return t.id === tLong.id && t.title === "question 0"; }),
     "and keeps that name once its first messages are dropped");
  tLong.msgs.splice(0, 20);
  eq(chatTitle(tLong), "question 0", "even with question 0 gone");
  chats.list.splice(chats.list.indexOf(tLong), 1); chatSave();
  // 13
  eq(chatInitials({ eng: { title: "Number One" } }), "N1", "Number One is N1");
  eq(chatInitials({ eng: { title: "Lt. Tasha Yar" } }), "TY", "\"Lt.\" is a rank, not a name");
  eq(chatInitials({ eng: { title: "Ens. Ro Laren" } }), "RL", "and so is \"Ens.\"");
  // 11
  ok(!/kept under Archived/.test(VCMDS.map(function (c) { return c.help || ""; }).join(" ")), "an archived chat is not promised to be kept");
  // 6: bring back by voice, the toast's Undo with no chat open
  chatArchive(tOld.id, true);
  vMatch(vWords("bring back the chat"), 0).cmd.fn();
  ok(!tOld.archived, "\"bring back the chat\" with none open brings back the last archived");
  // 14: a touch screen's Enter is a new line; Send sends
  chatsOpen(tOld.id); runTimers(); await settle(1);
  var mmWas = window.matchMedia;
  window.matchMedia = function (q) { return { matches: /coarse/.test(q) || mmWas(q).matches }; };
  var nMsgs = tOld.msgs.length;
  $(".chth .chbox").value = "two";
  var enterEv = dispatch($(".chth .chbox"), "keydown", { key: "Enter", shiftKey: false, isComposing: false });
  ok(!enterEv.defaultPrevented && tOld.msgs.length === nMsgs, "on a touch screen Enter is a new line, not a send");
  window.matchMedia = mmWas;
  enterEv = dispatch($(".chth .chbox"), "keydown", { key: "Enter", shiftKey: false, isComposing: false });
  ok(enterEv.defaultPrevented && tOld.msgs.length > nMsgs, "with a keyboard and mouse it sends");
  await tOld.done; await settle(4);
  // QA bug A: WebKit cancels a tap's click when its pointerdown is
  // prevented (to keep the keyboard), so a touch on Send sends on its
  // pointerup; a click that does follow is not a second send
  $(".chth .chbox").focus();
  input($(".chth .chbox"), "sent by a tap");
  nMsgs = tOld.msgs.length;
  var pdEv = dispatch($(".chth .chsend"), "pointerdown", { pointerType: "touch" });
  ok(pdEv.defaultPrevented, "a touch on Send keeps the focus in the box");
  dispatch($(".chth .chsend"), "pointerup", { pointerType: "touch" });
  eq(tOld.msgs.length, nMsgs + 2, "and sends on its pointerup, with no click from the browser");
  ok(document.activeElement === $(".chth .chbox"), "the box still has the focus");
  await tOld.done; await settle(4);
  click($(".chth .chsend"), { isTrusted: true });
  eq(tOld.msgs.length, nMsgs + 2, "the browser's own click after it sends nothing more");
  // the press opens ⋯'s sheet at pointerup; the tap's own mousedown and
  // click then land on its scrim, and must neither blur the box nor shut it
  $(".chth .chbox").focus();
  dispatch($(".chth .chmore"), "pointerdown", { pointerType: "touch" });
  dispatch($(".chth .chmore"), "pointerup", { pointerType: "touch" });
  ok(!$(".chth .chscrim").hidden, "a touch on ⋯ opens its sheet on the pointerup");
  ok(dispatch($(".chth .chscrim"), "mousedown", {}).defaultPrevented, "the tap's late mousedown, on the scrim now, keeps the focus");
  click($(".chth .chscrim"), { isTrusted: true });
  ok(!$(".chth .chscrim").hidden, "and its late click does not close the sheet it opened");
  chatSheet("");
  input($(".chth .chbox"), "by a click");
  click($(".chth .chsend"), { isTrusted: true });
  eq(tOld.msgs.length, nMsgs + 4, "a click on its own (a mouse) still sends");
  await tOld.done; await settle(4);
  // 6: "read it out" in a chat is its last answer, not the open entry
  var rlWas = chatReadLast, rlN = 0;
  chatReadLast = function () { rlN++; };
  vMatch(vWords("read it out"), 0).cmd.fn();
  chatReadLast = rlWas;
  eq(rlN, 1, "\"read it out\" in the chats reads the chat's last answer");
  eq(vMatch(vWords("mark this chat unread"), 0).cmd.say, "mark unread", "\"mark this chat unread\" is an order");
  vMatch(vWords("mark unread"), 0).cmd.fn();
  runTimers(); await settle(1);
  ok(tOld.mark && !$("#dlg").classList.contains("th-open"), "\"mark unread\" marks the chat on screen, back on the list");
  ok(/&bull;/.test($("#chrows").querySelector('.chrow[data-id="' + tOld.id + '"]').innerHTML), "with its dot");
  chatMarkRead(tOld.id);
  ok(!tOld.mark, "Mark read clears it");
  closeOv(); runTimers(); await settle(1);

  // the 0.156 thread (lcars.chat) is carried over
  var lsChats = localStorage.getItem("lcars.chats"), lsChat = localStorage.getItem("lcars.chat");
  localStorage.removeItem("lcars.chats");
  lsSet("lcars.chat", { sid: "s-old", model: "opus", msgs: [{ role: "user", text: "from 0.156" }] });
  var mig = chatsLoad();
  eq(mig.list.length, 1, "the one thread before 0.157 is carried over");
  eq(mig.list[0].id + " " + mig.list[0].sid + " " + mig.list[0].model, "computer-1 s-old opus", "with its session and model");
  eq(mig.list[0].msgs[0].text, "from 0.156", "and its messages");
  lsSet("lcars.chat", { msgs: [{ role: "user", text: "hi" }], role: { kind: "crew_ops", title: "Ops brief" } });
  eq(chatsLoad().list[0].id, "role-crew_ops", "a role's thread becomes that role's");
  if (lsChats) localStorage.setItem("lcars.chats", lsChats);
  if (lsChat) localStorage.setItem("lcars.chat", lsChat); else localStorage.removeItem("lcars.chat");
  eq(chatThread({ id: "x", model: "nope" }).model, "sonnet", "a thread with no known model answers with Sonnet");
  [["chats", "chats"], ["show the chats", "chats"], ["back to the chats", "back to the chats"], ["next unread", "next unread"],
   ["archive this chat", "archive this chat"], ["mark all read", "mark all read"], ["back to the list", "close"]].forEach(function (x) {
    var hit = vMatch(vWords(x[0]), 0);
    eq(hit && hit.cmd.say, x[1], "\"" + x[0] + "\" is " + x[1]);
  });
  lsSet("lcars.deck.engkey", "");
  closeOv();
  fetch = chatFetch;
  if (!hadRaf) delete globalThis.requestAnimationFrame;
  chat.msgs = chatWas; chat.sid = sidWas;
  chatSave();
  closeEditor();
  await settle(2);

  console.log("-- the editor's own microphone button --");
  var mrow = st.all.filter(function (e) {
    return !e.deleted && e.kind && !needsBody(e);
  })[0];
  select(mrow.id);
  await settle(6);
  setRead(true);
  ok($("#bMic"), "the editor's action bar has a microphone of its own");
  edMic();
  ok(!st.read, "dictating from the reader switches to editing first");
  ok(!vx.on, "a page that cannot have the microphone does not pretend to listen");
  ok(!$("#bMic").classList.contains("on"), "and the button stays off");
  hideToast();

  /* Dictation is two things at once — the words typed into the body and a
     recording of them attached to the entry — and on an iPhone it was doing
     only the second: the tape opened a microphone capture of its own, and iOS
     keeps one capture alive, so the recogniser's went silent. What is faked
     here is everything under the page: the capture and its clones, the
     recorder, the upload, and each engine's side of the microphone. */
  console.log("-- dictation: the words and the tape, together --");
  var gum = 0, bases = [], recs = [], xhrs = [], srecs = [], sockets = [];
  function FakeTrack() { this.readyState = "live"; }
  FakeTrack.prototype.stop = function () { this.readyState = "ended"; };
  function FakeStream(base, kind) {
    this.base = base || this;
    this.kind = kind || (base && base.kind) || "audio";
    this.tracks = [new FakeTrack()];
    this.tracks[0].kind = this.kind;
  }
  FakeStream.prototype.getTracks = function () { return this.tracks; };
  FakeStream.prototype.getAudioTracks = function () { return this.tracks.filter(function (t) { return t.kind === "audio"; }); };
  FakeStream.prototype.getVideoTracks = function () { return this.tracks.filter(function (t) { return t.kind === "video"; }); };
  FakeStream.prototype.clone = function () { return new FakeStream(this.base); };
  var mediaWas = { nav: navigator.mediaDevices, sec: window.isSecureContext,
                   ac: window.AudioContext, g: {} };
  ["MediaRecorder", "MediaStream", "Blob", "File", "XMLHttpRequest", "WebSocket", "URL"].forEach(function (k) {
    mediaWas.g[k] = globalThis[k];
  });
  var cams = [], camDown = false;
  navigator.mediaDevices = { getUserMedia: function (c) {
    if (c && c.video) {
      if (camDown) return Promise.reject(new Error("Permission denied"));
      var cs = new FakeStream(null, "video");
      cams.push({ stream: cs, want: c.video });
      return Promise.resolve(cs);
    }
    gum++;
    var sm = new FakeStream();
    bases.push(sm);
    return Promise.resolve(sm);
  } };
  globalThis.MediaStream = function (tracks) { this.tracks = tracks; };
  globalThis.MediaStream.prototype = Object.create(FakeStream.prototype);
  window.isSecureContext = true;
  globalThis.MediaRecorder = function (stream, o) { this.stream = stream; this.opts = o; this.state = "inactive"; recs.push(this); };
  MediaRecorder.isTypeSupported = function (t) {
    return t === "audio/mp4;codecs=mp4a.40.2" || t === "video/mp4;codecs=avc1.42E01E,mp4a.40.2";
  };
  MediaRecorder.prototype.start = function () {
    this.state = "recording";
    this.mimeType = this.opts && this.opts.mimeType && this.opts.mimeType.indexOf("video/") === 0 ? "video/mp4" : "audio/mp4";
  };
  MediaRecorder.prototype.stop = function () {
    this.state = "inactive";
    this.ondataavailable({ data: { size: 4000 } });
    this.onstop();
  };
  globalThis.Blob = function (parts, o) {
    this.size = parts.reduce(function (n, x) { return n + (x.size || 0); }, 0);
    this.type = o && o.type;
  };
  Blob.prototype.slice = function (a, b) {
    return new Blob([{ size: Math.max(0, Math.min(b == null ? this.size : b, this.size) - a) }]);
  };
  globalThis.File = function (parts, name, o) { this.size = parts[0].size; this.name = name; this.type = o && o.type; };
  globalThis.XMLHttpRequest = function () { this.upload = {}; this.h = {}; xhrs.push(this); };
  // what keepLocal hands the device: a download's blob, or the share sheet's files
  var kept = [], shared = [];
  globalThis.URL = { createObjectURL: function (b) { kept.push(b); return "blob:k" + kept.length; },
                     revokeObjectURL: function () {} };
  XMLHttpRequest.prototype.open = function (m, u) { this.method = m; this.url = u; };
  XMLHttpRequest.prototype.setRequestHeader = function (k, v) { this.h[k] = v; };
  XMLHttpRequest.prototype.send = function (b) { this.body = b; };
  function answerUpload(x, path) {
    x.status = 200;
    x.responseText = JSON.stringify({ id: 900 + xhrs.indexOf(x), entry_id: mrow.id, path: path,
                                      mime: "audio/mp4", bytes: 4000, name: "d.m4a" });
    x.onload();
  }
  // the browser's recogniser: onstart arrives a beat after start(), as it does
  function FakeRec() { srecs.push(this); }
  FakeRec.prototype.start = function () {
    var r = this;
    Promise.resolve().then(function () { if (r.onstart) r.onstart(); });
  };
  FakeRec.prototype.abort = FakeRec.prototype.stop = function () {};
  window.webkitSpeechRecognition = FakeRec;
  function heardRec(r, text) {
    var res = [{ transcript: text }];
    res.isFinal = true;
    r.onresult({ resultIndex: 0, results: [res] });
  }
  var engWas = vcfg.engine, keyWas = vcfg.key;

  // --- the browser's own recogniser ---
  vcfg.engine = "browser";
  vx.on = false; vx.dict = false;
  $("#content").value = "Before.";
  edMic();
  ok(vx.on && vx.dict, "a tap opens the microphone straight into dictation");
  eq(srecs.length, 1, "the recogniser is started");
  eq(recs.length, 0, "the tape waits for the recogniser, rather than racing it for the microphone");
  await settle(3);
  ok(vx.live, "the recogniser comes up");
  eq(recs.length, 1, "and then the tape rolls");
  eq(recs[0].state, "recording", "recording");
  heardRec(vx.rec, "hello from the phone");
  has($("#content").value, "Hello from the phone", "what is said is typed into the body");
  ok($("#content").value.indexOf("Before.") === 0, "after what was there");
  ok($("#bMic").classList.contains("on"), "the button lights up");
  has($("#bMic").textContent, "Pause", "and offers to pause");

  edMic();
  ok(!vx.dict && vx.on, "a second tap pauses dictation and keeps the microphone");
  has($("#bMic").textContent, "Dictate", "and the button offers it again");
  await settle(3);
  eq(xhrs.length, 1, "the tape is uploaded when dictation pauses");
  has(xhrs[0].url, "/entries/" + mrow.id + "/media?name=dictation-", "to the entry being dictated into");
  eq(kept.length, 1, "the tape is also kept on the device");
  has(kept[0].name, "dictation-", "under the recording's own name");
  has($("#content").value, "uploading…", "a placeholder holds its place meanwhile");
  answerUpload(xhrs[0], "media/2026/09/26/e1-tape.m4a");
  await settle(3);
  has($("#content").value, "(media/2026/09/26/e1-tape.m4a)", "and the recording is linked in the body");
  has($("#content").value, "Hello from the phone", "beside the words, which are still there");
  ok(!vmic.users.size && bases[0].tracks[0].readyState === "ended",
     "the capture is let go with the tape");

  // the two cannot share after all: the words win
  edMic();
  await settle(3);
  eq(recs.length, 2, "resuming rolls a new tape");
  vx.rec.onerror({ error: "audio-capture" });
  ok(!vx.tape && recs[1].state === "inactive", "a recogniser that lost the microphone to the tape stops the tape");
  ok(vx.on && vx.dict, "and dictation carries on");
  has($("#toast").textContent, "not being recorded", "saying so");
  hideToast();
  heardRec(vx.rec, "still typing");
  has($("#content").value, "Still typing", "the words keep coming");
  voiceStop();
  await settle(3);
  xhrs.forEach(function (x, i) { if (!x.status) answerUpload(x, "media/2026/09/26/e1-x" + i + ".m4a"); });
  await settle(3);

  // --- deepgram: one capture, streamed and taped ---
  gum = 0; recs = []; xhrs = [];
  vcfg.engine = "deepgram"; vcfg.key = "";
  globalThis.WebSocket = function (url, protos) { this.url = url; this.protos = protos; this.readyState = 0; sockets.push(this); };
  WebSocket.prototype.send = function () {};
  WebSocket.prototype.close = function () { this.readyState = 3; };
  var fakeNode = function () { return { connect: function () {}, disconnect: function () {}, gain: {} }; };
  window.AudioContext = function () { this.state = "running"; this.sampleRate = 48000; this.destination = {}; };
  window.AudioContext.prototype.createMediaStreamSource = function (sm) { this.fed = sm; return fakeNode(); };
  window.AudioContext.prototype.createGain = fakeNode;
  window.AudioContext.prototype.createScriptProcessor = fakeNode;
  window.AudioContext.prototype.close = function () {};
  setForm(mrow); setClean();
  $("#content").value = "Before.";
  edMic();
  await settle(3);
  eq(gum, 1, "deepgram and the tape open the microphone once between them");
  eq(recs.length, 1, "the tape rolls");
  ok(dg.stream && recs[0].stream !== dg.stream && recs[0].stream.base === dg.stream.base,
     "each on its own clone of the one capture");
  var sock = sockets[sockets.length - 1];
  ok(TEST.fetches.indexOf("GET /say/token") >= 0, "the socket's key is asked of the server (GET /say/token), none kept here");
  eq(sock.protos && sock.protos.join(" "), "bearer aaaa.bbbb.cccc", "and goes as a bearer, the minted kind");
  sock.readyState = 1;
  sock.onopen();
  sock.onmessage({ data: JSON.stringify({ type: "Results", is_final: true, speech_final: true,
    channel: { alternatives: [{ transcript: "words over deepgram", words: [] }] } }) });
  has($("#content").value, "Words over deepgram", "what deepgram hears is typed into the body");
  edMic();
  await settle(3);
  eq(xhrs.length, 1, "and the tape is uploaded");
  ok(dg.stream && dg.stream.tracks[0].readyState === "live" && dg.stream.base.tracks[0].readyState === "live",
     "the recogniser keeps its microphone when the tape stops");
  answerUpload(xhrs[0], "media/2026/09/26/e1-dg.m4a");
  await settle(3);
  has($("#content").value, "(media/2026/09/26/e1-dg.m4a)", "the recording is linked");
  voiceStop();
  ok(!vmic.users.size && !vmic.base, "closing the microphone releases the capture");

  /* The tape is sent a second at a time while it records (tapeFeed), so the
     stop only has to attach what the server already holds. */
  console.log("-- dictation: the tape goes up while it is recorded --");
  var fetchWas = fetch, tapes = [], held = 0, tapeDown = false;
  fetch = function (url, o) {
    if (String(url).indexOf("/tapes/") < 0) return fetchWas(url, o);
    var off = Number(/off=(\d+)/.exec(url)[1]);
    tapes.push({ url: String(url), off: off, size: o.body.size });
    if (tapeDown) return Promise.reject(new Error("Failed to fetch"));
    held = off + o.body.size;
    var answer = JSON.stringify({ size: held });
    return Promise.resolve({ ok: true, status: 200,
      text: function () { return Promise.resolve(answer); } });
  };
  recs = []; xhrs = [];
  setForm(mrow); setClean();
  $("#content").value = "Before.";
  edMic();
  await settle(3);
  eq(recs.length, 1, "the tape rolls");
  recs[0].ondataavailable({ data: { size: 1000 } });
  recs[0].ondataavailable({ data: { size: 1500 } });
  await settle(3);
  ok(tapes.length >= 1 && tapes[0].off === 0, "its first seconds are sent while dictation goes on");
  eq(held, 2500, "every slice so far, in order");
  eq(xhrs.length, 0, "and nothing is uploaded whole");
  var token = /\/tapes\/([0-9a-f]+)/.exec(tapes[0].url)[1];
  edMic();
  await settle(6);
  eq(held, 6500, "the stop sends only the last second");
  eq(xhrs.length, 1, "and then attaches the tape");
  has(xhrs[0].url, "&tape=" + token, "by its token");
  ok(xhrs[0].body == null, "with no body: the server has the bytes");
  answerUpload(xhrs[0], "media/2026/10/01/e1-streamed.m4a");
  await settle(3);
  has($("#content").value, "(media/2026/10/01/e1-streamed.m4a)", "and the recording is linked");

  // an attach the server cannot honour goes up whole
  edMic();
  await settle(3);
  recs[recs.length - 1].ondataavailable({ data: { size: 800 } });
  await settle(3);
  xhrs = [];
  edMic();
  await settle(6);
  eq(xhrs.length, 1, "a second tape is attached the same way");
  xhrs[0].status = 404;
  xhrs[0].responseText = JSON.stringify({ error: "No staged tape" });
  xhrs[0].onload();
  await settle(3);
  eq(xhrs.length, 2, "a refused attach falls back to the upload");
  ok(xhrs[1].body && xhrs[1].body.size === 4800 && xhrs[1].url.indexOf("&tape=") < 0,
     "of the whole recording, kept by the page meanwhile");
  answerUpload(xhrs[1], "media/2026/10/01/e1-whole.m4a");
  await settle(3);
  has($("#content").value, "(media/2026/10/01/e1-whole.m4a)", "linked all the same");

  // and a link that drops the slices does not lose the tape either
  tapeDown = true;
  edMic();
  await settle(3);
  recs[recs.length - 1].ondataavailable({ data: { size: 700 } });
  await settle(10);
  xhrs = [];
  edMic();
  await settle(10);
  eq(xhrs.length, 1, "with the slices refused, the stop uploads the tape");
  ok(xhrs[0].body && xhrs[0].body.size === 4700 && xhrs[0].url.indexOf("&tape=") < 0,
     "whole, the old way");
  answerUpload(xhrs[0], "media/2026/10/01/e1-down.m4a");
  await settle(3);

  // the Record button records through the same recorder, and streams the same way
  tapeDown = false; tapes = []; recs = []; xhrs = [];
  await mediaRecToggle();
  eq(recs.length, 1, "Record rolls a recorder");
  recs[0].ondataavailable({ data: { size: 900 } });
  await settle(3);
  eq(tapes.length, 1, "whose seconds are sent while it records");
  var recToken = /\/tapes\/([0-9a-f]+)/.exec(tapes[0].url)[1];
  await mediaRecToggle();
  await settle(6);
  eq(xhrs.length, 1, "and the stop attaches it");
  has(xhrs[0].url, "&tape=" + recToken, "by its token");
  ok(xhrs[0].body == null, "with no body");
  answerUpload(xhrs[0], "media/2026/10/01/e1-rec.m4a");
  await settle(3);
  voiceStop();

  /* Video dictation: the same tape with the camera on. */
  console.log("-- video dictation: typed, filmed, streamed --");
  tapes = []; recs = []; xhrs = []; cams = []; held = 0;
  setForm(mrow); setClean();
  $("#content").value = "Before.";
  var gum0 = gum;
  edMic(true);
  await settle(3);
  ok(vx.on && vx.dict, "the Video button opens the microphone into dictation");
  eq(cams.length, 1, "and the camera");
  eq(cams[0].want.facingMode, "user", "the front one: this is someone talking to it");
  eq(gum - gum0, 1, "the sound is the page's one microphone capture, shared with deepgram");
  eq(recs.length, 1, "one recorder");
  ok(recs[0].stream.getVideoTracks().length === 1 && recs[0].stream.getAudioTracks().length === 1,
     "of the camera's pictures and the microphone's sound together");
  eq(recs[0].opts.mimeType, "video/mp4;codecs=avc1.42E01E,mp4a.40.2", "as H.264/AAC where it can be had");
  ok($("#bVid").classList.contains("on") && !$("#bMic").classList.contains("on"), "the Video button is lit, Dictate is not");
  ok(!$("#vcam").hidden && $("#vcam").srcObject === cams[0].stream, "a preview shows what is filmed");
  var sock2 = sockets[sockets.length - 1];
  sock2.readyState = 1;
  sock2.onopen();
  has($("#vmode").textContent, "film", "and the read-out says so");
  sock2.onmessage({ data: JSON.stringify({ type: "Results", is_final: true, speech_final: true,
    channel: { alternatives: [{ transcript: "said to the camera", words: [] }] } }) });
  has($("#content").value, "Said to the camera", "what is said is typed, as in any dictation");
  // a second of video is far bigger than one of speech; a backlog goes up in capped slices
  recs[0].ondataavailable({ data: { size: 300000 } });
  recs[0].ondataavailable({ data: { size: 300000 } });
  recs[0].ondataavailable({ data: { size: 300000 } });
  await settle(6);
  ok(tapes.every(function (t) { return t.size <= TAPE_SLICE_MAX; }), "no slice is over what the server takes in one");
  eq(held, 900000, "and all of it arrives, in order");
  var vidToken = /\/tapes\/([0-9a-f]+)/.exec(tapes[0].url)[1];
  edMic(true);
  await settle(6);
  ok(!vx.dict && vx.on, "a second tap pauses it");
  ok($("#vcam").hidden && !$("#vcam").srcObject, "the preview goes");
  ok(cams[0].stream.tracks[0].readyState === "ended", "and so does the camera");
  eq(xhrs.length, 1, "the film is attached");
  has(xhrs[0].url, "name=video-dictation-", "named as video dictation");
  has(xhrs[0].url, ".mp4", "an mp4");
  has(xhrs[0].url, "&tape=" + vidToken, "by its token, with no body");
  has($("#content").value, "[🎥 video dictation ", "a placeholder holds its place meanwhile");
  answerUpload(xhrs[0], "media/2026/10/01/e1-film.mp4");
  await settle(3);
  has($("#content").value, "🎥 video dictation", "and the link says it is a video");
  has($("#content").value, "(media/2026/10/01/e1-film.mp4)", "to the film");
  ok($("#content").value.indexOf("uploading…") < 0, "and the placeholder is gone");

  // switching kinds mid-dictation ends one tape and starts the other
  recs = []; xhrs = []; cams = [];
  edMic(false);
  await settle(3);
  eq(recs.length, 1, "Dictate rolls an audio tape");
  eq(cams.length, 0, "with no camera");
  voiceHeard("computer start video dictation");
  await settle(6);
  eq(recs.length, 2, "the video order starts a filmed tape");
  eq(cams.length, 1, "with the camera");
  eq(xhrs.length, 1, "and the audio tape is attached");
  answerUpload(xhrs[0], "media/2026/10/01/e1-a.m4a");
  voiceHeard("computer start dictation");
  await settle(3);
  eq(recs.length, 2, '"start dictation" while filming goes on filming');
  ok(vx.tape && vx.tape.video, "the same tape");
  voiceHeard("computer pause dictation");
  await settle(6);
  ok(!vx.tape && cams[0].stream.tracks[0].readyState === "ended", "pausing stops the film");
  xhrs.forEach(function (x, i) { if (!x.status) answerUpload(x, "media/2026/10/01/e1-v" + i + ".mp4"); });
  await settle(3);

  // a refused camera: the words go on, unfilmed
  camDown = true; recs = [];
  edMic(true);
  await settle(3);
  ok(vx.dict, "dictation runs without the camera");
  eq(recs.length, 0, "nothing is recorded");
  has($("#toast").textContent, "not being filmed", "and it says why");
  ok(!vmic.users.size || dg.stream && vmic.users.size === 1, "the microphone clone the tape took is let go");
  hideToast();
  edMic(true);
  ok(!vx.dict, "and the button still pauses it");
  // --- a copy on the device: an iPhone's waits for a tap on Save ---
  var iosWas = KEEP_IOS, shareWas = navigator.share, canWas = navigator.canShare;
  KEEP_IOS = true;
  navigator.canShare = function () { return true; };
  navigator.share = function (d) { shared.push(d.files); return Promise.resolve(); };
  var k0 = kept.length;
  var snap = keepNamed(new File([{ size: 10 }], "image.jpg", { type: "image/jpeg" }));
  ok(/^photo-\d{8}-\d{6}\.jpg$/.test(snap.name), "a camera capture is named for when it was taken: " + snap.name);
  keepLocal([snap]);
  eq(kept.length, k0, "on an iPhone nothing is downloaded");
  eq(keep.q.length, 1, "the capture waits for a tap instead");
  has(mediaBarHtml(), "Save 1 to device", "which the media bar offers");
  await keepShare();
  eq(shared.length, 1, "the tap opens the share sheet");
  eq(shared[0][0], snap, "with the capture in it");
  eq(keep.q.length, 0, "and it is offered no more");
  ok(mediaBarHtml().indexOf("to device") < 0, "the button goes with it");
  cfg.keep = false;
  keepLocal([snap]);
  eq(keep.q.length + kept.length - k0, 0, "switched off in Config, nothing is kept");
  cfg.keep = true;
  KEEP_IOS = iosWas; navigator.share = shareWas; navigator.canShare = canWas;

  camDown = false;
  fetch = fetchWas;
  voiceStop();

  delete window.webkitSpeechRecognition;
  vcfg.engine = engWas; vcfg.key = keyWas;
  navigator.mediaDevices = mediaWas.nav;
  window.isSecureContext = mediaWas.sec;
  window.AudioContext = mediaWas.ac;
  Object.keys(mediaWas.g).forEach(function (k) {
    if (mediaWas.g[k] === undefined) delete globalThis[k]; else globalThis[k] = mediaWas.g[k];
  });
  media.byEntry.delete(mrow.id);
  hideToast();
  setForm(mrow); setClean();
  vPaint();
  closeEditor();
  await settle(2);

  console.log("-- aloud: a synthesiser that fails --");
  window.speechSynthesis.speak = function () { throw new Error("no voices"); };
  st.read = true;
  paintMode(true);
  ttsAloud();
  await settle(2);
  ok(!tts.on, "a refusal does not leave the button lit for ever");

  window.speechSynthesis = null;
  window.SpeechSynthesisUtterance = undefined;
  closeEditor();
  hideToast();

  /* ---------- voice ----------
     There is no SpeechRecognition in here, and there does not need to be: the
     preprocessor is handed the transcript the recogniser would have produced,
     and everything downstream of that is the part worth testing. */
  console.log("\n-- voice: words to text --");
  eq(vText(vWords("hello world period new line and then comma more")),
     "hello world.\nand then, more", "spoken punctuation lands, and hugs correctly");
  eq(vText(vWords("open bracket like this close bracket")), "(like this)",
     "brackets hug what they hold");
  eq(vText(vWords("a new bullet b")), "a\n- b", "an outline bullet takes its own line");

  console.log("-- voice: the order under the wake word --");
  var m = vMatch(vWords("delete last three words"), 0);
  ok(m, "a counted phrase matches");
  eq(m.cmd.say, "delete last {n} words", "the longest phrase wins over 'delete last word'");
  eq(m.arg.n, "3", "and the spoken number is read");
  eq(vMatch(vWords("delete last word"), 0).cmd.say, "delete last word",
     "the plain phrase still matches when there is no count");
  eq(vMatch(vWords("open entry 14 82"), 0).arg.n, "1482", "digits said apart are one number");
  var tm = vMatch(vWords("five minutes earlier"), 0);
  eq(tm && tm.cmd.say, "move the time {n} minutes earlier", "the written time moves by voice");
  eq(tm && +tm.arg.n, 5, "by the minutes said");
  tm = vMatch(vWords("move it to hour nine"), 0);
  eq(tm && tm.cmd.say, "set the hour to {n}", "and jumps to an hour");
  if (st.sel || st.isNew) {
    var tw = $("#e_created_at_utc").value;
    voiceTime("min", -3);
    eq(utcMs($("#e_created_at_utc").value), utcMs(tw) - 180000, "three minutes earlier is three minutes earlier");
    voiceTime("orig");
    eq($("#e_created_at_utc").value, tw, "and back to the original");
  }
  eq(vMatch(vWords("please save"), 0).cmd.say, "save", "a filler in front of an order is ignored");
  eq(vMatch(vWords("search for the trip computer save"), 0).arg.text, "the trip",
     "a spoken argument stops at the next wake word");
  eq(vMatch(vWords("link graph"), 0).cmd.say, "the graph",
     "at equal length the phrase with no placeholder wins over 'link {*}'");
  ok(!vMatch(vWords("flibbertigibbet"), 0), "an unknown phrase matches nothing");

  console.log("-- voice: dictation goes to the field with the focus --");
  var vrow = st.all.filter(function (e) {
    return !e.deleted && e.kind && !needsBody(e);
  })[0];
  select(vrow.id);
  await settle(6);
  setRead(false);
  $("#content").value = "";
  $("#content").focus();
  $("#content").selectionStart = $("#content").selectionEnd = 0;
  ok(!vx.dict, "the microphone opens listening for orders, not dictating");
  vx.dict = true;             // as "start dictation" leaves it, without the tape
  voiceHeard("this is a test");
  eq($("#content").value, "This is a test", "a sentence starts with a capital");
  voiceHeard("and this follows");
  eq($("#content").value, "This is a test and this follows", "the next one is spaced, not capitalised");
  voiceHeard("period next one");
  eq($("#content").value, "This is a test and this follows. Next one",
     "a full stop closes the sentence and opens the next");

  console.log("-- voice: an order inside the dictation --");
  voiceHeard("more words computer delete last word");
  eq($("#content").value, "This is a test and this follows. Next one more",
     "the words land first, then the order takes the last of them back");
  voiceHeard("computer delete last sentence");
  eq($("#content").value, "This is a test and this follows. ",
     "a sentence goes back to the last full stop");

  console.log("-- voice: while dictating, an order it does not know is words --");
  // "the computer was slow" is a sentence; stopping to ask cost more than it saved
  var before = $("#content").value;
  hideToast();
  voiceHeard("computer polarise the deflector dish");
  eq($("#content").value, before + "Computer polarise the deflector dish",
     "the wake word and what follows it are typed as said");
  ok(!$("#toast").className, "and nothing is refused");
  ok(vx.dict, "dictation carries on");
  voiceHeard("computer undo");
  eq($("#content").value, before, "a spoken undo is the way back");

  console.log("-- voice: paused dictation still answers orders --");
  // with dictation on, an order said without the wake word is only ever words
  voiceHeard("delete last word");
  eq($("#content").value, before + "Delete last word",
     "with dictation ON a bare order is typed, not run");
  voiceHeard("computer undo");
  eq($("#content").value, before, "…and the wake word takes it back");

  voiceHeard("computer pause dictation");
  voiceHeard("this must not land");
  eq($("#content").value, before, "nothing is typed while it is paused");

  console.log("-- voice: paused, an order it does not know types nothing --");
  voiceHeard("computer polarise the deflector dish");
  eq($("#content").value, before, "nothing was typed");
  has($("#toast").textContent, "no order called", "and it says so");
  has($("#toast").innerHTML, "Type it", "offering the words back");
  hideToast();

  console.log("-- voice: paused, the wake word is optional --");
  voiceHeard("computer edit title");
  $("#e_head").value = "keep this";
  voiceHeard("clear the field");
  eq($("#e_head").value, "", "a bare order runs while dictation is paused");
  voiceHeard("undo please");
  eq($("#e_head").value, "keep this", "a trailing filler does not stop it");
  // a bare order has to account for the whole utterance: the microphone is open
  // on a room, and most of what it hears was said to somebody else
  $("#e_head").value = "still here";
  hideToast();
  voiceHeard("clear the field of battle was quiet");
  eq($("#e_head").value, "still here", "a half-match is not an order");
  has($("#vsaid").textContent, "not an order", "and the read-out says why");
  ok(!$("#toast").className, "quietly — nothing shouts at a room it overheard");

  voiceHeard("computer edit content");
  voiceHeard("computer start dictation");
  voiceHeard("back on");
  eq($("#content").value, before + "Back on", "and it types again afterwards");
  voiceHeard("computer undo");
  eq($("#content").value, before, "a spoken undo takes back the last thing it typed");
  // the stack is bounded and must run out gracefully, not throw
  for (var vu = 0; vu < 25; vu++) voiceHeard("computer undo");
  has($("#vsaid").textContent, "nothing to undo", "an exhausted undo stack says so");
  $("#content").value = before;

  console.log("-- voice: an order that moves the focus takes the rest with it --");
  $("#e_head").value = "";
  voiceHeard("computer edit title a fine day");
  eq(document.activeElement.id, "e_head", "the title took the focus");
  eq($("#e_head").value, "A fine day", "and the words after the order landed in it");
  ok(document.body.classList.contains("dirty"), "a dictated edit dirties the form");

  console.log("-- voice: orders that are not typing --");
  voiceHeard("computer mark it done");
  eq($("#e_done_bool").value, "1", "done_bool is set");
  voiceHeard("computer set kind to " + vrow.kind.replace(/_/g, " "));
  eq($("#e_kind").value, vrow.kind, "a spoken kind finds the snake_case one it means");
  voiceHeard("computer edit kind");
  ok($("#ov").classList.contains("on") && $("#dlgh").textContent === "Set the kind",
     "edit kind is the kind picker, as the chip's tap (the field went with design P7)");
  input($("#pkq"), "brand new kind");
  var nkRows = $("#pkrows").querySelectorAll(".pkr");
  has(nkRows[nkRows.length - 1].textContent, "new kind", "a name nobody used is offered as a new kind");
  click(nkRows[nkRows.length - 1]);
  eq($("#e_kind").value, "brand_new_kind", "taken, spaces as underscores");
  eq($("#edkind").textContent, "brand_new_kind", "and the chip says it");
  $("#e_kind").value = vrow.kind; markDirty();
  var vTitle = $("#e_head").value;
  voiceHeard("computer edit title");
  eq(document.activeElement.id, "e_head", "an order can move where the words go");
  voiceHeard("computer clear the field");
  eq($("#e_head").value, "", "the field with the focus is the one cleared");
  has($("#toast").innerHTML, "Undo", "and the clear is offered back");
  click($("#toast").querySelector(".tact"));
  eq($("#e_head").value, vTitle, "undo puts it back");

  setForm(vrow); setClean(); hideToast();
  voiceHeard("computer search for " + vrow.kind);
  eq($("#q").value, vrow.kind, "a spoken search reaches the search box");
  $("#q").value = ""; refresh();

  /* ---------- every feature has an order ----------
     The rule (CLAUDE.md): whatever a key or a button does, a spoken order
     does too. This is its check — each KEYS entry with a function of its own
     must call something a VCMDS order also calls (looking one call deep, so
     voiceNew counts as newEntry). The exemptions say why voice cannot. */
  console.log("-- voice: every key has a spoken order --");
  var VOICE_EXEMPT = {
    m: "the microphone itself: it cannot be opened by speaking into it",
    "/": "'edit search' is voiceGo('#q'), the same box",
  };
  // a key that toggles, where speech says which way: the orders call the halves
  var VOICE_SAME = { ambToggle: ["ambStart", "ambStop"], toggleCol: ["setCol"] };
  var callsIn = function (src) {
    var out = [], re = /([A-Za-z_$][\w$]*)\s*\(/g, m;
    while ((m = re.exec(src))) out.push(m[1]);
    return out;
  };
  var vReach = new Set();
  VCMDS.forEach(function (c) {
    if (!c.fn) return;
    // every name the order mentions, called or handed on (voicePicked(mergePicked))
    (String(c.fn).match(/[A-Za-z_$][\w$]*/g) || []).forEach(function (n) {
      vReach.add(n);
      var f; try { f = eval(n); } catch (err) { f = null; }
      if (typeof f === "function") callsIn(String(f)).forEach(function (m2) { vReach.add(m2); });
    });
  });
  KEYS.forEach(function (k) {
    if (!k.fn || VOICE_EXEMPT[k.key]) return;
    var calls = callsIn(String(k.fn)).filter(function (n) { return n !== "$"; });
    ok(calls.some(function (n) {
         return vReach.has(n) || (VOICE_SAME[n] || []).some(function (h) { return vReach.has(h); });
       }),
       "key " + k.key + " (" + calls.join(", ") + ") has a spoken order in VCMDS — add one, or an exemption saying why not");
  });

  var vSeen = new Map(), vDup = [];
  VPHRASES.forEach(function (p) {
    var k = p.w.join(" ");
    if (vSeen.has(k) && vSeen.get(k) !== p.cmd) vDup.push(k);
    vSeen.set(k, p.cmd);
  });
  eq(vDup.join(" | "), "", "no phrase belongs to two orders");
  // the deck's table in front of this one (lcarsDeckVoice): at a tie the deck's
  var dkHelp = { say: "help", fn: function () {} };
  var dkPh = vPhrases([dkHelp].concat(VCMDS));
  ok(dkPh.find(function (p) { return p.w.join(" ") === "help"; }).cmd === dkHelp, "a deck order wins a tie with the console's");
  ok(dkPh.find(function (p) { return p.w.join(" ") === "start dictation"; }).cmd.say === "start dictation", "and the console's own are still there");

  console.log("-- voice: the orders for the later features --");
  eq(vMatch(vWords("start the timer"), 0).cmd.say, "start the timer", "the stopwatch starts by name");
  var vm = vMatch(vWords("start the timer 10 minutes ago"), 0);
  eq(vm.cmd.say, "start the timer {n} minutes ago", "a start in the past is its own order");
  eq(vm.arg.n, "10", "with its number");
  eq(vMatch(vWords("start the timer from when it was written"), 0).cmd.say,
     "start the timer from when it was written", "and so is a start from the entry's own stamp");
  eq(vMatch(vWords("filter by kind"), 0).cmd.say, "pick a kind", "a bare 'filter by kind' opens the picker");
  eq(vMatch(vWords("filter by kind personal log"), 0).cmd.say, "show only {*}",
     "with a kind after it, it filters");
  eq(vMatch(vWords("new entry called the trip"), 0).arg.text, "the trip",
     "'new entry called …' is longer than 'new entry', so it wins");
  eq(vMatch(vWords("continue"), 0).cmd.say, "start dictation",
     "'continue' still resumes dictation; threads need 'continue this entry'");
  eq(vMatch(vWords("search by meaning for time outdoors"), 0).cmd.say, "search by meaning for {*}",
     "a meaning search is not taken for a text search");

  // the stopwatch, spoken, against the fake API
  var vw = st.byId.get(vrow.id);
  var vwWas = { start_date: vw.start_date || "", end_date: vw.end_date || "" };
  await api("/entries/" + vw.id, { method: "PUT", body: { start_date: "", end_date: "" } });
  await refetchInto(vw);
  setForm(vw); setClean(); hideToast();
  voiceHeard("computer start the timer");
  await settle(6);
  ok(!!dbFind(vw.id).start_date && !dbFind(vw.id).end_date, "'start the timer' writes start_date and leaves end_date empty");
  ok(watchRunning(vw), "and the entry is a running timer");
  var vwStart = dbFind(vw.id).start_date;
  voiceHeard("computer start the timer");
  await settle(6);
  eq(dbFind(vw.id).start_date, vwStart, "a second bare start does not throw the running one away");
  has($("#toast").textContent, "already timing", "it says the timer is running instead");
  voiceHeard("computer stop the timer");
  await settle(6);
  ok(!!dbFind(vw.id).end_date, "'stop the timer' writes end_date");
  voiceHeard("computer resume the timer");
  await settle(6);
  eq(dbFind(vw.id).end_date, "", "'resume the timer' clears it again");
  voiceHeard("computer start the timer 90 minutes ago");
  await settle(6);
  var vwAgo = (Date.now() - parseUtc(dbFind(vw.id).start_date).getTime()) / 60000;
  ok(vwAgo > 85 && vwAgo < 95, "a start said in minutes ago lands that far back  (" + vwAgo + ")");
  // an unsaved edit is saved before the timer writes, not left to undo it
  $("#e_head").value = "voice timer title"; markDirty();
  voiceHeard("computer stop the timer");
  await settle(8);
  eq(dbFind(vw.id).title, "voice timer title", "a dirty form is saved first");
  ok(!!dbFind(vw.id).end_date, "and the timer still stops");
  voiceHeard("computer clear the timer");
  await settle(6);
  ok(!dbFind(vw.id).start_date && !dbFind(vw.id).end_date, "'clear the timer' empties both");
  await api("/entries/" + vw.id, { method: "PUT", body: { title: vrow.title || "", start_date: vwWas.start_date, end_date: vwWas.end_date } });
  await refetchInto(vw);
  setForm(vw); setClean(); hideToast();

  // the kind filter, by voice: an existing kind narrows, a misheard one is refused
  voiceHeard("computer show only " + vrow.kind.replace(/_/g, " "));
  eq(st.kinds.join(","), vrow.kind, "'show only …' pins that kind");
  voiceHeard("computer show only flibbertigibbet");
  eq(st.kinds.join(","), vrow.kind, "a kind the journal does not have changes nothing");
  voiceHeard("computer all kinds");
  eq(st.kinds.length, 0, "'all kinds' clears it");
  hideToast();

  // anything in the palette, by name
  var vSortWas = $("#fSort").value;
  voiceHeard("computer run sort by length");
  eq($("#fSort").value, "len:desc", "'run …' runs the palette row its words name");
  $("#fSort").value = vSortWas; refresh();
  voiceHeard("computer run flibbertigibbet");
  ok($("#ov").classList.contains("on") && $("#pkq") && $("#pkq").value === "flibbertigibbet",
     "with no row to run, the palette opens on the words");
  closeOv(); hideToast();

  // picking, spoken
  voiceHeard("computer pick this one");
  ok(st.picking && st.pick.has(vrow.id), "'pick this one' picks the open entry");
  voiceHeard("computer stop picking");
  ok(!st.picking && !st.pick.size, "'stop picking' drops the picks");

  console.log("-- voice: the panel is built from the table --");
  ok(VPHRASES.length > VCMDS.length, "every alias is a phrase of its own");
  voiceHelp();
  has($("#dlg").innerHTML, "pause dictation", "the panel lists the orders");
  has($("#dlg").innerHTML, "make it so", "aliases and all");
  has($("#dlg").innerHTML, "v_lang", "and carries the language picker");
  closeOv();

  console.log("-- voice: with no recogniser it says so rather than failing --");
  voiceToggle();
  ok(!vx.on, "the toggle does not pretend to listen");
  has($("#toast").textContent, "speech recognition", "it says why");
  hideToast();

  /* ---------- the other recogniser ----------
     There is no WebSocket and no microphone in here either, so what is tested
     is everything up to the socket: which model a language picks, what the
     stream is asked for, that an utterance is assembled out of fragments
     rather than dispatched piecemeal, and that a missing key is a sentence
     rather than a failed connection. */
  console.log("-- voice: the deepgram engine --");
  var vengWas = vcfg.engine, vkeyWas = vcfg.key, vlangWas = vx.lang;
  eq(vEngine(), "browser", "the browser's own recogniser is the default");

  // the key: minted by the server per socket; a pasted one only when it has none
  vcfg.engine = "deepgram"; vcfg.key = "";
  var vtok = null, vtokErr = null;
  dgToken().then(function (t) { vtok = t; });
  await settle(3);
  eq(vtok, "aaaa.bbbb.cccc", "deepgram's key is a token the server mints (GET /say/token)");
  TEST.sayToken = 503; vcfg.key = "pasted-before";
  vtok = null;
  dgToken().then(function (t) { vtok = t; });
  await settle(3);
  eq(vtok, "pasted-before", "a server with no key: an old pasted one, as a fallback");
  vcfg.key = "";
  dgToken().then(null, function (e) { vtokErr = e; });
  await settle(3);
  has(vtokErr && vtokErr.message, "no Deepgram key", "with neither, it says which is missing");
  TEST.sayToken = 403; vtokErr = null;
  dgToken().then(null, function (e) { vtokErr = e; });
  await settle(3);
  has(vtokErr && vtokErr.message, "may not listen", "a login that may not listen is told so");
  TEST.sayToken = 200;
  openCfg();
  has($("#dlg").innerHTML, "c_veng", "Config carries the engine picker");
  ok($("#dlg").innerHTML.indexOf("c_vkey") < 0, "and no key field: no key lives in the browser");
  closeOv();
  hideToast();

  vcfg.key = "not-a-real-key";
  var u = dgUrl(48000);
  has(u, "wss://api.deepgram.com/v1/listen", "the stream goes to deepgram");
  has(u, "model=nova-3", "nova-3 for english");
  has(u, "encoding=linear16", "raw pcm, so every browser sends the same thing");
  has(u, "sample_rate=48000", "at the rate the audio context actually runs");
  has(u, "interim_results=true", "interim results, for the read-out");
  has(u, "utterance_end_ms=1200", "and an utterance end to flush on");
  vx.lang = "ro-RO";
  has(dgUrl(16000), "model=nova-2",
      "a language nova-3 has no model for falls back rather than failing");
  has(dgUrl(16000), "language=ro", "in its own language");
  vx.lang = vlangWas;

  // the fragments Deepgram marks final several times per sentence
  $("#content").value = "";
  $("#content").focus();
  $("#content").selectionStart = $("#content").selectionEnd = 0;
  dg.buf = ["this is"];
  ok($("#content").value === "", "a fragment on its own types nothing");
  dg.buf.push("one utterance");
  dgFlush();
  eq($("#content").value, "This is one utterance",
     "the fragments are joined and handed over as one");
  eq(dg.buf.length, 0, "and the buffer is emptied behind them");
  dgFlush();
  eq($("#content").value, "This is one utterance", "flushing nothing types nothing");

  // an order split across two finals is still one order
  dg.buf = ["computer delete", "last word"];
  dgFlush();
  eq($("#content").value, "This is one",
     "which is what keeps an order from being torn in half");

  /* And the split deepgram actually makes: it ends an utterance at the pause
     after the wake word, so the order arrives in the next one. Held over
     rather than dispatched — otherwise the first asks "computer?" and the
     second is typed into the entry as prose. */
  dg.buf = ["and then we left. Computer,"];
  dgFlush();
  eq($("#content").value, "This is one and then we left.",
     "the words before a trailing wake word are typed at once");
  eq(dg.carry, "Computer,", "the wake word itself waits for what follows it");
  dgFlush();                 // the UtteranceEnd deepgram sends straight after
  eq(dg.carry, "Computer,", "an empty flush does not release it on its own");
  dg.buf = ["delete last word."];
  dgFlush();
  eq($("#content").value, "This is one and then we",
     "and the order it belonged to is obeyed, not typed");
  ok(!dg.carry, "nothing is left carried");

  // dictating, a lone wake word that nothing follows is only a word
  var vlone = $("#content").value;
  dg.buf = ["computer"];
  dgFlush();
  hideToast();
  vx.on = true;              // the carry only ever expires with the mic open
  dgCarryOut();
  vx.on = false;
  eq($("#content").value, vlone + " computer",
     "dictating, a wake word nothing follows is typed, not swallowed");
  ok(!$("#toast").className, "and nothing asks");
  $("#content").value = vlone;

  // paused, it asks
  vx.dict = false;
  dg.buf = ["computer"];
  dgFlush();
  hideToast();
  vx.on = true;
  dgCarryOut();
  vx.on = false;
  vx.dict = true;
  has($("#toast").textContent, "computer?",
      "paused, a wake word nothing follows asks, rather than being swallowed");
  hideToast();

  dgClose();
  ok(!dg.ws && !dg.stream && !dg.ctx && dg.buf.length === 0,
     "closing releases the socket, the microphone and the buffer");
  vcfg.engine = vengWas; vcfg.key = vkeyWas;
  setForm(vrow); setClean();
  closeEditor();

  /* ---------- sound ----------
     There is no Web Audio in QuickJS, so sndPlay never runs for real and
     nothing here can listen. What is worth testing is the layer above it: out
     of everything a single gesture asks for, which sound is chosen — and,
     since sfx() is sprinkled across a hundred call sites that cannot see each
     other, that is the whole of the design. The chosen spec is caught on its
     way to the oscillators and named back. */
  console.log("\n-- sound: one gesture, one voice --");
  var realPlay = sndPlay, heard = [];
  var nameOf = function (spec) {
    return Object.keys(SFX).filter(function (k) { return SFX[k] === spec; })[0];
  };
  sndPlay = function (spec) { heard.push(nameOf(spec)); };
  /* Ask, let the tick fire, collect. The drain matters: these are virtual
     timers, so an sfx() from an earlier test can still be sitting un-fired,
     and an ask that arrives while one is pending is (correctly) folded into
     it rather than heard on its own. A browser never has that problem — the
     tick always comes — so it is the harness that has to catch up first. */
  var say = function () {
    runTimers();
    heard = [];
    for (var i = 0; i < arguments.length; i++) sfx(arguments[i]);
    runTimers();
    var out = heard.join(",");
    heard = [];
    return out;
  };
  /* Nothing still ringing. The drain has to come first: a leftover ask firing
     later would set the floor back up again, and the very next say() would be
     judged against the sound this call was supposed to have cleared. */
  var quiet = function () { runTimers(); sfxAt = 0; sfxRank = 0; };

  quiet();
  eq(say("open"), "open", "one ask, one sound");
  quiet();
  eq(say("nav", "open", "notice"), "open",
     "a gesture that speaks from three layers is heard once, as the loudest");
  quiet();
  eq(say("save", "open"), "save", "and the order they were asked in does not decide it");
  quiet();
  eq(say("nothing at all"), "", "an unknown name is silence, not a throw");

  console.log("-- sound: the floor only silences what it outranks --");
  quiet();
  say("nav");
  sfxAt = Date.now(); sfxRank = SFX.nav.rank;
  eq(say("nav"), "", "a second tick inside the gap is dropped (a held j)");
  sfxAt = Date.now(); sfxRank = SFX.nav.rank;
  eq(say("save"), "save", "a write inside the same gap is not");
  sfxAt = Date.now(); sfxRank = SFX.save.rank;
  eq(say("nav"), "", "and the tick under it still is");

  console.log("-- sound: muting is immediate, remembered, and total --");
  var wasOn = snd.on;
  runTimers();
  quiet();
  heard = [];
  sfx("save");
  snd.on = false;                     // muted between the ask and the tick
  runTimers();
  eq(heard.join(","), "", "a sound already asked for is cancelled by muting");
  snd.on = true;

  sndSet(false);
  eq(sndAc, null, "muting closes the audio context, so the phone's other audio is left alone");
  quiet();
  eq(say("save", "error", "boot"), "", "nothing is heard while muted");
  ok(!JSON.parse(localStorage.getItem("lcars.sound")).on, "and it is remembered");
  ok($("#bSound").classList.contains("mute"), "the button says so");
  eq($("#bSound").getAttribute("aria-pressed"), "false", "aloud, too");
  sndSet(true);
  quiet();
  eq(say("open"), "open", "unmuting brings it back");
  ok(!$("#bSound").classList.contains("mute"), "and the button with it");

  console.log("-- sound: the voice console speaks through the same engine --");
  var chirp = function (kind) {
    runTimers();
    heard = [];
    quiet();
    vChirp(kind);
    runTimers();
    var out = heard.join(",");
    heard = [];
    return out;
  };
  eq(say(), "", "nothing asked, nothing heard");
  eq(chirp("ok"), "vok", "an order answered");
  eq(chirp("down"), "vdown", "the microphone closing");
  eq(chirp("nonsense"), "", "and a kind that does not exist is silent");

  console.log("-- sound: every voice is a playable one --");
  var bad = [];
  Object.keys(SFX).forEach(function (k) {
    var s = SFX[k], last = -1;
    if (!(s.rank > 0) || !(s.v > 0) || !s.t || !s.n.length) bad.push(k + ": shape");
    s.n.forEach(function (n) {
      // an exponential gain ramp cannot touch zero and a frequency of zero
      // cannot be ramped to, so every number here has to be positive
      if (!(n[0] > 0) || !(n[1] >= 0) || !(n[2] > 0)) bad.push(k + ": " + n);
      if (n[3] !== undefined && !(n[3] > 0)) bad.push(k + ": sweep to " + n[3]);
      if (n[1] < last) bad.push(k + ": tones out of order");
      last = n[1];
    });
  });
  eq(bad.join(" | "), "", "every sound in the table is well formed");
  ok(SFX.open.n[0][0] === SFX.close.n[1][0] && SFX.open.n[1][0] === SFX.close.n[0][0],
     "opened and closed are the same two notes, inverted");
  ok(SFX.del.n.map(function (n) { return n[0]; }).reverse().join() ===
     SFX.restore.n.map(function (n) { return n[0]; }).join(),
     "so are deleted and restored");
  ok(SFX.beam.n.every(function (n, i) {
       var m = SFX.beamin.n[i];
       return n[0] === m[3] && n[3] === m[0] && n[1] === m[1] && n[2] === m[2];
     }), "and the transporter's two directions are one sweep, turned over");

  sndPlay = realPlay;
  snd.on = wasOn;

  console.log("\n-- the entry head carries its date --");
  clearFilters();
  refresh();
  var sdRow = st.view[0];
  select(sdRow.id);
  await settle(2);
  eq($("#edtitle .edate").textContent, localOf(sdRow.created_at_utc),
     "the plain local date and time, nothing made up");
  closeEditor();

  console.log("-- the rail's numbers are real --");
  refresh();
  runTimers();
  var lbl = function (k) { return $('.lbl[data-stat="' + k + '"]'); };
  var p3 = function (n) { return String(n).padStart(3, "0"); };
  eq(lbl("shown").dataset.tag, "05-" + p3(st.view.length), "Sort counts the rows in the list");
  has(lbl("shown").title, "in this list", "and says so on hover");
  eq(lbl("streak").dataset.tag, "00-" + p3(ambStats().streak), "Activity is the writing streak");
  eq(lbl("today").dataset.tag, "04-" + p3(ambStats().todayN), "Created is today's count");
  eq(lbl("views").dataset.tag, "01-" + p3(views.length), "Views counts the saved ones");
  eq(lbl("tasks").dataset.tag, "03-" + p3(taskIndex().filter(function (t) {
       return TASK_OPEN.indexOf(t.word) >= 0; }).length), "State counts the open tasks");
  var nowD = new Date();
  eq($("#elbow b").textContent, pad2(nowD.getDate()) + " " + MO[nowD.getMonth()].toUpperCase(),
     "and the elbow reads today's date");
  st.kinds = [st.all[0].kind];
  refresh();
  runTimers();
  eq(lbl("shown").dataset.tag, "05-" + p3(st.view.length), "a filter moves the count with it");
  clearFilters();
  refresh();
  runTimers();

  console.log("-- the transporter --");
  var bRow = $("#list").querySelector(".item");
  eq(beamGrab(+bRow.dataset.id), null, "a row with no layout is not beamed");
  bRow._rect = { left: 0, top: 10, right: 300, bottom: 60, width: 300, height: 50 };
  $("#list")._rect = { left: 0, top: 0, right: 300, bottom: 600, width: 300, height: 600 };
  var beamsBefore = document.body.querySelectorAll(".beam").length;
  beamIn(+bRow.dataset.id);
  ok(bRow.classList.contains("beamin"), "a row arriving fades up");
  eq(document.body.querySelectorAll(".beam.in").length, beamsBefore + 1, "under a sparkle over it");
  runTimers();
  ok(!bRow.classList.contains("beamin"), "and both are gone once it has played");
  eq(document.body.querySelectorAll(".beam").length, beamsBefore, "leaving nothing behind");
  bRow._rect = { left: 0, top: 700, right: 300, bottom: 750, width: 300, height: 50 };
  beamIn(+bRow.dataset.id);
  ok(!bRow.classList.contains("beamin"), "a row scrolled out of the list is not beamed");
  delete bRow._rect;
  delete $("#list")._rect;

  /* ---------- stellar cartography ----------
     Nine topics of five entries each, as vectors: each topic owns a band of
     the dimensions, plus noise. The chart has to find the topics without being
     told, related-by-meaning has to name a topic's other four, and a search
     has to fly to the right one. The server side is api.js's EMB. */
  console.log("-- stellar cartography --");
  var b64s = function (arr) {
    var s = "";
    for (var i = 0; i < arr.length; i++) s += String.fromCharCode(arr[i] & 255);
    return btoa(s);
  };
  eq(Array.from(starB64(b64s([1, -2, 127, -127, 0]))).join(","), "1,-2,127,-127,0",
     "a vector's base64 decodes to the same signed bytes");
  eq(starB64(b64s([5, 6, 7, 8])).length, 4, "whatever padding the length needs");
  var u = starUnit(Int8Array.from([3, 4]));
  ok(Math.abs(u[0] - 0.6) < 1e-6 && Math.abs(u[1] - 0.8) < 1e-6, "and is taken to unit length");

  closeOv();
  closeEditor();
  // an old server: the chart says what it lacks rather than drawing nothing
  EMB = null;
  EMB_CODE = 404;
  sv.at = 0;
  await openStars();
  ok($("#ov").classList.contains("on") && $("#scanvas"), "the star chart opens on a canvas");
  has($("#sempty").textContent, "/embeddings", "an old server is told apart: it needs the route");
  closeOv();
  EMB_CODE = 503;
  await openStars();
  has($("#sempty").textContent, "LCARS_EMBED=0", "and a server with embeddings off is named as such");
  closeOv();

  var SDIM = 72, srng = starRng(42), topic = {};
  var starVec = function (g) {
    var a = [];
    for (var t = 0; t < SDIM; t++)
      a.push(Math.round((Math.floor(t / 8) === g ? 80 : 0) + (srng() - 0.5) * 40));
    return a;
  };
  var sLive = st.all.filter(function (e) { return !e.deleted; }).slice(0, 45);
  EMB = { model: "e5@test", dim: SDIM, rows: sLive.map(function (e, i) {
    topic[e.id] = i % 9;
    return [e.id, b64s(starVec(i % 9)), "2026-09-01 10:00:00"];
  }) };
  var sMap = new Map(), keptStore = starStore;
  starStore = {
    get: function (k) { return Promise.resolve(sMap.get(k)); },
    put: function (k, v) { sMap.set(k, v); return Promise.resolve(); },
  };
  var chartDone = async function () {
    // the sync, the kept chart's read and the layout are three awaits apart,
    // so what is waited for is their end: a chart, and no job laying one out
    for (var w = 0; w < 3000 && (sv.busy || sc.job || !sc.lay); w++) { await pump(4); runTimers(20); }
  };
  sv.at = 0;
  key("S");
  ok($("#ov").classList.contains("on") && $("#scanvas"), "S opens the chart");
  await chartDone();
  ok(sc.lay && sc.lay.ids.length === 45, "every entry with a vector is a star (" +
     (sc.lay && sc.lay.ids.length) + ")");
  eq(sv.vec.size, 45, "the vectors are held, one per entry");
  ok(sMap.get("vec") && sMap.get("vec").ids.length === 45, "and kept on the device");
  ok(sMap.get("lay") && sMap.get("lay").ids.length === 45, "the chart too");
  ok(TEST.fetches.some(function (f) { return f === "GET /embeddings"; }), "fetched whole the first time");

  // does the chart find the topics? each star nearer its own topic's middle
  var cen = [];
  for (var g = 0; g < 9; g++) cen.push([0, 0, 0]);
  for (var i = 0; i < sc.lay.ids.length; i++) {
    var c = cen[topic[sc.lay.ids[i]]];
    c[0] += sc.lay.x[i]; c[1] += sc.lay.y[i]; c[2]++;
  }
  cen.forEach(function (c) { c[0] /= c[2]; c[1] /= c[2]; });
  var home = 0;
  for (var i = 0; i < sc.lay.ids.length; i++) {
    var mine = topic[sc.lay.ids[i]], best = -1, bd = Infinity;
    for (var g = 0; g < 9; g++) {
      var dx = sc.lay.x[i] - cen[g][0], dy = sc.lay.y[i] - cen[g][1];
      if (dx * dx + dy * dy < bd) { bd = dx * dx + dy * dy; best = g; }
    }
    if (best === mine) home++;
  }
  ok(home >= 42, "the chart finds the topics unaided: " + home + " of 45 stars sit with their own");

  // the statistics group the same vectors into topics
  var tj = statTopicsJob(function () { return false; }), tr2;
  do { tr2 = tj.next(); } while (!tr2.done);
  ok(tr2.value && tr2.value.topics.length >= 2, "the statistics find topics in the vectors (" +
     (tr2.value && tr2.value.topics.length) + ")");
  var tsum = tr2.value.topics.reduce(function (s, t) { return s + t.n; }, 0);
  ok(tsum <= 45 && tsum >= 35, "and put nearly every entry in one (" + tsum + " of 45)");
  ok(tr2.value.topics.every(function (t) { return t.months.length === 18; }), "each with eighteen months of history");
  ok(sc.lay.labels.every(function (l) { return l.words.length >= 1 && l.words.length <= 2; }),
     "every constellation is named by a word or two");
  has($("#snote").innerHTML, "45 stars", "the frame counts its stars");

  // drawing: every star into one pixel buffer, put on the canvas once
  var puts = 0, texts = 0, fake = {};
  ["setTransform", "fillRect", "beginPath", "moveTo", "lineTo", "arc", "rect", "stroke",
   "strokeText", "fill"].forEach(function (m) { fake[m] = function () {}; });
  fake.createImageData = function (w, h) {
    return { width: w, height: h, data: new Uint8ClampedArray(w * h * 4) };
  };
  fake.putImageData = function () { puts++; };
  fake.measureText = function (t) { return { width: t.length * 7 }; };
  fake.fillText = function () { texts++; };
  sc.ctx = fake;
  sc.w = 800; sc.h = 600; sc.dpr = 1;
  sc.buf = null;
  starFit();
  starDraw();
  eq(puts, 1, "a frame puts its stars on the canvas in one call");
  var lit = 0, px = sc.buf.u32;
  for (var i = 0; i < px.length; i++) if (px[i] !== 0xff000000 && (px[i] & 0xff) > 0x60) lit++;
  ok(lit >= 45, "with every star in it, in its kind's colour (" + lit + " bright pixels)");
  var c0 = sc.lay.ids[0], sx0 = Math.round(starX(0)), sy0 = Math.round(starY(0));
  var at0 = px[sy0 * 800 + sx0];
  var rgb0 = starRGB(kindColor(st.byId.get(c0).kind));
  // star 0 may sit under a later neighbour, so the test is only that a lit
  // star's colour is there — one of the chart's kinds, at full strength
  var kindPx = sc.groups.map(function (g) { var c = starRGB(g.col); return starABGR(c[0], c[1], c[2]); });
  ok(kindPx.indexOf(at0) >= 0, "a star's pixels are a kind's colour, where the chart puts it");
  sc.year = 1999;
  starDraw();
  at0 = px[sy0 * 800 + sx0];
  ok(kindPx.indexOf(at0) < 0 && at0 !== 0xff000000, "a year with nothing in it dims every star, without hiding it");
  sc.year = 0;
  starDraw();

  // a click picks a star, and draws its nearest by meaning
  $("#scanvas")._rect = { left: 0, top: 0, right: 800, bottom: 600, width: 800, height: 600 };
  var pickI = 7, pickId = sc.lay.ids[pickI];
  var px = starX(pickI), py = starY(pickI);
  eq(starHit(px, py), pickI, "the star under the pointer is the one hit");
  dispatch($("#scanvas"), "pointerdown", { pointerId: 1, clientX: px, clientY: py });
  dispatch($("#scanvas"), "pointerup", { pointerId: 1, clientX: px, clientY: py });
  eq(sc.sel, pickI, "a click selects it");
  ok($("#scard").classList.contains("on"), "and its card comes up");
  has($("#scard").innerHTML, "#" + pickId, "naming the entry");
  eq(sc.near.length, STAR_NEAR, "its nearest stars are drawn to it");
  var mates = sc.near.filter(function (j) { return topic[sc.lay.ids[j]] === topic[pickId]; });
  eq(mates.length, 4, "the four that share its topic are among them");
  // a drag is a flight, not a click
  var tx0 = sc.tx;
  dispatch($("#scanvas"), "pointerdown", { pointerId: 2, clientX: 100, clientY: 100 });
  dispatch($("#scanvas"), "pointermove", { pointerId: 2, clientX: 160, clientY: 100 });
  dispatch($("#scanvas"), "pointerup", { pointerId: 2, clientX: 160, clientY: 100 });
  eq(sc.tx - tx0, 60, "a drag pans the chart");
  eq(sc.sel, pickI, "and leaves the selection alone");

  // a search by meaning: the query's vector sits in topic 4
  EMBQ = function () { return b64s(starVec(4)); };
  $("#sq").value = "whatever topic four is about";
  dispatch($("#sq"), "keydown", { key: "Enter" });
  await settle(3);
  ok(sc.hits && sc.hits.size > 0, "a search lights stars up");
  eq(topic[sc.lay.ids[sc.sel]], 4, "and selects the nearest, in the topic the query is about");
  var litI = [];
  sc.hits.forEach(function (j) { litI.push(j); });
  var firstFive = litI.slice(0, 5).filter(function (j) { return topic[sc.lay.ids[j]] === 4; });
  eq(firstFive.length, 5, "its five nearest are the topic's five");
  ok(TEST.fetches.some(function (f) { return f === "POST /embed"; }), "the query was embedded by the server");
  input($("#sq"), "");
  eq(sc.hits, null, "an emptied search box lights nothing");
  // no /embed: the words in the entries answer instead
  EMBQ = null;
  var wordOf = (sLive[3].title || "").split(/\s+/).filter(function (w) { return w.length > 3; })[0];
  if (wordOf) {
    await starSearch(wordOf);
    ok(sc.hits && sc.hits.size > 0, "without /embed a search still answers, by words");
  }

  // Open takes the reader to the entry
  starSelect(pickI);
  click($("#sopen"));
  ok(!$("#ov").classList.contains("on"), "Open closes the chart");
  eq(st.sel && st.sel.id, pickId, "and opens the entry the star is");

  // possibly related, by meaning
  await drainExtras();
  has($("#rd_rel").innerHTML, "close in meaning", "the reader's related rows are by meaning now");
  var relIds = [];
  $("#rd_rel").querySelectorAll(".blrow").forEach(function (b) { relIds.push(+b.dataset.id); });
  ok(relIds.length === 4 && relIds.every(function (id) { return topic[id] === topic[pickId]; }),
     "and they are exactly its topic's other four (" + relIds.join(",") + ")");
  var noVec = st.all.filter(function (e) { return !e.deleted && !sv.vec.has(e.id); })[0];
  if (noVec) {
    var rw = related(noVec);
    ok(rw.rows.every(function (x) { return !x.sim; }), "an entry with no vector keeps the word-based list");
  }

  // a second open: the kept chart, caught up with a new star
  var newE = st.all.filter(function (e) { return !e.deleted && !topic.hasOwnProperty(e.id); })[0];
  topic[newE.id] = 2;
  EMB.rows.push([newE.id, b64s(starVec(2)), "2026-09-02 10:00:00"]);
  var layWas = sc.lay;
  sv.at = 0;
  var fetchN = TEST.fetches.length;
  await openStars();
  await chartDone();
  ok(TEST.fetches.slice(fetchN).some(function (f) { return f.indexOf("GET /embeddings?since=") === 0; }),
     "the second open asks only for what is new");
  ok(sc.lay === layWas, "the chart is kept, not laid out again");
  eq(sc.lay.ids.length, 46, "the new entry is a star");
  eq(sc.lay.placed, 1, "placed by its neighbours, and counted as such");
  var ni = sc.lay.ids.indexOf(newE.id);
  var d2 = function (g) {
    var dx = sc.lay.x[ni] - cen[g][0], dy = sc.lay.y[ni] - cen[g][1];
    return dx * dx + dy * dy;
  };
  ok([0, 1, 3, 4, 5, 6, 7, 8].every(function (g) { return d2(2) < d2(g); }),
     "among the topic it is about");
  has($("#snote").innerHTML, "placed by their neighbours", "the frame says some stars were placed");
  closeOv();

  // the chart comes back from the device with no layout run at all
  sc.lay = null;
  sv.at = 0;
  await openStars();
  ok(!sc.job && sc.lay && sc.lay.ids.length === 46, "a reopened page draws the kept chart");
  click($("#sredo"));
  ok(sc.job, "Re-chart lays it out again");
  await chartDone();
  eq(sc.lay.placed, 0, "from scratch, with nothing placed by neighbours");
  closeOv();
  ok(!sc.open && !sc.raf, "closing stops the chart");

  // an entry whose meaning changed is placed again, and counted
  var movedId = sLive[0].id, mi = sc.lay.ids.indexOf(movedId);
  EMB.rows.forEach(function (r) {
    if (r[0] === movedId) { r[1] = b64s(starVec(6)); r[2] = "2026-09-03 10:00:00"; }
  });
  sv.at = 0;
  await openStars();
  await chartDone();
  ok(sc.lay.placed === 1, "an edited entry is placed again where its new meaning is (" + sc.lay.placed + ")");
  var dm = function (g) {
    var dx = sc.lay.x[mi] - cen[g][0], dy = sc.lay.y[mi] - cen[g][1];
    return dx * dx + dy * dy;
  };
  ok([0, 1, 2, 3, 4, 5, 7, 8].every(function (g) { return dm(6) < dm(g); }),
     "which is among the topic it is about now");
  closeOv();

  // constellations are named by what entries say, not how they were filed
  var sw = starWords({ kind: "bike_ride", title: "Evening",
    content: "type:: Person\nsource:: capacities/People\n![shot](assets/a.png) " +
             "[the park](https://example.com/x) https://example.org/y walked home" });
  ok(sw.has("bike") && sw.has("ride"), "a kind's parts are words");
  ok(sw.has("evening") && sw.has("park") && sw.has("walked"), "and so are the title and the text");
  ok(!sw.has("type") && !sw.has("person") && !sw.has("source") && !sw.has("capacities"),
     "but not property lines");
  ok(!sw.has("shot") && !sw.has("example") && !sw.has("https") && !sw.has("assets"),
     "nor images, link targets or bare URLs");
  eq([...starWords({ kind: "personal_log", title: "", content: "Am mers în parc cu cățelul" })].sort().join(","),
     "cățelul,mers,parc", "Romanian keeps its letters, and loses its small words");

  // spoken
  var vh = vMatch(vWords("chart the garden"), 0);
  ok(vh && vh.cmd.say === "chart {*}" && vh.arg.text === "the garden",
     "\"chart …\" is an order, with the topic as its argument");
  var vh2 = vMatch(vWords("star chart"), 0);
  ok(vh2 && vh2.cmd.say === "star chart", "and \"star chart\" opens it");

  console.log("-- plot a course: the trip as text, its times, its orders --");
  var ct = crsParse("**x**\n\n```json trip\n" + JSON.stringify({ v: 1, depart: "2026-10-12T08:00",
    points: [{ name: "A", lat: 45, lon: 25 }, { name: "B", lat: "45.1", lon: 25.1, stay: "30" }, { q: "Omu Peak" }],
    legs: [{ mode: "foot_hiking" }, { mode: "nonsense" }, { mode: "car_fast" }] }) + "\n```\n");
  ok(ct && ct.points.length === 3, "a fenced trip parses");
  eq(ct.points[1].lat, 45.1, "coordinates are numbers");
  eq(ct.points[1].stay, 30, "and so is a stay");
  eq(ct.points[2].q, "Omu Peak", "a point by name only waits to be looked up");
  eq(ct.legs.length, 2, "one leg fewer than points, whatever was written");
  eq(ct.legs[1].mode, "car_fast", "an unknown mode is driving");
  ok(crsParse('{"points":[]}') !== null, "the bare object (the navigator's way) parses too");
  eq(crsParse("just words"), null, "and words are not a trip");
  var tm = crsTimes(ct, [{ dur: 3600 }, { dur: 1800 }]);
  eq(crsHm(tm[0].leave), "08:00", "the course leaves at its departure");
  eq(crsHm(tm[1].arrive), "09:00", "a leg takes its duration");
  eq(crsHm(tm[1].leave), "09:30", "a stop its stay");
  eq(crsHm(tm[2].arrive), "10:00", "and the next leg starts after it");
  eq(crsTimes(ct, [{ dur: 3600 }])[2].arrive, null, "a leg not routed yet leaves what follows unknown");
  var lv = crsParse(JSON.stringify({ depart: "2026-10-12T08:00", points: [{ name: "A", lat: 45, lon: 25 },
    { name: "Hut", lat: 45.1, lon: 25.1, stay: 30, leave: "2026-10-13T07:00" }, { name: "Top", lat: 45.2, lon: 25.2 }],
    legs: [{ mode: "foot_hiking" }, { mode: "foot_hiking" }] }));
  eq(lv.points[1].leave, "2026-10-13T07:00", "a stop keeps its own leave time");
  var lt = crsTimes(lv, [{ dur: 3 * 3600 }, { dur: 3600 }]);
  ok(lt[1].fixed && !lt[1].late && lt[1].wait === 20 * 60, "it waits there until then, whatever its stay (" + lt[1].wait + " min)");
  eq(crsHm(lt[2].arrive), "08:00", "and what follows runs from that time");
  eq(crsTimes(lv, [null, { dur: 3600 }])[2].arrive.getDate(), 13, "a fixed leave time knows the rest even with a leg unrouted before it");
  lv.points[1].leave = "2026-10-12T09:00";
  var ll = crsTimes(lv, [{ dur: 3 * 3600 }, { dur: 3600 }]);
  ok(ll[1].late && crsHm(ll[1].leave) === "11:00", "arriving after it leaves on arrival, and says it is late");
  ok(/, leave [^\n]*07:00/.test(crsSummary(crsParse(JSON.stringify(Object.assign({}, lv, { points: lv.points.map(function (p, i) {
       return i === 1 ? Object.assign({}, p, { leave: "2026-10-13T07:00" }) : p; }) }))), [{ dur: 3 * 3600 }, { dur: 3600 }], "x")),
     "the summary says when the stop is left");
  var cc = crsContent(ct, [{ len: 5000, dur: 3600 }, { len: 1000, dur: 1800 }], "Walk");
  ok(/Total 6\.0 km/.test(cc) && /arrives/.test(cc), "the summary totals the legs");
  eq(crsParse(cc).points.length, 3, "and the trip survives its own summary");
  var vc = vMatch(vWords("plot a course to brasov"), 0);
  ok(vc && vc.cmd.say === "plot a course to {*}" && vc.arg.text === "brasov", "\"plot a course to …\" is a trip now");
  eq(vMatch(vWords("plot a course"), 0).cmd.say, "plot a course", "and the bare order opens the courses");
  eq(vMatch(vWords("navigator add a lunch stop"), 0).cmd.say, "navigator {*}", "the navigator takes orders by name");
  eq(vMatch(vWords("show the navigator"), 0).cmd.say, "show the navigator", "the navigator's sheet is shown by name, not asked \"show the\"");
  eq(vMatch(vWords("hide the navigator"), 0).cmd.say, "hide the navigator", "and folded away");
  eq(vMatch(vWords("map only"), 0).cmd.say, "hide the navigator", "\"map only\" folds the sheet whatever it shows");
  eq(vMatch(vWords("show the itinerary"), 0).cmd.say, "show the itinerary", "the itinerary has its own order");
  eq(vMatch(vWords("map layers"), 0).cmd.say, "map layers", "and the layers");
  eq(vMatch(vWords("show it on the map"), 0).cmd.say, "show it on the map", "a trip in the reader goes to its map");
  eq(vMatch(vWords("back to the entry"), 0).cmd.say, "show the entry", "and the map back to its entry");

  console.log("-- a part of the course: the hike alone, its own numbers, and back --");
  // drive to the trailhead, walk to the hut, hike to the peak, hike down, drive home
  var ft = crsParse(JSON.stringify({ depart: "2026-10-12T08:00", points: [
    { name: "Home", lat: 44.45, lon: 26.05 }, { name: "Busteni", lat: 45.41, lon: 25.53 },
    { name: "Hut", lat: 45.42, lon: 25.5, stay: 30 }, { name: "Omu", lat: 45.445, lon: 25.457 },
    { name: "Busteni", lat: 45.411, lon: 25.531 }, { name: "Home", lat: 44.451, lon: 26.051 }],
    legs: [{ mode: "car_fast" }, { mode: "foot_fast" }, { mode: "foot_hiking" }, { mode: "foot_hiking" }, { mode: "car_fast_traffic" }] }));
  var fc = [{ len: 140000, dur: 7200 }, { len: 2000, dur: 1800, asc: 200, desc: 0 },
    { len: 5000, dur: 10800, asc: 1100, desc: 50 }, { len: 6000, dur: 9000, asc: 50, desc: 1250 }, { len: 141000, dur: 9000 }];
  eq(JSON.stringify(crsParts(ft)), '[{"a":0,"b":0},{"a":1,"b":3},{"a":4,"b":4}]',
     "the parts are the runs of one means: a walk and a hike are both on foot");
  eq(crsPartLabel(ft, 1, 3), "On foot", "a run of mixed foot legs is on foot");
  eq(crsPartLabel(ft, 4, 4), "Drive", "a drive with traffic is a drive");
  eq(crsPartLabel(ft, 2, 2), "Leg 3", "and a single leg inside a part is a leg");
  var fs = crsSpan(ft, fc, 1, 3);
  ok(fs.len === 13000 && fs.dur === 21600 && fs.asc === 1350 && fs.desc === 1300, "a part's numbers are its legs' alone");
  eq(crsHm(fs.leave) + "→" + crsHm(fs.arrive), "10:00→16:30", "and it runs from leaving its first stop to reaching its last");
  eq(crsSpan(ft, fc.slice(0, 2), 1, 3), null, "a part not routed yet has no numbers");
  var ff = function (s) { var r = crsFocusFind(ft, s); return r ? r.a + "-" + r.b : null; };
  eq(ff("the hike"), "1-3", "\"the hike\" is the foot part");
  eq(ff("drive"), "0-0", "\"drive\" the first drive, of two the same length or less");
  eq(ff("leg 3"), "2-2", "a leg by number");
  eq(ff("part two"), "1-3", "a part by number, said as a word");
  eq(ff("last part"), "4-4", "the last part");
  eq(ff("bike"), null, "and a part it does not have is none");
  var fv = vMatch(vWords("focus hike"), 0);
  ok(fv && fv.cmd.say === "focus {*}" && fv.arg.text === "hike", "\"focus hike\" is the order");
  eq(vMatch(vWords("focus"), 0).cmd.say, "focus mode", "while \"focus\" alone is still focus mode");
  eq(vMatch(vWords("focus mode"), 0).cmd.say, "focus mode", "and so is \"focus mode\"");
  eq(vMatch(vWords("whole trip"), 0).cmd.say, "whole trip", "\"whole trip\" is the way back");
  eq(vMatch(vWords("show the whole course"), 0).cmd.say, "whole trip", "said either way");
  // on screen: the chips in the sheet's head, the map's numbers, and back
  var fr = await api("/entries", { method: "POST", body: { kind: kindOf("trip"), title: "Omu day",
    content: crsContent(ft, [], "Omu day"), start_date: "2026-10-12 05:00:00" } });
  insertRow(await api("/entries/" + fr.id));
  if (!hadRaf) globalThis.requestAnimationFrame = function (f) { return setTimeout(f, 16); };
  crsOpen(st.byId.get(fr.id));
  await settle(2);
  ok($("#crsSheet") && crs.id === fr.id, "the course opens");
  crs.calc = fc.slice();
  crsPaintList();
  var fchips = $("#crsParts").querySelectorAll("[data-part]");
  ok(!$("#crsParts").hidden && fchips.length === 4, "the head offers the whole trip and its three parts");
  eq(fchips[0].getAttribute("aria-pressed"), "true", "the whole trip, to begin with");
  ok(/Drive 1–2/.test(fchips[1].textContent) && /On foot 2–5/.test(fchips[2].textContent), "each part named, with its stops");
  ok(/^294 km · /.test($("#crsSum").textContent), "the head totals the whole trip: " + $("#crsSum").textContent);
  click(fchips[2]);
  ok(crsFocus() && crsFocus().a === 1 && crsFocus().b === 3, "a part's chip focuses it");
  ok(/^On foot · 13 km · 6h · ↑1350 m · 10:00–16:30$/.test($("#crsSum").textContent),
     "and the head is its numbers alone: " + $("#crsSum").textContent);
  eq($("#crsParts [aria-pressed=true]").dataset.part, "1-3", "its chip pressed");
  ok($("#crsList [data-pt='0']").className.indexOf("cout") >= 0 && $("#crsList [data-pt='2']").className.indexOf("cout") < 0,
     "the itinerary dims what is outside it");
  eq(crsLegIn(0) + "," + crsLegIn(2) + "," + crsPtIn(4) + "," + crsPtIn(5), "false,true,true,false", "the map draws the part alone");
  crsInsert(2, { lat: 45.43, lng: 25.48 });
  ok(crsFocus() && crsFocus().a === 1 && crsFocus().b === 4, "a stop put on its route widens the part: " + JSON.stringify(crs.focus) + " " + crs.t.legs.length);
  crsRemove(3);
  eq(crsFocus(), null, "and a stop taken away gives the whole course back");
  crs.calc = fc.slice();
  crsFocusSay("the hike");
  ok(crsFocus() && crsFocus().a === 1, "the voice order focuses");
  dispatch($("#dlg"), "keydown", { key: "Escape" });
  eq(crsFocus(), null, "Escape is the way back to the whole trip");
  ok($("#crsSheet"), "and the course is still open");
  click($("#crsList [data-focus='4']"));
  eq(crsFocus() && crsFocus().a, 4, "a leg's own button focuses that leg");
  eq($("#crsParts [aria-pressed=true]").dataset.part, "4-4", "which is the last drive's chip");
  click($("#crsParts [data-part='']"));
  eq(crsFocus(), null, "and Whole trip is the way back");
  ok(/stops$|arr /.test($("#crsSum").textContent) && !/^Drive/.test($("#crsSum").textContent), "to the whole trip's numbers");
  crsFocusNext();
  eq(crsFocus().a + "-" + crsFocus().b, "0-0", "P walks the parts");
  crsFocusNext(); crsFocusNext(); crsFocusNext();
  eq(crsFocus(), null, "and past the last comes back to the whole trip");

  console.log("-- a leg's mode changed in the itinerary: re-routed, its numbers new, saved --");
  // every leg routed, each keyed the way crsRoute keys it, so nothing but the
  // changed leg is asked for again
  var mt = crsTimes(crs.t, fc);
  crs.calc = fc.map(function (c, i) {
    var t = crs.t, dep = crsDepHour(t.legs[i].mode, mt[i].leave || crsDepart(t));
    return Object.assign({ key: crsLegKey(t.points[i], t.points[i + 1], t.legs[i].mode, dep) }, c);
  });
  crsPaintList();
  var msel = $("#crsList select[data-leg='2']");
  ok(msel && msel.querySelector("option[selected]").getAttribute("value") === "foot_hiking", "leg 3 is a hike");
  // <body> carries data-focus (the editor's focus mode): a tap anywhere in the
  // list once matched it, focused nothing and repainted the list, and the
  // phone's picker, opened by that tap, lost its choice with its select
  click(msel);
  ok($("#crsList select[data-leg='2']") === msel, "a tap on the mode leaves the list as it is, so the picker keeps its select");
  eq(crsFocus(), null, "and focuses nothing");
  click($("#crsList [data-pt='3'] [data-act='go']"));
  eq(crs.sel, 3, "a stop's own button gets through too");
  // the driven route, held until the test lets it land
  var mland, mpts = [crs.t.points[2], crs.t.points[3]];
  crsRoutes.set("car_fast|" + mpts.map(function (p) { return p.lat + "," + p.lon; }).join(";") + "||free",
                new Promise(function (r) { mland = r; }));
  change(msel, "car_fast");
  eq(crs.t.legs[2].mode, "car_fast", "picking Drive drives the leg");
  var mleg = $("#crsList select[data-leg='2']").parentNode;
  eq(mleg.querySelector("option[selected]").getAttribute("value"), "car_fast", "the list shows it at once");
  ok(/#9cf/.test(mleg.getAttribute("style")), "in a drive's colour");
  ok(/plotting/.test(mleg.textContent) && mleg.textContent.indexOf(crsFmtKm(5000)) < 0,
     "and says it is plotting, not the hike's numbers, while the route loads: " + mleg.textContent.replace(/\s+/g, " "));
  mland([{ geo: [[45.42, 25.5], [45.445, 25.457]], len: 9000, dur: 1200, by: "brouter" }]);
  await settle(4);
  eq(crs.calc[2] && crs.calc[2].len, 9000, "the route lands");
  mleg = $("#crsList select[data-leg='2']").parentNode;
  ok(!/plotting/.test(mleg.textContent) && mleg.textContent.indexOf(crsFmtKm(9000)) >= 0 && mleg.textContent.indexOf(crsFmtDur(1200)) >= 0,
     "and the leg has its new numbers: " + mleg.textContent.replace(/\s+/g, " "));
  var msaved = JSON.parse(CRS_FENCE.exec(st.byId.get(fr.id).content)[1]);
  ok(msaved && msaved.legs[2].mode === "car_fast" && msaved.calc && msaved.calc[2].len === 9000,
     "the course is saved with the drive and its numbers");
  clearTimeout(crs.saveT); crs.saveT = 0;
  closeOv();
  await settle(2);

  console.log("-- a course opened to look at it, routing failing: nothing written --");
  // QA 2026-10-13 #1: yesterday's trip, opened with every router and
  // Open-Meteo unreachable
  var lt = crsParse(crsContent(ft, [], "x"));
  lt.points = lt.points.slice(0, 3); lt.legs = lt.legs.slice(0, 2);
  var ldep = new Date(Date.now() - 864e5); ldep.setSeconds(0, 0);
  lt.depart = localInput(ldep).slice(0, 16);
  var lcalc = [{ len: 25000, dur: 1920, wx: "sunny 21°" }, { len: 3000, dur: 2400, asc: 300, desc: 0, wx: "cloudy 15°" }];
  var lsd = crsUtcStamp(crsDepart(lt));
  var lr = await api("/entries", { method: "POST", body: { kind: kindOf("trip"), title: "Look only",
    content: crsContent(lt, lcalc, "Look only"), start_date: lsd } });
  insertRow(await api("/entries/" + lr.id));
  var lrow = st.byId.get(lr.id), lwas = { content: lrow.content, sd: lrow.start_date, ed: lrow.end_date };
  var lFetch = fetch, lOut = [], lPut = 0;
  fetch = function (url, init) {
    var u = String(url);
    if (/brouter|open-meteo|mapy|nominatim/.test(u)) { lOut.push(u); return Promise.reject(new Error("offline")); }
    if (init && init.method === "PUT" && u.indexOf("/entries/" + lr.id) >= 0) lPut++;
    return lFetch.apply(this, arguments);
  };
  crs.key = null;
  crsOpen(lrow);
  await settle(2);
  // what crsOpen does once the map is up (the shim has no Leaflet)
  crsChanged({ save: false, fit: true });
  await settle(4);
  runTimers(5000);
  await settle(2);
  ok(lOut.some(function (u) { return /brouter/.test(u); }), "the router was asked, and could not answer");
  eq(lOut.filter(function (u) { return /open-meteo/.test(u); }).length, 0, "the weather is not asked for a trip already over");
  eq(lPut, 0, "opening the course writes nothing");
  lrow = st.byId.get(lr.id);
  ok(lrow.content === lwas.content && lrow.start_date === lwas.sd && lrow.end_date === lwas.ed,
     "the row is as it was: its numbers and its dates");
  ok(crs.calc[0] && crs.calc[0].len === 25000 && crs.calc[0].by === "saved" && !crs.calc[0].err,
     "a leg that cannot be routed now keeps what was saved for it");
  eq(crs.calc[1] && crs.calc[1].wx, "cloudy 15°", "and its weather");
  ok(/^28 km · /.test($("#crsSum").textContent), "the head still totals it: " + $("#crsSum").textContent);
  // the captain moves the departure: now the plan changed, and start_date
  // follows it; the numbers kept still go with it
  var ldep2 = new Date(ldep.getTime() + 36e5);
  $("#crsDep").value = localInput(ldep2).slice(0, 16);
  dispatch($("#crsDep"), "change");
  await settle(4);
  runTimers(5000);
  await settle(4);
  lrow = st.byId.get(lr.id);
  ok(lPut > 0 && lrow.start_date === crsUtcStamp(crsDepart(crs.t)), "a changed departure writes start_date: " + lrow.start_date);
  var lsaved = JSON.parse(CRS_FENCE.exec(lrow.content)[1]);
  ok(lsaved.calc && lsaved.calc[0].len === 25000 && lsaved.calc[1].dur === 2400, "with the legs' saved numbers, not an error");
  fetch = lFetch;
  clearTimeout(crs.saveT); crs.saveT = 0;
  closeOv();
  await settle(2);

  console.log("-- a course opened in another zone: its start_date stays --");
  // QA 2026-10-13 #2: depart is a wall-clock time with no zone. Planned six
  // hours off this device's zone, its start_date is not this device's
  // reading of depart; a change that does not touch the times (the name)
  // leaves it, and only a new departure writes it
  var zt = crsParse(crsContent(ft, [], "x"));
  zt.points = zt.points.slice(0, 2); zt.legs = zt.legs.slice(0, 1);
  var zdep = new Date(Date.now() + 3 * 864e5); zdep.setMinutes(0, 0, 0);
  zt.depart = localInput(zdep).slice(0, 16);
  var zsd = crsUtcStamp(new Date(crsDepart(zt).getTime() - 6 * 36e5));
  var zr = await api("/entries", { method: "POST", body: { kind: kindOf("trip"), title: "Planned abroad",
    content: crsContent(zt, [{ len: 9000, dur: 900 }], "Planned abroad"), start_date: zsd } });
  insertRow(await api("/entries/" + zr.id));
  var zPut = 0;
  fetch = function (url, init) {
    var u = String(url);
    if (/brouter|open-meteo|mapy|nominatim/.test(u)) return Promise.reject(new Error("offline"));
    if (init && init.method === "PUT" && u.indexOf("/entries/" + zr.id) >= 0) zPut++;
    return lFetch.apply(this, arguments);
  };
  crsOpen(st.byId.get(zr.id));
  await settle(2);
  crsChanged({ save: false, fit: true });
  await settle(4);
  runTimers(5000);
  await settle(2);
  ok(zPut === 0 && st.byId.get(zr.id).start_date === zsd, "opening it writes nothing");
  $("#crsCalled").value = "Planned abroad, renamed";
  dispatch($("#crsCalled"), "change");
  await settle(4);
  runTimers(5000);
  await settle(4);
  var zrow = st.byId.get(zr.id);
  ok(zPut > 0 && zrow.title === "Planned abroad, renamed", "a new name is saved");
  eq(zrow.start_date, zsd, "and start_date stays where it was planned");
  var zdep2 = new Date(zdep.getTime() + 2 * 36e5);
  $("#crsDep").value = localInput(zdep2).slice(0, 16);
  dispatch($("#crsDep"), "change");
  await settle(4);
  runTimers(5000);
  await settle(4);
  eq(st.byId.get(zr.id).start_date, crsUtcStamp(zdep2), "a new departure writes it");
  eq(crs.t.depart, localInput(zdep2).slice(0, 16), "as the time the captain set");
  fetch = lFetch;
  clearTimeout(crs.saveT); crs.saveT = 0;
  closeOv();
  await settle(2);
  if (!hadRaf) delete globalThis.requestAnimationFrame;
  eq(crsPoiFind("fuel").map(function (c) { return c.id; }).join(), "fuel", "\"fuel\" is the fuel stations");
  eq(crsPoiFind("toilets nearby").map(function (c) { return c.id; }).join(), "toilets", "small words around it do not matter");
  eq(crsPoiFind("omu peak").length, 0, "but a peak's own name is a place to find, not every peak");
  eq(crsPoiFind("water and food").length, 0, "nor is a sentence");
  eq(crsPoiFind("food water").map(function (c) { return c.id; }).sort().join(), "food,water", "two kinds at once");
  var pq = crsPoiQuery([CRS_POI[0]], { box: [45, 25, 45.1, 25.1] });
  ok(/nwr\["amenity"="fuel"\]\(45\.0000,25\.0000,45\.1000,25\.1000\);/.test(pq), "Overpass is asked in the box in view");
  ok(/\(around:400,45\.00000,25\.00000,45\.10000,25\.10000\)/.test(crsPoiQuery([CRS_POI[0]], { r: 400, line: [[45, 25], [45.1, 25.1]] })),
     "or along the route's line");
  ok(CRS_POI.every(function (c) { return c.test({}) === false && c.sel.length && c.stay >= 0; }), "every kind of place has a query, a test and a stay");
  eq(vMatch(vWords("places fuel"), 0).cmd.say, "places {*}", "\"places …\" turns a kind on");
  eq(vMatch(vWords("places along the course"), 0).cmd.say, "places along the course", "and along the course is its own order");
  eq(crsPolyline([[38.5, -120.2], [40.7, -120.95], [43.252, -126.453]]), "_p~iF~ps|U_ulLnnqC_mqNvxq`@",
     "the route picture's path is Google's polyline, as its own example encodes");
  var splitGeo = [[45, 25], [45.01, 25], [45.02, 25], [45.03, 25], [45.04, 25]];
  eq(crsSplit(splitGeo, [null, [45.02, 25], null], [{ lat: 45, lon: 25 }, { lat: 45.02, lon: 25 }, { lat: 45.04, lon: 25 }]).join(),
     "0,2,4", "one route with a waypoint is cut back into its two legs where the waypoint fell");
  var wn = { at: new Date(Date.UTC(2026, 9, 10, 18, 0)), sun: { rise: Date.UTC(2026, 9, 10, 4, 30) / 1000, set: Date.UTC(2026, 9, 10, 15, 40) / 1000 },
             h: { frz: 2000, uv: 7, snow: 0.2 }, ele: 2400 };
  var notes = crsWxNotes(wn).join(" | ");
  ok(/after dark/.test(notes) && /freezing level 2000 m/.test(notes) && /UV 7/.test(notes) && /snow 20 cm/.test(notes),
     "an arrival knows the dark, the freezing level, the UV and the snow (" + notes + ")");
  eq(crsFold("Județul Brașov"), "brasov", "a warning's region and a point's are compared without their accents or the word county");
  var rs = crsRecStats([[45, 25, 0], [45.001, 25, 60], [45.001, 25, 600]]);
  ok(rs.km > 0.1 && rs.km < 0.12 && rs.mins === 10 && rs.moving === 1, "a track's distance, its time and the minutes it moved");
  ok(/<trkpt lat="45" lon="25"><ele>800<\/ele><time>1970-01-01T00:00:00\.000Z<\/time><\/trkpt>/.test(crsRecGpx([[45, 25, 0, 800]], "t")),
     "and its GPX");
  eq(vMatch(vWords("stop recording"), 0).cmd.say, "start recording", "\"stop recording\" is still the memo's");
  eq(vMatch(vWords("stop the track"), 0).cmd.say, "stop the track", "the track stops by its own words");
  var tp = crsParse(crsContent(Object.assign(crsParse('{"points":[]}'), { pic: { id: 3, path: "media/x.jpg" },
    tracks: [{ id: 4, path: "media/t.gpx", start: 0, end: 60, km: 1, moving: 1, mins: 1 }] }), [], "T"));
  ok(tp.pic && tp.pic.path === "media/x.jpg" && tp.tracks.length === 1, "the picture and the tracks are kept with the course");
  // stops on one spot are spread apart; ones that do not touch stay put
  var faces = function (o, its) {
    var bad = 0;
    for (var a = 0; a < its.length; a++) for (var b = a + 1; b < its.length; b++)
      if (Math.abs(its[a].x + o[a][0] - its[b].x - o[b][0]) < its[a].hw + its[b].hw &&
          Math.abs(its[a].y + o[a][1] - its[b].y - o[b][1]) < its[a].hh + its[b].hh) bad++;
    return bad;
  };
  var pin = function (x, y) { return { x: x, y: y, hw: 13, hh: 13 }; };
  var lone = [pin(0, 0), pin(100, 0), pin(0, 100)];
  eq(JSON.stringify(crsSpreadLayout(lone)), "[[0,0],[0,0],[0,0]]", "stops apart stay on their spot");
  var two = [pin(50, 50), pin(50, 50), pin(300, 300)], o2 = crsSpreadLayout(two);
  ok(faces(o2, two) === 0 && o2[2][0] === 0 && o2[2][1] === 0, "a round trip's first and last stop are spread apart, and only they move");
  var heap = [];
  for (var hi = 0; hi < 30; hi++) heap.push(pin(200 + (hi % 3), 200 + (hi % 5)));
  heap.push({ x: 230, y: 180, hw: 27, hh: 11 });
  var oh = crsSpreadLayout(heap);
  eq(faces(oh, heap), 0, "thirty stops and a wider face on one spot: every face shows");
  ok(oh.every(function (d) { return Math.hypot(d[0], d[1]) < 260; }), "and they stay near it");
  ok(crsSpreadLayout(heap.slice(0, 30)).every(function (d) { return Math.hypot(d[0], d[1]) < 130; }),
     "thirty stops alone, nearer still");

  // with vectors held, the statistics chart topics without asking the server
  closeOv();
  var fetchedB4 = TEST.fetches.length;
  openStats();
  for (var w2 = 0; w2 < 400 && $("#st_topics"); w2++) { await pump(2); runTimers(5); }
  ok(!$("#st_topics"), "and the dialog fills its topics section in");
  ok($("#dlg").querySelector(".strow"), "one row a topic");
  closeOv();
  eq(TEST.fetches.length, fetchedB4, "from the vectors already on the device");

  console.log("-- the navigator: a revision is a new entry, the old one soft-deleted --");
  var navTrip = { v: 1, depart: "2026-10-12T08:00", points: [{ name: "Busteni", lat: 45.41, lon: 25.53, stay: 0 },
    { name: "Omu", lat: 45.445, lon: 25.457, stay: 30 }], legs: [{ mode: "foot_hiking" }], notes: "boots",
    pic: { id: 7, path: "pics/course.jpg" } };
  var navR = await api("/entries", { method: "POST", body: { kind: kindOf("trip"), title: "Omu hike",
    content: crsContent(crsParse(JSON.stringify(navTrip)), [], "Omu hike"), start_date: "2026-10-12 05:00:00" } });
  insertRow(await api("/entries/" + navR.id));
  var navOld = navR.id, navSent = [], navAnswer = null, navFetch = fetch;
  fetch = function (url, o) {
    if (String(url).indexOf("/chat") < 0) return navFetch.apply(this, arguments);
    navSent.push(JSON.parse(o.body));
    var body = sse({ type: "system", subtype: "init", session_id: "nav-" + navSent.length }) +
      sse({ type: "stream_event", event: { type: "content_block_start", content_block: { type: "text", text: navAnswer } } }) +
      sse({ type: "result", session_id: "nav-" + navSent.length, duration_ms: 900 }) +
      sse({ type: "lcars_exit", code: 0 });
    return Promise.resolve({ ok: true, status: 200, text: function () { return Promise.resolve(body); } });
  };
  if (!hadRaf) globalThis.requestAnimationFrame = function (f) { return setTimeout(f, 16); };
  var navWas = { id: crs.id, t: crs.t, calc: crs.calc, warn: crs.warn, saved: crs.saved, chat: chat };
  crs.id = navOld; crs.t = crsParse(st.byId.get(navOld).content); crs.calc = []; crs.warn = [];
  crs.saved = st.byId.get(navOld).content;
  // the navigator's thread, as its tab sends: the course on screen's
  var navSay = function (q) { chat = navThread(crs.id); return chatSend(q); };
  var navTh = navThread(navOld);
  navTh.model = chatComputer().model === "haiku" ? "opus" : "haiku";
  navAnswer = "It is about 3 hours up. No change needed.";
  await navSay("how long is the climb?");
  await settle(4);
  eq(navSent.length, 1, "an order goes to the computer");
  eq(navSent[0].session_id, "", "in a conversation of its own");
  has(navSent[0].message, "Busteni", "carrying the plan");
  has(navSent[0].message, "Each order is sent afresh", "and the brief");
  has(navSent[0].message, "Nothing said before", "saying it is the first order");
  has(navSent[0].message, "No recording", "and that there is no recording, plainly");
  has(navSent[0].message, "[Now: ", "with the date and time now");
  has(navSent[0].message, "The captain is at unknown", "and no place when the page has none");
  eq(navSent[0].model, navTh.model, "with the navigator's own model, not the computer's");
  eq(navTh.msgs.length, 2, "the order and its answer are the course's thread");
  ok(chatComputer().msgs.every(function (m) { return String(m.text || "").indexOf("the climb") < 0; }), "and nobody else's");
  eq(crs.id, navOld, "a question changes nothing");
  ok(!st.byId.get(navOld).deleted, "and deletes nothing");
  var navAfter = crsParse(JSON.stringify(navTrip));
  navAfter.points.splice(1, 0, { name: "Babele", lat: 45.405, lon: 25.464, stay: 45 });
  delete navAfter.pic;
  navAnswer = "Added lunch at Babele.\n\n```json trip\n" + JSON.stringify(navAfter) + "\n```";
  var navGeo = geo.last;
  geo.last = { coords: { latitude: 45.4123456, longitude: 25.5212345, accuracy: 12 }, timestamp: Date.now() - 5 * 60000 };
  await navSay("add a lunch stop at Babele");
  await settle(4);
  eq(navSent.length, 2, "the second order is sent");
  eq(navSent[1].session_id, "", "again in a fresh conversation, though the first one had a session");
  var navPast = navSent[1].message.indexOf("What was said before");
  ok(navPast > 0 && navSent[1].message.indexOf("Captain: how long is the climb?") > navPast &&
     navSent[1].message.indexOf("Navigator: It is about 3 hours up") > navPast, "carrying both sides of what was said before");
  ok(navSent[1].message.split("add a lunch stop at Babele").length === 2, "the new order once, not among the earlier ones");
  has(navSent[1].message, "45.41235, 25.52123 ±12 m, the device's fix from 5m ago", "where the device is, and how old the fix is");
  geo.last = navGeo;
  var navNewId = crs.id, navNewRow = st.byId.get(navNewId);
  ok(navNewId !== navOld && navNewRow, "the revision is a new entry (#" + navNewId + ")");
  eq(navNewRow.kind, kindOf("trip"), "of the trip's kind");
  eq(navNewRow.title, "Omu hike", "and its title");
  var navNewT = crsParse(navNewRow.content);
  eq(navNewT.points.map(function (p) { return p.name; }).join(), "Busteni,Babele,Omu", "holding the new plan");
  eq(navNewT.prev, navOld, "naming the plan it replaces");
  eq(navNewT.pic && navNewT.pic.path, "pics/course.jpg", "and keeping the trip's picture, which the navigator never saw");
  eq(st.byId.get(navOld).deleted, 1, "the old plan is soft-deleted");
  eq(crsParse(st.byId.get(navOld).content).points.length, 2, "and still holds itself, unchanged");
  ok(crsTrips().every(function (e) { return e.id !== navOld; }), "it is gone from the courses");
  var navLast = navTh.msgs[navTh.msgs.length - 1];
  var navShown = navLast.parts.map(function (p) { return p.s || ""; }).join("");
  ok(navShown.indexOf("```") < 0 && navShown.indexOf("#" + navOld + ", is kept, deleted") > 0,
     "the answer shows where the plan went, not the JSON");
  ok(chatFind("nav-" + navNewId) === navTh && !chatFind("nav-" + navOld), "the messages follow the course");
  eq(navTh.nav, navNewId, "to its new entry");
  ok(JSON.parse(localStorage.getItem("lcars.chats")).list.some(function (t) { return t.id === "nav-" + navNewId && t.nav === navNewId; }),
     "kept so in lcars.chats");
  navAfter.points[1].stay = 60;
  navAnswer = "Longer lunch.\n\n```json trip\n" + JSON.stringify(navAfter) + "\n```";
  // a kept recording: an hour's walk from 08:00, a 20 minute stop at Babele
  var navT0 = Math.round(Date.parse("2026-10-12T08:00:00") / 1000), navPts = [];
  for (var nk = 0; nk <= 40; nk++) navPts.push([45.41 - nk * 0.0001, 25.53 - nk * 0.0016, navT0 + nk * 60]);
  for (var nk2 = 1; nk2 <= 20; nk2++) navPts.push([45.406, 25.466, navT0 + (40 + nk2) * 60]);
  crs.t.tracks = [{ id: 99, path: "media/test-track.gpx", start: navT0, end: navT0 + 60 * 60, km: 5.1, mins: 60, moving: 40 }];
  crsTrackPts.set("media/test-track.gpx", navPts);
  await navSay("make lunch an hour");
  await settle(4);
  has(navSent[2].message, "Navigator: Added lunch at Babele.", "the earlier answers too");
  ok(navSent[2].message.indexOf("Navigator: Added lunch") < navSent[2].message.indexOf("[The course as the planner"),
     "before the plan");
  ok(navSent[2].message.indexOf('"points":[{"name":"Busteni"') === navSent[2].message.lastIndexOf('"points":[{"name":"Busteni"'),
     "an earlier answer's plan folded to a line, not sent again");
  var navRecAt = navSent[2].message.indexOf("The captain's recording");
  ok(navRecAt > 0, "the recording, when there is one");
  var navRec = JSON.parse(navSent[2].message.slice(navSent[2].message.indexOf("[{", navRecAt), navSent[2].message.indexOf("]\n\n", navRecAt)));
  eq(navRec[0].start, "2026-10-12T08:00", "from its start");
  eq(navRec[0].km, 5.1, "with its numbers");
  eq(navRec[0].stops.length, 1, "one stop found");
  eq(navRec[0].stops[0].from, "2026-10-12T08:40", "where it began");
  ok(navRec[0].stops[0].minutes >= 19, "and how long (" + navRec[0].stops[0].minutes + " min)");
  ok(navRec[0].points.length <= CRS_NAV_PTS && navRec[0].points.length > 10, "the points thinned (" + navRec[0].points.length + ")");
  eq(navRec[0].points[navRec[0].points.length - 1][2], "09:00", "to the end");
  ok(crsNavPast(Array.from({ length: 40 }, function (_, i) { return { role: "user", text: "x".repeat(2000) + i }; })).length < CRS_NAV_PAST + 400,
     "a long thread is capped");
  has(crsNavPast(Array.from({ length: 40 }, function (_, i) { return { role: "user", text: "x".repeat(2000) + i }; })), "earlier messages left out",
      "and says so");
  eq(navSent[2].session_id, "", "a revision of a revision starts afresh too");
  has(navSent[2].message, "Babele", "from the plan before it");
  eq(st.byId.get(navNewId).deleted, 1, "which is soft-deleted in turn");
  eq(crsParse(st.byId.get(crs.id).content).prev, navNewId, "and named by the new one");
  // told not to, the agent writes the entry in place: the same revision, the old content put back
  var navInPlace = crs.id, navBefore = st.byId.get(navInPlace).content;
  navAfter.notes = "boots, poles";
  navAnswer = "Done, I set the notes.";
  var navFetch2 = fetch;
  fetch = function (url, o) {
    if (String(url).indexOf("/chat") >= 0)
      api("/entries/" + navInPlace, { method: "PUT", body: { content: JSON.stringify(navAfter) } });
    return navFetch2.apply(this, arguments);
  };
  await navSay("add poles to the notes");
  await settle(4);
  fetch = navFetch2;
  ok(crs.id !== navInPlace, "a plan written over in place is still a new entry");
  eq(crsParse(st.byId.get(crs.id).content).notes, "boots, poles", "holding what was written");
  eq(st.byId.get(navInPlace).content, navBefore, "the old plan is put back as it was");
  eq(st.byId.get(navInPlace).deleted, 1, "and soft-deleted");
  var navLastId = crs.id;
  await crsUnrevise(navLastId, navInPlace);
  await settle(2);
  ok(!st.byId.get(navInPlace).deleted && st.byId.get(navLastId).deleted, "Undo brings the old plan back and deletes the new one");
  eq(crs.id, navInPlace, "and the view goes with it");
  crsTrackPts.delete("media/test-track.gpx");
  crs.id = navWas.id; crs.t = navWas.t; crs.calc = navWas.calc; crs.warn = navWas.warn; crs.saved = navWas.saved;
  chat = navWas.chat;
  // lcars.nav (0.159 and before) is taken into the threads once
  var lsChats2 = localStorage.getItem("lcars.chats"), lsNav = localStorage.getItem("lcars.nav");
  lsSet("lcars.chats", { seq: 1, model: "sonnet", list: [] });
  lsSet("lcars.nav", { "4242": { msgs: [{ role: "user", text: "old order" }] } });
  var navMig = chatsLoad();
  ok(navMig.list.some(function (t) { return t.id === "nav-4242" && t.nav === 4242 && t.msgs[0].text === "old order"; }),
     "a course's navigator messages from before become its thread");
  ok(navMig.navIn, "once");
  localStorage.setItem("lcars.chats", lsChats2);
  if (lsNav) localStorage.setItem("lcars.nav", lsNav); else localStorage.removeItem("lcars.nav");
  clearTimeout(crs.saveT); crs.saveT = 0;
  runTimers(5000);
  await settle(2);
  fetch = navFetch;
  if (!hadRaf) delete globalThis.requestAnimationFrame;

  /* ---------- search by meaning ----------
     The list asks the chart's question: the query embedded by the server
     (EMBQ, topic 4's vector), every entry ranked by closeness to it. */
  console.log("-- search by meaning --");
  closeOv();
  closeEditor();
  applyQS("");
  refresh();
  var modeBtn = function (v) { return $("#mode").querySelector('[data-v="' + v + '"]'); };
  ok(modeBtn("meaning"), "the search has a Meaning switch beside Text and Regex");
  click(modeBtn("meaning"));
  eq(segVal("#mode"), "meaning", "which lights when pressed");
  EMBQ = function () { return b64s(starVec(4)); };
  var embN = TEST.fetches.filter(function (f) { return f === "POST /embed"; }).length;
  input($("#q"), "the thing topic four is about");
  runTimers(100);                       // the box's own debounce, not yet the meaning's
  ok(st.meanPending && st.view.length === 0, "while the meaning is read, the list waits rather than guessing");
  has($("#list").innerHTML, "reading the meaning", "and says what it is doing");
  eq(searchTitle(), "", "a meaning search offers no “new entry called”");
  await settle(4);
  eq(TEST.fetches.filter(function (f) { return f === "POST /embed"; }).length, embN + 1,
     "the settled query is embedded once, by the server");
  ok(!st.meanPending && st.meanHits && st.meanHits.size >= MEAN_KEEP, "the answer lands (" +
     (st.meanHits && st.meanHits.size) + " rows)");
  var top5 = st.view.slice(0, 5).filter(function (e) { return topic[e.id] === 4; });
  eq(top5.length, 5, "and its first five rows are topic four's five");
  ok(st.view.every(function (e) { return sv.vec.has(e.id); }), "every row is one the server embedded");
  var closes = st.view.map(function (e) { return st.meanHits.get(e.id); });
  ok(closes.every(function (c, i) { return !i || closes[i - 1] >= c; }), "closest first, whatever the sort says");
  ok(!st.dayOf, "with no day bars cutting a ranking into days");
  has($("#count").innerHTML, "closest in meaning first", "the header says how the list is ordered");
  has($("#qnote").textContent, "not embedded yet", "and the note counts the entries it could not search");
  has(stateQS(false), "mean=1", "the url carries the mode");
  var meanQS = stateQS(false);
  applyQS("");
  eq(segVal("#mode"), "text", "a bare url is Text again");
  applyQS(meanQS);
  eq(segVal("#mode"), "meaning", "and the url brings Meaning back");
  refresh();
  ok(st.meanHits && st.view.length === st.meanHits.size, "answered from what it already knows");
  eq(TEST.fetches.filter(function (f) { return f === "POST /embed"; }).length, embN + 1,
     "without asking the server again");
  // the calendar and the statistics scope read the same filter
  var calRows = st.all.filter(makeRowFilter(true));
  eq(calRows.length, st.view.length, "the calendar sees the same rows");

  // "~" from Text mode
  setSeg("#mode", "text");
  input($("#q"), "~ the thing topic four is about");
  await settle(3);
  ok(st.meanHits && st.view.slice(0, 5).every(function (e) { return topic[e.id] === 4; }),
     "a leading ~ searches by meaning from Text mode too");
  eq(TEST.fetches.filter(function (f) { return f === "POST /embed"; }).length, embN + 1,
     "a query asked before is not embedded again");
  input($("#q"), "~ab");
  await settle(2);
  ok(!st.meanHits && st.view.length === st.all.filter(makeRowFilter(false)).length,
     "two letters are not worth a round trip, and narrow nothing");

  // no embedding service: the words answer, and the box says so
  EMBQ = null;
  var wordQ = (sLive[3].title || "").split(/\s+/).filter(function (w) { return w.length > 3; })[0] || "the";
  input($("#q"), "~" + wordQ);
  await settle(3);
  has($("#qerr").textContent, "matching the words instead", "with /embed off, it says it fell back");
  ok(!st.meanHits && st.matcher && st.view.length > 0, "and the words still find rows");
  ok(st.view.every(function (e) { return hay(e, "all").toLowerCase().indexOf(wordQ.toLowerCase()) >= 0; }),
     "only rows that carry the word");

  // a device that never charted fetches the vectors the first time it is asked
  EMBQ = function () { return b64s(starVec(4)); };
  sv.vec.clear(); sv.raw.clear(); sv.mark = ""; sv.at = 0; sv.loaded = false;
  sMap.delete("vec");
  var embsN = TEST.fetches.filter(function (f) { return f === "GET /embeddings"; }).length;
  setSeg("#mode", "meaning");
  input($("#q"), "something else about topic four");
  await settle(4);
  eq(TEST.fetches.filter(function (f) { return f === "GET /embeddings"; }).length, embsN + 1,
     "a device holding no vectors fetches them, once");
  ok(st.meanHits && st.view.slice(0, 5).every(function (e) { return topic[e.id] === 4; }),
     "and answers the question with them");
  setSeg("#mode", "text");
  input($("#q"), "");
  await settle(1);
  ok(!st.meanHits && !st.meanPending, "an emptied box is an ordinary list again");

  /* ---------- suggestions while writing ----------
     Topic four's five entries become one kind with day-dash titles; a draft
     embedded into topic four should be offered that kind, and a title in
     that shape made of its own opening line. */
  console.log("-- suggestions while writing --");
  closeOv();
  closeEditor();
  var t4 = sLive.filter(function (e) { return topic[e.id] === 4; });
  var t4was = t4.map(function (e) { return [e.kind, e.title]; });
  t4.forEach(function (e, i) { e.kind = "sug_test_kind"; e.title = "2026-09-0" + (i + 1) + " - topic four, part " + i; });
  sg.off = false; sg.synced = false;
  EMBQ = function () { return b64s(starVec(4)); };
  newEntry();
  setRead(false);
  ok($("#esug").hidden, "a blank new entry is offered nothing");
  $("#e_kind").value = "personal_log";
  embN = TEST.fetches.filter(function (f) { return f === "POST /embed"; }).length;
  input($("#content"), "short");
  await settle(3);
  ok($("#esug").hidden, "nor is a draft too short to resemble anything");
  input($("#content"), "We walked along the river after lunch and talked about the move. Then home again.");
  runTimers(200);
  ok($("#esug").hidden, "nothing while the typing has not paused");
  await settle(4);
  ok(!$("#esug").hidden, "a paused draft is offered suggestions");
  var sk = $("#esug").querySelector("[data-sk]");
  ok(sk && sk.dataset.sk === "sug_test_kind", "the kind its nearest entries share (" + (sk && sk.dataset.sk) + ")");
  var dayNow = dayKey($("#e_created_at_utc").value);
  var stt = $("#esug").querySelector(".sgt");
  has(stt && stt.textContent, dayNow + " - We walked along the river after lunch and talked about the move",
      "and a title in their day-dash shape, from the draft's first sentence");
  eq(TEST.fetches.filter(function (f) { return f === "POST /embed"; }).length, embN + 1, "the draft was embedded once");
  input($("#content"), $("#content").value + " Tea.");
  await settle(3);
  eq(TEST.fetches.filter(function (f) { return f === "POST /embed"; }).length, embN + 1,
     "a few more words do not embed it again");
  eq($("#e_kind").value, "personal_log", "nothing is filled in unasked");
  click(sk);
  eq($("#e_kind").value, "sug_test_kind", "a tap on the kind takes it");
  ok(document.body.classList.contains("dirty"), "as an edit");
  ok(!$("#esug").querySelector("[data-sk]"), "and it is no longer offered");
  click($("#esug").querySelector(".sgt"));
  has($("#e_head").value, " - We walked along the river", "a tap on the title fills the field");
  ok($("#esug").hidden, "and with both taken, the row goes");
  await settle(3);
  ok($("#esug").hidden, "a titled entry of the suggested kind is offered nothing more");
  // the ✕
  $("#e_head").value = "";
  input($("#e_head"), "");
  await settle(3);
  ok(!$("#esug").hidden, "emptying the title brings the title offer back");
  click($("#esug").querySelector(".sgx"));
  ok($("#esug").hidden, "✕ dismisses it");
  input($("#content"), $("#content").value + " More words to make it move along quite a bit further than sixty bytes.");
  await settle(3);
  ok($("#esug").hidden, "for the rest of this entry");
  // a saved entry: a title for the placeholder, never a kind
  TEST.confirmAnswer = true;
  closeEditor();
  var placeholder = sLive.filter(function (e) { return topic[e.id] !== 4 && !needsBody(e); })[0];
  var phWas = placeholder.title;
  placeholder.title = "HTTP Entry";
  select(placeholder.id);
  setRead(false);
  input($("#content"), "Dictated on the phone while walking to the station this morning. Long enough now.");
  await settle(4);
  ok(!$("#esug").querySelector("[data-sk]"), "a saved entry is not offered a kind");
  ok($("#esug").querySelector(".sgt"), "but a placeholder title is offered a real one");
  has($("#esug").querySelector(".sgt").textContent, "Dictated on the phone while walking to the station this morning",
      "its first sentence");
  closeEditor();
  placeholder.title = phWas;
  // no embeddings at all: the title is still offered, from the draft alone
  var embWas = EMB;
  EMB = null; EMBQ = null; sg.off = false;
  sv.vec.clear(); sv.raw.clear(); sv.mark = ""; sv.at = 0; sv.loaded = false; sMap.delete("vec");
  sg.synced = false;
  newEntry();
  setRead(false);
  input($("#content"), "## Groceries\n- milk, bread and the good coffee for the weekend");
  await settle(4);
  ok(!$("#esug").querySelector("[data-sk]"), "with no embeddings, no kind is guessed");
  has($("#esug").querySelector(".sgt") && $("#esug").querySelector(".sgt").textContent, "Groceries",
      "but the opening line is still offered as the title");
  ok(sg.off, "and the server is not asked again this session");
  $("#content").value = ""; setClean();   // a draft with words would be saved on the way out (P8)
  closeEditor();
  eq(sugOpening("type:: log\n- [[Andrei]] went to the [park](https://x.y/z) with us, and then we went home and slept for a while longer than planned"),
     "Andrei went to the park with us, and then we went home and…", "a long line is cut at a word, links flattened, properties skipped");
  t4.forEach(function (e, i) { e.kind = t4was[i][0]; e.title = t4was[i][1]; });
  EMB = embWas;

  starStore = keptStore;
  EMB = null; EMBQ = null; EMB_CODE = 404;
  sv.vec.clear(); sv.raw.clear(); sv.mark = ""; sv.at = 0; sv.moved.clear();
  sc.lay = null;

  console.log("\n-- a view pad in the deck opens its view here --");
  closeOv();
  ok(window.lcarsDeckView("tasks") === true, "the task board opens at once, the rows being here");
  eq($("#dlgh").textContent, "Tasks", "and it is the task board");
  ok(window.lcarsDeckView("month") === true && /\d{4}/.test($("#dlgh").textContent), "the month");
  ok(window.lcarsDeckView("readings") === true, "the readings");
  has($("#dlgh").textContent, "explore", "in the explorer");
  ok(window.lcarsDeckView("today") === true && $("#ov").classList.contains("on"), "today");
  ok(window.lcarsDeckView("stats") === true && $("#ov").classList.contains("on"), "the statistics");
  closeOv();
  ok(window.lcarsDeckView("nosuch") === true && !$("#ov").classList.contains("on"), "a key it does not know opens nothing, and is not asked again");

  console.log("\n-- the deck's desk dictates through this page --");
  closeOv();
  markDirty();
  eq(window.lcarsDeckDictate(), "dirty", "an unsaved edit is not thrown away by a frame nobody can see");
  setClean();
  var dr = window.lcarsDeckDictate();
  ok(dr === true || dr === "novoice", "otherwise a new entry opens and the microphone is asked for (" + dr + ")");
  var ds = window.lcarsDeckDictation();
  ok(ds.isNew && ds.text === "", "the deck reads back a new, empty entry");
  $("#content").value = "Captain's log, from the desk."; markDirty();
  eq(window.lcarsDeckDictation().text, "Captain's log, from the desk.", "and the words as they arrive");
  $("#content").value = ""; setClean();
  ok(window.lcarsDeckDictateEnd() === true && !window.lcarsDeckDictation().on, "the end stops listening; nothing said, nothing saved");
  ok(!document.body.classList.contains("dirty"), "and leaves nothing owed");

  console.log("\n-- merge3: the outbox's three-way merge --");
  var m3 = merge3("a\nb\nc", "a\nB\nc", "a\nb\nc\nd");
  eq(m3.text, "a\nB\nc\nd", "each side's own change is kept");
  eq(m3.conflicts, 0, "with nothing to settle");
  m3 = merge3("a\nb\nc", "a\nmine\nc", "a\ntheirs\nc");
  eq(m3.conflicts, 1, "the same line changed two ways is a conflict");
  has(m3.text, "<<<<<<< this device\nmine\n=======\ntheirs\n>>>>>>> server", "written out between markers");
  m3 = merge3("x", "x\nmine added", "x\ntheirs added");
  eq(m3.text, "x\ntheirs added\nmine added", "text both added at the end is kept from both");
  eq(m3.conflicts + ":" + m3.both, "0:1", "and said to be both");
  eq(merge3("same", "same", "same").text, "same", "nothing changed, nothing changes");

  console.log("\n-- offline: writes are kept on this device and sent when the link is back --");
  closeOv(); setClean();
  var obFetch = fetch, obDown = true, obAsked = 0;
  fetch = function (u, init) {
    if (obDown) {
      if (/\/entries\/\d+$/.test(String(u))) obAsked++;
      return Promise.reject(new Error("Failed to fetch"));
    }
    return obFetch(u, init);
  };
  var obT = st.all.filter(function (e) { return !e.deleted && e.content && !needsBody(e) && !isLocalId(e.id); });
  var obEditRow = obT[0], obDelRow = obT[1];
  var obOrig = obEditRow.content;
  select(obEditRow.id);
  $("#content").value = obOrig + "\nwritten offline";
  markDirty();
  await save();
  await settle(3);
  ok(ob.offline, "a write that gets no answer takes the page offline");
  ok(ob.ops.has(obEditRow.id), "the edit waits in the outbox");
  ok(!document.body.classList.contains("dirty"), "and the editor is clean: it is saved, on this device");
  has(obEditRow.content, "written offline", "the row on screen has it");
  eq(dbFind(obEditRow.id).content, obOrig, "the server does not, yet");
  ok(!$("#hq").hidden, "the header says so");
  has($("#hq").textContent, "offline", "in a word");
  var askedBefore = obAsked;
  $("#content").value = obOrig + "\nwritten offline, twice";
  markDirty();
  await save();
  await settle(3);
  eq(obAsked, askedBefore, "once offline, a save does not wait on the network again");
  eq(ob.ops.size, 1, "two saves of one entry are one op");

  newEntry();
  $("#e_kind").value = "personal_log";
  $("#e_head").value = "made offline";
  $("#content").value = "no link at all";
  markDirty();
  await save();
  await settle(3);
  var obNew = st.sel;
  ok(obNew && isLocalId(obNew.id), "a new entry gets a local id");
  ok(st.byId.get(obNew.id) === obNew && st.all[0] === obNew, "and is in the list, on top");
  has($("#edtitle").textContent, "#new", "titled as new, not by its local number");
  ok(!DB.some(function (r) { return r.title === "made offline"; }), "and is not on the server");

  await api("/entries/" + obDelRow.id, { method: "DELETE" });
  eq(ob.ops.get(obDelRow.id).row.deleted, 1, "a delete waits too");
  eq(dbFind(obDelRow.id).deleted, 0, "with the server's row untouched");

  var kept = lsGet("lcars.outbox", null);
  ok(kept && kept.ops.length === 3, "the outbox is kept on the device (" + (kept && kept.ops.length) + ")");
  var opsWere = new Map(ob.ops);
  ob.ops.clear();
  await obLoad();
  eq(ob.ops.size, 3, "and comes back after a reload");
  ob.ops = opsWere;

  // meanwhile, on the server, someone adds a first line to the edited entry
  var srvRow = dbFind(obEditRow.id);
  srvRow.content = "server's first line\n" + obOrig;
  srvRow.last_modified_at_utc = "2099-02-02 00:00:00";
  obDown = false;
  await obTry();
  await settle(6);
  var obMade = DB.filter(function (r) { return r.title === "made offline"; });
  eq(obMade.length, 1, "the new entry is created on the server, once");
  ok(obMade.length && obNew.id === obMade[0].id, "and the row on screen took the server's id");
  ok(obMade.length && ob.remap.get(LOCAL_ID) === obMade[0].id || !isLocalId(obNew.id), "the local id maps to it");
  eq(dbFind(obDelRow.id).deleted, 1, "the delete reaches the server");
  ok($("#ov").classList.contains("on"), "the entry both sides edited is asked about");
  has($("#dlgh").textContent, "two places", "in its own dialog");
  var obMerged = $("#obt0") ? $("#obt0").value : "";
  has(obMerged, "server's first line", "the suggestion keeps the server's line");
  has(obMerged, "written offline, twice", "and this device's");
  ok(obMerged.indexOf("<<<<<<<") < 0, "with no markers: they changed different lines");
  click($("#obKeep"));
  await settle(6);
  eq(dbFind(obEditRow.id).content, obMerged, "keeping it sends the merge");
  eq(ob.ops.size, 0, "the outbox is empty");
  ok($("#hq").hidden, "and the header has nothing more to say");
  fetch = obFetch;

  console.log("\n-- a refused password does not interrupt a device holding the journal --");
  closeOv();
  var pwFetch = fetch, pwMarked = true;
  fetch = function (u, init) {
    if (!(init && init.headers && init.headers["X-LCARS-Client"])) pwMarked = false;
    return Promise.resolve({ ok: false, status: 401, statusText: "Unauthorized",
      text: function () { return Promise.resolve('{"error":"Unauthorized","status":401}'); } });
  };
  var markWas = mirror.mark, userWas = cfg.user;
  if (!mirror.mark) mirror.mark = "2000-01-01 00:00:00";
  cfg.user = "someone";
  await bootSync();
  await settle(3);
  ok(!$("#ov").classList.contains("on"), "no password dialog over the journal");
  ok($("#hSignIn"), "a Sign in capsule instead");
  ok(pwMarked, "every request says it is the page's, so the server sends no browser challenge");

  console.log("\n-- a page that never stored a password is asked, once, by its own dialog --");
  cfg.user = "";
  await bootSync();
  await settle(3);
  ok($("#ov").classList.contains("on"), "the Connection dialog, which keeps what is typed");
  closeOv();
  cfg.user = userWas;
  fetch = pwFetch;
  mirror.mark = markWas;

  console.log("\n-- a new engineer from the console --");
  var slug = engNewSlug("Ilse Moreau", []);
  ok(/^moreau-[a-z0-9]{3}$/.test(slug), "the slug is the last name and a random tail: " + slug);
  ok(/^[a-z][a-z0-9-]{0,23}$/.test(engNewSlug("  Dr. 7of9 Annika Hansen-Smith!!  ", [])), "a messy name still makes a slug engineer.py takes");
  ok(/^eng-/.test(engNewSlug("42", [])), "a name with no letter to lead gets eng-");
  var held = engNewSlug("Moreau", []);
  ok(engNewSlug("Moreau", [held]) !== held, "a name already held is never reused (it would resume them)");
  [["new engineer Ilse Moreau", "new engineer {*}"], ["engineer moreau", "engineer {*}"],
   ["dismiss engineer moreau", "dismiss engineer {*}"], ["bring back engineer moreau", "bring back engineer {*}"],
   ["talk to reyes", "talk to {*}"], ["talk to number one", "number one"], ["talk to the navigator", "show the navigator"],
   ["show the crew", "show the crew"], ["show the crew reports", "crew reports"], ["show the crew entries", "show crew entries"],
   ["answer two", "answer {*}"], ["answer with opus", "switch model to {*}"], ["deploy reyes", "deploy {*}"],
   ["deploy this", "deploy this"], ["roll back the deploy", "roll back the deploy"]].forEach(function (x) {
    var hit = vMatch(vWords(x[0]), 0);
    eq(hit && hit.cmd.say, x[1], "\"" + x[0] + "\" is " + x[1]);
  });

  console.log("-- the crew in the chats: who they are, the seat, a thread with any of them --");
  eq(engRole({ title: "Lieutenant Harry Kim", who: "Lieutenant Harry Kim, an engineer of the U.S.S. Enterprise" }),
     "an engineer of the U.S.S. Enterprise", "the role line drops the name it opens with");
  eq(engRole({ title: "Chief Miles O'Brien", who: "ops engineer: scripts/engineer.py" }), "ops engineer: scripts/engineer.py",
     "and is whole when it does not");
  var nowS = Math.round(Date.now() / 1000);
  var crewEngs = [{ name: "reyes-c20", title: "Chief Ana Reyes", status: "idle", who: "Chief Ana Reyes, an engineer", active: nowS - 120, ctx: 167000 },
                  { name: "obrien-c33", title: "Chief Miles O'Brien", status: "queued", who: "ops engineer", active: nowS - 600 },
                  { name: "kim-c32", title: "Lieutenant Harry Kim", status: "blocked", active: nowS - 60, ctx: 250000 },
                  { name: "number-one", title: "Number One", status: "idle", active: nowS - 9000 },
                  { name: "gone-e3f", title: "Gone Fishing", status: "off", active: nowS - 30, dismissed: nowS - 20 }];
  // The live journal's own orders waiting for these names (a real
  // crew_inbox row "obrien-c33 ← No.1 …" while the suite runs) would count
  // in their rows, and the checks below would hang on what the journal
  // holds that day: the in-memory copy of them dropped, the fixtures' own
  // (ibMk) the only ones
  st.all.filter(function (r) {
    return engInboxRow(r) && crewEngs.some(function (x) { return (r.title || "").indexOf(x.name + " ← ") === 0; });
  }).forEach(unplant);
  engInboxN = null;
  ok(crewEngs.every(function (x) { return !engInboxCount(x.name); }), "no live order waits for a fixture's name");
  eq(engFind(crewEngs, "Reyes").name, "reyes-c20", "a crew member by a word of their name");
  eq(engFind(crewEngs, "chief reyes").name, "reyes-c20", "by rank and name");
  eq(engFind(crewEngs, "obrien").name, "obrien-c33", "O'Brien said without the apostrophe");
  eq(engFind(crewEngs, "the number one").name, "number-one", "Number One by both words");
  eq(engFind(crewEngs, "fishing").name, "gone-e3f", "a dismissed engineer is still found by name");
  lsSet("lcars.deck.engkey", "k");
  eng.list = crewEngs; eng.deploy = {}; eng.at = Date.now(); eng.offOpen = false;
  eng.seat = { holder: "kim-c32", queue: ["obrien-c33", "crew:yeoman"], waiting: ["reyes-c20"] };
  chatsList(); await settle(2);
  var engRowsShown = Array.prototype.map.call($("#chrows").querySelectorAll(".chrow[data-eng]"), function (b) { return b.dataset.eng; });
  eq(engRowsShown.join(","), "number-one,kim-c32,reyes-c20,obrien-c33,gone-e3f",
     "Number One first, then the newest activity, the dismissed after, under their own heading");
  has($("#chrows").innerHTML, "Dismissed (1)", "the dismissed are counted under Dismissed");
  has($("#chrows").querySelector('[data-eng="kim-c32"]').innerHTML, "ANSWER", "one waiting on an answer says so on their row");
  has($("#chrows").querySelector('[data-eng="obrien-c33"]').innerHTML, "#1 SEAT", "one queued says where in line");
  has($("#chrows").querySelector('[data-eng="reyes-c20"]').innerHTML, "an engineer", "and each row has who they are");
  // an engineer's unread: said something since their thread was last seen
  localStorage.removeItem(ENG_SEEN_KEY);
  var engSw = $("#chrows").querySelector('.chrow[data-eng="reyes-c20"]');
  ok(!engSw.querySelector(".chbadge") && engSw.parentNode.dataset.rd === "unread", "an engineer first met is not unread");
  swDrag(engSw, 60);
  engSw = $("#chrows").querySelector('.chrow[data-eng="reyes-c20"]');
  ok(engUnread(crewEngs[0]) && /&bull;/.test(engSw.innerHTML), "a swipe right marks them unread, a dot on their row at once");
  eq(engSw.parentNode.dataset.rd, "read", "and the next swipe right is Mark read");
  swDrag(engSw, 60);
  ok(!engUnread(crewEngs[0]), "which reads them");
  var engSeenM = engSeenMap(); engSeenM["reyes-c20"] = crewEngs[0].active - 60; lsSet(ENG_SEEN_KEY, engSeenM);
  chatListPaint();
  ok(engUnread(crewEngs[0]) && /&bull;/.test($("#chrows").querySelector('.chrow[data-eng="reyes-c20"]').innerHTML),
     "one who has said something since their thread was seen is unread");
  ok(chatUnreadTotal() >= 1, "counted with the chats");
  // the seat is said once, on the Queue row (the old line under the header is gone)
  ok(!$("#chseat"), "no seat line under the list's header");
  var seatRow = $("#chrows").querySelector(".chrow[data-queue]");
  ok(seatRow, "the seat is shown when the server has one, on the Queue row");
  has(seatRow.innerHTML, "working: Lieutenant Harry Kim", "who holds it, by name");
  var seatErr = eng.seat; eng.seat = { error: "seat.json unreadable" }; chatListPaint();
  has($("#chrows").querySelector(".chrow[data-queue]").innerHTML, "seat unknown: seat.json unreadable", "a seat that could not be read says so, not that it is free");
  eng.seat = seatErr; chatListPaint();
  ok(!$("#chfoot").hidden, "with the key, a box to add an engineer");
  has($("#bChat").textContent, "Chats", "the Chats button");
  ok(!$("#bEng") && !$("#bCrew") && !$("#hNo1"), "is the only one: Crew, Reports and No.1 asks are gone from the header");

  // the server's answers, recorded
  var engPosts = [], engFetch = fetch, engPoll1 = null, engServed = null, engSay1 = { ok: true }, engModel1 = null;
  var engJson = function (o) { var t = JSON.stringify(o); return Promise.resolve({ ok: true, status: 200,
    json: function () { return Promise.resolve(JSON.parse(t)); }, text: function () { return Promise.resolve(t); },
    headers: { get: function () { return "application/json"; } } }); };
  fetch = function (url, o) {
    var u = String(url);
    if (u.indexOf("/engineer") < 0) return engFetch.apply(this, arguments);
    engPosts.push(((o && o.method) || "GET") + " " + u.replace(/^.*\/engineer/, "/engineer") + (o && o.body ? " " + o.body : ""));
    if (/\/say$/.test(u)) return typeof engSay1 === "function" ? engSay1() : engJson(engSay1);
    if (/\/model$/.test(u)) return engModel1();
    if (/\?off=/.test(u)) {
      // as the server does: events once, then only what is new (none, here)
      var po = engPoll1 || { session: "s1", events: [], next: 0, first: 0, status: "idle" };
      if (po === engServed && !/off=-1/.test(u)) po = Object.assign({}, po, { events: [] });
      engServed = engPoll1;
      return engJson(po);
    }
    return engJson({ ok: true });
  };
  click($("#chrows").querySelector(".chrow[data-dismiss]") || $("#chrows").querySelector('[data-dismiss="reyes-c20"]'));
  await settle(3);
  ok(engPosts.some(function (u) { return /^POST \/engineer\/[a-z0-9-]+\/dismiss/.test(u); }), "Dismiss posts /engineer/<name>/dismiss");
  ok(crewEngs.filter(function (x) { return x.dismissed; }).length === 2, "the row is dismissed on the page at once");
  has($("#chrows").innerHTML, "Dismissed (2)", "and folds away with the other");
  await engDismiss("gone fishing", true);
  ok(engPosts.some(function (u) { return /^POST \/engineer\/gone-e3f\/recall/.test(u); }), "Bring back posts /engineer/<name>/recall, by a name said aloud too");
  ok(!crewEngs[4].dismissed, "and they are back on the list");
  var disHit = vMatch(vWords("dismiss gone fishing"), 0);
  await disHit.cmd.fn(disHit.arg);
  ok(crewEngs[4].dismissed && $("#ov").classList.contains("on"), "\"dismiss <name>\" dismisses them, the chats left up");
  // QA bug B: any other "dismiss the …" is the dialog's, never a name
  var coWas = closeOv, coN = 0, posts0 = engPosts.length;
  closeOv = function () { coN++; };
  ["dismiss the chats", "dismiss the panel", "dismiss it"].forEach(function (x) { var h = vMatch(vWords(x), 0); h.cmd.fn(h.arg); });
  closeOv = coWas;
  eq(coN, 3, "\"dismiss the chats\", \"the panel\", \"it\" close the dialog");
  eq(engPosts.length, posts0, "and dismiss nobody");
  crewEngs.forEach(function (x) { if (x.name !== "gone-e3f") delete x.dismissed; });

  // the queue: one row at the top of the Crew section, a view of its own
  var qRow = $("#chrows").querySelector(".chrow[data-queue]");
  ok(qRow && $("#chrows").innerHTML.indexOf("data-queue") < $("#chrows").innerHTML.indexOf("data-eng="),
     "the Crew section opens with one row for the queue, above the crew");
  has(qRow.innerHTML, "working: Lieutenant Harry Kim · 2 queued", "which says who has the seat and how many wait");
  var engQueue1 = {
    seat: { holder: { name: "kim-c32", title: "Lieutenant Harry Kim", task: "a clock in the header", since: nowS - 600, by: "no1", waiting: false,
                      time: { start: nowS - 900, end: nowS, dur: 900, turns: 1, live: true, kinds: [{ k: "think", s: 300 }, { k: "read", s: 600 }] } },
            queue: [{ name: "obrien-c33", title: "Chief Miles O'Brien", task: "the old task", order: "a Queue view in the web app", from: "No.1", since: nowS - 300, by: "no1" },
                    { name: "okafor-c30", title: "Lieutenant Daniel Okafor", task: "header framing", order: "[deploy finished] deployed okafor-c30", from: "ship", note: true, since: nowS - 250 },
                    { name: "crew:yeoman", title: "", task: "", since: nowS - 200, by: "crew" }],
            waiting: [{ name: "reyes-c20", title: "Chief Ana Reyes", task: "the boiler", since: nowS - 900 }] },
    deploys: [
      { ts: nowS - 100, name: "kim-c32", title: "Lieutenant Harry Kim", verb: "deploy", outcome: "done", live: true, from: "aaaa1111", to: "bbbb2222",
        versions: [{ v: "0.179.0", tag: "web", head: "a live clock in the header" }],
        time: { start: nowS - 100 - 8040, end: nowS - 100, dur: 8040, turns: 3, order: "a clock in the header, please",
                kinds: [{ k: "think", s: 1206 }, { k: "write", s: 2010 }, { k: "test", s: 4020 }, { k: "deploy", s: 804 }] } },
      { ts: nowS - 2000, name: "yar-c36", title: "Lieutenant Tasha Yar", verb: "deploy", outcome: "failed",
        msg: "eng/yar-c36 does not rebase cleanly onto deb (conflicts: TODO.md)", versions: [] },
      { ts: nowS - 3000, name: "okafor-c30", title: "Lieutenant Daniel Okafor", verb: "deploy", outcome: "rolled_back", rolled_back: nowS - 2500,
        from: "cccc", to: "dddd", c: true, versions: [{ v: "0.177.4", head: "four" }, { v: "0.177.3", head: "three" }, { v: "0.177.2", head: "two" }, { v: "0.177.1", head: "one" }] },
      { ts: nowS - 4000, name: "yar-c36", title: "Lieutenant Tasha Yar", verb: "deploy", outcome: "done", from: "eeee", to: "ffff", versions: [],
        subject: "TODO: a bug from the QA re-test" }],
    live: { version: "0.179.0", commit: "bbbb2222" },
    deploy: { state: "running", verb: "deploy", name: "laforge-c34", title: "Lt. Cmdr. Geordi La Forge", msg: "running the web suite (PERF=0)" } };
  var qFetch = fetch, qGets = 0, qKey = "";
  fetch = function (url, o) {
    if (/\/engineer\/queue$/.test(String(url))) { qGets++; qKey = o && o.headers && o.headers["X-LCARS-Engineer-Key"]; return engJson(engQueue1); }
    return qFetch.apply(this, arguments);
  };
  click(qRow);
  ok(qRow.classList.contains("pressing"), "a tap on it shows at once, before the server answers");
  await settle(2);
  ok($("#dlg").classList.contains("qview"), "and opens the queue");
  eq(curRel().split("?")[0], "queue", "at ./queue");
  ok(qGets > 0 && qKey === "k", "read from GET /engineer/queue, with the key");
  var qHtml = $("#qtl").innerHTML;
  ok(qHtml.indexOf(">Working<") >= 0 && qHtml.indexOf(">Working<") < qHtml.indexOf(">Queued<") &&
     qHtml.indexOf(">Queued<") < qHtml.indexOf(">Shipped<"), "three bands in one timeline: working, queued, shipped");
  var qWork = $("#qtl").querySelector(".qb-work").innerHTML;
  has(qWork, "Lieutenant Harry Kim", "working: who has the seat");
  has(qWork, "a clock in the header", "on what");
  has(qWork, "since ", "and since when");
  var qWait = $("#qtl").querySelectorAll(".qb-wait .qitem");
  eq(qWait.length, 4, "queued: the line, and who waits on an answer");
  has(qWait[0].innerHTML, "#1", "in order");
  has(qWait[0].innerHTML, "a Queue view in the web app", "each with the order waiting in their inbox");
  ok(qWait[0].innerHTML.indexOf("the old task") < 0, "not their old task when an order waits");
  has(qWait[0].innerHTML, "from No.1", "and who it is from");
  has(qWait[1].innerHTML, "header framing", "the ship's note on a deploy is no order: their task is shown");
  has(qWait[2].innerHTML, "Yeoman (scheduled)", "a scheduled role in line by its name");
  ok(qWait[3].innerHTML.indexOf("Chief Ana Reyes") >= 0 && qWait[3].innerHTML.indexOf("ANSWER") >= 0, "who waits on an answer says so");
  var qShip = $("#qtl").querySelectorAll(".qb-ship .qitem");
  eq(qShip.length, 5, "shipped: the deploy under way, and each deploy");
  has(qShip[0].innerHTML, "running the web suite", "the one under way first, with its step");
  has(qShip[0].innerHTML, "Geordi La Forge", "and who is shipping it, by name");
  ok(qShip[1].classList.contains("live") && qShip[1].innerHTML.indexOf("LIVE") >= 0, "then the newest, marked live");
  has(qShip[1].innerHTML, "0.179.0", "with the version it carried");
  has(qShip[1].innerHTML, "a live clock in the header", "and its CHANGELOG headline");
  ok(qShip[2].classList.contains("bad") && qShip[2].innerHTML.indexOf("FAILED") >= 0 && qShip[2].innerHTML.indexOf("does not rebase") >= 0,
     "a failed deploy says so, and why");
  ok(qShip[3].innerHTML.indexOf("ROLLED BACK") >= 0 && qShip[3].innerHTML.indexOf("server rebuilt") >= 0, "a rolled-back one says so");
  has(qShip[3].innerHTML, "1 more", "past three versions, the rest folded");
  has(qShip[4].innerHTML, "a bug from the QA re-test", "a deploy without a version shows its commit");
  has($("#qtl").querySelector(".qday").innerHTML, "today", "under a heading per day");
  // each item's time: start, end, how long in words, one bar; the legend once
  eq($("#qtl").querySelectorAll(".qlegend").length, 1, "one legend, at the top of the timeline");
  ok($("#qtl").innerHTML.indexOf("qlegend") < $("#qtl").innerHTML.indexOf(">Working<"), "above the bands");
  var qLeg = $("#qtl").querySelector(".qlegend").textContent;
  ok(/thinking/.test(qLeg) && /writing code/.test(qLeg) && /testing/.test(qLeg) && /deploying/.test(qLeg) && /reading/.test(qLeg),
     "naming every kind the bars show");
  ok(!/waiting for the seat/.test(qLeg), "and none they do not");
  var qT = $("#qtl").querySelector('.qb-ship [data-qtime="kim-c32@' + (nowS - 100) + '"]');
  ok(qT, "a shipped item has its time under it");
  has(qT.innerHTML, "2h 14m", "the end-to-end duration in words");
  has(qT.innerHTML, queueClock(nowS - 100 - 8040) + " &rarr; " + queueClock(nowS - 100), "from its start to its end, local");
  var qSeg = qT.querySelectorAll(".qbar i");
  eq(qSeg.length, 4, "one bar, a segment per kind");
  ok(qSeg[2].classList.contains("qk-test") && /width:50\.00%/.test(qSeg[2].getAttribute("style")), "each as wide as its share of the time");
  eq(qT.getAttribute("aria-expanded"), "false", "closed at first");
  var qLive = $("#qtl").querySelector('.qb-work [data-qtime="live:kim-c32"]');
  ok(qLive && /now/.test(qLive.innerHTML) && /15m/.test(qLive.innerHTML) && /so far/.test(qLive.innerHTML),
     "the work under way: its bar so far, to now");
  // the estimate under the working one's line (engineer.py eta): three states
  var qEta = function () { return $("#qtl").querySelector(".qb-work .etab"); };
  ok(qEta() && qEta().classList.contains("none") && /no estimate yet/.test(qEta().textContent), "no estimate yet: an empty bar that says so, dim");
  eq(qEta().querySelector(".etat i").getAttribute("style"), "width:0.0%", "and empty");
  ok($("#qtl").innerHTML.indexOf("etab") < $("#qtl").innerHTML.indexOf('data-qtime="live:kim-c32"'), "right under their line");
  ok(!$("#qtl").querySelector(".qb-wait .etab"), "the queued ones show their line as before");
  var qH = qv.data.seat.holder;
  qH.task_started_at = nowS - 12 * 60 - 20; qH.eta_min = 40; qH.eta_at = nowS - 600;
  queuePaint();
  ok(!/none|over|late/.test(qEta().className), "an estimate: in progress");
  has(qEta().textContent, "12 of about 40 min", "elapsed of the estimate, in words");
  eq(qEta().querySelector(".etat i").getAttribute("style"), "width:30.0%", "filled by elapsed over the estimate");
  eq(qEta().getAttribute("aria-valuenow"), "12", "and told to a screen reader");
  qH.task_started_at = nowS - 48 * 60 - 20;
  queuePaint();
  ok(qEta().classList.contains("over"), "past the estimate: amber");
  has(qEta().textContent, "8 min over the estimate of 40", "saying by how much");
  eq(qEta().querySelector(".etat i").getAttribute("style"), "width:100.0%", "and full");
  qH.task_started_at = nowS - 70 * 60 - 20;
  queuePaint();
  ok(qEta().classList.contains("late") && /30 min over/.test(qEta().textContent), "half as long again past it: red");
  // the minute's timer moves it between polls
  qH.task_started_at = nowS - 12 * 60 - 20;
  queuePaint();
  qEta().dataset.etaStart = String(nowS - 20 * 60 - 20);
  ok(etaTick(), "the timer finds the bars on screen");
  has(qEta().textContent, "20 of about 40 min", "and moves them on without a read");
  eq(qEta().querySelector(".etat i").style.width, "50.0%", "the fill too");
  // calibrated by the record (0.213.0): against expected_min, said and expected in words
  qH.task_started_at = nowS - 6 * 60 - 20; qH.eta_min = 100; qH.expected_min = 12; qH.ratio_from = "own";
  queuePaint();
  has(qEta().textContent, "6 of 12 min (said 100, expected 12)", "against the expected minutes, the estimate beside them");
  eq(qEta().querySelector(".etat i").getAttribute("style"), "width:50.0%", "filled against the expected");
  eq(qEta().getAttribute("aria-valuemax"), "12", "and so told");
  qEta().dataset.etaStart = String(nowS - 15 * 60 - 20);
  etaTick();
  ok(qEta().classList.contains("over") && /3 min over \(said 100, expected 12\)/.test(qEta().textContent),
     "the timer keeps the expected: past it, amber, both said");
  qH.task_started_at = nowS - 20 * 60 - 20;
  queuePaint();
  ok(qEta().classList.contains("late"), "half as long again past the expected: red");
  qH.task_started_at = nowS - 6 * 60 - 20; qH.expected_min = null; qH.ratio_from = "none";
  queuePaint();
  has(qEta().textContent, "6 of about 100 min", "no ratio on record: drawn as before");
  ok(!/expected/.test(qEta().textContent), "with no expected in words");
  delete qH.expected_min; delete qH.ratio_from; qH.eta_min = 40;
  qH.idle = nowS;
  queuePaint();
  ok(!qEta(), "not when the one seated is idle");
  delete qH.idle; delete qH.task_started_at; delete qH.eta_min; delete qH.eta_at;
  qv.data.deploys[0].eta = { est: 30, first: 20, actual: 41 };
  queuePaint();
  has($("#qtl").querySelector(".qb-ship .qitem.live").innerHTML, "estimated 30 min, took 41", "a shipped item: estimated against taken");
  ok(!/turns/.test($("#qtl").querySelector(".qb-ship .qitem.live").innerHTML), "one turn: not said");
  qv.data.deploys[0].eta = { est: 30, first: 20, actual: 41, turns: 2 };
  queuePaint();
  has($("#qtl").querySelector(".qb-ship .qitem.live").innerHTML, "took 41 over 2 turns", "a task sent back: its turns");
  delete qv.data.deploys[0].eta;
  queuePaint();
  eq(queueDur(40), "40s", "a duration under a minute in seconds");
  eq(queueDur(3600), "1h", "a whole hour without minutes");
  eq(queueDur(93600 + 60), "1d 2h", "days and hours past a day");
  click(qT);
  qT = $("#qtl").querySelector('.qb-ship [data-qtime="kim-c32@' + (nowS - 100) + '"]');
  eq(qT.getAttribute("aria-expanded"), "true", "a tap opens its breakdown at once");
  var qBrk = qT.nextElementSibling;
  ok(qBrk && qBrk.classList.contains("qbrk"), "under it");
  var qRows = qBrk.querySelectorAll("tr");
  eq(qRows.length, 4, "a line per kind");
  ok(/testing/.test(qRows[2].textContent) && /1h 7m/.test(qRows[2].textContent) && /50%/.test(qRows[2].textContent),
     "with its time and share");
  has(qBrk.textContent, "3 turns", "and the number of turns");
  has(qBrk.textContent, "a clock in the header, please", "and the order it came from");
  ok(!qv.data.deploys[0].time.partial && qBrk.textContent.indexOf("partial") < 0, "whole data is not called partial");
  qv.data.deploys[3].time = { start: nowS - 5000, end: nowS - 4000, dur: 1000, turns: 0, partial: true, kinds: [{ k: "deploy", s: 100 }, { k: "answer", s: 900 }] };
  queuePaint();
  ok($("#qtl").querySelector('[data-qtime="kim-c32@' + (nowS - 100) + '"]').getAttribute("aria-expanded") === "true", "a repaint keeps it open");
  has($("#qtl").querySelector('[data-qtime="yar-c36@' + (nowS - 4000) + '"]').innerHTML, "partial", "an item the transcripts do not cover says partial");
  click($("#qtl").querySelector('[data-qtime="kim-c32@' + (nowS - 100) + '"]'));
  ok(!$("#qtl").querySelector(".qbrk"), "a second tap closes it");
  var qHow = vMatch(vWords("how long did that take"), 0);
  ok(qHow && qHow.cmd.say === "how long did that take", "\"how long did that take\" is an order");
  await qHow.cmd.fn();
  ok($("#qtl").querySelector('[data-qtime="kim-c32@' + (nowS - 100) + '"]').getAttribute("aria-expanded") === "true",
     "which opens the newest shipped item's breakdown");
  qv.open.clear();
  has($("#qstat").textContent, "live 0.179.0", "the header says what is live");
  click($("#qrefresh"));
  ok($("#qrefresh").classList.contains("pressing"), "Read it again shows pressed at once");
  await settle(2);
  ok(!$("#qrefresh").classList.contains("pressing"), "until it is read");
  var qOpenWas = chatsOpen, qOpened = "";
  chatsOpen = function (id) { qOpened = id; };
  click($("#qtl").querySelector('.qb-wait [data-qeng="obrien-c33"]'));
  chatsOpen = qOpenWas;
  eq(qOpened, "eng-obrien-c33", "a crew member's item opens their conversation");

  // reorder and take out: thumb-sized controls under each queued item
  var qLine0 = engQueue1.seat.queue.slice(), qEdits = [], qAnswer = null, qHold = null;
  var qNames = function () { return [].map.call($("#qtl").querySelectorAll(".qb-wait .qctl"), function (c) { return c.dataset.qn; }); };
  var qCtl = function (n) { return $("#qtl").querySelector('.qctl[data-qn="' + n + '"]'); };
  var qFetch2 = fetch;
  fetch = function (url, o) {
    var m = /\/engineer\/queue\/(move|remove|restore)$/.exec(String(url));
    if (!m) return qFetch2.apply(this, arguments);
    var b = JSON.parse(o.body);
    qEdits.push(m[1] + " " + JSON.stringify(b));
    var answer = function () {
      if (qAnswer) { var a = qAnswer; qAnswer = null;
        var tx = JSON.stringify(a.body);
        return { ok: false, status: a.status, statusText: "", text: function () { return Promise.resolve(tx); },
                 json: function () { return Promise.resolve(JSON.parse(tx)); }, headers: { get: function () { return "application/json"; } } }; }
      var q = engQueue1.seat.queue, i = q.findIndex(function (x) { return x.name === b.name; });
      if (m[1] === "move") { var j = b.to === "first" ? 0 : i + (b.to === "up" ? -1 : 1); q.splice(j, 0, q.splice(i, 1)[0]); }
      if (m[1] === "remove") { qGone = q.splice(i, 1)[0]; qGoneAt = i; return engJson({ ok: true, cancelled: 2, seat: {} }); }
      if (m[1] === "restore") { q.splice(qGoneAt, 0, qGone); return engJson({ ok: true, name: qGone.name, restored: 2, seat: {} }); }
      return engJson({ ok: true, seat: {} });
    };
    if (qHold) return new Promise(function (res) { qHold = function () { res(answer()); }; });
    return Promise.resolve(answer());
  };
  var qGone = null, qGoneAt = -1;
  eq(qNames().join(), "obrien-c33,okafor-c30,crew:yeoman", "each queued item has its controls; who waits on an answer has none");
  var qUp0 = qCtl("obrien-c33").querySelector('[data-qact="up"]');
  ok(qUp0.disabled && qCtl("obrien-c33").querySelector('[data-qact="first"]').disabled, "the first cannot go up or to the front");
  ok(qCtl("crew:yeoman").querySelector('[data-qact="down"]').disabled, "the last cannot go down");
  ok(!qCtl("crew:yeoman").querySelector('[data-qact="remove"]'), "a scheduled role is not taken out (its timeout does that)");
  ok(!$("#qtl").querySelector('.qb-work .qctl'), "and the one seated has no controls at all");
  qHold = true;
  click(qCtl("okafor-c30").querySelector('[data-qact="up"]'));
  eq(qNames().join(), "okafor-c30,obrien-c33,crew:yeoman", "Up redraws the line at once, before the server answers");
  ok($("#qtl").querySelector(".qb-wait .qitem.qpend") && /moving/.test(qCtl("okafor-c30").textContent), "the moved one marked moving…");
  eq(qEdits[0], 'move {"name":"okafor-c30","to":"up","expect":"obrien-c33,okafor-c30,crew:yeoman"}', "posted with the line as it was read");
  qHold(); qHold = null;
  await settle(3);
  eq(qNames().join(), "okafor-c30,obrien-c33,crew:yeoman", "and the read after it agrees");
  ok(!$("#qtl").querySelector(".qitem.qpend"), "the mark gone once it landed");
  click(qCtl("crew:yeoman").querySelector('[data-qact="first"]'));
  await settle(3);
  eq(qNames().join(), "crew:yeoman,okafor-c30,obrien-c33", "To the front");
  // the line changed meanwhile (a handoff): a 409, said, and read again
  qAnswer = { status: 409, body: { error: "the queue changed since it was read" } };
  engQueue1.seat.queue = [engQueue1.seat.queue[1], engQueue1.seat.queue[2]];
  click(qCtl("obrien-c33").querySelector('[data-qact="up"]'));
  await settle(3);
  has($("#toast").textContent, "queue changed", "a 409 says the queue changed");
  eq(qNames().join(), "okafor-c30,obrien-c33", "and the line is read again, as the server has it");
  // Remove asks in the row, then takes out, with Undo
  click(qCtl("okafor-c30").querySelector('[data-qact="remove"]'));
  ok($("#qtl").querySelector(".qcf") && /out of the queue\?/.test($("#qtl").querySelector(".qcf").textContent), "Remove asks first, in the row");
  eq(qEdits.filter(function (e) { return /^remove/.test(e); }).length, 0, "and posts nothing yet");
  click($("#qtl").querySelector(".qcf [data-qno]"));
  ok(!$("#qtl").querySelector(".qcf") && qCtl("okafor-c30"), "Keep leaves them be");
  click(qCtl("okafor-c30").querySelector('[data-qact="remove"]'));
  qHold = true;
  click($("#qtl").querySelector(".qcf [data-qyes]"));
  ok(/taking out/.test(qCtl("okafor-c30").textContent), "Remove shows taking out… at once");
  qHold(); qHold = null;
  await settle(3);
  eq(qEdits[qEdits.length - 1], 'remove {"name":"okafor-c30","expect":"okafor-c30,obrien-c33"}', "posted with the line");
  eq(qNames().join(), "obrien-c33", "they are out of the line");
  has($("#toast").textContent, "2 orders cancelled", "the toast says their orders were cancelled");
  var qUndo = $("#toast").querySelector(".tact");
  ok(qUndo && qUndo.textContent === "Undo", "with an Undo");
  click(qUndo);
  await settle(3);
  eq(qEdits[qEdits.length - 1], 'restore {"name":"okafor-c30"}', "Undo restores them by name");
  eq(qNames().join(), "okafor-c30,obrien-c33", "back where they were");
  has($("#toast").textContent, "back in the queue with 2 orders", "their orders live again");
  // by voice: the same functions
  var qv1 = vMatch(vWords("move down okafor"), 0);
  ok(qv1 && qv1.cmd.say === "move down {*}", "\"move down Okafor\" is an order");
  await qv1.cmd.fn(qv1.arg); await settle(3);
  eq(qNames().join(), "obrien-c33,okafor-c30", "which moves them down");
  ok(vMatch(vWords("move up okafor"), 0).cmd.say === "move up {*}" && vMatch(vWords("to the front of the queue okafor"), 0).cmd.say === "to the front of the queue {*}",
     "up and to the front are orders too");
  var qv2 = vMatch(vWords("remove from the queue okafor"), 0);
  await qv2.cmd.fn(qv2.arg);
  ok($("#qtl").querySelector('.qcf[data-qn="okafor-c30"]'), "\"remove from the queue Okafor\" asks, as the button does");
  await vMatch(vWords("confirm the removal"), 0).cmd.fn(); await settle(3);
  eq(qNames().join(), "obrien-c33", "\"confirm the removal\" takes them out");
  await vMatch(vWords("undo the removal"), 0).cmd.fn(); await settle(3);
  eq(qEdits[qEdits.length - 1], 'restore {"name":""}', "\"undo the removal\" restores the latest");
  eq(qNames().join(), "obrien-c33,okafor-c30", "back in their place");
  fetch = qFetch2;
  engQueue1.seat.queue = qLine0;
  await queueFetch();

  // the job line (docs/design/job-queue.md): a Jobs block under the seat
  ok(/no job running or waiting/.test($("#qtl").querySelector(".qb-jobs").textContent), "with no jobs, the Jobs block says so");
  var qjGone = [];
  engQueue1.seat.jobs = {
    running: { id: "reyes-c20-20261021-140200", name: "reyes-c20", title: "Chief Ana Reyes", label: "lcars-ui/test/run.sh", t: nowS - 400, since: nowS - 180, elapsed: 180 },
    queue: [{ id: "okafor-c30-20261021-140500", name: "okafor-c30", title: "Lieutenant Daniel Okafor", label: "test/buttons.py", t: nowS - 60, place: 1, hold: true }],
    recent: [], note: "" };
  var qjFetch = fetch, qjHold = null, qjFail = false;
  fetch = function (url, o) {
    var m = /\/engineer\/([a-z0-9-]+)\/job-cancel$/.exec(String(url));
    if (!m) return qjFetch.apply(this, arguments);
    var b = JSON.parse(o.body);
    qjGone.push(m[1] + " " + b.id);
    var answer = function () {
      if (qjFail) { qjFail = false; var tx = JSON.stringify({ error: "okafor-c30 has no job in the line" });
        return { ok: false, status: 409, statusText: "", text: function () { return Promise.resolve(tx); },
                 json: function () { return Promise.resolve(JSON.parse(tx)); }, headers: { get: function () { return "application/json"; } } }; }
      var j = engQueue1.seat.jobs;
      if (j.running && j.running.id === b.id) j.running = null;
      j.queue = j.queue.filter(function (x) { return x.id !== b.id; });
      return engJson({ ok: true, cancelled: b.id });
    };
    if (qjHold) return new Promise(function (res) { qjHold = function () { res(answer()); }; });
    return Promise.resolve(answer());
  };
  await queueFetch();
  qHtml = $("#qtl").innerHTML;
  ok(qHtml.indexOf(">Queued<") < qHtml.indexOf(">Jobs<") && qHtml.indexOf(">Jobs<") < qHtml.indexOf(">Shipped<"), "the Jobs block sits under the seat, above Shipped");
  var qJobs = $("#qtl").querySelectorAll(".qb-jobs .qitem");
  eq(qJobs.length, 2, "the running job, then the job line");
  has(qJobs[0].innerHTML, "Chief Ana Reyes", "whose job runs");
  has(qJobs[0].innerHTML, "lcars-ui/test/run.sh", "with its label");
  has(qJobs[0].innerHTML, "running 3m", "and how long it has run");
  has(qJobs[1].innerHTML, "#1", "the line in order");
  has(qJobs[1].innerHTML, "test/buttons.py", "each with its label");
  has(qJobs[1].innerHTML, "starts when their turn ends", "a held one says why it waits");
  var qjCtl = function (id) { return $("#qtl").querySelector('.qctl[data-qj="' + id + '"]'); };
  ok(qjCtl("reyes-c20-20261021-140200") && qjCtl("okafor-c30-20261021-140500"), "each job has a Cancel");
  click(qjCtl("reyes-c20-20261021-140200").querySelector("[data-qjc]"));
  ok(/Cancel Chief Ana Reyes's job\?/.test($("#qtl").querySelector(".qcf").textContent), "Cancel asks first, in the row");
  eq(qjGone.length, 0, "and posts nothing yet");
  click($("#qtl").querySelector(".qcf [data-qjno]"));
  ok(!$("#qtl").querySelector(".qcf"), "Keep leaves it running");
  click(qjCtl("reyes-c20-20261021-140200").querySelector("[data-qjc]"));
  qjHold = true;
  click($("#qtl").querySelector(".qcf [data-qjyes]"));
  ok(/cancelling/.test(qjCtl("reyes-c20-20261021-140200").textContent) && $("#qtl").querySelector(".qb-jobs .qitem.qpend"),
     "Cancel the job shows cancelling… at once, before the server answers");
  qjHold(); qjHold = null;
  await settle(3);
  eq(qjGone[0], "reyes-c20 reyes-c20-20261021-140200", "posted to /engineer/<name>/job-cancel with the job's id");
  has($("#toast").textContent, "job cancelled", "the toast says so");
  eq($("#qtl").querySelectorAll(".qb-jobs .qitem").length, 1, "and the read after it has the job gone");
  // a failure said on the row
  qjFail = true;
  click(qjCtl("okafor-c30-20261021-140500").querySelector("[data-qjc]"));
  click($("#qtl").querySelector(".qcf [data-qjyes]"));
  await settle(3);
  has(qjCtl("okafor-c30-20261021-140500").textContent, "not cancelled", "a failed cancel says so on its row");
  // by voice
  var qj1 = vMatch(vWords("cancel okafor's job"), 0);
  ok(qj1 && qj1.cmd.say === "cancel {*} job", "\"cancel Okafor's job\" is an order");
  var qjN = qjGone.length;
  await qj1.cmd.fn(qj1.arg);
  ok(document.activeElement === $("#qtl").querySelector(".qcf [data-qjno]"), "the focus on Keep, as the tap leaves it");
  await settle(3);
  ok($("#qtl").querySelector('.qcf[data-qj="okafor-c30-20261021-140500"]'), "which asks in their job's row, the 's no part of the name");
  eq(qjGone.length, qjN, "and cancels nothing by voice alone");
  click($("#qtl").querySelector(".qcf [data-qjyes]"));
  await settle(3);
  eq(qjGone[qjGone.length - 1], "okafor-c30 okafor-c30-20261021-140500", "the tap on Cancel the job cancels it");
  ok(!$("#qtl").querySelector(".qb-jobs .qctl"), "the line empty after it");
  var qj2 = vMatch(vWords("show the jobs"), 0);
  ok(qj2 && qj2.cmd.say === "show the jobs" && vMatch(vWords("what jobs are running"), 0).cmd.say === "show the jobs", "\"show the jobs\" is an order");
  await qj2.cmd.fn(qj2.arg);
  ok(!qv.wantJobs && $("#qjobs"), "it paints the queue at its Jobs block");
  // the Crew list: a row's badge and the queue row's preview
  has(engRowHtml({ name: "okafor-c30", title: "Lieutenant Daniel Okafor", status: "off", job: { id: "j", label: "x", state: "queued", place: 2, since: nowS } }),
      "job #2", "a crew row waiting on a queued job wears its place");
  has(engRowHtml({ name: "okafor-c30", title: "Lieutenant Daniel Okafor", status: "off", job: { id: "j", label: "x", state: "running", place: 0, since: nowS - 180 } }),
      "job 3m", "a running one, how long it has run");
  var qjSeat = eng.seat;
  eng.seat = Object.assign({}, qjSeat, { jobs: { running: { id: "j", name: "reyes-c20", label: "x", since: nowS }, queue: [], recent: [] } });
  has(queueRowHtml(), "· job: ", "the Queue row's preview names whose job runs");
  eng.seat = qjSeat;
  fetch = qjFetch;
  delete engQueue1.seat.jobs;
  await queueFetch();
  ok(vMatch(vWords("what is in the queue"), 0).cmd.say === "show the queue", "\"what is in the queue\" is the queue");
  ok(vMatch(vWords("deploy history"), 0).cmd.say === "show the queue", "\"deploy history\" too, not a deploy of someone called history");
  ok(vMatch(vWords("what shipped"), 0).cmd.say === "show the queue", "and \"what shipped\"");
  ok(KEYMAP.get("Q") && /openQueue/.test(String(KEYMAP.get("Q").fn)), "Q is the queue");
  click($("#qback"));
  await settle(2);
  ok($("#dlg").classList.contains("chats") && $("#chrows"), "‹ is back to the chats it was opened from");
  fetch = qFetch;
  await vMatch(vWords("show the queue"), 0).cmd.fn();
  await settle(2);
  ok($("#dlg").classList.contains("qview"), "\"show the queue\" opens it");
  chatEscape();
  ok($("#dlg").classList.contains("chats"), "and Escape goes back to the chats");

  // a thread from their transcript
  engPoll1 = { session: "s1", next: 300, first: 0, status: "idle", task: "the boiler",
               git: { branch: "eng/reyes-c20", ahead: 2, last: "Fix the boiler", base: "deb" },
               events: [{ r: "me", t: "fix the boiler" }, { r: "tool", t: "Read index.html" }, { r: "text", t: "On it: **the valve**." }] };
  // their context in the row, a share of engineer.py's handover mark
  var rcR = $("#chrows").querySelector('.chrow[data-eng="reyes-c20"] .chrc'), rcK = $("#chrows").querySelector('.chrow[data-eng="kim-c32"] .chrc');
  eq(rcR && rcR.textContent, "84%", "a crew row gives their context as a percentage of the handover mark");
  ok(rcR && !rcR.classList.contains("over") && rcK && rcK.textContent === "125%" && rcK.classList.contains("over"),
     "amber past the mark");
  // the reading's chip only: the inbox's "n waiting" is a .chrc too (.chinq)
  ok(!Array.prototype.some.call($("#chrows").querySelectorAll('.chrow[data-eng="obrien-c33"] .chrc'),
                                function (c) { return !c.classList.contains("chinq"); }), "and none for one with no reading");
  click($("#chrows").querySelector('.chrow[data-eng="reyes-c20"]'));
  ok(!$(".chth .chgauge").hidden && $(".chth .chgauge").textContent.indexOf("…") >= 0, "the thread's context gauge is there at once, pending");
  await settle(3);
  var rt = chat;
  eq(rt.id, "eng-reyes-c20", "a row opens the engineer's thread");
  ok(!engUnread(crewEngs[0]), "which reads what they said");
  eq(curRel().split("?")[0], "chats/eng-reyes-c20", "at ./chats/eng-<name>");
  ok(engPosts.some(function (u) { return u.indexOf("GET /engineer/reyes-c20?off=-1") === 0; }), "their transcript is read from its tail");
  eq($(".chth .chlog").children.length, 2, "the captain's words a bubble, the rest one answer");
  has($(".chth .chlog").innerHTML, "1 step", "its tool lines folded into a chip");
  has($(".chth .chlog").innerHTML, "<b>the valve</b>", "its words markdown");
  has($(".chth .chhdr .chstat").textContent, "eng/reyes-c20", "the header says their branch");
  has($(".chth .chhdr .chstat").textContent, "2 commits to deploy", "and what waits to deploy");
  ok(!$(".chth .chmodel").hidden && $(".chth .chmodel").textContent.indexOf("Opus") >= 0, "an engineer's chip is their session's model (opus when none is said)");
  has($(".chth .chgauge").textContent, "\u2014", "no reading in their poll: the gauge says so");
  engPoll1 = { session: "s1", next: 300, first: 0, status: "idle", ctx: 167000, events: [] };
  await engPoll(rt); await settle(1);
  has($(".chth .chgauge").textContent, "84%", "their poll's context, as a percentage of the handover mark");
  ok(!$(".chth .chgauge").classList.contains("over") && $(".chth .chhdr .chstat").textContent.indexOf("ctx") < 0,
     "not amber under it, and no longer the status line's tail");
  engPoll1 = { session: "s1", next: 300, first: 0, status: "idle", ctx: 250000, events: [] };
  await engPoll(rt); await settle(1);
  ok($(".chth .chgauge").textContent.indexOf("125%") >= 0 && $(".chth .chgauge").classList.contains("over"), "past the mark: amber");
  ok($(".chth .cheta").hidden && !$(".chth .cheta").querySelector(".etab"), "no estimate bar while they are idle");
  ok(JSON.parse(localStorage.getItem("lcars.chats")).list.every(function (t) { return t.id.indexOf("eng-") !== 0; }),
     "and their thread is not saved here: the transcript is the server's");
  var rtFirst = $(".chth .chlog").children[0], rtAns = $(".chth .chlog").children[1];
  engPoll1 = { session: "s1", next: 400, first: 0, status: "working", events: [{ r: "text", t: "Built clean." }] };
  await engPoll(rt); await settle(1);
  ok($(".chth .chlog").children[0] === rtFirst && $(".chth .chlog").children[1] === rtAns, "a poll extends the answer in place");
  has(rtAns.innerHTML, "Built clean.", "with the new words");
  has($(".chth .chlog").innerHTML, "working", "and says they are working");
  ok(!$(".chth .cheta").hidden && /no estimate yet/.test($(".chth .cheta").textContent), "their estimate's bar at the top while they work: none yet");
  engPoll1 = { session: "s1", next: 400, first: 0, status: "working", events: [], eta_min: 40, task_started_at: Math.floor(Date.now() / 1000) - 12 * 60 - 5 };
  await engPoll(rt); await settle(1);
  has($(".chth .cheta").textContent, "12 of about 40 min", "then elapsed of the estimate");
  engPoll1 = { session: "s1", next: 400, first: 0, status: "working", events: [], eta_min: 40, task_started_at: Math.floor(Date.now() / 1000) - 48 * 60 - 5 };
  await engPoll(rt); await settle(1);
  ok($(".chth .cheta").querySelector(".etab.over") && /8 min over the estimate of 40/.test($(".chth .cheta").textContent), "and past it, amber");
  engPoll1 = { session: "s1", next: 400, first: 0, status: "working", events: [], eta_min: 40, expected_min: 8, ratio_from: "crew", task_started_at: Math.floor(Date.now() / 1000) - 2 * 60 - 5 };
  await engPoll(rt); await settle(1);
  has($(".chth .cheta").textContent, "2 of 8 min (said 40, expected 8)", "calibrated: against the expected, said beside it");
  engPoll1 = { session: "s1", next: 400, first: 0, status: "working", events: [] };
  await engPoll(rt); await settle(1);
  eq($(".chth .chsend").textContent, "Stop", "Send is Stop while they work");
  click($(".chth .chsend")); await settle(2);
  ok(engPosts.some(function (u) { return /\/key .*"esc"/.test(u); }), "Stop is Esc on their screen");

  // a message: at once, then queued for the seat
  engSay1 = { ok: true, queued: true, seat: { position: 2, holder: "kim-c32" } };
  engPoll1 = { session: "s1", next: 400, first: 0, status: "queued", events: [] };
  $(".chth .chbox").value = "and the dentist"; $(".chth .chbox").oninput();
  eq($(".chth .chsend").textContent, "Send", "typing makes it Send: it waits its turn, it does not stop them");
  var rtSend = chatSend();
  has($(".chth .chlog").innerHTML, "sending", "the bubble is there at once, sending");
  await rtSend; await settle(2);
  ok(engPosts.some(function (u) { return /^POST \/engineer\/reyes-c20\/say .*and the dentist/.test(u); }), "said to them");
  has($(".chth .chlog").innerHTML, "queued", "not in the seat: marked queued");
  has($(".chth .chlog").innerHTML, "#2 in line for the seat, after Lieutenant Harry Kim", "with where in line, after whom");
  engPoll1 = { session: "s1", next: 500, first: 0, status: "idle", events: [{ r: "me", t: "and the dentist" }] };
  await engPoll(rt); await settle(1);
  ok($(".chth .chlog").innerHTML.indexOf("queued") < 0, "in the transcript: the queued mark goes");
  eq(rt.msgs.filter(function (m) { return m.text === "and the dentist"; }).length, 1, "and the message is there once");

  // their inbox: crew_inbox entries not done, titled "<name> ← <from>: …"
  ok($(".chth .chinbox").hidden, "nothing waiting: no inbox block");
  var ibTop = st.all.reduce(function (m, e) { return Math.max(m, e.id); }, 0);
  var ibMk = function (n, title, content, done, ago) {
    var at = new Date(Date.now() - ago * 60000).toISOString().slice(0, 19).replace("T", " ");
    var r = { id: ibTop + n, kind: "crew_inbox", title: title, content: content, created_at_utc: at, last_modified_at_utc: at,
              deleted: 0, done_bool: done, content_length: content.length };
    st.all.unshift(r); st.byId.set(r.id, r); return r;
  };
  var ib2 = ibMk(2, "reyes-c20 ← ship: [ship] the build broke", "[ship] the build broke\non deb", 0, 3);
  var ib1 = ibMk(1, "reyes-c20 ← No.1 [fresh]: [No.1] fix the valve", "[No.1] fix the valve\nand test it on the phone", 0, 20);
  ibMk(3, "kim-c32 ← No.1: [No.1] not his", "[No.1] not his", 0, 5);
  ibMk(4, "reyes-c20 ← No.1: [No.1] already typed", "[No.1] already typed", 1, 60);
  refresh(); await settle(1);
  var ibBox = $(".chth .chinbox");
  ok(!ibBox.hidden, "two waiting: the inbox block over the box");
  var ibItems = ibBox.querySelectorAll("li[data-inid]");
  eq(Array.prototype.map.call(ibItems, function (l) { return Number(l.dataset.inid); }).join(","), ib1.id + "," + ib2.id,
     "theirs only, the delivered left out, oldest first");
  has(ibBox.innerHTML, "2 waiting", "it says how many");
  has(ibBox.innerHTML, "seat: Lieutenant Harry Kim", "and who holds the seat, by name");
  has(ibItems[0].innerHTML, "Number One", "each its sender: Number One");
  has(ibItems[1].innerHTML, "the ship", "the ship");
  has(ibItems[0].innerHTML, "queued 20m ago", "when it was queued");
  has(ibItems[0].innerHTML, "[No.1] fix the valve", "its first line");
  ok(ibItems[0].innerHTML.indexOf("test it on the phone") < 0, "folded: not the rest");
  click(ibItems[0].querySelector(".chinx"));
  has($(".chth .chinbox").querySelector('li[data-inid="' + ib1.id + '"]').innerHTML, "and test it on the phone", "a tap opens the whole order, at once");
  eq($(".chth .chinbox").querySelector('li[data-inid="' + ib1.id + '"] .chinx').getAttribute("aria-expanded"), "true", "and says it is open");
  has(engRowHtml(crewEngs[0]), "2 waiting", "their Crew row counts what waits");
  ok(engRowHtml(crewEngs[1]).indexOf("waiting") < 0, "one with nothing waiting has no count");
  // Open: the entry in the editor
  var ibSel = [], ibSelWas = select, ibCoWas = closeOv;
  select = function (id) { ibSel.push(id); }; closeOv = function () {};
  click($(".chth .chinbox").querySelector('[data-inopen="' + ib2.id + '"]'));
  eq(ibSel.join(","), String(ib2.id), "Open opens that entry in the editor (select)");
  ibSel = [];
  var ibHit = vMatch(vWords("open the waiting order"), 0);
  ok(ibHit && ibHit.cmd.say === "open the waiting order", "\"open the waiting order\" is an order");
  ibHit.cmd.fn(ibHit.arg);
  ibHit = vMatch(vWords("open waiting order two"), 0);
  ibHit.cmd.fn(ibHit.arg);
  eq(ibSel.join(","), ib1.id + "," + ib2.id, "by voice: the oldest, then the second");
  select = ibSelWas; closeOv = ibCoWas;
  // delivered: /events brings done 1 and the item goes
  ib1.done_bool = 1; refresh(); await settle(1);
  eq($(".chth .chinbox").querySelectorAll("li[data-inid]").length, 1, "one delivered: it leaves the block");
  has($(".chth .chinbox").innerHTML, "1 waiting", "the count follows");
  has(engRowHtml(crewEngs[0]), "1 waiting", "and so does the row's");
  ib2.done_bool = 1; refresh(); await settle(1);
  ok($(".chth .chinbox").hidden && !$(".chth .chinbox").innerHTML, "none waiting: the block goes");
  ok(engRowHtml(crewEngs[0]).indexOf("waiting") < 0, "and the count");
  st.all = st.all.filter(function (r) { return !(r.id > ibTop && r.id <= ibTop + 4); });
  for (var ibI = 1; ibI <= 4; ibI++) st.byId.delete(ibTop + ibI);
  refresh();
  engSay1 = function () { return Promise.reject(new Error("the seat is stopped")); };
  await chatSend("one more"); await settle(2);
  has($(".chth .chlog").innerHTML, "not sent", "a message that did not go says so on its bubble");
  eq($(".chth .chbox").value, "one more", "and its words are back in the box");
  $(".chth .chbox").value = ""; rt.eng.pending = []; engSay1 = { ok: true };

  // the question on their screen
  engPoll1 = { session: "s1", next: 500, first: 0, status: "blocked", events: [],
               screen: "Trust this folder?\n❯ 1. Yes, proceed\n  2. No, exit" };
  await engPoll(rt); await settle(1);
  ok(!$(".chth .chqcard").hidden, "a question on their screen is a card over the box");
  eq($(".chth .chqcard").querySelectorAll(".chqopt").length, 2, "a chip per numbered answer");
  click($(".chth .chqcard").querySelector('[data-k="1"]'));
  ok($(".chth .chqcard").hidden, "answered: the card folds at once");
  has($(".chth .chlog").innerHTML, "Answered: 1. Yes, proceed", "into what was answered");
  await settle(2);
  ok(engPosts.some(function (u) { return /\/reyes-c20\/key .*"1"/.test(u); }), "and the key goes to their screen");

  // deploy: asked in the sheet, then followed in the thread
  engPoll1 = { session: "s1", next: 500, first: 0, status: "idle", events: [],
               git: { branch: "eng/reyes-c20", ahead: 2, last: "Fix the boiler", base: "deb" }, deploy: { state: "done", verb: "deploy" } };
  await engPoll(rt); await settle(1);
  click($(".chth .chmore"));
  var depOpt = $(".chth .chsheet").querySelector('[data-act="deploy"]');
  ok(depOpt && !depOpt.disabled, "⋯ has Deploy, with commits to deploy");
  click(depOpt);
  has($(".chth .chsheet").innerHTML, "Deploy Chief Ana Reyes", "which asks first");
  has($(".chth .chsheet").innerHTML, "Fix the boiler", "naming what goes");
  click($(".chth .chsheet").querySelector('.pill[data-act="deploy"]'));
  ok($(".chth .chscrim").hidden, "yes closes the sheet");
  has($(".chth .chlog").innerHTML, "Deploy asked for", "and the thread says so at once");
  await settle(2);
  ok(engPosts.some(function (u) { return u.indexOf("POST /engineer/reyes-c20/deploy") === 0; }), "the deploy is posted");
  ok(!rt.eng.deploy || rt.eng.deploy.line.text === "Deploy asked for", "an old deploy's state does not end the new one");
  engPoll1.deploy = { state: "running", verb: "deploy" }; await engPoll(rt); await settle(1);
  has($(".chth .chlog").innerHTML, "deploy running", "the line follows it");
  engPoll1.deploy = { state: "done", verb: "deploy", msg: "0.159.0" }; await engPoll(rt); await settle(1);
  has($(".chth .chlog").innerHTML, "deploy done: 0.159.0", "to its end");
  ok($(".chth .chlog").querySelector(".chsys.ok"), "marked as gone well");
  // a deploy of their work started elsewhere (Number One) is told as it goes
  engPoll1.deploy = { started: 77, state: "running", verb: "deploy", name: "reyes-c20" }; await engPoll(rt); await settle(1);
  engPoll1.deploy = { started: 77, state: "done", verb: "deploy", name: "reyes-c20", msg: "0.161.0" }; await engPoll(rt); await settle(1);
  has($(".chth .chlog").innerHTML, "Deploy · ✓ 0.161.0", "a deploy started elsewhere is told in the thread too");
  engPoll1.deploy = { started: 78, state: "running", verb: "deploy", name: "kim-c32" }; await engPoll(rt); await settle(1);
  ok($(".chth .chlog").innerHTML.indexOf("kim") < 0 && rt.eng.done.filter(function (m) { return /^Deploy · /.test(m.text || ""); }).length === 2,
     "but not someone else's");

  // their model: the chip at once, pending until their poll says it took
  engPoll1 = { session: "s1", next: 500, first: 0, status: "working", events: [], model: "opus", model_pending: "", model_used: "claude-opus-5-5" };
  await engPoll(rt); await settle(1);
  ok(!$(".chth .chmodel").hidden && !$(".chth .chmodel").disabled, "an engineer's thread has the model chip");
  has($(".chth .chmodel").textContent, "Opus", "naming the model they run on");
  click($(".chth .chmodel"));
  has($(".chth .chsheet").innerHTML, "their turn ends", "the picker says when it takes effect");
  engModel1 = function () { return engJson({ ok: true, model: "haiku", pending: true, note: "takes effect when their turn ends" }); };
  click($(".chth .chsheet").querySelector('[data-model="haiku"]'));
  has($(".chth .chmodel").textContent, "Haiku \u22ef", "the chip changes at once, marked pending");
  has($(".chth .chlog").innerHTML, "Model → Haiku asked for", "and the thread says so");
  await settle(3);
  ok(engPosts.some(function (u) { return /^POST \/engineer\/reyes-c20\/model .*"haiku"/.test(u); }), "posted to /engineer/<name>/model");
  has($(".chth .chlog").innerHTML, "Model → Haiku when their turn ends", "working: when their turn ends");
  engPoll1 = Object.assign({}, engPoll1, { model: "haiku", model_pending: "haiku" }); await engPoll(rt); await settle(1);
  has($(".chth .chmodel").textContent, "\u22ef", "still pending while their turn runs");
  engPoll1 = Object.assign({}, engPoll1, { status: "idle", model_pending: "" }); await engPoll(rt); await settle(1);
  has($(".chth .chmodel").textContent, "Haiku \u25be", "taken: the mark goes");
  var userWas2 = cfg.user;
  if (!cfg.user) cfg.user = "someone";
  engModel1 = function () { return Promise.resolve({ ok: false, status: 403, statusText: "Forbidden",
    json: function () { return Promise.resolve({ error: "not for this login" }); },
    text: function () { return Promise.resolve("{\"error\":\"not for this login\"}"); }, headers: { get: function () { return "application/json"; } } }); };
  chatModelSet("Fable");
  has($(".chth .chmodel").textContent, "Fable", "asked again: at once");
  await settle(3);
  has($(".chth .chmodel").textContent, "Haiku", "refused: the choice is put back");
  ok($(".chth .chlog").querySelector(".chsys.bad") && $(".chth .chlog").innerHTML.indexOf("may not choose") >= 0, "and the thread says why, in red");
  ok($(".chth .chmodel").disabled, "and the chip is off for this login");
  localStorage.removeItem("lcars.eng.modelno");
  cfg.user = userWas2;

  // their earlier conversations: one kept by a clear, listed by task and
  // date, opened read-only in the same thread, the current one back after
  var pastAt = Math.floor(new Date(2026, 9, 11, 14, 5).getTime() / 1000);
  engPoll1 = Object.assign({}, engPoll1, { status: "idle", events: [],
    past: [{ name: "fix the boiler", session: "0a1b-old", at: pastAt }] });
  await engPoll(rt); await settle(1);
  chatSheet("more");
  var pastOpt = $(".chth .chsheet").querySelector('[data-act="pastlist"]');
  ok(pastOpt && pastOpt.textContent.indexOf("1 kept") >= 0, "⋯ has Earlier conversations when one was kept");
  click(pastOpt);
  var pastRow = $(".chth .chsheet").querySelector('[data-past="0a1b-old"]');
  ok(pastRow && pastRow.textContent.indexOf("fix the boiler") >= 0 && pastRow.textContent.indexOf("Sun 11 Oct, 14:05") >= 0,
     "listed by its task and the date it was cleared");
  ok($(".chth .chsheet").querySelector('[data-past=""][aria-pressed="true"]'), "the current one first, and the one shown");
  var pastFetch = fetch;
  fetch = function (url) {
    if (/past=0a1b-old/.test(String(url))) { engPosts.push("GET " + String(url).replace(/^.*\/engineer/, "/engineer"));
      return engJson(Object.assign({}, engPoll1, { viewing: "0a1b-old", next: 90, first: 0,
        events: [{ r: "me", t: "the boiler again" }, { r: "text", t: "The old valve was it." }] })); }
    return pastFetch.apply(this, arguments);
  };
  engPosts = [];
  click(pastRow);
  has($(".chth .chlog").innerHTML, "Opening", "opening one says so at once");
  await settle(3);
  ok(engPosts.some(function (u) { return u.indexOf("GET /engineer/reyes-c20?off=-1&past=0a1b-old") === 0; }), "it is read with &past=<its session>");
  has($(".chth .chlog").innerHTML, "The old valve was it.", "its messages in the same thread");
  ok($(".chth .chlog").innerHTML.indexOf("Built clean.") < 0, "and not the current one's");
  has($(".chth .chlog").innerHTML, "read-only", "marked read-only");
  has($(".chth .chhdr .chstat").textContent, "an earlier conversation", "the header says so too");
  ok($(".chth .chbox").disabled && $(".chth .chsend").disabled, "the box is off: it is read, not answered");
  chatSheet("more");
  ok(!$(".chth .chsheet").querySelector('[data-act="clear"]'), "⋯ offers no Clear: it would clear the current one, not this");
  chatSheet("");
  engPosts = [];
  await settle(3);
  ok(!engPosts.some(function (u) { return /past=/.test(u); }), "and it is not polled again");
  eq(vMatch(vWords("back to the current conversation"), 0).cmd.say, "current conversation", "the order to go back");
  vMatch(vWords("current conversation"), 0).cmd.fn();
  await settle(3);
  ok(!rt.eng.view && !$(".chth .chbox").disabled, "\"current conversation\" goes back, the box on again");
  ok($(".chth .chlog").innerHTML.indexOf("The old valve was it.") < 0, "the old one gone from the log");
  var pastHit = vMatch(vWords("earlier conversation the boiler"), 0);
  pastHit.cmd.fn(pastHit.arg);
  await settle(3);
  eq(rt.eng.view && rt.eng.view.session, "0a1b-old", "\"earlier conversation <name>\" opens it by name");
  engPast(""); await settle(3);
  fetch = pastFetch;
  vMatch(vWords("show earlier conversations"), 0).cmd.fn();
  ok(!$(".chth .chscrim").hidden && $(".chth .chsheet").querySelector('[data-past="0a1b-old"]'), "\"earlier conversations\" opens the list");
  chatSheet("");

  // scrolling back: past the current conversation's start into the kept
  // ones, newest first, a page at a time, a divider at each clear, the
  // reader's place held as each page goes on top
  var atA = Math.floor(new Date(2026, 9, 9, 9, 30).getTime() / 1000), atB = Math.floor(new Date(2026, 9, 10, 18, 0).getTime() / 1000);
  engPoll1 = Object.assign({}, engPoll1, { status: "idle", first: 0, task: "chat stage 7", events: [{ r: "me", t: "now the scroll" }],
    past: [{ name: "the boiler", session: "aa01", at: atA }, { name: "course map", session: "bb02", at: atB }] });
  rt.eng.off = -1;
  await engPoll(rt); await settle(1);
  var sLog = $(".chth .chlog");
  // 50px a message, in a log shorter than what it holds (else it is at its end)
  Object.defineProperty(sLog, "scrollHeight", { get: function () { return sLog.children.length * 50; }, configurable: true });
  var sLogH = sLog.clientHeight;
  sLog.clientHeight = 20;
  has(sLog.innerHTML, "earlier conversation: \u201ccourse map\u201d", "at the current one's start, the top line names the conversation before it");
  var scrollFetch = fetch;
  fetch = function (url) {
    var u = String(url), b = (/before=(-?\d+)/.exec(u) || [])[1];
    var pg = /past=bb02/.test(u) ? (b === "120" ? { first: 0, events: [{ r: "me", t: "start the map" }, { r: "text", t: "Mapped." }] }
                                                : { first: 120, events: [{ r: "me", t: "the deck map" }, { r: "text", t: "Turned the map." }] })
           : /past=aa01/.test(u) ? { first: 0, events: [{ r: "me", t: "the boiler first" }, { r: "text", t: "Valve." }] } : null;
    if (!pg) return scrollFetch.apply(this, arguments);
    engPosts.push("GET " + u.replace(/^.*\/engineer/, "/engineer"));
    return engJson(Object.assign({}, engPoll1, pg, { viewing: /past=(\w+)/.exec(u)[1], next: 0 }));
  };
  engPosts = [];
  var kids0 = sLog.children.length;
  sLog.scrollTop = 0;
  var up1 = engEarlier(rt);
  has(sLog.innerHTML, "loading \u201ccourse map\u201d", "scrolled up: a loading line at once, naming it");
  await up1; await settle(1);
  ok(engPosts.some(function (u) { return /\/engineer\/reyes-c20\?off=-1&before=-1&past=bb02/.test(u); }), "the newest kept one is read from its tail with &past=");
  var h1 = sLog.innerHTML;
  ok(h1.indexOf("Turned the map.") >= 0 && h1.indexOf("Turned the map.") < h1.indexOf("\u25b2 \u201ccourse map\u201d") &&
     h1.indexOf("\u25b2 \u201ccourse map\u201d") < h1.indexOf("now the scroll"), "above the current one, with the divider between");
  has(h1, "\u25b2 \u201ccourse map\u201d \u00b7 cleared " + engPastWhen({ at: atB }), "the divider says what the earlier one was, and when cleared");
  has(h1, "\u25bc the current conversation: chat stage 7", "and what comes next");
  eq(sLog.scrollTop, (sLog.children.length - kids0) * 50, "the reader's place is kept as the page goes on top");
  var kids1 = sLog.children.length;
  sLog.scrollTop = 0;
  sLog.onscroll();
  await settle(3);
  ok(engPosts.some(function (u) { return /before=120&past=bb02/.test(u); }), "scrolled to the top again: its page before, &before=");
  ok(sLog.innerHTML.indexOf("start the map") < sLog.innerHTML.indexOf("the deck map"), "on top of it, in order");
  eq(sLog.scrollTop, (sLog.children.length - kids1) * 50, "the place kept again");
  sLog.scrollTop = 0;
  await engEarlier(rt); await settle(1);
  ok(engPosts.some(function (u) { return /off=-1&before=-1&past=aa01/.test(u); }), "at its start, the one kept before it");
  var h3 = sLog.innerHTML, order = ["Valve.", "\u25b2 \u201cthe boiler\u201d", "\u25bc \u201ccourse map\u201d \u00b7 cleared " + engPastWhen({ at: atB }),
    "start the map", "Turned the map.", "\u25b2 \u201ccourse map\u201d", "now the scroll"].map(function (x) { return h3.indexOf(x); });
  ok(order.every(function (x, i) { return x >= 0 && (!i || x > order[i - 1]); }), "oldest at the top: each conversation, then its divider, the current one last (" + order.join(",") + ")");
  ok(engUp(rt.eng) === null && !sLog.querySelector("[data-earlier]"), "at the first kept one's start: nothing more to load");
  engPosts = [];
  $(".chth .chbox").value = "and the next"; await chatSend(); await settle(3);
  ok(engPosts.some(function (u) { return /^POST \/engineer\/reyes-c20\/say .*and the next/.test(u); }), "a message goes to the current conversation");
  fetch = scrollFetch;
  delete sLog.scrollHeight;
  sLog.clientHeight = sLogH;
  engPoll1 = Object.assign({}, engPoll1, { past: [], events: [] });

  // Number One, and his questions
  engPosts = [];
  await engNo1("status report"); await settle(3);
  eq(chat.id, "eng-number-one", "Number One's thread");
  ok(!engPosts.some(function (u) { return /number-one\/start/.test(u); }), "not started again when on duty");
  ok(engPosts.some(function (u) { return /number-one\/say .*status report/.test(u); }), "with the words said to him");

  // his threads (no1-threads.md, section 13): labels on one conversation;
  // the chips filter it, and the one picked tags what is sent
  var thrFetch = fetch, thrOps = [], thrSays = [], thrSayEnd = null, thrSayAns = { ok: true };
  var thrList = [{ id: "main", name: "Main" }, { id: "deck", name: "Deck redesign" }];
  fetch = function (url, o) {
    var u = String(url);
    if (u.indexOf("/engineer/number-one") < 0) return thrFetch.apply(this, arguments);
    engPosts.push(((o && o.method) || "GET") + " " + u.replace(/^.*\/engineer/, "/engineer"));
    if (/\/thread$/.test(u)) {
      var b = JSON.parse(o.body);
      thrOps.push(b);
      if (b.op === "new") thrList = thrList.concat([{ id: b.id, name: b.name }]);
      if (b.op === "close") thrList = thrList.filter(function (x) { return x.id !== b.id; });
      return engJson({ ok: true, threads: thrList, closed: [] });
    }
    if (/\/say$/.test(u)) {
      thrSays.push(JSON.parse(o.body));
      return new Promise(function (res) { thrSayEnd = function () { res(engJson(thrSayAns)); }; }).then(function (x) { return x; });
    }
    if (/\?off=/.test(u)) {
      return engJson({ session: "s-main", next: 10, first: 0, status: "idle", threads: thrList,
                       events: /off=-1/.test(u) ? [{ r: "me", t: "status report", th: "main" }, { r: "them", t: "All quiet.", th: "main" },
                                                   { r: "me", t: "about the chairs", th: "deck" }, { r: "them", t: "Chairs done.", th: "deck" },
                                                   { r: "them", t: "And main is fine.", th: "main" }] : [] });
    }
    return engJson({ ok: true });
  };
  var n1 = chat;
  n1.eng.off = -1;
  await engPoll(n1); await settle(2);
  var thr = $(".chth .chthr"), chips = thr.querySelectorAll("[data-thr]");
  ok(!thr.hidden && chips.length === 3 && thr.querySelector("[data-thrplus]"), "All, each thread, and +: chips under the header");
  ok(chips[0].dataset.thr === "" && chips[0].getAttribute("aria-selected") === "true", "All first, and shown");
  ok(thr.innerHTML.indexOf("chbadge") < 0, "no unread counts");
  has($(".chth .chlog").innerHTML, "about the chairs", "All: every thread's messages");
  has($(".chth .chlog").innerHTML, "All quiet.", "main's too");
  eq(n1.eng.done.filter(function (m) { return m.role === "asst"; }).length, 3, "an answer turning to another thread is a message of its own");
  engPosts = [];
  click(chips[2]);
  eq(thr.querySelector('[aria-selected="true"]').dataset.thr, "deck", "a tap lights its chip at once");
  ok($(".chth .chlog").innerHTML.indexOf("All quiet.") < 0 && $(".chth .chlog").innerHTML.indexOf("And main is fine.") < 0, "only deck's shown");
  has($(".chth .chlog").innerHTML, "Chairs done.", "deck's answer shown");
  ok(!engPosts.some(function (u) { return /^POST |thread=/.test(u); }), "a filter: nothing posted, nothing fetched by thread");
  has($(".chth .chbox").placeholder, "to Deck redesign", "the box says whom it goes to");
  has($(".chth .chhdr .chstat").textContent, "thread Deck redesign", "the header says which thread");
  $(".chth .chbox").value = "how are the chairs"; $(".chth .chbox").oninput();
  var thrSend = chatSend();
  await settle(1);
  has($(".chth .chlog").innerHTML, "sending", "the bubble at once, sending");
  eq(thrSays[0] && thrSays[0].thread, "deck", "the say carries the thread");
  thrSayEnd(); await thrSend; await settle(2);
  eq(n1.eng.pending[n1.eng.pending.length - 1].state, "delivered", "delivered");
  click(thr.querySelector("[data-thr=main]")); await settle(1);
  ok($(".chth .chlog").innerHTML.indexOf("how are the chairs") < 0, "deck's bubble is not main's");
  $(".chth .chbox").value = "and main"; $(".chth .chbox").oninput();
  thrSend = chatSend(); await settle(1);
  ok(!("thread" in thrSays[1]), "to main: no thread on the say");
  thrSayEnd(); await thrSend; await settle(2);
  click(thr.querySelector("[data-thr='']")); await settle(1);
  has($(".chth .chlog").innerHTML, "how are the chairs", "All again: everything");
  // a long press: rename and close
  engThreadSheet("main");
  ok($("#chthren") && $(".chth .chsheet [data-act=thr-close]").disabled, "main's sheet: Close is off");
  chatSheet("");
  engThreadSheet("deck");
  ok(!$(".chth .chsheet [data-act=thr-close]").disabled, "another's: Close is on");
  $("#chthren").value = "The bridge";
  click($(".chth .chsheet [data-act=thr-ren]")); await settle(2);
  eq(JSON.stringify(thrOps[thrOps.length - 1]), '{"op":"rename","id":"deck","name":"The bridge"}', "Rename posts op rename");
  // +: the sheet, a new thread with its opening message, sent as any message
  click($(".chth .chthr [data-thrplus]"));
  ok($("#chthcall") && $("#chthseed"), "+ opens the sheet: a name and the opening message");
  ok(!$(".chth .chsheet [data-act=thr-fork]"), "no Branch");
  $("#chthcall").value = "Web app"; $("#chthseed").value = "Look at the console's header.";
  click($(".chth .chsheet [data-act=thr-new]"));
  ok($(".chth .chthr [data-thr=web-app]") && $(".chth .chthr [data-thr=web-app]").classList.contains("pend"), "its chip at once, pending");
  eq(n1.eng.thread, "web-app", "and picked");
  await settle(3);
  eq(JSON.stringify(thrOps[thrOps.length - 1]), '{"op":"new","id":"web-app","name":"Web app"}', "New posts op new, the id from the name");
  eq(thrSays[2] && thrSays[2].thread, "web-app", "the opening message: a say into it");
  has(thrSays[2] && thrSays[2].message, "Look at the console's header.", "with its words");
  thrSayEnd(); await settle(2);
  // the voice orders and the key
  [["number one threads", "number one threads"], ["switch to deck thread", "switch to {*} thread"], ["all threads", "all threads"],
   ["new thread web", "new thread {*}"], ["close the deck thread", "close the {*} thread"]].forEach(function (c) {
    var h = vMatch(vWords(c[0]), 0);
    eq(h && h.cmd.say, c[1], "\"" + c[0] + "\" is an order");
  });
  var sw = vMatch(vWords("switch to main thread"), 0);
  engPosts = [];
  await sw.cmd.fn(sw.arg); await settle(1);
  eq(n1.eng.thread, "main", "said: main picked, by the name said");
  ok(!engPosts.some(function (u) { return /^POST /.test(u); }), "nothing posted: a filter");
  sw = vMatch(vWords("all threads"), 0);
  await sw.cmd.fn(sw.arg); await settle(1);
  eq(n1.eng.thread, "", "all threads: the filter off");
  ok(KEYS.some(function (k) { return k.key === "U"; }), "U opens the threads sheet");
  // earlier conversations: one list
  n1.eng.st.past = [{ name: "old main", session: "p1", at: 1 }, { name: "old deck", session: "p2", at: 2, thread: "deck" }];
  chatSheet("past");
  ok($(".chth .chsheet").innerHTML.indexOf("<h4>") < 0, "Earlier conversations: one list, no groups");
  has($(".chth .chsheet").innerHTML, "old deck", "every one in it");
  chatSheet("");
  fetch = thrFetch;
  closeOv();
  fetch = engFetch;
  lsSet("lcars.deck.engkey", "");
  eng.list = null; eng.seat = null;
  chats.list = chats.list.filter(function (t) { return !t.eng; });
  eq(crewAuthor({ kind: "crew_inbox", title: "kim-c32 ← No.1: [No.1] deflake" }).name, "kim-c32",
     "a message in the crew inbox is its engineer's");
  eq(crewAuthor({ kind: "no1_log", title: "x" }).name, "number-one", "Number One's log is his");
  eq(crewAuthor({ kind: "crew_seat" }), null, "the seat's entry is nobody's in particular");
  var yeo = crewAuthor({ kind: "crew_yeoman" });
  eq(yeo.role, "crew_yeoman", "a scheduled role's report is the role's");
  ok(!yeo.name, "not an engineer's: no session is started for it");
  var yctx = crewRoleContext(yeo, { id: 77, kind: "crew_yeoman", title: "Three things due", content: "- the boiler" }, "Each night, look for untidiness.");
  has(yctx, "ship's Yeoman", "the computer is told whom it speaks as");
  has(yctx, "Each night, look for untidiness.", "with the role's brief");
  has(yctx, "#77", "and the report, by id");
  has(yctx, "- the boiler", "and its text");
  has(yctx, "change no files", "and that it edits nothing");
  has(yctx, "binds the nightly run, not this chat", "but may write to the journal in the chat");
  has(yctx, "> Yeoman created this, ", "a created entry is marked as the role's");
  has(yctx, "(from the chat)", "and says it came from the chat");
  has(yctx, "> Yeoman added, ", "added text is a quote headed as the role's");
  has(yctx, "lcars-cli append <id>", "added through the add-only append, never a set of his text");
  has(yctx, "anything in the journal, of any date", "it may read the whole journal, not only today");
  has(yctx, "--search <words>, --since/--until", "by words and by a date range");
  has(yctx, "WebSearch", "and search the web for what the journal does not hold");
  has(yctx, "Open-Meteo", "the weather as the computer's prompt allows");
  has(yctx, "A question only proposes", "a question only proposes; his yes makes it");
  has(yctx, "--title, --kind, --start, --end, --done, --value-int, --value-float, --created-at (when it was written)",
      "on his word it may set any field of an entry of his");
  has(yctx, "lcars-cli rm <id>, soft", "delete, soft and restorable");
  has(yctx, "lcars-cli restore <id>", "and restore");
  has(yctx, "always append, never set --content", "added text goes by append, never by resending his");
  has(yctx, "only when he asks for an edit of his text", "his text replaced only when he asks for an edit");
  has(yctx, "the old words and the new", "and then the answer says exactly what changed");
  has(yctx, "what it was and what it is now", "every change named with its old value, so he can ask for it back");
  has(yctx, "never write out a secret", "and no secret written out");
  has(yctx, "task_no1", "and keeps off the crew's, Number One's and the imports' kinds");
  has(yctx, "#<id>", "and names what it made so the page links it");
  eq(crewChatLabel({ kind: "crew_ops" }), "Chat with Operations Officer", "the button names them");
  eq(crewChatLabel({ kind: "flow_note" }), "", "and is not on the captain's own entries");

  console.log("-- the engineer key: a long one pasted is kept whole --");
  var longKey = "Kx9-" + Array(30).join("aB3_") + "-end";      // 120 characters
  ok(longKey.length > 100, "the key is over 100 characters (" + longKey.length + ")");
  var askedKey = engKeyAsk();
  ok(Number($("#lcIn").getAttribute("maxlength")) >= 512, "the key box takes 512 characters, not a name's 40");
  await answerPrompt("  " + longKey + "\n");
  eq(await askedKey, true, "the key is accepted");
  eq(lsGet("lcars.deck.engkey", ""), longKey, "and stored whole, trimmed of the spaces a paste brings");
  lsSet("lcars.deck.engkey", "");
  closeOv();

  console.log("-- crew reports: a row per role in the chats, unread marks, history, the voice order, the ops pin --");
  // The fixture is made here and taken out again at the end, the way the
  // new-entry test does. The live journal has crew_* rows of its own now (the
  // seat's, real reports), which would join every count below, so they are
  // set aside meanwhile and put back where they were.
  var crewReal = st.all.filter(function (e) { return isCrewKind(e.kind); });
  var crewRest = st.all.filter(function (e) { return !isCrewKind(e.kind); });
  var crewAll = st.all.slice();
  st.all.length = 0;
  Array.prototype.push.apply(st.all, crewRest);
  crewReal.forEach(function (e) { st.byId.delete(e.id); });
  var crewOv = function () { return $("#ov").classList.contains("on"); };
  closeOv();
  lsSet(CREW_READ_KEY, {});
  var crewThreadsWas = chats.list;
  chats.list = chats.list.filter(function (t) { return !t.role; });
  var crewStamp = function (agoS) { return new Date(Date.now() - agoS * 1000).toISOString().slice(0, 19).replace("T", " "); };
  var crewTop = st.all.reduce(function (m, e) { return Math.max(m, e.id); }, 0);
  var crewMk = function (n, kind, agoS, title, content) {
    return { id: crewTop + n, kind: kind, title: title, content: content, created_at_utc: crewStamp(agoS),
             updated_at_utc: crewStamp(agoS), deleted: 0 };
  };
  var crewRows = [
    crewMk(1, "crew_ops", 2 * 86400, "Ops brief, two days ago", "## Ops\n\nOld **brief**"),
    crewMk(2, "crew_yeoman", 7200, "Three things due", "- the boiler\n- the dentist"),
    crewMk(3, "crew_ship", 3600, "", "# All systems nominal\n\ndisk 41%"),
    crewMk(4, "crew_ops", 60, "Ops brief, today", "## Today\n\nTwo meetings and **one** deploy"),
    crewMk(5, "crew_cartography", 300, "Charts updated", "new waypoints"),
  ];
  crewRows.forEach(function (r) { st.all.unshift(r); st.byId.set(r.id, r); });
  var crewBy = crewReports();
  eq(crewBy.get("crew_ops").map(function (e) { return e.id; }).join(","), (crewTop + 4) + "," + (crewTop + 1),
     "a role's reports are newest first");
  eq(crewBy.size, CREW_ROLES.length + 1, "every known role is there, and a new crew_* kind too");
  eq(crewName("crew_cartography"), "cartography", "a kind the table does not know is named from itself");
  eq(crewFind("ops"), "crew_ops", "a role is found by a word of its name");
  eq(crewFind("ship's health"), "crew_ship", "by its whole name, apostrophe and all");
  eq(crewFind("health"), "crew_ship", "or by any word of it");
  eq(crewFind("crew_qa"), "crew_qa", "or by its kind, from the url");
  eq(crewFind("no such role"), "", "and nothing matches what is not a role");

  chatsList(); await settle(2);
  var repRows = function () { return Array.prototype.slice.call($("#chrows").querySelectorAll(".chrow[data-report]")); };
  eq(repRows().length, 4, "Reports in the chats: a row per role that has reported");
  var opsRow = repRows().find(function (b) { return Number(b.dataset.report) === crewTop + 4; });
  ok(opsRow, "showing its latest report");
  has(opsRow.innerHTML, "Ops brief, today", "by its headline");
  has(opsRow.innerHTML, "NEW", "an unread report is marked");
  has(repRows().find(function (b) { return Number(b.dataset.report) === crewTop + 3; }).innerHTML, "All systems nominal",
      "an untitled report is headed by its first line");
  // a swipe right on a NEW report marks it read, as on a thread
  var repReadWas = JSON.stringify(crewRead());
  var shipRow = repRows().find(function (b) { return Number(b.dataset.report) === crewTop + 3; });
  swT(shipRow, "touchstart", 30); swT(shipRow, "touchmove", 90);
  ok(shipRow.parentNode.classList.contains("dr"), "a NEW report's row drags right, showing Mark read");
  swT(shipRow, "touchend", 90);
  ok(!crewUnread("crew_ship", crewReports().get("crew_ship")[0]), "and letting go marks the report read");
  shipRow = repRows().find(function (b) { return Number(b.dataset.report) === crewTop + 3; });
  ok(shipRow.innerHTML.indexOf("NEW") < 0 && shipRow.parentNode.dataset.rd === "unread", "its row says NEW no more, and its swipe right is Mark unread");
  swDrag(shipRow, 60);
  ok(crewUnread("crew_ship", crewReports().get("crew_ship")[0]), "which makes the report NEW again");
  has(repRows().find(function (b) { return Number(b.dataset.report) === crewTop + 3; }).innerHTML, "NEW", "and says so on its row");
  lsSet(CREW_READ_KEY, JSON.parse(repReadWas));
  closeOv();
  select(crewTop + 2);
  ok(!$("#bCrewChat").hidden, "a crew report open in the reader has a Chat button");
  has($("#bCrewChat").innerHTML, "Chat with Yeoman", "naming who wrote it");
  // the phone's ⋯ sheet: the bar's other buttons, Chat only where it is
  var edMoreTiles = function () {
    openEdMore();
    var t = Array.prototype.map.call($("#dlg").querySelectorAll(".shtile"), function (x) { return x.textContent; });
    var red = $("#dlg").querySelector(".shtile.danger");
    closeOv();
    return { t: t, red: red ? red.textContent : "" };
  };
  var emt = edMoreTiles();
  ok(emt.t.some(function (x) { return x.indexOf("Chat with Yeoman") >= 0; }), "the ⋯ sheet has Chat on a crew report");
  eq(emt.t[emt.t.length - 1].indexOf("Delete") >= 0 && emt.red.indexOf("Delete") >= 0, true, "Delete last, in red");
  ok(emt.t.every(function (x) { return x.indexOf("Revert") < 0; }), "no Revert in the reader, where the bar has none");
  select(crewRest[0].id);
  ok($("#bCrewChat").hidden, "the captain's own entry has none");
  emt = edMoreTiles();
  ok(emt.t.every(function (x) { return x.indexOf("Chat") < 0; }), "nor a Chat tile in its ⋯ sheet");
  ok(emt.t.some(function (x) { return x.indexOf("Duplicate") >= 0; }) && emt.t.some(function (x) { return x.indexOf("Continue") >= 0; }), "Duplicate and Continue are there");
  setRead(false);
  ok(edMoreTiles().t.some(function (x) { return x.indexOf("Revert") >= 0; }), "Revert joins it in the editor");
  setRead(true);

  chatsList(); await settle(2);
  click(repRows().find(function (b) { return Number(b.dataset.report) === crewTop + 4; }));
  await settle(3);
  ok(st.route && st.route.v === "chats" && st.route.a[0] === "role-crew_ops", "a report row opens the role's thread, at chats/role-<kind>");
  ok(!$("#crewout") && $(".chth .chlog") && $(".chth .chbox"), "a thread like any other - log and box - not a report dialog");
  var opsReps = $(".chth .chlog").querySelectorAll(".chm.them .chrep");
  eq(opsReps.length, 2, "both its reports are the role's messages in the log");
  eq(opsReps[0].dataset.rep + "," + opsReps[1].dataset.rep, (crewTop + 1) + "," + (crewTop + 4), "oldest first, as a conversation");
  has(opsReps[1].innerHTML, "<b>one</b>", "the latest report rendered");
  has(opsReps[0].innerHTML, "Old <b>brief</b>", "the earlier one too");
  has(opsReps[1].innerHTML, "report #" + (crewTop + 4), "each with its number");
  ok(!crewUnread("crew_ops", crewBy.get("crew_ops")[0]), "reading the latest marks the role read");
  eq(chat.ctx && chat.ctx.id, crewTop + 4, "and the latest is the talk's context");
  // the captain's words fall after the reports they were said after
  var opsT = chat;
  opsT.msgs.push({ role: "user", text: "why two?", rep: crewTop + 1 }, { role: "asst", parts: [{ t: "text", s: "because" }] });
  chatDraw();
  var opsKids = Array.prototype.map.call($(".chth .chlog").children, function (k) { return k.querySelector(".chrep") ? "R" + k.querySelector(".chrep").dataset.rep : k.className.indexOf("me") >= 0 ? "me" : "them"; });
  eq(opsKids.join(" "), "R" + (crewTop + 1) + " me them R" + (crewTop + 4), "a report comes in the log where it came among the captain's words");
  opsT.msgs.length = 0;
  chatsBack();
  await settle(3);
  ok(st.route && st.route.v === "chats" && !st.route.a[0], "‹ is the list");
  ok(!repRows().some(function (b) { return Number(b.dataset.report) === crewTop + 4; }) &&
     $("#chrows").querySelector('.chrow[data-id="role-crew_ops"]').innerHTML.indexOf("NEW") < 0,
     "where the role is its thread's row now, not marked");
  ok(repRows().find(function (b) { return Number(b.dataset.report) === crewTop + 2; }).innerHTML.indexOf("NEW") >= 0,
     "and the others still are");
  eq(crewRead().crew_ops, crewTop + 4, "read is kept on this device, by the newest id read");
  var crewNew = crewMk(6, "crew_ops", 30, "Ops brief, later", "a late addendum");
  st.all.unshift(crewNew); st.byId.set(crewNew.id, crewNew); crewRows.push(crewNew);
  ok(crewUnread("crew_ops", crewReports().get("crew_ops")[0]), "a newer report makes the role unread again");
  closeOv();

  // the voice orders
  eq(vMatch(vWords("crew reports"), 0).cmd.say, "crew reports", "'crew reports' is an order");
  var crewVm = vMatch(vWords("crew report ships health"), 0);
  eq(crewVm.cmd.say, "crew report {*}", "'crew report <role>' is its own order");
  eq(crewVm.arg.text, "ships health", "with the role after it");
  eq(vMatch(vWords("number one report"), 0).cmd.say, "number one", "and Number One's report is still Number One");
  voiceHeard("computer crew reports");
  await settle(4);
  ok(crewOv() && st.route && st.route.v === "chats", "'computer, crew reports' opens the chats");
  closeOv();
  voiceHeard("computer report from the yeoman");
  await settle(4);
  ok(st.route && st.route.a[0] === "role-crew_yeoman", "'computer, report from the yeoman' opens that role's thread");
  has($(".chth .chlog").innerHTML, "the dentist", "showing its report");
  closeOv();

  // the latest ops brief, pinned over today in the day reader
  lsSet(CREW_READ_KEY, {});
  var crewToday = dayKey(crewNew.created_at_utc);
  openDay(crewToday);
  await settle(3);
  ok(!$("#daypin").hidden, "today's day view carries the ops pin");
  has($("#daypin").innerHTML, "a late addendum", "with the latest ops report");
  ok($("#daypin").innerHTML.indexOf("Two meetings") < 0, "and only the latest");
  ok($("#dayout").textContent.indexOf("a late addendum") < 0 || dayMode === "md", "the pin is not part of the day's text");
  lsDel(CREW_PIN_KEY);
  openDay(crewToday);
  await settle(3);
  ok(!/<details[^>]*\bopen\b/.test($("#daypin").innerHTML), "the pin is folded on a device that never chose");
  has($("#crewpinh").innerHTML, "Ops brief", "its summary is the one line: the flag, Ops brief");
  has($("#crewpinh").innerHTML, "NEW", "marked NEW while the brief is unread");
  ok(crewUnread("crew_ops", crewNew), "folded, the brief is not read");
  var pinDet = $("#crewpind");
  pinDet.open = true;
  pinDet.ontoggle();
  ok(lsGet(CREW_PIN_KEY, false) === true, "unfolding it is remembered on this device");
  ok(!crewUnread("crew_ops", crewNew), "and reading it there marks it read");
  ok($("#crewpinh").innerHTML.indexOf("NEW") < 0, "its NEW goes as it opens");
  ok(st.route && st.route.v === "day", "the summary's toggle stays on the day, no thread");
  openDay(crewToday);
  await settle(3);
  ok(/<details[^>]*\bopen\b/.test($("#daypin").innerHTML), "the next day reader comes up unfolded");
  voiceHeard("computer hide the ops brief");
  await settle(2);
  ok(lsGet(CREW_PIN_KEY, true) === false, "'computer, hide the ops brief' folds it");
  ok(!/<details[^>]*\bopen\b/.test($("#daypin").innerHTML), "on screen too");
  voiceHeard("computer show the ops brief");
  await settle(2);
  ok(lsGet(CREW_PIN_KEY, false) === true && /<details[^>]*\bopen\b/.test($("#daypin").innerHTML),
     "'computer, show the ops brief' unfolds it");
  lsDel(CREW_PIN_KEY);
  click($("#crewpinthr"));
  await settle(3);
  ok(st.route && st.route.a[0] === "role-crew_ops", "the pin opens the ops role's thread");
  has($(".chth .chlog").innerHTML, "a late addendum", "with the brief in its log");
  closeOv();
  openDay(dayKey(crewStamp(3 * 86400)));
  await settle(3);
  ok($("#daypin").hidden, "another day has no pin");
  closeOv();

  crewRows.forEach(function (r) { st.all.splice(st.all.indexOf(r), 1); st.byId.delete(r.id); });
  chats.list = crewThreadsWas;
  st.all.length = 0;
  Array.prototype.push.apply(st.all, crewAll);
  crewReal.forEach(function (e) { st.byId.set(e.id, e); });
  lsSet(CREW_READ_KEY, {});
  refresh();

  console.log("\n-- crew notes: @role lines, their chips and threads --");
  await (async function () {
    closeOv();
    var ntE = await plant({ kind: "personal_log", title: "Gym day", content: "Legs.\n- @yeoman log a gym session\nmid @yeoman no" });
    select(ntE.id); setRead(true); await settle(3);
    var chips = function (box) { return Array.prototype.slice.call($(box).querySelectorAll(".ntchip")); };
    eq(chips("#rd_notes").length, 1, "the reader shows a chip for the note, not for a mid-sentence @");
    eq(chips("#rd_notes")[0].dataset.s, "sending", "a saved note no thread has taken is sending");
    has($("#rd_notes").innerHTML, "log a gym session", "with its words beside it");
    ok($("#rd_content").innerHTML.indexOf("ntchip") < 0, "outside the entry's text");
    // typing a second note: the editor's strip, in the frame
    setRead(false); await settle(2);
    var c = $("#content");
    c.value = c.value + "\n@science how many runs this month";
    markDirty();
    await settle(3);
    var sci = chips("#ed_notes").find(function (b) { return b.dataset.nk === noteKey(ntE.id, "science"); });
    ok(sci && sci.dataset.s === "draft", "a note in an unsaved form says it sends when saved");
    has(sci.textContent, "sends when saved", "in words");
    c.value = c.value.replace("\n@science how many runs this month", "");
    document.body.classList.remove("dirty");
    setRead(true); await settle(2);
    // the watcher's thread: working, then answered
    var h = noteScan(ntE.content)[0].hash;
    var ntT = await plant({ kind: "crew_note", title: "Yeoman · #" + ntE.id + " Gym day", value_int: ntE.id, done_bool: 0,
      content: "status: working\nentry: #" + ntE.id + "\nrole: yeoman\n\n### Captain · 2026-10-15 23:14 · note " + h +
               "\n@yeoman log a gym session\n" });
    select(ntE.id); setRead(true); await settle(3);
    eq(chips("#rd_notes")[0].dataset.s, "working", "a thread at work shows on the chip");
    has(chips("#rd_notes")[0].textContent, "Yeoman working", "naming the role");
    ok(!crewReports().has("crew_note"), "a thread is not a crew report");
    await api("/entries/" + ntT.id, { method: "PUT", body: { done_bool: 1, content: ntT.content.replace("status: working", "status: answered") +
      "\n### Yeoman · 2026-10-15 23:15\nLogged it as **#999**.\n" } });
    await refetchInto(ntT); refresh(); await settle(3);
    eq(chips("#rd_notes")[0].dataset.s, "answered", "an answer turns the chip to answered");
    click(chips("#rd_notes")[0]); await settle(2);
    ok($("#rd_notes .ntcard"), "a tap on the chip opens the thread under the note");
    has($("#rd_notes .ntcard").innerHTML, "Logged it as <b>", "the answer rendered as markdown");
    eq(chips("#rd_notes")[0].getAttribute("aria-expanded"), "true", "and the chip says it is open");
    // a reply: sending in the tap's frame, then the captain's turn, queued
    var q = $("#rd_notes .ntq");
    q.value = "make it 45 minutes";
    click($("#rd_notes [data-nsend]"));
    has($("#rd_notes .ntcard").innerHTML, "sending", "a reply shows as sending at once");
    has($("#rd_notes .ntcard").innerHTML, "make it 45 minutes", "with its words");
    await settle(5);
    var th = noteThread(st.byId.get(ntT.id).content);
    eq(th.status, "queued", "the reply queues the thread");
    eq(th.turns.length, 3, "appended after the answer");
    ok(th.turns[2].reply && th.turns[2].text === "make it 45 minutes" && th.turns[2].who === "Captain", "as the captain's reply");
    ok($("#rd_notes .ntcard").innerHTML.indexOf("sending") < 0, "and sending is gone once it landed");
    eq(st.byId.get(ntE.id).content.indexOf("45 minutes"), -1, "the captain's entry is never written");
    // a failed one: Retry queues it again
    await api("/entries/" + ntT.id, { method: "PUT", body: { content: st.byId.get(ntT.id).content.replace("status: queued", "status: failed: budget") } });
    await refetchInto(ntT); refresh(); await settle(3);
    has($("#rd_notes .ntcard").innerHTML, "failed: budget", "a failed thread says why");
    click($("#rd_notes [data-nagain]")); await settle(5);
    eq(noteThread(st.byId.get(ntT.id).content).status, "queued", "and Retry queues it again");
    // a failed write leaves the reply where it was, with Retry
    var apiWas = api;
    api = function (path, o) { if (o && o.method === "PUT") return Promise.reject(new Error("offline")); return apiWas(path, o); };
    $("#rd_notes .ntq").value = "one more";
    click($("#rd_notes [data-nsend]")); await settle(5);
    has($("#rd_notes .ntcard").innerHTML, "not sent", "a reply that failed says so where it was");
    ok($("#rd_notes [data-nretry]"), "with Retry");
    api = apiWas;
    click($("#rd_notes [data-nretry]")); await settle(5);
    eq(noteThread(st.byId.get(ntT.id).content).turns.slice(-1)[0].text, "one more", "and Retry sends it");
    // the thread itself, opened from the list, has the same card
    select(ntT.id); setRead(true); await settle(3);
    ok($("#rd_notes .ntcard") && $("#rd_notes .ntq"), "a thread opened on its own shows its card and reply box");
    // the voice orders
    select(ntE.id); setRead(true); await settle(2);
    eq(vMatch(vWords("note to the yeoman log a gym session"), 0).cmd.say, "note to {*}", "“note to the yeoman …” is the note order");
    eq(vMatch(vWords("reply to the yeoman make it 45"), 0).cmd.say, "reply to {*}", "“reply to the yeoman …” is the reply order");
    eq(vMatch(vWords("reply to this report"), 0).cmd.say, "chat with the writer", "and “reply to this report” is still the writer's chat");
    eq(vMatch(vWords("crew notes"), 0).cmd.say, "crew notes", "“crew notes” opens them");
    noteSay("the science officer how far did I run");
    ok(/\n@science how far did I run$/.test($("#content").value), "a spoken note is a line on the open entry");
    ok(document.body.classList.contains("dirty"), "left to be saved like any typing");
    await settle(3);
    var sc = chips("#ed_notes").find(function (b) { return b.dataset.nk === noteKey(ntE.id, "science"); });
    ok(sc && sc.dataset.s === "draft", "and its chip shows in the strip");
    $("#content").value = ntE.content; document.body.classList.remove("dirty"); setRead(true);
    noteSay("the bosun do something");
    has($("#toast").textContent, "no crew role", "a role that takes no notes is refused");
    // ./notes and the Chats row
    openNotes(); await settle(3);
    eq(st.route && st.route.v, "notes", "the notes view has its url");
    var nrow = $("#ntrows").querySelector("[data-ntk]");
    ok(nrow, "a row per thread");
    has(nrow.innerHTML, "Gym day", "named by the captain's entry");
    click(nrow); await settle(3);
    ok(st.sel && st.sel.id === ntE.id && $("#rd_notes .ntcard"), "a row opens the entry with the note's thread open");
    chatsList(); await settle(2);
    ok($("#chrows").querySelector("[data-notes]"), "the Chats list has a Crew notes row");
    closeOv();
    ntState.open.clear(); ntState.pend.clear();
    unplant(ntT); unplant(ntE);
  })();

  console.log("\n-- crew notes: to Number One and the engineers --");
  await (async function () {
    closeOv();
    var chips = function (box) { return Array.prototype.slice.call($(box).querySelectorAll(".ntchip")); };
    var names = { no1: { to: "number-one", title: "Number One" },
      torres: { to: "torres-c37", title: "Lieutenant B'Elanna Torres" }, "torres-c37": { to: "torres-c37", title: "Lieutenant B'Elanna Torres" },
      obrien: { to: "obrien-c33", title: "Chief Miles O'Brien" },
      reyes: { to: "reyes-c20", title: "Chief Ana Reyes", off: 1 }, ops: { to: "ops-c1", title: "Ensign Ops" } };
    // the journal may hold the watcher's own names row (the live one does),
    // and the page takes the lowest id: note what it reads now, and point
    // the page at the planted row by id, which noteDirect keeps while it lives
    ntNames.id = 0; ntNames.at = 0;
    var baseNames = Object.keys(noteDirect()).sort().join(" ");
    var nm = await plant({ kind: "crew_note_names", title: "Crew notes: who answers an @name",
      content: "Who answers.\n\n```json\n" + JSON.stringify(names) + "\n```\n" });
    ntNames.id = nm.id; ntNames.at = 0;
    eq(Object.keys(noteDirect()).sort().join(" "), "no1 obrien reyes torres torres-c37", "the page reads the watcher's names, a crew role's left out");
    eq(noteRoles().ops, "Ops", "a crew role keeps its name");
    ok(!crewReports().has("crew_note_names"), "the names row is not a crew report");
    var pE = await plant({ kind: "personal_log", title: "Deck day",
      content: "Notes.\n@no1 check the deploy log\n- @Torres fix the chip\n@stranger nothing\nmail me at torres@x.com\n@home again" });
    eq(noteScan(pE.content).map(function (n) { return n.role + "=" + n.text; }).join(" | "),
       "no1=check the deploy log | torres=fix the chip", "@no1 and @Torres are notes; an unknown name, an email and @home are not");
    select(pE.id); setRead(true); await settle(3);
    var cs = chips("#rd_notes");
    eq(cs.length, 2, "a chip per note to a person");
    has(cs[1].textContent, "@torres", "named by the alias, lower case");
    has(cs[1].getAttribute("title"), "a note to Lieutenant B'Elanna Torres", "a person is not “the”");
    var h = noteScan(pE.content)[1].hash;
    var pT = await plant({ kind: "crew_note", title: "Lieutenant B'Elanna Torres (@torres) · #" + pE.id + " Deck day", value_int: pE.id,
      done_bool: 0, content: "status: working\nentry: #" + pE.id + "\nrole: torres\nto: torres-c37\nsent: 1\n\n### Captain · 2026-10-18 10:14 · note " + h +
      "\n@torres fix the chip\n" });
    refresh(); await settle(3);
    var tc = chips("#rd_notes").find(function (b) { return b.dataset.nk === noteKey(pE.id, "torres"); });
    ok(tc && tc.dataset.s === "working", "the thread, found by the alias in its title, sets the chip");
    has(tc.textContent, "Torres working", "naming them");
    click(tc); await settle(2);
    has($("#rd_notes .ntq").getAttribute("placeholder"), "Reply to Lieutenant B'Elanna Torres", "the reply box names them");
    await api("/entries/" + pT.id, { method: "PUT", body: { done_bool: 1, content: pT.content.replace("status: working", "status: answered") +
      "\n### Lieutenant B'Elanna Torres · 2026-10-18 10:40\nReport: fixed in 0.256.1.\n" } });
    await refetchInto(pT); refresh(); await settle(3);
    has($("#rd_notes .ntcard").innerHTML, "fixed in 0.256.1", "their answer shows under the note");
    $("#rd_notes .ntq").value = "and the deck too";
    click($("#rd_notes [data-nsend]")); await settle(5);
    var pc = st.byId.get(pT.id).content;
    has(pc, "\nto: torres-c37\nsent: 1\n", "a reply keeps the watcher's to: and sent:");
    eq(noteThread(pc).status, "queued", "and queues it");
    // the voice
    eq(noteRoleSaid(vWords("torres fix it")).join("|"), "torres|fix it", "“note to torres …” names her");
    eq(noteRoleSaid(vWords("number one check the logs")).join("|"), "no1|check the logs", "“note to number one …” names Number One");
    eq(noteRoleSaid(vWords("o'brien look at it")).join("|"), "obrien|look at it", "an apostrophe said is dropped");
    eq(noteRoleSaid(vWords("chief miles o'brien look")).join("|"), "obrien|look", "the whole title too");
    eq(noteRoleSaid(vWords("zzzznobody look")).join("|"), "|", "a name not on the list is nobody");
    // the @ popup: the short names of those on duty
    var rk = noteRank("").map(function (x) { return x.name; });
    ok(rk.indexOf("no1") >= 0 && rk.indexOf("torres") >= 0, "the popup offers Number One and the engineers");
    ok(rk.indexOf("torres-c37") < 0 && rk.indexOf("reyes") < 0, "not slugs, nor the dismissed");
    closeOv();
    ntState.open.clear(); ntState.pend.clear();
    unplant(pT); unplant(pE); unplant(nm);
    ntNames.id = 0; ntNames.at = 0;
    eq(Object.keys(noteDirect()).sort().join(" "), baseNames, "the planted row gone: the journal's own names again");
  })();

  console.log("\n-- crew notes: what the crew writes, marked, and undone --");
  await (async function () {
    closeOv();
    var who = "> Yeoman added, 2026-10-15 23:15:";
    var block = "\n\n" + who + "\n> Logged as a gym entry.\n>\n> 45 minutes.";
    var wE = await plant({ kind: "personal_log", title: "Leg day", content: "Squats.\n- @yeoman log a gym session" + block });
    var made = await plant({ kind: "gym", title: "Gym", content: "> Yeoman created this, 2026-10-15 23:15 (crew note #1, from #" + wE.id + ")\n\nLegs, 45 min." });
    var h = noteScan(wE.content)[0].hash;
    var ans = "Logged it.\n\n**Changes**\n- created #" + made.id + " (gym)\n- added to #" + wE.id + ": Logged as a gym entry.\n" +
      "```crew-changes\n" + JSON.stringify({ op: "create", id: made.id, kind: "gym", title: "Gym" }) + "\n" +
      JSON.stringify({ op: "append", id: wE.id, text: block }) + "\n```";
    var wT = await plant({ kind: "crew_note", title: "Yeoman · #" + wE.id + " Leg day", value_int: wE.id, done_bool: 1,
      content: "status: answered\nentry: #" + wE.id + "\nrole: yeoman\n\n### Captain · 2026-10-15 23:14 · note " + h +
               "\n@yeoman log a gym session\n\n### Yeoman · 2026-10-15 23:15\n" + ans + "\n" });
    select(wE.id); setRead(true); await settle(3);
    var heads = $("#rd_content").querySelectorAll("blockquote.crewhead");
    eq(heads.length, 1, "the crew's block in the reader is headed as the crew's");
    eq($("#rd_content").querySelectorAll("blockquote.crewadd").length, 4, "every quoted line of it drawn as the crew's");
    eq(mdRender("> a quote of mine\n> still mine").indexOf("crewadd"), -1, "the captain's own quotes are not");
    eq(mdRender(who + "\n> x\n\n> mine again").split("crewadd").length - 1, 2, "a blank line ends the crew's block");
    select(made.id); setRead(true); await settle(2);
    has($("#rd_meta").innerHTML, "created by the Yeoman", "an entry the crew made says so beside its kind");
    select(wE.id); setRead(false); await settle(3);
    has($("#ed_notes").innerHTML, "Yeoman added", "the editor's strip names the crew's block, which the text box cannot colour");
    setRead(true); await settle(2);
    ntState.open.add(noteKey(wE.id, "yeoman")); notesPaint();
    var undos = $("#rd_notes").querySelectorAll("[data-nundo]");
    eq(undos.length, 2, "the answer's changes each have an Undo");
    ok($("#rd_notes .ntcard").innerHTML.indexOf("crew-changes") < 0, "and the record behind them is not shown as text");
    // Undo the append: the block out, his words as they were
    click(undos[1]);
    has($("#rd_notes .ntcard").innerHTML, "undoing", "Undo shows it is working in the tap's frame");
    await settle(6);
    eq(st.byId.get(wE.id).content, "Squats.\n- @yeoman log a gym session", "Undo of an append takes exactly that block out");
    var recs = noteChanges(noteThread(st.byId.get(wT.id).content).turns[1].text).recs;
    ok(recs[1].undone && !recs[0].undone, "and marks that change undone in the thread");
    has($("#rd_notes .ntcard").innerHTML, "undone", "which the card says");
    // Undo the create: deleted, as the captain
    click($("#rd_notes [data-nundo]")); await settle(6);
    ok(st.byId.get(made.id).deleted, "Undo of a create deletes the entry");
    // an append the captain has since changed is not cut
    await api("/entries/" + wT.id, { method: "PUT", body: { content: st.byId.get(wT.id).content.replace(/,"undone":"[^"]*"/g, "") } });
    await refetchInto(wT);
    await api("/entries/" + wE.id, { method: "PUT", body: { content: "Squats.\n- @yeoman log a gym session" + block.replace("45 minutes", "50 minutes") } });
    await refetchInto(st.byId.get(wE.id)); refresh(); await settle(3);
    var u11 = Array.prototype.find.call($("#rd_notes").querySelectorAll("[data-nundo]"), function (b) { return b.dataset.nundo === wT.id + ":1:1"; });
    ok(u11, "the change is undoable again once its mark is gone");
    if (u11) click(u11);
    await settle(6);
    eq(st.byId.get(wE.id).content, "Squats.\n- @yeoman log a gym session" + block.replace("45 minutes", "50 minutes"), "a block he has edited is left alone");
    has($("#rd_notes .ntcard").innerHTML, "changed since", "and the card says why it was not undone");
    // the voice
    eq(vMatch(vWords("undo the crew's changes"), 0).cmd.say, "undo the crew's changes", "“undo the crew's changes” is its order");
    eq(vMatch(vWords("undo"), 0).cmd.say, "undo", "and “undo” is still the voice's own undo");
    await api("/entries/" + wE.id, { method: "PUT", body: { content: "Squats.\n- @yeoman log a gym session" + block } });
    await refetchInto(st.byId.get(wE.id)); refresh();
    noteUndoSaid(); await settle(8);
    eq(st.byId.get(wE.id).content, "Squats.\n- @yeoman log a gym session", "said aloud, it undoes the newest changes still standing");
    ntState.open.clear(); ntState.undoErr.clear();
    unplant(wT); unplant(made); unplant(wE);
  })();

  console.log("-- crew notes: a title the yeoman set, undone --");
  await (async function () {
    closeOv();
    var tE = await plant({ kind: "personal_log", title: "Leg day", content: "Squats, 5x5.\n- @yeoman title this" });
    var h = noteScan(tE.content)[0].hash;
    var rec = { op: "title", id: tE.id, old_title: "Gym day", title: "Leg day" };
    var tT = await plant({ kind: "crew_note", title: "Yeoman · #" + tE.id + " Leg day", value_int: tE.id, done_bool: 1,
      content: "status: answered\nentry: #" + tE.id + "\nrole: yeoman\n\n### Captain · 2026-10-15 23:14 · note " + h +
               "\n@yeoman title this\n\n### Yeoman · 2026-10-15 23:15\nTitled it.\n\n**Changes**\n- titled #" + tE.id +
               ": \u201cGym day\u201d \u2192 \u201cLeg day\u201d\n```crew-changes\n" + JSON.stringify(rec) + "\n```\n" });
    select(tE.id); setRead(true); await settle(3);
    ntState.open.add(noteKey(tE.id, "yeoman")); notesPaint();
    var u = $("#rd_notes [data-nundo]");
    ok(u, "a title change has an Undo");
    has($("#rd_notes .ntundo").innerHTML, "titled #" + tE.id, "named as a title change");
    // he has retitled it since: left alone, and the card says so
    await api("/entries/" + tE.id, { method: "PUT", body: { title: "Squats" } });
    await refetchInto(st.byId.get(tE.id)); refresh(); await settle(3);
    click($("#rd_notes [data-nundo]"));
    has($("#rd_notes .ntcard").innerHTML, "undoing", "Undo shows it is working in the tap's frame");
    await settle(6);
    eq(st.byId.get(tE.id).title, "Squats", "a title he has changed since is left alone");
    has($("#rd_notes .ntcard").innerHTML, "title has moved on", "and the card says the title has moved on");
    ok(!noteChanges(noteThread(st.byId.get(tT.id).content).turns[1].text).recs[0].undone, "the change is not marked undone");
    ok($("#rd_notes [data-nundo]"), "and Undo is still offered");
    // still the yeoman's title: the old one put back, his text untouched
    await api("/entries/" + tE.id, { method: "PUT", body: { title: "Leg day" } });
    await refetchInto(st.byId.get(tE.id)); ntState.undoErr.clear(); refresh(); await settle(3);
    click($("#rd_notes [data-nundo]")); await settle(6);
    eq(st.byId.get(tE.id).title, "Gym day", "Undo of a title puts the old one back");
    eq(st.byId.get(tE.id).content, "Squats, 5x5.\n- @yeoman title this", "and leaves the text as it was");
    ok(noteChanges(noteThread(st.byId.get(tT.id).content).turns[1].text).recs[0].undone, "and marks the change undone");
    has($("#rd_notes .ntcard").innerHTML, "undone", "which the card says");
    eq(NOTE_HINTS.yeoman.indexOf("tidies"), -1, "the yeoman's hint no longer says it tidies");
    has(NOTE_HINTS.yeoman, "titles", "it says it titles entries");
    ntState.open.clear(); ntState.undoErr.clear();
    unplant(tT); unplant(tE);
  })();

  console.log("-- crew notes: an open entry the yeoman closed, undone --");
  await (async function () {
    closeOv();
    var sE = await plant({ kind: "sleep", title: "Sleep", content: "- @yeoman close it, I woke at 7:05",
                           start_date: "2026-10-14 20:10:00", end_date: "2026-10-15 04:05:00" });
    var h = noteScan(sE.content)[0].hash;
    var rec = { op: "end", id: sE.id, old_end: "", end: "2026-10-15 04:05:00", at: "2026-10-15 07:05" };
    var sT = await plant({ kind: "crew_note", title: "Yeoman · #" + sE.id + " Sleep", value_int: sE.id, done_bool: 1,
      content: "status: answered\nentry: #" + sE.id + "\nrole: yeoman\n\n### Captain · 2026-10-15 07:20 · note " + h +
               "\n@yeoman close it, I woke at 7:05\n\n### Yeoman · 2026-10-15 07:21\nClosed.\n\n**Changes**\n- closed #" +
               sE.id + " at 2026-10-15 07:05\n```crew-changes\n" + JSON.stringify(rec) + "\n```\n" });
    select(sE.id); setRead(true); await settle(3);
    ntState.open.add(noteKey(sE.id, "yeoman")); notesPaint();
    ok($("#rd_notes [data-nundo]"), "a closed entry has an Undo");
    has($("#rd_notes .ntundo").innerHTML, "closed #" + sE.id + " at 07:05", "named as closed, at his time");
    // he moved the end since: left alone, and the card says so
    await api("/entries/" + sE.id, { method: "PUT", body: { end_date: "2026-10-15 04:30:00" } });
    await refetchInto(st.byId.get(sE.id)); refresh(); await settle(3);
    click($("#rd_notes [data-nundo]")); await settle(6);
    eq(st.byId.get(sE.id).end_date, "2026-10-15 04:30:00", "an end he has changed since is left alone");
    has($("#rd_notes .ntcard").innerHTML, "end has moved on", "and the card says the end has moved on");
    ok(!noteChanges(noteThread(st.byId.get(sT.id).content).turns[1].text).recs[0].undone, "the change is not marked undone");
    // still the yeoman's end: taken off, the entry open again, the rest as it was
    await api("/entries/" + sE.id, { method: "PUT", body: { end_date: "2026-10-15 04:05:00" } });
    await refetchInto(st.byId.get(sE.id)); ntState.undoErr.clear(); refresh(); await settle(3);
    click($("#rd_notes [data-nundo]")); await settle(6);
    ok(!st.byId.get(sE.id).end_date, "Undo of an end leaves the entry open again");
    eq(st.byId.get(sE.id).start_date, "2026-10-14 20:10:00", "its start as it was");
    ok(noteChanges(noteThread(st.byId.get(sT.id).content).turns[1].text).recs[0].undone, "and marks the change undone");
    has(NOTE_HINTS.yeoman, "closes an open one", "the yeoman's hint says it closes entries");
    ntState.open.clear(); ntState.undoErr.clear();
    unplant(sT); unplant(sE);
  })();

  console.log("-- crew notes: a set, a replaced text, a delete and a restore, undone --");
  await (async function () {
    closeOv();
    var gE = await plant({ kind: "child_sleep", title: "Sleep", content: "Legs, squats.\n- @yeoman fix it", value_int: 8,
                           start_date: "2026-10-14 20:20:00" });
    var dE = await plant({ kind: "gym", title: "Dup", content: "x" });
    var rE = await plant({ kind: "gym", title: "Twin", content: "y" });
    await api("/entries/" + dE.id, { method: "DELETE" }); await refetchInto(st.byId.get(dE.id));
    var h = noteScan(gE.content)[0].hash;
    var recs = [
      { op: "set", id: gE.id, old: { kind: "sleep", start_date: "2026-10-14 20:10:00", value_int: 7 },
        new: { kind: "child_sleep", start_date: "2026-10-14 20:20:00", value_int: 8 } },
      { op: "replace", id: gE.id, old_text: "Legs, squatts.\n- @yeoman fix it", text: "Legs, squats.\n- @yeoman fix it" },
      { op: "delete", id: dE.id, kind: "gym", title: "Dup" },
      { op: "restore", id: rE.id, kind: "gym", title: "Twin" }];
    var gT = await plant({ kind: "crew_note", title: "Yeoman · #" + gE.id + " Sleep", value_int: gE.id, done_bool: 1,
      content: "status: answered\nentry: #" + gE.id + "\nrole: yeoman\n\n### Captain · 2026-10-15 07:20 · note " + h +
               "\n@yeoman fix it\n\n### Yeoman · 2026-10-15 07:21\nDone.\n\n**Changes**\n- set #" + gE.id +
               "\n```crew-changes\n" + recs.map(function (r) { return JSON.stringify(r); }).join("\n") + "\n```\n" });
    select(gE.id); setRead(true); await settle(3);
    ntState.open.add(noteKey(gE.id, "yeoman")); notesPaint();
    var undos = $("#rd_notes").querySelectorAll("[data-nundo]");
    eq(undos.length, 4, "each new change has its Undo");
    var card = $("#rd_notes .ntcard").innerHTML;
    has(card, "changed #" + gE.id, "a set is named as changed");
    has(card, "edited the text of #" + gE.id, "a replace as an edit of the text");
    has(card, "deleted #" + dE.id, "a delete as deleted");
    has(card, "restored #" + rE.id, "a restore as restored");
    // the text Undo first: the set's Undo would move the stamp, not the text
    var undoBtn = function (i) {
      return [].slice.call($("#rd_notes").querySelectorAll("[data-nundo]")).filter(function (x) {
        return x.getAttribute("data-nundo") === gT.id + ":1:" + i; })[0];
    };
    var rec = function (i) { return noteChanges(noteThread(st.byId.get(gT.id).content).turns[1].text).recs[i]; };
    click(undoBtn(1)); await settle(6);
    eq(st.byId.get(gE.id).content, "Legs, squatts.\n- @yeoman fix it", "Undo of a replace puts his text back");
    ok(rec(1).undone, "and marks it undone");
    // he changed the kind since: the set is left alone, and says which field
    await api("/entries/" + gE.id, { method: "PUT", body: { kind: "sleep_nap" } });
    await refetchInto(st.byId.get(gE.id)); refresh(); await settle(3);
    click(undoBtn(0)); await settle(6);
    eq(st.byId.get(gE.id).kind, "sleep_nap", "a set whose field he changed since is left alone");
    has($("#rd_notes .ntcard").innerHTML, "kind moved on", "and the card names the field");
    ok(!rec(0).undone, "the set is not marked undone");
    await api("/entries/" + gE.id, { method: "PUT", body: { kind: "child_sleep" } });
    await refetchInto(st.byId.get(gE.id)); ntState.undoErr.clear(); refresh(); await settle(3);
    click(undoBtn(0)); await settle(6);
    var g = st.byId.get(gE.id);
    eq([g.kind, g.start_date, Number(g.value_int)].join("|"), "sleep|2026-10-14 20:10:00|7", "Undo of a set puts each field back");
    eq(g.title, "Sleep", "and touches no other");
    ok(rec(0).undone, "and marks it undone");
    click(undoBtn(2)); await settle(6);
    ok(!(await api("/entries/" + dE.id)).deleted, "Undo of a delete restores the entry");
    click(undoBtn(3)); await settle(6);
    ok((await api("/entries/" + rE.id)).deleted, "Undo of a restore deletes it again");
    ok(rec(2).undone && rec(3).undone, "both marked undone");
    has(NOTE_HINTS.yeoman, "edits, deletes or restores", "the yeoman's hint says it edits");
    ntState.open.clear(); ntState.undoErr.clear();
    unplant(gT); unplant(gE); unplant(dE); unplant(rE);
  })();


  console.log("-- the yeoman's proposals: Apply, Undo, Dismiss, a refusal, the ledger --");
  await (async function () {
    closeOv();
    var a = await plant({ kind: "personal_log", title: "Breakfast", content: "eggs" });
    var b = await plant({ kind: "personal_log", title: "start", content: "start" });
    var c = await plant({ kind: "task", title: "Call the bank at 10:00", content: "" });
    var d = await plant({ kind: "personal_log", title: "HTTP Entry", content: "Squats, 5x5" });
    var moved = await plant({ kind: "personal_log", title: "Lunch", content: "soup" });
    var text = "### Duplicates\n- #1 and #" + a.id + ": same breakfast; keep #1, delete #" + a.id + ". Say \"delete " + a.id + "\" and \"delete " + moved.id + "\".\n" +
      "- prose that says delete #" + a.id + ". and then goes on, with no change at its end\n" +
      "### Kinds\n- #" + b.id + " is personal_log but its body is start. Set kind of " + b.id + " to child_sleep.\n" +
      "### Dates\n- #" + c.id + " names 10:00 but has no due date; set due of " + c.id + " to 2026-10-16T07:00:00Z\n" +
      "### Titles\n- #" + d.id + " is untitled. Say \"title " + d.id + " to Leg day\".\n" +
      "- #999999 is a stray. delete 999999\n" +
      "- not a shape: merge " + a.id + " into " + b.id + "\n\n```\ndelete 4242\n```\n---\n*crew.py yeoman*";
    var rep = await plant({ kind: "crew_yeoman", title: "Hygiene", content: text });
    var ps = yeoProposals(text);
    eq(ps.map(function (p) { return p.change; }).join(" | "),
       "delete " + a.id + " | delete " + moved.id + " | set kind of " + b.id + " to child_sleep | set due of " + c.id + " to 2026-10-16 07:00:00 | title " + d.id + " to Leg day | delete 999999",
       "the four shapes, at a line's end or in quotes, each once; prose, other orders and code are not");
    select(rep.id); setRead(true); await settle(3);
    var box = $("#rd_yeo");
    ok(box && !box.hidden, "the reader of a yeoman report has the proposals box");
    eq(box.querySelectorAll("[data-yact=apply]").length, 6, "an Apply per proposal");
    eq(box.querySelectorAll("[data-yact=dismiss]").length, 6, "and a Dismiss");
    function btn(i, act) { return Array.prototype.find.call(box.querySelectorAll("[data-yact]"), function (x) { return x.dataset.y === i + "@" + rep.id && x.dataset.yact === act; }); }
    // delete, soft, and its Undo
    click(btn(0, "apply"));
    has(box.innerHTML, "applying", "Apply says it is working in the tap's frame");
    await settle(6);
    ok(st.byId.get(a.id).deleted, "Apply of a delete deletes the row (soft)");
    var led = yeoLedger(st.byId.get(rep.id).content).get("delete " + a.id);
    ok(led && led.applied && led.seen, "the ledger in the report records it applied");
    has(st.byId.get(rep.id).content, "```yeoman-ledger\n", "in a yeoman-ledger fence");
    eq($("#rd_content").innerHTML.indexOf("yeoman-ledger"), -1, "which the reader does not draw");
    has($("#toast").textContent, "applied: delete " + a.id, "the toast says what was done");
    ok($("#toast .tact") && $("#toast .tact").textContent === "Undo", "with an Undo");
    click($("#toast .tact")); await settle(6);
    ok(!st.byId.get(a.id).deleted, "Undo restores the row");
    led = yeoLedger(st.byId.get(rep.id).content).get("delete " + a.id);
    ok(led.applied && led.undone, "and the ledger says undone");
    eq(yeoState(led), "undone", "the proposal open again");
    ok(btn(0, "apply"), "Apply offered again");
    // set kind
    click(btn(2, "apply")); await settle(6);
    eq(st.byId.get(b.id).kind, "child_sleep", "Apply of a kind sets the kind");
    eq(yeoLedger(st.byId.get(rep.id).content).get("set kind of " + b.id + " to child_sleep").old.kind, "personal_log", "the old kind kept for the Undo");
    ok(btn(2, "undo"), "an applied proposal has Undo in its row");
    click(btn(2, "undo")); await settle(6);
    eq(st.byId.get(b.id).kind, "personal_log", "Undo puts the old kind back");
    // set due
    click(btn(3, "apply")); await settle(6);
    eq(st.byId.get(c.id).start_date, "2026-10-16 07:00:00", "Apply of a due date sets start_date");
    click($("#toast .tact")); await settle(6);
    eq(st.byId.get(c.id).start_date || "", "", "Undo puts the old date back");
    // title, and an Undo refused once he has retitled it
    click(btn(4, "apply")); await settle(6);
    eq(st.byId.get(d.id).title, "Leg day", "Apply of a title sets it");
    await api("/entries/" + d.id, { method: "PUT", body: { title: "Squats" } });
    await refetchInto(st.byId.get(d.id));
    click(btn(4, "undo")); await settle(6);
    eq(st.byId.get(d.id).title, "Squats", "a title changed since is left alone by Undo");
    has(box.innerHTML, "moved on", "and the row says why");
    // refusals: changed after the report, gone
    await api("/entries/" + moved.id, { method: "PUT", body: { content: "soup and bread" } });
    await refetchInto(st.byId.get(moved.id));
    click(btn(1, "apply")); await settle(6);
    ok(!st.byId.get(moved.id).deleted, "a row changed after the report is not touched");
    has(box.innerHTML, "changed after the report", "and its row says so");
    ok(!yeoState(yeoLedger(st.byId.get(rep.id).content).get("delete " + moved.id)), "nothing recorded for it");
    click(btn(5, "apply")); await settle(6);
    has(box.innerHTML, "gone from the journal", "a row that is gone is refused, saying so");
    // dismiss
    click(btn(5, "dismiss"));
    has(box.innerHTML, "dismissing", "Dismiss shows in the tap's frame");
    await settle(6);
    ok(yeoLedger(st.byId.get(rep.id).content).get("delete 999999").dismissed, "Dismiss is recorded in the ledger");
    has(box.querySelectorAll(".yeorow")[5].innerHTML, "dismissed", "and painted from it");
    ok(!btn(5, "apply"), "a dismissed proposal has no Apply");
    // the voice
    eq(vMatch(vWords("apply proposal 3"), 0).cmd.say, "apply proposal {n}", "“apply proposal 3” is its order");
    eq(vMatch(vWords("dismiss proposal 2"), 0).cmd.say, "dismiss proposal {n}", "“dismiss proposal 2” is its order");
    yeoSaid("apply", 3); await settle(6);
    eq(st.byId.get(b.id).kind, "child_sleep", "said aloud, it applies the third");
    // the bubble in the role's chat has the same box
    var m = crewLogMsg({ repMsgs: new Map() }, st.byId.get(rep.id));
    var html = crewLogHtml(m);
    has(html, "data-yact", "the report's bubble in its chat has the buttons");
    eq(html.indexOf("yeoman-ledger"), -1, "and not the ledger");
    // any other kind has none
    eq(yeoHtml(a), "", "an entry of another kind has no proposals box");
    ys.err.clear();
    [rep, a, b, c, d, moved].forEach(unplant);
  })();

  console.log("-- a scheduled report's one write: Undo, as the notes card has --");
  await (async function () {
    closeOv();
    var who = "> Science officer added, 2026-10-19 04:42:";
    var block = "\n\n" + who + "\n> - [[Oct 18th, 2026]] week 12 to 18 Oct 2026\n>   - apa\n> - words so far: 61";
    var page = await plant({ kind: "page", title: "Ana's words", content: "- words ana knows:" + block });
    var text = "### Ana's words\n- apa; 61 so far. Added the week to #" + page.id + ".\n\n**Changes**\n- added to #" + page.id +
      ": - [[Oct 18th, 2026]] week 12 to 18 Oct 2026\n```crew-changes\n" + JSON.stringify({ op: "append", id: page.id, text: block }) +
      "\n```\n\n---\n*crew.py science · sonnet*";
    var rep = await plant({ kind: "crew_science", title: "Week in numbers", content: text });
    select(rep.id); setRead(true); await settle(3);
    var box = $("#rd_yeo");
    ok(box && !box.hidden && box.querySelector("[data-rundo]"), "the reader of a report that wrote has an Undo");
    has(box.innerHTML, "added to #" + page.id, "naming the change");
    eq($("#rd_content").innerHTML.indexOf("crew-changes"), -1, "and does not draw the record behind it");
    var html = crewLogHtml(crewLogMsg({ repMsgs: new Map() }, st.byId.get(rep.id)));
    has(html, "data-rundo", "the report's bubble in its chat has the Undo too");
    eq(html.indexOf("crew-changes"), -1, "and not the fence");
    eq(crewRoleContext({ title: "Science", role: "science" }, st.byId.get(rep.id), null).indexOf("crew-changes"), -1,
       "nor does the role's chat context");
    // the captain has written under the block since: only the block goes
    await api("/entries/" + page.id, { method: "PUT", body: { content: "- words ana knows:" + block + "\n- sounds: ham" } });
    await refetchInto(st.byId.get(page.id));
    click(box.querySelector("[data-rundo]"));
    has(box.innerHTML, "undoing", "Undo shows it is working in the tap's frame");
    await settle(6);
    eq(st.byId.get(page.id).content, "- words ana knows:\n- sounds: ham", "Undo takes exactly the block out, his words as they are");
    ok(noteChanges(st.byId.get(rep.id).content).recs[0].undone, "and marks it undone in the report's fence");
    has(box.innerHTML, "undone", "which the box says");
    ok(!box.querySelector("[data-rundo]"), "with no Undo left");
    // an edited block is left alone, and the box says why
    await api("/entries/" + rep.id, { method: "PUT", body: { content: text } });
    await refetchInto(st.byId.get(rep.id));
    await api("/entries/" + page.id, { method: "PUT", body: { content: "- words ana knows:" + block.replace("apa", "apă") } });
    await refetchInto(st.byId.get(page.id)); refresh(); await settle(3);
    click(box.querySelector("[data-rundo]")); await settle(6);
    has(st.byId.get(page.id).content, "apă", "a block he has edited is not cut");
    has(box.innerHTML, "changed since", "and the box says why");
    ok(!noteChanges(st.byId.get(rep.id).content).recs[0].undone, "nothing marked undone");
    // the voice: "undo the crew's changes" with the report open
    await api("/entries/" + page.id, { method: "PUT", body: { content: "- words ana knows:" + block } });
    await refetchInto(st.byId.get(page.id)); ys.err.clear(); refresh();
    noteUndoSaid(); await settle(8);
    eq(st.byId.get(page.id).content, "- words ana knows:", "said aloud with the report open, it undoes the report's change");
    eq(repChangesHtml(page), "", "an entry that is not a crew report has no box");
    ys.err.clear();
    [rep, page].forEach(unplant);
  })();
  console.log("-- the header's clock: shown at once, ticking each second, still while hidden --");
  (function () {
    var DReal = Date, fake = new DReal(2026, 9, 13, 9, 59, 58, 400).getTime();
    // Date with its clock in the test's hand: no arguments (and Date.now) read `fake`
    class FakeDate extends DReal {
      constructor() { if (arguments.length) super(...arguments); else super(fake); }
      static now() { return fake; }
    }
    globalThis.Date = FakeDate;
    try {
      clockTick();
      eq($("#clock").textContent, "09:59:58", "the clock shows the local time at once");
      ok(!!clk.t, "and waits for the next second");
      fake += 610; runTimers(610);
      eq($("#clock").textContent, "09:59:59", "the clock advances a second");
      fake += 1000; runTimers(1000);
      eq($("#clock").textContent, "10:00:00", "and rolls the minute and the hour");
      eq($("#clock .s").textContent, ":00", "the seconds are their own span (a narrow phone hides them)");
      document.hidden = true; clockTick();
      ok(!clk.t, "a hidden page keeps no clock timer");
      fake += 5000; runTimers(5000);
      eq($("#clock").textContent, "10:00:00", "and the clock does not tick while hidden");
      document.hidden = false; clockTick();
      eq($("#clock").textContent, "10:00:05", "shown again, it catches up at once");
      ok(!!clk.t, "and ticks again");
      eq(vMatch(vWords("what time is it"), 0).cmd.fn.toString().indexOf("clockSay") >= 0, true,
         "\u201cwhat time is it\u201d is an order that says the time");
      eq(vMatch(vWords("what's the time"), 0).cmd.say, "what time is it", "\u201cwhat's the time\u201d is the same order");
      clockSay();
      has($("#toast").textContent, "the time is 10:00", "the order shows the time");
    } finally {
      globalThis.Date = DReal;
      delete document.hidden;
      clockTick();
    }
  })();

  console.log("\n-- tidy dictation: a diff to accept, as the captain --");
  await (async function () {
    closeOv(); hideToast();
    var raw = "Porsche now playing on the basketball field with ana jurses.\n";
    var tidied = "Porsche is now playing on the basketball field, with Ana's courses.\n";
    var tE = await plant({ kind: "personal_log", title: "Evening", content: raw });
    var sse = function (o) { return "data: " + JSON.stringify(o) + "\n\n"; };
    var realFetch = fetch, asks = [], held = [];
    var reply = function (text) {
      return { ok: true, status: 200, text: function () { return Promise.resolve(
        sse({ type: "system", subtype: "init", session_id: "s-tidy" }) +
        sse({ type: "assistant", message: { content: [{ type: "text", text: text }] } }) +
        sse({ type: "result", session_id: "s-tidy" }) + sse({ type: "lcars_exit", code: 0 })); } };
    };
    // a /chat answer waits until the test lets it go, so the working state can be seen
    fetch = function (url, o) {
      if (String(url).indexOf("/chat") < 0) return realFetch.apply(this, arguments);
      asks.push(JSON.parse(o.body));
      return new Promise(function (res) { held.push(res); });
    };
    try {
      select(tE.id); setRead(true); await settle(3);
      ok($("#bTidy").style.display !== "none", "an open entry offers Tidy dictation");
      openEdMore();
      ok(Array.prototype.some.call($("#dlg").querySelectorAll(".shtile"), function (t) { return t.textContent.indexOf("Tidy dictation") >= 0; }),
         "and so does the editor's ⋯ sheet");
      closeOv();
      eq(tidyDiffHtml("Porsche now playing on the basketball field", "Porsche is now playing on the basketball field."),
         "Porsche <ins>is </ins>now playing on the basketball field<ins>.</ins>", "the diff: what comes in green, the shared parts plain");
      eq(tidyDiffHtml("with ana jurses", "with Ana's courses"),
         "with <del>ana</del><ins>Ana's</ins> <del>jurses</del><ins>courses</ins>", "a word replaced: struck in red, then the new one");
      eq(tidyDiffHtml("a <b>", "a <b>"), "a &lt;b&gt;", "the text is escaped");

      // the tap: working, with Cancel, in the same frame
      var p = tidyDictation();
      has($("#tdline").textContent, "Tidying #" + tE.id, "the panel says it is working at once");
      ok($("#tdCancel") && $("#ov").classList.contains("on"), "with Cancel");
      ok($("#bTidy").classList.contains("busy"), "and the button is busy");
      eq(asks.length, 1, "the text goes to the computer, as the Ask chat sends it");
      has(asks[0].message, "Fix the speech-to-text errors", "with the fixed instruction");
      has(asks[0].message, "BEGIN\n" + raw + "\nEND", "and the text, whole");
      eq(asks[0].session_id, "", "in a session of its own");
      held.shift()(reply(tidied.trim()));
      await p; await settle(3);
      ok(!$("#bTidy").classList.contains("busy"), "the button lets go when the answer lands");
      has($("#tddiff").innerHTML, "<ins>Ana's</ins>", "the answer is shown as a diff");
      ok($("#tdOk") && $("#tdNo"), "with Accept and Discard");
      eq(st.byId.get(tE.id).content, raw, "nothing changed yet");
      var puts = DBLOG.length;
      click($("#tdOk")); await settle(8);
      eq($("#content").value, tidied, "Accept puts the tidied text in the editor, the trailing newline kept");
      eq(dbFind(tE.id).content, tidied, "and saves it");
      ok(DBLOG.slice(puts).some(function (l) { return l.indexOf("PUT") === 0; }), "as an edit (PUT)");
      ok(!document.body.classList.contains("dirty"), "the form is clean after the save");
      has($("#toast").textContent, "tidied #" + tE.id, "a toast says so");
      var tUndo = $("#toast").querySelector("button");
      ok(tUndo && tUndo.textContent === "Undo", "with an Undo");
      click(tUndo); await settle(8);
      eq(dbFind(tE.id).content, raw, "Undo puts the text back, saved");
      eq($("#content").value, raw, "in the editor too");

      // Discard leaves the text alone
      p = tidyDictation();
      held.shift()(reply(tidied));
      await p; await settle(3);
      puts = DBLOG.length;
      click($("#tdNo")); await settle(3);
      ok(!$("#ov").classList.contains("on"), "Discard closes the panel");
      eq($("#content").value, raw, "and leaves the text");
      ok(!DBLOG.slice(puts).some(function (l) { return l.indexOf("PUT") === 0; }), "nothing is written");

      // the entry changed while the request was out
      setRead(false);
      p = tidyDictation();
      input($("#content"), raw + "and then some");
      held.shift()(reply(tidied));
      await p; await settle(3);
      has($("#tdline").textContent, "changed while the computer was tidying it", "an entry changed meanwhile: said so");
      ok(!$("#tddiff"), "and the answer is discarded");
      eq($("#content").value, raw + "and then some", "the captain's typing stands");
      closeOv(); setForm(st.byId.get(tE.id)); setClean();

      // Cancel: the panel goes, and a late answer is dropped
      p = tidyDictation();
      click($("#tdCancel")); await settle(2);
      ok(!$("#bTidy").classList.contains("busy") && !tidyRun, "Cancel lets go at once");
      held.shift()(reply(tidied));
      await p; await settle(3);
      ok(!$("#ov").classList.contains("on"), "and the answer that comes after shows nothing");
      eq($("#content").value, raw, "nor changes anything");

      // an error, on the same line
      fetch = function (url, o) {
        if (String(url).indexOf("/chat") < 0) return realFetch.apply(this, arguments);
        asks.push(JSON.parse(o.body));
        return Promise.resolve({ ok: false, status: 503, statusText: "Unavailable",
          json: function () { return Promise.resolve({ error: "no model configured" }); } });
      };
      await tidyDictation(); await settle(2);
      has($("#tdline").textContent, "Not tidied: no model configured", "a failure is said on the panel's line");
      ok($("#tdline").classList.contains("bad") && $("#tdRetry"), "in red, with Retry");
      closeOv();

      // too short: nothing is sent
      var n = asks.length;
      setRead(false); input($("#content"), "too short"); 
      tidyDictation();
      eq(asks.length, n, "under 20 characters, nothing is sent");
      has($("#toast").textContent, "nothing to tidy", "and it says why");
      setForm(st.byId.get(tE.id)); setClean();

      ["tidy the dictation", "clean up the dictation", "fix the dictation"].forEach(function (x) {
        var hit = vMatch(vWords(x), 0);
        eq(hit && hit.cmd.say, "tidy the dictation", "“" + x + "” is its order");
      });
    } finally {
      fetch = realFetch;
      tidyRun = null; tidyBusy(false);
      closeOv(); hideToast(); setClean();
      unplant(tE);
    }
  })();

  console.log("\n-- the app's own updates: the server's version, the mark, Update --");
  await (async function () {
    var realFetchV = updFetchVersion, realShell = updShell, realReload = updReload;
    var served = APP_VERSION, asked = 0, reloads = 0, shell = 0, shellErr = null;
    updFetchVersion = function () { asked++; return Promise.resolve(served); };
    updShell = function () { shell++; return shellErr ? Promise.reject(new Error(shellErr)) : Promise.resolve(); };
    updReload = function () { reloads++; };
    try {
      eq(verCmp("0.184.10", "0.184.9"), 1, "0.184.10 is newer than 0.184.9 (numbers, not text)");
      eq(verCmp("0.185.0", "0.184.99"), 1, "a minor beats any patch");
      eq(verCmp("1.0.0", "0.999.0"), 1, "a major beats any minor");
      eq(verCmp("0.184.3", "0.184.3"), 0, "the same version");
      eq(verCmp("0.183.9", "0.184.0"), -1, "older");
      eq(verIn('<meta charset="utf-8">\n<script>\nconst APP_VERSION = "0.190.2";'), "0.190.2",
         "the version is read off the file's first lines");
      eq(verIn("<!doctype html><html>"), "", "and nothing from a file without it");
      lsDel("lcars.updTold"); lsDel("lcars.updLater");
      upd.server = ""; upd.at = 0; upd.failed = ""; upd.busy = "";

      await updCheck(false); await settle(2);
      eq(asked, 1, "a check asks the server once");
      eq(upd.server, APP_VERSION, "the server's version is kept");
      ok(!$("#appVer").classList.contains("upd"), "the same version: no mark");
      eq($("#appVer").textContent, "v" + APP_VERSION, "the header's version is this page's");

      // at most once a minute: a foreground inside the minute is put off, not dropped
      upd.at = Date.now();
      updCheckSoon(); updCheckSoon(); runTimers(1000); await settle(1);
      eq(asked, 1, "a second check inside the minute waits");
      runTimers(UPD_GAP); await settle(2);
      eq(asked, 2, "and is made once the minute is up, once");

      navigator.onLine = false;
      upd.at = 0; hideToast();
      await updCheck(false); await settle(1);
      eq(asked, 2, "offline, the server is not asked");
      ok(!$("#toast").classList.contains("on"), "and nothing is said");
      delete navigator.onLine;

      var parts = APP_VERSION.split(".");
      served = parts[0] + "." + (Number(parts[1]) + 1) + ".0";
      upd.at = 0;
      await updCheck(false); await settle(2);
      ok($("#appVer").classList.contains("upd"), "a newer version marks the header's version");
      eq($("#appVer").textContent, "v" + APP_VERSION, "whose text stays this page's version");
      eq($("#appVer").getAttribute("role"), "button", "and makes it a button");
      has($("#toast").textContent, "v" + served + " is on the server", "told once, in a toast");
      eq($("#toast").querySelector(".tact") && $("#toast").querySelector(".tact").textContent, "Update",
         "which carries Update");
      hideToast();
      upd.at = 0;
      await updCheck(false); await settle(2);
      ok(!$("#toast").classList.contains("on"), "the same version is not told twice");

      click($("#appVer")); await settle(1);
      ok($("#ov").classList.contains("on") && $("#c_upd"), "a tap on the marked version opens the settings");
      var row = function () { return $("#c_upd").textContent; };
      var btn = function (a) { return $("#c_upd").querySelector('[data-act="' + a + '"]'); };
      has(row(), "v" + APP_VERSION + " · server v" + served, "the row says both versions");
      eq(btn("update").textContent, "Update to v" + served, "Update to the server's version");
      ok(btn("check") && btn("reload") && btn("later"), "with Check now, Reload and Later");
      eq(document.activeElement, btn("update"), "focused on Update");

      click(btn("later")); await settle(1);
      ok(!$("#appVer").classList.contains("upd"), "Later takes the mark down");
      ok(!btn("later"), "and Later itself");
      ok(btn("update"), "Update stays in the settings");
      served = parts[0] + "." + (Number(parts[1]) + 2) + ".0";
      upd.at = 0;
      await updCheck(false); await settle(2);
      ok($("#appVer").classList.contains("upd"), "a newer one again marks again");
      hideToast();

      // Check now: the button shows it, the answer is said
      upd.at = Date.now();
      click(btn("check")); await settle(2);
      eq(asked, 6, "Check now asks at once, inside the minute");
      has($("#toast").textContent, "v" + served + " is on the server", "and says what it found");

      // a failed shell fetch: no reload, said on the row and with Retry
      shellErr = "index.html answered 502";
      click(btn("update")); await settle(4);
      eq(reloads, 0, "a failed update does not reload");
      has(row(), "index.html answered 502", "the row says why");
      eq(btn("update").textContent, "Retry update", "and Update becomes Retry");
      has($("#toast").textContent, "not updated: index.html answered 502", "the toast says so");
      eq($("#toast").querySelector(".tact") && $("#toast").querySelector(".tact").textContent, "Retry", "with Retry");

      // an open edit is saved on the way out, then one reload
      shellErr = null;
      var live = st.all.filter(function (e) { return !e.deleted; })[2];
      select(live.id); setRead(false);
      $("#e_head").value = "updated on the way " + live.id;
      markDirty();
      var before = DBLOG.length;
      var p = updApply(false);
      eq(btn("update").textContent, "Updating…", "Update shows Updating… at once");
      ok(btn("update").disabled && btn("reload").disabled, "and nothing else starts meanwhile");
      await p; await settle(6);
      ok(DBLOG.slice(before).some(function (l) { return l.indexOf("PUT") === 0; }), "the edit was saved first");
      eq(dbFind(live.id).title, "updated on the way " + live.id, "on the server");
      eq(lsGet("lcars.draft", null), null, "so nothing is left as a draft");
      eq(reloads, 1, "then the page reloads once");
      eq(btn("update").textContent, "Reloading…", "saying Reloading…");
      ok(upd.leaving, "and the reload is not asked about (beforeunload)");

      // Reload: the shell again, with no update waiting
      upd.leaving = false; upd.busy = ""; updPaint();
      reloads = 0;
      click(btn("reload")); await settle(4);
      eq(shell, 3, "Reload fetches the shell even with no update");
      eq(reloads, 1, "and reloads once");

      ["check for updates", "update the app", "reload the app"].forEach(function (x) {
        var hit = vMatch(vWords(x), 0);
        eq(hit && hit.cmd.say, x, "\u201c" + x + "\u201d is an order");
      });
      eq(vMatch(vWords("reload"), 0).cmd.say, "reload", "\u201creload\u201d is still the journal's");
    } finally {
      updFetchVersion = realFetchV; updShell = realShell; updReload = realReload;
      upd.leaving = false; upd.busy = ""; upd.failed = ""; upd.server = "";
      lsDel("lcars.updTold"); lsDel("lcars.updLater");
      updPaint(); setClean(); closeOv(); hideToast();
    }
  })();

  console.log("\n-- files in the chat (docs/design/chat-dock.md Part 2) --");
  await (async function () {
    closeOv(); runTimers(); await settle(1);
    var hadRaf = typeof requestAnimationFrame !== "undefined";
    if (!hadRaf) globalThis.requestAnimationFrame = function (f) { return setTimeout(f, 16); };
    var hadURL = typeof URL !== "undefined", urls = 0;
    if (!hadURL) globalThis.URL = { createObjectURL: function () { return "blob:t/" + (++urls); }, revokeObjectURL: function () {} };
    // the upload stood in for: each call held until the test answers it
    var ups = [], realSend = chatMediaSend, n = 0;
    chatMediaSend = function (blob, name, onprog) {
      var c = { blob: blob, name: name, onprog: onprog, aborted: false };
      var p = new Promise(function (res, rej) { c.res = res; c.rej = rej; });
      p.abort = function () { c.aborted = true; var e = new Error("dropped"); e.abort = true; c.rej(e); };
      c.ok = function () { n++; c.res({ path: "media/chat/2026/10/" + name.replace(/\W+/g, "-") + "-" + n + ".bin", url: "/media/chat/x", name: name,
                                        mime: blob.type, bytes: blob.size }); };
      c.fail = function (http) { var e = new Error(http === 413 ? "too big" : "500 boom"); e.http = http; c.rej(e); };
      c.net = function () { var e = new Error("network error"); e.net = true; c.rej(e); };
      ups.push(c);
      return p;
    };
    var sse = function (o) { return "data: " + JSON.stringify(o) + "\n\n"; }, bodies = [], fFetch = fetch;
    fetch = function (url, o) {
      if (!/\/chat$/.test(String(url))) return fFetch.apply(this, arguments);
      bodies.push(JSON.parse(o.body));
      var body = sse({ type: "system", subtype: "init", session_id: "s-f" }) +
        sse({ type: "stream_event", event: { type: "content_block_start", content_block: { type: "text", text: "A fine picture." } } }) +
        sse({ type: "result", session_id: "s-f" }) + sse({ type: "lcars_exit", code: 0 });
      return Promise.resolve({ ok: true, status: 200, text: function () { return Promise.resolve(body); } });
    };
    var blob = function (name, type, size) { return { name: name, type: type, size: size }; };
    try {
      openChat();
      var m = chatFull(), t = chatShown();
      t.msgs = []; t.sid = null; t.fileSeen = false; chatDraw();
      ok(chatTakesFiles(t) && !m.plus.hidden, "the computer's thread takes files: + shows");
      ok(!chatTakesFiles({ nav: 5 }) && !chatTakesFiles({ person: { key: "x" } }) && chatTakesFiles({ eng: { name: "x" } }) && chatTakesFiles({ role: { kind: "k" } }),
         "a navigator and a deck persona do not; an engineer and a role do");
      ok(m.pick && m.pick.getAttribute("multiple") !== null && !m.pick.getAttribute("accept"), "the picker takes several files, of any type");
      ok(m.plus.nextElementSibling === m.pick && m.pick.nextElementSibling === m.box, "+ sits before the box in the composer");

      // the chips: picked, each uploading at once; too big never sent
      chatFileAdd(t, [blob("shot.png", "image/png", 2000), blob("a-long-name-for-the-plan-of-the-week.pdf", "application/pdf", 1200000),
                      blob("huge.mov", "video/quicktime", 40 * 1048576)]);
      await settle(2);
      eq(m.files.querySelectorAll(".chfchip").length, 3, "a chip per file, in the order added");
      eq(ups.length, 2, "the uploads start when the chips appear, the too-big one never");
      ok(m.files.querySelector(".chfchip.img img"), "a picture's chip is its thumbnail, from the file itself");
      has(m.files.innerHTML, "…", "a long name loses its middle");
      has(m.files.innerHTML, "week.pdf", "keeping its extension");
      ok(m.files.querySelector(".chfchip.big"), "the too-big one red");
      has(m.files.innerHTML, "too big", "saying why");
      ok(m.send.disabled, "a too-big chip blocks Send");
      has(m.send.title, "remove huge.mov", "Send says what to remove");
      has(m.files.innerHTML, "the computer sees images", "the first time, a line on what the other side does with files");
      ups[0].onprog(50); await settle(2);
      has(m.files.innerHTML, "width:50%", "the chip's bar shows the upload's progress");
      click(m.files.querySelector(".chfchip.big [data-fx]")); await settle(1);
      eq(t.att.length, 2, "× drops a chip at once");
      ok(!m.send.disabled && !m.box.value.trim(), "Send is enabled with files and no words");
      eq(m.send.textContent, "Send", "and says Send");
      ups[0].ok(); ups[1].fail(500); await settle(2);
      eq(t.att[0].state, "done", "an upload answered: done");
      ok(t.att[0].path.indexOf("media/chat/") === 0 && t.att[0].url.indexOf("/media/chat/") > 0, "with the server's path, and a URL on the page's base");
      ok(m.files.querySelector(".chfchip.failed [data-fre]"), "a failed upload: red, with Retry");
      click(m.files.querySelector("[data-fre]")); await settle(1);
      eq(ups.length, 3, "Retry uploads it again");
      ok(t.att[1].state === "up", "uploading again");

      // sent while one is still uploading: the bubble at once, the message when it is up
      m.box.value = "look at these"; m.box.oninput();
      chatSend(); await settle(2);
      var u = t.msgs[t.msgs.length - 1];
      ok(u && u.role === "user" && u.files && u.files.length === 2, "sent: the bubble at once, the files in it");
      eq(t.att.length, 0, "the chips gone from above the box");
      eq(bodies.length, 0, "the message waits for its last file");
      has(m.log.innerHTML, "uploading 2 of 2", "the bubble says sending… · uploading 2 of 2");
      var k1 = chatMsgKey(u);
      ups[2].onprog(80); await settle(1);
      ok(chatMsgKey(u) !== k1, "a file's progress changes the message's key (the keyed log redraws it)");
      ups[2].ok(); await settle(8);
      eq(bodies.length, 1, "the last file up: the message goes");
      eq(JSON.stringify(bodies[0].attachments.map(function (a) { return Object.keys(a).join(","); })), JSON.stringify(["path,name,mime,bytes", "path,name,mime,bytes"]),
         "carrying attachments, each {path, name, mime, bytes} as the upload answered");
      eq(bodies[0].message, "look at these", "beside the words");
      ok(Object.keys(bodies[0]).indexOf("attachments") < Object.keys(bodies[0]).indexOf("message"), "before the message (the server finds keys by substring)");
      ok(m.log.querySelector(".chimgs.n1 .chimg") && m.log.querySelector(".chftile"), "the bubble: the picture, and a tile for the PDF");
      ok(m.log.querySelector('.chftile a[download]') && m.log.querySelector('.chftile a[target="_blank"]'), "the tile downloads, and opens in a new tab");

      // files alone, and a file that fails after Send: the words kept with Retry
      chatFileAdd(t, [blob("only.png", "image/png", 10)]); await settle(1);
      chatSend(); await settle(1);
      ups[3].ok(); await settle(8);
      eq(bodies.length, 2, "a message of files alone goes");
      eq(bodies[1].message, "", "with no words");
      chatFileAdd(t, [blob("notes.txt", "text/plain", 10)]); await settle(1);
      m.box.value = "read this"; chatSend(); await settle(1);
      ups[4].fail(500); await settle(4);
      u = t.msgs[t.msgs.length - 1];
      eq(u.state, "failed", "a file that cannot upload: the message not sent");
      has(m.log.innerHTML, "notes.txt did not upload", "the bubble says which");
      has(m.log.innerHTML, "read this", "its words kept in the bubble");
      ok(m.log.querySelector("[data-retry]"), "with Retry");
      click(m.log.querySelector("[data-retry]")); await settle(2);
      eq(ups.length, 6, "Retry uploads the file again");
      ups[5].ok(); await settle(8);
      eq(bodies.length, 3, "and then sends");
      eq(bodies[2].message + "|" + bodies[2].attachments[0].name, "read this|notes.txt", "the words and the file");

      // offline: the chip waits for the network, and goes when it is back
      var wasOff = ob.offline;
      ob.offline = true;
      chatFileAdd(t, [blob("later.pdf", "application/pdf", 10), blob("later2.pdf", "application/pdf", 10)]); await settle(1);
      eq(ups.length, 6, "offline: nothing is sent");
      ok(m.files.querySelectorAll(".chfchip.offline").length === 2, "the chips dim");
      has(m.files.innerHTML, "waits for the network", "saying they wait for the network");
      chatSend(); await settle(2);
      has(m.log.innerHTML, "goes when back", "sent offline: the bubble says it goes when back");
      obBack(); await settle(2);
      eq(ups.length, 8, "the link back: they upload");
      eq(ups[6].name + "," + ups[7].name, "later.pdf,later2.pdf", "in order");
      ups[6].ok(); ups[7].ok(); await settle(8);
      eq(bodies.length, 4, "and the message goes");
      ob.offline = wasOff;

      // the bubble's pictures: one at its aspect, 2-4 a grid, more three and +n
      var pics = function (k) { var fs = []; for (var i = 0; i < k; i++) fs.push({ name: "p" + i + ".jpg", mime: "image/jpeg", state: "done", url: "/media/chat/p" + i + ".jpg", path: "media/chat/p" + i + ".jpg" }); return { role: "user", text: "", files: fs }; };
      var cells = function (h) { return h.split('class="chimg ').length - 1; };
      var h1 = chatFilesHtml(pics(1), 0), h2 = chatFilesHtml(pics(2), 0), h4 = chatFilesHtml(pics(4), 0), h6 = chatFilesHtml(pics(6), 0);
      ok(/chimgs n1/.test(h1) && cells(h1) === 1, "one picture: alone");
      ok(/chimgs n2/.test(h2) && cells(h2) === 2, "two: a grid of two");
      ok(/chimgs n4/.test(h4) && cells(h4) === 4 && h4.indexOf("chimore") < 0, "four: a grid of four");
      ok(/chimgs n4/.test(h6) && cells(h6) === 4, "six: four squares");
      has(h6, ">+3<", "the last a +3");
      has(h1, 'loading="lazy"', "a picture is loaded lazily");
      var p1 = pics(1); p1.files[0].w = 800; p1.files[0].h = 400;
      has(chatFilesHtml(p1, 0), "--r:2.0000", "its own aspect when known, so its box is there before it loads");
      // the lightbox from a bubble, ← → through its pictures, Esc
      t.msgs.push(pics(3)); chatDraw(); await settle(1);
      var lbs = m.log.querySelectorAll("[data-lb]"), lb = lbs[lbs.length - 2];
      click(lb); await settle(1);
      ok(media.light && $("#mlight"), "a tap on a picture: the lightbox");
      eq(media.lightList && media.lightList.length, 3, "holding the bubble's three");
      eq(media.lightK, 1, "at the one tapped");
      var wk = function (k) { var ev = { key: k, preventDefault: function () {}, stopImmediatePropagation: function () {} };
        (window._on.keydown || []).forEach(function (f) { f(ev); }); };
      wk("ArrowRight");
      eq(media.lightK, 2, "→ the next");
      wk("Escape");
      ok(!media.light && !$("#mlight"), "Esc closes it");

      // voice: drop the attachments, show the picture
      eq(vMatch(vWords("drop the attachments"), 0).cmd.say, "drop the attachments", "“drop the attachments” is an order");
      eq(vMatch(vWords("clear the attachments"), 0).cmd.say, "drop the attachments", "and “clear the attachments”");
      eq(vMatch(vWords("show the image"), 0).cmd.say, "show the picture", "“show the image” is the picture, not show only");
      eq(vMatch(vWords("show only runs"), 0).cmd.say, "show only {*}", "“show only …” is still the filter");
      chatFileAdd(t, [blob("x.png", "image/png", 10), blob("y.txt", "text/plain", 10)]); await settle(1);
      vMatch(vWords("drop the attachments"), 0).cmd.fn(); await settle(1);
      ok(!t.att.length && m.files.hidden, "drop the attachments: every chip of the box gone");
      ok(ups[ups.length - 1].aborted && ups[ups.length - 2].aborted, "their uploads stopped");
      vMatch(vWords("show the picture"), 0).cmd.fn(); await settle(1);
      ok(media.light && media.lightK === media.lightList.length - 1, "show the picture: the newest in the lightbox");
      mediaUnlight();

      // kept: no blobs, no object URLs; one not yet up is lost
      chatFileAdd(t, [blob("z.png", "image/png", 10)]); await settle(1);
      m.box.value = "z"; chatSend(); await settle(1);
      chatSave();
      var kept = lsGet("lcars.chats", {}).list.find(function (x) { return x.id === t.id; });
      var km = kept.msgs[kept.msgs.length - 1];
      ok(km.files && km.files[0].name === "z.png" && !km.files[0].thumb, "saved without the object URL");
      eq(km.files[0].state + "|" + km.state, "lost|failed", "a file not yet up is lost to a reload, and its message failed");
      ups[ups.length - 1].ok(); await settle(8);

      // an engineer's transcript: the file lines drawn as files
      var fx = chatFilesFrom("Fix this\n\nAttached file: /mnt/nas/media/chat/2026/10/shot-0a1b2c3d.png (Shot 1, final.png, image/png, 1.2 MB) - Read that path; without the media mount, fetch x");
      eq(fx.text, "Fix this", "the words without the file lines");
      eq(fx.files.length + "|" + fx.files[0].path + "|" + fx.files[0].name + "|" + fx.files[0].mime + "|" + fx.files[0].size,
         "1|media/chat/2026/10/shot-0a1b2c3d.png|Shot 1, final.png|image/png|1.2 MB", "the file: its path under the root, name, type and size");
      eq(chatFilesFrom("Attached file: /r/media/chat/../../etc/x (a, b/c, 1 KB)").files.length, 0, "never a path with ..");
      var et = engThread("ftest", "Lt. Files");
      engFold(et.eng, [{ r: "me", t: "See\n\nAttached file: /r/media/chat/2026/10/a-1.png (a.png, image/png, 3 KB)" }]);
      var em = et.eng.done[et.eng.done.length - 1];
      ok(em.files && em.files[0].url.indexOf("/media/chat/2026/10/a-1.png") > 0 && em.text === "See", "engFold: the captain's message with its file");
      chats.list.splice(chats.list.indexOf(et), 1);

      // answers' pictures: a bare media line, never a stranger's, never mid-sentence
      has(chatMd("/media/chat/2026/10/plot-1.png"), "mdmedia image", "a bare media path on a line of its own: the picture");
      has(chatMd("Here:\n\n`media/chat/2026/10/plot-1.png`"), "mdmedia image", "in backticks too");
      has(chatMd(mediaBase() + "/media/chat/2026/10/plot-1.png"), "mdmedia image", "the page's own media URL");
      ok(chatMd("saved to /media/chat/2026/10/plot-1.png for you").indexOf("<img") < 0, "a path mid-sentence stays words");
      ok(chatMd("https://elsewhere.example/media/x.png").indexOf("<img") < 0, "another site's bare URL is never fetched");
      ok(chatMd("/tmp/plot.png").indexOf("<img") < 0, "a path outside the media root neither");
      ok(chatMd("/media/chat/2026/10/notes.pdf").indexOf("<img") < 0, "a document's path is not a picture");
      ok(mdRender("/media/chat/2026/10/plot-1.png").indexOf("<img") < 0, "an entry's text is drawn as before");
      has(chatMd("![plot](media/chat/2026/10/plot-1.png)"), "mdmedia image", "markdown images as before");
      var rc = reportCards("Published: [Weekly review](https://host.example/media/reports/2026/10/weekly-ab12cd34.html)");
      has(rc, "rpcard", "an engineer's published report: a card");
      has(rc, "Weekly review", "with its title");
      has(rc, "View", "and View (the report viewer)");
      // a dock window's live answer: a finished line with a picture is settled, not redrawn every frame
      var cut = dockLiveCut("Look:\n![p](media/chat/a.png)\nand then more");
      eq(cut, "Look:\n![p](media/chat/a.png)".length, "a picture's finished line is a cut in a dock window's stream");
      eq(dockLiveCut("one\n\ntwo ![p](media/chat/a.p"), 3, "a half-written one stays in the tail");
    } finally {
      chatMediaSend = realSend; fetch = fFetch;
      if (!hadRaf) delete globalThis.requestAnimationFrame;
      if (!hadURL) delete globalThis.URL;
      mediaUnlight(); closeOv(); runTimers(); await settle(1);
    }
  })();

  /* ---------- the public demo (demo/static.js, docs/design/demo-static.md) ----------
     Its server in the page, run in a sandbox: its own URL, Response,
     storage and IndexedDB stand-ins, journal.json a small fixture built a
     few days ago. test/demo_static.py runs the built folder in Chromium. */
  console.log("\n-- the public demo: its server in the page --");
  await (async function () {
    function TURL(u, base) {
      if (!/^[a-z]+:\/\//.test(u)) {
        var b = new TURL(base), dir = b.pathname.replace(/[^\/]*$/, "");
        u = b.origin + (u === "." ? dir : u.charAt(0) === "/" ? u : dir + u);
      }
      var m = /^([a-z]+:)\/\/([^\/?#]+)([^?#]*)(\?[^#]*)?(#.*)?$/.exec(u);
      this.origin = m[1] + "//" + m[2]; this.pathname = m[3] || "/"; this.search = m[4] || "";
      this.searchParams = new URLSearchParams(this.search.slice(1));
      this.href = this.origin + this.pathname + this.search + (m[5] || "");
    }
    function TResp(body, init) {
      this.status = (init && init.status) || 200; this.ok = this.status < 400;
      this.headers = (init && init.headers) || {}; this._b = body;
    }
    TResp.prototype.text = function () { return Promise.resolve(this._b); };
    TResp.prototype.json = function () { return Promise.resolve(JSON.parse(this._b)); };
    function TStore() { this.m = {}; }
    TStore.prototype.getItem = function (k) { return Object.prototype.hasOwnProperty.call(this.m, k) ? this.m[k] : null; };
    TStore.prototype.setItem = function (k, v) { this.m[k] = String(v); };
    TStore.prototype.removeItem = function (k) { delete this.m[k]; };
    TStore.prototype.key = function (i) { return Object.keys(this.m)[i] || null; };
    Object.defineProperty(TStore.prototype, "length", { get: function () { return Object.keys(this.m).length; } });
    var dropped = [], net = [];
    var IDB = { deleteDatabase: function (n) { dropped.push(n); var q = {}; Promise.resolve().then(function () { if (q.onsuccess) q.onsuccess(); }); return q; } };
    var day = function (n) { var d = new Date(Date.now() - n * 864e5); return d.getFullYear() + "-" + ("0" + (d.getMonth() + 1)).slice(-2) + "-" + ("0" + d.getDate()).slice(-2); };
    var row = function (id, kind, title, at, extra) {
      return Object.assign({ id: id, kind: kind, title: title, content: "- " + title + "\n", value_int: 0, value_float: 0,
        done_bool: 0, deleted: 0, created_at_utc: at, last_modified_at_utc: at }, extra || {});
    };
    var FX = { built: day(3), media: [{ id: 1, entry_id: 12, path: "media/demo/e12-1.png", mime: "image/png", bytes: 9, name: "p.png", created_at_utc: "2026-01-02 09:00:00" }],
      embeddings: { model: "demo-bag-of-words", dim: 4, mark: "2026-01-03 00:00:00", rows: [[12, "AQIDBA=="]] },
      rows: [row(10, "personal_log", "Old", "2026-01-01 08:00:00"), row(11, "task", "Open task", "2026-01-02 08:00:00"),
             row(12, "page", "LCARS UI", "2026-01-03 08:00:00"), row(13, "personal_log", "Gone", "2026-01-03 09:00:00", { deleted: 1 })] };
    // one load of the page: static.js run over a storage that outlives it, as a reload does
    function boot(store) {
      var W = { fetch: function (u) {
        net.push(String(u));
        return Promise.resolve(/journal\.json$/.test(u) ? new TResp(JSON.stringify(FX)) : new TResp("png", { status: 200 }));
      } };
      var D = { currentScript: { src: "https://demo.example/lcars-demo/demo.js" } };
      new Function("window", "document", "location", "localStorage", "indexedDB", "URL", "Response", "Headers", "DOMException",
                   "URLSearchParams", "TextEncoder", DEMO_STATIC_SRC)(
        W, D, { href: "https://demo.example/lcars-demo/index.html" }, store, IDB, TURL, TResp, undefined, Error,
        URLSearchParams, TextEncoder);
      W.call = function (method, path, body, headers) {
        return W.fetch(W.LCARS_DEMO.base + path, { method: method, headers: headers || {}, body: body ? JSON.stringify(body) : undefined })
          .then(function (r) { return r.text().then(function (t) { return { code: r.status, data: /^[\[{]/.test(t) ? JSON.parse(t) : t }; }); });
      };
      return W;
    }
    var store = new TStore();
    var W = boot(store);
    eq(W.LCARS_DEMO.base, "https://demo.example/lcars-demo/api", "the API is the folder's api, beside demo.js");
    var r = await W.call("GET", "/entries?deleted=all&order=id&dir=desc&limit=10&content=0");
    eq(r.data.map(function (x) { return x.id; }).join(","), "13,12,11,10", "GET /entries: the rows, id-desc, the deleted with deleted=all");
    ok(r.data.every(function (x) { return !("content" in x); }), "content=0 leaves the bodies out");
    eq(r.data[1].created_at_utc, "2026-01-06 08:00:00", "built three days ago: every date moved on three days");
    eq((await W.call("GET", "/entries?limit=10")).data.length, 3, "the deleted row only when asked for");
    eq((await W.call("GET", "/dump?deleted=all&kind=task")).data.map(function (x) { return x.title; }).join(), "Open task", "/dump with a kind");
    eq((await W.call("GET", "/stats?deleted=all")).data.count, 4, "/stats counts them");
    eq((await W.call("GET", "/entries?limit=0")).code, 400, "a limit out of range is the server's 400");

    var put = await W.call("PUT", "/entries/11", { content: "- DONE the edit\n", done_bool: 1 });
    eq(put.code, 200, "PUT answers as the server does");
    var e11 = (await W.call("GET", "/entries/11")).data;
    ok(e11.content === "- DONE the edit\n" && e11.done_bool === 1 && e11.content_length === 16, "the edit is the row now, its length counted");
    ok(e11.last_modified_at_utc > "2026-01-06 08:00:00", "and modified now, so the mirror's delta sync finds it");
    var mod = (await W.call("GET", "/entries?deleted=all&modified_since=" + encodeURIComponent(e11.last_modified_at_utc) + "&limit=100")).data;
    eq(mod.map(function (x) { return x.id; }).join(), "11", "modified_since: the edited row alone");
    var c1 = await W.call("POST", "/entries", { kind: "idea", title: "", content: "x" }, { "Idempotency-Key": "k1" });
    var c2 = await W.call("POST", "/entries", { kind: "idea", content: "x" }, { "Idempotency-Key": "k1" });
    ok(c1.code === 201 && c1.data.id === 14 && c2.data.id === 14, "POST: a new id above the rest, and a retried key is the first's answer");
    eq((await W.call("GET", "/entries/14")).data.title, "HTTP Entry", "an empty title is the server's placeholder");
    await W.call("DELETE", "/entries/10");
    eq((await W.call("GET", "/entries/10")).data.deleted, 1, "DELETE is the soft delete");
    eq((await W.call("PUT", "/entries/10", { restore: true })).code, 200, "and a restore");
    eq((await W.call("GET", "/entries/10")).data.deleted, 0, "brings it back");
    eq((await W.call("GET", "/entries/99")).code, 404, "an id it does not have is a 404");

    // what needs a server: a note, in the shape each caller reads
    var chatR = await W.call("POST", "/chat", { message: "hello" });
    ok(/made-up journal/.test(chatR.data) && /"type":"lcars_exit"/.test(chatR.data), "/chat: a reply saying why, then the turn's end");
    var em = await W.call("POST", "/embed", { text: "x" });
    ok(em.code === 503 && /^Search by meaning needs the journal's server/.test(em.data.error), "/embed: a 503 saying what needs the server");
    eq((await W.call("POST", "/entries/12/media", null)).code, 503, "an upload too");
    eq(JSON.stringify((await W.call("GET", "/engineer")).data), '{"engineers":[]}', "no engineers");
    eq((await W.call("GET", "/events")).code, 404, "/events is quiet (the page stops asking at a 404)");
    eq((await W.call("GET", "/entries/12/media")).data[0].path, "media/demo/e12-1.png", "an entry's pictures");
    var eb = (await W.call("GET", "/embeddings")).data;
    ok(eb.dim === 4 && eb.rows.length === 1 && eb.live === 4, "the star chart's vectors, from the build");
    eq((await W.call("GET", "/embeddings?since=" + encodeURIComponent(eb.mark))).data.rows.length, 0, "and nothing new since its mark");
    var n0 = net.length;
    await W.fetch("https://demo.example/lcars-demo/api/media/demo/e12-1.png");
    await W.fetch("https://elsewhere.example/x.js");
    eq(net.length - n0, 2, "a picture under api/media/ and anything off the API go to the network");
    var n1 = net.length;
    await W.call("GET", "/entries/12");
    eq(net.length, n1, "the API itself never does");

    // a reload: the edits are this browser's, the day the same
    W = boot(store);
    eq((await W.call("GET", "/entries/11")).data.content, "- DONE the edit\n", "after a reload the edit is still there");
    eq((await W.call("GET", "/entries/14")).data.kind, "idea", "and the new entry");
    eq((await W.call("POST", "/entries", { title: "next" })).data.id, 15, "ids go on from there");
    eq(dropped.length, 0, "the same day: the mirror is kept");
    // another day: the dates move, so the mirror is emptied before the page opens it
    store.setItem("lcars.demo.shift", "2");
    W = boot(store);
    await W.call("GET", "/stats");
    eq(dropped.join(), "lcars,lcars-outbox,lcars-stars", "a new day empties the mirror, the outbox and the star cache");

    // Reset: the fixture back
    store.setItem("lcars.cfg", "{}");
    store.setItem("other.app", "kept");
    dropped = [];
    await W.LCARS_DEMO.reset();
    ok(store.getItem("lcars.demo.edits") === null && store.getItem("lcars.cfg") === null, "Reset empties the demo's edits and the pages' settings");
    eq(store.getItem("other.app"), "kept", "and nothing that is not LCARS's");
    eq(dropped.join(), "lcars,lcars-outbox,lcars-stars", "and the mirror, the outbox and the star cache");
    W = boot(store);
    eq((await W.call("GET", "/entries/11")).data.content, "- Open task\n", "the made-up journal is back as built");
    eq((await W.call("GET", "/entries/14")).code, 404, "without the visitor's entries");
  })().catch(function (e) { TEST.fails.push("demo server threw: " + e); console.log("  FAIL demo server threw: " + e + "\n" + (e && e.stack)); });

  console.log("-- the public demo: nothing of it outside the demo --");
  ok(DEMO === false && !window.LCARS_DEMO, "this page is not the demo");
  var toastWas = $("#toast").textContent;
  ok(featureOff("media", null, "Attaching a file") === false && $("#toast").textContent === toastWas, "featureOff: no note, the feature goes on");

  console.log("-- the server's features (GET /features) --");
  // the parsing: what is kept, what is dropped
  eq(featParse(null), null, "featParse: nothing is null");
  eq(featParse({ features: "x" }), null, "a features that is not a list is null");
  eq(featParse([]), null, "a bare list is null");
  var fp = featParse({ features: [
    { name: "maps", on: false, needs: ["LCARS_MAPY_KEY"], note: "Set the key." },
    { name: "media", on: true, needs: [], note: "kept" },
    { name: "", on: true }, { on: false, name: 3 }, { name: "speech", on: "no" }, null,
    { name: "strava", on: false, needs: ["A", 4, "", null, "B"] },
    { name: "warp_drive", on: false, needs: "LCARS_WARP", note: 7 },
  ] });
  eq([...fp.keys()].join(), "maps,media,strava,warp_drive", "a feature with no name or no boolean on is dropped; an unknown name kept");
  eq(fp.get("maps").needs.join() + "|" + fp.get("maps").note, "LCARS_MAPY_KEY|Set the key.", "needs and note as sent");
  eq(fp.get("strava").needs.join(), "A,B", "needs: only the non-empty strings");
  ok(fp.get("warp_drive").needs.length === 0 && fp.get("warp_drive").note === "", "a needs or note of another type is none");
  eq(featParse({ features: [] }).size, 0, "an empty list is an empty map, not null");

  // an older server (404) and a limited login (403): everything on, and said
  var FALL = ["media", "media_ffmpeg", "computer", "navigator", "maps", "transcription", "speech", "embeddings",
              "caldav", "strava", "logseq", "engineers", "number_one", "crew", "reports"];
  FEATURES = null;
  await featLoad(true);
  ok(feat.map === null && /older/.test(feat.err), "404: no map, an older server (" + feat.err + ")");
  ok(featureOff("media") === false && featNote("maps") === "", "404: every door open, no note");
  FEATURES = 403;
  await featLoad(true);
  ok(feat.map === null && /owner/.test(feat.err), "403: no map, the owner's login only (" + feat.err + ")");
  ok(FALL.every(function (n) { return !featIsOff(n); }), "403: every feature taken as on");
  // the same login is not asked twice; another login is
  var fAsks = function () { return TEST.fetches.filter(function (f) { return /\/features$/.test(f); }).length; };
  var fN = fAsks();
  await featLoad();
  eq(fAsks(), fN, "the same login: not asked again");
  var fUser = cfg.user;
  cfg.user = fUser + "-other";
  FEATURES = { features: FALL.map(function (n) {
    return { name: n, on: n === "caldav", needs: n === "maps" ? ["LCARS_MAPY_KEY"] : n === "strava" ? ["LCARS_STRAVA_CLIENT_ID", "LCARS_STRAVA_CLIENT_SECRET"] : [],
             note: n === "maps" ? "Plotting a course draws Mapy.com maps: set LCARS_MAPY_KEY." : "The " + n + " note." };
  }) };
  await featLoad();
  eq(fAsks(), fN + 1, "another login: asked again");
  cfg.user = fUser;
  await featLoad();
  eq(fAsks(), fN + 2, "and back: asked again");
  eq(feat.err, "", "read: no error");
  ok(featIsOff("maps") && !featIsOff("caldav"), "maps off, caldav on");
  var fnote = featNote("maps");
  has(fnote, "Plotting a course draws Mapy.com maps", "the note is the server's sentence");
  has(fnote, "<code>LCARS_MAPY_KEY</code>", "and names the setting");
  eq(featNote("caldav"), "", "a feature on has no note");
  has(featSummary(), "14 of 15 off", "the summary counts what is off");

  // the doors: the note in the view
  if ($("#ov").classList.contains("on")) closeOv();
  openReports();
  ok(!!$("#dlg .featoff[data-feat=reports]"), "Reports: the note in the view");
  closeOv();
  openCourse();
  ok(!!$("#dlg .featoff[data-feat=maps]") && !!$("#dlg .featoff[data-feat=navigator]"), "the course's list: maps and the navigator said, and it still opens");
  closeOv();
  openQueue();
  await pump();
  ok(!!$("#dlg .featoff[data-feat=engineers]") && /Off on this server/.test($("#dlgh").textContent), "the queue: a dialog of its own with the engineers' note");
  has($("#toast").textContent, "The engineers is off on this server", "and the toast as well");
  closeOv();
  chatsUp();
  ok((await engKeyAsk()) === false, "an engineer's door shut");
  ok(!!$("#dlg .featbox .featoff[data-feat=engineers]"), "the chats: the note in the list's slot");
  ok($("#dlgh") && $("#dlgh").textContent === "Chats", "and the chats stay up");
  closeOv();
  // the editor's media
  newEntry("", "", false);
  ok(document.body.dataset.pane === "edit", "an entry being written");
  mediaAdd([{ name: "x.txt", size: 1, type: "text/plain" }]);
  ok(!!$("#ed_mfield .featoff[data-feat=media]"), "attach: the note in the editor's media");
  ok(media.jobs.length === 0, "and nothing sent");
  var fRec = media.rec;
  await mediaRecToggle();
  ok(media.rec === fRec, "record: the door shut");
  leaveEntry();

  // Config's Server section
  openCfg();
  var srv = $("#c_srvl");
  ok(!!srv, "Config has a Server section");
  has(srv.textContent, "14 of 15 off", "it says what is off");
  ok(srv.querySelectorAll(".featrow").length === 15 && srv.querySelectorAll(".featrow.off").length === 14, "a row for each feature, the off ones marked");
  has(srv.innerHTML, "LCARS_STRAVA_CLIENT_ID", "an off one names its settings");
  has(srv.innerHTML, "The strava note.", "and its note");
  ok(!!$("#c_vengoff .featoff[data-feat=transcription]"), "the recogniser's field says Deepgram is off");
  FEATURES = 403;
  $("#c_srvr").click();
  has($("#c_srvr").textContent, "reading", "Read again: pressed at once");
  await pump();
  await featLoad();
  has($("#c_srvl").textContent, "could not be read", "a 403: the section says so");
  has($("#c_srvl").textContent, "owner", "and why");
  closeOv();

  // the voice order and its key
  eq(vMatch(vWords("what is off"), 0).cmd.say, "what is off", "'what is off' is an order");
  eq(vMatch(vWords("what can the server do"), 0).cmd.say, "what is off", "and so is 'what can the server do'");
  ok(KEYS.some(function (k) { return k.key === "W" && /featWhatOff/.test(String(k.fn)); }), "W is its key");
  FEATURES = { features: [{ name: "maps", on: false, needs: ["LCARS_MAPY_KEY"], note: "No maps." }, { name: "media", on: true, needs: [], note: "" }] };
  await featLoad(true);
  await featWhatOff();
  ok(/Off on this server/.test($("#dlgh").textContent) && !!$("#dlg .featoff[data-feat=maps]") && !$("#dlg .featoff[data-feat=media]"), "what is off: the dialog lists what is off, only");
  has($("#toast").textContent, "1 of 2 off", "and the toast says how many");
  closeOv();
  // back to a server with everything on, for what follows
  FEATURES = null;
  await featLoad(true);
  demoBanner();
  ok(!$("#demobar"), "no demo banner");
  ok(!VCMDS.some(function (c) { return c.say === "reset the demo"; }), "no reset order");
  ok(updOn() === WEB && !inDeck(), "the update check as ever");

  console.log("\n-- open questions: what the crew asks of the captain --");
  await (async function () {
    closeOv(); hideToast();
    var n0 = oqCount();
    var qA = await plant({ kind: "task_no1", title: "Ship the deck's new pins?", done_bool: 0,
      content: "Sato built them; the deck test is green.\nMy recommendation: ship.\n" + "more context\n".repeat(8) });
    var qB = await plant({ kind: "task_crew", title: "The NAS is 95% full: prune the tapes?", done_bool: 0, content: "ops found it" });
    var qOld = await plant({ kind: "task_no1", title: "an answered one", done_bool: 1, content: "x" });
    qB.created_at_utc = fmtUtc(new Date(Date.now() + 60000));
    refresh();
    eq(oqCount(), n0 + 2, "the open ones are counted, a done one not");
    has($("#bChat").textContent, String(chatUnreadTotal() + engAnswerCount()), "the Chats button carries them");
    ok(engAnswerCount() >= 2, "each open question waits on the captain");
    chatsList(); await settle(2);
    var row = $("#chrows").querySelector("[data-oqv]");
    ok(row && /^<div class="chrowl"[^>]*><button[^>]*data-oqv/.test($("#chrows").innerHTML), "the Chats list has an Open questions row at its top");
    has(row.textContent, String(n0 + 2), "with the count");
    click(row); await settle(3);
    eq(st.route && st.route.v, "questions", "the view has its url");
    var cards = $("#oqrows").querySelectorAll(".oqcard");
    eq(cards.length, n0 + 2, "a card per open question");
    eq(Number(cards[0].dataset.oqid), qB.id, "newest first");
    has(cards[0].querySelector(".oqmeta").textContent, "The crew", "the crew's ask says who");
    var cA = $("#oqrows").querySelector('[data-oqid="' + qA.id + '"]');
    has(cA.querySelector(".oqq").textContent, "Ship the deck's new pins?", "the question is the heading");
    has(cA.querySelector(".oqmeta").textContent, "Number One", "Number One's says so");
    ok(cA.querySelector(".oqctx.fold") && /recommendation/.test(cA.querySelector(".oqctx").innerHTML), "the context rendered, folded");
    click(cA.querySelector("[data-oqmore]")); await settle(1);
    cA = $("#oqrows").querySelector('[data-oqid="' + qA.id + '"]');
    ok(!cA.querySelector(".oqctx.fold"), "more unfolds it");
    ok(!$("#oqrows").querySelector('[data-oqid="' + qOld.id + '"]'), "a done one has no card");
    // a draft kept across a repaint and Later
    var ta = cA.querySelector("[data-oqa]");
    ta.value = "Ship it, after the phone check.";
    ta.dispatchEvent(new Event("input", { bubbles: true }));
    eq(oqDraft(qA.id), "Ship it, after the phone check.", "typing is kept as the draft");
    oq.sig = ""; oqPaint();
    eq($("#oqrows").querySelector('[data-oqa="' + qA.id + '"]').value, "Ship it, after the phone check.", "and survives a repaint");
    click($("#oqrows").querySelector('[data-oqlater="' + qA.id + '"]')); await settle(1);
    ok(st.byId.get(qA.id).done_bool == 0, "Later keeps it open");
    has($("#toast").textContent, "draft kept", "and says the draft is kept");
    // Answer and close
    var was = DB.filter(function (r) { return r.id === qA.id; })[0].content;
    var pA = oqAnswer(qA.id);
    ok($("#oqrows").querySelector('[data-oqid="' + qA.id + '"].saving'), "the card shows saving at once");
    has($("#oqrows").querySelector('[data-oqid="' + qA.id + '"]').textContent, "saving", "in words");
    await pA; await settle(3);
    var dA = DB.filter(function (r) { return r.id === qA.id; })[0];
    ok(/^Answer \(captain, \d{4}-\d\d-\d\d \d\d:\d\d\): Ship it, after the phone check\.\n\n/.test(dA.content), "the answer is prepended to the content");
    ok(dA.content.slice(dA.content.indexOf("\n\n") + 2) === was, "the context kept under it");
    eq(dA.done_bool, 1, "and it is done");
    ok(DBLOG.some(function (l) { return /^PATCH \/entries\/\d+ .*if_modified/.test(l); }), "through a guarded PATCH");
    ok(!$("#oqrows").querySelector('[data-oqid="' + qA.id + '"]'), "the card leaves");
    eq(oqDraft(qA.id), "", "the draft goes with it");
    eq(oqCount(), n0 + 1, "the count drops");
    var undo = $("#toast").querySelector(".tact");
    ok(undo && undo.textContent === "Undo", "a toast with Undo");
    click(undo); await settle(4);
    dA = DB.filter(function (r) { return r.id === qA.id; })[0];
    eq(dA.content, was, "Undo puts the old content back");
    eq(dA.done_bool, 0, "and opens it again");
    ok($("#oqrows").querySelector('[data-oqid="' + qA.id + '"]'), "its card is back");
    eq(oqDraft(qA.id), "Ship it, after the phone check.", "with the answer in its box");
    // a row moved between the read and the write: answered on the new one
    var apiWas = api, moved = false;
    api = function (path, o) {
      if (o && o.method === "PATCH" && !moved) { moved = true; var r = dbFind(qB.id); r.content = "ops found it, and more"; r.last_modified_at_utc = "2099-02-02 00:00:00"; }
      return apiWas(path, o);
    };
    await oqAnswer(qB.id); await settle(3);
    api = apiWas;
    var dB = dbFind(qB.id);
    ok(moved && dB.done_bool === 1 && dB.content === "ops found it, and more",
       "a tick with no text is a tick, on the row as it is now (a 412 read again)");
    // a failed write: on the card, with Retry
    api = function (path, o) { if (o && o.method === "PATCH") return Promise.reject(Object.assign(new Error("offline"), { http: 500 })); return apiWas(path, o); };
    await oqAnswer(qA.id); await settle(2);
    api = apiWas;
    var cF = $("#oqrows").querySelector('[data-oqid="' + qA.id + '"]');
    ok(cF && /not saved/.test(cF.textContent) && cF.querySelector("[data-oqdone]").textContent === "Retry", "a failure says so on the card, with Retry");
    eq(oqDraft(qA.id), "Ship it, after the phone check.", "the text kept");
    oq.busy.delete(qA.id);
    // the order, the key, the palette row
    eq(vMatch(vWords("open questions"), 0).cmd.say, "open questions", "“open questions” is the order");
    eq(vMatch(vWords("what do you need from me"), 0).cmd.say, "open questions", "and “what do you need from me”");
    ok(KEYMAP.get("!") && /openQuestions/.test(String(KEYMAP.get("!").fn)), "! is its key");
    closeOv();
    oqDraftSet(qA.id, "");
    unplant(qA); unplant(qB); unplant(qOld);
    eq(oqCount(), n0, "and gone with the rows");
  })();

  console.log("\n-- open questions: an ask split into its questions, each answered, one Send --");
  await (async function () {
    closeOv(); hideToast();
    // the parser
    eq(oqParse("Ship it?", "Sato built them.\nMy recommendation: ship."), null, "the old shape: no question lines, no Options: one question as before");
    eq(oqParse("t", "Steps:\n1. build\n2. test\n3. ship"), null, "a numbered list that asks nothing is context");
    var p = oqParse("Two things", "The deck is green.\nShared line.\n\nQ1: Ship the pins today?\nThe phone check passed.\nOptions: A) ship now B) wait for the iPad C) drop them\nRecommendation: A, it is tested.\n" +
      "**Q2.** Keep the old view?\nOnly the menu used it.\n\nQ3: Rename it?\nOptions:\nA) Questions\nB) Asks\n");
    eq(p.qs.length, 3, "Q lines: three questions");
    eq(p.ctx, "The deck is green.\nShared line.", "the text before the first is the shared context");
    eq(p.qs[0].opts.map(function (o) { return o.k + "=" + o.l; }).join("|"), "A=ship now|B=wait for the iPad|C=drop them", "inline Options");
    eq(p.qs[0].rec, "A", "Recommendation marks the default");
    has(p.qs[0].ctx, "phone check passed", "a question's own context");
    has(p.qs[0].ctx, "Recommendation: A, it is tested.", "the recommendation's reason stays as context");
    eq(p.qs[1].text, "Keep the old view?", "a bold Q2. line");
    eq(p.qs[1].opts.map(function (o) { return o.k; }).join(), "yes,no", "no Options: Yes and No");
    eq(p.qs[1].rec, "", "no Recommendation, none marked");
    eq(p.qs[2].opts.map(function (o) { return o.k + "=" + o.l; }).join("|"), "A=Questions|B=Asks", "Options: then a line each");
    var pn = oqParse("t", "Context.\n1. Ship it?\nRecommendation: yes\n2. And the deck too?");
    eq(pn && pn.qs.length, 2, "1. and 2. lines that ask are questions");
    eq(pn.qs[0].rec, "yes", "a yes/no Recommendation");
    var p1 = oqParse("Which name?", "Options: A) Asks B) Questions\nRecommendation: Z");
    ok(p1 && p1.qs.length === 1 && p1.qs[0].text === "Which name?" && p1.qs[0].own, "Options alone: one question, the title's");
    eq(p1.qs[0].rec, "", "a Recommendation naming no choice marks none");
    eq(oqAnsLine(p.qs[0], { c: "A", note: "after lunch" }), "Q1: A (ship now); note: after lunch", "an answer's line");
    eq(oqAnsLine(p.qs[1], { c: "yes" }), "Q2: yes", "a yes");
    eq(oqAnsLine(p.qs[2], { c: "skip" }), "Q3: skipped", "a Skip");

    // the card
    var content = "The deck is green.\nShared line.\nThird line.\n\nQ1: Ship the pins today?\nOptions: A) ship now B) wait\nRecommendation: A\nQ2: Keep the old view?\nQ3: Rename it?";
    var qM = await plant({ kind: "task_no1", title: "Pins and the old view", done_bool: 0, content: content });
    // the top card, which the spoken answers go to
    qM.created_at_utc = fmtUtc(new Date(Date.now() + 120000));
    refresh();
    oq.more.delete(qM.id);  // an id an earlier check's row had, unfolded there
    openQuestions(); await settle(2);
    var card = function () { return $("#oqrows").querySelector('[data-oqid="' + qM.id + '"]'); };
    ok(card() && card().classList.contains("oqmulti"), "an ask in the shape gets the split card");
    eq(card().querySelectorAll(".oqb").length, 3, "a block per question");
    ok(card().querySelector(".oqctx.fold"), "the shared context folded");
    ok(card().querySelector('[data-oqc="' + qM.id + ':1:A"].rec'), "the recommended choice marked");
    ok(card().querySelector('[data-oqc="' + qM.id + ':2:yes"]') && card().querySelector('[data-oqc="' + qM.id + ':2:no"]'), "Yes and No where no Options");
    ok(card().querySelector('[data-oqc="' + qM.id + ':3:skip"]'), "and Skip");
    ok(card().querySelector("[data-oqdone]").disabled, "Send waits for every answer");
    has(card().querySelector(".oqst").textContent, "0 of 3", "and says how many are in");
    click(card().querySelector('[data-oqc="' + qM.id + ':1:B"]'));
    ok(card().querySelector('[data-oqb="' + qM.id + ':1"].done') && /wait/.test(card().querySelector('[data-oqb="' + qM.id + ':1"] .oqpick').textContent),
       "a choice shows at once, the block folded to its answer");
    click(card().querySelector('[data-oqopen="' + qM.id + ':1"]'));
    ok(card().querySelector('[data-oqc="' + qM.id + ':1:B"].on'), "the folded answer unfolds to change it");
    click(card().querySelector('[data-oqc="' + qM.id + ':1:A"]'));
    var note = card().querySelector('[data-oqnote="' + qM.id + ':1"]');
    note.value = "after lunch"; note.dispatchEvent(new Event("input", { bubbles: true }));
    click(card().querySelector('[data-oqc="' + qM.id + ':3:skip"]'));
    oq.sig = ""; oqPaint();
    eq(card().querySelector('[data-oqnote="' + qM.id + ':1"]').value, "after lunch", "a note survives a repaint");
    eq(oqAns(qM.id)[1].c, "A", "the choices kept per question on the device");
    ok(card().querySelector("[data-oqdone]").disabled, "Send still waits for Q2");
    // by voice
    eq(vMatch(vWords("answer question 2 yes but only on the phone"), 0).cmd.say, "answer question {n} {*}", "“answer question 2 yes …” is an order");
    eq(vMatch(vWords("send the answers"), 0).cmd.say, "send the answers", "and “send the answers”");
    oqSendSaid(); await settle(1);
    eq(dbFind(qM.id).done_bool, 0, "a send said before every answer is in refuses");
    oqSaid(2, "yes but only on the phone");
    eq(oqAns(qM.id)[2].c, "yes", "said: the choice");
    eq(oqAns(qM.id)[2].note, "only on the phone", "and the rest its note");
    ok(!card().querySelector("[data-oqdone]").disabled, "every question answered: Send is on");
    // Send
    var pS = oqAnswer(qM.id);
    ok(card().classList.contains("saving") && /sending/.test(card().textContent), "Send shows at once");
    await pS; await settle(3);
    var dM = dbFind(qM.id);
    eq(dM.content.slice(0, dM.content.indexOf("\n\n") + 2).replace(/\d{4}-\d\d-\d\d \d\d:\d\d/, "T"),
       "Answer (captain, T):\nQ1: A (ship now); note: after lunch\nQ2: yes; note: only on the phone\nQ3: skipped\n\n", "Send writes every answer in one block");
    ok(dM.content.endsWith(content), "the ask kept under it");
    eq(dM.done_bool, 1, "and ticks it off");
    eq(JSON.stringify(oqAns(qM.id)), "{}", "the answers' draft goes");
    click($("#toast").querySelector(".tact")); await settle(4);
    dM = dbFind(qM.id);
    ok(dM.content === content && dM.done_bool === 0, "Undo: the block off, open again");
    eq(oqAns(qM.id)[1].note, "after lunch", "the answers back on the card");
    closeOv();
    oqAnsSet(qM.id, null);
    unplant(qM);
  })();

  console.log("\n-- the architect: its thread, the fence, the entry, the error turn (docs/design/architect.md) --");
  await (async function () {
    closeOv(); runTimers(); await settle(1);
    // the fence's head and the fence closing
    var p1 = archParse("// new: A brass vase by the window\nconst at = deck.room().point(0.8, 0.2);\n");
    eq(p1.id + "|" + p1.title, "new|A brass vase by the window", "a fence's first line: new, and its title");
    eq(archParse("// arch-lx3: Smaller\ndeck.obj('x').scale(0.8);").id, "arch-lx3", "an id to revise");
    eq(archParse("deck.obj('x').hide();").id + "|" + archParse("deck.obj('x').hide();").title, "new|", "no head: a new patch, untitled");
    ok(!archParse("  \n"), "an empty fence is no patch");
    ok(!archFence("Here:\n```js deck-patch\n// new: x\ndeck.obj('a').hide();\n``"), "a fence not yet closed is not handed on");
    var fz = archFence("Here:\n```js deck-patch\n// new: x\ndeck.obj('a').hide();\n```\nThe table is gone.");
    ok(fz && fz.code === "// new: x\ndeck.obj('a').hide();" && /The table is gone/.test(fz.after), "closed: the code, and what follows it");
    ok(!archFence("```js\nconst a = 1;\n```"), "a plain js fence is not a patch");

    // the deck, stood in for: what it sees, its picture, its patch door
    var calls = [], sees = 0, libs = 0, shots = 0, failNext = [];
    var deck = {
      lcarsDeckSees: function (o) { sees++; if (o && o.library) libs++; return { text: "[What the captain sees on the deck, now:\n Room: 8/Ten Forward.]" + (o && o.library ? "\n[The model library: tenforward: tf_table 1x0.7x1]" : ""), room: "8/Ten Forward", aim: { name: "8/Ten Forward/tenforward/tf_table#1" } }; },
      lcarsDeckShot: function () { shots++; return Promise.resolve({ size: 1500, type: "image/jpeg" }); },
      lcarsDeckPatch: function (x, op) {
        calls.push({ x: JSON.parse(JSON.stringify(x)), op: op });
        if (op === "apply" && failNext.length) { var f = failNext.shift(); return Promise.resolve({ ok: false, id: x.id === "new" ? "arch-t" + calls.length : x.id, err: f, line: 2, names: [] }); }
        var id = x.id === "new" ? "arch-t" + calls.length : x.id;
        return Promise.resolve({ ok: true, id: id, seq: 1, on: op !== "off", room: x.room || "8/Ten Forward", names: [],
                                 patch: { v: 1, id: id, seq: 1, room: x.room || "8/Ten Forward", on: op !== "off", code: x.code, title: x.title, says: "", by: "architect", asked: x.asked || "", api: 1, replaces: null, row: x.row || 0 } });
      },
      lcarsDeckArchitect: function () { calls.push({ op: "sheet" }); return true; },
    };
    var hadParent = Object.prototype.hasOwnProperty.call(window, "parent"), oldParent = window.parent;
    var hadTD = typeof TextDecoder !== "undefined";
    if (!hadTD) globalThis.TextDecoder = function () { this.decode = function (v) { return v == null ? "" : String(v); }; };
    var hadRaf = typeof requestAnimationFrame !== "undefined";
    if (!hadRaf) globalThis.requestAnimationFrame = function (f) { return setTimeout(f, 16); };
    var realSend = chatMediaSend, ups = [];
    chatMediaSend = function (blob, name) {
      ups.push(name);
      var p = Promise.resolve({ path: "media/chat/2026/10/" + name, url: "/media/chat/" + name, name: name, mime: "image/jpeg", bytes: blob.size });
      p.abort = function () {};
      return p;
    };
    // /chat: each answer streamed in two parts, the second held until the
    // test lets it go - so what happens at the fence is seen before the end
    var sse = function (o) { return "data: " + JSON.stringify(o) + "\n\n"; }, txt = function (s) { return sse({ type: "stream_event", event: { type: "content_block_delta", delta: { type: "text_delta", text: s } } }); };
    var bodies = [], gates = [], answers = [], fFetch = fetch;
    fetch = function (url, o) {
      if (!/\/chat$/.test(String(url))) return fFetch.apply(this, arguments);
      bodies.push(JSON.parse(o.body));
      var a = answers.shift() || ["Nothing to change.", ""], gate = {}, held = new Promise(function (r) { gate.go = r; });
      gates.push(gate);
      var chunks = [sse({ type: "system", subtype: "init", session_id: "s-arch" }) + sse({ type: "stream_event", event: { type: "content_block_start", content_block: { type: "text", text: "" } } }) + txt(a[0]),
                    null, txt(a[1]) + sse({ type: "result", session_id: "s-arch" }) + sse({ type: "lcars_exit", code: 0 })];
      var i = 0;
      return Promise.resolve({ ok: true, status: 200, body: { getReader: function () { return { read: function () {
        if (i === 1) { i++; return held.then(function () { return { value: "", done: false }; }); }
        if (i >= chunks.length) return Promise.resolve({ done: true });
        return Promise.resolve({ value: chunks[i++], done: false });
      } }; } } });
    };
    try {
      // outside the deck: the order says where it is
      window.parent = window;
      eq(openArchitect(), false, "the console alone: the architect is not here");
      has($("#toast").textContent, "open the deck", "and the toast says where it is");
      eq(vMatch(vWords("architect"), 0).cmd.say, "architect", "“architect” is a console order");
      ok(paletteRows().some(function (r) { return /the architect/.test(r.label) && r.run === openArchitect; }), "and a palette row");
      window.parent = deck;
      eq(openArchitect(), true, "in the deck's frame: the deck's sheet opens");
      eq(calls.pop().op, "sheet", "through lcarsDeckArchitect");

      // a thread made by an older deck as a person named arch becomes the architect's
      chats.list = chats.list.filter(function (x) { return x.id !== "arch"; });
      chats.list.push(chatThread({ id: "arch", person: { key: "arch", name: "The architect" }, msgs: [], at: 1 }));
      chats.list[chats.list.length - 1].person = { key: "arch", name: "The architect" };
      ok(window.lcarsDeckChat("arch", { person: { key: "arch", name: "The architect", title: "changes the ship while you watch" }, model: "sonnet" }), "the deck opens the arch thread");
      var t = chatFind("arch");
      ok(t.arch && !t.person, "a person named arch migrated: a thread of its own kind");
      eq(chatTitle(t) + "|" + chatKind(t) + "|" + chatInitials(t), "The architect|k-arch|A", "its title, kind and initial");
      ok(chatTakesFiles(t), "it takes files (the picture)");
      ok(chatRows("").aboard.some(function (x) { return x.t === t; }), "listed under Aboard");
      ok(chatThread({ id: "arch", person: { key: "arch" } }).arch && !chatThread({ id: "arch", person: { key: "arch" } }).person, "and a saved one loads as the architect's");
      ok(t.pre && /deck-patch/.test(t.pre), "its brief rides on the first message (the short one with no engineer key)");
      var m = chatFull();

      // a message: the bubble and its picture at once; the fence applied before the stream ends
      answers.push(["```js deck-patch\n// new: A round table\ndeck.obj(\"8/Ten Forward/tenforward/tf_table#1\").scale([1.2, 1, 1.2]);\n```\n", "The table is round now."]);
      var before = DB.length;
      m.box.value = "make this table round"; m.box.oninput();
      chatSend(); 
      var u = t.msgs[t.msgs.length - 1];
      ok(u && u.role === "user" && u.state === "sending" && u.files && u.files.length === 1 && u.files[0].shot, "sent: the bubble in the tap's frame, the picture as its file");
      eq(sees + "|" + libs, "2|1", "what the deck sees read at Send, the library on the first message in a room");
      await settle(8);
      eq(shots + "|" + ups.length, "1|1", "the picture taken and uploaded");
      eq(bodies.length, 1, "the message goes once the picture is up");
      var b0 = bodies[0];
      ok(b0.attachments && b0.attachments.length === 1 && /^deck-\d{8}-\d{6}\.jpg$/.test(b0.attachments[0].name), "attached: the deck's picture");
      ok(b0.message.indexOf("deck-patch") >= 0 && b0.message.indexOf("Room: 8/Ten Forward") > 0 && b0.message.indexOf("model library") > 0 &&
         /make this table round$/.test(b0.message), "the message: the brief, what he sees (the library too), then his words");
      eq(calls.length, 1, "the fence closed: handed to the deck before the answer ended");
      eq(calls[0].op + "|" + calls[0].x.id + "|" + calls[0].x.room + "|" + calls[0].x.title + "|" + calls[0].x.asked, "apply|new|8/Ten Forward|A round table|make this table round",
         "a new patch, in the room he stands in, its title and what he asked");
      ok(/^\/\/ new: A round table\ndeck\.obj/.test(calls[0].x.code), "its code as written");
      eq(DB.length, before, "nothing written yet: the answer is still coming");
      has(m.log.innerHTML, "applied as arch-t1", "the answer says applied, at once");
      gates[0].go(); await settle(10);
      var rowP = DB[DB.length - 1];
      eq(DB.length, before + 1, "the answer ended: one entry written");
      eq(rowP.kind + "|" + rowP.title, "deck_patch|A round table", "of kind deck_patch, titled as the patch");
      var cP = JSON.parse(rowP.content);
      ok(cP.id === "arch-t1" && cP.code === calls[0].x.code && cP.on === true && cP.says === "The table is round now." && !("row" in cP),
         "its content the patch, its closing sentence as what it says, no row");
      var am = t.msgs[t.msgs.length - 1];
      ok(/Applied as arch-t1\.$/.test(chatMsgText(am)), "“Applied as arch-t1.” at the end of the answer");
      ok(m.log.querySelector('[data-patch="off"]'), "with an Undo chip");
      eq(t.archLast, "[Your last patch arch-t1 applied.]", "the next message will say it applied");

      // Undo: off in the deck, then kept off in the entry (a guarded PATCH from a fresh read)
      click(m.log.querySelector('[data-patch="off"]'));
      ok(am.patch.busy, "Undo pressed: busy at once");
      await settle(8);
      eq(calls[calls.length - 1].op + "|" + calls[calls.length - 1].x.id, "off|arch-t1", "the deck switched it off");
      eq(JSON.parse(rowP.content).on, false, "and the entry keeps it off");
      eq(JSON.parse(rowP.content).says, "The table is round now.", "the rest of the content as it was");
      ok(m.log.querySelector('[data-patch="on"]'), "the chip offers it back");
      // a write in between (another device): the 412 is read again, not written over
      rowP.last_modified_at_utc = "2099-03-03 00:00:00";
      rowP.content = JSON.stringify(Object.assign(JSON.parse(rowP.content), { title: "Rounder" }));
      click(m.log.querySelector('[data-patch="on"]')); await settle(8);
      ok(JSON.parse(rowP.content).on === true && JSON.parse(rowP.content).title === "Rounder", "On again: kept from the journal's copy, the other write not lost");

      // the next message carries how the last patch went; a failing patch goes back once by itself
      failNext.push("deck.obj: no such object 8/Ten Forward/x#9", "deck.obj: still not there");
      answers.push(["```js deck-patch\n// new: A lamp\ndeck.obj(\"8/Ten Forward/x#9\").hide();\n```\n", "Done."]);
      answers.push(["```js deck-patch\n// new: A lamp\ndeck.obj(\"8/Ten Forward/x#8\").hide();\n```\n", "Done now."]);
      m.box.value = "hide that lamp"; m.box.oninput(); chatSend(); await settle(8);
      ok(bodies[1].message.indexOf("[Your last patch arch-t1 applied.]") === 0, "the next message opens with the last patch's outcome");
      ok(bodies[1].message.indexOf("model library") < 0, "the same room: no library again");
      gates[1].go(); await settle(14);
      eq(bodies.length, 3, "the patch failed: the error sent back by itself, once");
      eq(bodies[2].message.split("\n").pop(), "[Your patch failed: deck.obj: no such object 8/Ten Forward/x#9 (line 2). The scene is unchanged. Fix it.]",
         "in the design's words, after what the deck shows");
      eq(bodies[2].attachments, undefined, "with no new picture: the scene is unchanged");
      var sysl = t.msgs.filter(function (x) { return x.role === "sys" && /Your patch failed/.test(x.text); });
      eq(sysl.length, 1, "shown as a system line, not as the captain's words");
      eq(DB.length, before + 1, "nothing written for a patch that failed");
      gates[2].go(); await settle(14);
      eq(bodies.length, 3, "a second failure is not sent again");
      var last = t.msgs[t.msgs.length - 1];
      ok(last.patch && last.patch.final, "the second failure is the captain's");
      has(m.log.innerHTML, "no such object 8/Ten Forward/x#9", "both errors under the answer: the first");
      has(m.log.innerHTML, "still not there", "and the second");
      ok(m.log.querySelector('[data-patch="retry"]'), "with Retry");
      answers.push(["```js deck-patch\n// new: A lamp\ndeck.obj(\"8/Ten Forward/x#7\").hide();\n```\n", "The lamp is gone."]);
      click(m.log.querySelector('[data-patch="retry"]')); await settle(8);
      eq(bodies.length, 4, "Retry sends the error turn again");
      gates[3].go(); await settle(14);
      eq(DB.length, before + 2, "and its patch, applied, is written");
      chatSave();
      var saved = lsGet("lcars.chats", {}).list.find(function (x) { return x.id === "arch"; });
      ok(saved && !saved.person && saved.archRoom === "8/Ten Forward", "the thread is saved as the architect's, with its room");
    } finally {
      fetch = fFetch; chatMediaSend = realSend;
      if (hadParent) window.parent = oldParent; else delete window.parent;
      if (!hadTD) delete globalThis.TextDecoder;
      if (!hadRaf) delete globalThis.requestAnimationFrame;
      chats.list = chats.list.filter(function (x) { return x.id !== "arch"; });
      chat = chatComputer();
      closeOv(); hideToast(); runTimers(); await settle(2);
    }
  })();

  /* ---------- kinds by role (docs/design/kinds.md) ---------- */
  console.log("\n-- kinds: the roles, the mapping, Config's Kinds --");
  await (async function () {
    eq(JSON.stringify(KIND_ROLES), JSON.stringify(C_KIND_ROLES), "the page's role table is lcars_kinds.h's, in its order");
    ok(kindMap.map && kindMap.map.size === C_KIND_ROLES.length, "the boot read GET /kinds/roles");
    C_KIND_ROLES.forEach(function (r) {
      var m = KINDMAP[r[0]];
      if (!m) eq(kindOf(r[0]), r[1], "an unset role is its default: " + r[0]);
      else eq(kindsOf(r[0]).join(","), m.kind, "a set role is the mapping's: " + r[0]);
    });
    ok(lsGet("lcars.kinds", null) && lsGet("lcars.kinds", null).base === cfg.base, "the answer is kept for the next boot, per server");
    var mapWas = JSON.parse(JSON.stringify(KINDMAP));
    closeOv(); hideToast();
    voiceHeard("computer the kinds by role");
    await settle(6);
    ok($("#c_kinds"), "“the kinds by role” opens Config at Kinds");
    var rows = $("#c_kindl").querySelectorAll(".kr");
    eq(rows.length, C_KIND_ROLES.length, "a row a role");
    var row = function (r) { return $("#c_kindl").querySelector('.kr[data-role="' + r + '"]'); };
    ok(row("child_sleep").querySelector(".krnm"), "the child's sleep takes a name");
    ok(!row("log").querySelector(".krnm"), "the log does not");
    var puts = function () { return DBLOG.filter(function (l) { return /^PUT \/kinds\/roles/.test(l); }).length; };
    var p0 = puts();
    change(row("child_vocab").querySelector(".krk"), "zz_words");
    ok(row("child_vocab").classList.contains("busy"), "a change shows in its row in the same frame");
    has(row("child_vocab").textContent, "saving…", "saying saving…");
    await settle(6);
    eq(puts(), p0 + 1, "one PUT /kinds/roles");
    eq(KINDMAP.child_vocab && KINDMAP.child_vocab.kind, "zz_words", "the server holds it");
    eq(kindOf("child_vocab"), "zz_words", "kindOf reads it");
    ok(row("child_vocab").classList.contains("set") && row("child_vocab").querySelector(".krx"), "the row is marked set, with Reset");
    ok(!row("child_vocab").classList.contains("busy"), "and no longer saving");
    change(row("child_vocab").querySelector(".krk"), "Not A Kind!");
    eq(puts(), p0 + 1, "a kind that is not a slug is not sent");
    ok(row("child_vocab").classList.contains("bad"), "it says so in the row");
    KINDS_CODE = 403;
    change(row("child_vocab").querySelector(".krk"), "zz_other");
    await settle(6);
    KINDS_CODE = 0;
    ok(row("child_vocab").classList.contains("bad") && row("child_vocab").querySelector(".krr"), "a refusal is said in the row, with Retry");
    has(row("child_vocab").textContent, "owner's only", "in words");
    eq(row("child_vocab").querySelector(".krk").value, "zz_other", "what was typed is kept");
    click(row("child_vocab").querySelector(".krr"));
    await settle(6);
    eq(KINDMAP.child_vocab && KINDMAP.child_vocab.kind, "zz_other", "Retry sends it again");
    click(row("child_vocab").querySelector(".krx"));
    await settle(6);
    eq(kindOf("child_vocab"), "child_vocab", "Reset: back to the default");
    voiceHeard("computer set the kind for the child's vocab to zz words");
    await settle(6);
    eq(KINDMAP.child_vocab && KINDMAP.child_vocab.kind, "zz_words", "said: “set the kind for the child's vocab to zz words”");
    voiceHeard("computer set the kind for the child's vocab to default");
    await settle(6);
    ok(!KINDMAP.child_vocab, "and “… to default” resets it");
    voiceHeard("computer set the kind for nothing known to x");
    await settle(2);
    has($("#vstat") ? $("#vstat").textContent + $("#toast").textContent : $("#toast").textContent, "no role", "a role it does not know is refused");
    // the captain's mapping as it was, whatever the run started with
    Object.keys(KINDMAP).forEach(function (k) { delete KINDMAP[k]; });
    Object.assign(KINDMAP, mapWas);
    await kindsLoad(true);
    closeOv(); hideToast();

    // a server older than the route: the defaults, nothing kept
    KINDS_CODE = 404;
    await kindsLoad(true);
    KINDS_CODE = 0;
    eq(kindMap.map, null, "a server with no /kinds/roles: every role its default");
    eq(kindOf("log"), "personal_log", "a new entry is a personal_log");
    await kindsLoad(true);

    // a journal with nothing in it: every view opens on it (kinds.md 4)
    console.log("-- kinds: the empty journal --");
    var dbWas = DB;
    DB = [];
    st.all = []; st.byId = new Map();
    await loadAll();
    await settle(10);
    eq(st.all.length, 0, "an empty journal loads empty");
    ok(!/loading/.test($("#count").textContent), "and finishes loading");
    var threw = "";
    try {
      openStats(); await settle(4); closeOv();
      openDay(isoDay(new Date())); await settle(4); closeOv();
      voiceHeard("computer calendar"); await settle(4); closeOv();
      voiceHeard("computer reminders"); await settle(4); closeOv();
      eq(napOffer("nap from 13:35 to 14:39") && napOffer("nap from 13:35 to 14:39").from, "13:35",
         "the nap chip is offered with no row of its kind yet");
    } catch (e) { threw = String(e && e.stack || e); }
    eq(threw, "", "the stats, the day, the calendar and the reminders open on it");
    closeOv(); hideToast();
    DB = dbWas;
    st.all = []; st.byId = new Map();
    await loadAll();
    await settle(20);
    eq(st.all.length, DB.length, "the journal back for what follows");
  })();

  // ---------- classified entries (index.html's "classified" block) ----------
  // The rules the page keeps, with a stand-in for the cipher (this engine has
  // no WebCrypto); test/classified.py runs the real one in Chromium.
  await (async function () {
    console.log("-- classified: what is kept, sealed and shown --");
    var realCrypto = Object.assign({}, clsCrypto), box = new Map(), n = 0;
    clsCrypto.seal = async function (k, p) { var e = "lcs1.dA." + (++n); box.set(e, JSON.parse(JSON.stringify(p))); return e; };
    clsCrypto.open = async function (k, e) { if (!box.has(e)) throw new Error("tag"); return box.get(e); };

    var kept = plainRow({ id: 9, kind: "note", classification: 2, sealed: "lcs1.a.b", title: "t", content: "c",
                          value_int: 3, value_float: 1.5, done_bool: 1 });
    ok(kept.title === "" && kept.content === "" && kept.value_int === 0 && kept.value_float === 0,
       "plainRow (the mirror, the outbox) keeps no Secret text");
    ok(kept.sealed === "lcs1.a.b" && kept.classification === 2 && kept.done_bool === 1, "but its envelope, level and done");
    eq(plainRow({ id: 8, kind: "note", title: "plain", content: "words" }).content, "words", "a plain row as it was");
    lsDel("lcars.draft");
    lsSet("lcars.draft", { id: 9, v: { classification: "2", content: "the plan" }, at: 1 });
    eq(lsGet("lcars.draft", null), null, "a Secret entry's draft is never written down");
    lsSet("lcars.draft", { id: 8, v: { classification: "0", content: "fine" }, at: 1 });
    eq((lsGet("lcars.draft", {}).v || {}).content, "fine", "a plain one is");
    lsDel("lcars.draft");

    ok(clsWrite("/entries", { method: "POST", body: {} }) && clsWrite("/entries/4", { method: "PATCH", body: {} }),
       "the writes api() seals: POST /entries, PUT/PATCH /entries/<id>");
    ok(!clsWrite("/entries/4", { method: "GET" }) && !clsWrite("/vault", { method: "PUT", body: {} }) &&
       !clsWrite("/entries/4/append", { method: "POST", body: {} }), "and nothing else");

    var threw = "";
    try { await clsSealOpts("/entries", { method: "POST", body: { kind: "note", title: "x", classification: 2 } }); }
    catch (e) { threw = e.message; }
    ok(/locked/.test(threw), "locked, a Secret write is refused before it is sent (" + threw + ")");

    cls.key = {}; cls.token = "ab".repeat(32);
    var o = await clsSealOpts("/entries", { method: "POST", body: { kind: "note", title: "Plan", content: "the words",
                                                                     classification: 2 } });
    ok(o.body.title === "" && o.body.content === "" && /^lcs1\./.test(o.body.sealed) && o.body.classification === 2,
       "a Secret create goes out as an envelope and empty columns");
    eq(box.get(o.body.sealed).content, "the words", "the envelope holds the text");
    var h = {};
    clsHeaders(o, h);
    eq(h["X-LCARS-Vault"], cls.token, "and carries the vault token");
    h = {};
    clsHeaders({ body: { done_bool: 1 } }, h);
    ok(!h["X-LCARS-Vault"], "a plain write does not");

    var row = { id: 77001, kind: "note", classification: 2, sealed: o.body.sealed, title: "", content: "",
                value_int: 0, value_float: 0, done_bool: 0, deleted: 0, created_at_utc: "2026-10-20 10:00:00",
                last_modified_at_utc: "2026-10-20 10:00:00", content_length: 9 };
    cls.plain.delete(row.sealed);        // as a row read from the server is, before it is opened
    eq(shownTitle(row).t, clsPlaceholder, "unopened, its row shows the placeholder");
    st.byId.set(row.id, row);
    await clsOpenRows([row]);
    eq(row.title, "Plan", "opened, its title is back in memory");
    eq(shownTitle(row).t, "Plan", "and shown");
    var same = { method: "PUT", body: { done_bool: 1 } };
    ok(await clsSealOpts("/entries/77001", same) === same, "done, the kind, the dates: sent as they are");
    var t = await clsSealOpts("/entries/77001", { method: "PUT", body: { title: "Plan B" } });
    ok(t.body.title === "" && box.get(t.body.sealed).title === "Plan B" && box.get(t.body.sealed).content === "the words",
       "a new title is sealed with the text the page holds");
    var low = await clsSealOpts("/entries/77001", { method: "PUT", body: { classification: 0 } });
    ok(low.body.title === "Plan" && low.body.content === "the words" && low.body.sealed === "",
       "declassifying puts the text back in its columns");

    await clsLock();
    ok(!clsOn() && row.title === "" && row.content === "" && cls.plain.size === 0, "a lock drops the key and the text");
    threw = "";
    try { await clsSealOpts("/entries/77001", { method: "PUT", body: { classification: 0 } }); } catch (e) { threw = e.message; }
    ok(/unlock/.test(threw), "and declassifying then asks for the unlock");
    st.byId.delete(row.id);

    eq(vMatch(vWords("unlock classified"), 0).cmd.say, "unlock classified", "voice: unlock classified");
    eq(vMatch(vWords("lock"), 0).cmd.say, "lock", "voice: lock");
    eq(vMatch(vWords("mark this secret"), 0).cmd.say, "mark this secret", "voice: mark this secret");
    eq(vMatch(vWords("declassify"), 0).cmd.say, "declassify", "voice: declassify");
    ok(KEYS.some(function (k) { return k.key === "L" && /clsUnlockAsk/.test(String(k.fn)); }), "L is its key");

    console.log("-- classified: the recovery code and the passkeys (phase 5) --");
    var b16 = new Uint8Array(16);
    for (var i = 0; i < 16; i++) b16[i] = (i * 37 + 11) & 255;
    var code = clsCodeOf(b16);
    ok(/^[0-9A-HJKMNP-TV-Z]{5}(-[0-9A-HJKMNP-TV-Z]{5}){3}-[0-9A-HJKMNP-TV-Z]{6}$/.test(code),
       "a recovery code: 26 characters of Crockford's base32, in groups (" + code + ")");
    eq(Array.from(clsCodeBytes(code)).join(","), Array.from(b16).join(","), "it reads back to its 16 bytes");
    eq(Array.from(clsCodeBytes(code.toLowerCase().replace(/-/g, " ").replace(/0/g, "o").replace(/1/g, "l"))).join(","),
       Array.from(b16).join(","), "typed in any case, spaced, with O for 0 and L for 1");
    threw = "";
    try { clsCodeBytes(code.slice(0, -1)); } catch (e) { threw = e.message; }
    ok(/26/.test(threw), "a short one is refused (" + threw + ")");
    threw = "";
    try { clsCodeBytes(code.slice(0, -1) + "Z"); } catch (e) { threw = e.message; }
    ok(/wrong/.test(threw), "a last character with its spare bits set is a typo (" + threw + ")");

    // a stand-in vault on a stand-in server: each kek is what made it, each wrap names its kek
    var srv = { vault: null, version: 0, puts: [] }, realApiNet = apiNet, prfOn = true, made = 0;
    apiNet = async function (path, opts) {
      if (path !== "/vault") return realApiNet(path, opts);
      if (!opts || opts.method !== "PUT") return { vault: srv.vault && JSON.parse(JSON.stringify(srv.vault)), version: srv.version };
      if (opts.body.version !== srv.version) { var e = new Error("stale"); e.http = 409; throw e; }
      if (opts.body.vault.wraps.filter(function (w) { return w.type === "password"; }).length !== 1)
        { var e2 = new Error("a vault keeps exactly one password wrap"); e2.http = 400; throw e2; }
      srv.puts.push(JSON.parse(JSON.stringify(opts.body)));
      srv.vault = JSON.parse(JSON.stringify(opts.body.vault));
      srv.version++;
      return { version: srv.version };
    };
    clsCrypto.kek = async function (pw) { return { k: "pw:" + pw }; };
    clsCrypto.hkek = async function (secret, salt, info) { return { k: info + ":" + clsHex(secret) }; };
    clsCrypto.fresh = async function () { return { mk: "MK" }; };
    clsCrypto.wrap = async function (kek, mk) { return { iv: "aXY", wrapped: kek.k + "|" + mk.mk }; };
    clsCrypto.unwrap = async function (kek, w) {
      if (w.wrapped.split("|")[0] !== kek.k) throw new Error("tag");
      return { key: { mk: w.wrapped.split("|")[1] }, token: "cd".repeat(32) };
    };
    clsCrypto.bytes = function (n) { var u = new Uint8Array(n); for (var j = 0; j < n; j++) u[j] = (j * 7 + made) & 255; return u; };
    clsCrypto.pkOk = function () { return true; };
    clsCrypto.salt = function () { return "c2FsdA"; };
    clsCrypto.ok = function () { return true; };
    var prfs = {};
    clsCrypto.pkCreate = async function () {
      made++;
      var id = "Y3JlZA" + made;
      prfs[id] = clsCrypto.bytes(32);
      return { id: id, enabled: prfOn, prf: prfOn ? prfs[id] : null };
    };
    clsCrypto.pkGet = async function (list) { var id = list[list.length - 1].cred; return { id: id, prf: prfs[id] }; };
    clsCrypto.pkForget = function () {};
    cls.vault = undefined; cls.key = null; cls.token = "";

    var rc = await clsSetup("correct horse 1", true);
    ok(/^[0-9A-Z]{5}-/.test(rc) && rc.replace(/-/g, "").length === 26, "setup with the recovery code returns it, once");
    eq(srv.vault.wraps.map(function (w) { return w.type; }).join(","), "password,recovery", "the vault: password and recovery wraps");
    ok(JSON.stringify(srv.puts).indexOf(rc.replace(/-/g, "")) < 0, "and no PUT carries the code");
    eq(srv.vault.wraps[1].kdf + " " + srv.vault.wraps[1].info, "HKDF-SHA256 lcars vault recovery v1", "the recovery wrap names its KDF");
    var w1 = await clsPasskeyAdd("correct horse 1", "Phone");
    eq(srv.vault.wraps.map(function (w) { return w.type; }).join(","), "password,recovery,passkey", "a passkey: one more wrap");
    ok(w1.cred && w1.prf_salt && w1.salt && w1.name === "Phone" && /^\d{4}-\d\d-\d\d$/.test(w1.created),
       "with its credential, its PRF salt, its HKDF salt, a name and a date");
    var pkThrew = "";
    try { await clsPasskeyAdd("not it at all", "Other"); } catch (e) { pkThrew = e.message; }
    ok(/wrong password/.test(pkThrew) && srv.vault.wraps.length === 3, "a wrong password: refused, before any passkey is made");
    prfOn = false;
    pkThrew = "";
    try { await clsPasskeyAdd("correct horse 1", "Old key"); } catch (e) { pkThrew = e.message; }
    ok(/no PRF/.test(pkThrew) && srv.vault.wraps.length === 3, "an authenticator without PRF: told so, not registered (" + pkThrew + ")");
    prfOn = true;
    await clsLock();
    await clsPasskeyUnlock();
    ok(clsOn() && cls.key.mk === "MK", "the passkey unlocks: the same master key");
    await clsLock();
    await clsRecoveryUse(rc.toLowerCase(), "a new password 2");
    ok(clsOn() && cls.key.mk === "MK", "the recovery code unlocks");
    var pw2 = srv.vault.wraps.filter(function (w) { return w.type === "password"; });
    ok(pw2.length === 1 && pw2[0].wrapped.indexOf("pw:a new password 2") === 0 && srv.vault.wraps.length === 3,
       "and sets the new password, every other wrap kept");
    threw = "";
    try { await clsUnwrapPw("correct horse 1"); } catch (e) { threw = e.message; }
    ok(/wrong/.test(threw), "the old password no longer opens it");
    var rc2 = await clsRecoveryMake("a new password 2");
    ok(rc2 !== rc && srv.vault.wraps.filter(function (w) { return w.type === "recovery"; }).length === 1,
       "a new recovery code replaces the old one");
    await clsChange("a new password 2", "a third password");
    eq(srv.vault.wraps.map(function (w) { return w.type; }).sort().join(","), "passkey,password,recovery",
       "changing the password keeps the passkey and the recovery wraps");
    await clsPasskeyRemove(w1.cred);
    eq(srv.vault.wraps.map(function (w) { return w.type; }).sort().join(","), "password,recovery", "a passkey removed: only it");
    // the old one-wrap vault: unlocks as before
    srv.vault = { v: 1, kid: "k1", wraps: [{ type: "password", kdf: "PBKDF2-SHA256", iter: 600000, salt: "c2FsdA",
                                             iv: "aXY", wrapped: "pw:old faithful 9|MK" }] };
    await clsLock();
    await clsUnlock("old faithful 9");
    ok(clsOn() && cls.key.mk === "MK", "a phase-1 vault (one password wrap) unlocks exactly as before");
    threw = "";
    try { await clsPasskeyUnlock(); } catch (e) { threw = e.message; }
    ok(/no passkey/.test(threw), "and says it has no passkey when asked for one");
    ok(/Recovery code/.test(clsCfgHtml()) && /none/.test(clsCfgHtml()) && /data-cls="recmake"/.test(clsCfgHtml()),
       "Config offers a recovery code to a vault that has none");
    ok(/gone/.test(clsCfgHtml()), "and says what a lost password means");
    ok(/data-cls="pkadd"/.test(clsCfgHtml()), "and a passkey for this device");
    await clsLock();

    eq(vMatch(vWords("unlock with a passkey"), 0).cmd.say, "unlock with a passkey", "voice: unlock with a passkey");
    eq(vMatch(vWords("register a passkey"), 0).cmd.say, "register a passkey", "voice: register a passkey");
    eq(vMatch(vWords("use the recovery code"), 0).cmd.say, "use the recovery code", "voice: use the recovery code");
    eq(vMatch(vWords("make a recovery code"), 0).cmd.say, "make a recovery code", "voice: make a recovery code");
    eq(vMatch(vWords("recovery code"), 0).cmd.say, "use the recovery code", "voice: recovery code alone is the door");
    var csp = window.LCARS_CSP;
    ok(typeof csp === "string" && /^connect-src 'self' /.test(csp) && /wss:\/\/api\.deepgram\.com/.test(csp),
       "the page's CSP: connect-src 'self' and the services it names");
    apiNet = realApiNet;
    cls.vault = undefined;
    Object.assign(clsCrypto, realCrypto);
  })();

  console.log("\n-- the real database was never touched --");
  ok(TEST.fetches.every(function (f) { return f.indexOf("http") < 0; }), "all traffic was mocked");

  console.log("\nTOTAL: " + TEST.asserts + " assertions, " + TEST.fails.length + " failures");
  if (TEST.fails.length) { console.log("\nFAILURES:"); TEST.fails.forEach(function (f) { console.log("  - " + f); }); }
  console.log(TEST.fails.length ? "\nRESULT: FAIL" : "\nRESULT: PASS");
})().catch(function (e) { console.log("SUITE E THREW: " + e + "\n" + (e && e.stack)); });
