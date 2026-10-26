import { z } from "zod";

export interface ToolDef {
  name: string;
  description: string;
  shape: Record<string, z.ZodTypeAny>;
  method: string;
}

const track = z.number().int().describe("track index (negative counts from the end)");
const slot = z.number().int().describe("clip slot index");
const device = z.number().int().describe("device index on the track");
const value01 = z.number().describe("normalised 0..1 value");
const rootNote = z.string().default("C").describe("key root: C, C#, Db ... B");
const scaleName = z
  .enum([
    "major", "minor", "harmonic_minor", "melodic_minor", "dorian", "phrygian", "lydian",
    "mixolydian", "locrian", "pentatonic_major", "pentatonic_minor", "blues", "chromatic",
  ])
  .default("minor");

const noteShape = z.object({
  pitch: z.number().int().min(0).max(127),
  start: z.number().min(0),
  dur: z.number().min(0.001),
  vel: z.number().int().min(1).max(127).default(100),
  mute: z.boolean().default(false),
});

export const TOOLS: ToolDef[] = [
  // ------------------------------------------------------------- session
  {
    name: "session_state",
    description: "Full snapshot: tempo, signature, transport, every track with level/device/clip counts, returns and scenes.",
    shape: {},
    method: "session_state",
  },
  {
    name: "session_overview",
    description: "Compact human readable text summary of the live set.",
    shape: {},
    method: "session_overview",
  },
  {
    name: "session_set_tempo",
    description: "Set the project tempo in BPM.",
    shape: { tempo: z.number().min(20).max(999) },
    method: "session_set_tempo",
  },
  {
    name: "session_set_signature",
    description: "Set the time signature.",
    shape: { numerator: z.number().int(), denominator: z.number().int() },
    method: "session_set_signature",
  },
  {
    name: "session_set_master_volume",
    description: "Set the master volume (0..1).",
    shape: { value: value01 },
    method: "session_set_master_volume",
  },
  {
    name: "session_save",
    description: "Save the current Live set.",
    shape: {},
    method: "session_save",
  },
  {
    name: "session_undo",
    description: "Undo the last action.",
    shape: {},
    method: "session_undo",
  },
  {
    name: "session_redo",
    description: "Redo the last undone action.",
    shape: {},
    method: "session_redo",
  },
  {
    name: "session_capture_scene",
    description: "Capture everything currently playing into a new scene.",
    shape: {},
    method: "session_capture_scene",
  },
  {
    name: "transport_play",
    description: "Start playback, optionally from a given song time in beats.",
    shape: { from_time: z.number().min(0).optional() },
    method: "transport_play",
  },
  {
    name: "transport_stop",
    description: "Stop playback.",
    shape: {},
    method: "transport_stop",
  },
  {
    name: "transport_seek",
    description: "Move the playhead to a song time in beats.",
    shape: { time: z.number().min(0) },
    method: "transport_seek",
  },
  {
    name: "transport_set_loop",
    description: "Configure the arrangement loop.",
    shape: {
      enabled: z.boolean().optional(),
      start: z.number().min(0).optional(),
      length: z.number().min(0).optional(),
    },
    method: "transport_set_loop",
  },

  // -------------------------------------------------------------- tracks
  {
    name: "track_list",
    description: "List all tracks with level, pan, mute, solo, arm, device and clip counts.",
    shape: {},
    method: "track_list",
  },
  {
    name: "track_brief",
    description: "Detailed info for one track including its devices and clip slots.",
    shape: { index: track },
    method: "track_brief",
  },
  {
    name: "track_create_midi",
    description: "Create a MIDI track, optionally at an index and with a name.",
    shape: { index: z.number().int().default(-1), name: z.string().optional() },
    method: "track_create_midi",
  },
  {
    name: "track_create_audio",
    description: "Create an audio track.",
    shape: { index: z.number().int().default(-1), name: z.string().optional() },
    method: "track_create_audio",
  },
  {
    name: "track_create_return",
    description: "Create a return track.",
    shape: { name: z.string().optional() },
    method: "track_create_return",
  },
  {
    name: "track_delete",
    description: "Delete a track.",
    shape: { index: track },
    method: "track_delete",
  },
  {
    name: "track_duplicate",
    description: "Duplicate a track.",
    shape: { index: track },
    method: "track_duplicate",
  },
  {
    name: "track_rename",
    description: "Rename a track.",
    shape: { index: track, name: z.string() },
    method: "track_rename",
  },
  {
    name: "track_color",
    description: "Set a track colour index (0..69).",
    shape: { index: track, color_index: z.number().int().min(0).max(69) },
    method: "track_color",
  },
  {
    name: "track_set_volume",
    description: "Set a track volume (0..1).",
    shape: { index: track, value: value01 },
    method: "track_set_volume",
  },
  {
    name: "track_set_pan",
    description: "Set a track pan (-1..1).",
    shape: { index: track, value: z.number().min(-1).max(1) },
    method: "track_set_pan",
  },
  {
    name: "track_mute",
    description: "Mute or unmute a track.",
    shape: { index: track, value: z.boolean().default(true) },
    method: "track_mute",
  },
  {
    name: "track_solo",
    description: "Solo or unsolo a track.",
    shape: { index: track, value: z.boolean().default(true) },
    method: "track_solo",
  },
  {
    name: "track_arm",
    description: "Arm or disarm a track for recording.",
    shape: { index: track, value: z.boolean().default(true) },
    method: "track_arm",
  },
  {
    name: "track_set_send",
    description: "Set a send level on a track.",
    shape: { index: track, send: z.number().int().min(0), value: value01 },
    method: "track_set_send",
  },
  {
    name: "track_select",
    description: "Select a track so browser loads target it.",
    shape: { index: track },
    method: "track_select",
  },
  {
    name: "track_group",
    description: "Group tracks starting at the lowest given index.",
    shape: { indices: z.array(z.number().int()).min(1) },
    method: "track_group",
  },
  {
    name: "track_move",
    description: "Move a track to another index.",
    shape: { index: track, to: z.number().int().min(0) },
    method: "track_move",
  },
  {
    name: "track_fold",
    description: "Fold or unfold a group track.",
    shape: { index: track, folded: z.boolean().default(true) },
    method: "track_fold",
  },
  {
    name: "track_freeze",
    description: "Freeze a track.",
    shape: { index: track },
    method: "track_freeze",
  },
  {
    name: "track_unfreeze",
    description: "Unfreeze a track.",
    shape: { index: track },
    method: "track_unfreeze",
  },

  // --------------------------------------------------------------- clips
  {
    name: "clip_list",
    description: "List every clip slot on a track.",
    shape: { track },
    method: "clip_list",
  },
  {
    name: "clip_info",
    description: "Detailed info for one clip.",
    shape: { track, slot },
    method: "clip_info",
  },
  {
    name: "clip_create",
    description: "Create an empty clip in a slot.",
    shape: { track, slot, length: z.number().min(0.25).default(4), name: z.string().optional() },
    method: "clip_create",
  },
  {
    name: "clip_delete",
    description: "Delete the clip in a slot.",
    shape: { track, slot },
    method: "clip_delete",
  },
  {
    name: "clip_duplicate",
    description: "Duplicate a clip to another slot.",
    shape: {
      track,
      slot,
      target_track: z.number().int().optional(),
      target_slot: z.number().int().optional(),
    },
    method: "clip_duplicate",
  },
  {
    name: "clip_rename",
    description: "Rename a clip.",
    shape: { track, slot, name: z.string() },
    method: "clip_rename",
  },
  {
    name: "clip_color",
    description: "Set a clip colour index (0..69).",
    shape: { track, slot, color_index: z.number().int().min(0).max(69) },
    method: "clip_color",
  },
  {
    name: "clip_set_loop",
    description: "Set clip loop start/end and looping.",
    shape: {
      track,
      slot,
      start: z.number().min(0).optional(),
      end: z.number().min(0).optional(),
      looping: z.boolean().optional(),
    },
    method: "clip_set_loop",
  },
  {
    name: "clip_set_markers",
    description: "Set audio clip start and end markers.",
    shape: {
      track,
      slot,
      start: z.number().min(0).optional(),
      end: z.number().min(0).optional(),
    },
    method: "clip_set_markers",
  },
  {
    name: "clip_set_warp",
    description: "Set clip warping and warp mode.",
    shape: {
      track,
      slot,
      warping: z.boolean().optional(),
      mode: z.number().int().min(0).max(6).optional(),
    },
    method: "clip_set_warp",
  },
  {
    name: "clip_fire",
    description: "Fire the clip in a slot.",
    shape: { track, slot },
    method: "clip_fire",
  },
  {
    name: "clip_stop",
    description: "Stop the clip in a slot.",
    shape: { track, slot },
    method: "clip_stop",
  },
  {
    name: "clip_transpose",
    description: "Transpose every note in a MIDI clip.",
    shape: { track, slot, semitones: z.number().int() },
    method: "clip_transpose",
  },

  // -------------------------------------------------------------- scenes
  {
    name: "scene_list",
    description: "List scenes with their names and tempo.",
    shape: {},
    method: "scene_list",
  },
  {
    name: "scene_create",
    description: "Insert a new scene (-1 appends at the end).",
    shape: { index: z.number().int().default(-1), name: z.string().optional() },
    method: "scene_create",
  },
  {
    name: "scene_delete",
    description: "Delete a scene.",
    shape: { index: z.number().int() },
    method: "scene_delete",
  },
  {
    name: "scene_fire",
    description: "Launch a scene.",
    shape: { index: z.number().int() },
    method: "scene_fire",
  },
  {
    name: "scene_rename",
    description: "Rename a scene.",
    shape: { index: z.number().int(), name: z.string() },
    method: "scene_rename",
  },
  {
    name: "scene_duplicate",
    description: "Duplicate a scene with all its clips.",
    shape: { index: z.number().int() },
    method: "scene_duplicate",
  },

  // --------------------------------------------------------------- notes
  {
    name: "notes_get",
    description: "Read MIDI notes from a clip.",
    shape: {
      track,
      slot,
      pitch_low: z.number().int().default(0),
      pitch_high: z.number().int().default(127),
      time_low: z.number().min(0).default(0),
      time_high: z.number().min(0).optional(),
    },
    method: "notes_get",
  },
  {
    name: "notes_stats",
    description: "Note statistics: range, velocity, density, pitch classes.",
    shape: { track, slot },
    method: "notes_stats",
  },
  {
    name: "notes_set",
    description: "Replace all notes in a clip.",
    shape: { track, slot, notes: z.array(noteShape) },
    method: "notes_set",
  },
  {
    name: "notes_add",
    description: "Append notes to a clip without clearing it.",
    shape: { track, slot, notes: z.array(noteShape) },
    method: "notes_add",
  },
  {
    name: "notes_clear",
    description: "Remove every note from a clip.",
    shape: { track, slot },
    method: "notes_clear",
  },
  {
    name: "notes_transpose",
    description: "Transpose all notes in a clip.",
    shape: { track, slot, semitones: z.number().int() },
    method: "notes_transpose",
  },
  {
    name: "notes_velocity",
    description: "Scale and offset note velocities.",
    shape: { track, slot, factor: z.number().default(1), offset: z.number().int().default(0) },
    method: "notes_velocity",
  },
  {
    name: "notes_length_scale",
    description: "Scale note lengths.",
    shape: { track, slot, factor: z.number().default(1) },
    method: "notes_length_scale",
  },
  {
    name: "notes_range",
    description: "Fold notes into a pitch range.",
    shape: { track, slot, low: z.number().int().default(0), high: z.number().int().default(127) },
    method: "notes_range",
  },
  {
    name: "notes_quantize",
    description: "Quantize note starts to a grid with a strength.",
    shape: {
      track,
      slot,
      grid: z.number().min(0.01).default(0.25),
      strength: z.number().min(0).max(1).default(1),
    },
    method: "notes_quantize",
  },
  {
    name: "notes_humanize",
    description: "Add timing and velocity jitter.",
    shape: {
      track,
      slot,
      timing: z.number().default(0.02),
      velocity: z.number().int().default(12),
      seed: z.number().int().default(0),
    },
    method: "notes_humanize",
  },
  {
    name: "notes_legato",
    description: "Extend each note up to the next one.",
    shape: { track, slot, gap: z.number().min(0).default(0) },
    method: "notes_legato",
  },
  {
    name: "notes_shuffle_time",
    description: "Apply a swing feel to note starts.",
    shape: { track, slot, amount: z.number().min(0).max(1).default(0.15), seed: z.number().int().default(0) },
    method: "notes_shuffle_time",
  },

  // -------------------------------------------------------------- theory
  {
    name: "notes_detect_key",
    description: "Estimate the key of a MIDI clip (Krumhansl-Schmuckler, duration weighted). Returns the best key and runner-up candidates.",
    shape: { track, slot, top: z.number().int().min(1).max(24).default(3) },
    method: "notes_detect_key",
  },
  {
    name: "notes_scale_fit",
    description: "Snap every note of a MIDI clip into a key/scale.",
    shape: {
      track,
      slot,
      root: rootNote,
      scale: scaleName,
      direction: z.enum(["nearest", "up", "down"]).default("nearest"),
    },
    method: "notes_scale_fit",
  },
  {
    name: "notes_chords",
    description:
      "Write a diatonic chord progression into a MIDI clip. progression is a list of 1-based scale degrees, e.g. [1,6,3,7] (i-VI-III-VII in minor).",
    shape: {
      track,
      slot,
      root: rootNote,
      scale: scaleName,
      progression: z.array(z.number().int().min(1).max(14)).min(1).max(64).default([1, 6, 3, 7]),
      octave: z.number().int().min(-2).max(8).default(3).describe("Ableton octave numbering: C3 = MIDI 60"),
      size: z.number().int().min(1).max(7).default(3).describe("3 = triads, 4 = sevenths, 5 = ninths"),
      beats_per_chord: z.number().min(0.25).default(4),
      velocity: z.number().int().min(1).max(127).default(96),
      inversions: z.array(z.number().int().min(0).max(6)).optional().describe("inversion per chord"),
      spread: z.boolean().default(false).describe("open voicing: raise the middle voice an octave"),
      replace: z.boolean().default(true),
    },
    method: "notes_chords",
  },
  {
    name: "notes_arpeggiate",
    description: "Turn the held notes/chords of a MIDI clip into an arpeggio.",
    shape: {
      track,
      slot,
      rate: z.number().min(0.03125).default(0.25).describe("step length in beats (0.25 = 16ths)"),
      style: z.enum(["up", "down", "updown", "random", "played"]).default("up"),
      gate: z.number().min(0.05).max(1).default(0.8),
      octaves: z.number().int().min(1).max(4).default(1),
      seed: z.number().int().default(0),
    },
    method: "notes_arpeggiate",
  },
  {
    name: "notes_swing",
    description:
      "MPC-style swing: push off-beat notes late. Use a preset or grid + amount (50-75 %).",
    shape: {
      track,
      slot,
      preset: z
        .enum([
          "straight", "mpc_54", "mpc_58", "mpc_62", "mpc_66", "mpc_71",
          "eighth_swing", "triplet_eighth", "house_shuffle", "hiphop_lazy",
        ])
        .optional(),
      grid: z.number().min(0.0625).default(0.25).describe("0.25 = 16ths, 0.5 = 8ths"),
      amount: z.number().min(50).max(75).default(58),
    },
    method: "notes_swing",
  },

  // ------------------------------------------------------------- devices
  {
    name: "device_list",
    description: "List the device chain of a track.",
    shape: { track },
    method: "device_list",
  },
  {
    name: "device_params",
    description: "List every parameter of a device with ranges and display values.",
    shape: { track, device },
    method: "device_params",
  },
  {
    name: "device_get_param",
    description: "Read one parameter by index or name.",
    shape: { track, device, index: z.number().int().optional(), name: z.string().optional() },
    method: "device_get_param",
  },
  {
    name: "device_set_param",
    description: "Write one parameter by index or name.",
    shape: {
      track,
      device,
      index: z.number().int().optional(),
      name: z.string().optional(),
      value: z.number(),
      normalized: z.boolean().default(false),
    },
    method: "device_set_param",
  },
  {
    name: "device_set_active",
    description: "Bypass or enable a device.",
    shape: { track, device, active: z.boolean().default(true) },
    method: "device_set_active",
  },
  {
    name: "device_delete",
    description: "Delete a device from a track.",
    shape: { track, device },
    method: "device_delete",
  },
  {
    name: "device_move",
    description: "Move a device within the chain.",
    shape: { track, device, to: z.number().int().min(0) },
    method: "device_move",
  },
  {
    name: "device_chains",
    description: "List rack chains of a device.",
    shape: { track, device },
    method: "device_chains",
  },
  {
    name: "device_chain_devices",
    description: "List devices inside a rack chain.",
    shape: { track, device, chain: z.number().int().min(0) },
    method: "device_chain_devices",
  },
  {
    name: "device_add",
    description: "Load a device from the browser path onto a track.",
    shape: { track, path: z.string() },
    method: "device_add",
  },

  // ------------------------------------------------------------- browser
  {
    name: "browser_roots",
    description: "List the available browser root categories.",
    shape: {},
    method: "browser_roots",
  },
  {
    name: "browser_children",
    description: "List browser children under a path such as 'instruments'.",
    shape: {
      path: z.string().default(""),
      depth: z.number().int().min(1).max(4).default(1),
      limit: z.number().int().min(1).max(1000).default(500),
    },
    method: "browser_children",
  },
  {
    name: "browser_search",
    description: "Search the browser for loadable items by name.",
    shape: {
      query: z.string(),
      limit: z.number().int().min(1).max(200).default(25),
      categories: z.array(z.string()).optional(),
      loadable_only: z.boolean().default(true),
    },
    method: "browser_search",
  },
  {
    name: "browser_item",
    description: "Info about a single browser path.",
    shape: { path: z.string() },
    method: "browser_item",
  },
  {
    name: "browser_load",
    description: "Load a browser item, optionally onto a track.",
    shape: { path: z.string(), track: z.number().int().optional() },
    method: "browser_load",
  },

  // ---------------------------------------------------------- automation
  {
    name: "automation_get",
    description: "Read an automation envelope of a device parameter on a clip.",
    shape: {
      track,
      slot,
      device,
      param: z.number().int().describe("parameter index"),
      grid: z.number().min(0.01).default(0.25),
    },
    method: "automation_get",
  },
  {
    name: "automation_write",
    description: "Write automation points to a device parameter envelope.",
    shape: {
      track,
      slot,
      device,
      param: z.number().int(),
      points: z.array(z.object({ time: z.number().min(0), value: z.number() })),
      clear: z.boolean().default(true),
    },
    method: "automation_write",
  },
  {
    name: "automation_clear",
    description: "Clear one automation envelope.",
    shape: { track, slot, device, param: z.number().int() },
    method: "automation_clear",
  },
  {
    name: "automation_list",
    description: "List every parameter on a clip that already has an envelope.",
    shape: { track, slot },
    method: "automation_list",
  },
  {
    name: "automation_clear_all",
    description: "Clear every automation envelope on a clip.",
    shape: { track, slot },
    method: "automation_clear_all",
  },

  // --------------------------------------------------------------- mix
  {
    name: "mix_report",
    description: "Per track level, meter, pan and send report sorted by loudness.",
    shape: {
      tracks: z.array(z.number().int()).optional(),
      include_meters: z.boolean().default(true),
    },
    method: "mix_report",
  },
  {
    name: "mix_balance",
    description: "Sample the meters and rebalance track volumes. Start the transport first.",
    shape: {
      target: z.number().min(0.05).max(1).default(0.7),
      tracks: z.array(z.number().int()).optional(),
      samples: z.number().int().min(1).max(40).default(6),
      interval: z.number().int().min(1).max(20).default(2),
      max_gain: z.number().min(0.05).default(4),
      min_gain: z.number().min(0.01).default(0.25),
    },
    method: "mix_balance",
  },
  {
    name: "mix_chain",
    description: "Show the device chain of a track for gain staging review.",
    shape: { track },
    method: "mix_chain",
  },

  // ---------------------------------------------------------- quick loop
  {
    name: "quickloop_generate",
    description:
      "Slice a clip into N slices and rebuild it in a new order into another slot. mode: shuffle | reverse | rotate.",
    shape: {
      track,
      slot,
      target_track: z.number().int().optional(),
      target_slot: z.number().int().optional(),
      seed: z.number().int().default(0),
      slices: z.number().int().min(1).max(64).default(8),
      transpose: z.number().int().min(0).max(24).default(0),
      mode: z.enum(["shuffle", "reverse", "rotate"]).default("shuffle"),
      velocity_jitter: z.number().int().min(0).max(60).default(0),
    },
    method: "quickloop_generate",
  },
  {
    name: "quickloop_scatter",
    description: "Aggressive variation of quickloop_generate with 16 slices and octave jumps.",
    shape: {
      track,
      slot,
      target_track: z.number().int().optional(),
      target_slot: z.number().int().optional(),
      seed: z.number().int().default(0),
    },
    method: "quickloop_scatter",
  },

  // ------------------------------------------------------------- license
  {
    name: "license_check",
    description: "Validate the license key in the background.",
    shape: { license_key: z.string().optional() },
    method: "license_check",
  },
  {
    name: "license_status",
    description: "Current license state.",
    shape: {},
    method: "license_status",
  },
];
