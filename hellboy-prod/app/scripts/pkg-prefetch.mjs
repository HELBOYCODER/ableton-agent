// Put pkg's prebuilt Node base binaries into its cache before `pkg` runs.
//
// pkg-fetch looks for binaries under a release tag derived from its own
// version (v3.6 for 3.6.x), but they are published under earlier tags too.
// When the lookup misses, pkg silently starts compiling Node from source,
// which needs Visual Studio on Windows and hours on macOS. This script finds
// the binary under the expected tag or an earlier one, checks it against the
// SHA-256 that pkg-fetch itself ships (expected-shas.json), and stores it
// where pkg looks first.
//
// Usage: node app/scripts/pkg-prefetch.mjs node20-macos-arm64 [more targets]
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const fetchDir = path.dirname(require.resolve("@yao-pkg/pkg-fetch/package.json"));
const { version } = JSON.parse(fs.readFileSync(path.join(fetchDir, "package.json"), "utf8"));
const shas = JSON.parse(fs.readFileSync(path.join(fetchDir, "lib-es5", "expected-shas.json"), "utf8"));
const [major, minor] = version.split(".").map(Number);
const tag = `v${major}.${minor}`;
const cacheDir = path.join(process.env.PKG_CACHE_PATH || path.join(os.homedir(), ".pkg-cache"), tag);

function newest(nodeMajor, platform, arch) {
  const pattern = new RegExp(`^node-v(${nodeMajor}\\.\\d+\\.\\d+)-${platform}-${arch}$`);
  const versions = Object.keys(shas)
    .map((name) => pattern.exec(name)?.[1])
    .filter(Boolean)
    .sort((a, b) => {
      const [x, y] = [a, b].map((v) => v.split(".").map(Number));
      return x[1] - y[1] || x[2] - y[2];
    });
  if (!versions.length) throw new Error(`pkg-fetch ${version} lists no node${nodeMajor} for ${platform}-${arch}`);
  return versions[versions.length - 1];
}

const sha256 = (buffer) => crypto.createHash("sha256").update(buffer).digest("hex");

async function prefetch(target) {
  const match = /^node(\d+)-(\w+)-(\w+)$/.exec(target);
  if (!match) throw new Error(`target must look like node20-macos-arm64, got ${target}`);
  const [, nodeMajor, platform, arch] = match;
  const nodeVersion = newest(nodeMajor, platform, arch);
  const name = `node-v${nodeVersion}-${platform}-${arch}`;
  const expected = shas[name];
  const file = path.join(cacheDir, `fetched-v${nodeVersion}-${platform}-${arch}`);
  if (fs.existsSync(file) && sha256(fs.readFileSync(file)) === expected) {
    console.log(`${target}: cached ${name}`);
    return;
  }
  // the expected tag first, then earlier minors of the same major
  for (let m = minor; m >= 0; m--) {
    const url = `https://github.com/yao-pkg/pkg-fetch/releases/download/v${major}.${m}/${name}`;
    const res = await fetch(url);
    if (!res.ok) continue;
    const body = Buffer.from(await res.arrayBuffer());
    if (sha256(body) !== expected) throw new Error(`${name} from v${major}.${m}: SHA-256 mismatch`);
    fs.mkdirSync(cacheDir, { recursive: true });
    fs.writeFileSync(file, body, { mode: 0o755 });
    console.log(`${target}: ${name} from v${major}.${m} (sha256 ok)`);
    return;
  }
  throw new Error(`${name} is not published under any v${major}.x tag`);
}

// pkg also runs a base binary for the machine it is on (bytecode step)
const hostPlatform = { darwin: "macos", win32: "win", linux: "linux" }[process.platform];
const targets = new Set(process.argv.slice(2));
for (const target of [...targets]) {
  targets.add(target.replace(/-\w+-\w+$/, `-${hostPlatform}-${process.arch}`));
}
for (const target of targets) await prefetch(target);
