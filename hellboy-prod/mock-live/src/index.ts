import net from "node:net";

interface MockTrack {
  name: string;
  kind: "midi" | "audio";
  volume: number;
  pan: number;
  mute: boolean;
  solo: boolean;
  devices: { name: string; class: string; params: number }[];
  slots: { hasClip: boolean; name: string | null; notes: any[] }[];
}

const port = Number(process.env.HELLBOY_PORT || 8971);

const state = {
  tempo: 124,
  signature: [4, 4],
  playing: false,
  tracks: [
    {
      name: "Drums", kind: "midi", volume: 0.8, pan: 0, mute: false, solo: false,
      devices: [{ name: "Drum Rack", class: "DrumGroupDevice", params: 4 }],
      slots: Array.from({ length: 8 }, () => ({ hasClip: false, name: null, notes: [] })),
    },
    {
      name: "Bass", kind: "audio", volume: 0.7, pan: 0, mute: false, solo: false,
      devices: [{ name: "Compressor", class: "Compressor2", params: 6 }],
      slots: Array.from({ length: 8 }, () => ({ hasClip: false, name: null, notes: [] })),
    },
  ] as MockTrack[],
};

const METHODS = [
  "hello", "ping", "shutdown",
  "session_state", "session_overview", "session_set_tempo", "session_set_signature",
  "session_save", "session_undo", "session_redo", "session_capture_scene",
  "session_set_master_volume", "transport_play", "transport_stop", "transport_seek",
  "transport_set_loop",
  "track_list", "track_brief", "track_create_midi", "track_create_audio",
  "track_create_return", "track_delete", "track_duplicate", "track_rename",
  "track_color", "track_set_volume", "track_set_pan", "track_mute", "track_solo",
  "track_arm", "track_set_send", "track_select", "track_group", "track_move",
  "track_fold", "track_freeze", "track_unfreeze",
  "clip_list", "clip_info", "clip_create", "clip_delete", "clip_duplicate",
  "clip_rename", "clip_color", "clip_set_loop", "clip_set_markers", "clip_set_warp",
  "clip_fire", "clip_stop", "clip_transpose",
  "scene_list", "scene_create", "scene_delete", "scene_fire", "scene_rename",
  "scene_duplicate",
  "notes_get", "notes_stats", "notes_set", "notes_add", "notes_clear",
  "notes_transpose", "notes_velocity", "notes_length_scale", "notes_range",
  "notes_quantize", "notes_humanize", "notes_legato", "notes_shuffle_time",
  "notes_detect_key", "notes_scale_fit", "notes_chords", "notes_arpeggiate", "notes_swing",
  "device_list", "device_params", "device_get_param", "device_set_param",
  "device_set_active", "device_delete", "device_move", "device_chains",
  "device_chain_devices", "device_add",
  "browser_roots", "browser_children", "browser_search", "browser_item", "browser_load",
  "automation_get", "automation_write", "automation_clear", "automation_list",
  "automation_clear_all",
  "mix_report", "mix_balance", "mix_chain",
  "quickloop_generate", "quickloop_scatter",
  "license_check", "license_status",
];

function brief(index: number, track: MockTrack) {
  return {
    index,
    name: track.name,
    kind: track.kind,
    color_index: index,
    mute: track.mute,
    solo: track.solo,
    arm: false,
    volume: track.volume,
    pan: track.pan,
    grouped: false,
    device_count: track.devices.length,
    clip_count: track.slots.filter((s) => s.hasClip).length,
    sends: [0, 0],
  };
}

function trackAt(index: number): MockTrack {
  let position = Number(index);
  if (position < 0) position = state.tracks.length + position;
  const track = state.tracks[position];
  if (!track) throw new Error(`track index out of range: ${index}`);
  return track;
}

function slotAt(trackIndex: number, slotIndex: number) {
  const track = trackAt(trackIndex);
  let position = Number(slotIndex);
  if (position < 0) position = track.slots.length + position;
  const slot = track.slots[position];
  if (!slot) throw new Error(`clip slot index out of range: ${slotIndex}`);
  return slot;
}

