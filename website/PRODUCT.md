# Neyra public website

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Plain static HTML, CSS, and JavaScript, hosted on GitHub Pages. The user explicitly
requested no framework and asked to configure GitHub hosting.

## Purpose

Introduce Neyra, explain local desktop dictation, and provide Windows, Linux,
and Apple silicon macOS release downloads. Neyra itself remains a Python/PySide6 desktop application.

## Audience

Windows, Linux, and Apple silicon Mac users deciding whether to try Neyra. The user confirmed that
the page should focus on downloads and a feature guide, matching the app's look.

## Product truth

- Default Whistle recognition is local, English, and uses a small model.
- Its current results are useful but not exceptional. It is an early project.
- Voz is optional and requires Node.js. Linux integration varies by desktop. The Apple silicon macOS build is planned for the next tagged release, is unsigned, and requires approving first launch in Privacy & Security.
- The new assistant preview has bounded desktop commands, selected-text AI,
  questions over saved notes, meeting actions, and a spoken local daily briefing.
- Optional AI connects with the user's ChatGPT account.
- The published binaries can lag behind development. The page must label preview
  features and screenshots rather than imply they are in every release.

## Evidence

The application source and README define behavior. The preview screenshot is an
actual development UI capture containing illustrative notes. No testimonials,
performance measurements, customer counts, or certification claims are supplied.

## Constraints

Relative asset paths support GitHub Pages' `/neyra/` project path. Download links
work without JavaScript. No microphone access, analytics, authentication, or app
runtime belongs in this static page. Fonts are self-hosted under their license.
