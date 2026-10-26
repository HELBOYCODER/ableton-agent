// Switch a Windows .exe to the GUI subsystem so double-clicking it does not
// open a console window. stdio still works when a parent passes pipes, so
// `hellboy-studio.exe --mcp` keeps working for agents.
// Usage: node win-gui.mjs path/to/app.exe
import fs from "node:fs";

const file = process.argv[2];
const exe = fs.readFileSync(file);
const peOffset = exe.readUInt32LE(0x3c);
if (exe.toString("latin1", peOffset, peOffset + 4) !== "PE\0\0") throw new Error(`${file} is not a PE file`);
const optional = peOffset + 24;
const magic = exe.readUInt16LE(optional);
if (magic !== 0x10b && magic !== 0x20b) throw new Error("unknown optional header");
const SUBSYSTEM = optional + 68; // same offset for PE32 and PE32+
const before = exe.readUInt16LE(SUBSYSTEM);
exe.writeUInt16LE(2, SUBSYSTEM); // IMAGE_SUBSYSTEM_WINDOWS_GUI
fs.writeFileSync(file, exe);
console.log(`${file}: subsystem ${before} -> 2 (GUI)`);
