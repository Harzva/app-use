#!/usr/bin/env node
'use strict';

/**
 * WeChat / WeCom VoIP 实时语音通话伴侣守护进程
 * - 使用 Bot Studio 的 app-audio-bridge + HardwareAudio (sherpa ASR) + 18794/Ark 语音问答
 * - 动态切换 macOS 默认麦克风：AI 说话期间切至 OrayVirtualAudioDevice_UID 注入语音，
 *   停顿/结束时立刻切回原硬件麦克风（FF-Camera），进程退出必恢复。
 */

const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { promisify } = require('node:util');
const { execFile, execFileSync, spawn } = require('node:child_process');
const execFileAsync = promisify(execFile);

const ASAR = process.env.BOT_STUDIO_ASAR_PATH || '/Users/mac/Applications/Bot Studio.app/Contents/Resources/app.asar';
const OPENBOT_DIR = process.env.BOT_STUDIO_USER_DATA_DIR || '/Users/mac/Library/Application Support/openbot';
const DEFAULT_DATA_DIR = process.env.WECHAT_BOT_DATA_DIR || '/Users/mac/Library/Application Support/WeChatBot';
const AUDIO_BRIDGE = path.join(ASAR, '..', 'app.asar.unpacked', 'native', 'app-audio-bridge');

function resolveVisionAx() {
  const candidates = [
    process.env.WECHAT_VISION_AX_BIN,
    path.resolve(__dirname, 'wechat-vision-ax'),
    '/Users/mac/Applications/WeChat Bot.app/Contents/MacOS/wechat-vision-ax',
    '/Volumes/SanDisk/Builds/WeChatBot/draft-status.cUlVkiJS/source/bin/wechat-vision-ax'
  ].filter(Boolean);
  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  throw new Error('wechat-vision-ax binary not found');
}

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
const appFilter = String(args.options.app || 'wechat').toLowerCase();
const targetContact = String(args.options.target || '').trim();
const greetingText = String(args.options.greeting || (targetContact ? `喂${targetContact}你好，我是安晓心，语音已经接通啦，听得清我说话吗？` : '喂你好，我是安晓心，语音已经接通啦，听得到我说话吗？')).trim();
const customInstructions = String(args.options.instructions || '').trim();
const virtualMicUid = String(args.options['virtual-mic'] || 'OrayVirtualAudioDevice_UID').trim();
const idleInputUid = String(args.options['idle-input-uid'] || '').trim();
const httpPort = Number(args.options.port || 18797);
const assumeConnected = args.flags.has('assume-connected') || args.options['assume-connected'] === '1';

const logsDir = path.join(DEFAULT_DATA_DIR, 'logs');
fs.mkdirSync(logsDir, { recursive: true });
const stateFile = args.options['state-file'] || path.join(logsDir, 'voip_call_state.json');
const pidFile = path.join(logsDir, 'wechat_voip_call.pid');
const savedMicFile = path.join(logsDir, 'voip_saved_input_device.json');
const summariesFile = path.join(logsDir, 'voip_call_summaries.json');
fs.writeFileSync(pidFile, String(process.pid), 'utf8');

const visionBin = resolveVisionAx();
const { HardwareAudio } = require(path.join(ASAR, 'src/hardware-audio'));
const { summarizeVoiceSessionWithArk, readArkKey, ARK_ENDPOINT, ARK_CHAT_MODEL } = require(path.join(ASAR, 'src/seeduplex-voice'));

function runVisionJson(cmdArgs, timeoutMs = 6000) {
  try {
    const raw = execFileSync(visionBin, cmdArgs, {
      encoding: 'utf8',
      timeout: timeoutMs,
      env: { ...process.env, HOME: '/Users/mac' }
    });
    return JSON.parse(String(raw || '{}').trim() || '{}');
  } catch (err) {
    return { ok: false, error: err?.message || String(err) };
  }
}

