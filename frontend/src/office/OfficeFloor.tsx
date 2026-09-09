import { useEffect, useRef, useState } from "react";
import { Application, Container, Graphics, Ticker, Texture } from "pixi.js";
import { TiledMapRenderer } from "./TiledMapRenderer";
import { Camera } from "./Camera";
import { Character, paintCup } from "./Character";
import { DeskScreen } from "./DeskScreen";
import { MessageEnvelope, type MessageAct } from "./MessageEnvelope";
import { hexToNumber, DEFAULT_CHARACTER } from "./cast";
import { pickSoloLine, pickExchange, type BreakSpot } from "./cafeteriaLines";
import { colors } from "./tokens";
import { loadTheme, resolveThemeMap, themeTilesetUrls } from "./themeLoader";
import { installContextLossRecovery, planInitFailure, DEFAULT_MAX_INIT_RETRIES } from "./glRecovery";
import type { Tile, Facing, ErrandKind, ErrandSpot } from "./themeRegistry";
import "./office.css";

// ---------------------------------------------------------------------------
// RazorGrowth-adapted OfficeFloor — prop-driven, no Electron / no window.cth
// Keeps the PixiJS room engine, Tiled map, procedural characters, and all
// live animation directors (cafeteria, coffee, errands, desk screens, envelopes)
// from the reference implementation. Data now comes from props.
// ---------------------------------------------------------------------------

export type OfficeAgentStatus =
  | "idle"
  | "thinking"
  | "working"
  | "waiting"
  | "blocked"
  | "success"
  | "ghost"
  | "compacting"
  | "looping";

export interface OfficeAgent {
  id: string;
  name: string;
  character: string; // OfficeCharacterName — fallback to 'jim' if unknown
  status: OfficeAgentStatus;
  action?: string;
  accent?: string; // coral|mint|sky|lemon|lilac|peach
  isGod?: boolean;
  carrying?: string;
  lastPrompt?: string;
}

interface OfficeFloorProps {
  agents: OfficeAgent[];
  selectedId?: string | null;
  onSelectAgent?: (id: string) => void;
  paused?: boolean;
}

function loadTexture(url: string): Promise<Texture> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      // Pixi 8 warns when an HTMLImageElement is passed directly ("Use CanvasSource instead").
      // Draw to a canvas first so Texture.from uses a CanvasSource and keeps nearest scaling.
      const canvas = document.createElement("canvas");
      canvas.width = img.naturalWidth || img.width;
      canvas.height = img.naturalHeight || img.height;
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        reject(new Error("canvas 2d context unavailable"));
        return;
      }
      ctx.drawImage(img, 0, 0);
      const tex = Texture.from(canvas);
      tex.source.scaleMode = "nearest";
      resolve(tex);
    };
    img.onerror = () => reject(new Error("failed to load " + url.slice(0, 40)));
    img.src = url;
  });
}

function liveActivity(agent: OfficeAgent, fallback = ""): string {
  const action = (agent.action || "").trim();
  if (action) return action;
  return agent.lastPrompt ? firstWords(agent.lastPrompt) : fallback;
}
function firstWords(prompt: string | undefined, maxWords = 6, maxChars = 42): string {
  if (!prompt) return "";
  const words = prompt.trim().split(/\s+/);
  let out = words.slice(0, maxWords).join(" ");
  const truncatedWords = words.length > maxWords;
  if (out.length > maxChars) out = out.slice(0, maxChars).trimEnd();
  else if (truncatedWords) out += "…";
  return out;
}

// Lightweight i18n stub — returns English strings for the floor
function t(key: string, vars?: Record<string, string>): string {
  const map: Record<string, string> = {
    "office.gpuError": "The office floor lost its GPU context.\n\nToo many contexts are using the GPU at once.\nClose a few tabs, or restart, to bring it back.",
    "office.mugs.empty": "no clean mugs left…",
    "office.mugs.brewing": "brewing a fresh one ☕",
    "office.mugs.washing": "washing the mug",
    "office.activity.waiting": "waiting",
    "office.activity.needsYou": "needs you",
    "office.activity.compacting": "compacting context",
    "office.activity.looping": "looping — breaker armed",
    "office.activity.runningFloor": "running the floor",
    "office.activity.idle": "idle",
  };
  let v = map[key] ?? key;
  if (vars) for (const [k, val] of Object.entries(vars)) v = v.replaceAll(`{{${k}}}`, val);
  return v;
}

interface CafeChat { lines: readonly string[]; partnerId: string; idx: number; beat: number; }
interface CafeBreak { spotIdx: number; phase: "walking" | "lingering"; timer: number; quipTimer: number; chat?: CafeChat; chattingWith?: string; }
interface ErrandRun { phase: "walking" | "doing"; timer: number; idx: number; }
interface CoffeeRun { phase: "toTray" | "taking" | "toMachine" | "brewing" | "toSink" | "washing" | "toTrayBack" | "placing"; timer: number; }
interface Runtime {
  character: Character;
  seatIndex: number | null;
  waitTile: Tile;
  charName: string;
  prevStatus?: string;
  prevAction?: string;
  prevCarrying?: string;
  prevPrompt?: string;
  brk?: CafeBreak;
  screen?: DeskScreen;
  cupCarryHome?: boolean;
  err?: ErrandRun;
  run?: CoffeeRun;
  busySince?: number;
}
const CHEER_MIN_BUSY_MS = 60_000;
const ERRAND_THOUGHTS: Record<ErrandKind, readonly string[]> = {
  water: ["watering the plants 🌱", "giving the plants a drink", "they grow so fast"],
  window: ["letting some air in 🌬", "a bit of fresh air", "nice breeze today"],
  dispenser: ["getting some water 💧", "hydration break", "staying sharp"],
  fridge: ["anything good in the fridge?", "who took my yogurt?", "just looking…"],
  shelf: ["checking out the shelf 📚", "anything new in here?", "so much good stuff"],
  bin: ["out with the scrap paper 🗑", "desk cleanup day", "tidying up a little"],
  smoke: ["the floor runs itself 🚬", "boss break.", "thinking big thoughts 🚬", "I DECLARE… a break"],
};
const SUCK_UP_KEYS = ["already shipped {{done}} tasks, boss. raise? 🚀","{{done}} tasks done this week, boss!","great vision as always, boss!","I was JUST about to do exactly that!","love the tie today, boss","working hard, boss! 💼","best boss ever. genuinely."] as const;
const GOSSIP_KEYS = ["has he ever actually written code?","another 'quick sync' that took an hour…","'world's best boss' — he bought that mug himself","he pinned MY task as his idea","the cigar smell, honestly…","he watered the plant. ONE plant. his own.","did you hear him? 'I DECLARE… a break'"] as const;
const CHEER_KEYS = ["done! 🎉","nailed it","that's a wrap","ship it 🚀","another one done","crushed it","in the books"] as const;

