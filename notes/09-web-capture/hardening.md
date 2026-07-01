# Web capture hardening — login walls + consent overlays

## The two failure modes (seen in real captures)
1. **Login walls / social networks.** A web beat lands on facebook.com (or IG/X/LinkedIn)
   and we capture the "See more on Facebook" login modal, not the content behind it.
2. **Cookie-consent overlays.** A real article (e.g. Nature/Springer) is buried under a
   "Your privacy, your choice — Accept all cookies / Reject optional" banner.

Both produce a useless clip. Neither is a render bug; it's the sourcer choosing/shooting
the wrong surface.

## What already exists (the seam to extend)
`webcapture_worker.py` already detects bot-block pages via a `BLOCKS` keyword list and
`sys.exit(2)`; `sourcing.py` catches that as `SourcingError` and moves to the NEXT Serper
result. Every layer below rides that same detect-then-skip / clean-before-shoot pattern.

## Plan — four layers, most-deterministic first
Guiding rule (matches the tooling philosophy + the "fake determinism" note): **determinism
absorbs entropy; the model JUDGES, it doesn't CLICK.** Clicking a known consent button by
its stable selector is an EXACT lookup (deterministic). Deciding "is this frame actually
content?" is judgment (VLM). So we do NOT put a subagent in charge of clicking cookie
buttons — that's slow, costs a call per capture, and is the exact trap to avoid.

### Layer 1 — Search-time domain blacklist (deterministic; sourcing.py / serper)
Never pick a URL from a login-gated or hard-paywalled domain. Filter Serper results by a
curated blacklist BEFORE capture. This alone kills the Facebook case.
- Seed set (config-driven): facebook.com, instagram.com, x.com/twitter.com, linkedin.com,
  tiktok.com, pinterest.*, quora.com, reddit.com, and hard paywalls wsj.com, ft.com,
  nytimes.com, bloomberg.com, medium.com.
- Belt-and-suspenders: also append `-site:` operators to the query, but result-filtering
  is the reliable seam.
- ~20 min. Biggest single win.

### Layer 2 — Pre-shot page cleanup (deterministic; webcapture_worker)
After load, before scrolling: run a consent-dismiss pass. Click the first matching known
CMP button — the frameworks are standardized enough that ~15 selectors cover most of the
web. Prefer REJECT/optional-off where present (cleaner page), else ACCEPT to clear it.
- OneTrust `#onetrust-accept-btn-handler` / `#onetrust-reject-all-handler`
- Cookiebot `#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll` / `...ButtonDecline`
- Didomi `#didomi-notice-agree-button`; Quantcast `.qc-cmp2-summary-buttons button[mode=primary]`
- Usercentrics / TrustArc / Osano / CookieYes / Sourcepoint (iframe-rendered)
- Springer/Nature custom (the shot-2 case): their `button[data-cc-action=...]`
- Generic text scan of button/[role=button]/a for /^(accept all|reject all|reject optional|
  i agree|allow all|got it|accept cookies)$/i
- Must search `page.frames` (many CMPs render inside an iframe). Also a light Escape /
  `[aria-label=close]` pass for generic modals.
- ~1–2 hr. Kills the cookie banners.

### Layer 3 — Bad-state detection at shoot time (deterministic; mirrors BLOCKS)
- **Login wall:** a visible modal containing `input[type=password]`, or body text matching
  "log in to continue / see more on <site> / sign up to see / create new account" while the
  content is dimmed → `exit(3)` (LOGIN_WALL) → sourcing skips to next URL.
- **Consent still present** after Layer 2 → `exit(4)` (CONSENT_STUCK) → skip.
- Keep existing bot-block `exit(2)`. sourcing.py already loops to the next result on
  SourcingError; just add the new reasons.
- ~30 min. Cheap safety net.

### Layer 4 — VLM backstop (reuse verify_fit; extend the prompt)
We already sample 3 frames and score them vs the shot_brief. Extend the verifier to
hard-fail (fit≈0) when a frame is predominantly a login screen, cookie/consent banner,
paywall, error page, or browser chrome rather than the described content. Costs nothing
extra (already running); catches whatever slips past 1–3.
- ~10 min prompt change.

## Sequencing recommendation
Layer 1 → 2 → 3 → 4. Layer 1 is the cheap high-value win (Facebook gone); Layer 2 is the
real work (cookie banners); 3 and 4 are cheap belt-and-suspenders.

## Open / later (roadmap, not now)
- Reddit/X can be legit "evidence" (a real post). Instead of hard-blacklisting, route
  through an unauth mirror (nitter / old.reddit / teddit) or an embed. 
- AMP/cache (existing roadmap note) complements Layer 1 for hard paywalls: rewrite to
  `/amp/` or archive.today before giving up.