function dispatch(method: string, params: any): any {
  switch (method) {
    case "hello":
      return {
        product: "Hellboy Prod",
        api: 1,
        port,
        live_version: "12.0-mock",
        methods: METHODS,
      };
    case "ping":
      return { pong: true };
    case "session_state":
      return {
        product: "Hellboy Prod",
        tempo: state.tempo,
        signature: state.signature,
        playing: state.playing,
        track_count: state.tracks.length,
        return_count: 0,
        scene_count: 2,
        selected_track: 0,
        tracks: state.tracks.map((t, i) => brief(i, t)),
        returns: [],
        scenes: [{ index: 0, name: "Scene 1" }, { index: 1, name: "Scene 2" }],
        master_volume: 0.85,
      };
    case "session_overview":
      return { text: "mock overview", track_count: state.tracks.length };
    case "session_set_tempo":
      state.tempo = Number(params.tempo);
      return { tempo: state.tempo };
    case "transport_play":
      state.playing = true;
      return { playing: true };
    case "transport_stop":
      state.playing = false;
      return { playing: false };
    case "track_list":
      return { tracks: state.tracks.map((t, i) => brief(i, t)) };
    case "track_brief": {
      const index = Number(params.index || 0);
      const track = trackAt(index);
      return {
        ...brief(index, track),
        devices: track.devices.map((d, i) => ({
          index: i, name: d.name, class: d.class, active: true,
          chainable: false, parameter_count: d.params,
        })),
        slots: track.slots.map((s, i) => ({
          index: i, has_clip: s.hasClip, name: s.name,
        })),
      };
    }
    case "track_create_midi":
    case "track_create_audio": {
      const name = params.name || (method.endsWith("midi") ? "MIDI" : "Audio");
      state.tracks.push({
        name, kind: method.endsWith("midi") ? "midi" : "audio",
        volume: 0.85, pan: 0, mute: false, solo: false,
        devices: [],
        slots: Array.from({ length: 8 }, () => ({ hasClip: false, name: null, notes: [] })),
      });
      return { index: state.tracks.length - 1, name };
    }
    case "track_delete":
      state.tracks.splice(Number(params.index || 0), 1);
      return { deleted: Number(params.index || 0), track_count: state.tracks.length };
    case "track_rename": {
      const track = trackAt(params.index);
      track.name = String(params.name ?? "");
      return { index: params.index, name: track.name };
    }
    case "track_set_volume": {
      const track = trackAt(params.index);
      track.volume = Number(params.value);
      return { index: params.index, volume: track.volume };
    }
    case "track_mute": {
      const track = trackAt(params.index);
      track.mute = Boolean(params.value);
      return { index: params.index, mute: track.mute };
    }
    case "clip_create": {
      const slot = slotAt(params.track, params.slot);
      slot.hasClip = true;
      slot.name = params.name || "Clip";
      slot.notes = [];
      return { track: params.track, slot: params.slot, length: Number(params.length || 4) };
    }
    case "clip_delete": {
      const slot = slotAt(params.track, params.slot);
      if (!slot.hasClip) throw new Error("slot is empty");
      slot.hasClip = false;
      slot.name = null;
      slot.notes = [];
      return { deleted: true };
    }
    case "clip_info": {
      const slot = slotAt(params.track, params.slot);
      if (!slot.hasClip) throw new Error("no clip");
      return {
        track: params.track, slot: params.slot, name: slot.name, length: 4,
        midi: true, looping: true, loop_start: 0, loop_end: 4,
        color_index: 0, note_count: slot.notes.length,
      };
    }
    case "notes_set": {
      const slot = slotAt(params.track, params.slot);
      slot.notes = (params.notes || []).map((n: any) => ({ ...n }));
      return { written: slot.notes.length };
    }
    case "notes_add": {
      const slot = slotAt(params.track, params.slot);
      slot.notes.push(...(params.notes || []).map((n: any) => ({ ...n })));
      return { written: (params.notes || []).length };
    }
    case "notes_get": {
      const slot = slotAt(params.track, params.slot);
      return { notes: slot.notes, count: slot.notes.length, length: 4 };
    }
    case "notes_clear": {
      const slot = slotAt(params.track, params.slot);
      slot.notes = [];
      return { cleared: true };
    }
    case "notes_stats": {
      const slot = slotAt(params.track, params.slot);
      return { count: slot.notes.length, length: 4 };
    }
    case "device_list": {
      const track = trackAt(params.track);
      return {
        devices: track.devices.map((d, i) => ({
          index: i, name: d.name, class: d.class, active: true,
          chainable: false, parameter_count: d.params,
        })),
      };
    }
    case "device_params": {
      const track = trackAt(params.track);
      const device = track.devices[Number(params.device || 0)];
      if (!device) throw new Error("device index out of range");
      return {
        device: device.name,
        parameters: Array.from({ length: device.params }, (_, i) => ({
          index: i, name: `Param ${i}`, value: 0.5, min: 0, max: 1,
          quantized: false, display: "0.5",
        })),
      };
    }
    case "browser_roots":
      return { roots: [{ name: "instruments", children: 3 }, { name: "audio_effects", children: 2 }] };
    case "browser_search":
      return {
        query: params.query,
        count: 1,
        items: [{ name: "Analog", path: "instruments/Analog", loadable: true, folder: false, device: true, uri: null }],
      };
    case "browser_children":
      return { path: params.path || "", items: [] };
    case "browser_load":
      return { loaded: params.path, into_track: params.track ?? null };
    case "mix_report":
      return {
        tracks: state.tracks.map((t, i) => ({
          index: i, name: t.name, kind: t.kind, volume: t.volume, pan: t.pan,
          mute: t.mute, solo: t.solo, device_count: t.devices.length,
          meter: 0.3 + i * 0.1, sends: [0, 0],
        })),
        loudest_meter: 0.4,
        master_volume: 0.85,
        playing: state.playing,
      };
    case "mix_balance":
      return { changed: state.tracks.length, tracks: [] };
    case "scene_list":
      return { scenes: [{ index: 0, name: "Scene 1" }, { index: 1, name: "Scene 2" }] };
    case "quickloop_generate":
    case "quickloop_scatter":
      return { notes: 16, length: 4, slices: Number(params.slices || 8), mode: params.mode || "shuffle" };
    case "license_status":
      return { checked: false, valid: null, detail: "not checked" };
    case "license_check":
      return { started: false, detail: "no license key provided" };
    default:
      return { method, params };
  }
}

const server = net.createServer((socket) => {
  let buffer = "";
  socket.on("data", (chunk) => {
    buffer += chunk.toString("utf8");
    let newline = buffer.indexOf("\n");
    while (newline >= 0) {
      const line = buffer.slice(0, newline);
      buffer = buffer.slice(newline + 1);
      newline = buffer.indexOf("\n");
      if (!line.trim()) continue;
      let request: any;
      try {
        request = JSON.parse(line);
      } catch {
        continue;
      }
      if (!METHODS.includes(request.method)) {
        socket.write(JSON.stringify({
          id: request.id, ok: false, error: `UnknownMethod: ${request.method}`,
        }) + "\n");
        continue;
      }
      try {
        const result = dispatch(request.method, request.params || {});
        socket.write(JSON.stringify({ id: request.id, ok: true, result }) + "\n");
      } catch (error) {
        socket.write(JSON.stringify({
          id: request.id, ok: false, error: (error as Error).message,
        }) + "\n");
      }
    }
  });
  socket.on("error", () => undefined);
});

server.listen(port, "127.0.0.1", () => {
  process.stdout.write(`mock-live ready on 127.0.0.1:${port}\n`);
});