async function runVisionJsonAsync(cmdArgs, timeoutMs = 10000) {
  try {
    const { stdout } = await execFileAsync(visionBin, cmdArgs, {
      encoding: 'utf8',
      timeout: timeoutMs,
      env: { ...process.env, HOME: '/Users/mac' }
    });
    return JSON.parse(String(stdout || '{}').trim() || '{}');
  } catch (err) {
    return { ok: false, error: err?.message || String(err) };
  }
}

function saveAndSwitchInput(uid) {
  return runVisionJson(['set-input-device', '--uid', uid, '--save-file', savedMicFile], 4000);
}

async function saveAndSwitchInputAsync(uid) {
  return runVisionJsonAsync(['set-input-device', '--uid', uid, '--save-file', savedMicFile], 4000);
}

function restoreIdleInput() {
  if (idleInputUid) {
    return runVisionJson(['set-input-device', '--uid', idleInputUid, '--save-file', savedMicFile], 4000);
  }
  return runVisionJson(['set-input-device', '--restore', '--save-file', savedMicFile], 4000);
}

async function restoreIdleInputAsync() {
  if (idleInputUid) {
    return runVisionJsonAsync(['set-input-device', '--uid', idleInputUid, '--save-file', savedMicFile], 4000);
  }
  return runVisionJsonAsync(['set-input-device', '--restore', '--save-file', savedMicFile], 4000);
}

function restoreOriginalHardwareInput() {
  try {
    return runVisionJson(['set-input-device', '--restore', '--save-file', savedMicFile], 4000);
  } catch (_) {
    return { ok: false };
  }
}

function loadOpenBotProfile() {
  try {
    const cfg = JSON.parse(fs.readFileSync(path.join(OPENBOT_DIR, 'config.json'), 'utf8'));
    return (cfg.profiles || []).find(p => {
      try { return p && p.baseUrl && new URL(p.baseUrl).hostname === 'token-plan.cn-beijing.maas.aliyuncs.com' && p.apiKey; }
      catch (_) { return false; }
    }) || (cfg.profiles || []).find(p => p && p.baseUrl && p.apiKey) || null;
  } catch (_) {
    return null;
  }
}

const openbotProfile = loadOpenBotProfile();

async function synthesizePcm24k(text) {
  const clean = String(text || '').trim();
  if (!clean) return Buffer.alloc(0);
  try {
    const controller = new AbortController();
    const t = setTimeout(() => controller.abort(), 18000);
    const res = await fetch('http://127.0.0.1:18794/v1/audio/speech', {
      method: 'POST',
      signal: controller.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: 'mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit',
        voice: 'Vivian',
        input: clean,
        response_format: 'pcm'
      })
    });
    clearTimeout(t);
    if (res.ok) {
      const ab = await res.arrayBuffer();
      const buf = Buffer.from(ab);
      if (buf.length >= 2400) return buf;
    }
  } catch (_) {}

  // Audible 24kHz harmonic fallback so caller always hears prompt even if local MLX is cold
  const samples = Math.min(24000 * 3, Math.max(12000, [...clean].length * 1600));
  const buf = Buffer.alloc(samples * 2);
  for (let i = 0; i < samples; i++) {
    const env = Math.sin(Math.PI * (i / samples)) * 0.25;
    const f = 260 + 45 * Math.sin(i / 4800);
    buf.writeInt16LE(Math.round(Math.sin(2 * Math.PI * f * (i / 24000)) * env * 32767), i * 2);
  }
  return buf;
}

