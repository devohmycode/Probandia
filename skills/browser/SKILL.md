---
name: browser
description: What to do when a Probandia archive page asks for a sign-in.
---

# Signing in to an archive

Some archives (FamilySearch…) show their records only to a signed-in user.
Signing in is **the user's**: you never type a username or a password, never
fill or submit a sign-in form, never create an account, never go around the
screen. The guard refuses any typing in a page while a sign-in waits. Nor
do you pose as a browser to get past a filter: requests keep the engine's
identity, and a page that challenges it is read here, in a browser.

## Which browser

- **`read`** uses the engine's own browser, whose cookies are its own: a
  session opened in the user's Chrome does not reach it. Ask the user to run
  `BROWSER_LOGIN=` (`probandia browser login <archive>`) at their terminal: a
  window opens, they sign in, press Enter; the engine keeps the session.
- **A browser tool you drive** (Claude in Chrome, Playwright MCP…): stop on the
  sign-in screen, give the user `LOGIN_URL=`, let them sign in in that window.
  Once you see the logged-in marker (`login check <archive>` lists it), run
  `login confirm <archive>`.

## The question

`read` answers `STATUS=ASK`, `QUESTION=login_required`, `ARCHIVE=`,
`LOGIN_URL=`, `CHOICES=connected|skip|stop`, `OPTION=--login`. Ask it with the
harness's question tool (the `ask` skill), in the user's language, with the
link and the command; then **wait** for their answer.

- `connected`: run `read <url> --login connected`. A sign-in screen again:
  ask once more; after two tries, `skip`.
- `skip`: `read <url> --login skip`; the page is "not consulted", never a
  negative.
- `stop`: `read <url> --login stop`; end the pass and say why.

## Before the pass

`plan` answers `LOGIN_NEEDED=<archive>,…` (or `none`): ask for every sign-in
at once, before any field agent starts, so none of them waits on the user.

## In a team

A field agent never asks the user: it sends the orchestrator
`{"type":"question","body":"login_required <archive> <url>"}` and moves on to
its next source. The orchestrator asks, then hands the page back.

## Without a user

In a headless run the engine asks nothing: the page goes to the manual tasks
(`MANUAL_TASKS:` in the digest, "To read by hand" in the report). Say so.
