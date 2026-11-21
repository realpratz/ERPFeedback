#!/usr/bin/env python3
"""
Auto-fill the BITS ERP "Student Feedback" (Overall Sem Feedback) forms,
then press "Generate Code" so you can view your marks.

Usage:
    python fill_feedback.py --dry-run   # fill the first form, screenshot, DON'T save
    python fill_feedback.py             # fill + save every form, then generate code
    python fill_feedback.py --headed    # same, but show the browser window

Settings are read from environment variables or a .env file next to this
script (see .env.example). The Google session is kept in .browser-profile/,
so 2-step verification is only needed the first time.
"""
import argparse
import os
import re
import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
PROFILE = HERE / ".browser-profile"
SHOTS = HERE / "screenshots"
LIST_URL = ("https://sis.erp.bits-pilani.ac.in/psc/sisprd/EMPLOYEE/SA/c/"
            "BITS_CUSTOM_SS_MENU.Z_STDFEED_SRCH_CM.GBL")

# ---- answers -------------------------------------------------------------
# For each multiple-choice question, the first label in this list that the
# question offers is picked. If none match, the first (top) option is picked.
PREFERRED = ["strongly agree", "> 80%", ">80%", "excellent", "very good", "always", "agree"]
COMMENT_GOOD = ("Concepts were explained clearly and the course was well structured. "
                "The instructor was approachable and helpful.")
COMMENT_IMPROVE = ("Nothing major. A few more solved examples and practice problems "
                   "would be helpful.")
# --------------------------------------------------------------------------

CHECKBOX_GRID = 'table[id^="Z_STDFED_OPN_VW$scroll$"]'
TEXTAREA = 'textarea[id^="Z_STDFB_O_REPLY_DESCRLONG$"]'
INSTR_PAGER = '[id="$ICField100$hpage$0"]'


def log(*a, **kw):
    print(*a, flush=True, **kw)


