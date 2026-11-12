# Handoff: demo video and submission (written Nov 12, 2026, 20:42 IST)

You are making the demo video for **Collabio** (PayPal AI Hackathon), then helping the user upload it,
make the repo public and submit on Devpost. The product is **built, deployed and tested**: do not
change product code unless something on camera is broken.

## 0. Time (read first)
- **Hard deadline: Nov 13, 01:30 IST** (Nov 12, 12:00 PM PST). Submissions lock; after it, touch
  nothing until Dec 21 (no commits, no README edits, no video swap).
- At hand-off it is ~20:45 IST, so **about 4 h 45 min are left**. Suggested budget:
  - recording: ~45 min;
  - build and render: ~90 min;
  - critique and fixes: ~30 min;
  - YouTube upload and processing: ~30 min, and start it as early as possible because processing can take hours;
  - repo public and Devpost: ~30 min.
- **If time runs short, cut scope, not quality.** In this order:
  1. drop the generated-people shots;
  2. drop the dashboard agent beat;
  3. keep the fund → prove → paid core.

  A clean 2:00 film beats an unfinished 2:45 one.

## 1. Read these, in order
1. This file.
2. **The video script v2** (the plan to execute): `D:\Github\All-Hackathons\Paypal-oct2026\submission\video-script.md`.
   It already applies the launch playbook. Its sections cover the brief, the story, the three claims, the shot list with
   P/H/G tags and voiceover, the budgets, the story checks, the people plan, a **money check** and the recording list.
3. **Hackathon rules**: `D:\Github\All-Hackathons\Paypal-oct2026\RULES.md` (section 4, item 6, and section 5),
   `GOTCHAS.md` (items 7, 8, 10, 11, 12, 13) and `DEADLINE_AND_CHECKLIST.md` (the submission checklist and the
   "Video recipe").
4. **Motion Studio skill** (load it with the Skill tool: `anthropic-skills:motion-studio`). Use the latest synced version.
   It was updated Nov 12; the launch-film section in SKILL.md (step 6, "Launch and product films") is the
   playbook the script follows. Also read its `references/directing.md` (anti-generic list) and
   `references/critique.md` (rubric).
5. Optional, for recording: the **animate-video** skill's demo mode (`animate-video`, `references/mode-demo.md`).
   It drives the real app with Playwright and records exact events. A draft demo script for it already exists at
   `D:\Github\Collabio.animate\demo-paypal-money\02_script.json` (validated; it predates script v2 and the UI
   renames below, so update the selectors and labels before you use it).
6. The Devpost text draft: `D:\Github\All-Hackathons\Paypal-oct2026\submission\devpost.md`.
7. Background only if needed: the overnight log, `D:\Github\Collabio\docs\superpowers\notes\overnight-log.md`, and
   the ledger at `D:\Github\Collabio\.superpowers\sdd\2026-11-11-collabio-m4-paypal-money\progress.md`.

## 2. Hackathon video rules (must all hold)
From RULES.md, GOTCHAS.md and the organizers' updates:
- [ ] **Under 3:00.** Judges need not watch past 3:00. Target 2:30–2:45.
- [ ] **Public on YouTube** (Public, not Unlisted), and the link goes on the Devpost form.
- [ ] **Shows the real working project** on its target device (the browser), **end to end**. No mockups.
- [ ] **No third-party trademarks**, and the organizer says even plain-text product or brand names count:
  - no social-platform names or logos anywhere. Say "post", "short video", "analytics screenshot";
  - no real products or brands. The demo uses fictional ones: Lumen Audio, Lumen Pods, Priya Raman, Arjun Mehta;
  - **allowed and wanted:** **PayPal** (the sponsor; its sandbox checkout page appears on screen) and the AI model,
    **Claude**. GOTCHAS item 10: "Name PayPal and the AI model explicitly … in the video, and show both working
    on screen";
  - sponsor tools named once, briefly, at the end: AG Grid (AG Studio) and Render. Show no third-party logos
    except PayPal's own checkout page;
  - **don't show** Gemini or ElevenLabs names, the user's browser chrome (tabs, bookmarks, extensions, other sites) or
    the OS taskbar. Record in a clean Playwright browser with no chrome, or crop to the page.
