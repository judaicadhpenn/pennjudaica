/* ============================================================================
   Penn Judaica Portal — BETA · app.js
   Loads items.json (produced by build.py) and indexes it with MiniSearch.
   Features:
   - unified search (MiniSearch, prefix + fuzzy, ranked by score)
   - live facets + advanced search
   - map (Leaflet), timeline, highlights, saved
   - deep-zoom item viewer (OpenSeadragon, single-image mode)
   - URL hash state (shareable links) + persistent saved items (localStorage)
   ============================================================================ */
(function () {
  "use strict";
  // Populated by boot() once items.json is fetched.
  var SOURCES = {};
  var ITEMS = [];
  var FEATURED = [];
  var mini = null;          // MiniSearch instance — built once on boot
  var dataReady = false;    // gate render passes until items.json has arrived

  var FACET_FIELDS = [
    { key: "source", label: "Collection", fmt: function (v) { return SOURCES[v].label; }, dot: function (v) { return SOURCES[v].color; } },
    { key: "type",   label: "Format / type" },
    { key: "region", label: "Region of origin" },
    { key: "lang",   label: "Language" }
  ];
  function emptyAdv() { return { key: "", title: "", creator: "", from: null, to: null, lang: "", type: "", source: "", region: "", iiif: false }; }

  var PAGE_SIZE = 60;  // cards rendered per "page" in the results grid
  var state = {
    q: "", sort: "relevance",
    filters: { source: new Set(), type: new Set(), region: new Set(), lang: new Set() },
    adv: emptyAdv(),
    saved: new Set(),
    view: "search",
    page: 1
  };
  var map, markerLayer, osd, currentItemId = null, restoring = false;
  var viewerPages = [], viewerIndex = 0;

  var $ = function (id) { return document.getElementById(id); };
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }

  /* ---------------- persistent saved items ---------------- */
  var LS_KEY = "pjp_saved_v1";
  var lsOK = (function () { try { localStorage.setItem("__t", "1"); localStorage.removeItem("__t"); return true; } catch (e) { return false; } })();
  function loadSaved() { if (!lsOK) return; try { (JSON.parse(localStorage.getItem(LS_KEY)) || []).forEach(function (id) { state.saved.add(id); }); } catch (e) {} }
  function persistSaved() { if (!lsOK) return; try { localStorage.setItem(LS_KEY, JSON.stringify([].concat(Array.from(state.saved)))); } catch (e) {} }

  /* ---------------- filtering ---------------- */
  // MiniSearch handles full-text ranking for the main query and the
  // "Keywords (anywhere)" field in advanced search. Everything else is a
  // plain field check on the candidate set.
  function miniHits(q) {
    if (!q || !mini) return null;
    var hits = mini.search(q, {
      prefix: true, fuzzy: 0.2,
      boost: { title: 3, creator: 2, place: 1.5 }
    });
    return hits.map(function (h) { return h.id; });
  }
  function substringMatch(it, q) {
    if (!q) return true; q = q.toLowerCase();
    return [it.title, it.creator, it.desc, it.place, it.region, it.collection, it.lang, it.type, it.dateText, it.callno].join(" ").toLowerCase().indexOf(q) !== -1;
  }
  function passesFacets(it) { return FACET_FIELDS.every(function (f) { var s = state.filters[f.key]; return s.size === 0 || s.has(it[f.key]); }); }
  function passesAdv(it) {
    var a = state.adv;
    if (a.key && !substringMatch(it, a.key)) return false;  // also intersected with mini hits if state.q is set
    if (a.title && it.title.toLowerCase().indexOf(a.title.toLowerCase()) === -1) return false;
    if (a.creator && it.creator.toLowerCase().indexOf(a.creator.toLowerCase()) === -1) return false;
    if (a.from != null && it.year < a.from) return false;
    if (a.to != null && it.year > a.to) return false;
    if (a.lang && it.lang !== a.lang) return false;
    if (a.type && it.type !== a.type) return false;
    if (a.source && it.source !== a.source) return false;
    if (a.region && it.region !== a.region) return false;
    if (a.iiif && !it.iiif) return false;
    return true;
  }
  function filtered() {
    if (!dataReady) return [];
    var pool;
    var ids = miniHits(state.q);
    if (ids) {
      // MiniSearch returned ranked ids; preserve that order through filtering
      var byId = new Map(ITEMS.map(function (it) { return [it.id, it]; }));
      pool = ids.map(function (id) { return byId.get(id); }).filter(Boolean);
    } else {
      pool = ITEMS;
    }
    return pool.filter(function (it) { return passesFacets(it) && passesAdv(it); });
  }
  function sortItems(arr) {
    var s = state.sort, a = arr.slice();
    // "relevance" = whatever order pool arrived in.
    // With a query that's MiniSearch's ranking; without one, it's ITEMS order.
    if (s === "oldest") a.sort(function (x, y) { return x.year - y.year; });
    else if (s === "newest") a.sort(function (x, y) { return y.year - x.year; });
    else if (s === "title") a.sort(function (x, y) { return x.title.localeCompare(y.title); });
    return a;
  }

  /* ---------------- URL state (shareable) ---------------- */
  function writeHash() {
    if (restoring) return;
    var p = [];
    if (state.view && state.view !== "search") p.push("view=" + state.view);
    if (state.q) p.push("q=" + encodeURIComponent(state.q));
    FACET_FIELDS.forEach(function (f) {
      if (state.filters[f.key].size) p.push(f.key + "=" + encodeURIComponent(Array.from(state.filters[f.key]).join("|")));
    });
    if (state.sort !== "relevance") p.push("sort=" + state.sort);
    if (currentItemId != null) p.push("item=" + currentItemId);
    var h = p.join("&");
    if (("#" + h) !== location.hash) history.replaceState(null, "", h ? ("#" + h) : location.pathname + location.search);
  }
  function readHash() {
    restoring = true;
    var h = location.hash.replace(/^#/, "");
    state.q = ""; state.sort = "relevance"; state.view = "search";
    FACET_FIELDS.forEach(function (f) { state.filters[f.key] = new Set(); });
    var openItem = null, view = "search";
    if (h) h.split("&").forEach(function (pair) {
      var i = pair.indexOf("="); if (i < 0) return;
      var k = pair.slice(0, i), v = decodeURIComponent(pair.slice(i + 1));
      if (k === "q") state.q = v;
      else if (k === "sort") state.sort = v;
      else if (k === "view") view = v;
      else if (k === "item") openItem = parseInt(v, 10);
      else if (state.filters[k]) v.split("|").forEach(function (x) { if (x) state.filters[k].add(x); });
    });
    $("q").value = state.q; $("sortSel").value = state.sort;
    restoring = false;
    setView(view, true);
    if (openItem != null && ITEMS.some(function (x) { return x.id === openItem; })) openItem2(openItem, true);
  }

  /* ---------------- facets ---------------- */
  // Facet counts reflect "what other facet values would still be available
  // if the user picked one in this group?" — so each group is computed
  // against the candidate set with that group's filter relaxed.
  function buildFacets() {
    var host = $("facetGroups"); host.innerHTML = "";
    // Apply MiniSearch / no-query exactly once for all facet groups.
    var ids = miniHits(state.q);
    var byId = ids ? new Map(ITEMS.map(function (it) { return [it.id, it]; })) : null;
    var candidates = ids ? ids.map(function (id) { return byId.get(id); }).filter(Boolean) : ITEMS;
    candidates = candidates.filter(function (it) { return passesAdv(it); });
    FACET_FIELDS.forEach(function (f) {
      var pool = candidates.filter(function (it) {
        return FACET_FIELDS.every(function (g) { return g.key === f.key ? true : (state.filters[g.key].size === 0 || state.filters[g.key].has(it[g.key])); });
      });
      var counts = {}; pool.forEach(function (it) { counts[it[f.key]] = (counts[it[f.key]] || 0) + 1; });
      var vals = Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a] || a.localeCompare(b); });
      if (!vals.length) return;
      var g = document.createElement("div"); g.className = "facet-group";
      var html = "<h4>" + f.label + "</h4>";
      vals.forEach(function (v) {
        var checked = state.filters[f.key].has(v) ? "checked" : "";
        var lbl = f.fmt ? f.fmt(v) : v;
        var dot = f.dot ? '<span class="dot" style="background:' + f.dot(v) + '"></span>' : "";
        html += '<label class="facet-opt"><input type="checkbox" ' + checked + ' onchange="PJPapp.toggleFacet(\'' + f.key + "',this.dataset.v,this.checked)\" data-v=\"" + esc(v) + '">' + dot + "<span>" + esc(lbl) + '</span><span class="cnt">' + counts[v] + "</span></label>";
      });
      g.innerHTML = html; host.appendChild(g);
    });
  }
  function renderActiveFilters() {
    var host = $("activeFilters"); host.innerHTML = "";
    if (state.q) host.innerHTML += '<span class="pill">“' + esc(state.q) + '” <span class="x" onclick="PJPapp.clearQuery()">×</span></span>';
    FACET_FIELDS.forEach(function (f) {
      state.filters[f.key].forEach(function (v) {
        var lbl = f.fmt ? f.fmt(v) : v;
        host.innerHTML += '<span class="pill">' + esc(lbl) + ' <span class="x" onclick="PJPapp.removeFilter(\'' + f.key + "','" + esc(v) + '\')">×</span></span>';
      });
    });
    var a = state.adv;
    [a.key && ["key", "keyword: " + a.key], a.title && ["title", "title: " + a.title], a.creator && ["creator", "creator: " + a.creator],
     (a.from != null) && ["from", "from " + a.from], (a.to != null) && ["to", "to " + a.to], a.lang && ["lang", a.lang], a.type && ["type", a.type],
     a.region && ["region", a.region], a.source && ["source", SOURCES[a.source] ? SOURCES[a.source].label : a.source], a.iiif && ["iiif", "has images"]
    ].filter(Boolean).forEach(function (kv) {
      host.innerHTML += '<span class="pill" style="border-color:var(--plum)">' + esc(kv[1]) + ' <span class="x" onclick="PJPapp.clearAdvField(\'' + kv[0] + '\')">×</span></span>';
    });
  }

  /* ---------------- cards / render ---------------- */
  function card(it) {
    var s = SOURCES[it.source], saved = state.saved.has(it.id);
    return '<div class="card" onclick="PJPapp.openItem(' + it.id + ')">' +
      '<div class="thumb"><img loading="lazy" src="' + it.img + '" alt="' + esc(it.title) + '">' +
      '<button class="savemark ' + (saved ? "on" : "") + '" title="' + (saved ? "Saved" : "Save") + '" onclick="PJPapp.toggleSave(' + it.id + ',event)">' + (saved ? "♥" : "♡") + "</button></div>" +
      '<div class="card-body"><div class="ctype"><span class="dot" style="background:' + s.color + '"></span><span>' + esc(it.type) + " · " + esc(s.label) + "</span></div>" +
      "<h3>" + esc(it.title) + '</h3><div class="meta">' + esc(it.dateText) + " · " + esc(it.lang) + "</div></div></div>";
  }
  function render(keepPage) {
    if (!keepPage) state.page = 1;
    var res = sortItems(filtered());
    buildFacets(); renderActiveFilters(); refreshSavedUI();
    renderGrid(res);
    if (state.view === "map") drawMap(res);
    if (state.view === "timeline") drawTimeline(res);
    if (state.view === "highlights") drawHighlights();
    if (state.view === "saved") drawSaved();
    writeHash();
  }
  function renderGrid(res) {
    var total = res.length, shown = Math.min(total, state.page * PAGE_SIZE);
    $("shownCount").textContent = shown; $("matchCount").textContent = total;
    if (!total) {
      $("grid").innerHTML = '<div class="empty" style="grid-column:1/-1"><span class="big">⌕</span>No items match. Try removing a filter or searching a broader term.</div>';
      return;
    }
    var html = res.slice(0, shown).map(card).join("");
    if (shown < total) {
      var next = Math.min(PAGE_SIZE, total - shown);
      html += '<div class="loadmore" style="grid-column:1/-1"><button class="btn ghost" onclick="PJPapp.loadMore()">Load ' + next + ' more · ' + (total - shown) + ' remaining</button></div>';
    }
    $("grid").innerHTML = html;
  }
  function drawSaved() {
    var items = ITEMS.filter(function (it) { return state.saved.has(it.id); });
    $("savedGrid").innerHTML = items.length ? items.map(card).join("") :
      '<div class="empty" style="grid-column:1/-1"><span class="big">♡</span>You haven’t saved anything yet.<br>Tap the heart on any item to keep it here.</div>';
  }

  /* ---------------- saved ---------------- */
  function refreshSavedUI() {
    var n = state.saved.size;
    $("savedBadge").textContent = n; $("savedTabCount").textContent = n; $("savedCount2").textContent = n;
  }

  /* ---------------- map ---------------- */
  function ensureMap() {
    if (map) { setTimeout(function () { map.invalidateSize(); }, 60); return; }
    map = L.map("map", { scrollWheelZoom: true }).setView([30, 24], 2);
    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", { attribution: "&copy; OpenStreetMap &copy; CARTO", maxZoom: 18, subdomains: "abcd" }).addTo(map);
    // markerCluster groups nearby points so we never plot ~1700 markers at once
    markerLayer = (L.markerClusterGroup ? L.markerClusterGroup({
      maxClusterRadius: 48, showCoverageOnHover: false, chunkedLoading: true,
      iconCreateFunction: function (cluster) {
        var n = cluster.getAllChildMarkers().reduce(function (s, m) { return s + (m.options.count || 1); }, 0);
        var size = n < 10 ? 34 : n < 100 ? 42 : 50;
        return L.divIcon({ html: "<span>" + n + "</span>", className: "pjp-cluster", iconSize: [size, size] });
      }
    }) : L.layerGroup()).addTo(map);
  }
  function drawMap(items) {
    if (!map) return; markerLayer.clearLayers();
    var byCoord = {};
    items.forEach(function (it) {
      if (typeof it.lat !== "number" || typeof it.lng !== "number") return; // skip un-geocoded
      var key = it.lat.toFixed(2) + "," + it.lng.toFixed(2);
      var g = byCoord[key] || (byCoord[key] = { lat: it.lat, lng: it.lng, places: {}, items: [] });
      g.items.push(it); g.places[it.place] = 1;
    });
    Object.keys(byCoord).forEach(function (k) {
      var g = byCoord[k], n = g.items.length, size = n < 10 ? 30 : n < 100 ? 38 : 46;
      var marker = L.marker([g.lat, g.lng], {
        count: n,
        icon: L.divIcon({ html: "<span>" + n + "</span>", className: "pjp-dot", iconSize: [size, size] })
      });
      var places = Object.keys(g.places).slice(0, 4).join(", ");
      var list = g.items.slice(0, 6).map(function (it) { return '<span class="pop-link" onclick="PJPapp.openItem(' + it.id + ')">› ' + esc(it.title) + "</span>"; }).join("");
      var more = g.items.length > 6 ? '<div class="pop-meta">+ ' + (g.items.length - 6) + " more</div>" : "";
      marker.bindPopup('<div class="pop-title">' + esc(places) + '</div><div class="pop-meta">' + n + " item" + (n > 1 ? "s" : "") + "</div>" + list + more);
      markerLayer.addLayer(marker);
    });
    setTimeout(function () { map.invalidateSize(); }, 60);
  }

  /* ---------------- timeline ---------------- */
  var ERAS = [
    { from: 1,    to: 1099, yr: "Before 1100", nm: "Earliest Cairo Genizah fragments" },
    { from: 1100, to: 1299, yr: "1100s–1200s", nm: "The Genizah & the age of Maimonides" },
    { from: 1300, to: 1499, yr: "1300s–1400s", nm: "Late medieval manuscripts" },
    { from: 1500, to: 1599, yr: "1500s", nm: "Renaissance & the Ottoman world" },
    { from: 1600, to: 1699, yr: "1600s", nm: "Early modern Italy & the Ottoman world" },
    { from: 1700, to: 1799, yr: "1700s", nm: "Enlightenment & the early American republic" },
    { from: 1800, to: 2100, yr: "1800s–1900s", nm: "A Jewish world spanning four continents" },
    { from: 0,    to: 0,    yr: "Undated", nm: "Date not recorded in the source" }
  ];
  function drawTimeline(items) {
    var host = $("timeline"); host.innerHTML = "";
    ERAS.forEach(function (e) {
      var inEra = items.filter(function (it) { return it.year >= e.from && it.year <= e.to; }).sort(function (a, b) { return a.year - b.year; });
      // never show an empty "Undated" scaffold row
      if (e.to === 0 && !inEra.length) return;
      var row = document.createElement("div"); row.className = "era-row";
      var ERA_CAP = 48;
      var chips = inEra.slice(0, ERA_CAP).map(function (it) {
        var t = it.title.length > 40 ? it.title.slice(0, 38) + "…" : it.title;
        return '<div class="tl-item" onclick="PJPapp.openItem(' + it.id + ')"><div class="tlimg"><img loading="lazy" src="' + it.img + '" alt=""></div><div class="t">' + esc(t) + '</div><div class="d">' + esc(it.dateText) + "</div></div>";
      }).join("");
      if (inEra.length > ERA_CAP) chips += '<div class="d" style="align-self:center;color:#8c8270;padding:0 6px">+ ' + (inEra.length - ERA_CAP) + ' more in this era — narrow your search to see them</div>';
      if (!inEra.length) chips = '<div class="d" style="color:#bcb39c;align-self:center">— no items in current results —</div>';
      row.innerHTML = '<div class="era-label"><div class="yr">' + e.yr + '</div><div class="nm">' + e.nm + '</div></div><div class="era-items">' + chips + "</div>";
      host.appendChild(row);
    });
  }

  /* ---------------- highlights ---------------- */
  function drawHighlights() {
    $("highlights").innerHTML = FEATURED.map(function (id) {
      var it = ITEMS.filter(function (x) { return x.id === id; })[0]; var s = SOURCES[it.source];
      return '<div class="feature"><div class="fimg"><img loading="lazy" src="' + it.img + '" alt="' + esc(it.title) + '"></div>' +
        '<div class="fbody"><div class="ftype"><span class="dot" style="background:' + s.color + '"></span><span>' + esc(it.type) + " · " + esc(s.label) + "</span></div>" +
        "<h3>" + esc(it.title) + "</h3><p>" + esc(it.desc) + '</p><div class="fmeta">' + esc(it.dateText) + " · " + esc(it.collection) + " · " + esc(it.callno) + "</div>" +
        '<button class="btn" onclick="PJPapp.openItem(' + it.id + ')">Open record</button></div></div>';
    }).join("");
  }

  /* ---------------- item viewer + deep zoom ---------------- */
  // Per-item page shards (the multi-page filmstrip data) are lazy-loaded
  // on first open. items.json carries only the search/card fields, so the
  // initial page payload stays small.
  var pageCache = Object.create(null);   // id -> Promise<pages[]>
  function loadPages(id) {
    if (pageCache[id]) return pageCache[id];
    pageCache[id] = fetch("records/" + id + ".json", { cache: "default" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (rec) { return (rec && rec.pages) || []; })
      .catch(function () { return []; });
    return pageCache[id];
  }
  function openItem2(id, fromHash) {
    var it = ITEMS.filter(function (x) { return x.id === id; })[0]; if (!it) return;
    currentItemId = id; var s = SOURCES[it.source];
    $("mDot").style.background = s.color;
    $("mType").textContent = it.type;
    $("mTitle").textContent = it.title;
    $("mCreator").textContent = it.creator;
    $("mDesc").textContent = it.desc;
    $("mMeta").innerHTML =
      '<tr><td class="k">Date</td><td class="v">' + esc(it.dateText) + "</td></tr>" +
      '<tr><td class="k">Place</td><td class="v">' + esc(it.place) + "</td></tr>" +
      '<tr><td class="k">Language</td><td class="v">' + esc(it.lang) + "</td></tr>" +
      '<tr><td class="k">Format</td><td class="v">' + esc(it.type) + "</td></tr>" +
      '<tr><td class="k">Collection</td><td class="v">' + esc(it.collection) + "</td></tr>" +
      '<tr><td class="k">Call number</td><td class="v">' + esc(it.callno) + "</td></tr>";
    $("mSrc").innerHTML = "Discovered via the unified index · Record &amp; images live in <b>" + esc(s.label) + "</b>";
    $("mSrcLink").href = it.srcUrl;
    syncModalSave();
    $("modalBg").classList.add("open");
    if (!fromHash) writeHash();
    // Show the cover image immediately, then fetch the rest of the pages.
    viewerPages = it.img ? [{ img: it.img, thumb: it.img, label: "" }] : [];
    viewerIndex = 0;
    renderViewer();
    var requestedId = id;
    loadPages(id).then(function (pages) {
      if (currentItemId !== requestedId) return;  // user moved on
      if (pages && pages.length) {
        viewerPages = pages;
        viewerIndex = 0;
        renderViewer();
      }
    });
  }
  function renderViewer() {
    var pg = viewerPages[viewerIndex] || viewerPages[0];
    loadImage(pg.img, pg.label);
    var multi = viewerPages.length > 1;
    $("pageNav").style.display = multi ? "flex" : "none";
    $("filmstrip").classList.toggle("hide", !multi);
    $("pageCounter").textContent = (viewerIndex + 1) + " / " + viewerPages.length;
    $("pgPrev").disabled = viewerIndex === 0;
    $("pgNext").disabled = viewerIndex === viewerPages.length - 1;
    if (multi) {
      $("filmstrip").innerHTML = viewerPages.map(function (p, i) {
        return '<img src="' + p.thumb + '" title="' + esc(p.label || ("Page " + (i + 1))) + '" class="' + (i === viewerIndex ? "active" : "") + '" onclick="PJPapp.goToPage(' + i + ')">';
      }).join("");
    } else { $("filmstrip").innerHTML = ""; }
  }
  function loadImage(url, alt) {
    if (typeof OpenSeadragon === "undefined") {  // graceful fallback
      $("vfallback").style.display = "flex";
      $("mFallbackImg").src = url; $("mFallbackImg").alt = alt || "";
      return;
    }
    $("vfallback").style.display = "none";
    if (osd) { osd.open({ type: "image", url: url }); return; }
    osd = OpenSeadragon({
      id: "osd", prefixUrl: "https://cdnjs.cloudflare.com/ajax/libs/openseadragon/4.1.0/images/",
      tileSources: { type: "image", url: url },
      showNavigationControl: true, gestureSettingsMouse: { clickToZoom: true },
      visibilityRatio: 1, minZoomImageRatio: 0.8, maxZoomPixelRatio: 3, animationTime: 0.5, background: "#1c1710"
    });
  }
  function goToPage(i) { if (i < 0 || i >= viewerPages.length) return; viewerIndex = i; renderViewer(); }
  function closeModal() {
    $("modalBg").classList.remove("open");
    if (osd) { try { osd.close(); } catch (e) {} }
    currentItemId = null; writeHash();
  }
  function syncModalSave() {
    var el = $("mSave"), on = state.saved.has(currentItemId);
    el.classList.toggle("on", on); el.textContent = on ? "♥ Saved" : "♡ Save";
  }

  /* ---------------- advanced search ---------------- */
  function fillSelect(id, values, ph) { $(id).innerHTML = '<option value="">' + ph + "</option>" + values.map(function (v) { return '<option value="' + esc(v) + '">' + esc(v) + "</option>"; }).join(""); }
  function uniq(field) { var s = {}; ITEMS.forEach(function (i) { s[i[field]] = 1; }); return Object.keys(s).sort(); }
  function initAdvOptions() {
    fillSelect("aLang", uniq("lang"), "Any language");
    fillSelect("aType", uniq("type"), "Any format");
    fillSelect("aRegion", uniq("region"), "Any region");
    $("aSource").innerHTML = '<option value="">Any collection</option>' + Object.keys(SOURCES).map(function (k) { return '<option value="' + k + '">' + esc(SOURCES[k].label) + "</option>"; }).join("");
  }

  /* ---------------- view switching ---------------- */
  function setView(v, fromHash) {
    state.view = v;
    ["search", "map", "timeline", "highlights", "saved"].forEach(function (x) { $("view-" + x).style.display = (x === v) ? "" : "none"; });
    var tabs = document.querySelectorAll(".tab");
    for (var i = 0; i < tabs.length; i++) tabs[i].classList.toggle("active", tabs[i].getAttribute("data-v") === v);
    if (v === "map") { ensureMap(); drawMap(filtered()); }
    if (v === "timeline") drawTimeline(filtered());
    if (v === "highlights") drawHighlights();
    if (v === "saved") drawSaved();
    if (!fromHash) { writeHash(); window.scrollTo({ top: document.querySelector(".tabsbar").offsetTop - 4, behavior: "smooth" }); }
  }

  /* ---------------- toast ---------------- */
  var toastT;
  function toast(msg) { var t = $("toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(toastT); toastT = setTimeout(function () { t.classList.remove("show"); }, 2200); }

  /* ---------------- export saved ---------------- */
  function exportSaved() {
    var items = ITEMS.filter(function (it) { return state.saved.has(it.id); });
    if (!items.length) { toast("No saved items to export."); return; }
    var rows = items.map(function (it) { return { title: it.title, creator: it.creator, date: it.dateText, place: it.place, collection: it.collection, callNumber: it.callno, source: it.srcUrl }; });
    var blob = new Blob([JSON.stringify({ portal: "Penn Judaica Portal (beta)", exported: new Date().toISOString(), items: rows }, null, 2)], { type: "application/json" });
    var a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "penn-judaica-saved.json";
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    toast("Exported " + items.length + " saved item" + (items.length > 1 ? "s" : "") + ".");
  }

  /* ---------------- public API (for inline handlers) ---------------- */
  window.PJPapp = {
    doSearch: function () { state.q = $("q").value.trim(); setView("search"); render(); },
    quick: function (q) { $("q").value = q; this.doSearch(); },
    setView: function (v) { setView(v); render(); },
    setSort: function () { state.sort = $("sortSel").value; render(); },
    loadMore: function () { state.page++; render(true); },
    toggleFacet: function (key, val, on) { if (on) state.filters[key].add(val); else state.filters[key].delete(val); render(); },
    removeFilter: function (key, val) { state.filters[key].delete(val); render(); },
    clearQuery: function () { state.q = ""; $("q").value = ""; render(); },
    clearAll: function () { state.q = ""; $("q").value = ""; FACET_FIELDS.forEach(function (f) { state.filters[f.key] = new Set(); }); state.adv = emptyAdv(); render(); },
    clearAdvField: function (k) { state.adv[k] = (k === "iiif" ? false : (k === "from" || k === "to" ? null : "")); render(); },
    openItem: function (id) { openItem2(id); },
    closeModal: closeModal,
    prevPage: function () { goToPage(viewerIndex - 1); },
    nextPage: function () { goToPage(viewerIndex + 1); },
    goToPage: function (i) { goToPage(i); },
    toggleSave: function (id, ev) {
      if (ev) ev.stopPropagation();
      if (state.saved.has(id)) state.saved.delete(id); else state.saved.add(id);
      persistSaved(); refreshSavedUI(); render(); if (currentItemId === id) syncModalSave();
    },
    toggleSaveCurrent: function () { if (currentItemId != null) this.toggleSave(currentItemId); },
    clearSaved: function () { state.saved.clear(); persistSaved(); refreshSavedUI(); render(); },
    exportSaved: exportSaved,
    openAdv: function () {
      var a = state.adv;
      $("aKey").value = a.key; $("aTitle").value = a.title; $("aCreator").value = a.creator;
      $("aFrom").value = a.from == null ? "" : a.from; $("aTo").value = a.to == null ? "" : a.to;
      $("aLang").value = a.lang; $("aType").value = a.type; $("aRegion").value = a.region; $("aSource").value = a.source; $("aIiif").checked = a.iiif;
      $("advBg").classList.add("open");
    },
    closeAdv: function () { $("advBg").classList.remove("open"); },
    resetAdv: function () { ["aKey", "aTitle", "aCreator", "aFrom", "aTo", "aLang", "aType", "aRegion", "aSource"].forEach(function (id) { $(id).value = ""; }); $("aIiif").checked = false; },
    applyAdv: function () {
      var num = function (v) { v = parseInt(v, 10); return isNaN(v) ? null : v; };
      state.adv = {
        key: $("aKey").value.trim(), title: $("aTitle").value.trim(), creator: $("aCreator").value.trim(),
        from: num($("aFrom").value), to: num($("aTo").value), lang: $("aLang").value, type: $("aType").value,
        region: $("aRegion").value, source: $("aSource").value, iiif: $("aIiif").checked
      };
      this.closeAdv(); setView("search"); render();
    },
    copyLink: function () {
      var url = location.href;
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(url).then(function () { toast("Shareable link copied."); }, function () { toast("Link is in the address bar."); });
      else toast("Link is in the address bar.");
    }
  };

  /* ---------------- boot ---------------- */
  function buildMiniSearch() {
    // MiniSearch is loaded from CDN as a UMD global.
    if (typeof MiniSearch === "undefined") {
      console.warn("MiniSearch not loaded — full-text search will fall back to substring match.");
      mini = null;
      return;
    }
    mini = new MiniSearch({
      idField: "id",
      fields: ["title", "creator", "desc", "place", "region", "collection",
               "lang", "type", "dateText", "callno",
               "people", "corpnames", "subjects", "places"],
      storeFields: ["id"],
      extractField: function (doc, fieldName) {
        // Subject heading arrays (people/corpnames/subjects/places) flatten
        // to a single string so MiniSearch indexes each word.
        var v = doc[fieldName];
        if (Array.isArray(v)) return v.join(" ");
        return v == null ? "" : String(v);
      },
      searchOptions: { prefix: true, fuzzy: 0.2 }
    });
    mini.addAll(ITEMS);
  }

  function showLoading() {
    $("grid").innerHTML = '<div class="empty" style="grid-column:1/-1"><span class="big">⌕</span>Loading the Judaica index…</div>';
  }
  function showLoadError(err) {
    $("grid").innerHTML = '<div class="empty" style="grid-column:1/-1"><span class="big">⚠</span>Could not load items.json (' + (err && err.message ? err.message : err) + '). Try refreshing.</div>';
  }

  function bindDom() {
    loadSaved();
    refreshSavedUI();
    $("q").addEventListener("keydown", function (e) { if (e.key === "Enter") window.PJPapp.doSearch(); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { closeModal(); window.PJPapp.closeAdv(); return; }
      if ($("modalBg").classList.contains("open") && viewerPages.length > 1) {
        if (e.key === "ArrowRight") { e.preventDefault(); goToPage(viewerIndex + 1); }
        else if (e.key === "ArrowLeft") { e.preventDefault(); goToPage(viewerIndex - 1); }
      }
    });
    window.addEventListener("hashchange", function () { if (!restoring) readHash(); });
  }

  function boot() {
    bindDom();
    showLoading();
    fetch("items.json", { cache: "no-cache" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (payload) {
        SOURCES = payload.sources || {};
        ITEMS = payload.items || [];
        FEATURED = payload.featured || [];
        window.PJP = payload;  // back-compat: anything else on the page that expected window.PJP
        $("totalCount").textContent = ITEMS.length;
        buildMiniSearch();
        initAdvOptions();   // populates the advanced-search dropdowns
        dataReady = true;
        if (location.hash) readHash(); else { setView("search", true); }
        render();
      })
      .catch(function (err) {
        console.error("items.json failed to load:", err);
        showLoadError(err);
      });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
