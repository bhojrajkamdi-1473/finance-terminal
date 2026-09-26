/* FINSIGHT API client (spec sections 3, 4.7, 13).
   Single fetch wrapper: envelope validation, 30-60s memory cache keyed by
   full URL, single-flight dedup, max 6 concurrent, AbortController support,
   stale-response tokens. No secrets, no auto-retry loops. */
(function () {
  "use strict";
  var BASE = (window.FINSIGHT && typeof window.FINSIGHT.API_BASE === "string")
    ? window.FINSIGHT.API_BASE : "";
  var KNOWN = { live: 1, delayed: 1, unavailable: 1, error: 1 };
  var MAX_INFLIGHT = 6, inflight = 0, queue = [];
  var cache = {};   // url -> { at, body }
  var pending = {}; // url -> [{ok, fail}]
  var CACHE_TTL = 45000;

  function pump() {
    while (inflight < MAX_INFLIGHT && queue.length) queue.shift()();
  }
  function full(path, params) {
    var qs = Object.keys(params || {}).map(function (k) {
      var v = params[k];
      if (v === undefined || v === null || v === "") return "";
      return encodeURIComponent(k) + "=" + encodeURIComponent(String(v));
    }).filter(Boolean).join("&");
    return BASE + path + (qs ? (path.indexOf("?") >= 0 ? "&" : "?") + qs : "");
  }
  function validEnvelope(b) {
    if (!b || typeof b !== "object") return "error";
    return KNOWN[b.status] ? b.status : "error";
  }
  function request(method, path, params, opts) {
    opts = opts || {};
    var url = method === "GET" ? full(path, params) : full(path);
    var token = opts.token || 0;
    return new Promise(function (resolve) {
      function done(out) { resolve(out); }
      function run() {
        if (method === "GET" && !opts.refresh) {
          var hit = cache[url];
          if (hit && Date.now() - hit.at < CACHE_TTL) {
            done({ state: "resolved", status: validEnvelope(hit.body), body: hit.body, fromCache: true, token: token });
            pump(); return;
          }
          if (pending[url]) { pending[url].push({ ok: done, token: token }); pump(); return; }
          pending[url] = [];
        }
        inflight++;
        var ctrl = null;
        try { ctrl = new AbortController(); } catch (e) { ctrl = null; }
        if (opts.signal && ctrl) {
          if (opts.signal.aborted) { inflight--; settle({ state: "network-error", token: token }); pump(); return; }
          opts.signal.addEventListener("abort", function () { try { ctrl.abort(); } catch (e) {} });
        }
        var fo = { method: method, headers: { "Accept": "application/json" } };
        if (ctrl) fo.signal = ctrl.signal;
        if (method !== "GET") {
          fo.headers["Content-Type"] = "application/json";
          try { fo.body = JSON.stringify(params || {}); } catch (e) { fo.body = "{}"; }
        }
        var timer = setTimeout(function () { try { ctrl.abort(); } catch (e) {} }, opts.timeoutMs || 25000);
        fetch(url, fo).then(function (resp) {
          clearTimeout(timer);
          return resp.text().then(function (t) {
            var body = null;
            try { body = t ? JSON.parse(t) : null; } catch (e) { body = null; }
            if (!resp.ok && (!body || typeof body !== "object")) body = { status: "error", message: "HTTP " + resp.status };
            if (!body || typeof body !== "object") body = { status: "error", message: "Unexpected response" };
            if (!KNOWN[body.status]) body.status = "error";
            if (method === "GET" && KNOWN[body.status] && body.status !== "error") {
              try { cache[url] = { at: Date.now(), body: body }; } catch (e) {}
            }
            settle({ state: "resolved", status: body.status, body: body, token: token });
          });
        }).catch(function () {
          clearTimeout(timer);
          settle({ state: "network-error", token: token });
        });
        function settle(out) {
          inflight--;
          done(out);
          (pending[url] || []).forEach(function (w) { w.ok(out); });
          delete pending[url];
          pump();
        }
      }
      queue.push(run); pump();
    });
  }
  window.FS_API = {
    get: function (path, params, opts) { return request("GET", path, params, opts); },
    post: function (path, params, opts) { return request("POST", path, params, opts); },
    del: function (path, params, opts) {
      var url = full(path, params);
      return request("DELETE", url, null, opts);
    },
    clearCache: function () { cache = {}; },
    KNOWN_STATUSES: ["live", "delayed", "unavailable", "error"]
  };
})();