- [ ] **No copyrighted music.** Synthesize the bed (Motion Studio `synth.py`) or use none. **An AI voiceover is allowed.**
- [ ] **No secrets on screen:** API keys, `.env` files, the PayPal buyer password being typed (mask that frame or
  cut it), terminal output with keys. The sandbox buyer email is fine; the README publishes it.
- [ ] In English.
- [ ] The **presentation** criterion: shows it working end to end; says what problem, for whom, and why it matters; easy
  to follow. Organizer tips: open with the problem and who it is for (first 15–20 s); show PayPal and AI working end to
  end with the AI taking the action; cut loading screens; close with impact and novelty.

## 3. The story and playbook rules (from Motion Studio's launch section; the script already follows them)
- **One idea:** *a creator deal that pays itself, safely: an AI checks the post, and code decides the money.*
- **Spine:**
  - **Hook**: a concrete scene, with a product cue within 5 s.
  - **Problem**: one example with real numbers, ending on a one-line diagnosis ("The payout is the bottleneck.").
  - **Reveal**: the name, "so that…", then "Let's see it."
  - **Three chapters**, each going situation → friction → product moment → result, with one peak:
    1. Fund once;
    2. **Prove it and get paid** (the peak);
    3. Ask the dashboard.
  - **Proof and trust**: "Would you let an AI move money?" Then the code computes the amount, the approval card, a
    **real refusal**, the refund.
  - **Close**: the payoff, a tagline that echoes the opening, the name, one call to action (URL) on screen and spoken,
    and sponsors last and short.
- **At most 3 headline claims** (Shu & Carlson):
  - every dollar is a real PayPal transaction (funding, payouts, refunds);
  - the AI never chooses the amount;
  - 32 of 292 founders interviewed pay creators, all by hand.
- **Screen time:**
  - real product (P) ≥ 70% for a competition entry (the plan has 79%);
  - people (H) 10–20%;
  - standalone graphics (G) 15–25%, and never more than ~6 s of G in a row except the end card.
- **One recurring character:** Priya. Narrate in the **first person** ("I'm the brand… now I'm Priya").
- **The film must read with sound off:** short labels next to what they name, highlight what is clicked, chapter pills.
- **Anti-generic** (directing.md):
  - no centred title on a gradient, no fade-everything, no slow zoom on a still;
  - no fake HUD or corner labels, no default glow or glassmorphism, no particle bursts;
  - use masks and wipes, contrast in pace, and holds long enough to read.
- **Critique loop:** at least 3 rounds, scoring hook, readability, motion, variety, brand, sound sync and **story**
  (gap by 3 s, product cue by 5 s, reveal with "so that", four beats per chapter, ≤3 claims, a CTA, readable sound-off,
  P/H/G budgets, credits within plan). Fix the three worst each round, until all scores are 8+.

## 4. Decisions still open (ask the user at the start, in one AskUserQuestion)
1. **Opening line:** the default is hook 1a–1c in the script (Priya's video just went live, and she gets paid before she's
   put the camera away). Alternatives: the founder statistic, or the question hook.
2. **Generated people** (H shots 1a, 2a, 8a): Google Flow, free tier, **49 of 50 daily credits** (Omni 1.2 Flash for
   Priya ×2, Veo 3.1 Lite for the brand manager). The user signs in to Google themselves. Or **product-only** (faster). The
   skill requires asking before generating; with time this short, product-only is the safe default.
3. **On-camera actions:** clicking Fund, Submit, Approve and Close moves **sandbox money only**, plus a few Claude calls.
   The animate-video demo mode bans clicking pay/submit unless the user agrees; get a clear yes.
4. **Theme:** record everything in **one** theme. Dark mode is verified readable, including the AG Studio dashboard;
   light is the app default. Recommendation: dark, consistently.

## 5. The live app and the exact demo state
- **Live site:** https://collabio-web.onrender.com (API: https://collabio-api.onrender.com, health
  `/api/v1/health`). Render, Singapore. Branch `hackathon/paypal-money`, HEAD `e345cfb`.
- **Personas** (no sign-up): the landing page's **"Enter as Lumen Audio (brand)"** and **"Enter as Priya (creator)"**, or
  `/api/demo-login?as=brand|creator`. Switch from the **Persona** item in the left rail. **Reset demo** is in that menu too.
- **Navigation after today's renames:**
  - brand rail: **Discover → Outreach → Booked → Money** (Outreach was "Board", Booked was "Deals");
  - creator rail: **Packages → Offers → Booked**;
  - a "you are here" strip with a one-line hint sits on top of every page.
