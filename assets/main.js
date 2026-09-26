/* ============================================================
   BHOJRAJ KAMDI — INTERACTION SCRIPT
   ============================================================ */

(function () {
  "use strict";

  /* ------------------------------------------------------------------
     REPORT LINKS — single source of truth.
     Verified Google Drive / Docs URLs taken from data/portfolio-data.json.
     NULL = no link exists (project 02 and 09 have no published report).
     ------------------------------------------------------------------ */
  var REPORTS = {
    p01: [
      "https://drive.google.com/file/d/1pGAY4Vr_cwJC33Z5CAIImhbXU2Av9RaV/view?usp=drive_link",
      "https://drive.google.com/file/d/13X6SglaG91yu_porTelERwR6Js7KmhCo/view?usp=drive_link",
      "https://docs.google.com/document/d/1b0azJOrUWnRysQ4T6offfiIfnlYEiOCq/edit?usp=drive_link&ouid=113586569177191721533&rtpof=true&sd=true"
    ],
    p01a: "https://drive.google.com/file/d/1pGAY4Vr_cwJC33Z5CAIImhbXU2Av9RaV/view?usp=drive_link",
    p01b: "https://drive.google.com/file/d/13X6SglaG91yu_porTelERwR6Js7KmhCo/view?usp=drive_link",
    p01c: "https://docs.google.com/document/d/1b0azJOrUWnRysQ4T6offfiIfnlYEiOCq/edit?usp=drive_link&ouid=113586569177191721533&rtpof=true&sd=true",
    p02: null,
    p03: "https://docs.google.com/document/d/15KwRoxBXu1gl8Ad9i0O74e_oHOddEKci/edit?usp=drive_link&ouid=113586569177191721533&rtpof=true&sd=true",
    p04: "https://drive.google.com/file/d/1yhWyuGiuQRcqxmyDaGqeDLzm3GDpXk3U/view?usp=drive_link",
    p05: "https://docs.google.com/document/d/1-ST0W2-EolFUOAw8sI0Gc8BhKvERcQRi/edit?usp=drive_link&ouid=113586569177191721533&rtpof=true&sd=true",
    p06: "https://drive.google.com/file/d/1MO-MuSvUr_hlUCkLot7nx0WQ8BYkMjTd/view?usp=drive_link",
    p07: "https://drive.google.com/file/d/1lDHJDYOQM1cuGc7sDE9fE-yhjT6owPne/view?usp=drive_link",
    p08: "https://drive.google.com/file/d/1vf_yJVM22RVhXzhebZaosspNmHFi_OS4/view?usp=sharing",
    p09: null
  };

  /* Labels for the three subcase reports under project 01.
     Rendered as small captions ABOVE each button — never inside it.
     Buttons always read exactly "View report" (uppercased via CSS). */
  var REPORT_LABELS = {
    p01a: "01A · Patel Retail Ltd. — IPO & secondary market",
    p01b: "01B · Tech Mahindra Ltd. — Financial statements & forecasts",
    p01c: "01C · MRF Limited — Ratio analysis"
  };

  /* ------------------------------------------------------------------
     CONTACT — verified addresses from data/portfolio-data.json.
     ------------------------------------------------------------------ */
  var CONTACT_EMAIL = "bhojrajkamdi14@gmail.com";
  var CONTACT_LINKEDIN = "https://www.linkedin.com/in/bhojrajkamdi";
  var RESUME_URL = "https://docs.google.com/document/d/1BFeB2oi3oYkQRqjwEmUpC3M__p_ACSpZ/edit";

  var doc = document;
  var root = doc.documentElement;

  var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var finePointer = window.matchMedia("(pointer: fine)").matches;

  /* ---------- Footer year ---------- */
  var yearEl = doc.getElementById("year");
  if (yearEl) yearEl.textContent = new Date().getFullYear();

  /* ---------- Topbar scrolled state ---------- */
  var topbar = doc.getElementById("topbar");
  function onScroll() {
    if (!topbar) return;
    topbar.classList.toggle("scrolled", window.scrollY > 10);
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* ---------- Mobile menu ---------- */
  var toggle = doc.getElementById("navToggle");
  var menu = doc.getElementById("mobileMenu");

  function closeMenu() {
    if (!menu || !toggle) return;
    menu.classList.remove("open");
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", "Open menu");
    doc.body.style.overflow = "";
  }

  function openMenu() {
    if (!menu || !toggle) return;
    menu.classList.add("open");
    toggle.setAttribute("aria-expanded", "true");
    toggle.setAttribute("aria-label", "Close menu");
    doc.body.style.overflow = "hidden";
  }

  if (toggle && menu) {
    toggle.addEventListener("click", function () {
      if (menu.classList.contains("open")) closeMenu(); else openMenu();
    });
    menu.querySelectorAll("a").forEach(function (a) { a.addEventListener("click", closeMenu); });
    doc.addEventListener("keydown", function (e) { if (e.key === "Escape") closeMenu(); });
  }

  /* ---------- Reveal on scroll ----------
     Fade-up on IntersectionObserver: 600ms settle curve, 60/120ms group
     steps, threshold 0.15, fires once. Observer reports current state on
     observe, so mid-scroll refreshes animate in immediately. will-change
     is released after each transition to keep GPU layers minimal. */
  var revealEls = doc.querySelectorAll(".rv");
  function rvDone(el) { el.style.willChange = "auto"; }
  if ("IntersectionObserver" in window && !reducedMotion) {
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            var t = entry.target;
            t.classList.add("in");
            t.addEventListener("transitionend", function () { rvDone(t); }, { once: true });
            observer.unobserve(t);
          }
        });
      },
      { threshold: 0.15, rootMargin: "0px 0px -40px 0px" }
    );
    revealEls.forEach(function (el) {
      el.addEventListener("transitionend", function () { rvDone(el); }, { once: true });
      observer.observe(el);
    });
  } else {
    revealEls.forEach(function (el) { el.classList.add("in"); rvDone(el); });
  }

  /* ---------- Evidence counters ----------
     Fire-once count-up (cubic ease-out, en-IN grouping). The "+" suffix
     is appended only at the final value. Final numbers stay in the HTML,
     so no-JS and reduced-motion readers see the true figures. */
  function animateCounter(el) {
    var target = parseInt(el.getAttribute("data-counter-target"), 10);
    var duration = parseInt(el.getAttribute("data-counter-duration") || "1200", 10);
    var suffix = el.getAttribute("data-counter-suffix") || "";
    if (!target || reducedMotion) {
      el.textContent = target.toLocaleString("en-IN") + suffix;
      return;
    }
    var start = null;
    function tick(now) {
      if (start === null) start = now;
      var p = Math.min((now - start) / duration, 1);
      var eased = 1 - Math.pow(1 - p, 3);
      var value = Math.round(eased * target);
      el.textContent = value.toLocaleString("en-IN");
      if (p < 1) requestAnimationFrame(tick);
      else el.textContent = target.toLocaleString("en-IN") + suffix;
    }
    requestAnimationFrame(tick);
  }

  var counterEls = doc.querySelectorAll("[data-counter]");
  if ("IntersectionObserver" in window && !reducedMotion) {
    var counterIO = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            animateCounter(entry.target);
            counterIO.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.5 }
    );
    counterEls.forEach(function (el) { counterIO.observe(el); });
  }

  /* ---------- Hero depth parallax ---------- */
  var stage = doc.getElementById("heroDepth");
  if (stage && finePointer && !reducedMotion) {
    var planes = [].slice.call(stage.children);
    var raf = null;

    var apply = function (x, y) {
      planes.forEach(function (plane) {
        var depth = parseFloat(plane.getAttribute("data-depth") || "6");
        var tx = x * depth;
        var ty = y * depth;
        var rot = x * 0.4;
        plane.style.transform =
          "translateZ(" + (depth * -1.4) + "px) translate3d(" + tx + "px," + ty + "px,0) rotate(" + rot + "deg)";
      });
    };

    var onMove = function (e) {
      var r = stage.getBoundingClientRect();
      var cx = (e.clientX - r.left - r.width / 2) / (r.width / 2);
      var cy = (e.clientY - r.top - r.height / 2) / (r.height / 2);
      if (raf) cancelAnimationFrame(raf);
      raf = requestAnimationFrame(function () { apply(cx, cy); });
    };

    window.addEventListener("pointermove", onMove, { passive: true });
  } else if (stage) {
    // No touch parallax; planes keep their resting CSS transforms.
    var p = [].slice.call(stage.children);
    p.forEach(function (plane) {
      var depth = parseFloat(plane.getAttribute("data-depth") || "6");
      plane.style.transform = "translateZ(" + (depth * -1.4) + "px)";
    });
  }

  /* ---------- Accordions (featured cases + research library) ----------
     Buttons carry data-acc-btn; the wrapping .acc-item / .lib-row toggles
     .open (smooth grid-rows animation in CSS). Independent toggles —
     multiple sections may stay open. Keyboard accessible by default. */
  var accBtns = doc.querySelectorAll("[data-acc-btn]");
  accBtns.forEach(function (btn) {
    var item = btn.closest(".acc-item");
    if (!item) item = btn.closest(".lib-row");
    if (!item) return;
    btn.addEventListener("click", function () {
      var open = item.classList.toggle("open");
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    });
  });

  /* ---------- Library filtering ----------
     Chips carry data-filter; rows carry data-cat. Clicking a chip filters
     the rows inside the same section. aria-pressed marks the active chip. */
  var chips = doc.querySelectorAll("[data-filter]");
  chips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      var scope = chip.closest("section") || doc;
      var value = chip.getAttribute("data-filter");
      scope.querySelectorAll("[data-filter]").forEach(function (c) {
        c.setAttribute("aria-pressed", c === chip ? "true" : "false");
      });
      scope.querySelectorAll("[data-cat]").forEach(function (row) {
        var show = value === "all" || row.getAttribute("data-cat") === value;
        if (show) row.removeAttribute("hidden");
        else row.setAttribute("hidden", "");
      });
    });
  });

  /* ---------- Report CTAs ----------
     Single-link slots render exactly one button: "View report ↗".
     Multi-link slots (project 01) render one caption + button pair per
     sub-report. Slots with no URL keep "REPORT LINK PENDING" as a
     disabled, non-clickable note. URLs are never invented. */
  /* ---------- IN PRACTICE slideshows ----------
     Editorial carousel: 2500ms autoplay, 750ms crossfade + 10px drift on
     cubic-bezier(0.4, 0, 0.2, 1), caption trails by 120ms, next image
     preloaded on every change. Pause on hover/focus/hidden tab/offscreen,
     transition lock against rapid input, dots + count + progress, arrows +
     space keyboard support, 40px swipe threshold, reduced-motion = fade. */
  var DURATION = 2500;
  var TRANSITION = 750;

  function ipPreload(stage, i) {
    var slides = stage._ip.slides;
    var n = slides.length;
    if (!n) return;
    var img = slides[((i % n) + n) % n].querySelector("img");
    if (img && !img.complete) {
      var preloader = new Image();
      preloader.src = img.currentSrc || img.src;
    }
  }

  function ipRender(stage) {
    var st = stage._ip;
    var slides = st.slides;
    var n = slides.length;
    if (!n) return;
    slides.forEach(function (s, k) {
      var on = k === st.idx;
      s.classList.toggle("active", on);
      if (!on) s.classList.remove("is-leaving");
      s.setAttribute("aria-hidden", on ? "false" : "true");
    });
    var box = stage.parentNode;
    var count = box.querySelector(".ip-count");
    if (count) {
      count.textContent = String(st.idx + 1).padStart(2, "0") + " / " + String(n).padStart(2, "0");
    }
    var dots = box.querySelectorAll(".ip-dots button");
    dots.forEach(function (d, k) {
      d.setAttribute("aria-selected", k === st.idx ? "true" : "false");
      d.setAttribute("aria-label", "Slide " + (k + 1) + " of " + n);
    });
    var bar = box.querySelector(".ip-progress i");
    if (bar) {
      bar.style.transition = "none";
      bar.style.width = "0%";
      void bar.offsetWidth;
      if (st.playing && !reducedMotion) {
        bar.style.transition = "width " + DURATION + "ms linear";
        bar.style.width = "100%";
      }
    }
    ipPreload(stage, st.idx + 1);
  }

  function ipGo(stage, i, animate) {
    var st = stage._ip;
    var n = st.slides.length;
    if (!n || st.locked) return;
    var target = ((i % n) + n) % n;
    if (target === st.idx) return;
    var prev = st.slides[st.idx];
    var box = stage.parentNode;
    var cap = box.parentNode.querySelector(".ip-cap");
    if (animate === false) {
      st.idx = target;
      ipRender(stage);
      return;
    }
    st.locked = true;
    prev.classList.remove("active");
    prev.classList.add("is-leaving");
    prev.setAttribute("aria-hidden", "true");
    if (cap) cap.classList.add("is-switching");
    setTimeout(function () {
      prev.classList.remove("is-leaving");
      st.idx = target;
      ipRender(stage);
      if (cap) {
        void cap.offsetWidth;
        cap.classList.remove("is-switching");
      }
      setTimeout(function () { st.locked = false; }, TRANSITION);
    }, 60);
  }

  function ipStop(stage, silent) {
    var st = stage._ip;
    if (st.timer) { clearInterval(st.timer); st.timer = null; }
    st.playing = false;
    stage.classList.remove("playing");
    var box = stage.parentNode;
    var bar = box.querySelector(".ip-progress i");
    if (bar) { bar.style.transition = "none"; bar.style.width = "0%"; }
    if (silent) return;
    var pb = box.querySelector("[data-ip-pause]");
    if (pb) { pb.setAttribute("aria-label", "Play slideshow"); pb.setAttribute("aria-pressed", "true"); pb.textContent = "▶"; }
    var badge = stage.querySelector("[data-ip-paused]");
    if (badge) badge.removeAttribute("hidden");
  }

  function ipPlay(stage) {
    var st = stage._ip;
    if (reducedMotion) { ipStop(stage); return; }
    if (st.userPaused || doc.hidden || !st.visible) return;
    st.playing = true;
    stage.classList.add("playing");
    var box = stage.parentNode;
    var pb = box.querySelector("[data-ip-pause]");
    if (pb) { pb.setAttribute("aria-label", "Pause slideshow"); pb.setAttribute("aria-pressed", "false"); pb.textContent = "❚❚"; }
    var badge = stage.querySelector("[data-ip-paused]");
    if (badge) badge.setAttribute("hidden", "");
    if (st.timer) clearInterval(st.timer);
    ipRender(stage);
    st.timer = setInterval(function () {
      if (!st.locked) ipGo(stage, st.idx + 1);
    }, DURATION);
  }

  function ipPauseToggle(stage) {
    if (stage._ip.playing) { stage._ip.userPaused = true; ipStop(stage); }
    else { stage._ip.userPaused = false; ipPlay(stage); }
  }

  var ipStages = [].slice.call(doc.querySelectorAll("[data-ip]"));
  ipStages.forEach(function (stage, si) {
    var slides = [].slice.call(stage.querySelectorAll(".ip-slide"));
    stage._ip = { slides: slides, idx: 0, timer: null, playing: false, locked: false, userPaused: false, visible: true };
    var box = stage.parentNode;
    var dotsWrap = box.querySelector(".ip-dots");
    if (dotsWrap && !dotsWrap.children.length) {
      slides.forEach(function (s, k) {
        var d = doc.createElement("button");
        d.setAttribute("role", "tab");
        d.setAttribute("aria-selected", k === 0 ? "true" : "false");
        d.setAttribute("aria-label", "Slide " + (k + 1) + " of " + slides.length);
        d.addEventListener("click", function () {
          stage._ip.userPaused = false;
          ipGo(stage, k);
          ipPlay(stage);
        });
        dotsWrap.appendChild(d);
      });
    }
    function go(d) {
      stage._ip.userPaused = false;
      ipGo(stage, stage._ip.idx + d);
      ipPlay(stage);
    }

    var prev = box.querySelector("[data-ip-prev]");
    var next = box.querySelector("[data-ip-next]");
    var pause = box.querySelector("[data-ip-pause]");
    if (prev) prev.addEventListener("click", function () { go(-1); });
    if (next) next.addEventListener("click", function () { go(1); });
    if (pause) pause.addEventListener("click", function () { ipPauseToggle(stage); });
    stage.addEventListener("keydown", function (e) {
      if (e.key === "ArrowLeft") { e.preventDefault(); go(-1); }
      else if (e.key === "ArrowRight") { e.preventDefault(); go(1); }
      else if (e.key === " ") { e.preventDefault(); ipPauseToggle(stage); }
    });
    box.addEventListener("mouseenter", function () { if (stage._ip.playing) ipStop(stage); });
    box.addEventListener("mouseleave", function () { if (!stage._ip.userPaused) ipPlay(stage); });
    box.addEventListener("focusin", function () { if (stage._ip.playing) ipStop(stage); });
    box.addEventListener("focusout", function (e) {
      if (!box.contains(e.relatedTarget) && !stage._ip.userPaused) ipPlay(stage);
    });
    var tx = null;
    stage.addEventListener("touchstart", function (e) { tx = e.touches[0].clientX; }, { passive: true });
    stage.addEventListener("touchend", function (e) {
      if (tx === null) return;
      var dx = e.changedTouches[0].clientX - tx;
      tx = null;
      if (Math.abs(dx) > 40) go(dx < 0 ? 1 : -1);
    }, { passive: true });

    stage._ip.idx = 0;
    ipRender(stage);
    ipPlay(stage);
  });

  if ("IntersectionObserver" in window && ipStages.length) {
    var ipIO = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        var stage = en.target._ip ? en.target : null;
        if (!stage) return;
        stage._ip.visible = en.isIntersecting;
        if (en.isIntersecting) { if (!stage._ip.userPaused) ipPlay(stage); }
        else ipStop(stage, true);
      });
    }, { threshold: 0.2 });
    ipStages.forEach(function (s) { ipIO.observe(s); });
  }

  doc.addEventListener("visibilitychange", function () {
    ipStages.forEach(function (s) {
      if (doc.hidden) ipStop(s, true);
      else if (!s._ip.userPaused && s._ip.visible) ipPlay(s);
    });
  });

  var reportSlots = doc.querySelectorAll("[data-report]");
  reportSlots.forEach(function (slot) {
    var key = slot.getAttribute("data-report");
    var urls = REPORTS[key];
    if (!urls) {
      slot.classList.add("pending-note");
      slot.setAttribute("role", "note");
      slot.setAttribute("aria-label", "Report link pending — no published report yet");
      if (!slot.textContent.trim()) slot.textContent = "REPORT LINK PENDING";
      return;
    }
    var labels = slot.getAttribute("data-labels") || "";
    var labelList = labels.split("|");
    if (typeof urls === "string") urls = [urls];
    var list = doc.createElement("div");
    list.className = "report-link-list";
    urls.forEach(function (url, i) {
      var item = doc.createElement("div");
      item.className = "report-item";
      var caption = (labelList[i] || "").trim();
      if (urls.length > 1 && caption) {
        var cap = doc.createElement("span");
        cap.className = "report-cap";
        cap.textContent = caption;
        item.appendChild(cap);
      }
      var a = doc.createElement("a");
      a.className = "arrow-link";
      a.href = url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.innerHTML = "<span>View report</span><span class=\"arrow\">↗</span>";
      item.appendChild(a);
      list.appendChild(item);
    });
    slot.innerHTML = "";
    slot.appendChild(list);
  });

  /* ---------- Resume / contact swaps ---------- */
  var resumeLinks = doc.querySelectorAll("[data-resume]");
  resumeLinks.forEach(function (a) {
    a.href = RESUME_URL;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
  });

  /* ---------- Scrollspy: gold underline on the section in view ----------
     Only on pages whose nav uses same-page anchors; harmless elsewhere. */
  (function scrollspy() {
    var links = [].slice.call(doc.querySelectorAll(".nav a[href^='#']"));
    if (!links.length || !("IntersectionObserver" in window)) return;
    var byId = {};
    links.forEach(function (a) {
      var id = a.getAttribute("href").slice(1);
      var sec = id && doc.getElementById(id);
      if (sec) byId[id] = byId[id] || { sec: sec, links: [] };
      if (sec) byId[id].links.push(a);
    });
    var ids = Object.keys(byId);
    if (!ids.length) return;
    function clear() { links.forEach(function (a) { a.removeAttribute("aria-current"); }); }
    var spy = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        clear();
        (byId[en.target.id].links || []).forEach(function (a) {
          a.setAttribute("aria-current", "page");
        });
      });
    }, { rootMargin: "-40% 0px -55% 0px", threshold: 0 });
    ids.forEach(function (id) { spy.observe(byId[id].sec); });
  })();

  /* ---------- Launch QA ---------- */
  var html = doc.documentElement.outerHTML;
  var issues = [];
  if (html.indexOf("bhojraj@bhojrajkamdi.com") !== -1) issues.push("Stale placeholder email present: bhojraj@bhojrajkamdi.com");
  if (html.indexOf("linkedin.com/in/bhojraj-kamdi") !== -1) issues.push("Stale placeholder LinkedIn URL present");
  if (html.indexOf("assets/bhojraj-kamdi-resume.pdf") !== -1) issues.push("Resume file not published at assets/ — use the Google Doc link instead");
  if (window.console && window.console.warn && issues.length) {
    issues.forEach(function (msg) { console.warn("[Pre-launch] " + msg); });
  }
})();