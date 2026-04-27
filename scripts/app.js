/* ==========================================================================
   Discovery Navmap - Frontend Application
   All data parsing is done server-side in Go.
   This JS handles rendering, interaction, and UI.
   ========================================================================== */

(function () {
    "use strict";

    // --- State ---
    var currentSystemNickname = "Sirius";
    var systemScaleFactor = 1;
    var clickHandlersEnabled = true;
    var currentSystemName = "";
    var dragSinceLastMouseUp = 0;
    var lastX = 0, lastY = 0;

    // Data from server (injected in template)
    var systems = serverData.systems || {};
    var connections = serverData.connections || [];
    var searchItems = serverData.searchItems || [];
    var oorpSystems = serverData.oorpSystems || {};

    // Pre-cached system details
    var systemDetailCache = {};

    // Pre-loaded infocard and faction data (for static deployment)
    var infocardCache = {};
    var factionCache = {};
    var factionHashToName = {}; // Maps FLHash(factionNickname) → display name

    // POB data indexed by system nickname
    var pobsBySystem = {};

    // Decoded texture cache - keeps Image objects alive so browser retains decoded pixels
    var textureCache = {};

    function escapeHtml(str) {
        if (!str) return "";
        return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    // --- FLHash (Freelancer nickname hash) ---
    // CRC-32 with polynomial 0xA001 << 14 = 0x28004000, then byte-reverse + shift + set high bit.
    // Reference: darklab8/fl-darkstat flhash.py / flhash_nick.go
    var FLHashTable = (function () {
        var POLY = 0x28004000; // 0xA001 << (30 - 16)
        var table = new Array(256);
        for (var i = 0; i < 256; i++) {
            var crc = i;
            for (var bit = 0; bit < 8; bit++) {
                if (crc & 1) {
                    crc = (crc >>> 1) ^ POLY;
                } else {
                    crc = crc >>> 1;
                }
            }
            table[i] = crc;
        }
        return table;
    })();

    function flHash(nick) {
        var hash = 0;
        var nickLower = nick.toLowerCase();
        for (var i = 0; i < nickLower.length; i++) {
            hash = (hash >>> 8) ^ FLHashTable[(hash & 0xFF) ^ nickLower.charCodeAt(i)];
        }
        // byte-reverse
        hash = ((hash >>> 24) & 0xFF) |
               ((hash >>> 8) & 0x0000FF00) |
               ((hash << 8) & 0x00FF0000) |
               ((hash << 24) & 0xFF000000);
        hash = hash >>> 0; // ensure unsigned
        // right-shift by 2 and set high bit
        hash = ((hash >>> 2) | 0x80000000) >>> 0;
        return hash;
    }

    // Build reverse map: hash (number) → system nickname (string)
    var hashToNickname = {};
    (function buildHashToNickname() {
        for (var nick in systems) {
            if (systems.hasOwnProperty(nick)) {
                hashToNickname[flHash(nick)] = nick;
            }
        }
    })();

    // Fetch PoBs from the Discovery GC API
    function getPoBBases() {
        var url = "https://discoverygc.com/forums/base_admin.php?action=getjson";
        return fetch(url)
            .then(function (res) { return res.json(); })
            .then(function (data) {
                var bases = data.bases || {};
                var result = [];
                var names = Object.keys(bases);
                for (var i = 0; i < names.length; i++) {
                    var name = names[i];
                    var base = bases[name];
                    var parts = (base.pos || "0, 0, 0").split(",");
                    var x = Number(parts[0].trim()) || 0;
                    var y = Number(parts[1] ? parts[1].trim() : "0") || 0;
                    var z = Number(parts[2] ? parts[2].trim() : "0") || 0;
                    var sysNick = hashToNickname[base.system] || "";
                    result.push({
                        name: name,
                        pos: [x, y, z],
                        systemNickname: sysNick,
                        affiliation: base.affiliation,
                        defenseMode: base.defensemode,
                        infotext: base.infocard_paragraphs || [],
                        hostileTags: base.hostile_tag_list || "",
                        hostileNames: base.hostile_name_list || "",
                        allyTags: base.ally_tag_list || "",
                        allyNames: base.ally_name_list || ""
                    });
                }
                // Merge faction names from darkstat
                return fetch("https://darkstat.dd84ai.com/api/pobs")
                    .then(function (r) { return r.json(); })
                    .then(function (dsData) {
                        var nameMap = {};
                        for (var d = 0; d < dsData.length; d++) {
                            var dp = dsData[d];
                            var fn = dp.faction_name || "";
                            if (fn) {
                                var key = ((dp.system_nickname || "") + "|" + (dp.name || "")).toLowerCase();
                                nameMap[key] = fn;
                            }
                        }
                        for (var r2 = 0; r2 < result.length; r2++) {
                            var key2 = (result[r2].systemNickname + "|" + result[r2].name).toLowerCase();
                            if (nameMap[key2]) result[r2].factionName = nameMap[key2];
                        }
                        return result;
                    })
                    .catch(function () { return result; });
            });
    }

    // --- DOM References ---
    var mapEl = document.querySelector(".map");
    var contentsEl = document.querySelector(".contents");
    var gridEl = document.querySelector(".grid");

    // --- Panzoom Setup ---
    var panzoom = Panzoom(mapEl, {
        maxScale: 5,
        minScale: 1,
        panOnlyWhenZoomed: false,
        canvas: true,
        contain: "outside",
        handleStartEvent: function (e) { e.preventDefault(); }
    });

    var zoomInThreshold = 1.3;
    var lastScale = 1;
    var constraintsCache = null;

    mapEl.parentElement.addEventListener("wheel", panzoom.zoomWithWheel);

    mapEl.addEventListener("panzoomchange", function (event) {
        var fn = event.detail.scale === 1 ? shiftGrid : function () {
            requestAnimationFrame(function () { shiftGrid(event); });
        };
        fn(event);

        document.body.setAttribute("data-mapscale", event.detail.scale);
        if (event.detail.scale > zoomInThreshold) {
            document.body.classList.add("zoomedIn");
        } else {
            document.body.classList.remove("zoomedIn");
        }

        // Re-resolve label overlaps after zoom/pan
        if (currentSystemNickname !== "Sirius") scheduleLabelResolve();
    });

    mapEl.addEventListener("panzoompan", function (event) {
        var dx = lastX - event.detail.x;
        var dy = lastY - event.detail.y;
        dragSinceLastMouseUp += dx * dx + dy * dy;
        lastX = event.detail.x;
        lastY = event.detail.y;
    });

    contentsEl.addEventListener("click", function () {
        setTimeout(function () { dragSinceLastMouseUp = 0; }, 10);
    });
    document.addEventListener("click", function () {
        setTimeout(function () { dragSinceLastMouseUp = 0; }, 10);
    });

    // --- Right-click to copy /wp command ---
    contentsEl.addEventListener("contextmenu", function (e) {
        var target = e.target.closest("[data-coords]");
        if (!target) return;
        e.preventDefault();
        var coords = target.dataset.coords;
        if (!coords) return;
        var parts = coords.split(",").map(function (s) { return s.trim(); });
        if (parts.length < 3) return;
        var wpCmd = "/wp " + Math.round(parts[0]) + " " + Math.round(parts[1]) + " " + Math.round(parts[2]);
        navigator.clipboard.writeText(wpCmd).then(function () {
            showWaypointCopy(wpCmd);
        }).catch(function () {
            // Fallback for older browsers
            var ta = document.createElement("textarea");
            ta.value = wpCmd;
            ta.style.position = "fixed";
            ta.style.left = "-9999px";
            document.body.appendChild(ta);
            ta.select();
            document.execCommand("copy");
            document.body.removeChild(ta);
            showWaypointCopy(wpCmd);
        });
    });

    function showWaypointCopy(text) {
        var existing = document.querySelector(".wpCopyNotification");
        if (existing) existing.remove();
        var el = document.createElement("div");
        el.className = "wpCopyNotification";
        el.textContent = "Copied: " + text;
        document.body.appendChild(el);
        setTimeout(function () { el.remove(); }, 2000);
    }

    function hasNotPannedRecently() {
        return dragSinceLastMouseUp < 10;
    }

    function getDimensions(elem) {
        var parent = elem.parentNode;
        var re = elem.getBoundingClientRect();
        var rp = parent.getBoundingClientRect();
        return {
            elem: { width: re.width, height: re.height, top: re.top, bottom: re.bottom, left: re.left, right: re.right },
            parent: { width: rp.width, height: rp.height, top: rp.top, bottom: rp.bottom, left: rp.left, right: rp.right }
        };
    }

    function getConstraints(element, scale) {
        var dims = getDimensions(element);
        var rw = dims.elem.width / scale;
        var rh = dims.elem.height / scale;
        var sw = rw * scale;
        var sh = rh * scale;
        var dh = (sw - rw) / 2;
        var dv = (sh - rh) / 2;
        return {
            minX: (-(sw - dims.parent.width) + dh) / scale,
            maxX: dh / scale,
            minY: (-(sh - dims.parent.height) + dv) / scale,
            maxY: dv / scale
        };
    }

    function shiftGrid(event) {
        var detail = event.detail || event;
        if (!constraintsCache || lastScale !== detail.scale) {
            lastScale = detail.scale;
            constraintsCache = getConstraints(mapEl, detail.scale);
        }
        var c = constraintsCache;
        document.querySelectorAll(".vertGridLine h3").forEach(function (el) {
            el.style.transform = "translateY(" + (-1 * detail.y + c.maxY) + "px)";
        });
        document.querySelectorAll(".hzGridLine h3").forEach(function (el) {
            el.style.transform = "translateX(" + (-1 * detail.x + c.maxX) + "px)";
        });
    }

    // --- URI Hash Management ---
    var URIHash = {
        dump: function () {
            var hash = location.hash;
            if (!hash || hash.length === 0) return {};
            var result = {};
            hash.substring(1).split("&").forEach(function (pair) {
                var kv = pair.split("=");
                if (kv.length === 2) result[decodeURIComponent(kv[0])] = decodeURIComponent(kv[1]);
            });
            return result;
        },
        get: function (key) { return this.dump()[key]; },
        set: function (key, value) {
            var dump = this.dump();
            dump[key] = value;
            var pairs = [];
            for (var k in dump) pairs.push(encodeURIComponent(k) + "=" + encodeURIComponent(dump[k]));
            location.hash = pairs.join("&");
        }
    };

    function updateFragment(param, data) {
        if (location.hash.indexOf("=") === -1) location.hash = "";
        URIHash.set(param, data);
    }

    // --- Cookie/LocalStorage Settings ---
    function saveSettings() {
        var settings = { _version: 2 };
        document.querySelectorAll("input[type='checkbox']").forEach(function (cb) {
            settings[cb.id] = cb.checked;
        });
        try { localStorage.setItem("navmapSettings", JSON.stringify(settings)); } catch (e) { }
    }

    function loadSettings() {
        try {
            var SETTINGS_VERSION = 2;
            var settings = JSON.parse(localStorage.getItem("navmapSettings")) || {};
            var savedVersion = settings._version || 0;
            if (savedVersion < SETTINGS_VERSION) {
                // Reset settings that changed defaults
                settings["switch1"] = false;   // wrecks: off by default
                settings["switch20"] = true;   // pobs: on by default
                settings._version = SETTINGS_VERSION;
            }
            for (var id in settings) {
                if (id === "_version") continue;
                var el = document.getElementById(id);
                if (el) el.checked = settings[id];
            }
            saveSettings();
        } catch (e) { }
    }

    // --- Config Menu ---
    document.getElementById("configButton").addEventListener("click", function (e) {
        document.querySelector(".configMenu").classList.toggle("closed");
        e.stopPropagation();
    });

    document.querySelectorAll("input[type='checkbox']").forEach(function (cb) {
        cb.addEventListener("change", function () {
            saveSettings();
            updateConfigClasses();
        });
    });

    function isChecked(optionId) {
        var el = document.querySelector(".configOption#" + optionId + " input");
        return el && el.checked;
    }

    function updateConfigClasses() {
        toggleClass(".object.wreck", "hidden", !isChecked("wrecks"));
        toggleClass(".object.wreck label", "hidden", !isChecked("wreckLabels"));
        toggleClass(".object.pob", "hidden", !isChecked("pobs"));
        toggleClass(".zone", "hidden", !isChecked("zones"));
        toggleClass(".zone label:not(.mineable label)", "hidden", !isChecked("zoneLabels"));
        toggleClass(".oorp", "hidden", !isChecked("oorp"));

        if (isChecked("fitToWindow")) document.body.classList.add("fitToWindow");
        else document.body.classList.remove("fitToWindow");

        if (isChecked("showInternalNicknames")) contentsEl.classList.add("showInternalNicknames");
        else contentsEl.classList.remove("showInternalNicknames");

        if (isChecked("onlyShowLatestPosition")) contentsEl.classList.remove("showOldPlayerShipPositions");
        else contentsEl.classList.add("showOldPlayerShipPositions");

        var isUniverse = currentSystemNickname === "Sirius";

        if (isChecked("connections") && isUniverse) {
            document.querySelectorAll(".systemConnectionProp").forEach(function (el) { el.style.display = ""; });
        } else {
            document.querySelectorAll(".systemConnectionProp").forEach(function (el) { el.style.display = "none"; });
        }

        if (isChecked("universeLabels") && isUniverse) {
            contentsEl.querySelectorAll("div label").forEach(function (el) { el.classList.remove("labelDisabled"); });
        } else if (isUniverse) {
            contentsEl.querySelectorAll("div label").forEach(function (el) { el.classList.add("labelDisabled"); });
        }

        if (isChecked("systemLabels") && !isUniverse) {
            contentsEl.querySelectorAll("div label").forEach(function (el) { el.classList.remove("labelDisabled"); });
        } else if (!isUniverse) {
            contentsEl.querySelectorAll("div label").forEach(function (el) { el.classList.add("labelDisabled"); });
        }

        if (isChecked("showAllObjects") && !isUniverse) contentsEl.classList.add("showAllObjects");
        else contentsEl.classList.remove("showAllObjects");

        if (isChecked("showAllObjectLabels") && !isUniverse) contentsEl.classList.add("showAllObjectLabels");
        else contentsEl.classList.remove("showAllObjectLabels");

        if (isChecked("showInfocardedObjectLabels") && !isUniverse) contentsEl.classList.add("showInfocardedObjectLabels");
        else contentsEl.classList.remove("showInfocardedObjectLabels");

        hAlignLabels();
        objectTerritorialConflictResolver();
    }

    function toggleClass(selector, cls, add) {
        document.querySelectorAll(selector).forEach(function (el) {
            if (add) el.classList.add(cls);
            else el.classList.remove(cls);
        });
    }

    // --- Label Horizontal Alignment ---
    function hAlignLabels() {
        var labels = contentsEl.querySelectorAll("label");
        // Batch read all widths first (avoids layout thrashing)
        var widths = new Array(labels.length);
        for (var i = 0; i < labels.length; i++) {
            widths[i] = labels[i].offsetWidth;
        }
        // Batch write all styles
        for (var i = 0; i < labels.length; i++) {
            labels[i].style.marginLeft = "-" + (widths[i] / 2) + "px";
            labels[i].style.left = "50%";
            labels[i].style.position = "absolute";
        }
    }

    // --- Label Overlap Prevention ---
    var _labelResolveTimer = null;
    function scheduleLabelResolve() {
        if (_labelResolveTimer) clearTimeout(_labelResolveTimer);
        _labelResolveTimer = setTimeout(function () {
            _labelResolveTimer = null;
            objectTerritorialConflictResolver();
        }, 120);
    }

    function objectTerritorialConflictResolver() {
        // Reset marginTop from previous runs
        contentsEl.querySelectorAll("label[style*='margin-top']").forEach(function (el) {
            el.style.marginTop = "";
        });
        var labels = contentsEl.querySelectorAll("label:not(.hidden):not(.labelDisabled)");
        if (!labels.length || !isChecked("labelMove")) return;
        var n = labels.length;
        var arr = new Array(n);
        var rects = new Array(n);
        var margins = new Array(n);
        // Single DOM read pass
        for (var j = 0; j < n; j++) {
            arr[j] = labels[j];
            rects[j] = labels[j].getBoundingClientRect();
            margins[j] = 0;
        }
        // Iterative relaxation: push overlapping labels down
        var currentDiffSum = -1, prevDiffSum = -1, prevPrevDiffSum;
        for (var iter = 0; iter < 8; iter++) {
            prevPrevDiffSum = prevDiffSum;
            prevDiffSum = currentDiffSum;
            currentDiffSum = 0;
            for (var i = 0; i < n; i++) {
                var curRect = rects[i];
                for (var o = 0; o < n; o++) {
                    if (o === i) continue;
                    var otherRect = rects[o];
                    if (curRect.right < otherRect.left || curRect.left > otherRect.right ||
                        curRect.bottom < otherRect.top || curRect.top > otherRect.bottom) continue;
                    if (curRect.top <= otherRect.top) {
                        var shift = curRect.bottom - otherRect.top;
                        margins[o] = Math.abs(margins[o] + shift);
                        rects[o] = { top: otherRect.top + shift, bottom: otherRect.bottom + shift,
                            left: otherRect.left, right: otherRect.right };
                        currentDiffSum += shift;
                    } else {
                        var shift = otherRect.bottom - curRect.top;
                        margins[i] = Math.abs(margins[i] + shift);
                        rects[i] = { top: curRect.top + shift, bottom: curRect.bottom + shift,
                            left: curRect.left, right: curRect.right };
                        curRect = rects[i];
                        currentDiffSum += shift;
                    }
                }
            }
            if (prevPrevDiffSum === 0) break;
        }
        // Single DOM write pass
        for (var j = 0; j < n; j++) {
            if (margins[j] > 0) {
                arr[j].style.marginTop = margins[j] + "px";
            }
        }
    }

    // --- Loading Overlay ---
    function showLoading(text) {
        removeLoading();
        panzoom.reset();
        var loader = document.createElement("div");
        loader.className = "loadingOverlay";
        loader.innerHTML = "<div class='loadTextContainer'><h2 class='loaderTitle'>" + (text || "Loading...") + "</h2><div class='loader'></div></div>";
        document.body.appendChild(loader);
    }

    function removeLoading() {
        var el = document.querySelector(".loadingOverlay");
        if (el) el.remove();
    }

    // --- Highlight Animation ---
    function createHighlight(element) {
        document.querySelectorAll(".highlighter").forEach(function (el) { el.remove(); });
        if (!element) return;
        var hl = document.createElement("div");
        hl.className = "highlighter";
        element.appendChild(hl);
        requestAnimationFrame(function () {
            var rect = element.getBoundingClientRect();
            var mapRect = mapEl.getBoundingClientRect();
            panzoom.zoomToPoint(1.25, {
                clientX: rect.left + rect.width / 2,
                clientY: rect.top + rect.height / 2
            }, { animate: true });
        });
        hl.addEventListener("mouseover", function () { hl.remove(); });
    }

    // --- Connection Lines ---
    function drawLine(x1, x2, y1, y2, lineClass, propClass, container, obj1, obj2) {
        var parent = document.querySelector(container);
        var xDiff = x1 - x2;
        var yDiff = y1 - y2;
        var xAvg = (x1 + x2) / 2;
        var yAvg = (y1 + y2) / 2;
        var len = Math.sqrt(xDiff * xDiff + yDiff * yDiff);

        var pivot = document.createElement("div");
        pivot.className = lineClass + " " + propClass;
        pivot.style.left = yAvg + "%";
        pivot.style.top = xAvg + "%";
        pivot.style.height = len + "%";
        pivot.style.marginTop = (-len / 2) + "%";
        pivot.style.position = "absolute";
        pivot.dataset.connectedPoints = obj1 + " " + obj2;
        pivot.style.transform = "rotate(" + (-Math.atan2(yDiff, xDiff)) + "rad)";

        var line = document.createElement("div");
        line.style.height = "100%";
        line.style.position = "absolute";
        line.className = propClass;

        pivot.appendChild(line);
        parent.appendChild(pivot);
    }

    // --- Universe Map ---
    function generateUniverseMap() {
        showLoading("Generating map...");

        try {
            var showAll = document.getElementById("showUniverseMap");
            if (showAll) showAll.style.display = "none";
            gridEl.querySelectorAll(":scope > *").forEach(function (el) { el.style.display = "none"; });
            var legend = document.querySelector(".mapLegend");
            if (legend) legend.style.display = "block";
            var help = document.getElementById("helpLink");
            if (help) help.style.display = "block";
            var navTitle = document.getElementById("navSystemTitle");
            if (navTitle) navTitle.style.display = "none";
            var search = document.getElementById("searchField");
            if (search) search.value = "";

        currentSystemNickname = "Sirius";
        gridEl.style.background = "url('./images/Sirius_Map.png') black";
        gridEl.style.backgroundSize = "cover";

        // Clear contents except connections
        contentsEl.style.visibility = "hidden";
        contentsEl.querySelectorAll(":scope > *:not(.systemConnectionProp)").forEach(function (el) { el.remove(); });

        // System title
        var title = document.querySelector(".systemTitle") || document.createElement("h2");
        title.innerHTML = "Sirius";
        title.className = "systemTitle";
        gridEl.appendChild(title);

        // Dark overlay
        if (!document.querySelector(".darkOverlay")) {
            var overlay = document.createElement("div");
            overlay.className = "darkOverlay";
            gridEl.appendChild(overlay);
        }

        // Remove scale
        var mapScale = document.querySelector(".mapScale");
        if (mapScale) mapScale.remove();

        // Render systems
        for (var nick in systems) {
            var sys = systems[nick];
            if (!sys.name || nick.indexOf("sector") !== -1) continue;

            var div = document.createElement("div");
            div.dataset.systemNickname = nick;
            div.className = "system " + (sys.class || "");
            if (sys.oorp) div.className += " oorp";

            var label = document.createElement("label");
            label.textContent = sys.name;
            div.appendChild(label);

            div.style.top = (sys.pos[1] * 6.6 - 50) + "%";
            div.style.left = (sys.pos[0] * 6.6 - 50) + "%";
            div.style.position = "absolute";

            div.addEventListener("click", (function (n) {
                return function () { generateSystemMap(n); };
            })(nick));

            // Hover highlights for connections
            div.addEventListener("mouseenter", (function (n) {
                return function () {
                    document.querySelectorAll("[data-connected-points*='" + n + "'] > .systemConnectionProp").forEach(function (el) {
                        el.classList.add("highlightedConnection");
                    });
                };
            })(nick));
            div.addEventListener("mouseleave", function () {
                document.querySelectorAll(".highlightedConnection").forEach(function (el) {
                    el.classList.remove("highlightedConnection");
                });
            });

            contentsEl.appendChild(div);
        }

        // Draw connections
        if (!document.querySelector(".systemConnectionProp")) {
            generateSystemConnections();
        }

        contentsEl.style.visibility = "";
        removeLoading();
        hAlignLabels();
        updateConfigClasses();
        // No objectTerritorialConflictResolver on universe map (matches original behavior)
        } catch (e) {
            console.error("generateUniverseMap error:", e);
            removeLoading();
        }
    }

    function generateSystemConnections() {
        connections.forEach(function (conn) {
            var from = systems[conn.from];
            var to = systems[conn.to];
            if (!from || !to || !from.pos || !to.pos) return;

            var x1 = from.pos[1] * 6.6 - 50;
            var x2 = to.pos[1] * 6.6 - 50;
            var y1 = from.pos[0] * 6.6 - 50;
            var y2 = to.pos[0] * 6.6 - 50;

            var propClass = "systemConnectionProp";
            if (oorpSystems[conn.from] || oorpSystems[conn.to]) propClass += " oorp";
            if (conn.jgOnly || conn.hasJG) propClass += " jgConnection";

            var lineClass = "systemConnection";
            if (conn.oneWay) lineClass += " oneWayConnection";
            else lineClass += " twoWayConnection";
            if (conn.jgOnly || conn.hasJG) lineClass += " jgConnection";

            drawLine(x1, x2, y1, y2, lineClass, propClass, ".contents", conn.from, conn.to);
        });
    }

    // --- System Map ---
    function generateSystemMap(systemNickname) {
        systemNickname = systemNickname.toLowerCase();
        showLoading("Generating map...");

        document.getElementById("showUniverseMap").style.display = "block";
        document.getElementById("navSystemTitle").style.display = "block";
        document.getElementById("helpLink").style.display = "none";
        gridEl.querySelectorAll(":scope > *").forEach(function (el) { el.style.display = ""; });
        document.querySelectorAll(".systemConnectionProp").forEach(function (el) { el.style.display = "none"; });
        document.querySelector(".mapLegend").style.display = "none";
        document.getElementById("searchField").value = "";

        currentSystemNickname = systemNickname;
        var darkOverlay = document.querySelector(".darkOverlay");
        if (darkOverlay) darkOverlay.remove();
        gridEl.style.background = "black";

        // Hide contents during DOM teardown/rebuild to prevent intermediate repaints
        contentsEl.style.visibility = "hidden";
        contentsEl.querySelectorAll(":scope > *:not(.systemConnectionProp)").forEach(function (el) { el.remove(); });
        contentsEl.dataset.systemNickname = systemNickname;

        // Use cached data (all systems are pre-loaded on init)
        if (systemDetailCache[systemNickname]) {
            renderSystemDetail(systemDetailCache[systemNickname]);
        } else {
            console.error("System not in cache:", systemNickname);
            removeLoading();
        }
    }

    function renderSystemDetail(detail) {
        var sys = detail.system;
        var scaleFactor = sys.scaleFactor || 1;
        systemScaleFactor = scaleFactor;
        currentSystemName = sys.name;

        // Set ambient color
        if (detail.ambientColor) {
            gridEl.style.background = detail.ambientColor;
        }

        // Scale indicator
        var mapScale = document.querySelector(".mapScale") || createMapScale();
        var baseSize = isChecked("scale") ? 30 : 27.5;
        var scaleText = (Math.round(baseSize / scaleFactor * 10) / 10) + "K";
        mapScale.querySelector("h2").textContent = scaleText;

        // System title
        var title = document.querySelector(".systemTitle") || document.createElement("h2");
        title.innerHTML = sys.name;
        title.className = "systemTitle";
        gridEl.appendChild(title);

        document.getElementById("navSystemTitle").textContent = "Current System: " + sys.name;
        updateFragment("q", sys.name);

        // Render zones and objects using DocumentFragment for batch DOM insert
        var frag = document.createDocumentFragment();

        (detail.zones || []).forEach(function (zone) {
            renderZone(zone, scaleFactor, frag);
        });

        // Render objects
        (detail.objects || []).forEach(function (obj) {
            renderObject(obj, scaleFactor, frag);
        });

        // Render POBs for this system (wrapped to prevent errors from breaking the map)
        try {
            var sysNick = currentSystemNickname.toLowerCase();
            var sysPobs = pobsBySystem[sysNick] || [];
            console.log("Rendering " + sysPobs.length + " POBs for " + sysNick);
            for (var pi = 0; pi < sysPobs.length; pi++) {
                renderPOB(sysPobs[pi], scaleFactor, frag);
            }
        } catch (e) { console.error("POB render error:", e); }

        contentsEl.appendChild(frag);

        // Make contents visible now that all elements are placed
        contentsEl.style.visibility = "";

        removeLoading();
        updateConfigClasses();
        // Defer label layout to next frame so the map paints immediately
        requestAnimationFrame(function () {
            hAlignLabels();
            objectTerritorialConflictResolver();
        });
    }

    function createMapScale() {
        var ms = document.createElement("div");
        ms.className = "mapScale";
        var arL = document.createElement("div"); arL.className = "arrowHead arrowL";
        var arR = document.createElement("div"); arR.className = "arrowHead arrowR";
        var h2 = document.createElement("h2");
        ms.appendChild(arR);
        ms.appendChild(arL);
        ms.appendChild(h2);
        gridEl.appendChild(ms);
        return ms;
    }

    function renderZone(zone, sf, container) {
        var div = document.createElement("div");
        div.className = "zone";
        div.dataset.internalNickname = zone.nickname;

        if (zone.idsName) div.dataset.idsName = zone.idsName;
        if (zone.idsInfo) div.dataset.idsInfo = zone.idsInfo;

        if (!zone.idsName) div.classList.add("noName");
        if (!zone.idsInfo) div.classList.add("noInfo");
        if (zone.zoneClass) div.classList.add(zone.zoneClass);
        else div.classList.add("noZoneType");

        if (zone.shape === "ellipsoid" || zone.shape === "sphere") div.classList.add("roundZone");
        else if (zone.shape === "cylinder") div.classList.add("cylinderZone");
        else if (zone.shape === "box") div.classList.add("boxZone");

        var label = document.createElement("label");
        label.textContent = zone.name || "";
        div.appendChild(label);

        // Position
        div.style.position = "absolute";
        div.style.top = (zone.pos[2] / 2000 * sf) + "%";
        div.style.left = (zone.pos[0] / 2000 * sf) + "%";
        div.dataset.zPos = zone.pos[1] * sf;

        // Store game coords for tooltip
        div.dataset.coords = zone.pos[0] + ", " + zone.pos[1] + ", " + zone.pos[2];

        // Size
        var isExcl = zone.zoneFlags === 131072;
        var w, h;
        if (isExcl) {
            h = sf * zone.size[2] / 2000;
            w = sf * zone.size[0] / 2000;
        } else {
            h = sf * zone.size[2] / 1000;
            w = sf * zone.size[0] / 1000;
        }
        div.style.height = h + "%";
        div.style.width = w + "%";

        var zIdx = Math.floor(-sf * zone.size[2] / 1000 * sf * zone.size[0] / 1000);
        if (zone.shape === "sphere") {
            div.style.height = div.style.width;
            zIdx = Math.floor(-sf * zone.size[0] / 1000 * sf * zone.size[0] / 1000);
        }
        div.style.zIndex = zIdx;

        if (isExcl) {
            div.style.marginTop = (-sf * zone.size[2] / 4000) + "%";
            div.style.marginLeft = (-sf * zone.size[0] / 4000) + "%";
        } else {
            div.style.marginTop = (-sf * zone.size[2] / 2000) + "%";
            div.style.marginLeft = (-sf * zone.size[0] / 2000) + "%";
        }
        if (zone.shape === "sphere") {
            div.style.marginTop = div.style.marginLeft;
        }

        if (zone.fogColor) div.style.backgroundColor = zone.fogColor;

        // Rotation
        if (zone.rotation && (zone.rotation[0] || zone.rotation[1] || zone.rotation[2])) {
            var rotSign = (zone.rotation[0] === 180 || zone.rotation[0] === -180) ? -1 : 1;
            div.style.transform = "rotate(" + (-rotSign * zone.rotation[1]) + "deg)";
            label.style.transform = "rotate(" + (rotSign * zone.rotation[1]) + "deg)";
        }

        // Mineable
        if (zone.mineable) {
            div.classList.add("mineable");
            if (zone.lootInfo) {
                div.dataset.dynamicCommodity = zone.lootInfo.commodity;
                div.dataset.dynamicCount = zone.lootInfo.count;
                div.dataset.dynamicDifficulty = zone.lootInfo.difficulty;
            }
            var mineIcon = '<svg class="mineableIcon" style="enable-background:new 0 0 512 512;" version="1.1" viewBox="0 0 512 512" xml:space="preserve" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"><path d="M256.001,6C117.928,6,6,117.929,6,256c0,138.071,111.928,250,250.001,250  C394.072,506,506,394.071,506,256C506,117.929,394.072,6,256.001,6z M217.135,399.953c-1.43,3.027-5.043,4.315-8.068,2.881  l-32.872-15.559c-3.022-1.43-4.311-5.041-2.881-8.066l8.401-17.02c1.133,0.677,2.166,1.252,3.045,1.667  c8.685,4.096,29.274,7.318,44.631,9.271L217.135,399.953z M294.363,291.966c-2.992,6.319-10.547,9.021-16.873,6.029  c6.326,2.992,9.029,10.546,6.034,16.87c-2.992,6.321-10.547,9.023-16.873,6.029c6.326,2.994,9.028,10.544,6.032,16.868  c-2.991,6.324-10.548,9.021-16.87,6.029c6.323,2.992,9.028,10.546,6.032,16.87c-2.481,5.242-8.091,7.934-13.538,7.018l-0.007,0.056  c0,0-47.308-4.48-60.319-10.61c-0.008-0.007-0.015-0.008-0.028-0.016c-7.87-3.725-30.067-21.676-40.265-30.074  c-3.42-2.823-6.494-6.006-9.171-9.547c-1.74-2.305-5.301-5.199-7.909-6.434l-42.835-20.277c-5.457-2.584-8.383-8.585-7.046-14.469  c4.223-18.568,12.183-37.279,28.923-60.216c3.645-4.995,10.298-6.7,15.889-4.053l39.03,18.478  c10.448,4.945,27.898,5.808,38.78,1.918l6.535-2.334c4.491-1.606,11.68-1.249,15.99,0.79l7.516,3.56  c1.277,0.601,1.824,2.134,1.223,3.409l-2.233,4.72c-2.14,8.37,5.245,14.681,15.448,19.51c13.981,6.618,33.247,10.454,40.505,13.004  C294.655,278.088,297.355,285.64,294.363,291.966z M430.383,263.831c-1.004,0.586-2.281,0.384-3.056-0.482  c-30.99-34.623-67.257-63.727-108.513-86.006l-39.883,87.315c-8.446-2.268-19.427-5.299-27.916-9.317  c-4.489-2.126-11.708-6.194-11.494-10.263l42.138-85.371c-43.573-17.951-89.281-27.625-135.923-29.657  c-1.164-0.054-2.127-0.914-2.313-2.062c-0.181-1.144,0.469-2.263,1.556-2.674c52.527-19.817,106.815-22.695,156.165-5.084  l3.191-6.473c1.435-3.027,5.046-4.316,8.071-2.885l24.829,11.752c3.022,1.43,4.315,5.044,2.881,8.071l-3.03,6.634  c44.552,27.036,76.507,70.68,94.382,123.602C431.839,262.034,431.387,263.244,430.383,263.831z" style="fill:#FFFFFF;"/></svg>';
            var hasUsableName = label.textContent
                && label.textContent.indexOf("undefined") === -1
                && label.textContent !== "Mineable Zone";
            if (hasUsableName) {
                label.innerHTML += mineIcon;
            } else if (zone.lootInfo && zone.lootInfo.commodityName) {
                label.innerHTML = zone.lootInfo.commodityName + mineIcon;
            } else if (zone.lootInfo && zone.lootInfo.commodity) {
                label.innerHTML = zone.lootInfo.commodity + mineIcon;
            } else {
                label.innerHTML = "Mineable Zone" + mineIcon;
            }
        }

        // Click handler
        if (zone.idsInfo || zone.mineable) {
            div.addEventListener("click", function () {
                if (hasNotPannedRecently()) showInfocard(div);
            });
        }

        (container || contentsEl).appendChild(div);
    }

    function renderObject(obj, sf, container) {
        var div = document.createElement("div");
        div.className = (obj.classes || ["object"]).join(" ");
        div.dataset.internalNickname = obj.nickname;

        if (obj.idsName) div.dataset.idsName = obj.idsName;
        if (obj.idsInfo) div.dataset.idsInfo = obj.idsInfo;
        if (obj.archetype) div.dataset.archetype = obj.archetype;
        if (obj.jumpDest) div.dataset.jumpDest = obj.jumpDest;
        if (obj.reputation) div.dataset.reputation = obj.reputation;

        var label = document.createElement("label");
        label.textContent = obj.name || obj.nickname;
        div.appendChild(label);

        // Position
        div.style.position = "absolute";
        div.style.top = (obj.pos[2] / 2000 * sf) + "%";
        div.style.left = (obj.pos[0] / 2000 * sf) + "%";
        div.dataset.zPos = obj.pos[1] * sf;

        // Store game coords for tooltip
        div.dataset.coords = obj.pos[0] + ", " + obj.pos[1] + ", " + obj.pos[2];

        // Texture
        if (obj.texturePath) {
            div.style.backgroundImage = "url(" + obj.texturePath + ")";
        }

        // Radius for planets/stars
        var hasClass = function (c) { return (obj.classes || []).indexOf(c) !== -1; };
        var objRadius = 0;
        if (obj.radius > 0 && (hasClass("star") || hasClass("planet"))) {
            var r = obj.radius / 2000 * sf;
            objRadius = r;
            div.style.width = (r * 2) + "%";
            div.style.height = (r * 2) + "%";
            div.style.marginTop = (-r) + "%";
            div.style.marginLeft = (-r) + "%";
            div.style.zIndex = Math.floor(-r * 2);
        }

        // Atmosphere
        var atm = null;
        if (objRadius > 0 && obj.atmosphereRange > 0 && (hasClass("star") || hasClass("planet"))) {
            var atmR = 50 * obj.atmosphereRange / obj.radius;
            atm = document.createElement("div");
            atm.className = "atmosphere";
            atm.style.top = "50%";
            atm.style.left = "50%";
            atm.style.marginTop = (-atmR) + "%";
            atm.style.marginLeft = (-atmR) + "%";
            atm.style.width = (atmR * 2) + "%";
            atm.style.height = (atmR * 2) + "%";
            atm.style.position = "absolute";
            atm.style.zIndex = -1;
            div.style.zIndex = Math.floor(-obj.atmosphereRange / 2000 * sf);
            div.appendChild(atm);
            if (obj.atmosphereRange < obj.radius * 1.25 || (objRadius < 2 && obj.atmosphereRange < obj.radius * 1.5)) {
                atm.style.display = "none";
            }
        }

        // Burn color
        if (obj.burnColor) {
            div.style.backgroundColor = obj.burnColor;
            if (hasClass("star")) {
                div.style.boxShadow = "0em 0em 2em 0.2em " + obj.burnColor;
                if (atm) {
                    atm.style.boxShadow = "0em 0em 2em 0.2em " + obj.burnColor;
                }
            }
        }

        // Rotation for tradelanes
        if (obj.rotation && hasClass("tradelane") && (obj.rotation[0] || obj.rotation[1] || obj.rotation[2])) {
            var rDeg = obj.nickname.indexOf("ga_lane") !== -1 ? -obj.rotation[0] : -obj.rotation[1];
            div.style.transform = "rotate(" + rDeg + "deg)";
        }

        // Click handler
        if (obj.idsInfo) {
            div.addEventListener("click", function () {
                if (hasNotPannedRecently()) {
                    if (hasClass("jump") && obj.jumpDest && !hasClass("unusableJump")) {
                        generateSystemMap(obj.jumpDest);
                    } else {
                        showInfocard(div);
                    }
                }
            });
        } else if (obj.jumpDest && !hasClass("unusableJump")) {
            div.addEventListener("click", function () {
                if (hasNotPannedRecently()) generateSystemMap(obj.jumpDest);
            });
        }

        // Hide unknown unnamed objects (match main_new.js: only hide if name contains "???")
        if (!obj.idsName && obj.name && obj.name.indexOf("???") !== -1 && !hasClass("tradelane")) {
            div.style.display = "none";
        }

        (container || contentsEl).appendChild(div);
    }

    function renderPOB(pob, sf, container) {
        var div = document.createElement("div");
        div.className = "object base pob";
        div.dataset.internalNickname = pob.name;

        var label = document.createElement("label");
        label.textContent = pob.name;
        div.appendChild(label);

        // Position — pob.pos is [X, Y, Z]
        div.style.position = "absolute";
        div.style.top = (pob.pos[2] / 2000 * sf) + "%";
        div.style.left = (pob.pos[0] / 2000 * sf) + "%";
        div.dataset.zPos = pob.pos[1];

        // Store coords for tooltip
        div.dataset.coords = pob.pos[0] + ", " + pob.pos[1] + ", " + pob.pos[2];

        // Click handler
        div.addEventListener("click", function () {
            if (hasNotPannedRecently()) showPOBInfo(pob);
        });

        (container || contentsEl).appendChild(div);
    }

    function showPOBInfo(pob) {
        var html = "<h2>" + escapeHtml(pob.name) + "</h2>";

        // Render infotext paragraphs as main body (like station infocard text)
        if (pob.infotext && pob.infotext.length) {
            for (var i = 0; i < pob.infotext.length; i++) {
                html += "<p>" + escapeHtml(pob.infotext[i]) + "</p>";
            }
        }

        // Technical info section (same structure as station infocards)
        html += "<h3>Technical info</h3>";

        var affiliationName = factionHashToName[pob.affiliation] || pob.factionName || "";
        html += "<p class='technicalInfo'>Player Owned Station" + (affiliationName ? ". It belongs to " + escapeHtml(affiliationName) + "." : ".") + "</p>";
        html += "<p class='technicalInfo'>Coordinates: " + pob.pos[0] + ", " + pob.pos[1] + ", " + pob.pos[2] + "</p>";

        // Defense mode
        if (pob.defenseMode) {
            var modeLabel = pob.defenseMode == 1 ? "IFF Whitelist (Restricted Docking)" : pob.defenseMode == 2 ? "IFF Blacklist (Open Docking)" : "Unknown (" + escapeHtml(String(pob.defenseMode)) + ")";
            html += "<p class='technicalInfo'>Defense Mode: " + modeLabel + "</p>";
        }

        // Docking access lists
        function splitDockList(val) {
            if (Array.isArray(val)) return val.map(function (s) { return String(s).trim(); }).filter(Boolean);
            if (typeof val === "string" && val) return val.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
            return [];
        }
        var dockLists = [];
        if (pob.allyTags || pob.allyNames) {
            var allies = splitDockList(pob.allyTags).concat(splitDockList(pob.allyNames));
            if (allies.length) dockLists.push({ title: "Allies (Can Dock)", items: allies });
        }
        if (pob.hostileTags || pob.hostileNames) {
            var hostiles = splitDockList(pob.hostileTags).concat(splitDockList(pob.hostileNames));
            if (hostiles.length) dockLists.push({ title: "Hostiles (Cannot Dock)", items: hostiles });
        }
        for (var dl = 0; dl < dockLists.length; dl++) {
            html += "<p class='technicalInfo'><strong>" + dockLists[dl].title + ":</strong></p><ul class='pobDockList'>";
            for (var di = 0; di < dockLists[dl].items.length; di++) {
                html += "<li>" + escapeHtml(dockLists[dl].items[di]) + "</li>";
            }
            html += "</ul>";
        }

        html += "<div class='scrollUpButton' onclick='document.querySelector(\".infocardContainer\").style.display=\"none\";document.querySelector(\".remodal-bg\").style.display=\"none\"'><i class='fa fa-times'></i><p>Close</p></div>";

        var bg = document.querySelector(".remodal-bg");
        var infocardEl = document.querySelector(".infocardContainer");
        infocardEl.innerHTML = html;
        infocardEl.style.display = "inline-block";
        bg.style.display = "flex";
        bg.scrollTop = 0;
    }

    // --- Help Infocard ---
    function showHelpInfocard() {
        var html = "<h2>Discovery Navmap Help</h2>";
        html += "<p><b>Navigate:</b> Click any system on the universe map to view its details. Click <i>Show all systems</i> (top-left) to return.</p>";
        html += "<p><b>Search:</b> Use the search bar (top-right) to find systems, bases, and mining zones by name.</p>";
        html += "<p><b>Copy Waypoint:</b> Right-click any object, zone, or station in a system view to copy a <code>/wp X Y Z</code> command to your clipboard.</p>";
        html += "<p><b>Pan &amp; Zoom:</b> Scroll to zoom in/out. Click and drag to pan the map.</p>";
        html += "<p><b>Settings:</b> Click the gear icon (top-right) to toggle connections, zones, wrecks, labels, player stations, and more.</p>";
        html += "<p><b>Infocards:</b> Click any base, planet, or mineable zone to view its infocard with detailed info.</p>";
        html += "<p><b>Player Stations:</b> PoB data is fetched live from Discovery and refreshed every hour.</p>";
        html += "<p><b>Feedback:</b> Report bugs or suggest features on <a href='https://github.com/SlimyTheMoon/DiscoNavmap/issues' target='_blank' rel='noopener noreferrer'>GitHub Issues</a>.</p>";
		html += "<p><b>Credits:</b> Originally created by Space/Error <a href='https://github.com/AudunVN/Navmap' target='_blank' rel='noopener noreferrer'>Original Repository</a>.</p>";
        html += "<p><b>Credits:</b> Cherry Blossom to align the coloring to the server rules.</p>";        
		html += "<div class='scrollUpButton' onclick='document.querySelector(\".infocardContainer\").style.display=\"none\";document.querySelector(\".remodal-bg\").style.display=\"none\"'><i class='fa fa-times'></i><p>Close</p></div>";

        var bg = document.querySelector(".remodal-bg");
        var infocardEl = document.querySelector(".infocardContainer");
        infocardEl.innerHTML = html;
        infocardEl.style.display = "inline-block";
        bg.style.display = "flex";
        bg.scrollTop = 0;
    }

    document.getElementById("helpLink").addEventListener("click", function (e) {
        e.preventDefault();
        showHelpInfocard();
    });

    // --- Infocard Modal ---
    // Close infocard when clicking overlay background
    document.querySelector(".remodal-bg").addEventListener("click", function (e) {
        if (e.target === this) {
            document.querySelector(".infocardContainer").style.display = "none";
            this.style.display = "none";
        }
    });

    function showInfocard(element) {
        if (!clickHandlersEnabled) return;

        var idsName = element.dataset.idsName;
        var idsInfo = element.dataset.idsInfo;
        var nickname = element.dataset.internalNickname || "";
        var reputation = element.dataset.reputation || "";
        var zPos = element.dataset.zPos || "0";
        var dynamicCommodity = element.dataset.dynamicCommodity;
        var dynamicCount = element.dataset.dynamicCount;

        // Look up infocards and factions from pre-loaded caches (no network requests)
        var infoData = null;
        var nameData = null;
        var factionData = null;
        if (idsInfo && infocardCache[idsInfo]) {
            infoData = { id: idsInfo, text: infocardCache[idsInfo].text, mapped: infocardCache[idsInfo].mapped || "" };
        }
        if (idsName && infocardCache[idsName]) {
            nameData = { id: idsName, text: infocardCache[idsName].text, mapped: infocardCache[idsName].mapped || "" };
        }
        if (reputation && factionCache[reputation]) {
            factionData = { name: factionCache[reputation] };
        }

        (function () {

            var objectName = nameData ? nameData.text : (element.querySelector("label") ? element.querySelector("label").textContent : nickname);

            // Compute plane position
            var z = parseFloat(zPos) || 0;
            var planePos = "on";
            if (z > 0) planePos = (Math.round(z / (systemScaleFactor * 1000) * 10) / 10) + "K above";
            else if (z < 0) planePos = (Math.round(Math.abs(z) / (systemScaleFactor * 1000) * 10) / 10) + "K below";

            // Faction owner
            var ownerStr = "";
            if (factionData && factionData.name) {
                ownerStr = " It belongs to " + factionData.name + ".";
            }

            // Mining info
            var miningStr = "";
            if (dynamicCommodity) {
                var amountStr = dynamicCount && dynamicCount.indexOf("1, 1") === -1
                    ? dynamicCount.replace(/\s/g, "").split(",").join(" to ") + " units"
                    : "one unit";
                miningStr = "<p>This zone drops " + amountStr + " of the commodity " + dynamicCommodity + " when mined.</p>";
            }

            var html = "";
            var closeBtn = "<div class='scrollUpButton' onclick='document.querySelector(\".infocardContainer\").style.display=\"none\";document.querySelector(\".remodal-bg\").style.display=\"none\"'><i class='fa fa-times'></i><p>Close</p></div>";

            if (infoData) {
                html = "<h2>" + objectName + "</h2>" + (infoData.text || "") + (infoData.mapped || "");
                html += "<h3>Technical info</h3>" + miningStr;
                html += "<p class='technicalInfo'>This object with internal nickname " + nickname + " is located " + planePos + " the plane" + (idsName ? ", and has name infocard number " + idsName + " and infocard number " + (idsInfo || "") : "") + "." + ownerStr + "</p>";
                if (element.dataset.coords) {
                    html += "<p class='technicalInfo'>Coordinates: " + element.dataset.coords + "</p>";
                }
                html += closeBtn;
            } else if (dynamicCommodity) {
                html = miningStr + closeBtn;
            }

            if (html) {
                var bg = document.querySelector(".remodal-bg");
                var container = document.querySelector(".infocardContainer");
                container.innerHTML = html;
                container.style.display = "inline-block";
                bg.style.display = "flex";
                bg.scrollTop = 0;
            }
        })();
    }

    // --- Search ---
    var searchField = document.getElementById("searchField");

    // Build a lookup: system nickname -> system display name
    var systemNameLookup = {};
    for (var sn in systems) {
        if (systems[sn].name) systemNameLookup[sn] = systems[sn].name;
    }

    searchField.addEventListener("input", debounce(function () {
        var query = searchField.value.trim().toLowerCase();
        if (query.length < 2) { hideAutoComplete(); return; }

        // Collect matching suggestions sorted: systems first, then bases
        var sysSuggestions = [];
        var baseSuggestions = [];
        for (var i = 0; i < searchItems.length; i++) {
            if (searchItems[i].name.toLowerCase().indexOf(query) !== -1) {
                if (searchItems[i].type === "system") {
                    sysSuggestions.push(searchItems[i]);
                } else {
                    baseSuggestions.push(searchItems[i]);
                }
            }
        }
        showAutoComplete(sysSuggestions.concat(baseSuggestions), query);
    }, 150));

    function selectSearchItem(item) {
        hideAutoComplete();
        var sysNick = item.systemNickname;
        if (item.type === "system") {
            // Navigate to system or show universe if already a system view is showing the name
            if (sysNick.toLowerCase() === currentSystemNickname.toLowerCase()) {
                // Already on this system, do nothing special
            } else {
                generateSystemMap(sysNick);
            }
        } else {
            // Base: navigate to the system, then highlight
            if (sysNick.toLowerCase() !== currentSystemNickname.toLowerCase()) {
                generateSystemMap(sysNick);
            }
            // Try to highlight the matching base/object or zone
            setTimeout(function () {
                var labels = contentsEl.querySelectorAll(".object label, .zone label");
                for (var j = 0; j < labels.length; j++) {
                    if (labels[j].textContent.toLowerCase() === item.name.toLowerCase()) {
                        createHighlight(labels[j].parentNode);
                        break;
                    }
                }
            }, 500);
        }
        searchField.value = "";
    }

    searchField.addEventListener("keydown", function (e) {
        if (e.key === "Enter") {
            var acSel = document.querySelector(".autocomplete-suggestion.selected");
            if (acSel) {
                var idx = parseInt(acSel.dataset.idx, 10);
                selectSearchItem(acLastItems[idx]);
            }
        } else if (e.key === "Escape") {
            hideAutoComplete();
        } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            navigateAutoComplete(e.key === "ArrowDown" ? 1 : -1);
            e.preventDefault();
        }
    });

    var acContainer = null;
    var acLastItems = [];

    function highlightMatch(text, query) {
        var idx = text.toLowerCase().indexOf(query.toLowerCase());
        if (idx === -1) return document.createTextNode(text);
        var frag = document.createDocumentFragment();
        frag.appendChild(document.createTextNode(text.substring(0, idx)));
        var b = document.createElement("b");
        b.textContent = text.substring(idx, idx + query.length);
        frag.appendChild(b);
        frag.appendChild(document.createTextNode(text.substring(idx + query.length)));
        return frag;
    }

    function showAutoComplete(items, query) {
        hideAutoComplete();
        if (!items.length) return;
        acLastItems = items;
        acContainer = document.createElement("div");
        acContainer.className = "autocomplete-suggestions";
        items.slice(0, 15).forEach(function (item, i) {
            var div = document.createElement("div");
            div.className = "autocomplete-suggestion";
            div.dataset.idx = i;

            var nameSpan = document.createElement("span");
            nameSpan.className = "ac-name";
            nameSpan.appendChild(highlightMatch(item.name, query));
            div.appendChild(nameSpan);

            // Show system name for bases, or type badge for systems
            var metaSpan = document.createElement("span");
            metaSpan.className = "ac-meta";
            if (item.type === "base" || item.type === "pob" || item.type === "zone") {
                var sysName = systemNameLookup[item.systemNickname] || item.systemNickname;
                var suffix = item.type === "pob" ? " (PoB)" : item.type === "zone" ? " (Zone)" : "";
                metaSpan.textContent = sysName + suffix;
            } else {
                metaSpan.textContent = "System";
            }
            div.appendChild(metaSpan);

            div.addEventListener("mousedown", function (e) {
                e.preventDefault();
                selectSearchItem(item);
            });
            acContainer.appendChild(div);
        });
        var rect = searchField.getBoundingClientRect();
        acContainer.style.top = (rect.bottom + window.scrollY) + "px";
        acContainer.style.left = rect.left + "px";
        acContainer.style.width = Math.max(rect.width, 350) + "px";
        document.body.appendChild(acContainer);
    }

    function hideAutoComplete() {
        if (acContainer) { acContainer.remove(); acContainer = null; }
        acLastItems = [];
    }

    function navigateAutoComplete(dir) {
        if (!acContainer) return;
        var items = acContainer.querySelectorAll(".autocomplete-suggestion");
        var selected = acContainer.querySelector(".selected");
        var idx = -1;
        if (selected) {
            selected.classList.remove("selected");
            idx = Array.from(items).indexOf(selected);
        }
        idx += dir;
        if (idx >= 0 && idx < items.length) {
            items[idx].classList.add("selected");
            items[idx].scrollIntoView({ block: "nearest" });
        }
    }

    searchField.addEventListener("blur", function () {
        setTimeout(hideAutoComplete, 200);
    });

    // --- Show Universe Map Button ---
    document.getElementById("showUniverseMap").addEventListener("click", function () {
        generateUniverseMap();
    });

    // --- URL Hash Check ---
    function checkURL() {
        if (!location.hash) return;
        try {
            var query = URIHash.get("q");
            if (query) {
                for (var i = 0; i < searchItems.length; i++) {
                    if (searchItems[i].name.toLowerCase() === query.toLowerCase() ||
                        searchItems[i].name === query) {
                        if (searchItems[i].systemNickname.toLowerCase() !== currentSystemNickname.toLowerCase()) {
                            generateSystemMap(searchItems[i].systemNickname);
                        }
                        return;
                    }
                }
            }
        } catch (e) { }
    }

    // --- DSAce Log Reader ---
    var dsaceInput = document.getElementById("dsaceInput");
    if (dsaceInput) {
        dsaceInput.addEventListener("change", function (event) {
            var file = event.target.files[0];
            if (!file) return;
            var reader = new FileReader();
            var lastMapMatch = "";
            var lastPosMatch = "";

            reader.onload = function () {
                var raw = reader.result;
                var mapRe = /\/map (.*)/g;
                var posRe = /\] \/pos in .*[\n\r]+\[[^\]]*\] Position.*/g;

                try {
                    var mapMatch = raw.slice(raw.lastIndexOf("/map")).match(mapRe);
                    if (mapMatch) {
                        var cmd = mapMatch[0].slice(5).trim();
                        if (cmd !== lastMapMatch) {
                            lastMapMatch = cmd;
                            var lower = cmd.toLowerCase();
                            if (lower === "universe" || lower === "sirius" || lower === "universemap") {
                                generateUniverseMap();
                            } else {
                                searchField.value = cmd;
                                searchField.dispatchEvent(new Event("input"));
                            }
                        }
                    }
                } catch (e) { }
            };

            reader.readAsText(file);
            setInterval(function () { reader.readAsText(file); }, 1000);
        });
    }

    // --- Utility ---
    function debounce(fn, delay) {
        var timer;
        return function () {
            var ctx = this, args = arguments;
            clearTimeout(timer);
            timer = setTimeout(function () { fn.apply(ctx, args); }, delay);
        };
    }

    // --- Nickname Tooltip (cursor-following) ---
    var nickTooltip = document.createElement("div");
    nickTooltip.id = "nicknameTooltip";
    document.body.appendChild(nickTooltip);

    contentsEl.addEventListener("mouseover", function (e) {
        if (!contentsEl.classList.contains("showInternalNicknames")) return;
        var target = e.target.closest("[data-internal-nickname], [data-system-nickname]");
        if (!target) return;
        var nick = target.dataset.internalNickname || target.dataset.systemNickname || "";
        if (!nick) return;
        var text = nick;
        var coords = target.dataset.coords;
        if (coords) text += "\n(" + coords + ")";
        nickTooltip.textContent = text;
        nickTooltip.style.display = "block";
    });

    contentsEl.addEventListener("mouseout", function (e) {
        var target = e.target.closest("[data-internal-nickname], [data-system-nickname]");
        if (!target) return;
        var related = e.relatedTarget ? e.relatedTarget.closest("[data-internal-nickname], [data-system-nickname]") : null;
        if (related === target) return;
        nickTooltip.style.display = "none";
    });

    contentsEl.addEventListener("mousemove", function (e) {
        if (nickTooltip.style.display !== "block") return;
        nickTooltip.style.left = (e.clientX + 14) + "px";
        nickTooltip.style.top = (e.clientY + 14) + "px";
    });

    // --- Init ---
    loadSettings();
    generateUniverseMap();

    // --- Pre-cache all data from static JSON files ---
    (function prefetchAllData() {
        // Load POBs from Discovery GC, falling back to static data
        var pobPromise = getPoBBases()
            .catch(function () {
                console.warn("Failed to fetch POBs from Discovery GC, using static fallback");
                return fetch("data/pobs.json")
                    .then(function (r) { return r.ok ? r.json() : []; })
                    .catch(function () { return []; });
            });

        // Load core data files in parallel
        Promise.all([
            fetch("data/systems-all.json").then(function (r) { return r.ok ? r.json() : {}; }),
            fetch("data/infocards.json").then(function (r) { return r.ok ? r.json() : {}; }),
            fetch("data/factions.json").then(function (r) { return r.ok ? r.json() : {}; })
        ]).then(function (results) {
            var allDetails = results[0];
            infocardCache = results[1];
            factionCache = results[2];

            // Build faction hash → display name map for PoB affiliation lookups
            for (var fNick in factionCache) {
                if (factionCache.hasOwnProperty(fNick)) {
                    factionHashToName[flHash(fNick)] = factionCache[fNick];
                }
            }

            for (var nick in allDetails) {
                if (!systemDetailCache[nick]) {
                    systemDetailCache[nick] = allDetails[nick];
                }
            }

            console.log("Cached " + Object.keys(allDetails).length + " system details, " +
                Object.keys(infocardCache).length + " infocards, " +
                Object.keys(factionCache).length + " factions");

            // Preload and decode all unique planet/star textures
            var seen = {};
            var decodePromises = [];
            for (var sn in allDetails) {
                var objs = allDetails[sn].objects;
                if (!objs) continue;
                for (var i = 0; i < objs.length; i++) {
                    var tp = objs[i].texturePath;
                    if (tp && !seen[tp]) {
                        seen[tp] = true;
                        var img = new Image();
                        img.src = tp;
                        textureCache[tp] = img;
                        if (img.decode) {
                            decodePromises.push(img.decode().catch(function () {}));
                        }
                    }
                }
            }
            var count = Object.keys(seen).length;
            if (decodePromises.length) {
                Promise.all(decodePromises).then(function () {
                    console.log("Decoded " + count + " textures (GPU-ready)");
                });
            } else {
                console.log("Preloading " + count + " textures");
            }

            // Resolve POBs after core data is ready
            return pobPromise;
        }).then(function (pobs) {
            indexPoBs(pobs);

            // Check URL AFTER POBs are loaded so system maps render with POBs
            checkURL();

            // Re-apply label settings
            updateConfigClasses();

            // Refresh PoB data every hour
            setInterval(function () {
                getPoBBases().then(function (freshPobs) {
                    indexPoBs(freshPobs);
                    // Re-render POBs on the current system view
                    var sysNick = (currentSystemNickname || "").toLowerCase();
                    if (sysNick && sysNick !== "sirius") {
                        document.querySelectorAll(".object.pob").forEach(function (el) { el.remove(); });
                        var sysPobs = pobsBySystem[sysNick] || [];
                        for (var pi = 0; pi < sysPobs.length; pi++) {
                            renderPOB(sysPobs[pi], systemScaleFactor, contentsEl);
                        }
                        updateConfigClasses();
                    }
                    console.log("PoB data refreshed");
                }).catch(function (err) { console.warn("PoB refresh failed:", err); });
            }, 3600000);
        }).catch(function (err) { console.error("prefetchAllData error:", err); });
    })();

    function indexPoBs(pobs) {
        pobsBySystem = {};
        // Remove previous POB search entries
        searchItems = searchItems.filter(function (s) { return s.type !== "pob"; });
        if (Array.isArray(pobs)) {
            var seen = {};
            pobs.forEach(function (p) {
                var sn = (p.systemNickname || "").toLowerCase();
                if (!sn) return;
                var key = sn + "|" + p.name;
                if (seen[key]) return;
                seen[key] = true;
                if (!pobsBySystem[sn]) pobsBySystem[sn] = [];
                pobsBySystem[sn].push(p);
                searchItems.push({ name: p.name, systemNickname: sn, type: "pob" });
            });
            console.log("Cached " + pobs.length + " POBs across " + Object.keys(pobsBySystem).length + " systems");
        }
    }

})();