def load_env():
    """Values from .env, overridden by real environment variables."""
    env = {}
    f = HERE / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("ERP_EMAIL", "ERP_PASSWORD", "CHROME_PATH"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def find_browser(env):
    """Path to an installed Chrome/Chromium, or None to use Playwright's bundled one."""
    if env.get("CHROME_PATH"):
        return env["CHROME_PATH"]
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        if shutil.which(name):
            return shutil.which(name)
    for path in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                 "/Applications/Chromium.app/Contents/MacOS/Chromium",
                 r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                 r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"):
        if os.path.exists(path):
            return path
    return None


def headless_user_agent(p, exe):
    """A normal desktop Chrome UA (headless Chrome says 'HeadlessChrome', which Google dislikes)."""
    b = p.chromium.launch(executable_path=exe, headless=True)
    major = b.version.split(".")[0]
    b.close()
    plat = {"win32": "Windows NT 10.0; Win64; x64",
            "darwin": "Macintosh; Intel Mac OS X 10_15_7"}.get(sys.platform, "X11; Linux x86_64")
    return (f"Mozilla/5.0 ({plat}) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{major}.0.0.0 Safari/537.36")


def ps_wait(page, timeout=60000):
    """Wait for a PeopleSoft server round-trip to finish."""
    page.wait_for_timeout(250)
    page.wait_for_function(
        """() => { const w = document.getElementById('WAIT_win0');
                   return !w || w.style.visibility !== 'visible'; }""",
        timeout=timeout)
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass
    page.wait_for_timeout(150)


def read_ps_message(page):
    """Return (and dismiss) any PeopleSoft modal message currently shown."""
    msg = page.evaluate("""() => {
        const sels = ['#alertmsg', '[id^="ptModContent_"]', '.PSMODALCONTENT', '#ptpopupmsgtext'];
        for (const s of sels) { const e = document.querySelector(s);
            if (e && e.offsetParent !== null && e.innerText.trim()) return e.innerText.trim(); }
        return ''; }""")
    for sel in ['[id="#ICOK"]', '#ALERTOK', '[id="#ICYes"]']:
        loc = page.locator(sel)
        if loc.count() and loc.first.is_visible():
            loc.first.click()
            ps_wait(page)
            break
    return msg


def login(page, email, password, twofa_timeout=300):
    page.goto(LIST_URL, wait_until="networkidle", timeout=90000)
    if "accounts.google.com" in page.url:
        if not (email and password):
            sys.exit("Google login needed but ERP_EMAIL / ERP_PASSWORD are not set "
                     "(copy .env.example to .env and fill it in)")
        log("Signing in to Google...")
        # account chooser
        chooser = page.locator(f'[data-identifier="{email}"]')
        if chooser.count():
            chooser.first.click()
            page.wait_for_load_state("networkidle")
        ident = page.locator("#identifierId")
        if ident.count() and ident.is_visible():
            ident.fill(email)
            page.click("#identifierNext")
        try:
            page.wait_for_selector("input[name=Passwd]", state="visible", timeout=20000)
            page.fill("input[name=Passwd]", password)
            page.click("#passwordNext")
        except Exception:
            pass  # password step skipped (session partially remembered)
        log(f">>> If Google asks, approve the sign-in on your phone (waiting up to {twofa_timeout}s)")
        deadline = time.time() + twofa_timeout
        while time.time() < deadline and "accounts.google.com" in page.url:
            page.wait_for_timeout(2000)
        if "accounts.google.com" in page.url:
            SHOTS.mkdir(exist_ok=True)
            page.screenshot(path=str(SHOTS / "login_failed.png"))
            sys.exit("Login did not complete. See screenshots/login_failed.png")
        page.wait_for_load_state("networkidle")
        # SSO may land on the ERP gateway first; go to the feedback page again
        page.goto(LIST_URL, wait_until="networkidle", timeout=90000)
    if "Z_STDFEED_SRCH" not in page.url:
        sys.exit(f"Could not reach the feedback page (ended at {page.url})")
    log("Logged in.")


def list_courses(page):
    return page.evaluate("""() => [...document.querySelectorAll('[id^="Z_STDFEED_WRK_ADD_BTN$"]')].map(b => {
        const tds = [...b.closest('tr').querySelectorAll('td')].map(td => td.innerText.trim());
        return { idx: +b.id.split('$')[1], id: b.id,
                 enabled: !b.disabled && !b.className.includes('DISABLED'),
                 label: tds.slice(0, 5).join(' | ') }; })""")


def question_text(page, el_handle):
    """Text between the previous answer widget and this one = the question."""
    return page.evaluate("""(el) => {
        const all = [...document.querySelectorAll('%s, %s')];
        const i = all.indexOf(el); const r = document.createRange();
        if (i > 0) r.setStartAfter(all[i-1]); else r.setStart(document.body, 0);
        r.setEndBefore(el);
        let t = r.toString();
        if (i === 0) { const k = t.lastIndexOf('Instructor Name'); t = k >= 0 ? t.slice(k + 15) : t.slice(-200); }
        return t.replace(/\\s+/g, ' ').replace(/Weightage:.*$/, '').replace(/Options\\s*$/, '').trim();
    }""" % (CHECKBOX_GRID, TEXTAREA), el_handle)


def grid_options(page, grid_id):
    return page.evaluate("""(gid) => {
        const g = document.getElementById(gid);
        return [...g.querySelectorAll('tr[id^="trZ_STDFED_OPN_VW"]')].map(tr => {
            const cb = tr.querySelector('input[type=checkbox]');
            const lbl = tr.querySelector('[id^="Z_STDFED_L3_WRK_DESCR$"]');
            return cb && lbl ? { id: cb.id, label: lbl.innerText.trim(), checked: cb.checked } : null;
        }).filter(Boolean); }""", grid_id)


def pick(options):
    labels = [o["label"].lower().strip() for o in options]
    for pref in PREFERRED:
        if pref in labels:
            return options[labels.index(pref)]
    return options[0]


def click_checkbox(page, cid, want=True):
    loc = page.locator(f'[id="{cid}"]')
    if loc.is_checked() != want:
        loc.click()
        ps_wait(page)


def fill_current_instructor(page, quiet=False):
    problems = []
    grid_ids = page.eval_on_selector_all(CHECKBOX_GRID, "els => els.map(e => e.id)")
    for gid in grid_ids:
        q = question_text(page, page.locator(f'[id="{gid}"]').element_handle())
        opts = grid_options(page, gid)
        if not opts:
            continue
        target = pick(opts)
        click_checkbox(page, target["id"], True)
        # make sure exactly one option is ticked
        for o in grid_options(page, gid):
            if o["id"] != target["id"] and o["checked"]:
                click_checkbox(page, o["id"], False)
        final = [o["label"] for o in grid_options(page, gid) if o["checked"]]
        if final != [target["label"]]:
            problems.append(f"{q[:60]} -> {final}")
        if not quiet or final != [target["label"]]:
            log(f"    [{', '.join(final) or '-'}]  {q[:80]}")
    for ta_id in page.eval_on_selector_all(TEXTAREA, "els => els.map(e => e.id)"):
        loc = page.locator(f'[id="{ta_id}"]')
        q = question_text(page, loc.element_handle())
        if not loc.input_value().strip():
            if quiet:
                log(f"    (re-filling empty text box) {q[:60]}")
            text = COMMENT_IMPROVE if re.search(r"improv|suggest|weak|change|better", q, re.I) else COMMENT_GOOD
            loc.fill(text)
            loc.dispatch_event("change")
        if not quiet:
            log(f"    [text]  {q[:80]}")
    return problems


def fill_form(page, tag, dry_run):
    problems = []
    pager = page.locator(INSTR_PAGER)
    n = pager.locator("option").count() if pager.count() else 1
    for i in range(n):
        if i > 0:
            page.locator(INSTR_PAGER).select_option(str(i))
            ps_wait(page)
        name = page.evaluate("""() => { const e = document.querySelector('[id^="PERSONAL_DATA_NAME_DISPLAY"]');
                                        return e ? e.innerText.trim() : '?'; }""")
        log(f"  Instructor {i + 1}/{n}: {name}")
        problems += fill_current_instructor(page)
        if dry_run:
            page.screenshot(path=str(SHOTS / f"{tag}_instructor{i + 1}.png"), full_page=True)
    if n > 1:
        # re-visit every instructor page to make sure nothing was lost when paging
        log("  Verifying all instructor pages...")
        problems = []
        for i in range(n):
            page.locator(INSTR_PAGER).select_option(str(i))
            ps_wait(page)
            problems += fill_current_instructor(page, quiet=True)
    return problems


def save_enabled(page):
    """PeopleSoft greys the Save button out (class ...TBSAVED) once there is nothing unsaved."""
    return page.evaluate("""() => { const b = document.getElementById('#ICSave');
        return !!b && !b.disabled && !b.className.includes('TBSAVED'); }""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="fill only the first pending form, don't save")
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    ap.add_argument("--limit", type=int, default=0, help="only save this many forms")
    ap.add_argument("--no-code", action="store_true", help="don't press Generate Code at the end")
    args = ap.parse_args()
    env = load_env()
    SHOTS.mkdir(exist_ok=True)

    with sync_playwright() as p:
        exe = find_browser(env)
        try:
            ua = None if args.headed else headless_user_agent(p, exe)
        except Exception as e:
            if exe is None and "Executable doesn't exist" in str(e):
                sys.exit("No Chrome/Chromium found. Run `playwright install chromium` "
                         "or set CHROME_PATH in .env.")
            raise
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE), executable_path=exe, headless=not args.headed,
            args=["--disable-blink-features=AutomationControlled"],
            user_agent=ua, viewport={"width": 1400, "height": 900})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        dialogs = []
        page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))

        login(page, env.get("ERP_EMAIL"), env.get("ERP_PASSWORD"))

        courses = list_courses(page)
        pending = [c for c in courses if c["enabled"]]
        log(f"{len(courses)} courses with an Overall Sem Feedback form.")
        failures = []
        todo = pending[:1] if args.dry_run else (pending[:args.limit] if args.limit else pending)
        for c in todo:
            log(f"\n== {c['label']}")
            page.goto(LIST_URL, wait_until="networkidle", timeout=90000)
            btn = page.locator(f'[id="{c["id"]}"]')
            if not btn.is_enabled():
                log("  already done, skipping")
                continue
            btn.click()
            ps_wait(page)
            page.wait_for_selector("#ICSave, [id='#ICSave']", timeout=60000)
            tag = re.sub(r"\W+", "_", c["label"])[:60]
            problems = fill_form(page, tag, args.dry_run)
            if problems:
                log("  !! some answers did not stick:", *problems, sep="\n     ")
            if args.dry_run:
                log(f"  DRY RUN: not saved. Screenshots in {SHOTS}/")
                continue
            if not save_enabled(page):
                log("  Already submitted earlier (nothing changed), skipping save.")
                continue
            dialogs.clear()
            page.locator('[id="#ICSave"]').click()
            ps_wait(page)
            msg = read_ps_message(page)
            page.screenshot(path=str(SHOTS / f"{tag}_saved.png"), full_page=True)
            info = " / ".join(filter(None, [msg] + dialogs))
            # (the Save button only greys out on the next page load, so judge by messages)
            if re.search(r"error|required|must|invalid|please (select|answer|enter|fill)", info, re.I):
                log(f"  !! Save may have FAILED. {info}")
                failures.append((c["label"], info))
            else:
                log(f"  Saved OK. {info}")

        if not args.dry_run and not args.limit:
            page.goto(LIST_URL, wait_until="networkidle", timeout=90000)
            if failures:
                log("\nForms with problems:", *[f"{l}: {m}" for l, m in failures], sep="\n  ")
            if not args.no_code:
                log("\nPressing Generate Code...")
                dialogs.clear()
                page.locator('[id="Z_STDFEED_WRK_SAVE_BTN"]').click()
                ps_wait(page)
                msg = read_ps_message(page)
                page.screenshot(path=str(SHOTS / "generate_code.png"), full_page=True)
                body = page.locator("body").inner_text()
                codes = re.findall(r"(?i)code[^\n]{0,80}", body)
                log("Result:", " / ".join(filter(None, [msg] + dialogs)) or "(no popup)")
                for line in codes:
                    log("  ", line.strip())
                log(f"Screenshot: {SHOTS / 'generate_code.png'}")
        ctx.close()


if __name__ == "__main__":
    main()