async function generateCallReply(userText, history) {
  const sys = [
    customInstructions || `你是安晓心，正在和${targetContact || '好友'}通微信语音电话。`,
    '请像真人同事通电话那样简短自然回应，每次 15~55 个汉字，绝不输出 Markdown、编号或括号备注。'
  ].join('\n');
  const msgs = [
    { role: 'system', content: sys },
    ...history.slice(-10),
    { role: 'user', content: userText }
  ];

  if (openbotProfile) {
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 7500);
      const res = await fetch(openbotProfile.baseUrl.replace(/\/$/, '') + '/chat/completions', {
        method: 'POST',
        signal: ctrl.signal,
        headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + openbotProfile.apiKey },
        body: JSON.stringify({ model: 'qwen3.7-plus', messages: msgs, temperature: 0.35, max_tokens: 160, enable_thinking: false })
      });
      clearTimeout(t);
      if (res.ok) {
        const data = await res.json();
        const txt = data?.choices?.[0]?.message?.content?.trim();
        if (txt) return txt;
      }
    } catch (_) {}
  }

  const arkKey = await readArkKey({ userDataDir: OPENBOT_DIR });
  if (arkKey) {
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 7500);
      const res = await fetch(ARK_ENDPOINT, {
        method: 'POST',
        signal: ctrl.signal,
        headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + arkKey },
        body: JSON.stringify({ model: ARK_CHAT_MODEL, messages: msgs, temperature: 0.35, max_tokens: 160 })
      });
      clearTimeout(t);
      if (res.ok) {
        const data = await res.json();
        const txt = data?.choices?.[0]?.message?.content?.trim();
        if (txt) return txt;
      }
    } catch (_) {}
  }

  return `收到，你说的「${String(userText).slice(0, 20)}」我记下了，还有什么需要我马上处理吗？`;
}

const liveState = {
  ok: true,
  pid: process.pid,
  app: appFilter,
  target: targetContact,
  virtualMicUid,
  phase: assumeConnected ? 'connected' : 'dialing',
  callStatus: assumeConnected ? 'connected' : 'dialing',
  connectedAt: assumeConnected ? new Date().toISOString() : null,
  greeted: false,
  speaking: false,
  bargeInCount: 0,
  transcripts: [],
  spokenReplies: [],
  lastError: null,
  updatedAt: new Date().toISOString()
};

function flushState() {
  liveState.updatedAt = new Date().toISOString();
  try { fs.writeFileSync(stateFile, JSON.stringify(liveState, null, 2), 'utf8'); } catch (_) {}
}
flushState();

let shuttingDown = false;
let activePlayAbort = null;
let lastSpokenAt = 0;
let bridgeCaptureChild = null;
let hardwareAudio = null;
let httpServer = null;
let pollTimer = null;
const conversationHistory = [];
let seenConnected = assumeConnected;
let sameHostDualCall = false;
const startedAt = Date.now();
let seenDialing = false;
let idlePollsAfterDialing = 0;

