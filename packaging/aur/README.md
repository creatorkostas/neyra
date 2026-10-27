# Neyra AUR package

This directory prepares `neyra-bin`, an x86_64 Arch package for the Linux
Nuitka onefile release. No package has been published to the AUR by this work.
The recipe requires validation on a native Arch system before submission.

Tagged GitHub releases attach `neyra-bin-VERSION-aur.tar.gz` alongside
`Neyra-Linux-x86_64.tar.gz`. The submission archive contains `PKGBUILD`,
the hidden `.SRCINFO`, the launcher, desktop file, SVG icon, and app MIT license.
It contains no release executable. `makepkg` downloads that executable from
the corresponding GitHub release and verifies its SHA256.

## Generate for a release

Use Python 3.11 or newer. From the project root, supply the exact Linux release
archive, which must contain only the executable `Neyra` with executable permissions.
Replace `0.1.3` with the version being released; it is an example, not a published
release claim. Tags must use `v` followed by an Arch-compatible version without
hyphens or underscores.

```sh
python scripts/prepare_aur.py --version v0.1.3 \
  --archive dist/Neyra-Linux-x86_64.tar.gz --output dist/aur
tar -tzf dist/aur/neyra-bin-0.1.3-aur.tar.gz
```

The generator creates `dist/aur/neyra-bin/` and refuses to overwrite an existing
package directory. Choose a fresh output directory for another generation.
Both metadata files use the same version, dependencies, source URLs, and SHA256
values. Local text files use LF line endings even when generated on Windows.
Do not substitute `SKIP` or an example checksum for the release checksum.
The generator does not upload, build, install, or publish anything.

The portable synthetic check verifies metadata agreement, checksums, archive
contents including `.SRCINFO`, input rejection, and overwrite protection:

```sh
python packaging/aur/check_generator.py
```

## Check and install on Arch

Download the AUR submission archive from the intended GitHub release, extract it,
then inspect all the files. Run the following as an ordinary user on Arch after
installing the standard packaging tools:

```sh
sudo pacman -S --needed base-devel namcap desktop-file-utils
tar -xzf neyra-bin-0.1.3-aur.tar.gz
cd neyra-bin
bash -n PKGBUILD
desktop-file-validate neyra.desktop
makepkg --verifysource
makepkg --printsrcinfo > .SRCINFO
namcap PKGBUILD
makepkg --syncdeps --cleanbuild
namcap neyra-bin-*.pkg.tar.zst
sudo pacman -U neyra-bin-*.pkg.tar.zst
neyra
```

Review every `namcap` warning. The onefile embeds PySide6/Qt, Python dependencies,
models, and Python ONNX Runtime, so static dependency inspection alone cannot
prove that its extracted libraries load correctly. No Node.js installation is required on the
user's machine. PortAudio,
ALSA, PulseAudio client libraries, and Qt's host X11/XCB, graphics, font, and DBus
libraries are declared explicitly. Qt itself comes from the onefile payload.
`!strip` preserves Nuitka's appended executable payload.

Validate the declared dependencies against the actual tagged binary in a clean
Arch environment, ideally with `pkgctl build` from `devtools`. Confirm the desktop
menu icon and launcher, microphone dictation with both engines, meeting playback
capture through a working PulseAudio server or PipeWire PulseAudio compatibility
server, clipboard insertion, model downloads, and settings persistence. The
launcher executes `/opt/neyra/Neyra` directly and forwards its arguments.

X11 is the supported baseline for global hotkeys. Optional `wl-clipboard` and
`wtype` support insertion on compatible Wayland compositors; they do not provide
global hotkeys or universal compositor support. Check the actual desktop session.
Optional `libnotify` supplies `notify-send` for desktop reminder notifications when
the session has no tray icon. Neyra uses an in-app alert if no notification backend works.
Assistant playback commands use optional `playerctl`. Volume commands use `wpctl`
from WirePlumber or `pactl`. Piper speech is bundled and downloads its English voice on first use. Check these on the target desktop.

## Submit manually to the AUR

First check the official repositories and AUR for an existing package. Coordinate
with its maintainer if one exists. Read the current
[AUR submission guidelines](https://wiki.archlinux.org/title/AUR_submission_guidelines),
[Arch package guidelines](https://wiki.archlinux.org/title/Arch_package_guidelines),
[PKGBUILD reference](https://wiki.archlinux.org/title/PKGBUILD), and
[.SRCINFO guidance](https://wiki.archlinux.org/title/.SRCINFO).

Create an AUR account, add a dedicated SSH public key to its profile, and configure
that key for `aur.archlinux.org`. After the native checks above pass, use the AUR
SSH Git repository. Replace `/path/to/checked/neyra-bin` below with the directory
you checked. Add your own `# Maintainer: Name <email>` line to `PKGBUILD`.

```sh
git -c init.defaultBranch=master clone ssh://aur@aur.archlinux.org/neyra-bin.git
cd neyra-bin
cp /path/to/checked/neyra-bin/{PKGBUILD,.SRCINFO,neyra,neyra.desktop,neyra.svg,LICENSE} .
makepkg --printsrcinfo > .SRCINFO
git diff --check
git add PKGBUILD .SRCINFO neyra neyra.desktop neyra.svg LICENSE
git diff --cached
git commit -m "Package Neyra 0.1.3 binary release"
git push origin master
```

Those final commands publish the package only when the maintainer runs them.
Commit only the recipe, metadata, and local source files, never the Linux binary,
downloaded sources, built Arch packages, or build directories. For updates,
regenerate from the new exact release archive, repeat the native checks, and
update `.SRCINFO` with every metadata change. Bump `pkgrel` for packaging changes
to an existing upstream release and regenerate `.SRCINFO` before submission.
