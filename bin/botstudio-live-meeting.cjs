#!/usr/bin/env node
'use strict';

/**
 * WeChat Bot 外部卡片触发桥接器（轻量薄壳）
 * 核心参会逻辑（免重复入会探测、非阻塞字幕/元宝笔记开启、playbook 演示、
 * 120ms 打断问答与方舟纪要回写）全部委托给 Bot Studio 已安装的 app.asar。
 */

const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { spawn } = require('node:child_process');

const ASAR = process.env.BOT_STUDIO_ASAR_PATH || '/Users/mac/Applications/Bot Studio.app/Contents/Resources/app.asar';
const OPENBOT_DIR = process.env.BOT_STUDIO_USER_DATA_DIR || '/Users/mac/Library/Application Support/openbot';
const DEFAULT_DATA_DIR = process.env.WECHAT_BOT_DATA_DIR || '/Users/mac/Library/Application Support/WeChatBot';

function parseCliArgs(argv) {
  const out = { flags: new Set(), options: {} };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith('--')) continue;
    const eq = a.indexOf('=');
    if (eq > 2) {
      out.options[a.slice(2, eq)] = a.slice(eq + 1);
      continue;
    }
    const key = a.slice(2);
    const next = argv[i + 1];
    if (next && !next.startsWith('--')) {
      out.options[key] = next;
      i++;
    } else {
      out.flags.add(key);
    }
  }
  return out;
}

const args = parseCliArgs(process.argv);
const meetingCode = String(args.options['meeting-code'] || '').replace(/\s+/g, '');
const targetContact = String(args.options['contact'] || '心安');
const baseAgenda = String(args.options['agenda'] || '在腾讯会议中自我介绍、现场演示 Bot Studio 使用，并与主持人交流讨论').trim();
const stateFile = args.options['state-file'] || path.join(DEFAULT_DATA_DIR, 'logs', 'meeting_copilot_state.json');
const pidFile = path.join(DEFAULT_DATA_DIR, 'logs', 'botstudio_live_meeting.pid');
const preferredOutputUid = args.options['device'] || 'OrayVirtualAudioDevice_UID';
const httpPort = Number(args.options['port'] || 18799);
const autoDiscuss = args.options['auto-discuss'] !== '0';
const writeRecapOnStop = args.options['write-recap'] !== '0';

fs.mkdirSync(path.dirname(stateFile), { recursive: true });
fs.writeFileSync(pidFile, String(process.pid), 'utf8');

const { createExternalMeetingManager } = require(path.join(ASAR, 'src/external-meeting-session'));
const { PRESENTER_BOT_ID, PRESENTER_BOT_NAME, ensurePresenterBotInState } = require(path.join(ASAR, 'src/seeduplex-voice'));
const { createVoiceSpeechProvider } = require(path.join(ASAR, 'src/voice-speech-provider'));
const { HardwareAudio } = require(path.join(ASAR, 'src/hardware-audio'));
const contextMod = require(path.join(ASAR, 'src/context'));

const requestedBotId = String(args.options['bot-id'] || PRESENTER_BOT_ID).trim();

function loadOpenBotProfileAndBots() {
  const cfg = JSON.parse(fs.readFileSync(path.join(OPENBOT_DIR, 'config.json'), 'utf8'));
  const botsJson = JSON.parse(fs.readFileSync(path.join(OPENBOT_DIR, 'bots.json'), 'utf8'));
  const profile = (cfg.profiles || []).find(p => {
    try { return p && p.baseUrl && new URL(p.baseUrl).hostname === 'token-plan.cn-beijing.maas.aliyuncs.com' && p.apiKey; }
    catch (_) { return false; }
  }) || (cfg.profiles || []).find(p => p && p.baseUrl && p.apiKey) || null;
  const ensured = ensurePresenterBotInState(botsJson);
  return { profile, state: ensured.state };
}

