---
name: Neyra website
description: A static download and product guide extending the desktop identity.
colors:
  paper: "#f5f2eb"
  ink: "#29232f"
  muted: "#625d66"
  purple: "#7843a5"
  dark: "#2a2234"
  mint: "#a8e0ca"
typography:
  display:
    fontFamily: "Manrope, Arial, sans-serif"
    fontSize: "clamp(54px, 6.5vw, 92px)"
    fontWeight: 750
    lineHeight: 1.07
    letterSpacing: "-0.04em"
  body:
    fontFamily: "Manrope, Arial, sans-serif"
    fontSize: "16px"
    fontWeight: 450
    lineHeight: 1.65
rounded:
  media: "14px"
  button: "8px"
spacing:
  small: "8px"
  medium: "24px"
  section: "80px"
components:
  button-primary:
    backgroundColor: "{colors.purple}"
    textColor: "#ffffff"
    rounded: "{rounded.button}"
    padding: "13px 23px"
---

# Neyra website design

The landing page extends the existing desktop identity: warm off-white surfaces,
purple actions, dark violet recording controls, and mint voice activity. Product
copy names what the app does and distinguishes development previews from releases.

## Tokens

- Background: `#f5f2eb`; foreground: `#29232f`; secondary text: `#625d66`.
- Primary action: `#7843a5`; preview section: `#eee7f2`.
- Recording surface: `#2a2234`; waveform mint: `#a8e0ca`.
- Dividers: `#d9d3d9`; media radius: `14px`; button radius: `8px`.
- Type: self-hosted Manrope, weights 450–800. Hero display caps at 92px;
  body text is 16px with 1.65 line height. Tracking stops at -0.04em.

## Structure

The first view shows the dictation mechanism, download action, and a text-only
interactive demonstration. Later sections explain the shortcut, show an actual
development screenshot, list assistant workflows, set honest expectations, offer
platform downloads, and answer practical setup questions.

Desktop sections use paired columns and editorial feature rows. Below 720px they
stack in reading order. Controls retain keyboard focus rings. Native details
elements handle FAQ disclosure. The demonstration is the page's only animation;
reduced-motion users see its completed text immediately.

## Maintenance

Preserve preview labels until a release contains those features. Keep release
links usable independently of the API lookup. Do not add build tooling to the
static page. Scope these decisions to `website/`, not the PySide6 app.