export function OfficeFloor({ agents, selectedId, onSelectAgent, paused = false }: OfficeFloorProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const appRef = useRef<Application | null>(null);
  const mountIdRef = useRef(0);
  const [glGeneration, setGlGeneration] = useState(0);
  const initRetriesRef = useRef(0);
  const agentsRef = useRef(agents);
  agentsRef.current = agents;
  const pausedRef = useRef(paused);
  useEffect(() => { pausedRef.current = paused; const ticker = appRef.current?.ticker; if (!ticker) return; if (paused) ticker.stop(); else ticker.start(); }, [paused]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    while (host.firstChild) host.removeChild(host.firstChild);
    const mountId = ++mountIdRef.current;
    const app = new Application();
    appRef.current = app;
    const runtimes = new Map<string, Runtime>();
    const seatClaims = new Set<number>();
    const envelopes: MessageEnvelope[] = [];
    const MAX_ENVELOPES = 16;

    const init = async () => {
      const theme = await loadTheme("office");
      await app.init({
        background: theme.palette.background as unknown as number,
        antialias: false,
        roundPixels: true,
        resolution: Math.max(window.devicePixelRatio || 1, 2),
        autoDensity: true,
        width: host.clientWidth || 800,
        height: host.clientHeight || 600,
      });
      if (mountIdRef.current !== mountId) { safeDestroy(app); return; }
      while (host.firstChild) host.removeChild(host.firstChild);
      host.appendChild(app.canvas as unknown as Node);
      (app as unknown as Record<string, unknown>).__glRecovery = installContextLossRecovery(app.canvas as unknown as EventTarget, {
        onRebuild: () => { if (mountIdRef.current === mountId) setGlGeneration((n) => n + 1); },
        onGiveUp: () => { if (mountIdRef.current !== mountId) return; host.appendChild(floorNote(t("office.gpuError"))); },
      });
      const tilesetTextures = await Promise.all(themeTilesetUrls(theme).map(loadTexture));
      if (mountIdRef.current !== mountId) { safeDestroy(app); return; }
      const world = new Container();
      app.stage.addChild(world);
      const mapRenderer = new TiledMapRenderer(resolveThemeMap(theme), tilesetTextures);
      world.addChild(mapRenderer.getContainer());
      const charLayer = mapRenderer.getCharacterContainer();
      const camera = new Camera(world);
      camera.setMapSize(mapRenderer.width * mapRenderer.tileSize, mapRenderer.height * mapRenderer.tileSize);
      camera.setViewSize(app.screen.width, app.screen.height);
      camera.fitToScreen();

      // Wall calendar (visual only — no triggers in RazorGrowth web build)
      const calTs = mapRenderer.tileSize;
      const calG = new Graphics();
      calG.eventMode = "none";
      calG.position.set(theme.anchors.calendar.x * calTs + 8, theme.anchors.calendar.y * calTs + 5);
      calG.zIndex = 3 * calTs;
      calG.rect(7, -2, 2, 2).fill(0x4a3b52);
      calG.rect(0, 0, 16, 20).fill(0x4a3b52);
      calG.rect(1, 1, 14, 18).fill(0xf2ead8);
      calG.rect(1, 1, 14, 4).fill(0xc94f4f);
      calG.rect(4, 0, 1, 2).fill(0xd8d3c4);
      calG.rect(11, 0, 1, 2).fill(0xd8d3c4);
      for (let r = 0; r < 3; r++) for (let c = 0; c < 5; c++) calG.rect(2 + c * 3, 7 + r * 4, 2, 2).fill(0xb8ab90);
      calG.rect(8, 11, 2, 2).fill(0xc94f4f);
      charLayer.addChild(calG);

      const seatTiles: Tile[] = [];
      const seatSeen = new Set<string>();
      const addSeat = (t?: Tile) => { if (!t) return; const k = `${t.x},${t.y}`; if (seatSeen.has(k)) return; seatSeen.add(k); seatTiles.push({ x: t.x, y: t.y }); };
      for (const name of theme.primarySeatNames) addSeat(mapRenderer.getSpawnPoint(name));
      const addZoneSeats = (zone: string) => {
        const z = mapRenderer.getZone(zone);
        if (!z) return;
        for (let y = z.y; y < z.y + z.height; y++) for (let x = z.x; x < z.x + z.width; x++) if (mapRenderer.isWalkable(x, y)) addSeat({ x, y });
      };
      addZoneSeats("boardroom");
      const entrance = mapRenderer.getSpawnPoint("entrance") ?? { x: Math.floor(mapRenderer.width / 2), y: mapRenderer.height - 2 };
      const waitTiles: Tile[] = [];
      const waitSeen = new Set<string>();
      for (let radius = 0; radius <= 6 && waitTiles.length < 16; radius++) {
        for (let dy = -radius; dy <= radius; dy++) for (let dx = -radius; dx <= radius; dx++) {
          if (Math.max(Math.abs(dx), Math.abs(dy)) !== radius) continue;
          const x = entrance.x + dx, y = entrance.y + dy; const k = `${x},${y}`; if (waitSeen.has(k)) continue;
          if (mapRenderer.isWalkable(x, y)) { waitSeen.add(k); waitTiles.push({ x, y }); }
        }
      }
      if (waitTiles.length === 0) waitTiles.push(entrance);
      const GOD_SEAT = 0;
      const claimSeat = (agent: OfficeAgent): number | null => {
        if (agent.isGod) { seatClaims.add(GOD_SEAT); return GOD_SEAT; }
        for (let i = 1; i < seatTiles.length; i++) if (!seatClaims.has(i)) { seatClaims.add(i); return i; }
        return null;
      };
      const facingForSeat = (t: Tile): "up" | "down" | "left" | "right" => {
        if (!mapRenderer.isWalkable(t.x, t.y - 1)) return "up";
        if (!mapRenderer.isWalkable(t.x, t.y + 1)) return "down";
        if (!mapRenderer.isWalkable(t.x - 1, t.y)) return "left";
        if (!mapRenderer.isWalkable(t.x + 1, t.y)) return "right";
        return "up";
      };

      // Cafeteria
      interface CafeSpot { tile: Tile; facing: Facing; spot: BreakSpot; seated: boolean; partner: number; }
      const cafeSpots: CafeSpot[] = [];
      const faceFurniture = (t: Tile): Facing => {
        if (!mapRenderer.isWalkable(t.x + 1, t.y)) return "right";
        if (!mapRenderer.isWalkable(t.x - 1, t.y)) return "left";
        if (!mapRenderer.isWalkable(t.x, t.y - 1)) return "up";
        return "down";
      };
      for (const name of theme.cafeSeatNames) { const p = mapRenderer.getSpawnPoint(name); if (p) cafeSpots.push({ tile: p, facing: facingForSeat(p), spot: "table", seated: true, partner: -1 }); }
      for (let i = 0; i < cafeSpots.length; i++) for (let j = i + 1; j < cafeSpots.length; j++) {
        const a = cafeSpots[i].tile, b = cafeSpots[j].tile;
        if (a.x === b.x && Math.abs(a.y - b.y) === 2) { cafeSpots[i].partner = j; cafeSpots[j].partner = i; }
      }
      for (const [name, spot] of theme.cafeStands) { const p = mapRenderer.getSpawnPoint(name); if (p) cafeSpots.push({ tile: p, facing: faceFurniture(p), spot, seated: false, partner: -1 }); }
      const cafeTaken: (string | null)[] = new Array(cafeSpots.length).fill(null);
      const agentById = (id: string): OfficeAgent | undefined => agentsRef.current.find((a) => a.id === id);

      // Coffee economy
      const TRAY_TILE: Tile = theme.coffee.trayTile;
      const TRAY_STAND: Tile = theme.coffee.trayStand;
      const MACHINE_STAND: Tile = theme.coffee.machineStand;
      const SINK_TILE: Tile = theme.coffee.sinkTile;
      const SINK_STAND: Tile = theme.coffee.sinkStand;
      const MAX_CUPS = theme.coffee.maxCups;
      let cleanCups = MAX_CUPS;
      const ts0 = mapRenderer.tileSize;
      const trayG = new Graphics(); trayG.eventMode = "none"; trayG.position.set(TRAY_TILE.x * ts0, TRAY_TILE.y * ts0); trayG.zIndex = (TRAY_TILE.y + 1) * ts0; charLayer.addChild(trayG);
      const drawTray = (): void => {
        trayG.clear(); const slots: Array<[number, number]> = [[2, 10], [9, 10], [2, 15], [9, 15]];
        for (let i = 0; i < cleanCups && i < slots.length; i++) paintCup(trayG, slots[i][0], slots[i][1]);
      }; drawTray();
      const sinkG = new Graphics(); sinkG.eventMode = "none"; sinkG.position.set(SINK_TILE.x * ts0, SINK_TILE.y * ts0); sinkG.zIndex = (SINK_TILE.y + 1) * ts0; charLayer.addChild(sinkG);
      let sinkBusy = 0;
      const drawSink = (t: number): void => {
        sinkG.clear();
        sinkG.rect(2, 6, 12, 8).fill(0xb9c2c9); sinkG.rect(3, 7, 10, 6).fill(0x87939d); sinkG.rect(7, 9, 2, 2).fill(0x5d676f);
        sinkG.rect(7, 2, 2, 4).fill(0x6b7680); sinkG.rect(6, 2, 4, 1).fill(0x6b7680);
        if (sinkBusy > 0) {
          sinkG.rect(7, 6, 2, 4).fill({ color: 0x9fd6f0, alpha: 0.9 });
          for (let i = 0; i < 3; i++) { const ph = (t * 1.2 + i / 3) % 1; sinkG.circle(4 + i * 4, 7 - ph * 4, 1).fill({ color: 0xffffff, alpha: 0.7 * (1 - ph) }); }
        }
      }; drawSink(0);
      const machineG = new Graphics(); machineG.eventMode = "none"; machineG.position.set(26 * ts0, 17 * ts0); machineG.zIndex = 19 * ts0; charLayer.addChild(machineG);
      let machineBusy = 0;
      const drawMachine = (t: number): void => {
        machineG.clear(); if (machineBusy <= 0) return;
        for (let i = 0; i < 2; i++) { const ph = (t * 0.9 + i * 0.5) % 1; machineG.rect(6 + i * 3, 2 - Math.round(ph * 5), 1, 1).fill({ color: 0xffffff, alpha: 0.6 * (1 - ph) }); }
      };
      const finishRun = (rt: Runtime): void => {
        rt.run = undefined; const c = rt.character;
        if (c.isCarryingCup()) { rt.cupCarryHome = true; c.hideThought(); c.sitAtDesk(false); }
        else { c.hideThought(); c.startWandering(); }
      };
      const startRunLeg = (rt: Runtime, phase: "toTray" | "toMachine" | "toSink" | "toTrayBack"): void => {
        rt.run = { phase, timer: 0 }; const c = rt.character;
        const dest = phase === "toMachine" ? MACHINE_STAND : phase === "toSink" ? SINK_STAND : TRAY_STAND;
        c.walkToAndThen(dest, () => {
          if (!rt.run || rt.run.phase !== phase) return;
          c.faceDirection("up");
          if (phase === "toTray") {
            if (cleanCups <= 0) { c.showThought(t("office.mugs.empty")); rt.run = { phase: "placing", timer: -1 }; return; }
            cleanCups--; drawTray(); c.setCarryingCup(true); rt.run = { phase: "taking", timer: 0 };
          } else if (phase === "toMachine") { c.showThought(t("office.mugs.brewing")); machineBusy = 2.6; rt.run = { phase: "brewing", timer: 0 }; }
          else if (phase === "toSink") { c.showThought(t("office.mugs.washing")); sinkBusy = 2.4; rt.run = { phase: "washing", timer: 0 }; }
          else { c.setCarryingCup(false); cleanCups = Math.min(MAX_CUPS, cleanCups + 1); drawTray(); rt.run = { phase: "placing", timer: 0 }; }
        });
      };
      const releaseRun = (rt: Runtime): void => { if (!rt.run) return; rt.run = undefined; if (rt.character.isCarryingCup()) rt.cupCarryHome = true; };
      let fxClock = 0;
      const updateCoffeeRuns = (dt: number): void => {
        fxClock += dt;
        if (sinkBusy > 0) { sinkBusy -= dt; drawSink(fxClock); }
        if (machineBusy > 0) { machineBusy -= dt; drawMachine(fxClock); }
        for (const [, rt] of runtimes) {
          const run = rt.run; if (!run) continue; run.timer += dt;
          const c = rt.character;
          switch (run.phase) {
            case "toTray": case "toMachine": case "toSink": case "toTrayBack": if (run.timer > 20) finishRun(rt); break;
            case "taking": if (run.timer >= 0.8) startRunLeg(rt, "toMachine"); break;
            case "brewing": if (run.timer >= 2.6) finishRun(rt); break;
            case "washing": if (run.timer >= 2.4) startRunLeg(rt, "toTrayBack"); break;
            case "placing": if (run.timer >= 0.6) finishRun(rt); break;
          }
        }
      };
      const godDistance = (px: number, py: number): number => {
        const god = agentsRef.current.find((a) => a.isGod);
        const grt = god ? runtimes.get(god.id) : undefined;
        if (!grt) return Infinity;
        const p = grt.character.getPixelPosition();
        return Math.hypot(p.x - px, p.y - py);
      };
      const emitQuip = (id: string, rt: Runtime, spotIdx: number): void => {
        const spot = cafeSpots[spotIdx];
        const character = agentById(id)?.character ?? DEFAULT_CHARACTER;
        const seed = Math.floor(Math.random() * 1e6);
        const p = rt.character.getPixelPosition();
        if (godDistance(p.x, p.y) > 96 && Math.random() < 0.35) { rt.character.showThought(GOSSIP_KEYS[Math.floor(Math.random() * GOSSIP_KEYS.length)]); return; }
        rt.character.showThought(pickSoloLine(character as never, spot.spot, seed));
      };
      const maybePairChat = (id: string, rt: Runtime, spotIdx: number): boolean => {
        const spot = cafeSpots[spotIdx]; if (spot.partner < 0 || !rt.brk) return false;
        const partnerId = cafeTaken[spot.partner]; if (!partnerId) return false;
        const prt = runtimes.get(partnerId); if (!prt?.brk || prt.brk.phase !== "lingering") return false;
        if (rt.brk.chat || rt.brk.chattingWith || prt.brk.chat || prt.brk.chattingWith) return false;
        const character = agentById(id)?.character ?? DEFAULT_CHARACTER;
        const lines = pickExchange(character as never, Math.floor(Math.random() * 1e6));
        rt.brk.chat = { lines, partnerId, idx: 0, beat: 0 }; prt.brk.chattingWith = id; return true;
      };
      const releaseBreak = (rt: Runtime): void => {
        if (!rt.brk) return;
        if (rt.brk.chat) { const p = runtimes.get(rt.brk.chat.partnerId); if (p?.brk) p.brk.chattingWith = undefined; }
        if (rt.brk.chattingWith) { const o = runtimes.get(rt.brk.chattingWith); if (o?.brk) o.brk.chat = undefined; }
        cafeTaken[rt.brk.spotIdx] = null; rt.brk = undefined;
      };
      const endBreak = (id: string, rt: Runtime): void => {
        const arrived = rt.brk?.phase === "lingering"; releaseBreak(rt); rt.character.hideThought();
        const agent = agentById(id);
        if (agent?.isGod) { rt.character.sitAtDesk(true); return; }
        const c = rt.character;
        if (!arrived) { if (c.isCarryingCup()) { rt.cupCarryHome = true; c.sitAtDesk(false); } else c.startWandering(); return; }
        if (c.isCarryingCup()) { if (Math.random() < 0.6) startRunLeg(rt, "toMachine"); else startRunLeg(rt, "toSink"); }
        else if (!c.hasCupOnDesk() && Math.random() < 0.75) startRunLeg(rt, "toTray");
        else c.startWandering();
      };
      const startBreak = (id: string, rt: Runtime): void => {
        const free: number[] = []; const social: number[] = [];
        for (let i = 0; i < cafeSpots.length; i++) { if (cafeTaken[i]) continue; free.push(i); const p = cafeSpots[i].partner; if (p >= 0 && cafeTaken[p]) social.push(i); }
        if (free.length === 0) return;
        const pool = (social.length && Math.random() < 0.55) ? social : free;
        const idx = pool[Math.floor(Math.random() * pool.length)]; const spot = cafeSpots[idx];
        cafeTaken[idx] = id; rt.brk = { spotIdx: idx, phase: "walking", timer: 0, quipTimer: 0 };
        const c = rt.character;
        if (c.hasCupOnDesk()) { c.setCupOnDesk(false); c.setCarryingCup(true); }
        c.walkToAndThen(spot.tile, () => {
          if (!rt.brk || rt.brk.spotIdx !== idx) return;
          if (spot.seated) c.sitInPlace(spot.facing); else { c.setIdle(); c.faceDirection(spot.facing); }
          rt.brk.phase = "lingering"; rt.brk.timer = 8 + Math.random() * 8; rt.brk.quipTimer = 4 + Math.random() * 4;
          if (!maybePairChat(id, rt, idx)) emitQuip(id, rt, idx);
        });
      };
      const breakEligible = (agent: OfficeAgent, rt: Runtime): boolean => {
        if (agent.isGod || rt.brk || rt.err || rt.run || rt.cupCarryHome) return false;
        if (agent.status !== "idle" && agent.status !== "success") return false;
        return !rt.character.isSitting();
      };
      let cafeCooldown = 5;
      const updateCafeteria = (dt: number): void => {
        for (const [id, rt] of runtimes) {
          const b = rt.brk; if (!b) continue;
          if (b.phase === "walking") { b.timer += dt; if (b.timer > 20) endBreak(id, rt); continue; }
          if (b.chat) {
            b.chat.beat -= dt;
            if (b.chat.beat <= 0) {
              if (b.chat.idx < b.chat.lines.length) {
                const speaker = (b.chat.idx % 2 === 0) ? rt : runtimes.get(b.chat.partnerId);
                speaker?.character.showThought(b.chat.lines[b.chat.idx]); b.chat.idx++; b.chat.beat = 2.4;
                b.timer = Math.max(b.timer, 3.5); const prt = runtimes.get(b.chat.partnerId); if (prt?.brk) prt.brk.timer = Math.max(prt.brk.timer, 3.5);
              } else { const prt = runtimes.get(b.chat.partnerId); if (prt?.brk) prt.brk.chattingWith = undefined; b.chat = undefined; }
            }
          } else if (!b.chattingWith) {
            b.quipTimer -= dt;
            if (b.quipTimer <= 0) { b.quipTimer = 4 + Math.random() * 4; emitQuip(id, rt, b.spotIdx); }
            else if (Math.random() < 0.004) maybePairChat(id, rt, b.spotIdx);
          }
          b.timer -= dt; if (b.timer <= 0) endBreak(id, rt);
        }
        cafeCooldown -= dt; if (cafeCooldown > 0) return;
        cafeCooldown = 6 + Math.random() * 6;
        if (cafeTaken.filter(Boolean).length >= 4) return;
        if (Math.random() >= 0.7) return;
        const candidates: Array<[OfficeAgent, Runtime]> = [];
        for (const agent of agentsRef.current) { const rt = runtimes.get(agent.id); if (rt && breakEligible(agent, rt)) candidates.push([agent, rt]); }
        if (candidates.length === 0) return;
        const [agent, rt] = candidates[Math.floor(Math.random() * candidates.length)];
        startBreak(agent.id, rt);
      };

      // Idle errands
      const ERRAND_SPOTS: ErrandSpot[] = theme.errandSpots;
      const errandTaken: (string | null)[] = new Array(ERRAND_SPOTS.length).fill(null);
      const errandFx = new Map<number, Graphics>();
      const fxFor = (idx: number): Graphics => {
        let g = errandFx.get(idx);
        if (!g) {
          const spot = ERRAND_SPOTS[idx];
          g = new Graphics(); g.eventMode = "none"; g.position.set(spot.fx.x * ts0, spot.fx.y * ts0); g.zIndex = (spot.fx.y + 1) * ts0;
          charLayer.addChild(g); errandFx.set(idx, g);
        } return g;
      };
      const drawErrandFx = (kind: ErrandKind, g: Graphics, t: number): void => {
        g.clear();
        if (kind === "window" || kind === "smoke") {
          for (let i = 0; i < 3; i++) { const ph = (t * 0.7 + i / 3) % 1; g.rect(2 + i * 9 - ph * 5, 26 + ph * 16, 7, 1).fill({ color: 0xd8f1f7, alpha: 0.55 * (1 - ph) }); }
        } else if (kind === "dispenser") {
          const ph = (t * 1.6) % 1; g.rect(7, 18 + ph * 6, 1, 3).fill({ color: 0x9fd6f0, alpha: 0.9 * (1 - ph) });
          const bp = (t * 0.9) % 1; g.circle(8, 12 - bp * 6, 1).fill({ color: 0xffffff, alpha: 0.6 * (1 - bp) });
        } else if (kind === "fridge") { const a = 0.16 + 0.05 * Math.sin(t * 5); g.poly([3, 12, 13, 12, 16, 30, 0, 30]).fill({ color: 0xfff2b8, alpha: a }); }
        else if (kind === "shelf") { const ph = (t * 0.5) % 1; g.rect(2 + ph * 24, 4 + (Math.floor(t * 0.5) % 3) * 9, 2, 2).fill({ color: 0xfff7c8, alpha: 0.8 * Math.sin(ph * Math.PI) }); }
        else if (kind === "bin") {
          const ph = (t * 1.0) % 1;
          if (ph < 0.45) { const p = ph / 0.45; const fromX = 18, toX = 8; const x = fromX + (toX - fromX) * p; const y = 2 - Math.sin(p * Math.PI) * 9; g.rect(Math.round(x), Math.round(y), 2, 2).fill({ color: 0xf5f1e6, alpha: 0.95 }); }
        }
      };
      const releaseErrand = (rt: Runtime): void => { if (!rt.err) return; errandTaken[rt.err.idx] = null; errandFx.get(rt.err.idx)?.clear(); rt.err = undefined; rt.character.stopWatering(); rt.character.stopSmoking(); };
      let errCooldown = 18;
      const updateErrands = (dt: number): void => {
        for (const [, rt] of runtimes) {
          const err = rt.err; if (!err) continue; err.timer += dt; const spot = ERRAND_SPOTS[err.idx];
          if (err.phase === "walking") { if (err.timer > 20) { releaseErrand(rt); rt.character.startWandering(); } continue; }
          drawErrandFx(spot.kind, fxFor(err.idx), err.timer);
          if (spot.kind !== "water" && spot.kind !== "smoke" && err.timer >= spot.duration) { releaseErrand(rt); rt.character.hideThought(); rt.character.startWandering(); }
        }
        errCooldown -= dt; if (errCooldown > 0) return;
        errCooldown = 14 + Math.random() * 18; if (Math.random() >= 0.65) return;
        const free = ERRAND_SPOTS.map((_, i) => i).filter((i) => !errandTaken[i]); if (free.length === 0) return;
        const idx = free[Math.floor(Math.random() * free.length)]; const spot = ERRAND_SPOTS[idx];
        let agent: OfficeAgent | undefined; let rt: Runtime | undefined;
        if (spot.godOnly) {
          const god = agentsRef.current.find((a) => a.isGod); const grt = god ? runtimes.get(god.id) : undefined;
          if (!god || !grt || grt.err || grt.brk || (god.status !== "idle" && god.status !== "success") || Math.random() >= 0.5) return;
          agent = god; rt = grt;
        } else {
          const candidates: Array<[OfficeAgent, Runtime]> = [];
          for (const a of agentsRef.current) { const r = runtimes.get(a.id); if (r && breakEligible(a, r)) candidates.push([a, r]); }
          if (candidates.length === 0) return; [agent, rt] = candidates[Math.floor(Math.random() * candidates.length)];
        }
        const c = rt.character; errandTaken[idx] = agent.id; rt.err = { phase: "walking", timer: 0, idx };
        c.walkToAndThen(spot.stand, () => {
          if (!rt!.err || rt!.err.idx !== idx) return;
          rt!.err.phase = "doing"; rt!.err.timer = 0; c.faceDirection(spot.facing);
          const lines = ERRAND_THOUGHTS[spot.kind]; c.showThought(lines[Math.floor(Math.random() * lines.length)]);
          const finish = (): void => { const wasGod = !!agent!.isGod; releaseErrand(rt!); c.hideThought(); if (wasGod) c.sitAtDesk(true); else c.startWandering(); };
          if (spot.kind === "water") c.startWatering(spot.duration, finish);
          else if (spot.kind === "smoke") c.startSmoking(spot.duration, finish);
        });
      };

      // Boss aura
      const lastSuckUp = new Map<string, number>();
      let auraCooldown = 1.5;
      const updateBossAura = (dt: number): void => {
        auraCooldown -= dt; if (auraCooldown > 0) return; auraCooldown = 1.5;
        const god = agentsRef.current.find((a) => a.isGod); const grt = god ? runtimes.get(god.id) : undefined; if (!grt) return;
        const gp = grt.character.getPixelPosition(); const now = Date.now();
        for (const [id, rt] of runtimes) {
          if (id === god!.id) continue; const a = agentById(id); if (!a) continue;
          if (a.status !== "idle" && a.status !== "success") continue;
          if (rt.brk?.chat || rt.brk?.chattingWith) continue;
          const p = rt.character.getPixelPosition();
          if (Math.hypot(p.x - gp.x, p.y - gp.y) > 44) continue;
          if (now - (lastSuckUp.get(id) ?? 0) < 25_000) continue;
          if (Math.random() >= 0.6) continue;
          lastSuckUp.set(id, now);
          const pool = SUCK_UP_KEYS.slice(2); const line = pool[Math.floor(Math.random() * pool.length)];
          rt.character.showThought(line);
        }
      };

      // Desk life
      const updateDeskLife = (dt: number): void => {
        for (const [id, rt] of runtimes) {
          if (rt.cupCarryHome && rt.character.isSittingAtDesk()) {
            rt.cupCarryHome = false; rt.character.setCarryingCup(false); rt.character.setCupOnDesk(true);
            const agent = agentById(id);
            if (agent && !agent.isGod && (agent.status === "idle" || agent.status === "success")) rt.character.startWandering();
          }
          if (rt.screen) { rt.screen.setOn(rt.character.isSittingAtDesk()); rt.screen.update(dt); }
        }
      };

      // Task boards (static — no hiveTasks in RazorGrowth web)
      const BOARD_TILE: Tile = theme.anchors.boards;
      const NOTE_COLORS: Record<string, number> = theme.palette.noteColors;
      const tsB = mapRenderer.tileSize;
      const boardG = new Graphics(); boardG.eventMode = "none"; boardG.position.set(BOARD_TILE.x * tsB + 15, BOARD_TILE.y * tsB); boardG.zIndex = (BOARD_TILE.y + 1) * tsB; charLayer.addChild(boardG);
      const drawCork = (ox: number, header: number, notes: string[]): void => {
        boardG.rect(ox, -8, 30, 22).fill(0x6e5639); boardG.rect(ox + 1, -7, 28, 3).fill(header); boardG.rect(ox + 1, -4, 28, 17).fill(0xc9b083);
        const n = Math.min(notes.length, 12);
        for (let i = 0; i < n; i++) { const x = ox + 3 + (i % 4) * 7; const y = -2 + Math.floor(i / 4) * 5; boardG.rect(x, y, 5, 4).fill(NOTE_COLORS[notes[i]] ?? 0xf2eddc); boardG.rect(x + 2, y, 1, 1).fill(0x4a3b52); }
        if (notes.length > 12) { boardG.rect(ox + 22, 8, 5, 4).fill(0xe8e0c8); boardG.rect(ox + 23, 7, 5, 4).fill(0xf2eddc); }
      };
      const drawTaskBoardStatic = (): void => {
        boardG.clear();
        const todoNotes: string[] = ["todo","todo","todo","todo"]; const blocked: string[] = Math.random() > 0.5 ? ["blocked"] : [];
        drawCork(0, NOTE_COLORS.blocked, blocked); drawCork(34, NOTE_COLORS.todo, todoNotes);
        boardG.rect(68, 6, 14, 4).fill(0xb08d5e); boardG.rect(68, 10, 14, 4).fill(0x8a6f4d); boardG.rect(69, 14, 2, 2).fill(0x6e5639); boardG.rect(79, 14, 2, 2).fill(0x6e5639);
        for (let i = 0; i < 2; i++) boardG.rect(71 + (i % 2), 4 - i * 2, 8, 2).fill({ color: NOTE_COLORS.done, alpha: 1 }).stroke({ color: 0x6e8f6e, width: 0.5 });
      }; drawTaskBoardStatic();
      // Clock (visual only)
      const clockG = new Graphics(); clockG.eventMode = "none"; clockG.position.set(theme.anchors.clock.x * ts0, theme.anchors.clock.y * ts0); clockG.zIndex = 3 * ts0; charLayer.addChild(clockG);
      // simple clock face
      clockG.rect(2, 6, 12, 12).fill(0xf2ead8).stroke({ color: 0x4a3b52, width: 1 }); clockG.rect(7, 8, 2, 4).fill(0x4a3b52); clockG.rect(7, 12, 4, 1).fill(0x4a3b52);
      // ASK ME board (visual only)
      const askG = new Graphics(); askG.eventMode = "none"; askG.position.set(14 * tsB + 25, 10 * tsB); askG.zIndex = 11 * tsB; charLayer.addChild(askG);
      const drawAskBoard = (): void => { askG.clear(); askG.rect(0, -8, 30, 22).fill(0x5b4a6b); askG.rect(1, -7, 28, 3).fill(0xcdb4e8); askG.rect(1, -4, 28, 17).fill(0xc9b083); askG.rect(13, -1, 4, 2).fill({ color: 0x8a755f, alpha: 0.8 }); askG.rect(15, 1, 2, 4).fill({ color: 0x8a755f, alpha: 0.8 }); askG.rect(15, 7, 2, 2).fill({ color: 0x8a755f, alpha: 0.8 }); }; drawAskBoard();

      const ACCENT_MAP: Record<string, number> = { coral: colors.accent.coral, mint: colors.accent.mint, sky: colors.accent.sky, lemon: colors.accent.lemon, lilac: colors.accent.lilac, peach: colors.accent.peach };
      const addCharacter = async (agent: OfficeAgent) => {
        const charName = (theme.cast.byName[agent.character] ? agent.character : theme.cast.defaultCharacter) as string;
        const member = theme.cast.byName[charName];
        const accentNum = ACCENT_MAP[agent.accent ?? "sky"] ?? colors.accent.sky;
        const seatIndex = claimSeat(agent);
        const seatTile: Tile = (seatIndex != null ? seatTiles[seatIndex] : undefined) ?? mapRenderer.getSpawnPoint("entrance") ?? { x: 2, y: 2 };
        const waitTile = waitTiles[(seatIndex ?? 0) % waitTiles.length];
        const frames = await theme.cast.getFrames(charName);
        if (mountIdRef.current !== mountId) return;
        if (!agentsRef.current.some((a) => a.id === agent.id)) { if (seatIndex != null) seatClaims.delete(seatIndex); return; }
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const glowColor = hexToNumber((member as any)?.shirt ?? "#5a6b8c") || accentNum;
        const character = new Character({
          agentId: agent.id,
          mapRenderer,
          frames,
          seatTile,
          seatDirection: facingForSeat(seatTile),
          spawnTile: entrance,
          glowColor,
          onClick: (id) => onSelectAgent?.(id),
        });
        character.show(charLayer);
        const rt: Runtime = { character, seatIndex, waitTile, charName };
        if (mapRenderer.gidAt("furniture-above", seatTile.x, seatTile.y - 2) === theme.monitor.offTopLeftGid) {
          const top = { x: seatTile.x, y: seatTile.y - 2 };
          rt.screen = new DeskScreen(mapRenderer, top, theme.monitor);
          charLayer.addChild(rt.screen.container);
          const ts2 = mapRenderer.tileSize;
          character.setCupSpot({ x: top.x * ts2 + 18, y: top.y * ts2 + 23 });
        }
        runtimes.set(agent.id, rt);
        applyState(agent, rt, true);
      };
      const removeCharacter = (id: string) => {
        const rt = runtimes.get(id); if (!rt) return;
        releaseBreak(rt); releaseErrand(rt); releaseRun(rt);
        if (rt.character.isCarryingCup() || rt.character.hasCupOnDesk()) { if (cleanCups < MAX_CUPS) { cleanCups++; drawTray(); } }
        if (rt.seatIndex != null) seatClaims.delete(rt.seatIndex);
        rt.screen?.destroy(); rt.character.hide(0); setTimeout(() => rt.character.destroy(), 700); runtimes.delete(id);
      };
      const applyState = (agent: OfficeAgent, rt: Runtime, force = false) => {
        const changed = force || rt.prevStatus !== agent.status || rt.prevAction !== agent.action || rt.prevCarrying !== agent.carrying || rt.prevPrompt !== agent.lastPrompt;
        if (!changed) return;
        const wasBusy = rt.prevStatus === "working" || rt.prevStatus === "thinking" || rt.prevStatus === "compacting";
        const isBusy = agent.status === "working" || agent.status === "thinking" || agent.status === "compacting";
        if (isBusy && !wasBusy) rt.busySince = Date.now();
        const finishedWork = !force && !agent.isGod && wasBusy && (agent.status === "idle" || agent.status === "success") && rt.busySince !== undefined && Date.now() - rt.busySince >= CHEER_MIN_BUSY_MS;
        if (!isBusy) rt.busySince = undefined;
        rt.prevStatus = agent.status; rt.prevAction = agent.action; rt.prevCarrying = agent.carrying; rt.prevPrompt = agent.lastPrompt;
        const c = rt.character;
        c.setBaseAlpha(agent.status === "ghost" ? 0.5 : 1);
        if (rt.brk) {
          if (agent.status === "idle" || agent.status === "success") { c.setStatusGlyph(agent.status === "success" ? "success" : "none"); return; }
          releaseBreak(rt);
        }
        if (rt.err) {
          if (agent.status === "idle" || agent.status === "success") { c.setStatusGlyph(agent.status === "success" ? "success" : "none"); return; }
          releaseErrand(rt);
        }
        if (rt.run) {
          if (agent.status === "idle" || agent.status === "success") { c.setStatusGlyph(agent.status === "success" ? "success" : "none"); return; }
          releaseRun(rt);
        }
        switch (agent.status) {
          case "working": case "thinking": c.setStatusGlyph("none"); c.sitAtDesk(true); c.showThought(liveActivity(agent), agent.carrying); break;
          case "waiting": c.setStatusGlyph("none"); c.sitAtDesk(false); c.showThought(liveActivity(agent, t("office.activity.waiting")), agent.carrying); break;
          case "blocked": c.setStatusGlyph("blocked"); c.showThought(liveActivity(agent, t("office.activity.needsYou"))); c.walkToTile(rt.waitTile); break;
          case "compacting": c.setStatusGlyph("compacting"); c.sitAtDesk(true); c.showThought(liveActivity(agent, t("office.activity.compacting"))); break;
          case "looping": c.setStatusGlyph("looping"); c.sitAtDesk(false); c.showThought(liveActivity(agent, t("office.activity.looping"))); break;
          case "success": c.setStatusGlyph("success"); if (agent.isGod) { c.hideThought(); c.sitAtDesk(true); break; } c.startWandering(); if (finishedWork) { c.cheer(); c.showThought(CHEER_KEYS[Math.floor(Math.random() * CHEER_KEYS.length)]); } else c.hideThought(); break;
          case "ghost": c.setStatusGlyph("none"); c.hideThought(); c.setIdle(); break;
          case "idle":
          default: c.setStatusGlyph("none"); if (agent.isGod) { c.sitAtDesk(true); c.showThought(liveActivity(agent, t("office.activity.runningFloor"))); }
            else if (finishedWork) { c.startWandering(); c.cheer(); c.showThought(CHEER_KEYS[Math.floor(Math.random() * CHEER_KEYS.length)]); }
            else { c.startWandering(); c.showThought(liveActivity(agent, t("office.activity.idle"))); }
            break;
        }
      };
      const syncAgents = () => {
        const present = new Set(agentsRef.current.map((a) => a.id));
        for (const id of Array.from(runtimes.keys())) if (!present.has(id)) removeCharacter(id);
        for (const agent of agentsRef.current) { const rt = runtimes.get(agent.id); if (!rt) void addCharacter(agent); else applyState(agent, rt); }
        // camera follow selected
        if (selectedId) { const rt = runtimes.get(selectedId); if (rt) { const p = rt.character.getPixelPosition(); camera.nudgeToward(p.x, p.y); } }
      };
      syncAgents();
      const syncInterval = setInterval(syncAgents, 400);

      // Demo envelopes: occasionally fly a random envelope between two agents
      const spawnRandomEnvelope = () => {
        if (agentsRef.current.length < 2 || Math.random() > 0.22 || envelopes.length >= MAX_ENVELOPES) return;
        const ids = agentsRef.current.map((a) => a.id);
        const from = ids[Math.floor(Math.random() * ids.length)];
        let to = from; for (let i = 0; i < 6 && to === from; i++) to = ids[Math.floor(Math.random() * ids.length)];
        if (to === from) return;
        const fromRt = runtimes.get(from), toRt = runtimes.get(to);
        if (!fromRt || !toRt) return;
        const acts: MessageAct[] = ["request","inform","propose","query","agree"];
        const act = acts[Math.floor(Math.random() * acts.length)];
        const fromPos = fromRt.character.getPixelPosition();
        const toPos = toRt.character.getPixelPosition();
        const env = new MessageEnvelope(fromPos, toPos, act, false);
        charLayer.addChild(env.container); envelopes.push(env);
      };
      const envelopeTimer = setInterval(spawnRandomEnvelope, 2400);

      const resolveBubbleOverlaps = () => {
        const items: Array<{ rt: Runtime; x: number; y: number; w: number; h: number }> = [];
        for (const rt of runtimes.values()) { const lay = rt.character.getThoughtLayout(); if (lay) items.push({ rt, ...lay }); }
        if (items.length < 2) { for (const it of items) it.rt.character.setThoughtLift(0); return; }
        items.sort((a, b) => (b.y + b.h) - (a.y + a.h) || a.x - b.x);
        const placed: Array<{ x: number; y: number; w: number; h: number }> = [];
        const pad = 2;
        for (const it of items) {
          let y = it.y; let moved = true, guard = 0;
          while (moved && guard++ < 12) {
            moved = false;
            for (const p of placed) { const overlapX = it.x < p.x + p.w + pad && it.x + it.w + pad > p.x; const overlapY = y < p.y + p.h + pad && y + it.h + pad > p.y; if (overlapX && overlapY) { y = p.y - it.h - pad; moved = true; } }
          }
          placed.push({ x: it.x, y, w: it.w, h: it.h }); it.rt.character.setThoughtLift(it.y - y);
        }
      };

      const onTick = (ticker: Ticker) => {
        const dt = ticker.deltaMS / 1000;
        camera.update(dt);
        const zoom = world.scale.x;
        for (const rt of runtimes.values()) { rt.character.setBubbleZoom(zoom); rt.character.update(dt); }
        updateCafeteria(dt); updateCoffeeRuns(dt); updateErrands(dt); updateBossAura(dt); updateDeskLife(dt);
        resolveBubbleOverlaps();
        for (let i = envelopes.length - 1; i >= 0; i--) if (envelopes[i].update(dt)) { envelopes[i].destroy(); envelopes.splice(i, 1); }
      };
      app.ticker.add(onTick);
      if (pausedRef.current) app.ticker.stop();

      const resize = new ResizeObserver((entries) => {
        for (const e of entries) { const { width, height } = e.contentRect; if (width === 0 || height === 0) continue; app.renderer?.resize(width, height); camera.setViewSize(width, height); }
      });
      resize.observe(host);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (app as any).__resize = resize;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (app as any).__syncInterval = syncInterval;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (app as any).__envelopeTimer = envelopeTimer;
      initRetriesRef.current = 0;
    };
    init().catch((err: unknown) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const e = err as any;
      if (mountIdRef.current !== mountId) return;
      const plan = planInitFailure(e, initRetriesRef.current);
      if (plan.action === "retry") {
        initRetriesRef.current = plan.attempt;
        setTimeout(() => { if (mountIdRef.current === mountId) setGlGeneration((n) => n + 1); }, plan.delayMs);
        return;
      }
      if (plan.action === "give-up") { host.appendChild(floorNote("The office floor could not get a GPU context.\n\nToo many contexts are using the GPU at once.\nClose a few tabs, or restart.")); return; }
      host.appendChild(floorNote("OfficeFloor failed to start:\n" + (e?.stack || e?.message || String(e))));
    });
    return () => {
      mountIdRef.current++;
      const a = appRef.current;
      if (a) {
        try { (a as unknown as Record<string, { disconnect?: () => void }>).__resize?.disconnect?.(); } catch {}
        try { clearInterval((a as unknown as Record<string, number>).__syncInterval); } catch {}
        try { clearInterval((a as unknown as Record<string, number>).__envelopeTimer); } catch {}
        try { (a as unknown as Record<string, { (): void } >).__glRecovery?.(); } catch {}
        safeDestroy(a);
      }
      appRef.current = null;
      while (host.firstChild) host.removeChild(host.firstChild);
    };
  }, [glGeneration, selectedId]);

  // Keep selectedId ref for syncAgents closure — already handled via deps above

  return <div ref={hostRef} className="office-host" style={{ width: "100%", height: "100%", minHeight: 560 }} />;
}

function floorNote(text: string): HTMLDivElement {
  const note = document.createElement("div");
  note.style.cssText = "position:absolute;inset:0;display:flex;align-items:center;justify-content:center;padding:24px;color:#ffd0b5;font-family:monospace;font-size:13px;text-align:center;white-space:pre-wrap;";
  note.textContent = text;
  return note;
}
function hexNum(n: number): number { return n; }
function safeDestroy(app: Application) { try { app.ticker?.stop(); } catch {} try { app.destroy(true, { children: true }); } catch {} }
void hexNum;
