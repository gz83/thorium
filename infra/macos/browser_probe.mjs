// Copyright (c) 2026 Alex313031 and gz83.
// Run with Node.js >= 22. No npm packages or browser-driver version coupling.
import fs from 'node:fs';
import path from 'node:path';
import {spawn, execFileSync} from 'node:child_process';
import {createServer} from 'node:http';
import {setTimeout as delay} from 'node:timers/promises';
import {CDP} from './cdp.mjs';

const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const root = config.results;
fs.mkdirSync(root, {recursive: true});
const report = {
  success: false, status: 'INCOMPLETE', core_status: 'INCOMPLETE', phase: 'startup',
  pages: [], external: [], crashes: [], warnings: [],
  interaction: config.mode === 'gui' ? {status: 'INCOMPLETE', reason: 'Local input/navigation not reached'} : null,
  issues: config.mode === 'gui' ? {
    '1286': {status: 'INCOMPLETE', reason: 'Startup check not completed'},
    '1316': {status: 'INCOMPLETE', reason: 'Baidu search not started', steps: []},
  } : {},
  capabilities: config.mode === 'gui' ? {
    webgl: {status: 'INCOMPLETE', reason: 'Not reached'},
    audio: {status: 'INCOMPLETE', reason: 'Not reached'},
  } : {},
};
const save = () => fs.writeFileSync(path.join(root, 'report.json'), JSON.stringify(report, null, 2));
const phase = name => { report.phase = name; save(); };
function updateStatus() {
  // Capabilities are diagnostics. Crashes/timeouts during them still fail core.
  const baidu = report.issues['1316'];
  report.external_blocked = baidu?.status === 'INCOMPLETE' &&
    ['captcha', 'network'].includes(baidu.blocked_by) && baidu.renderer_responsive === true &&
    report.interaction?.status === 'PASS';
  const statuses = [report.core_status,
    ...(report.interaction ? [report.interaction.status] : []),
    ...Object.entries(report.issues)
      .filter(([id]) => !(id === '1316' && report.external_blocked))
      .map(([, item]) => item.status)];
  report.status = statuses.includes('FAIL') ? 'FAIL' : statuses.includes('INCOMPLETE') ? 'INCOMPLETE' : 'PASS';
  report.success = report.status === 'PASS';
}
const command = (name, args, file, timeout = 10000) => {
  try {
    const output = execFileSync(name, args, {timeout, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe']});
    fs.writeFileSync(path.join(root, file), output);
    return output;
  } catch (error) {
    fs.writeFileSync(path.join(root, file), `${error}\n${error.stdout ?? ''}\n${error.stderr ?? ''}`);
    report.warnings.push(`${name}: ${error.message}`);
    return null;
  }
};
const desktop = name => {
  if (config.mode === 'gui') {
    command('screencapture', ['-x', path.join(root, `${name}-desktop.png`)], `${name}-capture.txt`);
  }
};
let browser, cdp, session, closing = false;
let activeIssue = config.mode === 'gui' ? '1286' : null;
let descendants = [];
let interrupted = false;
for (const signal of ['SIGTERM', 'SIGINT']) {
  process.on(signal, () => {
    interrupted = true;
    cdp?.fail(new Error(`Probe interrupted: ${signal}`));
  });
}

class PageScriptError extends Error {}

async function evaluate(expression, timeout = 15000) {
  const result = await cdp.call('Runtime.evaluate', {
    expression, returnByValue: true, awaitPromise: true,
  }, session, timeout);
  if (result.exceptionDetails) throw new PageScriptError(JSON.stringify(result.exceptionDetails));
  return result.result.value;
}

async function ready(url, timeout = 30000) {
  const until = Date.now() + timeout;
  let state;
  while (Date.now() < until) {
    try {
      state = await evaluate(`({url: location.href, ready: document.readyState,
        title: document.title, text: document.body?.innerText?.slice(0, 16000) ?? ''})`, 5000);
      const expected = !url || state.url === url ||
        (url === 'chrome://newtab/' && /^chrome:\/\/(new-tab-page|newtab)\//.test(state.url)) ||
        (url.startsWith('https:') && new URL(state.url).hostname === new URL(url).hostname);
      if (expected && state.ready === 'complete') return state;
    } catch (error) {
      // Execution contexts can disappear during cross-process navigation.
      if (cdp.failure || !/context|Cannot find|Inspected target navigated/i.test(error.message)) throw error;
    }
    if (interrupted) throw new Error('Probe interrupted');
    await delay(200);
  }
  throw new Error(`Page did not finish loading: ${url}; last state: ${JSON.stringify(state)}`);
}

async function screenshot(name) {
  try {
    const {data} = await cdp.call('Page.captureScreenshot', {format: 'png'}, session, 5000);
    fs.writeFileSync(path.join(root, `${name}-page.png`), Buffer.from(data, 'base64'));
  } catch (error) { report.warnings.push(`Page screenshot: ${error.message}`); }
}

async function navigate(name, url, timeout = 30000) {
  const navigation = await cdp.call('Page.navigate', {url}, session, timeout);
  if (navigation.errorText) throw new Error(`Navigation failed: ${navigation.errorText}`);
  const state = await ready(url, timeout);
  // A live browser process or a remembered target title alone is insufficient.
  if (await evaluate('6 * 7') !== 42) throw new Error('Renderer did not execute JavaScript');
  await screenshot(name);
  return {name, ...state};
}

class Incomplete extends Error {
  constructor(message, blockedBy) {
    super(message);
    this.blockedBy = blockedBy;
  }
}
const transientContext = error => /context|Cannot find|Inspected target navigated/i.test(error.message)
  && !/timeout/i.test(error.message);
const networkFailure = error => /Navigation failed: net::ERR_|Page did not finish loading:/.test(error.message);

async function pressEnter() {
  const enter = {key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13};
  await cdp.call('Input.dispatchKeyEvent', {type: 'keyDown', ...enter, text: '\r', unmodifiedText: '\r'}, session);
  await cdp.call('Input.dispatchKeyEvent', {type: 'keyUp', ...enter}, session);
}

async function localInteraction() {
  const result = report.interaction;
  const requests = [];
  let server;
  try {
    phase('local-input');
    const html = fs.readFileSync(new URL('./navigation.html', import.meta.url));
    server = createServer((request, response) => {
      const url = new URL(request.url, 'http://127.0.0.1');
      requests.push({method: request.method, path: url.pathname, query: url.searchParams.get('q')});
      const allowed = request.method === 'GET' && ['/', '/search'].includes(url.pathname);
      response.writeHead(allowed ? 200 : 404, {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'});
      response.end(allowed ? html : 'Not found');
    });
    await new Promise((resolve, reject) => {
      server.once('error', reject);
      server.listen(0, '127.0.0.1', resolve);
    });
    const origin = `http://127.0.0.1:${server.address().port}`;
    result.home = await navigate('local-form', `${origin}/`, 15000);
    if (!await evaluate(`(() => {
      const input = document.querySelector('#query');
      input.focus();
      input.select();
      return document.activeElement === input;
    })()`)) throw new Error('Local search field did not receive focus');
    await cdp.call('Input.insertText', {text: 'hello'}, session);
    if (await evaluate('document.querySelector("#query").value') !== 'hello') {
      throw new Error('Local search field did not receive hello');
    }
    await screenshot('local-input');
    phase('local-submit');
    await pressEnter();
    const expected = `${origin}/search?q=hello`;
    result.result = await ready(expected, 15000);
    await delay(2000);
    result.state = await evaluate(`({url: location.href, ready: document.readyState,
      query: window.navigationProbe?.query, text: document.querySelector('#result')?.textContent})`);
    if (result.state.url !== expected || result.state.ready !== 'complete' || result.state.query !== 'hello' ||
        result.state.text !== 'Search result: hello' || await evaluate('6 * 7') !== 42 ||
        !requests.some(request => request.method === 'GET' && request.path === '/search' && request.query === 'hello')) {
      throw new Error(`Local form submission/navigation failed: ${JSON.stringify(result.state)}`);
    }
    await screenshot('local-results');
    if (cdp.failure) throw cdp.failure;
    result.status = 'PASS';
    result.reason = 'Local HTTP form input, Enter submission, result content and renderer liveness verified';
  } catch (error) {
    result.status = 'FAIL';
    result.reason = error.message;
    throw error;
  } finally {
    result.requests = requests;
    if (server) {
      server.closeAllConnections();
      await new Promise(resolve => server.close(resolve));
    }
    save();
  }
}

async function pageHTML(name) {
  try {
    // Baidu's inline styles alone can exceed 200 KB. Keep the body as well.
    const html = await evaluate('document.documentElement.outerHTML', 5000);
    fs.writeFileSync(path.join(root, `${name}.html`), html);
  } catch (error) { report.warnings.push(`Page HTML: ${error.message}`); }
  try {
    const inputs = await evaluate(`({
      url: location.href,
      fields: Array.from(document.querySelectorAll('input, textarea, [contenteditable], [role="textbox"]'))
        .map(field => {
          const rect = field.getBoundingClientRect();
          const style = getComputedStyle(field);
          return {
            tag: field.tagName, id: field.id, name: field.getAttribute('name'),
            type: field.getAttribute('type'), role: field.getAttribute('role'),
            placeholder: field.getAttribute('placeholder'), ariaLabel: field.getAttribute('aria-label'),
            contentEditable: field.isContentEditable, disabled: field.matches(':disabled'),
            readOnly: Boolean(field.readOnly), focused: document.activeElement === field,
            display: style.display, visibility: style.visibility,
            rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height}
          };
        })
    })`, 5000);
    fs.writeFileSync(path.join(root, `${name}-inputs.json`), JSON.stringify(inputs, null, 2));
  } catch (error) { report.warnings.push(`Page input inventory: ${error.message}`); }
}

async function baiduState() {
  return evaluate(`(() => {
    const url = new URL(location.href);
    const results = Array.from(document.querySelectorAll(
      '#content_left .result, #content_left .c-container, #content_left .result-op'
    )).filter(node => node.querySelector('h3 a[href]'));
    return {
      url: location.href, title: document.title, ready: document.readyState,
      query: url.searchParams.get('wd'),
      resultURL: ['www.baidu.com', 'baidu.com'].includes(url.hostname) && url.pathname === '/s',
      resultCount: results.length,
      resultTitles: results.slice(0, 5).map(node => node.querySelector('h3').innerText),
      challenge: /安全验证|访问验证|验证码|captcha|security verification/i.test(document.title) ||
        url.hostname === 'wappass.baidu.com' ||
        Boolean(document.querySelector('iframe[src*="captcha"], iframe[src*="verify"], input[name="vcode"]')),
      text: document.body?.innerText?.slice(0, 16000) ?? '',
    };
  })()`, 5000);
}

async function baiduSearch() {
  const issue = report.issues['1316'];
  activeIssue = '1316';
  try {
    phase('baidu-home');
    issue.steps.push(await navigate('baidu-home', 'https://www.baidu.com/', 30000));
    await pageHTML('baidu-home');
    const inputDeadline = Date.now() + 10000;
    let input;
    do {
      issue.last_page = await baiduState();
      if (issue.last_page.challenge) throw new Incomplete('Baidu presented a verification challenge', 'captcha');
      input = await evaluate(`(() => {
        // Prefer the current homepage editor, then the classic search form.
        // Keep editable fallbacks within Baidu's search container, not login forms.
        const selectors = [
          'textarea#chat-textarea',
          'input#kw, input[name="wd"], textarea#kw, textarea[name="wd"]',
          '#chat-input-main textarea, #chat-input-main input[type="text"], ' +
            '#chat-input-main [contenteditable="true"], #chat-input-main [contenteditable="plaintext-only"]'
        ];
        const field = selectors.flatMap(selector => Array.from(document.querySelectorAll(selector)))
          .find(node => {
            const rect = node.getBoundingClientRect();
            const style = getComputedStyle(node);
            return !node.matches(':disabled') && !node.readOnly &&
              node.getAttribute('aria-disabled') !== 'true' && node.getAttribute('aria-readonly') !== 'true' &&
              !node.closest('[hidden], [inert]') && style.visibility === 'visible' &&
              rect.width > 0 && rect.height > 0;
          });
        if (!field) return null;
        field.scrollIntoView({block: 'center'});
        field.focus();
        if (field.isContentEditable) {
          const range = document.createRange();
          range.selectNodeContents(field);
          const selection = getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
        } else {
          field.select();
        }
        return document.activeElement === field ? {
          tag: field.tagName, id: field.id, name: field.getAttribute('name'),
          contentEditable: field.isContentEditable
        } : null;
      })()`);
      if (!input) await delay(250);
    } while (!input && Date.now() < inputDeadline);
    if (!input) throw new Incomplete('Baidu search field unavailable; see HTML, input inventory and screenshot');

    phase('baidu-input');
    await cdp.call('Input.insertText', {text: 'hello'}, session);
    if (await evaluate(`(() => {
      const field = document.activeElement;
      return field?.isContentEditable ? field.textContent : field?.value;
    })()`) !== 'hello') {
      throw new Incomplete('Could not verify hello in the Baidu search field');
    }
    issue.steps.push({name: 'input', field: input, value: 'hello'});
    await screenshot('baidu-input');
    await pageHTML('baidu-input');
    phase('baidu-submit');
    await pressEnter();
    issue.steps.push({name: 'submit', method: 'Enter'});
    phase('baidu-results');
    const deadline = Date.now() + 30000;
    let verified = false;
    while (Date.now() < deadline) {
      try {
        const state = await baiduState();
        issue.last_page = state;
        save();
        if (state.challenge) throw new Incomplete('Baidu presented a verification challenge after submission', 'captcha');
        if (state.resultURL && state.query === 'hello' && state.ready === 'complete' && state.resultCount > 0) {
          // Require the result renderer to remain alive, not just commit the URL.
          await delay(2000);
          const stable = await baiduState();
          issue.last_page = stable;
          if (stable.resultURL && stable.query === 'hello' && stable.ready === 'complete' &&
              stable.resultCount > 0 && !stable.challenge && await evaluate('6 * 7') === 42) {
            issue.steps.push({name: 'results', ...stable});
            verified = true;
            break;
          }
        }
      } catch (error) {
        if (cdp.failure || !transientContext(error)) throw error;
      }
      await delay(250);
    }
    if (!verified) throw new Incomplete('Could not verify /s?wd=hello with result content and a live renderer');
    await screenshot('baidu-results');
    await pageHTML('baidu-results');
    if (cdp.failure) throw cdp.failure;
    issue.status = 'PASS';
    issue.reason = 'Homepage input, Enter submission, result URL/content and renderer liveness verified';
  } catch (error) {
    issue.status = 'FAIL';
    issue.reason = error.message;
    if (!cdp.failure && (error instanceof Incomplete || networkFailure(error))) {
      try {
        if (await evaluate('6 * 7', 5000) === 42) {
          issue.status = 'INCOMPLETE';
          issue.renderer_responsive = true;
          issue.blocked_by = error.blockedBy ?? (networkFailure(error) ? 'network' : null);
          if (issue.blocked_by) report.warnings.push(`Baidu #1316 remains INCOMPLETE: ${issue.blocked_by}`);
        }
      } catch (livenessError) { issue.reason += `; liveness check: ${livenessError.message}`; }
    }
    if (issue.status === 'FAIL') processSnapshot(true, 'baidu-');
    await screenshot('baidu-unverified');
    await pageHTML('baidu-unverified');
    // Preserve hard failures and let unrelated checks run if CDP still works.
    if (cdp.failure) {
      issue.status = 'FAIL';
      issue.reason += `; ${cdp.failure.message}`;
      throw error;
    }
  } finally {
    activeIssue = null;
    save();
  }
}

async function capabilities() {
  // Run AFTER the issue reproductions; a GPU/audio problem cannot prevent them.
  phase('gpu-info');
  try {
    const info = await cdp.call('SystemInfo.getInfo', {}, undefined, 10000);
    fs.writeFileSync(path.join(root, 'gpu-info.json'), JSON.stringify(info, null, 2));
  } catch (error) {
    if (cdp.failure) throw error;
    report.warnings.push(`GPU information unavailable: ${error.message}`);
  }
  for (const [name, expression] of [['webgl', 'window.checkWebGL()'], ['audio', 'window.checkAudio()']]) {
    if (cdp.failure) throw cdp.failure;
    phase(name);
    try {
      report.capabilities[name] = {status: 'PASS', result: await evaluate(expression)};
    } catch (error) {
      report.capabilities[name] = {status: 'FAIL', error: error.message};
      save();
      // Only a JavaScript capability assertion can be diagnostic-only.
      // Protocol timeouts, crashes and lost renderer responsiveness are fatal.
      if (cdp.failure || !(error instanceof PageScriptError)) throw error;
      if (await evaluate('6 * 7', 5000) !== 42) throw new Error(`${name}: renderer stopped responding`);
      report.warnings.push(`${name} diagnostic failed; see capabilities in report.json and browser logs`);
    }
    save();
  }
}

function processSnapshot(sample, prefix = '') {
  const output = command('ps', ['-axo', 'pid=,ppid=,pgid=,command='], `${prefix}processes.txt`);
  if (!output || !browser?.pid) return;
  const rows = output.split('\n').map(line => line.match(/^\s*(\d+)\s+(\d+)\s+(\d+)\s+(.*)$/))
    .filter(Boolean).map(m => ({pid: +m[1], parent: +m[2], group: +m[3], command: m[4]}));
  const ids = new Set([browser.pid]);
  for (let changed = true; changed;) {
    changed = false;
    for (const row of rows) {
      if (!ids.has(row.pid) && (ids.has(row.parent) || row.group === browser.pid)) {
        ids.add(row.pid);
        changed = true;
      }
    }
  }
  descendants = rows.filter(row => ids.has(row.pid));
  if (sample) {
    for (const row of descendants.filter(row => !row.command.includes('crashpad_handler')).slice(0, 6)) {
      command('sample', [String(row.pid), '3', '1', '-file', path.join(root, `${prefix}sample-${row.pid}.txt`)],
        `${prefix}sample-${row.pid}-command.txt`, 10000);
    }
  }
}

try {
  const args = [
    `--user-data-dir=${config.profile}`, '--remote-debugging-pipe',
    '--no-first-run', '--no-default-browser-check', '--use-mock-keychain',
    '--enable-logging=stderr', ...(config.mode === 'headless' ? ['--headless=new', 'about:blank'] : []),
    ...config.extra_args,
  ];
  report.command = [config.browser, ...args];
  const stdout = fs.openSync(path.join(root, 'browser.stdout.txt'), 'w');
  const stderr = fs.openSync(path.join(root, 'browser.stderr.txt'), 'w');
  browser = spawn(config.browser, args, {
    detached: true, stdio: ['ignore', stdout, stderr, 'pipe', 'pipe'],
    env: {...process.env, BREAKPAD_DUMP_LOCATION: config.dumps},
  });
  fs.closeSync(stdout);
  fs.closeSync(stderr);
  report.pid = browser.pid;
  save();
  cdp = new CDP(browser.stdio[3], browser.stdio[4], event => {
    const evidence = {...event, phase: report.phase};
    fs.appendFileSync(path.join(root, 'events.jsonl'), JSON.stringify(evidence) + '\n');
    if (['Target.targetCrashed', 'Inspector.targetCrashed'].includes(event.method) && !closing) {
      report.crashes.push(evidence);
    }
  });
  browser.on('error', error => cdp.fail(error));
  browser.on('exit', (code, signal) => {
    report.exit = {code, signal, during_cleanup: closing};
    if (!closing) cdp.fail(new Error(`Browser exited early: code=${code}, signal=${signal}`));
  });
  report.browser = await cdp.call('Browser.getVersion', {}, undefined, 60000);
  await cdp.call('Target.setDiscoverTargets', {discover: true});
  desktop('startup');
  const until = Date.now() + 30000;
  let target;
  do {
    const {targetInfos} = await cdp.call('Target.getTargets');
    report.targets = targetInfos;
    target = targetInfos.find(item => item.type === 'page');
    if (!target) await delay(200);
  } while (!target && Date.now() < until);
  if (!target) throw new Error('Browser did not create a startup page');
  ({sessionId: session} = await cdp.call('Target.attachToTarget', {targetId: target.targetId, flatten: true}));
  await cdp.call('Page.enable', {}, session);
  await cdp.call('Inspector.enable', {}, session);
  report.startup = await ready();
  if (config.mode === 'gui') {
    report.window = await cdp.call('Browser.getWindowForTarget', {targetId: target.targetId});
    await cdp.call('Page.bringToFront', {}, session);
    if (await evaluate('6 * 7') !== 42) throw new Error('Startup renderer did not respond');
    report.issues['1286'] = {
      status: 'PASS', reason: 'Browser window and startup renderer responded',
      scope: 'Browser/renderer startup responsiveness; native control input is not exercised',
    };
    activeIssue = null;
  }
  await screenshot('startup');
  phase('local');
  report.pages.push(await navigate('local', config.local_url));
  report.javascript = await evaluate('window.smoke');
  if (!report.javascript?.success) throw new Error(`Local JS/Wasm failed: ${JSON.stringify(report.javascript)}`);
  if (config.mode === 'gui') {
    await localInteraction();
    await baiduSearch();
  }
  phase('version');
  const version = await navigate('version', 'chrome://version/');
  report.pages.push(version);
  if (!version.text.includes(config.expected_version)) throw new Error('Running browser version does not match input');
  phase('newtab');
  report.pages.push(await navigate('newtab', 'chrome://newtab/'));
  if (config.mode === 'gui') {
    phase('google');
    try {
      report.external.push({status: 'PASS', ...await navigate('google', 'https://www.google.com/', 15000)});
    } catch (error) {
      report.external.push({name: 'google', status: 'INCOMPLETE', error: error.message});
      if (cdp.failure || !networkFailure(error)) {
        report.external.at(-1).status = 'FAIL';
        throw error;
      }
      if (await evaluate('6 * 7', 5000) !== 42) throw new Error('External-page renderer stopped responding');
    }
  }
  // Recover from external network errors, then require another live local renderer.
  phase('local-final');
  report.pages.push(await navigate('local-final', config.local_url));
  if (config.mode === 'gui') await capabilities();
  phase('final-liveness');
  await delay(1500);
  if (!(await evaluate('window.smoke'))?.success) throw new Error('Renderer failed final liveness check');
  if (cdp.failure) throw cdp.failure;
  if (interrupted) throw new Error('Probe interrupted');
  report.core_status = 'PASS';
  updateStatus();
  desktop('final');
} catch (error) {
  report.core_status = 'FAIL';
  report.error = error.stack;
  if (activeIssue) report.issues[activeIssue] = {status: 'FAIL', reason: error.message};
  desktop('failure');
  if (cdp && session) await screenshot('failure');
} finally {
  updateStatus();
  // Sample BEFORE terminating a hung browser. Allow Crashpad time to finish writing.
  processSnapshot(!report.success);
  await delay(report.success ? 300 : 5000);
  if (cdp?.failure || report.crashes.length || interrupted) {
    const needsSample = report.status !== 'FAIL';
    report.core_status = 'FAIL';
    report.error ??= cdp?.failure?.message ?? 'Crash or interruption before cleanup';
    updateStatus();
    if (needsSample) {
      processSnapshot(true);
      await delay(5000);
    }
  }
  closing = true;
  if (cdp && !cdp.failure) {
    try { await cdp.call('Browser.close', {}, undefined, 3000); }
    catch (error) { report.warnings.push(`Browser.close: ${error.message}`); }
  }
  await delay(1000);
  if (browser?.pid) {
    try { process.kill(-browser.pid, 'SIGTERM'); } catch {}
    await delay(500);
    try { process.kill(-browser.pid, 'SIGKILL'); } catch {}
    // Crashpad may have left the browser process group.
    for (const row of descendants.filter(row => row.command.includes('crashpad_handler'))) {
      try {
        const current = execFileSync('ps', ['-p', String(row.pid), '-o', 'command='], {encoding: 'utf8'}).trim();
        if (current === row.command) process.kill(row.pid, 'SIGTERM');
      } catch {}
    }
  }
  cdp?.fail(new Error('Probe finished'));
  browser?.stdio[3]?.destroy();
  browser?.stdio[4]?.destroy();
  save();
}
process.exitCode = report.status === 'PASS' ? 0 : report.status === 'FAIL' ? 1 : 2;
