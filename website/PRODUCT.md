# Neyra public website

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Plain static HTML, CSS, and JavaScript, hosted on GitHub Pages. The user explicitly
requested no framework and asked to configure GitHub hosting.

## Purpose

Introduce Neyra, explain local desktop dictation, and provide Windows and Linux
release downloads. Neyra itself remains a Python/PySide6 desktop application.

## Audience

Assumption for this page: Windows and Linux users deciding whether to try Neyra.
The optional preference question received no answer before implementation. The
page defaults to downloads and a feature guide using the existing app identity.

## Product truth

- Default Whistle recognition is local, English, CPU-based, and uses a small model.
- Its current results are useful but not exceptional. It is an early project.
- Voz is optional and requires Node.js. Linux integration varies by desktop.
- The new assistant preview has bounded desktop commands, selected-text AI,
  questions over saved notes, meeting actions, and a spoken local daily briefing.
- Optional AI uses a Neyra-owned ChatGPT login, exact GPT-6 Luna, low reasoning.
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
