# BITS ERP Feedback Filler

At the end of each semester, the BITS Pilani ERP won't show your marks until you fill in an
"Overall Sem Feedback" form for every course component (lecture, tutorial, lab). Each form can
have several instructors. This script fills them all in, saves them, and presses
**Generate Code** to get your code.

It drives a real Chrome/Chromium browser with [Playwright](https://playwright.dev/python/).

## Setup

You need Python 3.9 or newer.

```bash
git clone <this repo>
cd <repo folder>
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

The script uses Chrome or Chromium if it's already installed. If you have neither, run:

```bash
playwright install chromium
```

Then add your login details:

```bash
cp .env.example .env               # then edit .env
```

## Usage

```bash
python fill_feedback.py --dry-run   # fill the first form only, save screenshots, don't submit
python fill_feedback.py             # fill and submit every form, then press Generate Code
```

The first run logs in with Google. If your account has 2-step verification, approve the prompt on
your phone within 5 minutes. The session is saved in `.browser-profile/`, so later runs usually
skip the login.

At the end it prints your code, e.g. `Code: 1234`. A screenshot is also saved at
`screenshots/generate_code.png`.

| Option       | What it does                                         |
|--------------|------------------------------------------------------|
| `--dry-run`  | Fill the first form and take screenshots; don't save |
| `--headed`   | Show the browser window                              |
| `--limit N`  | Only submit the first N forms                        |
| `--no-code`  | Don't press Generate Code at the end                 |

Re-running is safe: forms you've already submitted are left as they are.

## Choosing your answers

The answers are set near the top of `fill_feedback.py`:

- `PREFERRED`: for each multiple-choice question, the script picks the first label in this list
  that the question offers. The default is "strongly agree", and "> 80%" for attendance. If none
  of the labels match, it picks the top option.
- `COMMENT_GOOD` / `COMMENT_IMPROVE`: text for the free-text questions. Questions that ask what
  needs improving get `COMMENT_IMPROVE`; all other text questions get `COMMENT_GOOD`.

The feedback goes to your instructors. Change these if you'd rather give real answers.

## Privacy

- `.env` holds your password. `.browser-profile/` holds your logged-in session. `screenshots/`
  shows your name, ID and courses. All three are listed in `.gitignore`. Never commit or share them.
- The script only talks to Google sign-in and the BITS ERP.

## Notes

- Tested on the Hyderabad campus SIS (`sis.erp.bits-pilani.ac.in`) in the 2026-27 first semester.
  If the ERP's form layout changes, the selectors at the top of the script will need updating.
- This is an unofficial student tool, not affiliated with BITS Pilani.
