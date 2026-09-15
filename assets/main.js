/* ============================================================
   BHOJRAJ KAMDI — PORTFOLIO SCRIPT
   ============================================================ */

(function () {
  "use strict";

  /* ------------------------------------------------------------------
     LINK INTEGRITY CHECKLIST
     Verified production values. The console QA below warns when any
     page still carries an old placeholder or is missing a real link.
     ------------------------------------------------------------------ */
  var EXPECTED_LINKEDIN = "https://www.linkedin.com/in/bhojrajkamdi";
  var EXPECTED_EMAIL = "bhojrajkamdi14@gmail.com";
  var EXPECTED_RESUME = "https://docs.google.com/document/d/1BFeB2oi3oYkQRqjwEmUpC3M__p_ACSpZ/edit";
  var OLD_LINKEDIN = "https://www.linkedin.com/in/bhojraj-kamdi";
  var OLD_EMAIL = "bhojraj@bhojrajkamdi.com";
  var OLD_RESUME = "assets/bhojraj-kamdi-resume.pdf";

  /* ---------- Footer year ---------- */
  var yearEl = document.getElementById("year");
  if (yearEl) {
    yearEl.textContent = new Date().getFullYear();
  }

  /* ---------- Topbar scrolled state ---------- */
  var topbar = document.getElementById("topbar");
  var onScroll = function () {
    if (!topbar) return;
    if (window.scrollY > 8) {
      topbar.classList.add("scrolled");
    } else {
      topbar.classList.remove("scrolled");
    }
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* ---------- Mobile menu ---------- */
  var toggle = document.getElementById("navToggle");
  var menu = document.getElementById("mobileMenu");

  var closeMenu = function () {
    if (!menu || !toggle) return;
    menu.classList.remove("open");
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", "Open menu");
    document.body.style.overflow = "";
  };

  var openMenu = function () {
    if (!menu || !toggle) return;
    menu.classList.add("open");
    toggle.setAttribute("aria-expanded", "true");
    toggle.setAttribute("aria-label", "Close menu");
    document.body.style.overflow = "hidden";
  };

  if (toggle && menu) {
    toggle.addEventListener("click", function () {
      if (menu.classList.contains("open")) {
        closeMenu();
      } else {
        openMenu();
      }
    });
    menu.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", closeMenu);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeMenu();
    });
  }

  /* ---------- Reveal on scroll ---------- */
  var revealEls = document.querySelectorAll(".rv");
  if ("IntersectionObserver" in window) {
    var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      revealEls.forEach(function (el) { el.classList.add("in"); });
    } else {
      var observer = new IntersectionObserver(
        function (entries) {
          entries.forEach(function (entry) {
            if (entry.isIntersecting) {
              entry.target.classList.add("in");
              observer.unobserve(entry.target);
            }
          });
        },
        { threshold: 0.14, rootMargin: "0px 0px -40px 0px" }
      );
      revealEls.forEach(function (el) { observer.observe(el); });
    }
  } else {
    revealEls.forEach(function (el) { el.classList.add("in"); });
  }

  /* ---------- Link integrity QA ---------- */
  if (window.console && window.console.warn) {
    var html = document.documentElement.outerHTML;
    var issues = [];
    if (html.indexOf(OLD_EMAIL) !== -1) {
      issues.push("Old placeholder email still present: " + OLD_EMAIL);
    }
    if (html.indexOf(OLD_LINKEDIN) !== -1) {
      issues.push("Old placeholder LinkedIn URL still present: " + OLD_LINKEDIN);
    }
    if (html.indexOf(OLD_RESUME) !== -1) {
      issues.push("Old placeholder resume path still present: " + OLD_RESUME);
    }
    if (html.indexOf(EXPECTED_LINKEDIN) === -1) {
      issues.push("Verified LinkedIn URL missing from page.");
    }
    if (html.indexOf(EXPECTED_EMAIL) === -1) {
      issues.push("Verified email address missing from page.");
    }
    if (html.indexOf(EXPECTED_RESUME) === -1) {
      issues.push("Verified resume Drive URL missing from page.");
    }
    if (issues.length) {
      issues.forEach(function (msg) {
        console.warn("[Portfolio pre-launch check] " + msg);
      });
    }
  }
})();