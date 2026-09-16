/* Thin fetch wrapper over /api/*. All responses are status envelopes. */
(function () {
  "use strict";
  function qs(params) {
    return Object.keys(params || {})
      .filter(function (k) { return params[k] !== undefined && params[k] !== null && params[k] !== ""; })
      .map(function (k) { return encodeURIComponent(k) + "=" + encodeURIComponent(params[k]); })
      .join("&");
  }
  function get(path, params) {
    var url = "/api/" + path + (params && qs(params) ? "?" + qs(params) : "");
    return fetch(url, { headers: { Accept: "application/json" } }).then(function (r) {
      return r.json().then(function (j) { return { http: r.status, body: j }; });
    });
  }
  function post(path, data) {
    return fetch("/api/" + path, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data || {}),
    }).then(function (r) { return r.json().then(function (j) { return { http: r.status, body: j }; }); });
  }
  function del(path, params) {
    var url = "/api/" + path + (params && qs(params) ? "?" + qs(params) : "");
    return fetch(url, { method: "DELETE" }).then(function (r) {
      return r.json().then(function (j) { return { http: r.status, body: j }; });
    });
  }
  /* Polling helper: frontend polls on `ms`, backend serves cache unless
     a refresh is allowed (rate-limit governor). Skips while tab hidden. */
  function poll(ms, fn) {
    fn();
    var id = setInterval(function () {
      if (document.hidden) return;
      fn();
    }, ms);
    return id;
  }
  window.FT_API = { get, post, del, poll };
})();
