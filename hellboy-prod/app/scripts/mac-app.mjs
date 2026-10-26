// Wrap the macOS binary in "Hellboy Studio.app" so a double click never
// opens Terminal. The bundle's executable is a tiny launcher that starts the
// server in the background and exits, so clicking the icon again re-runs it
// and brings the browser window back instead of being swallowed by macOS.
// Usage: node mac-app.mjs <binary> <out-dir> <version>
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const [binary, outDir, version = "0.0.0"] = process.argv.slice(2);
const here = path.dirname(fileURLToPath(import.meta.url));
const app = path.join(outDir, "Hellboy Studio.app");
fs.rmSync(app, { recursive: true, force: true });
fs.mkdirSync(path.join(app, "Contents", "MacOS"), { recursive: true });
fs.mkdirSync(path.join(app, "Contents", "Resources"), { recursive: true });

fs.copyFileSync(binary, path.join(app, "Contents", "MacOS", "hellboy-studio"));
fs.chmodSync(path.join(app, "Contents", "MacOS", "hellboy-studio"), 0o755);
fs.writeFileSync(
  path.join(app, "Contents", "MacOS", "launch"),
  `#!/bin/sh
DIR="$(cd "$(dirname "$0")" && pwd)"
/usr/bin/nohup "$DIR/hellboy-studio" >/dev/null 2>&1 &
exit 0
`,
  { mode: 0o755 },
);
fs.copyFileSync(path.join(here, "..", "assets", "icon.icns"), path.join(app, "Contents", "Resources", "icon.icns"));
fs.writeFileSync(
  path.join(app, "Contents", "Info.plist"),
  `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Hellboy Studio</string>
  <key>CFBundleDisplayName</key><string>Hellboy Studio</string>
  <key>CFBundleIdentifier</key><string>prod.hellboy.studio</string>
  <key>CFBundleVersion</key><string>${version}</string>
  <key>CFBundleShortVersionString</key><string>${version}</string>
  <key>CFBundleExecutable</key><string>launch</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
`,
);
console.log(`built ${app}`);
