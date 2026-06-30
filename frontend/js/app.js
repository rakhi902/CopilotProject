/*
 * Job Application Co-Pilot - application controller.
 *
 * A tiny hand-rolled SPA: a single `state` object, a `render()` that swaps the
 * active view into #view, and view functions that build markup and wire events.
 * No framework, no build step. Everything is wrapped in an IIFE.
 *
 * Views:
 *   "auth"      -> sign in / create account
 *   "workspace" -> the command center: a roster of all applications (left) and a
 *                  tabbed stage of the four artifacts for the selected role (right)
 *   "new"       -> the "brief your co-pilot" upload form
 */
(function () {
  "use strict";

  // --- Application state ----------------------------------------------------
  var state = {
    user: null,          // the signed-in user (from /auth/me), or null
    roles: [],           // cached roles list (the pipeline), newest first
    drafts: {},          // map: String(roleId) -> latest draft (or null), cached
    activeRoleId: null,  // String id of the role shown in the stage
    activeTab: "fit",    // which artifact tab is open: fit|resume|cover|interview
    rosterFilter: "",    // live search text filtering the roster pipeline
    selectedRoleIds: {}, // set (id -> true) of roster items ticked for bulk delete
    view: "auth",        // current view name
    authMode: "login",   // "login" | "register"
    pollTimer: null,     // active setInterval id while a draft is generating
    landingTimer: null,  // diff-demo cycle interval on the public landing page
    landingObserver: null, // scroll-reveal IntersectionObserver (landing)
    landingScroll: null  // landing nav scroll-shadow listener
  };

  // The four agents, shown in the loading pipeline (cosmetic, indeterminate).
  var PIPELINE_STAGES = [
    { n: "01", name: "Fit Analyst", note: "matching you to the role" },
    { n: "02", name: "Resume Writer", note: "rewriting your bullets" },
    { n: "03", name: "Cover Letter", note: "drafting your letter" },
    { n: "04", name: "Interviewer", note: "preparing your questions" }
  ];

  // The four artifact tabs of the stage. `label` is the tab text; `title` is the
  // heading shown inside the pane; `no` is the editorial section number.
  var TABS = [
    { id: "fit", no: "01", label: "Fit Analysis", title: "Fit analysis" },
    { id: "resume", no: "02", label: "Resume Diff", title: "Resume rewrite" },
    { id: "cover", no: "03", label: "Cover Letter", title: "Cover letter" },
    { id: "interview", no: "04", label: "Interview Q&A", title: "Interview prep" },
    { id: "salary", no: "05", label: "Salary Coach", title: "Salary coach" }
  ];
  var TAB_IDS = TABS.map(function (t) { return t.id; });

  // The user-curated application statuses (must match the backend enum values).
  var APPLICATION_STATUSES = ["Not Applied", "Applied", "Interviewing", "Rejected"];

  // Friendly labels for the regeneratable artifacts (for toasts).
  var ARTIFACT_LABELS = { resume: "resume rewrite", cover: "cover letter", interview: "interview Q&A" };

  var POLL_INTERVAL_MS = 2000;
  var POLL_MAX_ATTEMPTS = 90; // ~3 minutes before we stop and show a timeout note.

  // Cached top-level elements.
  var viewEl = document.getElementById("view");
  var mastheadEl = document.getElementById("masthead");
  var toastsEl = document.getElementById("toasts");

  // ======================================================================
  // Small utilities
  // ======================================================================

  /** Escape a value so it is safe to drop into an innerHTML template. */
  function esc(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  /** Format an ISO timestamp as a short, human date. */
  function formatDate(isoString) {
    if (!isoString) return "";
    var date = new Date(isoString);
    if (isNaN(date.getTime())) return "";
    return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }

  /** Replace the #view contents with the given HTML and return the container. */
  function setView(html) {
    stopPolling(); // navigating anywhere cancels any in-flight polling.
    stopLandingFx(); // ...and tears down any landing-page animations/observers.
    viewEl.innerHTML = html;
    window.scrollTo({ top: 0, behavior: "instant" in document.documentElement.style ? "instant" : "auto" });
    return viewEl;
  }

  /** Show a transient toast. kind: "" | "error" | "success". */
  function toast(message, kind) {
    var node = document.createElement("div");
    node.className = "toast" + (kind ? " toast-" + kind : "");
    node.innerHTML = '<span>' + esc(message) + '</span><button class="toast-x" aria-label="Dismiss">×</button>';
    node.querySelector(".toast-x").addEventListener("click", function () { node.remove(); });
    toastsEl.appendChild(node);
    setTimeout(function () { node.remove(); }, 6000);
  }

  /** Render a status pill for a draft status string. */
  function statusPill(status) {
    var label = status || "unknown";
    return '<span class="pill pill-' + esc(status) + '">' + esc(label) + "</span>";
  }

  /** Find a cached role by (string-coerced) id. */
  function findRole(roleId) {
    var wanted = String(roleId);
    for (var i = 0; i < state.roles.length; i++) {
      if (String(state.roles[i].id) === wanted) return state.roles[i];
    }
    return null;
  }

  /**
   * Centralized API-error handling: a 401 means our token is stale, so we log
   * out and bounce to the auth screen; everything else becomes a toast.
   */
  function handleApiError(error) {
    if (error && error.status === 401) {
      API.logout();
      state.user = null;
      toast("Your session expired. Please sign in again.", "error");
      navigate("auth");
      return;
    }
    toast((error && error.message) || "Something went wrong.", "error");
  }

  // ======================================================================
  // Navigation / routing
  // ======================================================================

  /** Switch views. "workspace" optionally takes a roleId to pre-select. */
  function navigate(view, param) {
    state.view = view;
    renderMasthead();
    if (view === "landing") return renderLanding();
    if (view === "auth") return renderAuth();
    if (view === "home") return renderHome();
    if (view === "workspace") return renderWorkspace(param);
    if (view === "new") return renderNewApplication();
  }

  // ======================================================================
  // Off-canvas pipeline sidebar (the roster slides in over the stage)
  // ======================================================================

  /** Is the roster sidebar currently slid open? */
  function isSidebarOpen() {
    var roster = document.getElementById("roster");
    return !!roster && roster.classList.contains("is-open");
  }

  /** Slide the roster in and raise the dimming backdrop. */
  function openSidebar() {
    var roster = document.getElementById("roster");
    if (!roster) return;
    roster.classList.add("is-open");
    roster.setAttribute("aria-hidden", "false");
    var backdrop = document.getElementById("sidebar-backdrop");
    if (backdrop) backdrop.classList.add("is-open");
    var toggle = document.getElementById("nav-pipeline");
    if (toggle) toggle.setAttribute("aria-expanded", "true");
  }

  /** Slide the roster away and drop the backdrop. */
  function closeSidebar() {
    var roster = document.getElementById("roster");
    if (roster) { roster.classList.remove("is-open"); roster.setAttribute("aria-hidden", "true"); }
    var backdrop = document.getElementById("sidebar-backdrop");
    if (backdrop) backdrop.classList.remove("is-open");
    var toggle = document.getElementById("nav-pipeline");
    if (toggle) toggle.setAttribute("aria-expanded", "false");
  }

  /** Toggle the roster (wired to the masthead "☰ Pipeline" button). */
  function toggleSidebar() {
    if (isSidebarOpen()) closeSidebar();
    else openSidebar();
  }

  // ======================================================================
  // Masthead
  // ======================================================================

  /** Clear the session and all cached state, then return to the public landing. */
  function signOut() {
    API.logout();
    state.user = null;
    state.roles = [];
    state.drafts = {};
    state.activeRoleId = null;
    state.rosterFilter = "";
    state.selectedRoleIds = {};
    toast("Signed out.", "success");
    navigate("landing");
  }

  function renderMasthead() {
    // The masthead only makes sense once signed in (and not on the auth screen).
    if (!state.user || state.view === "auth" || state.view === "landing") {
      mastheadEl.hidden = true;
      mastheadEl.innerHTML = "";
      return;
    }
    mastheadEl.hidden = false;
    // The "☰ Pipeline" toggle only belongs on the workspace, where the roster lives.
    var pipelineToggle = state.view === "workspace"
      ? '<button class="masthead-toggle" id="nav-pipeline" type="button" aria-controls="roster" aria-expanded="false" aria-label="Toggle the pipeline sidebar">' +
          '<span class="mt-ico" aria-hidden="true">☰</span><span class="mt-label">Pipeline</span>' +
        "</button>"
      : "";
    mastheadEl.innerHTML =
      '<div class="masthead-left">' +
        pipelineToggle +
        '<div class="brand" id="brand-home" role="button" tabindex="0">' +
          '<span class="brand-mark"><svg class="brand-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/></svg></span>' +
          '<span class="brand-name">Co·Pilot</span>' +
          '<span class="brand-kicker">Application Desk</span>' +
        "</div>" +
      "</div>" +
      '<div class="masthead-actions">' +
        '<span class="masthead-user">' + esc(state.user.email) + "</span>" +
        '<button class="btn btn-ghost" id="nav-desk">Dashboard</button>' +
        '<button class="btn btn-primary" id="nav-new">New application</button>' +
        '<button class="btn btn-ghost" id="nav-logout">Sign out</button>' +
      "</div>";

    // The logo is the always-available way back to the public landing page.
    var goLanding = function () { navigate("landing"); };
    var brandEl = mastheadEl.querySelector("#brand-home");
    brandEl.addEventListener("click", goLanding);
    brandEl.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); goLanding(); }
    });
    mastheadEl.querySelector("#nav-desk").addEventListener("click", function () { navigate("home"); });
    mastheadEl.querySelector("#nav-new").addEventListener("click", function () { navigate("new"); });
    mastheadEl.querySelector("#nav-logout").addEventListener("click", signOut);
    var pipelineBtn = mastheadEl.querySelector("#nav-pipeline");
    if (pipelineBtn) pipelineBtn.addEventListener("click", toggleSidebar);
  }

  // ======================================================================
  // Landing: the public front door (shown to logged-out visitors)
  // ======================================================================
  //
  // A conversion-focused marketing page that sells the product before sign-up:
  // an editorial hero with a LIVE résumé "diff" demo that cycles real rewrites,
  // a by-the-numbers strip, a four-pass walkthrough, a feature gallery, the
  // grounding/anti-fabrication promise, and CTAs into the auth screen. Built from
  // the same tokens as the app, with scroll-reveal + count-up motion that all
  // collapses gracefully under prefers-reduced-motion. Every stat is product-true
  // (4 agents, 5 artifacts, grounded) - no invented users or testimonials.

  // Real before/after bullet rewrites the hero demo cycles through.
  var LP_DEMO = [
    { old: "Responsible for backend APIs and some database work.",
      neu: "Architected FastAPI services handling 1M+ requests/day at p99 < 120 ms.",
      why: "A vague duty becomes quantified scale, surfacing the JD’s “FastAPI”." },
    { old: "Worked on the data team to help with pipelines.",
      neu: "Built the nightly ETL that cut batch time from 6 h to 40 min.",
      why: "Concrete, measurable impact a screener and a human both notice." },
    { old: "Helped improve our testing and code quality.",
      neu: "Drove unit coverage 48% → 91%, gating every deploy on green CI.",
      why: "Numbers and ownership replace a soft, forgettable line." }
  ];

  function lpNavHtml() {
    var actions = state.user
      ? '<button class="btn btn-ghost" id="lp-signout">Sign out</button>' +
        '<button class="btn btn-primary" id="lp-enter">Enter the desk →</button>'
      : '<button class="btn btn-ghost" id="lp-signin">Sign in</button>' +
        '<button class="btn btn-primary" id="lp-start">Get started →</button>';
    return (
      '<nav class="lp-nav" id="lp-nav">' +
        '<div class="brand" id="lp-brand" role="button" tabindex="0" aria-label="Back to top">' +
          '<span class="brand-mark"><svg class="brand-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/></svg></span>' +
          '<span class="brand-name">Co·Pilot</span>' +
          '<span class="brand-kicker">Application Desk</span>' +
        "</div>" +
        '<div class="lp-nav-actions">' + actions + "</div>" +
      "</nav>"
    );
  }

  function lpHeroHtml() {
    return (
      '<header class="lp-hero">' +
        '<div class="lp-hero-copy reveal">' +
          '<p class="eyebrow">Your editor for the job hunt</p>' +
          '<h1 class="lp-h1">Every application, <em>marked up</em> by a master editor.</h1>' +
          '<p class="lp-lead">Hand over your résumé and a job description. Your co-pilot reads the fit, rewrites your bullets, drafts the cover letter, and rehearses your interview — all grounded in your real experience.</p>' +
          '<div class="lp-hero-cta">' +
            (state.user
              ? '<button class="btn btn-primary btn-lg" id="lp-enter-hero">Open your desk →</button>'
              : '<button class="btn btn-primary btn-lg" id="lp-hero-start">Start free →</button>') +
            '<button class="btn btn-ghost btn-lg" id="lp-hero-how">See how it works</button>' +
          "</div>" +
          '<p class="lp-microcopy">Free to start · grounded in your real experience, never fabricated.</p>' +
        "</div>" +
        '<div class="lp-hero-demo reveal">' +
          '<div class="lp-diff" id="lp-diff">' +
            '<div class="lp-diff-head"><span class="lp-diff-dots"></span><span class="lp-diff-file">résumé.pdf · marked up</span></div>' +
            '<div class="lp-diff-body">' +
              '<div class="lp-diff-old"><span class="diff-tag">Original</span><p></p></div>' +
              '<div class="lp-diff-new"><span class="diff-tag">Rewritten</span><p></p></div>' +
              '<p class="lp-diff-why"></p>' +
            "</div>" +
          "</div>" +
        "</div>" +
      "</header>"
    );
  }

  function lpStripHtml() {
    var items = [
      { n: "4", unit: "", label: "specialist agents, in sequence" },
      { n: "5", unit: "", label: "tailored artifacts per role" },
      { n: "100", unit: "%", label: "grounded in your real experience" },
      { n: "60", unit: "s", prefix: "<", label: "from upload to a ready kit" }
    ];
    return (
      '<section class="lp-strip reveal">' +
        items.map(function (it) {
          return (
            '<div class="lp-strip-item">' +
              '<span class="lp-strip-n">' +
                (it.prefix ? '<span class="lp-strip-pre">' + it.prefix + "</span>" : "") +
                '<span data-count="' + it.n + '">0</span>' +
                (it.unit ? '<span class="lp-strip-unit">' + it.unit + "</span>" : "") +
              "</span>" +
              '<span class="lp-strip-label">' + esc(it.label) + "</span>" +
            "</div>"
          );
        }).join("") +
      "</section>"
    );
  }

  function lpHowHtml() {
    var steps = [
      { t: "Brief your co-pilot", d: "Upload your résumé as a PDF and paste the job description — or just drop a link and we’ll fetch it." },
      { t: "Four agents go to work", d: "A Fit Analyst, Résumé Writer, Cover-Letter writer, and Interviewer run in sequence over your material." },
      { t: "Get your marked-up kit", d: "A fit score, a proofreader’s diff of every bullet, a one-page letter, and ten grounded interview answers." },
      { t: "Tune, rehearse, apply", d: "Run an ATS keyword scan, practice answers by voice, draft salary scripts, then export to PDF or DOCX." }
    ];
    return (
      '<section class="lp-section" id="lp-how">' +
        '<header class="lp-sec-head reveal">' +
          '<p class="eyebrow">How it works</p>' +
          "<h2>From blank page to interview-ready in four passes.</h2>" +
        "</header>" +
        '<ol class="lp-steps">' +
          steps.map(function (s, i) {
            return (
              '<li class="lp-step reveal">' +
                '<span class="lp-step-n">' + ("0" + (i + 1)).slice(-2) + "</span>" +
                "<div><h3>" + esc(s.t) + "</h3><p>" + esc(s.d) + "</p></div>" +
              "</li>"
            );
          }).join("") +
        "</ol>" +
      "</section>"
    );
  }

  function lpFeaturesHtml() {
    var feats = [
      { ic: "◎", t: "Fit Analysis", d: "A computed 0–100 score with exactly what you meet, what’s missing, and what to lead with." },
      { ic: "±", t: "Résumé Diff", d: "Your bullets rewritten beside the originals in proofreader’s red and green, each with a why." },
      { ic: "✎", t: "Cover Letter", d: "A grounded one-page letter that bridges gaps with first principles, not fabricated skills." },
      { ic: "❝", t: "Interview Q&A", d: "Ten likely questions with sample answers drawn from your real experience — rehearse by voice." },
      { ic: "⚡", t: "ATS Scan", d: "A keyword screen that ignores hedged “haven’t used” mentions and tells you what to add honestly." },
      { ic: "₹", t: "Salary Coach", d: "Two ready-to-send negotiation scripts the moment an offer lands." }
    ];
    return (
      '<section class="lp-section">' +
        '<header class="lp-sec-head reveal">' +
          '<p class="eyebrow">What you get</p>' +
          "<h2>Five artifacts. One application kit.</h2>" +
        "</header>" +
        '<div class="lp-feature-grid">' +
          feats.map(function (f) {
            return (
              '<article class="lp-feature reveal">' +
                '<span class="lp-feature-ic">' + f.ic + "</span>" +
                "<h3>" + esc(f.t) + "</h3>" +
                "<p>" + esc(f.d) + "</p>" +
              "</article>"
            );
          }).join("") +
        "</div>" +
      "</section>"
    );
  }

  function lpHonestyHtml() {
    return (
      '<section class="lp-honesty-wrap">' +
        '<div class="lp-honesty reveal">' +
          '<p class="eyebrow">The non-negotiable</p>' +
          "<h2>Grounded, or it doesn’t ship.</h2>" +
          "<p>A dedicated fact-checker audits every cover letter against your résumé. If it claims a skill you don’t actually have, it gets sent back and rewritten — no invented experience, no padded keywords. Just work you’d be glad to defend in the room.</p>" +
        "</div>" +
      "</section>"
    );
  }

  function lpCtaHtml() {
    if (state.user) {
      return (
        '<section class="lp-cta reveal">' +
          "<h2>Your desk is ready when you are.</h2>" +
          "<p>Pick up where you left off, or brief your co-pilot on a new role.</p>" +
          '<button class="btn btn-primary btn-lg" id="lp-enter-cta">Back to your desk →</button>' +
        "</section>"
      );
    }
    return (
      '<section class="lp-cta reveal">' +
        "<h2>Stop sending the same résumé into the void.</h2>" +
        "<p>Turn your next application into a tailored, honest, interview-ready kit — in about a minute.</p>" +
        '<button class="btn btn-primary btn-lg" id="lp-cta-start">Create your free account →</button>' +
      "</section>"
    );
  }

  function lpFooterHtml() {
    return (
      '<footer class="lp-footer">' +
        '<div class="brand"><span class="brand-mark"><svg class="brand-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/></svg></span><span class="brand-name">Co·Pilot</span></div>' +
        '<p class="lp-foot-tag">Your editor for the job hunt.</p>' +
        '<div class="lp-foot-actions">' +
          (state.user
            ? '<button class="linkish" id="lp-signout-foot">Sign out</button>' +
              '<button class="btn btn-primary" id="lp-enter-foot">Enter the desk →</button>'
            : '<button class="linkish" id="lp-foot-signin">Sign in</button>' +
              '<button class="btn btn-primary" id="lp-foot-start">Get started →</button>') +
        "</div>" +
      "</footer>"
    );
  }

  /** Cycle the hero diff demo through LP_DEMO (static first frame if reduced-motion). */
  function startLpDemo() {
    var el = viewEl.querySelector("#lp-diff");
    if (!el) return;
    var body = el.querySelector(".lp-diff-body");
    var oldP = el.querySelector(".lp-diff-old p");
    var newP = el.querySelector(".lp-diff-new p");
    var whyP = el.querySelector(".lp-diff-why");
    function paint(d) {
      oldP.textContent = d.old;
      newP.textContent = d.neu;
      whyP.innerHTML = "<b>Why:</b> " + esc(d.why);
    }
    paint(LP_DEMO[0]);
    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) return;
    var i = 0;
    state.landingTimer = setInterval(function () {
      body.classList.add("is-swap");
      setTimeout(function () {
        i = (i + 1) % LP_DEMO.length;
        paint(LP_DEMO[i]);
        body.classList.remove("is-swap");
      }, 340);
    }, 3900);
  }

  /** Scroll-reveal a view's `.reveal` sections (and count up any [data-count] inside).
   *  Shared by the public landing page and the signed-in home. */
  function setupReveal() {
    var els = viewEl.querySelectorAll(".reveal");
    function countWithin(scope) {
      Array.prototype.forEach.call(scope.querySelectorAll("[data-count]"), function (n) {
        animateCount(n, n.getAttribute("data-count"));
      });
    }
    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || !("IntersectionObserver" in window)) {
      Array.prototype.forEach.call(els, function (el) { el.classList.add("is-visible"); countWithin(el); });
      return;
    }
    state.landingObserver = new IntersectionObserver(function (entries, obs) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        countWithin(entry.target);
        obs.unobserve(entry.target);
      });
    }, { threshold: 0.14, rootMargin: "0px 0px -6% 0px" });
    Array.prototype.forEach.call(els, function (el) { state.landingObserver.observe(el); });
  }

  /** Wire every landing CTA, the smooth-scroll, the brand, and the nav shadow. */
  function wireLanding() {
    function goAuth(mode) { return function () { state.authMode = mode; navigate("auth"); }; }
    [["#lp-start", "register"], ["#lp-hero-start", "register"], ["#lp-cta-start", "register"],
     ["#lp-foot-start", "register"], ["#lp-signin", "login"], ["#lp-foot-signin", "login"]
    ].forEach(function (pair) {
      var btn = viewEl.querySelector(pair[0]);
      if (btn) btn.addEventListener("click", goAuth(pair[1]));
    });

    // Returning (already-signed-in) visitors get "enter the app" + sign-out instead.
    ["#lp-enter", "#lp-enter-hero", "#lp-enter-cta", "#lp-enter-foot"].forEach(function (sel) {
      var btn = viewEl.querySelector(sel);
      if (btn) btn.addEventListener("click", function () { navigate("home"); });
    });
    ["#lp-signout", "#lp-signout-foot"].forEach(function (sel) {
      var btn = viewEl.querySelector(sel);
      if (btn) btn.addEventListener("click", signOut);
    });

    var how = viewEl.querySelector("#lp-hero-how");
    if (how) how.addEventListener("click", function () {
      var target = viewEl.querySelector("#lp-how");
      if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
    });

    var brand = viewEl.querySelector("#lp-brand");
    if (brand) {
      var toTop = function () { window.scrollTo({ top: 0, behavior: "smooth" }); };
      brand.addEventListener("click", toTop);
      brand.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toTop(); }
      });
    }

    var nav = viewEl.querySelector("#lp-nav");
    if (nav) {
      state.landingScroll = function () { nav.classList.toggle("is-scrolled", window.scrollY > 12); };
      window.addEventListener("scroll", state.landingScroll, { passive: true });
      state.landingScroll();
    }
  }

  /** Tear down landing-page timers/observers/listeners (called by setView). */
  function stopLandingFx() {
    if (state.landingTimer) { clearInterval(state.landingTimer); state.landingTimer = null; }
    if (state.landingObserver) { state.landingObserver.disconnect(); state.landingObserver = null; }
    if (state.landingScroll) { window.removeEventListener("scroll", state.landingScroll); state.landingScroll = null; }
  }

  /** Render the public landing page and start its interactions. */
  function renderLanding() {
    setView(
      '<div class="landing">' +
        lpNavHtml() +
        lpHeroHtml() +
        lpStripHtml() +
        lpHowHtml() +
        lpFeaturesHtml() +
        lpHonestyHtml() +
        lpCtaHtml() +
        lpFooterHtml() +
      "</div>"
    );
    startLpDemo();
    setupReveal();
    wireLanding();
  }

  // ======================================================================
  // Auth view
  // ======================================================================

  function renderAuth() {
    var isLogin = state.authMode === "login";
    setView(
      '<section class="auth">' +
        '<aside class="auth-hero">' +
          '<div class="brand" id="auth-brand" role="button" tabindex="0" title="Back to home">' +
            '<span class="brand-mark"><svg class="brand-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/></svg></span>' +
            '<span class="brand-name" style="color:var(--paper)">Co·Pilot</span>' +
          "</div>" +
          "<div>" +
            '<p class="eyebrow" style="color:#b9ac96;margin-bottom:1rem">Your editor for the job hunt</p>' +
            "<h1>Every application, <em>marked up</em> by a master editor.</h1>" +
            '<p class="hero-sub">Upload your resume and a job description. Your co-pilot analyses the fit, rewrites your bullets, drafts a cover letter, and prepares your interview.</p>' +
          "</div>" +
          '<ol class="hero-steps">' +
            '<li><span class="n">01</span><span>Reads your resume against the role</span></li>' +
            '<li><span class="n">02</span><span>Rewrites bullets to weave in the keywords</span></li>' +
            '<li><span class="n">03</span><span>Drafts a one-page cover letter</span></li>' +
            '<li><span class="n">04</span><span>Prepares ten grounded interview answers</span></li>' +
          "</ol>" +
        "</aside>" +
        '<div class="auth-panel">' +
          '<div class="auth-card stagger">' +
            '<div class="auth-tabs">' +
              '<button class="auth-tab' + (isLogin ? " is-active" : "") + '" data-mode="login">Sign in</button>' +
              '<button class="auth-tab' + (!isLogin ? " is-active" : "") + '" data-mode="register">Create account</button>' +
            "</div>" +
            '<form id="auth-form" novalidate>' +
              (isLogin
                ? ""
                : '<div class="field"><label for="f-name">Full name <span style="text-transform:none;letter-spacing:0">(optional)</span></label>' +
                  '<input class="input" id="f-name" type="text" autocomplete="name" placeholder="Ada Lovelace" /></div>') +
              '<div class="field"><label for="f-email">Email</label>' +
                '<input class="input" id="f-email" type="email" autocomplete="email" required placeholder="you@example.com" /></div>' +
              '<div class="field"><label for="f-password">Password</label>' +
                '<input class="input" id="f-password" type="password" autocomplete="' + (isLogin ? "current-password" : "new-password") + '" required placeholder="' + (isLogin ? "Your password" : "At least 8 characters") + '" /></div>' +
              '<div class="field-error" id="auth-error" hidden></div>' +
              '<button class="btn btn-primary btn-block" id="auth-submit" type="submit">' + (isLogin ? "Sign in" : "Create account") + "</button>" +
            "</form>" +
          "</div>" +
        "</div>" +
      "</section>"
    );

    // Tab switching, kept simple (there's no state to preserve).
    Array.prototype.forEach.call(viewEl.querySelectorAll(".auth-tab"), function (tab) {
      tab.addEventListener("click", function () {
        state.authMode = tab.getAttribute("data-mode");
        renderAuth();
      });
    });

    viewEl.querySelector("#auth-form").addEventListener("submit", onAuthSubmit);

    // The hero logo takes a visitor back out to the public landing page.
    var authBrand = viewEl.querySelector("#auth-brand");
    if (authBrand) {
      var toLanding = function () { navigate("landing"); };
      authBrand.addEventListener("click", toLanding);
      authBrand.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toLanding(); }
      });
    }
  }

  async function onAuthSubmit(event) {
    event.preventDefault();
    var isLogin = state.authMode === "login";
    var email = viewEl.querySelector("#f-email").value.trim();
    var password = viewEl.querySelector("#f-password").value;
    var nameInput = viewEl.querySelector("#f-name");
    var fullName = nameInput ? nameInput.value.trim() : "";
    var errorEl = viewEl.querySelector("#auth-error");
    var submitBtn = viewEl.querySelector("#auth-submit");

    errorEl.hidden = true;
    if (!email || !password) {
      errorEl.textContent = "Email and password are required.";
      errorEl.hidden = false;
      return;
    }
    if (!isLogin && password.length < 8) {
      errorEl.textContent = "Password must be at least 8 characters.";
      errorEl.hidden = false;
      return;
    }

    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner"></span>' + (isLogin ? "Signing in…" : "Creating…");
    try {
      if (!isLogin) {
        // Register, then immediately sign in for a seamless first experience.
        await API.register({ email: email, full_name: fullName || null, password: password });
      }
      await API.login({ email: email, password: password });
      state.user = await API.getCurrentUser();
      toast(isLogin ? "Welcome back." : "Account created.", "success");
      navigate("home");
    } catch (error) {
      submitBtn.disabled = false;
      submitBtn.textContent = isLogin ? "Sign in" : "Create account";
      errorEl.textContent = (error && error.message) || "Authentication failed.";
      errorEl.hidden = false;
    }
  }

  // ======================================================================
  // Shared pipeline data
  // ======================================================================

  /**
   * Fetch the user's roles (newest first) and prime the per-role draft cache:
   * one /draft call each, all in parallel, where a role with no draft (404) maps
   * to null. allSettled means one failure never sinks the whole load. Shared by
   * the Home overview and the workspace so both read one consistent snapshot.
   */
  async function loadRolesAndDrafts() {
    var roles = await API.listRoles();
    state.roles = roles || [];
    state.drafts = {};
    if (state.roles.length) {
      var settled = await Promise.allSettled(
        state.roles.map(function (role) { return API.getRoleDraft(role.id); })
      );
      settled.forEach(function (outcome, index) {
        state.drafts[String(state.roles[index].id)] = outcome.status === "fulfilled" ? outcome.value : null;
      });
    }
  }

  // ======================================================================
  // Home: "The Front Page" (the signed-in landing; reachable via the logo)
  // ======================================================================
  //
  // The job hunt rendered as the masthead of a publication you edit: a dateline,
  // an editorial greeting, a "by the numbers" deck (animated count-up), a lead
  // story (your strongest match), and a grid of recent dispatches that open the
  // workspace on click. A blank-front-page empty state greets brand-new users.

  /** First name for greetings: the given name, else the email handle, else "there". */
  function firstName() {
    var u = state.user || {};
    if (u.full_name && u.full_name.trim()) return u.full_name.trim().split(/\s+/)[0];
    if (u.email) return String(u.email).split("@")[0];
    return "there";
  }

  /** A time-of-day greeting, with a little editorial character at the edges. */
  function greetingWord() {
    var h = new Date().getHours();
    if (h < 5) return "Burning the midnight oil";
    if (h < 12) return "Good morning";
    if (h < 17) return "Good afternoon";
    if (h < 21) return "Good evening";
    return "Working late";
  }

  /**
   * Count a number element from 0 up to its target with an easeOut ramp. Honors
   * prefers-reduced-motion (sets the final value at once) and bails quietly if
   * the element is detached mid-animation (e.g. the user navigated away).
   */
  function animateCount(el, to, duration) {
    to = Number(to) || 0;
    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || to === 0) { el.textContent = String(to); return; }
    duration = duration || 750;
    var start = null;
    function step(ts) {
      if (!document.body.contains(el)) return;
      if (start === null) start = ts;
      var p = Math.min(1, (ts - start) / duration);
      var eased = 1 - Math.pow(1 - p, 3); // easeOutCubic
      el.textContent = String(Math.round(to * eased));
      if (p < 1) window.requestAnimationFrame(step);
      else el.textContent = String(to);
    }
    window.requestAnimationFrame(step);
  }

  /** The completed role with the highest fit score (the "lead story"), or null. */
  function strongestMatch() {
    var best = null, bestScore = -1;
    state.roles.forEach(function (role) {
      var draft = state.drafts[String(role.id)];
      if (!draft || draft.status !== "completed") return;
      var fit = draft.fit_analysis;
      var score = fit ? Number(fit.fit_score) : NaN;
      if (!isNaN(score) && score > bestScore) { bestScore = score; best = { role: role, score: score, fit: fit }; }
    });
    return best;
  }

  /** The greeting hero: a quiet brand+date kicker, the greeting, status, and CTAs. */
  function homeHeroHtml(dateline, statusLine) {
    return (
      '<header class="home-hero reveal">' +
        '<p class="eyebrow home-kicker"><span class="brand-mark"><svg class="brand-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/></svg></span> The Editor’s Desk · ' + esc(dateline) + "</p>" +
        '<h1 class="home-greeting">' + esc(greetingWord()) + ', <em>' + esc(firstName()) + "</em>.</h1>" +
        '<p class="home-status">' + esc(statusLine) + "</p>" +
        '<div class="home-cta">' +
          '<button class="btn btn-primary" id="home-new">Start a new application →</button>' +
          (state.roles.length ? '<button class="btn btn-ghost" id="home-pipeline">Open your pipeline</button>' : "") +
        "</div>" +
      "</header>"
    );
  }

  /** The "by the numbers" strip: four figures in one quiet card; numbers count up. */
  function homeStatsHtml(m) {
    var stats = [
      { value: m.total, label: "Applications" },
      { value: m.highFit, label: "High-fit · 80+" },
      { value: m.active, label: "On the press" },
      { value: m.failed, label: "Needs attention", alert: m.failed > 0 }
    ];
    return (
      '<section class="home-stats reveal" aria-label="Pipeline by the numbers">' +
        stats.map(function (s) {
          return (
            '<div class="home-stat' + (s.alert ? " is-alert" : "") + '">' +
              '<span class="home-stat-n" data-count="' + s.value + '">0</span>' +
              '<span class="home-stat-l">' + esc(s.label) + "</span>" +
            "</div>"
          );
        }).join("") +
      "</section>"
    );
  }

  /** The featured "lead story": the strongest match, with its fit ring. */
  function homeLeadHtml(lead) {
    var role = lead.role;
    var score = Math.max(0, Math.min(100, Math.round(lead.score)));
    var summary = lead.fit && lead.fit.overall_summary ? lead.fit.overall_summary : "";
    return (
      '<article class="home-lead reveal" data-role-id="' + esc(String(role.id)) + '" role="button" tabindex="0"' +
        ' aria-label="Open ' + esc(role.job_title) + " at " + esc(role.company) + '">' +
        '<div class="home-lead-body">' +
          '<p class="eyebrow">★ Your strongest match</p>' +
          "<h2>" + esc(role.company) + "</h2>" +
          '<p class="home-lead-role">' + esc(role.job_title) + "</p>" +
          (summary ? '<p class="home-lead-sum">' + esc(summary) + "</p>" : "") +
          '<span class="home-lead-open">Open the kit →</span>' +
        "</div>" +
        '<div class="home-lead-score">' +
          '<div class="score-ring" style="--val:' + score + '">' +
            '<div class="score-inner"><div class="score-num">' + score + '</div><div class="score-of">/ 100 FIT</div></div>' +
          "</div>" +
        "</div>" +
      "</article>"
    );
  }

  /** One recent-dispatch card (reuses .role-card; trailing = fit chip or status). */
  function homeRoleCardHtml(role, draft) {
    var status = draft ? draft.status : null;
    var fit = draft && draft.fit_analysis ? draft.fit_analysis.fit_score : null;
    var hasFit = fit !== null && fit !== undefined && fit !== "" && !isNaN(Number(fit));
    var trailing;
    if (status === "completed" && hasFit) {
      var s = Math.max(0, Math.min(100, Math.round(Number(fit))));
      trailing = '<span class="role-fit band-' + scoreBand(s) + '">' + s + " fit</span>";
    } else if (status && status !== "completed") {
      trailing = statusPill(status);
    } else {
      trailing = '<span class="role-fit role-fit-none">No kit yet</span>';
    }
    return (
      '<button class="role-card reveal" type="button" data-role-id="' + esc(String(role.id)) + '">' +
        '<div class="role-card-top">' + trailing + "</div>" +
        '<span class="role-company">' + esc(role.company) + "</span>" +
        '<span class="role-title">' + esc(role.job_title) + "</span>" +
        '<div class="role-meta">' +
          '<span class="role-date">' + esc(formatDate(role.created_at)) + "</span>" +
          '<span class="role-arrow">→</span>' +
        "</div>" +
      "</button>"
    );
  }

  /** The feed: the lead story (if any) + a grid of the most recent dispatches. */
  function homeFeedHtml() {
    var lead = strongestMatch();
    var recent = state.roles.slice(0, 6);
    var cards = recent.map(function (role) {
      return homeRoleCardHtml(role, state.drafts[String(role.id)]);
    }).join("");
    return (
      '<section class="home-feed">' +
        (lead ? homeLeadHtml(lead) : "") +
        '<div class="home-feed-head reveal">' +
          "<h2>Latest dispatches</h2>" +
          (state.roles.length > recent.length
            ? '<button class="linkish" id="home-all">See all ' + state.roles.length + " →</button>"
            : "") +
        "</div>" +
        '<div class="roles-grid">' + cards + "</div>" +
      "</section>"
    );
  }

  /** A blank-front-page invitation for users with no applications yet. */
  function homeEmptyHtml() {
    return (
      '<section class="home-empty reveal">' +
        '<div class="home-empty-mark"><svg class="brand-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/></svg></div>' +
        "<h2>The front page is yours to write.</h2>" +
        "<p>Brief your co-pilot with a resume and a job description, and your first edition — fit analysis, " +
          "rewritten bullets, a cover letter, and interview prep — rolls off the press in under a minute.</p>" +
        '<button class="btn btn-primary" id="home-empty-new">Start your first application →</button>' +
      "</section>"
    );
  }

  /** Wire the Home CTAs, the clickable lead/dispatch cards, and the count-up. */
  function wireHome() {
    ["#home-new", "#home-empty-new"].forEach(function (sel) {
      var btn = viewEl.querySelector(sel);
      if (btn) btn.addEventListener("click", function () { navigate("new"); });
    });
    ["#home-pipeline", "#home-all"].forEach(function (sel) {
      var btn = viewEl.querySelector(sel);
      if (btn) btn.addEventListener("click", function () { navigate("workspace"); });
    });

    // Every card carrying a role id opens that role in the workspace.
    Array.prototype.forEach.call(viewEl.querySelectorAll("[data-role-id]"), function (el) {
      var id = el.getAttribute("data-role-id");
      var go = function () { navigate("workspace", id); };
      el.addEventListener("click", go);
      if (el.getAttribute("role") === "button") {
        el.addEventListener("keydown", function (e) {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); }
        });
      }
    });
  }

  /** Render the Home front page: fetch a fresh snapshot, then paint the edition. */
  async function renderHome() {
    setView('<div class="center-screen"><span class="spinner"></span></div>');
    try {
      await loadRolesAndDrafts();
    } catch (error) {
      return handleApiError(error);
    }

    var m = computeMetrics();
    var hasRoles = state.roles.length > 0;

    var dateline = new Date().toLocaleDateString(undefined, {
      weekday: "long", year: "numeric", month: "long", day: "numeric"
    });

    var statusLine;
    if (!hasRoles) {
      statusLine = "A blank front page — let’s fill it.";
    } else if (m.active > 0) {
      statusLine = m.active + (m.active === 1 ? " application is" : " applications are") + " on the press right now.";
    } else {
      statusLine = m.total + (m.total === 1 ? " application" : " applications") + " in your pipeline" +
        (m.highFit > 0 ? " · " + m.highFit + " scoring 80+." : ".");
    }

    setView(
      '<div class="home">' +
        homeHeroHtml(dateline, statusLine) +
        (hasRoles ? homeStatsHtml(m) : "") +
        (hasRoles ? homeFeedHtml() : homeEmptyHtml()) +
      "</div>"
    );

    wireHome();
    setupReveal(); // scroll-reveal + count-up, shared with the landing page
  }

  // ======================================================================
  // Workspace: the command center (roster pipeline + tabbed stage)
  // ======================================================================

  /**
   * Render the whole command center. Fetches the roles list and each role's
   * latest draft once (so the roster can show pipeline status and switching
   * between roles is instant), then paints the split layout.
   * @param {string|number} [roleIdToSelect]  Role to open in the stage.
   */
  async function renderWorkspace(roleIdToSelect) {
    setView('<div class="center-screen"><span class="spinner"></span></div>');

    try {
      await loadRolesAndDrafts();
    } catch (error) {
      return handleApiError(error);
    }

    // Drop any multi-select ticks that point at roles which no longer exist.
    Object.keys(state.selectedRoleIds).forEach(function (id) {
      if (!(id in state.drafts)) delete state.selectedRoleIds[id];
    });

    // Decide which role to open: the requested one, else the previously active
    // one if it still exists, else the most recent (first) role.
    var ids = state.roles.map(function (role) { return String(role.id); });
    var wanted = roleIdToSelect !== undefined && roleIdToSelect !== null ? String(roleIdToSelect) : null;
    if (wanted && ids.indexOf(wanted) !== -1) {
      state.activeRoleId = wanted;
    } else if (state.activeRoleId && ids.indexOf(state.activeRoleId) !== -1) {
      // keep the current selection
    } else {
      state.activeRoleId = ids.length ? ids[0] : null;
    }

    paintWorkspaceShell();
    renderRoster();
    if (state.activeRoleId) {
      selectRole(state.activeRoleId);
    } else {
      renderStageEmpty();
    }
  }

  /** Paint the empty split-screen frame: a diagnostics strip, an aside roster,
   *  and a section stage. */
  function paintWorkspaceShell() {
    setView(
      '<div class="metrics" id="metrics" hidden aria-label="Pipeline diagnostics"></div>' +
      '<div class="workspace">' +
        '<aside class="roster" id="roster" aria-label="Your applications" aria-hidden="true"></aside>' +
        '<div class="sidebar-backdrop" id="sidebar-backdrop"></div>' +
        '<section class="stage" id="stage"></section>' +
      "</div>"
    );
    // Clicking the dimmed backdrop slides the sidebar away.
    var backdrop = viewEl.querySelector("#sidebar-backdrop");
    if (backdrop) backdrop.addEventListener("click", closeSidebar);
  }

  // --- Live pipeline diagnostics (the metrics strip atop the workspace) -----

  /**
   * Tally real-time engine diagnostics from the cached roles + their drafts:
   * total applications, high-fit matches (fit_score >= 80), pipelines still
   * generating, and runs that failed. Reads only cached state - no network.
   */
  function computeMetrics() {
    var total = state.roles.length;
    var highFit = 0, active = 0, failed = 0;
    state.roles.forEach(function (role) {
      var draft = state.drafts[String(role.id)];
      if (!draft) return;
      if (draft.status === "pending" || draft.status === "processing") active += 1;
      if (draft.status === "failed") failed += 1;
      var fit = draft.fit_analysis;
      var score = fit ? Number(fit.fit_score) : NaN;
      if (!isNaN(score) && score >= 80) highFit += 1;
    });
    return { total: total, highFit: highFit, active: active, failed: failed };
  }

  /**
   * Paint the diagnostics strip from computeMetrics(). Hidden until there is a
   * pipeline to report on. The "active" card breathes while work is in flight.
   */
  function renderMetrics() {
    var el = viewEl.querySelector("#metrics");
    if (!el) return;
    if (!state.roles.length) { el.hidden = true; el.innerHTML = ""; return; }
    var m = computeMetrics();
    var cards = [
      { k: "total", value: m.total, label: "Applications", note: "in your pipeline" },
      { k: "fit", value: m.highFit, label: "High-fit matches", note: "scoring 80+" },
      { k: "active", value: m.active, label: "Active pipelines", note: "generating now" },
      { k: "failed", value: m.failed, label: "Needs attention", note: "failed runs" }
    ];
    el.hidden = false;
    el.innerHTML = cards.map(function (c) {
      var live = (c.k === "active" && c.value > 0) ? " is-live" : "";
      return (
        '<div class="metric metric-' + c.k + live + '">' +
          '<span class="metric-value">' + c.value + "</span>" +
          '<span class="metric-label">' + esc(c.label) + "</span>" +
          '<span class="metric-note">' + esc(c.note) + "</span>" +
        "</div>"
      );
    }).join("");
  }

  /**
   * Fill the roster with one item per role (the pipeline), a "new" button, and a
   * live search field that filters the pipeline by company or job title.
   */
  function renderRoster() {
    renderMetrics(); // keep the diagnostics strip in step with the pipeline
    var rosterEl = viewEl.querySelector("#roster");
    if (!rosterEl) return;

    var count = state.roles.length;
    var head =
      '<div class="roster-head">' +
        '<p class="eyebrow">Pipeline' + (count ? " · " + count : "") + "</p>" +
        '<button class="roster-new" id="roster-new" title="New application" aria-label="New application">+</button>' +
      "</div>";

    // The filter is only useful once there is a pipeline to search through.
    var search = count
      ? '<input class="roster-search" id="roster-search" type="search" autocomplete="off"' +
          ' placeholder="Filter by company or title…" aria-label="Filter applications"' +
          ' value="' + esc(state.rosterFilter || "") + '" />'
      : "";

    var list;
    if (!count) {
      list = '<p class="pane-note" style="padding:0.4rem 0">No applications yet.</p>';
    } else {
      list =
        '<div class="roster-list" id="roster-list">' +
          state.roles.map(function (role) {
            return rosterItemHtml(role, state.drafts[String(role.id)]);
          }).join("") +
        "</div>" +
        '<p class="pane-note" id="roster-no-match" hidden style="padding:0.4rem 0"></p>';
    }
    // Bulk-action bar: shown only while one or more items are ticked.
    var actions =
      '<div class="roster-actions" id="roster-actions" hidden>' +
        '<span class="roster-sel-count" id="roster-sel-count"></span>' +
        '<button class="linkish" id="roster-clear-sel" type="button">Clear</button>' +
        '<button class="btn btn-ghost roster-del-btn" id="roster-del-sel" type="button">Delete</button>' +
      "</div>";

    rosterEl.innerHTML = head + search + actions + list;

    rosterEl.querySelector("#roster-new").addEventListener("click", function () { navigate("new"); });

    // Wire each roster item: the body selects the role for the stage; the
    // checkbox drives multi-select; the dropdown updates the application status.
    Array.prototype.forEach.call(rosterEl.querySelectorAll(".roster-item"), function (item) {
      var id = item.getAttribute("data-role-id");
      var main = item.querySelector(".ri-main");
      // Picking a role closes the sidebar, revealing the freshly-loaded stage.
      if (main) main.addEventListener("click", function () { closeSidebar(); selectRole(id); });
      var check = item.querySelector(".ri-check");
      if (check) check.addEventListener("change", function () { toggleRoleSelection(id, check.checked); });
      var statusSel = item.querySelector(".ri-status");
      if (statusSel) statusSel.addEventListener("change", function () { onStatusChange(id, statusSel.value, statusSel); });
    });

    var clearBtn = rosterEl.querySelector("#roster-clear-sel");
    if (clearBtn) clearBtn.addEventListener("click", clearSelection);
    var delBtn = rosterEl.querySelector("#roster-del-sel");
    if (delBtn) delBtn.addEventListener("click", deleteSelectedRoles);

    var searchEl = rosterEl.querySelector("#roster-search");
    if (searchEl) {
      searchEl.addEventListener("input", function () {
        state.rosterFilter = searchEl.value;
        applyRosterFilter();
      });
    }

    renderRosterActions();
    applyRosterFilter(); // re-apply any active filter after a (re-)render
  }

  // --- Multi-select + per-role status -----------------------------------

  /** Tick/untick a roster item for bulk delete. */
  function toggleRoleSelection(roleId, selected) {
    var id = String(roleId);
    if (selected) state.selectedRoleIds[id] = true;
    else delete state.selectedRoleIds[id];
    var item = viewEl.querySelector('.roster-item[data-role-id="' + id + '"]');
    if (item) item.classList.toggle("is-selected", !!selected);
    renderRosterActions();
  }

  /** The currently-ticked role ids. */
  function selectedIdList() {
    return Object.keys(state.selectedRoleIds);
  }

  /** Clear all multi-select ticks. */
  function clearSelection() {
    state.selectedRoleIds = {};
    Array.prototype.forEach.call(viewEl.querySelectorAll(".roster-item"), function (item) {
      item.classList.remove("is-selected");
      var check = item.querySelector(".ri-check");
      if (check) check.checked = false;
    });
    renderRosterActions();
  }

  /** Show/hide the bulk-action bar and update its labels from the selection. */
  function renderRosterActions() {
    var bar = viewEl.querySelector("#roster-actions");
    if (!bar) return;
    var ids = selectedIdList();
    bar.hidden = ids.length === 0;
    if (!ids.length) return;
    var label = viewEl.querySelector("#roster-sel-count");
    if (label) label.textContent = ids.length + " selected";
    var delBtn = viewEl.querySelector("#roster-del-sel");
    if (delBtn) delBtn.textContent = "Delete " + ids.length;
  }

  /** Bulk-delete every ticked role (with a confirm), then refresh the workspace. */
  async function deleteSelectedRoles() {
    var ids = selectedIdList().map(Number);
    if (!ids.length) return;
    var plural = ids.length > 1 ? "s" : "";
    if (!window.confirm("Delete " + ids.length + " application" + plural + "? This cannot be undone.")) return;

    try {
      await API.bulkDeleteRoles(ids);
    } catch (error) {
      return handleApiError(error);
    }
    // If the role on screen was among them, fall back to re-picking one.
    if (state.selectedRoleIds[state.activeRoleId]) state.activeRoleId = null;
    state.selectedRoleIds = {};
    toast("Deleted " + ids.length + " application" + plural + ".", "success");
    renderWorkspace(state.activeRoleId);
  }

  /** Persist a role's application status when its dropdown changes. */
  async function onStatusChange(roleId, newStatus, selectEl) {
    var id = String(roleId);
    try {
      var updated = await API.updateRoleStatus(id, newStatus);
      var role = findRole(id);
      if (role) role.application_status = updated.application_status;
      toast("Status set to “" + newStatus + "”.", "success");
    } catch (error) {
      handleApiError(error);
      // Roll the dropdown back to the last known value on failure.
      var current = findRole(id);
      if (selectEl && current) selectEl.value = current.application_status || "Not Applied";
    }
  }

  /**
   * Show only the roster items whose company or job title contains the current
   * filter text. Pure client-side DOM filtering - it toggles each item's display
   * in place (no re-render), and surfaces a "no matches" note when nothing fits.
   */
  function applyRosterFilter() {
    var query = (state.rosterFilter || "").trim().toLowerCase();
    var items = viewEl.querySelectorAll(".roster-item");
    var visible = 0;
    Array.prototype.forEach.call(items, function (item) {
      var hay = item.getAttribute("data-search") || "";
      var match = !query || hay.indexOf(query) !== -1;
      // Inline display beats the base `.roster-item { display: grid }` rule, so
      // the [hidden]-attribute gotcha (author rules win over it) does not bite.
      item.style.display = match ? "" : "none";
      if (match) visible += 1;
    });
    var note = viewEl.querySelector("#roster-no-match");
    if (note) {
      if (query && visible === 0) {
        note.textContent = "No applications match “" + state.rosterFilter.trim() + "”.";
        note.hidden = false;
      } else {
        note.hidden = true;
      }
    }
  }

  /** Markup for a single roster (pipeline) entry. */
  function rosterItemHtml(role, draft) {
    var id = String(role.id);
    var isActive = id === state.activeRoleId;
    var isSelected = !!state.selectedRoleIds[id];
    var draftStatus = draft ? draft.status : null;
    var appStatus = role.application_status || "Not Applied";
    // Lower-cased company + title, used by the live filter (applyRosterFilter).
    var haystack = ((role.company || "") + " " + (role.job_title || "")).toLowerCase();

    var options = APPLICATION_STATUSES.map(function (s) {
      return '<option value="' + esc(s) + '"' + (s === appStatus ? " selected" : "") + ">" + esc(s) + "</option>";
    }).join("");

    // Show the live generation pill while still working/failed; otherwise the date.
    var trailing = (draftStatus && draftStatus !== "completed")
      ? statusPill(draftStatus)
      : '<span class="ri-date">' + esc(formatDate(role.created_at)) + "</span>";

    return (
      '<div class="roster-item' + (isActive ? " is-active" : "") + (isSelected ? " is-selected" : "") + '"' +
        ' data-role-id="' + esc(id) + '" data-search="' + esc(haystack) + '">' +
        '<input type="checkbox" class="ri-check" aria-label="Select application"' + (isSelected ? " checked" : "") + " />" +
        '<div class="ri-body">' +
          '<button class="ri-main" type="button" data-role-id="' + esc(id) + '">' +
            '<span class="ri-company">' + esc(role.company) + "</span>" +
            '<span class="ri-title">' + esc(role.job_title) + "</span>" +
          "</button>" +
          '<div class="ri-foot">' +
            '<select class="ri-status" aria-label="Application status">' + options + "</select>" +
            trailing +
          "</div>" +
        "</div>" +
      "</div>"
    );
  }

  /**
   * Select a role: highlight it in the roster and (re)render the stage from the
   * cache. Begins polling if that role is still generating. No network refetch -
   * switching applications is instant.
   * @param {string|number} roleId
   */
  function selectRole(roleId) {
    stopPolling();
    state.activeRoleId = String(roleId);

    // Update roster highlight in place (no full re-render).
    Array.prototype.forEach.call(viewEl.querySelectorAll(".roster-item"), function (item) {
      var on = item.getAttribute("data-role-id") === state.activeRoleId;
      item.classList.toggle("is-active", on);
      item.setAttribute("aria-current", on ? "true" : "false");
    });

    renderStage();

    var draft = state.drafts[state.activeRoleId];
    if (draft && (draft.status === "pending" || draft.status === "processing")) {
      startPolling(state.activeRoleId);
    }
  }

  /** Render the stage for the active role: header + (tabs | loading | failure). */
  function renderStage() {
    var stageEl = viewEl.querySelector("#stage");
    if (!stageEl) return;

    var role = findRole(state.activeRoleId);
    if (!role) { renderStageEmpty(); return; }

    var draft = state.drafts[state.activeRoleId];
    var status = draft ? draft.status : "unknown";

    var head =
      '<div class="stage-head">' +
        "<div>" +
          '<p class="eyebrow">' + esc(role.company) + "</p>" +
          "<h1>" + esc(role.job_title) + "</h1>" +
          '<p class="stage-sub">Application kit · ' + esc(formatDate(role.created_at)) + "</p>" +
        "</div>" +
        '<div class="stage-head-actions">' +
          statusPill(status) +
          '<button class="btn btn-ghost stage-cal-btn" id="cal-followup" type="button">📅 Set 1-Week Follow-up</button>' +
        "</div>" +
      "</div>";

    var body;
    if (!draft) {
      body = '<div class="notice" style="border-color:var(--line);background:var(--paper-2)">No kit has been generated for this role yet.</div>';
    } else if (draft.status === "completed") {
      body = buildTabsAndPanes(draft, role);
    } else if (draft.status === "failed") {
      body = failureHtml(draft);
    } else {
      body = loadingHtml();
    }

    stageEl.innerHTML = head + body;

    // The follow-up calendar download works regardless of generation status.
    var calBtn = stageEl.querySelector("#cal-followup");
    if (calBtn) calBtn.addEventListener("click", function () { onCalendarFollowup(state.activeRoleId, calBtn); });

    // Tabs + per-artifact actions only exist once a kit is complete.
    if (draft && draft.status === "completed") {
      wireTabs(stageEl);
      wireCopyLetter(stageEl, draft);
      wireArtifactActions(stageEl, state.activeRoleId, draft);
    }
  }

  /** The "no applications" empty state, shown in the stage. */
  function renderStageEmpty() {
    var stageEl = viewEl.querySelector("#stage");
    if (!stageEl) return;
    stageEl.innerHTML =
      '<div class="empty">' +
        "<h2>Your desk is clear.</h2>" +
        "<p>Start your first application: upload a resume and paste the job description, and your co-pilot will assemble a tailored kit.</p>" +
        '<button class="btn btn-primary" id="empty-new">Start an application</button>' +
      "</div>";
    stageEl.querySelector("#empty-new").addEventListener("click", function () { navigate("new"); });
  }

  // ----------------------------------------------------------------------
  // The tabbed kit
  // ----------------------------------------------------------------------

  /** Build the horizontal tab bar + the five panes (one per artifact + salary). */
  function buildTabsAndPanes(draft, role) {
    var active = TAB_IDS.indexOf(state.activeTab) !== -1 ? state.activeTab : "fit";

    var tabBar =
      '<div class="tabs" role="tablist">' +
        TABS.map(function (tab) {
          var on = tab.id === active;
          return (
            '<button class="tab' + (on ? " is-active" : "") + '" role="tab"' +
              ' aria-selected="' + (on ? "true" : "false") + '" data-tab="' + tab.id + '">' +
              '<span class="tab-no">' + tab.no + "</span>" + esc(tab.label) +
            "</button>"
          );
        }).join("") +
      "</div>";

    var contentByTab = {
      fit: paneFit(draft.fit_analysis),
      resume: paneResume(draft.resume_rewrite),
      cover: paneCover(draft.cover_letter),
      interview: paneInterview(draft.interview_qa),
      salary: paneSalary(role)
    };

    var panes = TABS.map(function (tab) {
      var on = tab.id === active;
      return (
        '<div class="tab-pane' + (on ? " is-active" : "") + '" data-pane="' + tab.id + '" role="tabpanel">' +
          '<div class="pane-head"><span class="section-no">' + tab.no + "</span><h2>" + esc(tab.title) + "</h2></div>" +
          contentByTab[tab.id] +
        "</div>"
      );
    }).join("");

    return tabBar + panes;
  }

  /** Wire every tab button in the given scope to switch panes. */
  function wireTabs(scopeEl) {
    Array.prototype.forEach.call(scopeEl.querySelectorAll(".tab"), function (tab) {
      tab.addEventListener("click", function () {
        selectTab(scopeEl, tab.getAttribute("data-tab"));
      });
    });
  }

  /**
   * The core tab logic: add `is-active` to the clicked tab button and its
   * matching content pane, and remove it from all the others. Pure DOM - no
   * re-render, so scroll position and the rest of the page are untouched.
   */
  function selectTab(scopeEl, tabId) {
    state.activeTab = tabId;
    Array.prototype.forEach.call(scopeEl.querySelectorAll(".tab"), function (tab) {
      var on = tab.getAttribute("data-tab") === tabId;
      tab.classList.toggle("is-active", on);
      tab.setAttribute("aria-selected", on ? "true" : "false");
    });
    Array.prototype.forEach.call(scopeEl.querySelectorAll(".tab-pane"), function (pane) {
      pane.classList.toggle("is-active", pane.getAttribute("data-pane") === tabId);
    });
  }

  /** Wire the "copy cover letter" button if it is present. */
  function wireCopyLetter(scopeEl, draft) {
    var copyBtn = scopeEl.querySelector("#copy-letter");
    if (!copyBtn) return;
    copyBtn.addEventListener("click", function () {
      var letter = draft.cover_letter || "";
      if (navigator.clipboard) {
        navigator.clipboard.writeText(letter).then(function () { toast("Cover letter copied.", "success"); });
      }
    });
  }

  /** Wire the per-artifact actions in the active stage: Regenerate, Download,
   *  and the ATS scan / salary coach / voice practice buttons. */
  function wireArtifactActions(scopeEl, roleId, draft) {
    Array.prototype.forEach.call(scopeEl.querySelectorAll("[data-regen]"), function (btn) {
      btn.addEventListener("click", function () { onRegenerate(roleId, btn.getAttribute("data-regen")); });
    });
    Array.prototype.forEach.call(scopeEl.querySelectorAll("[data-export]"), function (btn) {
      btn.addEventListener("click", function () { onExport(roleId, btn.getAttribute("data-export"), btn); });
    });
    // ATS scan (resume pane).
    var atsBtn = scopeEl.querySelector("[data-ats]");
    if (atsBtn) atsBtn.addEventListener("click", function () { onAtsScan(roleId, atsBtn); });
    // Salary coach (salary pane).
    var salaryGo = scopeEl.querySelector("#salary-go");
    if (salaryGo) salaryGo.addEventListener("click", function () { onSalaryCoach(roleId, salaryGo); });
    // Voice practice (interview pane): one button per question.
    Array.prototype.forEach.call(scopeEl.querySelectorAll("[data-practice]"), function (btn) {
      var index = parseInt(btn.getAttribute("data-practice"), 10);
      var out = scopeEl.querySelector('[data-practice-out="' + index + '"]');
      btn.addEventListener("click", function () { startVoicePractice(roleId, draft, index, out, btn); });
    });
  }

  /** Re-run a single agent, then poll the draft until that artifact refreshes. */
  async function onRegenerate(roleId, artifact) {
    var id = String(roleId);
    try {
      await API.regenerateArtifact(id, artifact);
    } catch (error) {
      return handleApiError(error);
    }
    toast("Regenerating the " + (ARTIFACT_LABELS[artifact] || artifact) + "…", "");
    // Optimistically show the working state, then poll for the refreshed draft.
    var draft = state.drafts[id];
    if (draft) draft.status = "processing";
    if (state.activeRoleId === id) renderStage();
    renderRoster();
    startPolling(id);
  }

  /** Download an exported artifact (kind: "pdf" resume | "docx" cover letter). */
  async function onExport(roleId, kind, btn) {
    var id = String(roleId);
    var role = findRole(id);
    var safeCompany = (role && role.company ? role.company : "application")
      .replace(/[^A-Za-z0-9 _.-]+/g, "").trim() || "application";
    if (btn) btn.disabled = true;
    try {
      var blob, filename;
      if (kind === "docx") {
        blob = await API.downloadCoverLetterDocx(id);
        filename = "Cover Letter - " + safeCompany + ".docx";
      } else {
        blob = await API.downloadResumePdf(id);
        filename = "Resume - " + safeCompany + ".pdf";
      }
      triggerDownload(blob, filename);
      toast("Downloaded " + filename + ".", "success");
    } catch (error) {
      handleApiError(error);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  /** Save a Blob to disk via a temporary object-URL link. */
  function triggerDownload(blob, filename) {
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1500);
  }

  // ======================================================================
  // Extras: ATS scan, voice practice, salary coach, calendar follow-up
  // ======================================================================

  /** The "Run ATS Scan" button shown in the resume pane toolbar. */
  function atsButton() {
    return '<button class="btn btn-ghost pane-btn" type="button" data-ats="1"><span class="btn-ico">⚡</span> Run ATS Scan</button>';
  }

  /** Score the rewritten resume against the JD and render the result card. */
  async function onAtsScan(roleId, btn) {
    var out = viewEl.querySelector("#ats-result");
    if (!out) return;
    if (btn) btn.disabled = true;
    out.innerHTML = '<div class="ats-card is-loading"><span class="spinner"></span> Scanning keyword match…</div>';
    try {
      out.innerHTML = renderAtsCard(await API.atsScore(roleId));
    } catch (error) {
      out.innerHTML = "";
      handleApiError(error);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  /** A small helper: map a 0-100 score to a colour band class. */
  function scoreBand(score) {
    return score >= 75 ? "good" : (score >= 50 ? "mid" : "low");
  }

  /** A plain-language reading of an ATS score (label + one-line guidance), by band. */
  function atsScoreSummary(score) {
    if (score >= 75) return { label: "Strong match", detail: "Your résumé already mirrors most of the JD’s key terms — a real keyword screen would likely pass it through." };
    if (score >= 50) return { label: "Moderate match", detail: "Several important terms are thin or missing. Weave in the ones you can honestly support to clear more filters." };
    return { label: "Weak match", detail: "The résumé is missing many of the JD’s core keywords. Add the ones you genuinely have experience with before applying." };
  }

  function renderAtsCard(result) {
    var score = Math.max(0, Math.min(100, Math.round(Number(result.score) || 0)));
    var feedback = (result.feedback || []).map(function (f) { return "<li>" + esc(f) + "</li>"; }).join("");
    var summary = atsScoreSummary(score);
    return (
      '<div class="ats-card">' +
        '<div class="ats-head">' +
          '<div class="score-badge band-' + scoreBand(score) + '"><span class="score-badge-num">' + score + '</span><span class="score-badge-of">/100</span></div>' +
          "<div><h3>ATS keyword match</h3><p class=\"ats-sub\">How well the rewritten resume aligns with the JD’s keywords.</p></div>" +
        "</div>" +
        (feedback ? '<ul class="ats-feedback">' + feedback + "</ul>" : "") +
        '<div class="ats-about">' +
          '<p class="ats-detail"><strong>' + score + "/100 — " + esc(summary.label) + ".</strong> " + esc(summary.detail) + "</p>" +
          '<p class="ats-note">What this scan does: a second pass that reads your rewritten résumé the way an automated Applicant Tracking System would — pulling the job description’s key skills and tools and scoring how many <em>genuinely</em> appear. Hedged or “haven’t used” mentions don’t count toward the score. It’s a private check to tune your résumé; nothing here is sent to the employer.</p>' +
        "</div>" +
      "</div>"
    );
  }

  /** Capture a spoken answer via the Web Speech API, then grade it. */
  function startVoicePractice(roleId, draft, index, outEl, btn) {
    if (!outEl) return;
    var question = "";
    var sample = "";
    try {
      var q = draft.interview_qa.questions[index];
      question = q.question;
      sample = q.sample_answer || "";
    } catch (e) { /* no question found; grade with empty context */ }

    var SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) {
      outEl.innerHTML = '<p class="practice-note">Voice input isn’t supported in this browser. Try Chrome or Edge on desktop.</p>';
      return;
    }

    var recognition = new SpeechRec();
    recognition.lang = "en-US";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    var settled = false;
    var originalLabel = btn ? btn.innerHTML : "";
    function reset() { if (btn) { btn.disabled = false; btn.innerHTML = originalLabel || "🎤 Practice Answer"; } }
    if (btn) { btn.disabled = true; btn.innerHTML = "🎤 Listening…"; }
    outEl.innerHTML = '<p class="practice-note">Listening… speak your answer, then pause.</p>';

    function transcriptHtml(text) {
      return '<div class="practice-transcript"><span class="practice-tag">You said</span>' + esc(text) + "</div>";
    }

    recognition.onresult = async function (event) {
      settled = true;
      reset();
      var transcript = "";
      try { transcript = event.results[0][0].transcript; } catch (e) { transcript = ""; }
      if (!transcript) { outEl.innerHTML = '<p class="practice-note">Didn’t catch that — try again.</p>'; return; }
      outEl.innerHTML = transcriptHtml(transcript) + '<p class="practice-note"><span class="spinner"></span> Grading your answer…</p>';
      try {
        var grade = await API.gradeInterviewAnswer(roleId, { question: question, sample_answer: sample, user_answer: transcript });
        outEl.innerHTML = transcriptHtml(transcript) + renderGradeCard(grade);
      } catch (error) {
        outEl.innerHTML = transcriptHtml(transcript);
        handleApiError(error);
      }
    };
    recognition.onerror = function (event) {
      settled = true; reset();
      var msg = (event && event.error === "not-allowed") ? "Microphone permission denied." : "Voice capture failed — try again.";
      outEl.innerHTML = '<p class="practice-note">' + esc(msg) + "</p>";
    };
    recognition.onend = function () { if (!settled) reset(); };

    try {
      recognition.start();
    } catch (e) {
      reset();
      outEl.innerHTML = '<p class="practice-note">Could not start voice capture.</p>';
    }
  }

  function renderGradeCard(grade) {
    var score = Math.max(0, Math.min(100, Math.round(Number(grade.score) || 0)));
    function column(title, items, klass) {
      if (!items || !items.length) return "";
      return '<div class="grade-col ' + klass + '"><h4>' + title + "</h4><ul>" +
        items.map(function (i) { return "<li>" + esc(i) + "</li>"; }).join("") + "</ul></div>";
    }
    return (
      '<div class="grade-card">' +
        '<div class="grade-head">' +
          '<span class="score-badge band-' + scoreBand(score) + '"><span class="score-badge-num">' + score + "</span></span>" +
          (grade.assessment ? '<p class="grade-assess">' + esc(grade.assessment) + "</p>" : "") +
        "</div>" +
        '<div class="grade-cols">' +
          column("Strengths", grade.strengths, "grade-strengths") +
          column("Improve", grade.improvements, "grade-improve") +
        "</div>" +
      "</div>"
    );
  }

  /** Generate + render the two salary-negotiation scripts. */
  async function onSalaryCoach(roleId, btn) {
    var input = viewEl.querySelector("#salary-input");
    var out = viewEl.querySelector("#salary-result");
    if (!input || !out) return;
    var offered = input.value.trim();
    if (!offered) { out.innerHTML = '<p class="practice-note">Enter the offered base salary first.</p>'; return; }
    if (btn) btn.disabled = true;
    out.innerHTML = '<p class="practice-note"><span class="spinner"></span> Drafting your negotiation scripts…</p>';
    try {
      var result = await API.salaryCoach(roleId, offered);
      out.innerHTML = renderSalaryScripts(result.scripts || []);
    } catch (error) {
      out.innerHTML = "";
      handleApiError(error);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function renderSalaryScripts(scripts) {
    if (!scripts.length) return '<p class="practice-note">No scripts were generated.</p>';
    return '<div class="salary-scripts">' + scripts.map(function (s, i) {
      return (
        '<article class="salary-script">' +
          '<header><span class="salary-script-n">' + (i + 1) + "</span><h3>" + esc(s.title) + "</h3></header>" +
          "<p>" + esc(s.body) + "</p>" +
        "</article>"
      );
    }).join("") + "</div>";
  }

  /** Download a 1-week follow-up .ics for this role. */
  async function onCalendarFollowup(roleId, btn) {
    var role = findRole(roleId);
    var safeCompany = (role && role.company ? role.company : "application")
      .replace(/[^A-Za-z0-9 _.-]+/g, "").trim() || "application";
    if (btn) btn.disabled = true;
    try {
      var blob = await API.downloadFollowupIcs(roleId);
      triggerDownload(blob, "Follow up - " + safeCompany + ".ics");
      toast("Follow-up reminder downloaded — open it to add to your calendar.", "success");
    } catch (error) {
      handleApiError(error);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  /** A gentle placeholder for an artifact an agent did not produce. */
  function paneNote(text) {
    return '<p class="pane-note">' + esc(text) + "</p>";
  }

  /** A small toolbar (regenerate / download) shown at the top of an artifact pane. */
  function paneToolbar(buttonsHtml) {
    return '<div class="pane-tools">' + buttonsHtml + "</div>";
  }
  /** A "Regenerate" button for a single artifact ("resume" | "cover" | "interview"). */
  function regenButton(artifact) {
    return '<button class="btn btn-ghost pane-btn" type="button" data-regen="' + artifact + '">' +
      '<span class="btn-ico">↻</span> Regenerate</button>';
  }
  /** A download button (kind: "pdf" for the resume, "docx" for the cover letter). */
  function downloadButton(kind) {
    return '<button class="btn btn-ghost pane-btn" type="button" data-export="' + kind + '">' +
      '<span class="btn-ico">↓</span> Download .' + kind + "</button>";
  }

  /** Tab 01 - Fit analysis (score ring + met/missing/emphasize). */
  function paneFit(fit) {
    if (!fit) return paneNote("The fit analysis wasn’t generated for this application.");
    // Map the real fit_score (0-100) from the API onto BOTH the dial number and
    // the --val CSS variable that fills the green ring. Coerce + clamp + round so
    // any odd payload (string, out of range, null/blank) still renders sensibly.
    var rawScore = Number(fit.fit_score);
    var hasScore = fit.fit_score !== null && fit.fit_score !== undefined && fit.fit_score !== "" && !isNaN(rawScore);
    var score = hasScore ? Math.max(0, Math.min(100, Math.round(rawScore))) : null;
    var ring =
      '<div class="score-ring" style="--val:' + (score === null ? 0 : score) + '">' +
        '<div class="score-inner">' +
          '<div class="score-num">' + (score === null ? "—" : score) + "</div>" +
          '<div class="score-of">/ 100 FIT</div>' +
        "</div>" +
      "</div>";

    function column(klass, title, items) {
      var list = (items && items.length)
        ? "<ul>" + items.map(function (it) { return "<li>" + esc(it) + "</li>"; }).join("") + "</ul>"
        : '<p style="color:var(--ink-faint);font-size:0.9rem">None noted.</p>';
      return '<div class="fit-col ' + klass + '"><h3>' + title + "</h3>" + list + "</div>";
    }

    return (
      '<div class="card">' +
        '<div class="fit-top">' + ring +
          '<p class="fit-summary">' + esc(fit.overall_summary || "") + "</p>" +
        "</div>" +
        '<div class="fit-cols">' +
          column("fit-met", "Requirements met", fit.met_requirements) +
          column("fit-missing", "Gaps to address", fit.missing_requirements) +
          column("fit-emph", "Emphasize", fit.points_to_emphasize) +
        "</div>" +
      "</div>"
    );
  }

  /** Tab 02 - the Diff View: struck-out originals beside green rewrites. */
  function paneResume(rewrite) {
    if (!rewrite) return paneNote("No resume rewrite was generated for this application.");
    var bullets = rewrite.bullets || [];
    var summary = rewrite.summary_of_changes
      ? '<p class="diff-summary">' + esc(rewrite.summary_of_changes) + "</p>"
      : "";

    if (!bullets.length) {
      return paneToolbar(regenButton("resume")) + summary + '<div class="card">No bullet rewrites were produced.</div>';
    }

    var rows = bullets.map(function (bullet) {
      var section = bullet.section
        ? '<div class="diff-section">' + esc(bullet.section) + "</div>"
        : "";
      var rationale = bullet.rationale
        ? '<div class="diff-rationale"><b>Why:</b> ' + esc(bullet.rationale) + "</div>"
        : "";
      return (
        '<div class="diff-row">' +
          section +
          '<div class="diff-cell diff-old">' +
            '<span class="diff-tag">Original</span>' +
            '<p class="diff-text" data-mark="−">' + esc(bullet.original_bullet) + "</p>" +
          "</div>" +
          '<div class="diff-cell diff-new">' +
            '<span class="diff-tag">Rewritten</span>' +
            '<p class="diff-text" data-mark="+">' + esc(bullet.rewritten_bullet) + "</p>" +
          "</div>" +
          rationale +
        "</div>"
      );
    }).join("");

    return (
      paneToolbar(regenButton("resume") + downloadButton("pdf") + atsButton()) +
      summary + '<div class="diff-list">' + rows + "</div>" +
      '<div class="ats-result" id="ats-result"></div>'
    );
  }

  /** Tab 03 - the cover letter on a paper sheet. */
  function paneCover(letter) {
    if (!letter) return paneNote("No cover letter was generated for this application.");
    return (
      paneToolbar(regenButton("cover") + downloadButton("docx")) +
      '<article class="letter-sheet">' + esc(letter) + "</article>" +
      '<div class="letter-actions"><button class="btn btn-ghost" id="copy-letter">Copy to clipboard</button></div>'
    );
  }

  /** Tab 04 - interview questions as an accordion. */
  function paneInterview(qa) {
    var questions = qa && qa.questions ? qa.questions : [];
    if (!questions.length) return paneNote("No interview questions were generated for this application.");
    var items = questions.map(function (item, index) {
      var grounded = item.grounded_in
        ? '<p class="qa-grounded">Grounded in: ' + esc(item.grounded_in) + "</p>"
        : "";
      return (
        "<details class=\"qa\"" + (index === 0 ? " open" : "") + ">" +
          "<summary>" +
            '<span class="qa-n">Q' + (index + 1) + "</span>" +
            "<span>" + esc(item.question) + "</span>" +
            '<span class="qa-plus">+</span>' +
          "</summary>" +
          '<div class="qa-body">' +
            '<p class="qa-answer">' + esc(item.sample_answer) + "</p>" +
            grounded +
            '<div class="qa-practice-row"><button class="btn btn-ghost qa-practice-btn" type="button" data-practice="' + index + '">🎤 Practice Answer</button></div>' +
            '<div class="qa-practice-out" data-practice-out="' + index + '"></div>' +
          "</div>" +
        "</details>"
      );
    }).join("");
    return paneToolbar(regenButton("interview")) + '<div class="qa-list">' + items + "</div>";
  }

  /** Tab 05 - Salary negotiation coach (interactive; needs only the role). */
  function paneSalary(role) {
    var roleName = role ? (esc(role.job_title) + " at " + esc(role.company)) : "this role";
    return (
      '<div class="salary-coach">' +
        '<p class="salary-intro">Enter the base salary (in ₹) you were offered for <strong>' + roleName +
          "</strong>, and your coach will draft two negotiation scripts.</p>" +
        '<div class="salary-form">' +
          '<input class="input" id="salary-input" type="text" inputmode="numeric" placeholder="e.g. ₹12,00,000" aria-label="Offered base salary in rupees" />' +
          '<button class="btn btn-primary" id="salary-go" type="button">Coach me →</button>' +
        "</div>" +
        '<div class="salary-result" id="salary-result"></div>' +
      "</div>"
    );
  }

  /** The indeterminate "four agents at work" loading panel (stage body). */
  function loadingHtml() {
    return (
      '<div class="loading-wrap">' +
        "<h2>Marking up your application…</h2>" +
        "<p>Your co-pilot is working through four passes. This usually takes under a minute.</p>" +
        '<ol class="pipeline">' +
          PIPELINE_STAGES.map(function (stage) {
            return (
              "<li>" +
                '<span class="p-n">' + stage.n + "</span>" +
                '<span class="p-name">' + esc(stage.name) + "</span>" +
                '<span class="p-note">' + esc(stage.note) + "</span>" +
              "</li>"
            );
          }).join("") +
        "</ol>" +
      "</div>"
    );
  }

  /** The failure notice (stage body). */
  function failureHtml(draft) {
    return (
      '<div class="notice notice-fail">' +
        "<h2>Generation didn’t finish</h2>" +
        "<p>Your co-pilot hit a problem. The most common cause is a missing LLM API key on the server.</p>" +
        (draft.error_message ? "<p style=\"margin-top:0.8rem\"><code>" + esc(draft.error_message) + "</code></p>" : "") +
      "</div>"
    );
  }

  // ======================================================================
  // New application form
  // ======================================================================

  function renderNewApplication() {
    setView(
      '<div class="container">' +
        '<button class="back-link" id="back">← Back to the desk</button>' +
        '<div class="page-head"><div>' +
          '<p class="eyebrow">New application</p>' +
          "<h1>Brief your co-pilot</h1>" +
        "</div></div>" +
        '<form id="new-form" class="stagger" style="max-width:720px">' +
          '<div class="field"><label for="f-job">Job title</label>' +
            '<input class="input" id="f-job" type="text" required maxlength="255" placeholder="Senior Backend Engineer" /></div>' +
          '<div class="field"><label for="f-company">Company</label>' +
            '<input class="input" id="f-company" type="text" required maxlength="255" placeholder="Acme Corp" /></div>' +
          '<div class="field"><label for="f-jd">Job description</label>' +
            '<textarea class="textarea" id="f-jd" placeholder="Paste the full job description here…" rows="8"></textarea>' +
            '<p class="field-hint">Paste the JD text above, <em>or</em> give a link below and we’ll fetch it for you.</p></div>' +
          '<div class="field"><label for="f-jd-url">Job description URL <span style="text-transform:none;letter-spacing:0">(optional)</span></label>' +
            '<input class="input" id="f-jd-url" type="url" placeholder="https://… careers page or job posting" /></div>' +
          '<div class="field"><label>Resume (PDF)</label>' +
            '<label class="dropzone" id="dropzone">' +
              '<input type="file" id="f-file" accept="application/pdf,.pdf" />' +
              '<span class="dz-icon" id="dz-icon">↑</span>' +
              '<span class="dz-text" id="dz-text"><strong>Drop your PDF here</strong><span>or click to browse · max 5 MB</span></span>' +
            "</label>" +
          "</div>" +
          '<div class="field-error" id="new-error" hidden></div>' +
          '<button class="btn btn-primary" id="new-submit" type="submit" style="margin-top:0.5rem">Generate my kit →</button>' +
        "</form>" +
      "</div>"
    );

    viewEl.querySelector("#back").addEventListener("click", function () { navigate("home"); });
    wireDropzone();
    viewEl.querySelector("#new-form").addEventListener("submit", onNewSubmit);
  }

  /** Wire up the custom PDF dropzone (click-to-browse + drag-and-drop). */
  function wireDropzone() {
    var dropzone = viewEl.querySelector("#dropzone");
    var fileInput = viewEl.querySelector("#f-file");
    var textEl = viewEl.querySelector("#dz-text");
    var iconEl = viewEl.querySelector("#dz-icon");

    function showSelectedFile(file) {
      if (!file) return;
      dropzone.classList.add("has-file");
      iconEl.textContent = "✓";
      var sizeKb = Math.round(file.size / 1024);
      textEl.innerHTML = "<strong>" + esc(file.name) + "</strong><span>" + sizeKb + " KB · ready</span>";
    }

    fileInput.addEventListener("change", function () { showSelectedFile(fileInput.files[0]); });

    ["dragenter", "dragover"].forEach(function (evt) {
      dropzone.addEventListener(evt, function (e) { e.preventDefault(); dropzone.classList.add("is-dragover"); });
    });
    ["dragleave", "drop"].forEach(function (evt) {
      dropzone.addEventListener(evt, function (e) { e.preventDefault(); dropzone.classList.remove("is-dragover"); });
    });
    dropzone.addEventListener("drop", function (e) {
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
        fileInput.files = e.dataTransfer.files; // assign dropped file to the input
        showSelectedFile(fileInput.files[0]);
      }
    });
  }

  async function onNewSubmit(event) {
    event.preventDefault();
    var jobTitle = viewEl.querySelector("#f-job").value.trim();
    var company = viewEl.querySelector("#f-company").value.trim();
    var jdText = viewEl.querySelector("#f-jd").value.trim();
    var jdUrl = viewEl.querySelector("#f-jd-url").value.trim();
    var file = viewEl.querySelector("#f-file").files[0];
    var errorEl = viewEl.querySelector("#new-error");
    var submitBtn = viewEl.querySelector("#new-submit");

    errorEl.hidden = true;
    if (!jobTitle || !company) {
      errorEl.textContent = "Job title and company are required.";
      errorEl.hidden = false;
      return;
    }
    if (!jdText && !jdUrl) {
      errorEl.textContent = "Provide the job description as text, or paste a link to it.";
      errorEl.hidden = false;
      return;
    }
    if (!file) {
      errorEl.textContent = "Please attach your resume as a PDF.";
      errorEl.hidden = false;
      return;
    }
    if (file.type && file.type !== "application/pdf" && !/\.pdf$/i.test(file.name)) {
      errorEl.textContent = "The resume must be a PDF file.";
      errorEl.hidden = false;
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      errorEl.textContent = "That PDF is larger than 5 MB.";
      errorEl.hidden = false;
      return;
    }

    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner"></span>Uploading…';
    try {
      var result = await API.createRole({ jobTitle: jobTitle, company: company, jdText: jdText, jdUrl: jdUrl, file: file });
      // Land on the brand-new role in the command center; it will poll itself.
      state.activeTab = "fit";
      toast("Your co-pilot is on it.", "success");
      navigate("workspace", result.role.id);
    } catch (error) {
      submitBtn.disabled = false;
      submitBtn.textContent = "Generate my kit →";
      if (error && error.status === 401) return handleApiError(error);
      errorEl.textContent = (error && error.message) || "Could not start generation.";
      errorEl.hidden = false;
    }
  }

  // ======================================================================
  // Polling
  // ======================================================================

  /**
   * Poll one role's latest draft until it is completed or failed, updating the
   * cache, the roster pill, and (if it is still the role on screen) the stage.
   * @param {string|number} roleId  The role being generated.
   */
  function startPolling(roleId) {
    stopPolling();
    var id = String(roleId);
    var attempts = 0;
    state.pollTimer = setInterval(async function () {
      attempts += 1;
      if (attempts > POLL_MAX_ATTEMPTS) {
        stopPolling();
        if (state.activeRoleId === id) {
          var stageEl = viewEl.querySelector("#stage");
          var headEl = stageEl ? stageEl.querySelector(".stage-head") : null;
          if (stageEl) {
            stageEl.innerHTML =
              (headEl ? headEl.outerHTML : "") +
              '<div class="notice" style="border-color:var(--gold);background:var(--gold-tint)">' +
                '<h2 style="font-size:1.3rem;color:var(--gold)">Still working…</h2>' +
                "<p>This is taking longer than expected. Refresh in a moment to check again.</p></div>";
          }
        }
        return;
      }

      var draft;
      try {
        draft = await API.getRoleDraft(id);
      } catch (error) {
        stopPolling();
        return handleApiError(error);
      }
      if (!draft) return;

      var previous = state.drafts[id];
      var statusChanged = !previous || previous.status !== draft.status;
      state.drafts[id] = draft;

      var finished = draft.status !== "pending" && draft.status !== "processing";
      if (finished) {
        stopPolling();
        renderRoster();                          // refresh the pill in the pipeline
        if (state.activeRoleId === id) {
          renderStage();                         // swap loading -> kit (or failure)
        }
      } else if (statusChanged) {
        renderRoster();                          // e.g. pending -> processing
      }
    }, POLL_INTERVAL_MS);
  }

  function stopPolling() {
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  }

  // ======================================================================
  // Boot
  // ======================================================================

  async function boot() {
    // Always open on the public landing page. If a saved session exists, validate
    // it first so the landing can greet a returning user and offer a one-click
    // way into the app; an invalid token is simply discarded.
    if (API.isAuthenticated()) {
      setView('<div class="center-screen"><span class="spinner"></span></div>');
      try {
        state.user = await API.getCurrentUser();
      } catch (error) {
        API.logout();
      }
    }
    navigate("landing");
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