async function playToVirtualMic(text, { signal, precomputedPcm } = {}) {
  const pcm = precomputedPcm && precomputedPcm.length ? precomputedPcm : await synthesizePcm24k(text);
  if (!pcm.length || shuttingDown || signal?.aborted) return { ok: false, skipped: true };

  liveState.speaking = true;
  flushState();
  await saveAndSwitchInputAsync(virtualMicUid);
  await new Promise(r => setTimeout(r, 120));

  const playCfg = JSON.stringify({ mode: 'play', deviceUid: virtualMicUid, sampleRate: 24000 });
  const child = spawn(AUDIO_BRIDGE, [playCfg], { stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true });
  const localAbort = new AbortController();
  activePlayAbort = localAbort;
  const combinedAbort = signal
    ? () => { try { localAbort.abort(); } catch (_) {} try { child.kill('SIGTERM'); } catch (_) {} }
    : null;
  signal?.addEventListener?.('abort', combinedAbort, { once: true });

  let playedBytes = 0;
  let aborted = false;
  const maxWaitMs = Math.min(35000, Math.ceil(pcm.length / 48) + 6000);
  try {
    await new Promise(resolve => {
      let settled = false;
      const done = () => {
        if (settled) return;
        settled = true;
        clearTimeout(guardTimer);
        resolve();
      };
      const guardTimer = setTimeout(() => {
        aborted = true;
        try { child.kill('SIGTERM'); } catch (_) {}
        done();
      }, maxWaitMs);
      let stdoutBuf = '';
      child.stdout?.on('data', d => { stdoutBuf += d.toString('utf8'); });
      child.once('error', () => { aborted = true; done(); });
      child.once('close', code => {
        try {
          const parsed = JSON.parse(stdoutBuf.trim() || '{}');
          if (Number(parsed.playedBytes) > 0) playedBytes = Number(parsed.playedBytes);
        } catch (_) {}
        if (!aborted && code === 0 && playedBytes === 0) playedBytes = pcm.length;
        done();
      });
      localAbort.signal.addEventListener('abort', () => {
        aborted = true;
        try { child.kill('SIGTERM'); } catch (_) {}
        done();
      }, { once: true });
      try {
        child.stdin.end(pcm);
      } catch (_) {
        aborted = true;
        done();
      }
    });
  } finally {
    signal?.removeEventListener?.('abort', combinedAbort);
    if (activePlayAbort === localAbort) activePlayAbort = null;
    lastSpokenAt = Date.now();
    await new Promise(r => setTimeout(r, 150));
    await restoreIdleInputAsync();
    liveState.speaking = false;
    if (!aborted && playedBytes > 0) {
      liveState.spokenReplies.push({ text, bytes: playedBytes, at: new Date().toISOString() });
      liveState.transcripts.push({ role: 'assistant', text, at: new Date().toISOString() });
      conversationHistory.push({ role: 'assistant', content: text });
    }
    console.error(`[voip-play] aborted=${aborted} bytes=${playedBytes} text=${text.slice(0, 32)}`);
    flushState();
  }
  return { ok: !aborted, playedBytes, aborted };
}

async function attachCaptureAndAsr() {
  const listOut = (() => {
    try { return JSON.parse(execFileSync(AUDIO_BRIDGE, ['{"mode":"list"}'], { encoding: 'utf8', timeout: 4000 })); }
    catch (_) { return { apps: [] }; }
  })();
  const wantBundle = appFilter === 'wecom' ? 'com.tencent.WeWorkMac' : 'com.tencent.xinWeChat';
  const targetApp = (listOut.apps || []).find(a => a.bundleId === wantBundle) || (listOut.apps || []).find(a => a.bundleId === 'com.tencent.xinWeChat');
  if (!targetApp) return;

  try {
    hardwareAudio = new HardwareAudio();
    hardwareAudio.on('vad', ev => {
      if (sameHostDualCall) return;
      if (ev?.speaking && liveState.speaking && activePlayAbort && !activePlayAbort.signal.aborted) {
        liveState.bargeInCount += 1;
        activePlayAbort.abort('vad-barge-in');
        flushState();
      }
    });
    hardwareAudio.on('transcript', async ev => {
      const text = String(ev?.text || '').trim();
      if (!text || text.length < 2 || shuttingDown) return;
      if (liveState.speaking || (Date.now() - lastSpokenAt) < 1600) return;
      if (['嗯', '哦', '啊', '喂'].includes(text)) return;
      liveState.transcripts.push({ role: 'user', text, at: new Date().toISOString() });
      conversationHistory.push({ role: 'user', content: text });
      flushState();
      const reply = await generateCallReply(text, conversationHistory);
      await playToVirtualMic(reply);
    });
    hardwareAudio.on('error', () => {});
    hardwareAudio.setSession({
      sessionId: 'voip_' + process.pid,
      revision: 1,
      wakeNames: [],
      inputMode: 'meeting-passive',
      sampleRate: 16000,
      frameDurationMs: 60
    });
    await hardwareAudio.start();
  } catch (_) {
    hardwareAudio = null;
  }

  const capReq = JSON.stringify({
    mode: 'capture',
    pid: targetApp.pid,
    bundleId: targetApp.bundleId,
    launchDate: targetApp.launchDate || undefined,
    nativeTranscribe: false,
    locale: 'zh-CN'
  });
  bridgeCaptureChild = spawn(AUDIO_BRIDGE, [capReq], { stdio: ['pipe', 'pipe', 'ignore'], windowsHide: true });
  let buf = '';
  let loudRun = 0;
  bridgeCaptureChild.stdout?.on('data', chunk => {
    if (shuttingDown) return;
    buf += chunk.toString('utf8');
    let nl;
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (!line) continue;
      let ev;
      try { ev = JSON.parse(line); } catch (_) { continue; }
      if (ev.type === 'pcm' && typeof ev.b64 === 'string') {
        const pcm = Buffer.from(ev.b64, 'base64');
        const rms = Number(ev.rms) || 0;
        loudRun = rms >= 0.032 ? loudRun + 1 : 0;
        if (!sameHostDualCall && loudRun >= 4 && liveState.speaking && activePlayAbort && !activePlayAbort.signal.aborted) {
          liveState.bargeInCount += 1;
          activePlayAbort.abort('rms-barge-in');
          flushState();
        }
        if (hardwareAudio && pcm.length === 1920) {
          hardwareAudio.streamPcmFrame(pcm);
        }
      }
    }
  });
}

