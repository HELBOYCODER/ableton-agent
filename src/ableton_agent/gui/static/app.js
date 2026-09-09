/* ==========================================================================
   Ableton Agent Studio — Frontend Controller
   ========================================================================== */

document.addEventListener("DOMContentLoaded", () => {
  // Elements
  const livePill = document.getElementById("livePill");
  const statusText = document.getElementById("statusText");
  const detectedLiveName = document.getElementById("detectedLiveName");
  const bridgeStatusNote = document.getElementById("bridgeStatusNote");
  
  const playBtn = document.getElementById("playBtn");
  const stopBtn = document.getElementById("stopBtn");
  const bpmInput = document.getElementById("bpmInput");
  const inspectBtn = document.getElementById("inspectBtn");
  const installBtn = document.getElementById("installBtn");
  
  const modelPills = document.querySelectorAll(".model-pill");
  const activeModelBadge = document.getElementById("activeModelBadge");
  const presetChips = document.querySelectorAll(".preset-chip");
  const promptInput = document.getElementById("promptInput");
  const dryCheck = document.getElementById("dryCheck");
  const generateBtn = document.getElementById("generateBtn");
  const feedLog = document.getElementById("feedLog");
  const clearLogBtn = document.getElementById("clearLogBtn");

  const noteBtns = document.querySelectorAll(".note-btn");
  const typeBtns = document.querySelectorAll(".type-btn");
  const chordPreview = document.getElementById("chordPreview");
  const sendChordBtn = document.getElementById("sendChordBtn");

  const stepGrid = document.getElementById("stepGrid");
  const hitsSlider = document.getElementById("hitsSlider");
  const stepsSlider = document.getElementById("stepsSlider");
  const swingSlider = document.getElementById("swingSlider");
  const hitsVal = document.getElementById("hitsVal");
  const stepsVal = document.getElementById("stepsVal");
  const swingVal = document.getElementById("swingVal");
  const euclideanFormula = document.getElementById("euclideanFormula");
  const sendGrooveBtn = document.getElementById("sendGrooveBtn");

  const copyMcpBtn = document.getElementById("copyMcpBtn");
  const copyFeedback = document.getElementById("copyFeedback");

  const tracksContainer = document.getElementById("tracksContainer");
  const trackCount = document.getElementById("trackCount");
  const refreshSetBtn = document.getElementById("refreshSetBtn");
  const toast = document.getElementById("toast");

  // State
  let currentRoot = "G3";
  let currentChordType = "min7";
  let currentHits = 5;
  let currentSteps = 16;
  let currentSwing = 15;
  let currentModel = "gpt-4o";

  // ------------------------------------------------------------------------
  // Helper: Toast notification
  // ------------------------------------------------------------------------
  function showToast(msg, duration = 2600) {
    toast.textContent = msg;
    toast.classList.add("show");
    setTimeout(() => toast.classList.remove("show"), duration);
  }

  // Helper: Append log entry
  function logFeed(msg, type = "command") {
    const el = document.createElement("div");
    el.className = `log-entry ${type}`;
    const time = new Date().toLocaleTimeString();
    el.textContent = `[${time}] ${msg}`;
    feedLog.appendChild(el);
    feedLog.scrollTop = feedLog.scrollHeight;
  }

  clearLogBtn.addEventListener("click", () => {
    feedLog.innerHTML = "";
    logFeed("Feed cleared.", "system");
  });

  // ------------------------------------------------------------------------
  // 1. Check System & Live Status
  // ------------------------------------------------------------------------
  async function checkStatus() {
    try {
      const res = await fetch("/api/status");
      const data = await res.json();

      detectedLiveName.textContent = data.detected_live || "Ableton Live 11/12";
      activeModelBadge.textContent = data.model || "gpt-4o";

      if (data.bridge_alive) {
        statusText.textContent = "Live Connected";
        livePill.style.background = "rgba(16, 185, 129, 0.15)";
        livePill.style.color = "#34d399";
        livePill.style.borderColor = "rgba(16, 185, 129, 0.4)";
        bridgeStatusNote.textContent = `Connected to Live (${data.host}:${data.port}) • Bridge v${data.version}`;
      } else if (data.bridge_installed) {
        statusText.textContent = "Bridge Ready (Launch Live)";
        livePill.style.background = "rgba(245, 158, 11, 0.15)";
        livePill.style.color = "#fbbf24";
        livePill.style.borderColor = "rgba(245, 158, 11, 0.4)";
        bridgeStatusNote.textContent = "ChatGPTBridge installed! Open Live > Preferences > Control Surface";
      } else {
        statusText.textContent = "Click 'Install Script'";
        livePill.style.background = "rgba(239, 68, 68, 0.15)";
        livePill.style.color = "#f87171";
        livePill.style.borderColor = "rgba(239, 68, 68, 0.4)";
        bridgeStatusNote.textContent = "Remote Script not installed yet. Click Install to configure.";
      }
    } catch (e) {
      statusText.textContent = "Studio Offline";
      bridgeStatusNote.textContent = "Connecting to local studio backend...";
    }
  }

  // ------------------------------------------------------------------------
  // 2. Transport & Direct Commands
  // ------------------------------------------------------------------------
  async function sendCommand(action, args = {}) {
    logFeed(`Sending: ${action} ${JSON.stringify(args)}`, "command");
    try {
      const res = await fetch("/api/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, args }),
      });
      const data = await res.json();
      logFeed(`OK: ${action} executed`, "ok");
      return data;
    } catch (e) {
      logFeed(`Error: ${e.message}`, "error");
    }
  }

  playBtn.addEventListener("click", () => sendCommand("play"));
  stopBtn.addEventListener("click", () => sendCommand("stop"));

  bpmInput.addEventListener("change", () => {
    const bpm = parseFloat(bpmInput.value);
    sendCommand("set_tempo", { bpm });
    showToast(`Tempo set to ${bpm} BPM`);
  });

  installBtn.addEventListener("click", async () => {
    installBtn.textContent = "Installing...";
    try {
      const res = await fetch("/api/install", { method: "POST", body: "{}" });
      const data = await res.json();
      if (data.success) {
        showToast("ChatGPTBridge installed into Ableton!");
        logFeed("Script installed! In Live, select ChatGPTBridge under Preferences > Link/MIDI.", "system");
        checkStatus();
      } else {
        showToast(`Install failed: ${data.error}`);
      }
    } catch (e) {
      showToast("Install request error: " + e.message);
    } finally {
      installBtn.textContent = "⚡ Install Script";
    }
  });

  // ------------------------------------------------------------------------
  // 3. AI Music Producer
  // ------------------------------------------------------------------------
  modelPills.forEach((pill) => {
    pill.addEventListener("click", async () => {
      modelPills.forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");
      currentModel = pill.dataset.model;
      const endpoint = pill.dataset.endpoint;
      activeModelBadge.textContent = currentModel;
      await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: currentModel, endpoint }),
      });
      showToast(`Switched model to ${currentModel}`);
      logFeed(`Active AI model set to ${currentModel} (${endpoint})`, "system");
    });
  });

  presetChips.forEach((chip) => {
    chip.addEventListener("click", () => {
      promptInput.value = chip.dataset.prompt;
      promptInput.focus();
    });
  });

  generateBtn.addEventListener("click", async () => {
    const prompt = promptInput.value.trim();
    if (!prompt) {
      showToast("Please enter a track description first!");
      promptInput.focus();
      return;
    }

    const dryRun = dryCheck.checked;
    generateBtn.disabled = true;
    generateBtn.querySelector(".btn-spinner").style.display = "inline-block";
    generateBtn.querySelector(".btn-text").textContent = "Planning & Building...";

    logFeed(`AI Producer prompt: "${prompt}"`, "system");

    try {
      const res = await fetch("/api/prompt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, dry_run: dryRun }),
      });
      const data = await res.json();

      if (data.success) {
        const commands = data.plan?.commands || [];
        logFeed(`LLM generated ${commands.length} commands successfully.`, "ok");
        commands.forEach((c, idx) => {
          logFeed(`[${idx + 1}/${commands.length}] ${c.action}: ${JSON.stringify(c.args || {})}`, "command");
        });
        showToast(dryRun ? "Plan generated (Dry run)" : "Track built in Ableton Live!");
        inspectSet(); // refresh tracks
      } else {
        logFeed(`Plan failed: ${data.error}`, "error");
        showToast("Error generating track: " + data.error);
      }
    } catch (e) {
      logFeed(`Request error: ${e.message}`, "error");
    } finally {
      generateBtn.disabled = false;
      generateBtn.querySelector(".btn-spinner").style.display = "none";
      generateBtn.querySelector(".btn-text").textContent = "🚀 Build in Ableton Live";
    }
  });

  // ------------------------------------------------------------------------
  // 4. Music Theory (Chords)
  // ------------------------------------------------------------------------
  const CHORD_INTERVALS = {
    maj: [0, 4, 7],
    min: [0, 3, 7],
    min7: [0, 3, 7, 10],
    maj7: [0, 4, 7, 11],
    min9: [0, 3, 7, 10, 14],
    sus4: [0, 5, 7],
    dim: [0, 3, 6],
  };

  const NOTE_OFFSET = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };

  function calculateChord(root, type) {
    const noteLetter = root[0];
    const octave = parseInt(root.slice(1)) || 3;
    const basePitch = (octave + 1) * 12 + NOTE_OFFSET[noteLetter];
    const intervals = CHORD_INTERVALS[type] || [0, 3, 7];
    return intervals.map((iv) => basePitch + iv);
  }

  function updateChordUI() {
    const pitches = calculateChord(currentRoot, currentChordType);
    chordPreview.textContent = `${currentRoot} ${currentChordType.toUpperCase()}: [${pitches.join(", ")}]`;
  }

  noteBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      noteBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentRoot = btn.dataset.note;
      updateChordUI();
    });
  });

  typeBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      typeBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentChordType = btn.dataset.type;
      updateChordUI();
    });
  });

  sendChordBtn.addEventListener("click", async () => {
    const pitches = calculateChord(currentRoot, currentChordType);
    logFeed(`Generating chord ${currentRoot} ${currentChordType}...`, "command");
    const notes = pitches.map((p) => ({
      pitch: p,
      start: 0.0,
      length: 2.0,
      velocity: 100 + Math.floor(Math.random() * 10),
    }));
    await sendCommand("create_clip", { track_index: 0, slot: 0, length_beats: 4.0 });
    await sendCommand("add_notes", { track_index: 0, slot: 0, notes });
    showToast(`Sent ${currentRoot} ${currentChordType} to Track 1!`);
  });

  // ------------------------------------------------------------------------
  // 5. 16-Step Euclidean Sequencer
  // ------------------------------------------------------------------------
  function bjorklund(hits, steps) {
    if (hits <= 0) return new Array(steps).fill(0);
    if (hits >= steps) return new Array(steps).fill(1);
    let pattern = [];
    for (let i = 0; i < hits; i++) pattern.push([1]);
    for (let i = 0; i < steps - hits; i++) pattern.push([0]);

    while (pattern.length > 1) {
      const ones = pattern.filter((x) => x[0] === 1);
      const zeros = pattern.filter((x) => x[0] === 0);
      if (zeros.length === 0 || ones.length === 0) break;
      const minLen = Math.min(ones.length, zeros.length);
      const next = [];
      for (let i = 0; i < minLen; i++) next.push(ones[i].concat(zeros[i]));
      next.push(...ones.slice(minLen));
      next.push(...zeros.slice(minLen));
      pattern = next;
    }
    return pattern.flat();
  }

  function renderGrid() {
    const pattern = bjorklund(currentHits, currentSteps);
    stepGrid.innerHTML = "";
    stepGrid.style.gridTemplateColumns = `repeat(${currentSteps}, 1fr)`;

    pattern.forEach((hit, idx) => {
      const pad = document.createElement("div");
      pad.className = `step-pad ${hit ? "active" : ""}`;
      pad.textContent = idx + 1;
      pad.addEventListener("click", () => {
        pad.classList.toggle("active");
      });
      stepGrid.appendChild(pad);
    });

    hitsVal.textContent = currentHits;
    stepsVal.textContent = currentSteps;
    swingVal.textContent = `${currentSwing}%`;

    let label = `${currentHits} Hits / ${currentSteps} Steps`;
    if (currentHits === 3 && currentSteps === 8) label += " (Tresillo)";
    else if (currentHits === 5 && currentSteps === 16) label += " (Afro / House)";
    else if (currentHits === 7 && currentSteps === 16) label += " (Funky Break)";
    else if (currentHits === 4 && currentSteps === 16) label += " (Four on the floor)";
    euclideanFormula.textContent = label;
  }

  hitsSlider.addEventListener("input", (e) => {
    currentHits = parseInt(e.target.value);
    renderGrid();
  });

  stepsSlider.addEventListener("input", (e) => {
    currentSteps = parseInt(e.target.value);
    if (currentHits > currentSteps) {
      currentHits = currentSteps;
      hitsSlider.value = currentHits;
    }
    hitsSlider.max = currentSteps;
    renderGrid();
  });

  swingSlider.addEventListener("input", (e) => {
    currentSwing = parseInt(e.target.value);
    swingVal.textContent = `${currentSwing}%`;
  });

  sendGrooveBtn.addEventListener("click", async () => {
    const pattern = bjorklund(currentHits, currentSteps);
    const stepLen = 4.0 / currentSteps;
    const notes = [];

    pattern.forEach((hit, idx) => {
      if (hit) {
        let start = idx * stepLen;
        if (idx % 2 === 1 && currentSwing > 0) {
          start += (currentSwing / 100) * 0.1;
        }
        notes.push({
          pitch: 36, // Kick / Base
          start: parseFloat(start.toFixed(4)),
          length: 0.2,
          velocity: idx % 4 === 0 ? 115 : 95 + Math.floor(Math.random() * 10),
        });
      }
    });

    logFeed(`Sending Euclidean beat (${currentHits}/${currentSteps}) to Live...`, "command");
    await sendCommand("create_clip", { track_index: 0, slot: 1, length_beats: 4.0 });
    await sendCommand("add_notes", { track_index: 0, slot: 1, notes });
    showToast(`Sent ${currentHits}/${currentSteps} beat to Ableton!`);
  });

  // ------------------------------------------------------------------------
  // 6. Live Project Inspector
  // ------------------------------------------------------------------------
  async function inspectSet() {
    refreshSetBtn.textContent = "Loading...";
    try {
      const res = await fetch("/api/describe");
      const data = await res.json();
      const set = data.set;

      if (!set || !set.tracks || set.tracks.length === 0) {
        tracksContainer.innerHTML = '<div class="empty-tracks">No active tracks reported. Is Ableton Live playing?</div>';
        trackCount.textContent = "0 Tracks";
        return;
      }

      trackCount.textContent = `${set.tracks.length} Tracks • ${set.tempo} BPM`;
      bpmInput.value = Math.round(set.tempo);
      tracksContainer.innerHTML = "";

      set.tracks.forEach((t) => {
        const card = document.createElement("div");
        card.className = "track-card";
        const isMidi = t.is_midi;
        const devicesHtml = (t.devices || [])
          .map((d) => `<span class="device-badge">${d}</span>`)
          .join("");

        card.innerHTML = `
          <div class="track-card-header">
            <span class="track-name">${t.name || `Track ${t.index + 1}`}</span>
            <span class="track-type ${isMidi ? "midi" : "audio"}">${isMidi ? "MIDI" : "AUDIO"}</span>
          </div>
          <div class="track-devices">
            ${devicesHtml || '<span style="color:var(--text-dim);">No devices</span>'}
          </div>
        `;
        tracksContainer.appendChild(card);
      });
      logFeed(`Live set inspected: ${set.tracks.length} tracks at ${set.tempo} BPM`, "ok");
    } catch (e) {
      tracksContainer.innerHTML = `<div class="empty-tracks">Could not reach Ableton: ${e.message}</div>`;
    } finally {
      refreshSetBtn.textContent = "↻ Refresh";
    }
  }

  inspectBtn.addEventListener("click", inspectSet);
  refreshSetBtn.addEventListener("click", inspectSet);

  // ------------------------------------------------------------------------
  // 7. MCP Copy Config
  // ------------------------------------------------------------------------
  copyMcpBtn.addEventListener("click", async () => {
    const config = {
      mcpServers: {
        "ableton-agent": {
          command: "ableton-agent",
          args: ["mcp"],
        },
      },
    };
    try {
      await navigator.clipboard.writeText(JSON.stringify(config, null, 2));
      copyFeedback.style.display = "inline";
      setTimeout(() => (copyFeedback.style.display = "none"), 3000);
      showToast("Copied MCP config to clipboard!");
    } catch (e) {
      showToast("Failed to copy automatically. See README.");
    }
  });

  // Initial Boot
  checkStatus();
  updateChordUI();
  renderGrid();
});