function loadWeChatMemoryContext() {
  try {
    const soulPath = path.join(DEFAULT_DATA_DIR, 'config', 'soul_memories.json');
    if (!fs.existsSync(soulPath)) return '';
    const d = JSON.parse(fs.readFileSync(soulPath, 'utf8'));
    const prof = (d.contactProfiles || {})[targetContact] || {};
    const live = ((d.liveMemories || {})[targetContact] || []).slice(-6);
    const rolling = (d.rollingSummaries || {})[targetContact] || '';
    const bits = [];
    if (rolling) bits.push(`近期摘要：${rolling}`);
    if (live.length) bits.push(`最近沟通细节：${live.map(x => x.summary || x.fact || '').filter(Boolean).join('；')}`);
    if (prof.coreSummary) bits.push(`联系人印象：${prof.coreSummary}`);
    return bits.join('\n').slice(0, 600);
  } catch (_) {
    return '';
  }
}

const { profile, state: initialBotState } = loadOpenBotProfileAndBots();
const wechatMem = loadWeChatMemoryContext();
const combinedAgenda = wechatMem ? `${baseAgenda}\n微信背景：${wechatMem.slice(0, 260)}` : baseAgenda;

let localState = initialBotState;
const activeBot = (localState.bots || []).find(b => b && b.id === requestedBotId)
  || (localState.bots || []).find(b => b && b.id === PRESENTER_BOT_ID)
  || localState.bots?.[0];

async function callRealLlm(messages, { signal } = {}) {
  if (!profile) return '收到你的问题了，我继续顺着当前页面演示和说明。';
  const endpoint = profile.baseUrl.replace(/\/$/, '') + '/chat/completions';
  const res = await fetch(endpoint, {
    method: 'POST',
    signal,
    headers: {
      'Content-Type': 'application/json',
      Authorization: 'Bearer ' + profile.apiKey
    },
    body: JSON.stringify({
      model: activeBot?.model || 'qwen3.7-plus',
      messages,
      temperature: 0.35,
      max_tokens: 220,
      enable_thinking: false
    })
  });
  const data = await res.json();
  if (!res.ok) throw new Error('LLM HTTP ' + res.status);
  return data.choices?.[0]?.message?.content?.trim() || '';
}

const liveState = {
  ok: true,
  pid: process.pid,
  bridgeMode: 'botstudio-asar-wrapper',
  botId: activeBot?.id || PRESENTER_BOT_ID,
  botName: activeBot?.name || PRESENTER_BOT_NAME,
  meetingCode,
  contact: targetContact,
  agenda: combinedAgenda,
  autoDiscuss,
  demoLocked: false,
  status: 'starting',
  phase: 'starting',
  mode: 'participant',
  outputDeviceUid: preferredOutputUid,
  alreadyInMeeting: false,
  tmSetup: null,
  spokenReplies: [],
  transcripts: [],
  latestCue: null,
  recapWritten: false,
  lastError: null,
  updatedAt: new Date().toISOString()
};

function flushState() {
  liveState.updatedAt = new Date().toISOString();
  try {
    fs.writeFileSync(stateFile, JSON.stringify(liveState, null, 2), 'utf8');
  } catch (_) {}
}

flushState();