async function shutdown(reason = 'normal') {
  if (shuttingDown) return;
  shuttingDown = true;
  clearInterval(pollTimer);
  try { activePlayAbort?.abort(reason); } catch (_) {}
  try { bridgeCaptureChild?.kill('SIGTERM'); } catch (_) {}
  try { await hardwareAudio?.close?.(); } catch (_) {}
  restoreOriginalHardwareInput();
  liveState.phase = 'ended';
  liveState.speaking = false;
  flushState();

  try {
    if (liveState.transcripts.some(t => t.role === 'user')) {
      const summary = await summarizeVoiceSessionWithArk({
        transcripts: liveState.transcripts,
        scene: 'voip_voice_call',
        sceneTitle: `微信语音通话（${targetContact || appFilter}）`,
        botName: '安晓心',
        userDataDir: OPENBOT_DIR
      });
      const existing = fs.existsSync(summariesFile) ? JSON.parse(fs.readFileSync(summariesFile, 'utf8')) : [];
      existing.push({ at: new Date().toISOString(), target: targetContact, app: appFilter, summary, transcripts: liveState.transcripts });
      fs.writeFileSync(summariesFile, JSON.stringify(existing.slice(-20), null, 2), 'utf8');
      liveState.callSummary = summary;
      flushState();
    }
  } catch (_) {}

  try { httpServer?.close?.(); } catch (_) {}
  try { if (fs.existsSync(pidFile) && fs.readFileSync(pidFile, 'utf8').trim() === String(process.pid)) fs.unlinkSync(pidFile); } catch (_) {}
  process.exit(0);
}

process.on('SIGINT', () => void shutdown('sigint'));
process.on('SIGTERM', () => void shutdown('sigterm'));
process.on('uncaughtException', err => {
  liveState.lastError = err?.message || String(err);
  flushState();
  void shutdown('uncaught_exception');
});

