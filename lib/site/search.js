/* Search for the documentation site: one file, no libraries, no network beyond the index next to it.
   It fetches search-index.json from the folder this script is served from, so it works under any base path, and adds a
   search box at the top of the sidebar. Without it the page is complete: the box exists only once this has run. */
(function () {
  "use strict";
  var script = document.currentScript;
  var host = document.getElementById("sidebar");
  if (!script || !script.src || !host || !window.fetch || !window.URL) { return; }
  var indexUrl = new URL("search-index.json", script.src);
  var root = new URL("../", script.src);
  var LIMIT = 10;
  var entries = [];
  var shown = [];
  var active = -1;

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text) { e.textContent = text; }
    return e;
  }

  var box = el("div", "search");
  box.setAttribute("role", "search");
  var label = el("label", "search-label", "Search the documentation");
  label.htmlFor = "site-search";
  var input = el("input", "search-input");
  input.id = "site-search";
  input.type = "search";
  input.autocomplete = "off";
  input.spellcheck = false;
  input.placeholder = "Search";
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-controls", "search-results");
  input.setAttribute("aria-expanded", "false");
  var list = el("ul", "search-results");
  list.id = "search-results";
  list.setAttribute("role", "listbox");
  list.setAttribute("aria-label", "Search results");
  list.hidden = true;
  var status = el("p", "search-status");
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  box.appendChild(label);
  box.appendChild(input);
  box.appendChild(status);
  box.appendChild(list);

  function terms(q) {
    return q.toLowerCase().split(/\s+/).filter(function (w) { return w.length > 0; });
  }

  function score(e, ts) {
    var total = 0;
    for (var i = 0; i < ts.length; i++) {
      var t = ts[i];
      var inTitle = e.title.indexOf(t);
      var inText = e.text.indexOf(t);
      if (inTitle < 0 && inText < 0) { return 0; }
      if (inTitle === 0) { total += 12; }
      else if (inTitle > 0 && /[\s\-:\/]/.test(e.title.charAt(inTitle - 1))) { total += 10; }
      else if (inTitle > 0) { total += 6; }
      if (inText >= 0) { total += 2; }
    }
    if (e.title === ts.join(" ")) { total += 20; }
    if (!e.group) { total += 1; }
    return total;
  }

  function search(q) {
    var ts = terms(q);
    if (ts.length === 0) { return []; }
    var hits = [];
    for (var i = 0; i < entries.length; i++) {
      var s = score(entries[i], ts);
      if (s > 0) { hits.push({ e: entries[i], s: s, i: i }); }
    }
    hits.sort(function (a, b) { return b.s - a.s || a.i - b.i; });
    return hits.slice(0, LIMIT).map(function (h) { return h.e; });
  }

  function setActive(k) {
    var items = list.children;
    if (active >= 0 && items[active]) {
      items[active].removeAttribute("aria-selected");
      items[active].classList.remove("active");
    }
    active = k;
    if (k >= 0 && items[k]) {
      items[k].setAttribute("aria-selected", "true");
      items[k].classList.add("active");
      input.setAttribute("aria-activedescendant", items[k].id);
      if (items[k].scrollIntoView) { items[k].scrollIntoView({ block: "nearest" }); }
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  }

  function render() {
    var q = input.value;
    shown = search(q);
    while (list.firstChild) { list.removeChild(list.firstChild); }
    for (var i = 0; i < shown.length; i++) {
      var li = el("li", "search-result");
      li.id = "search-option-" + i;
      li.setAttribute("role", "option");
      var a = el("a", "", shown[i].raw.t);
      a.href = new URL(shown[i].raw.p, root).href;
      a.tabIndex = -1;
      li.appendChild(a);
      if (shown[i].group) { li.appendChild(el("span", "search-where", shown[i].raw.g)); }
      list.appendChild(li);
    }
    var searching = terms(q).length > 0;
    list.hidden = shown.length === 0;
    input.setAttribute("aria-expanded", shown.length > 0 ? "true" : "false");
    host.classList.toggle("searching", searching);
    status.textContent = !searching ? "" : shown.length === 0 ? "No results" : shown.length === 1 ? "1 result" : shown.length + " results";
    setActive(-1);
  }

  function clear() {
    input.value = "";
    render();
  }

  input.addEventListener("input", render);
  input.addEventListener("keydown", function (ev) {
    if (ev.key === "ArrowDown" && shown.length > 0) {
      ev.preventDefault();
      setActive(active + 1 >= shown.length ? 0 : active + 1);
    } else if (ev.key === "ArrowUp" && shown.length > 0) {
      ev.preventDefault();
      setActive(active <= 0 ? shown.length - 1 : active - 1);
    } else if (ev.key === "Enter" && shown.length > 0) {
      ev.preventDefault();
      window.location.href = new URL(shown[active < 0 ? 0 : active].raw.p, root).href;
    } else if (ev.key === "Escape") {
      ev.preventDefault();
      if (input.value === "") { input.blur(); } else { clear(); }
    }
  });

  fetch(indexUrl.href, { credentials: "same-origin" }).then(function (r) {
    if (!r.ok) { throw new Error("no index"); }
    return r.json();
  }).then(function (data) {
    if (!data || !Array.isArray(data.entries)) { throw new Error("bad index"); }
    entries = data.entries.map(function (e) {
      return { raw: e, title: String(e.t).toLowerCase(), text: String(e.x).toLowerCase(), group: e.g ? String(e.g) : "" };
    });
    host.insertBefore(box, host.firstChild);
  }).catch(function () { /* no index: the page works without search */ });
}());