function isValidUtterance(text) {
  const stripped = String(text || '').replace(/[\s，。！？、,.!?:;"'()（）~～…]/g, '');
  if ([...stripped].length < 2) return false;
  if (!/[\u4e00-\u9fffA-Za-z0-9]{2,}/.test(stripped)) return false;
  return true;
}

(async () => {
  const readyRuntimeStub = Object.assign(new EventEmitter(), {
    snapshot: () => ({ provider: 'mlx-local', phase: 'ready', error: null, port: 18794 }),
    start: async () => ({ ok: true }),
    close: async () => ({ ok: true })
  });
  const speechProvider = createVoiceSpeechProvider({
    config: { port: 18794, voice: 'Vivian' },
    createRuntime: () => readyRuntimeStub
  });
  await speechProvider.start({ port: 18794, voice: 'Vivian' });

  const activeAborts = new Map();
  let lastTtsFinishedAt = 0;
  let speakingLock = false;

  const wrappedSpeechProvider = {
    async playToDevice(text, opts = {}) {
      speakingLock = true;
      liveState.phase = 'speaking';
      flushState();
      try {
        const res = await speechProvider.playToDevice(text, {
          voice: 'Vivian',
          deviceUid: liveState.outputDeviceUid || preferredOutputUid,
          ...opts,
          readTtsProfile: () => profile
        });
        lastTtsFinishedAt = Date.now();
        liveState.spokenReplies.push({
          text,
          playedBytes: res?.playedBytes || 0,
          at: new Date().toISOString(),
          deviceUid: opts?.deviceUid || liveState.outputDeviceUid || preferredOutputUid
        });
        if (liveState.spokenReplies.length > 40) liveState.spokenReplies.shift();
        liveState.lastError = null;
        flushState();
        return res;
      } catch (err) {
        lastTtsFinishedAt = Date.now();
        liveState.lastError = 'tts_play_failed: ' + (err?.message || err);
        flushState();
        throw err;
      } finally {
        speakingLock = false;
        if (liveState.phase === 'speaking') {
          liveState.phase = 'listening';
          flushState();
        }
      }
    },
    close: () => speechProvider.close()
  };

  const audioFactory = () => {
    const a = new HardwareAudio();
    const origEmit = a.emit.bind(a);
    a.emit = (evt, payload, ...rest) => {
      if (evt === 'transcript' && payload && payload.text) {
        const clean = String(payload.text).trim();
        const sinceTts = Date.now() - lastTtsFinishedAt;
        if (liveState.demoLocked || speakingLock || liveState.phase === 'thinking' || sinceTts < 2500) {
          return false;
        }
        if (!isValidUtterance(clean)) return false;
        if (autoDiscuss) payload = { ...payload, addressed: true };
      }
      return origEmit(evt, payload, ...rest);
    };
    return a;
  };

  const manager = createExternalMeetingManager({
    getState: () => localState,
    saveState: async next => {
      localState = next;
      try {
        const recapDir = path.join(OPENBOT_DIR, 'meeting-recaps');
        fs.mkdirSync(recapDir, { recursive: true });
        const lastRecap = (next.bots || [])
          .flatMap(b => (b?.messages || []).map(m => ({ botId: b.id, botName: b.name, ...m })))
          .filter(m => m.kind === 'meeting-recap')
          .at(-1);
        if (lastRecap) {
          fs.writeFileSync(path.join(recapDir, `wechat_trigger_recap_${Date.now()}.json`), JSON.stringify(lastRecap, null, 2));
          liveState.recapWritten = true;
        }
      } catch (_) {}
      flushState();
      return { ok: true };
    },
    prepareMessages: bot => contextMod.assemble(bot, {}),
    acceptChat: async (eventSink, req, guard, observeReceipt) => {
      const controller = new AbortController();
      activeAborts.set(req.streamId, controller);
      const completion = (async () => {
        try {
          guard?.();
          const text = await callRealLlm(req.messages, { signal: controller.signal });
          guard?.();
          eventSink?.sender?.send?.('llm:done', { streamId: req.streamId, text });
          return { ok: true, text };
        } finally {
          activeAborts.delete(req.streamId);
        }
      })();
      observeReceipt?.({ ok: true, completion }, completion);
      return { ok: true };
    },
    stopChat: async streamId => {
      activeAborts.get(streamId)?.abort('barge-in');
    },
    inputArbiter: null,
    speechProvider: wrappedSpeechProvider,
    readTtsProfile: () => profile,
    userDataDir: OPENBOT_DIR,
    audioFactory,
    spawnBridge: (cmd, bridgeArgs, opts) => spawn(cmd, bridgeArgs, opts)
  });

  manager.on('changed', snap => {
    if (!speakingLock) liveState.phase = snap.phase;
    liveState.botId = snap.botId || liveState.botId;
    liveState.botName = snap.botName || liveState.botName;
    liveState.mode = snap.mode;
    liveState.asrBackend = snap.asrBackend;
    liveState.transcripts = snap.transcripts || [];
    liveState.latestCue = snap.latestCue || null;
    if (snap.lastError) liveState.lastError = snap.lastError;
    if (snap.phase === 'speaking') lastTtsFinishedAt = Date.now();
    flushState();
  });

  const attachResult = await manager.joinOrAttachTencentMeeting({
    botId: activeBot?.id || PRESENTER_BOT_ID,
    meetingCode,
    mode: 'participant',
    outputDeviceUid: preferredOutputUid,
    agenda: combinedAgenda,
    wantSubtitles: true,
    wantYuanbao: true
  });
  liveState.alreadyInMeeting = Boolean(attachResult.alreadyInMeeting);
  liveState.outputDeviceUid = attachResult.outputDeviceUid || preferredOutputUid;
  liveState.tmSetup = attachResult.setup || null;
  liveState.status = 'in_meeting_active';
  flushState();

  const server = http.createServer(async (req, res) => {
    const writeJson = (code, obj) => {
      res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify(obj));
    };
    if (req.method === 'GET' && req.url === '/status') {
      return writeJson(200, { ...liveState, session: manager.snapshot() });
    }
    let raw = '';
    for await (const chunk of req) raw += chunk.toString('utf8');
    let body = {};
    try { body = JSON.parse(raw || '{}'); } catch (_) {}

    if (req.method === 'POST' && req.url === '/demo-lock') {
      liveState.demoLocked = Boolean(body.locked);
      flushState();
      return writeJson(200, { ok: true, demoLocked: liveState.demoLocked });
    }
    if (req.method === 'POST' && req.url === '/speak') {
      const text = String(body.text || '').trim();
      if (!text) return writeJson(400, { ok: false, error: 'missing_text' });
      try {
        const result = await wrappedSpeechProvider.playToDevice(text, {
          voice: body.voice === 'Ryan' ? 'Ryan' : 'Vivian',
          deviceUid: liveState.outputDeviceUid
        });
        return writeJson(200, { ok: true, text, playedBytes: result?.playedBytes || 0, deviceUid: liveState.outputDeviceUid });
      } catch (err) {
        return writeJson(500, { ok: false, error: err?.message || String(err) });
      }
    }
    if (req.method === 'POST' && req.url === '/demo') {
      try {
        const result = await manager.startPlaybookDemo(body);
        return writeJson(200, result);
      } catch (err) {
        return writeJson(500, { ok: false, error: err?.message || String(err) });
      }
    }
    if (req.method === 'POST' && req.url === '/qa') {
      try {
        const result = await manager.interruptDemoWithQuestion(body.question || '');
        return writeJson(200, result);
      } catch (err) {
        return writeJson(500, { ok: false, error: err?.message || String(err) });
      }
    }
    if (req.method === 'POST' && req.url === '/switch-bot') {
      try {
        return writeJson(200, manager.switchBot(body.botId || PRESENTER_BOT_ID));
      } catch (err) {
        return writeJson(400, { ok: false, error: err?.message || String(err) });
      }
    }
    if (req.method === 'POST' && req.url === '/stop') {
      const stopRes = await manager.stop({ writeRecap: body.writeRecap !== false });
      writeJson(200, stopRes);
      setTimeout(() => shutdown(false), 80);
      return;
    }
    writeJson(404, { ok: false, error: 'not_found' });
  });

  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(httpPort, '127.0.0.1', resolve);
  });
  liveState.httpPort = httpPort;
  flushState();

  let shuttingDown = false;
  async function shutdown(doStop = true) {
    if (shuttingDown) return;
    shuttingDown = true;
    try { server.close(); } catch (_) {}
    if (doStop) {
      try { await manager?.stop?.({ writeRecap: writeRecapOnStop }); } catch (_) {}
    }
    try { await manager?.close?.(); } catch (_) {}
    try { await speechProvider?.close?.(); } catch (_) {}
    try { if (fs.existsSync(pidFile) && fs.readFileSync(pidFile, 'utf8').trim() === String(process.pid)) fs.unlinkSync(pidFile); } catch (_) {}
    process.exit(0);
  }
  process.on('SIGINT', () => shutdown(true));
  process.on('SIGTERM', () => shutdown(true));
})().catch(err => {
  liveState.status = 'error';
  liveState.lastError = err?.stack || err?.message || String(err);
  flushState();
  console.error('BOTSTUDIO_LIVE_MEETING_FAILED:', err);
  process.exit(1);
});
