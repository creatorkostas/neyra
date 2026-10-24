# Neyra website

Plain HTML, CSS, and JavaScript. No framework, package installation, or build step.

## Preview locally

From the repository root:

```sh
python -m http.server 4173 --directory website --bind 127.0.0.1
```

Open http://127.0.0.1:4173. The local preview and published site use the same files.

## Publish

GitHub Pages is configured to use GitHub Actions. The `Publish website` workflow
uploads only `website/` and deploys it when website files change on `main`. It can
also run manually from the Actions tab.

Site: https://creatorkostas.github.io/neyra/

If configuring a fork, open **Settings → Pages → Build and deployment** and choose
**GitHub Actions** as the source. Update the repository URLs, canonical URL, and
release lookup in the site files to match the fork.

The release API adds the latest version label. Download links work without
JavaScript or if that API request fails. They point to the existing release asset
names, not files committed into this website.

The assistant screenshot is a real development UI capture with illustrative
content. It is labeled as a preview because release binaries can lag behind
development. Update the preview and release copy as features are published.

## Assets

`assets/manrope.ttf` is Manrope, distributed under the SIL Open Font License in
`assets/OFL.txt`. The font is self-hosted. The logo comes from Neyra's existing
desktop icon. The page does not request microphone access or include analytics.
