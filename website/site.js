"use strict";

const demo = document.querySelector(".voice-demo");
const button = document.querySelector("#demo-button");
const text = document.querySelector("#demo-text");
const state = document.querySelector("#demo-state");
const announcement = document.querySelector("#demo-announcement");
const example = "A quick thought.\nA message to send.\nOne less thing to type.";

button.addEventListener("click", event => {
  button.disabled = true;
  demo.classList.add("is-playing");
  state.textContent = "Turning words into text";
  text.textContent = "";
  let position = 0;
  let timer;
  const finish = () => {
    window.clearInterval(timer);
    document.removeEventListener("visibilitychange", onVisibilityChange);
    text.textContent = example;
    demo.classList.remove("is-playing");
    state.textContent = "Your text is ready";
    button.disabled = false;
    announcement.textContent = "Preview complete. This demonstration did not use your microphone.";
  };
  const onVisibilityChange = () => {
    if (document.hidden) finish();
  };
  if (event.detail === 0 || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    text.textContent = example;
    finish();
    return;
  }
  document.addEventListener("visibilitychange", onVisibilityChange);
  timer = window.setInterval(() => {
    text.textContent = example.slice(0, ++position);
    if (position >= example.length) {
      window.clearInterval(timer);
      finish();
    }
  }, 29);
});

// The download links remain usable when GitHub's API is unavailable or JavaScript is disabled.
const controller = new AbortController();
const timeout = window.setTimeout(() => controller.abort(), 6000);
fetch("https://api.github.com/repos/creatorkostas/neyra/releases/latest", {signal: controller.signal})
  .then(response => {
    if (!response.ok) throw new Error("Release lookup unavailable");
    return response.json();
  })
  .then(release => {
    if (!/^v[0-9][a-zA-Z0-9.+-]*$/.test(release.tag_name || "")) return;
    document.querySelector("#release-version").textContent = "· " + release.tag_name;
    const assets = Array.isArray(release.assets) ? release.assets : [];
    const expected = {windows: "Neyra.exe", linux: "Neyra-Linux-x86_64.tar.gz", macos: "Neyra-macOS-AppleSilicon.zip"};
    for (const [platform, name] of Object.entries(expected)) {
      const asset = assets.find(item => item.name === name);
      if (asset) {
        const link = document.querySelector(`[data-platform="${platform}"]`);
        link.href = `https://github.com/creatorkostas/neyra/releases/download/${encodeURIComponent(release.tag_name)}/${name}`;
        if (platform === "macos") {
          link.querySelector("small").textContent = "Apple silicon · .app bundle";
          link.querySelector(".download-arrow").textContent = "↓";
        }
      }
    }
  })
  .catch(() => {
    document.querySelector("#release-status").textContent = "Version lookup is unavailable. Download links still open the latest published release.";
  })
  .finally(() => window.clearTimeout(timeout));
