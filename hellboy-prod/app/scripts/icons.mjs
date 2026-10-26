// Render app/assets/icon.svg to PNGs and pack them into icon.icns (macOS) and
// icon.ico (Windows). PNG-in-ICNS and PNG-in-ICO need no other tools.
// Usage: node app/scripts/icons.mjs   (needs playwright + chromium)
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const dir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "assets");
const svg = fs.readFileSync(path.join(dir, "icon.svg"), "utf8");

const browser = await chromium.launch();
const page = await browser.newPage();
const png = {};
for (const size of [16, 32, 48, 64, 128, 256, 512, 1024]) {
  await page.setViewportSize({ width: size, height: size });
  await page.setContent(`<style>html,body{margin:0;background:transparent}</style>${svg.replace("<svg ", `<svg width="${size}" height="${size}" `)}`);
  png[size] = await page.screenshot({ omitBackground: true });
}
await browser.close();
fs.writeFileSync(path.join(dir, "icon.png"), png[1024]);

// ICNS: "icns" + length, then (type, length, png) entries
const icnsTypes = [["icp4", 16], ["icp5", 32], ["icp6", 64], ["ic07", 128], ["ic08", 256], ["ic09", 512], ["ic10", 1024]];
const entries = icnsTypes.map(([type, size]) => {
  const head = Buffer.alloc(8);
  head.write(type, 0, "ascii");
  head.writeUInt32BE(8 + png[size].length, 4);
  return Buffer.concat([head, png[size]]);
});
const body = Buffer.concat(entries);
const icnsHead = Buffer.alloc(8);
icnsHead.write("icns", 0, "ascii");
icnsHead.writeUInt32BE(8 + body.length, 4);
fs.writeFileSync(path.join(dir, "icon.icns"), Buffer.concat([icnsHead, body]));

// ICO: header, directory, then PNG images
const sizes = [16, 32, 48, 64, 128, 256];
const header = Buffer.alloc(6);
header.writeUInt16LE(0, 0);
header.writeUInt16LE(1, 2);
header.writeUInt16LE(sizes.length, 4);
let offset = 6 + 16 * sizes.length;
const dirs = sizes.map((size) => {
  const d = Buffer.alloc(16);
  d.writeUInt8(size >= 256 ? 0 : size, 0);
  d.writeUInt8(size >= 256 ? 0 : size, 1);
  d.writeUInt16LE(1, 4);
  d.writeUInt16LE(32, 6);
  d.writeUInt32LE(png[size].length, 8);
  d.writeUInt32LE(offset, 12);
  offset += png[size].length;
  return d;
});
fs.writeFileSync(path.join(dir, "icon.ico"), Buffer.concat([header, ...dirs, ...sizes.map((s) => png[s])]));
console.log("wrote icon.png, icon.icns, icon.ico");