(async () => {
  const preGreetingPromise = greetingText ? synthesizePcm24k(greetingText).catch(() => Buffer.alloc(0)) : Promise.resolve(Buffer.alloc(0));
  const initialDevs = runVisionJson(['audio-devices'], 4000);
  if (initialDevs.ok && initialDevs.defaultInput && !initialDevs.defaultInput.isVirtual && !fs.existsSync(savedMicFile)) {
    try { fs.writeFileSync(savedMicFile, JSON.stringify(initialDevs.defaultInput, null, 2), 'utf8'); } catch (_) {}
  }
  if (idleInputUid) {
    saveAndSwitchInput(idleInputUid);
  }

  await attachCaptureAndAsr();

  httpServer = http.createServer(async (req, res) => {
    const replyJson = (code, obj) => {
      res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify(obj));
    };
    if (req.method === 'GET' && req.url === '/status') {
      return replyJson(200, liveState);
    }
    if (req.method === 'POST' && req.url === '/hangup') {
      replyJson(200, { ok: true, hangingUp: true });
      setTimeout(() => void shutdown('http_hangup'), 60);
      return;
    }
    if (req.method === 'POST' && req.url === '/speak') {
      let bodyStr = '';
      for await (const c of req) bodyStr += c.toString('utf8');
      let body = {};
      try { body = JSON.parse(bodyStr || '{}'); } catch (_) {}
      const text = String(body.text || '').trim();
      if (!text) return replyJson(400, { ok: false, error: 'missing_text' });
      const result = await playToVirtualMic(text);
      return replyJson(200, { ok: true, ...result });
    }
    replyJson(404, { ok: false, error: 'not_found' });
  });
  await new Promise((resolve, reject) => {
    httpServer.once('error', reject);
    httpServer.listen(httpPort, '127.0.0.1', resolve);
  });
  liveState.httpPort = httpPort;
  flushState();

  const onConnected = async () => {
    seenConnected = true;
    liveState.phase = 'connected';
    liveState.callStatus = 'connected';
    liveState.connectedAt = liveState.connectedAt || new Date().toISOString();
    flushState();
    if (!liveState.greeted && greetingText) {
      liveState.greeted = true;
      const prePcm = await preGreetingPromise;
      await playToVirtualMic(greetingText, { precomputedPcm: prePcm });
    }
  };

  if (assumeConnected) {
    void onConnected();
  }

  let pollInFlight = false;
  let dualChecked = false;
  pollTimer = setInterval(async () => {
    if (shuttingDown || pollInFlight) return;
    pollInFlight = true;
    try {
      const scanScope = (!dualChecked) ? 'all' : appFilter;
      const st = await runVisionJsonAsync(['voice-call', '--action', 'status', '--app-id', scanScope], 12000);
      if (!st.ok) return;
      const calls = Array.isArray(st.calls) ? st.calls : [];
      if (scanScope === 'all') {
        dualChecked = true;
        const hasWechatCall = calls.some(c => c && c.appId === 'wechat');
        const hasWecomCall = calls.some(c => c && c.appId === 'wecom');
        if (hasWechatCall && hasWecomCall) {
          sameHostDualCall = true;
          liveState.sameHostDualCall = true;
        }
      }

      let myCallStatus = st.callStatus || 'idle';
      if (appFilter !== 'all') {
        const ownCalls = calls.filter(c => c && c.appId === appFilter);
        if (ownCalls.length === 0) {
          myCallStatus = 'idle';
        } else if (ownCalls.some(c => c.callStatus === 'connected')) {
          myCallStatus = 'connected';
        } else if (ownCalls.some(c => c.callStatus === 'dialing')) {
          myCallStatus = 'dialing';
        } else {
          myCallStatus = ownCalls[0].callStatus || 'idle';
        }
      }

      liveState.callStatus = myCallStatus;
      if (myCallStatus === 'dialing') {
        seenDialing = true;
        idlePollsAfterDialing = 0;
      }
      if (myCallStatus === 'connected') {
        if (!seenConnected || !liveState.greeted) {
          void onConnected();
        }
      } else if (seenConnected && myCallStatus === 'idle' && !liveState.speaking) {
        // Remote party ended call
        void shutdown('remote_hangup');
      } else if (!seenConnected) {
        if ((seenDialing && myCallStatus === 'idle' && ++idlePollsAfterDialing >= 4) || (Date.now() - startedAt > 90_000)) {
          void shutdown('dial_ended_before_connect');
        }
      }
      flushState();
    } finally {
      pollInFlight = false;
    }
  }, 3000);
})();