- **Seeded demo** (only these four deals exist):

| Deal | Creator | State | Use in the film |
|---|---|---|---|
| Lumen Pods launch | Priya | booked, unfunded, 2 × $400 | Chapters 1 and 2: the live money path |
| Studio Monitors | Priya | funded; video 1 paid; **$1,400 payout awaiting approval** | Trust beat: approve, then close and refund |
| Soundbar review | Arjun | funded; video 1 paid (1.5M views) | Dashboard comparison |
| Desk Speaker | Arjun | completed and refunded | Dashboard history |

- **Money check** (so the peak auto-pays):
  - The seed's auto-approve limit is **$500**.
  - In chapter 1 the brand saves the bonus `$2 per 1K views after 200K, up to $500 per video` (the funding total becomes
    **$1,800**) and raises the limit to **$1,000** on camera ("Auto-approve payouts up to"; the hint says "Set $0 to
    review every payout yourself").
  - Priya's proof: **312,000 views**, so the bonus is $224 and the owed amount **$624**, which is under $1,000 and
    pays itself.
  - Studio Monitors' $1,400 is still above $1,000, so its approval card holds.
- **Priya's proof input** (it must satisfy the Lumen Pods brief or Claude asks for changes):
  - link: any `https://example.com/p/...`;
  - claimed views: `312000`;
  - sample screenshot: **"312K views"**;
  - caption: `Two weeks with Lumen Pods: the 30-hour battery is real and the charging case fits any pocket. #ad`.

  Verdict to payout takes about 15–40 s, and a PayPal sandbox payout can stay "Pending" for a while. Cut or fast-forward it.
- **The real refusal** for the trust beat: submit a caption about the wrong product (e.g. Lumen Pods text on the Studio
  Monitors deal's video, or any off-brief caption). Claude sets "Changes requested" with the reason, as seen in testing.
  Studio Monitors video 1 is already paid, so this resubmission works there.
- **Dashboard agent** (Money → Edit dashboard → the "Ask the AI Assistant…" box). Try "Which creator gives me the
  cheapest 1,000 views? Add a chart." Arjun ≈ $0.94/1K vs Priya ≈ $1.35/1K from the seed. Each prompt makes ~5–15
  Claude calls; the caps are 80 messages and 800 calls a day.
- **New today, worth showing:**
  - a **PayPal activity** table at the bottom of Money (every movement with its PayPal ID);
  - "Bonus paid" KPI;
  - the bonus editor's one-click examples, and "Claude needs a change" when a bonus is unsupported (only per-video,
    view-based bonuses are supported).
- **Before each recording take, reset the demo:**
  - Reset demo in the persona menu (limited to once a minute), **or** from `D:\Github\Collabio\backend`:
    `uv run python -m scripts.clean_demo --apply` then `uv run python -m scripts.seed_money`;
  - clear the daily caps with a one-off `delete from public.usage_counters` (see the overnight log; it uses
    `get_settings().supabase_db_url`, so never print it).
- **PayPal checkout:** the **user types the sandbox buyer login themselves.** It is in the landing page's **Judge guide**,
  the README, and `frontend/.env.local` (`NEXT_PUBLIC_JUDGE_BUYER_*`). **Never type a password through any tool.**
  Record with a browser the user can type into (headed Playwright with `recordVideo`, or the user records the checkout
  segment), and mask or cut the password frame.

## 6. How to build it (recommended path)
- **Motion Studio, route A** (seek(t) HTML, 1920×1080, 60 fps). Steps:
  1. `bash <skill>/scripts/new_project.sh D:\Github\All-Hackathons\Paypal-oct2026\video --route a`, then follow the
     skill's pipeline;
  2. write `docs/brief.md` and `docs/story.md` from script v2 section 1–2, and `docs/shotlist.md` from its table;
  3. **Recordings** become video assets (extract frames at the film fps so `seek` stays pure); overlay spotlights,
     labels, chapter pills and the elapsed-seconds counter in code;
  4. **Voiceover:** the animate-video skill's Kokoro (local, free; voice `af_heart`, about 150 wpm). Its environment
     is `C:\Users\natar\.claude\skills\animate-video\.venv`; `narrate.py script.txt out.mp4 --speaker af_heart --speed 0.92`
     makes a voice track and prints its duration and wpm. Align the shot timings to the real VO lengths;
  5. **Music:** `tools/beats.py --bpm <n> --duration <s>`, then `tools/synth.py cues.json`. Keep it quiet under the voice;
  6. **Mix:** `tools/finish.sh out/video.mp4 audio/score.wav out/final.mp4` (about −14 LUFS);
  7. review with `tools/review.mjs sheet|phone|beats|strip|audio|hash`, at least 3 rounds; then `poster`.
- **Downloads** go under `D:\claude-global` (C: is nearly full; see `C:\Users\natar\.claude\CLAUDE.md`). Video work
  folders live on D:.
- Look at the real frames before claiming anything about the film.

## 7. After the video (in this order)
1. **YouTube:** the user uploads `final.mp4` to the channel **@NattyNeuron** as **Public**.
   - Title: *"Collabio: creator deals that pay themselves (PayPal + Claude)"*.
   - Description: the one-liner, the live URL, the repo URL, "PayPal sandbox; all names fictional",
     "Built with PayPal, Claude, AG Grid, Render".
   - Upload as early as possible: processing can take hours.
2. **Merge and repo public:**
   - ask the user whether to merge `hackathon/paypal-money` into `main` (they wanted a separate branch, merged or swapped
     at the end). Render deploys from `hackathon/paypal-money`, so merging does not affect the live site;
   - before making the repo public, run the history secret scan:
     `C:\Python312\python.exe -I D:\Github\Collabio\.superpowers\secret_scan.py D:\Github\Collabio HEAD D:\Github\All-Hackathons\Paypal-oct2026\.env` (run from `D:\Github\Collabio`; git-ignored copy).
     Known non-secret hits:
     - model names;
     - a regex;
     - fictional demo emails;
     - the sandbox buyer email (intentionally public);
     - a README path held in `ELEVENLABS_WEBHOOK_SECRET`.

     If that file is gone, rewrite it: compare every `.env` value against `git log -p --all` and print names only;
   - the user makes `Natarajan-33/Collabio` public (GitHub → Settings → Danger zone). The MIT LICENSE is at the root
     (it shows in About).
3. **README:** add the YouTube link at the top. Confirm the hosted URL and the judge guide.
4. **Devpost** (draft at `submission/devpost.md`):
   - paste the YouTube, live-site and repo links;
   - Built With: PayPal, Claude/Anthropic, AG Grid, Render, APIMatic, Next.js, FastAPI, Supabase;
   - Tools section: Claude Sonnet (settlement agent with vision, dashboard agent), Claude Haiku (terms parser), and how
     each is used;
   - **select the sponsor tools** (AG Grid, Render, APIMatic);
   - testing instructions with the sandbox buyer login;
   - mention the honest limit: fake screenshots under the brand's limit could still be paid. Mitigations: confidence,
     the 5% claim check, the limit, human approval, $0 = review every payout. Platform analytics APIs are future work;
   - click **Submit**, not Save draft, by 01:30 IST at the latest (aim earlier).
5. **Verify from an incognito window:** the repo URL, the video URL and the live site. Then **touch nothing until Dec 21.**

## 8. Gotchas learned today (don't relearn them)
- **Shared database.** Local and live share one Supabase project. Never run the local backend with workers on; use
  `WORKERS_ENABLED=0`. Tests also write to the demo brand, so reseed after any test run.
- **Render deploys:** every push to `hackathon/paypal-money` auto-deploys, and a service only rebuilds when files in its
  folder change. Settings: from `backend/`, `uv run python -m scripts.render_env status|push [--deploy]|set KEY=VAL
  [--service ...] [--deploy]` (prints names only; needs `RENDER_API_KEY` in `backend/.env`, which is set).
- **When committing,** gate on the real test result (`if ! grep -q FAIL log; then commit`), never on a `grep` that always
  succeeds. Frontend tests: `cd frontend && npx vitest run` (951 pass). One flaky test, `offer-desk … accept intent`,
  passes when rerun.
- **Demo caps** reset at UTC midnight (05:30 IST). If a take hits "demo limit", clear `usage_counters`.
- **The secret scan** lives at `D:\Github\Collabio\.superpowers\secret_scan.py` (git-ignored; `.superpowers/` is wiped by `git clean -fdx`).
- **The Render Workflows service** is optional and not deployed. The README says settlement runs in-process unless
  `RENDER_WORKFLOWS_ENABLED=1`, so don't claim it in the video.
