#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const net = require('node:net');
const { spawn } = require('node:child_process');

function parseArgs(argv) {
  const result = {};
  for (let i = 0; i < argv.length; i += 2) {
    if (!argv[i].startsWith('--') || i + 1 >= argv.length) throw new Error('Expected --name value arguments.');
    result[argv[i].slice(2)] = argv[i + 1];
  }
  return result;
}
function hash(bytes) { return crypto.createHash('sha256').update(bytes).digest('hex'); }
function assert(ok, message) { if (!ok) throw new Error(message); }
function pause(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

async function freePort() {
  const protectedPorts = new Set([5195, 8644, 8787, 8788, 8789, 8795, 9876]);
  while (true) {
    const server = net.createServer();
    await new Promise((resolve, reject) => {
      server.once('error', reject);
      server.listen(0, '127.0.0.1', resolve);
    });
    const port = server.address().port;
    await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    if (!protectedPorts.has(port)) return port;
  }
}
async function assertPortAvailable(port) {
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, '127.0.0.1', resolve);
  });
  await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
}
function startOwned(name, command, args, cwd, env, logPath) {
  const fd = fs.openSync(logPath, 'wx');
  const child = spawn(command, args, { cwd, env, detached: true, stdio: ['ignore', fd, fd] });
  fs.closeSync(fd);
  child.name = name;
  child.command = [command, ...args].map(String);
  child.pgid = child.pid;
  child.done = new Promise((resolve) => {
    child.once('exit', (code, signal) => resolve({ code, signal }));
    child.once('error', (error) => resolve({ error: error.message }));
  });
  return child;
}
async function stopOwned(child) {
  if (!child) return { status: 'STOPPED', result: 'NOT_STARTED' };
  if (child.exitCode !== null || child.signalCode !== null) {
    return { status: 'STOPPED', result: 'ALREADY_EXITED' };
  }
  const pgid = child.pgid || child.pid;
  let termResult = 'SIGTERM_SENT';
  try { process.kill(-pgid, 'SIGTERM'); }
  catch (error) {
    if (error.code !== 'ESRCH') throw error;
    termResult = 'SIGTERM_ESRCH';
  }
  if (await Promise.race([child.done.then(() => true), pause(5000).then(() => false)])) {
    return { status: 'STOPPED', result: 'SIGTERM_EXITED', signal_result: termResult };
  }
  let killResult = 'SIGKILL_SENT';
  try { process.kill(-pgid, 'SIGKILL'); }
  catch (error) {
    if (error.code !== 'ESRCH') throw error;
    killResult = 'SIGKILL_ESRCH';
  }
  if (await Promise.race([child.done.then(() => true), pause(3000).then(() => false)])) {
    return { status: 'STOPPED', result: 'SIGKILL_EXITED', signal_result: killResult };
  }
  return { status: 'OUTCOME_UNKNOWN', result: 'SIGKILL_TIMEOUT', signal_result: killResult };
}

function processIdentity(child) {
  const command = Array.isArray(child.command) ? child.command : [];
  return {
    name: child.name || 'owned-child',
    pid: Number.isInteger(child.pid) ? child.pid : null,
    pgid: Number.isInteger(child.pgid) ? child.pgid : Number.isInteger(child.pid) ? child.pid : null,
    command: command.map(String),
  };
}

async function finalizeRun(evidence, outputDir, initialExitCode, options = {}) {
  let exitCode = initialExitCode;
  evidence.verification_status_before_cleanup = evidence.status;
  evidence.verification_exit_code_before_cleanup = initialExitCode;
  const processResults = [];
  for (const child of options.children || []) {
    const identity = processIdentity(child);
    let cleanup;
    try {
      cleanup = await (options.stopChild || stopOwned)(child);
      if (!cleanup || !['STOPPED', 'OUTCOME_UNKNOWN'].includes(cleanup.status)) {
        cleanup = { status: 'OUTCOME_UNKNOWN', result: 'INVALID_CLEANUP_RESULT' };
      }
    } catch (error) {
      cleanup = {
        status: 'OUTCOME_UNKNOWN',
        result: 'CLEANUP_ERROR',
        error_code: error.code || null,
        error_type: error.name || 'Error',
        error: error.message || String(error),
      };
    }
    processResults.push({ ...identity, cleanup });
  }
  evidence.processes = processResults;

  if (options.browser) {
    try {
      await options.browser.close();
      evidence.browser_cleanup = { status: 'STOPPED', result: 'CLOSED' };
    } catch (error) {
      evidence.browser_cleanup = {
        status: 'OUTCOME_UNKNOWN',
        result: 'CLEANUP_ERROR',
        error_code: error.code || null,
        error_type: error.name || 'Error',
        error: error.message || String(error),
      };
    }
  } else {
    evidence.browser_cleanup = { status: 'STOPPED', result: 'NOT_STARTED' };
  }

  const cleanupFailed = processResults.some((item) => item.cleanup.status !== 'STOPPED') ||
    evidence.browser_cleanup.status !== 'STOPPED';
  if (cleanupFailed) {
    evidence.status = 'OUTCOME_UNKNOWN';
    exitCode = 1;
  }

  try {
    const indexedScreenshots = new Set((evidence.screenshots || []).map((item) => item.file));
    for (const row of evidence.viewports || []) {
      for (const screenshot of row.screenshots || []) {
        if (indexedScreenshots.has(screenshot) || !fs.existsSync(screenshot)) continue;
        const bytes = fs.readFileSync(screenshot);
        evidence.screenshots.push({ file: screenshot, bytes: bytes.length, sha256: hash(bytes) });
        indexedScreenshots.add(screenshot);
      }
    }
  } catch (error) {
    evidence.status = 'OUTCOME_UNKNOWN';
    evidence.finalization_error = { type: error.name || 'Error', message: error.message || String(error) };
    exitCode = 1;
  }
  evidence.exit_code = exitCode;
  fs.writeFileSync(path.join(outputDir, 'receipt.json'), JSON.stringify(evidence, null, 2) + '\n', { flag: 'wx' });
  process.stdout.write(JSON.stringify({
    status: evidence.status,
    exit_code: exitCode,
    output_dir: outputDir,
    ports: evidence.ports,
    viewport_overflows: evidence.viewports.map((item) => ({ width: item.viewport.width, overflow: item.overflow_detected })),
    process_cleanup: processResults,
    screenshot_count: evidence.screenshots.length,
    error: evidence.error || null,
  }, null, 2) + '\n');
  return exitCode;
}
async function waitHttp(url, child, name) {
  const deadline = Date.now() + 30000;
  let reason = 'no response';
  while (Date.now() < deadline) {
    if (child.exitCode !== null || child.signalCode !== null) throw new Error(name + ' exited before readiness.');
    try {
      const response = await fetch(url);
      if (response.ok) return response;
      reason = 'HTTP ' + response.status;
    } catch (error) { reason = error.message; }
    await pause(250);
  }
  throw new Error(name + ' did not become ready: ' + reason);
}
function verifyManifest(root, pin) {
  const bytes = fs.readFileSync(path.join(root, 'artifact-manifest.json'));
  const digest = hash(bytes);
  assert(digest === pin, 'Manifest SHA-256 differs from the configured pin.');
  const manifest = JSON.parse(bytes.toString('utf8'));
  const entries = Object.entries(manifest.files || {});
  assert(entries.length === 52, 'Expected 52 manifest entries; found ' + entries.length + '.');
  for (const [relative, expected] of entries) {
    const parts = relative.split('/');
    assert(!path.isAbsolute(relative) && parts.every((part) => part && part !== '.' && part !== '..'), 'Unsafe manifest path.');
    const content = fs.readFileSync(path.join(root, ...parts));
    assert(content.length === expected.size_bytes, 'Manifest size mismatch: ' + relative);
    assert(hash(content) === expected.sha256, 'Manifest hash mismatch: ' + relative);
  }
  return { sha256: digest, file_count: entries.length };
}
function assetPath(root, intensity, strategy, kind) {
  const names = { plan: 'plan.png', axonometric: 'axonometric.png', geometry: 'scenario.geojson' };
  return path.join(root, intensity, strategy, names[kind]);
}

function isUrbanDesignRuntimePath(value) {
  const lexical = path.resolve(value);
  let resolved = lexical;
  try { resolved = fs.realpathSync(lexical); } catch {}
  return lexical.split(path.sep).includes('.urban_design_runtime') ||
    resolved.split(path.sep).includes('.urban_design_runtime');
}

function assertDisposableDatabase(database, project) {
  assert(database && fs.existsSync(database) && fs.statSync(database).isFile(), 'A disposable SQLite database copy is required.');
  assert(!isUrbanDesignRuntimePath(database), 'The browser verifier refuses .urban_design_runtime paths.');
  const authority = path.resolve(project, '..', 'project', '.urban_design_runtime', 'state.sqlite3');
  const canonicalAuthority = path.resolve(authority);
  let canonicalDatabase = path.resolve(database);
  try { canonicalDatabase = fs.realpathSync(database); } catch {}
  assert(canonicalDatabase !== canonicalAuthority, 'The browser verifier refuses the authoritative database.');
  if (fs.existsSync(canonicalAuthority)) {
    const candidateStat = fs.statSync(canonicalDatabase);
    const authorityStat = fs.statSync(canonicalAuthority);
    assert(candidateStat.dev !== authorityStat.dev || candidateStat.ino !== authorityStat.ino,
      'The browser verifier refuses a database with the authoritative database inode.');
  }
}

function parsePort(value, label) {
  const port = Number(value);
  assert(Number.isInteger(port) && port > 0 && port <= 65535, label + ' must be an integer TCP port.');
  return port;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const project = path.resolve(args.project);
  const web = path.join(project, 'web');
  const sourceRoot = path.resolve(args['source-root']);
  const pin = args['manifest-sha256'];
  const output = path.resolve(args['output-dir']);
  const database = path.resolve(args.database || '');
  const phase = args.phase;
  const playwrightPath = path.resolve(args.playwright);
  assert(phase === 'before' || phase === 'after', 'phase must be before or after.');
  assert(/^[0-9a-f]{64}$/.test(pin || ''), 'A pinned SHA-256 is required.');
  assert(fs.existsSync(path.join(project, '.venv', 'bin', 'python')), 'The worktree .venv is missing.');
  assert(fs.existsSync(path.join(web, 'package.json')), 'The web app is missing.');
  assert(fs.existsSync(playwrightPath), 'Playwright module path is missing.');
  assertDisposableDatabase(database, project);
  assert(!isUrbanDesignRuntimePath(output), 'Browser evidence output must not be under .urban_design_runtime.');
  assert(!fs.existsSync(output), 'Refusing to overwrite existing browser evidence.');
  fs.mkdirSync(output, { recursive: false });

  const evidence = {
    schema_version: 'preview-browser-evidence-v1',
    phase,
    status: 'FAIL',
    recorded_at_utc: new Date().toISOString(),
    project_root: project,
    preview_source_root: sourceRoot,
    database_copy: database,
    manifest: null,
    browser: null,
    ports: null,
    viewports: [],
    served_assets: [],
    downloads: [],
    requests: [],
    blocked_external_requests: [],
    mutating_api_requests: [],
    page_errors: [],
    console_errors: [],
    asset_verification_errors: [],
    screenshots: [],
    limitations: [
      'Site-context, critic-status, scenarios, and model-profile responses are deterministic local UI fixtures. Preview catalog and asset responses come from the real workspace FastAPI app using a disposable SQLite backup copy.',
      'No model dispatch, live provider, external source, QGIS, weather service, formal runtime database, or user browser page is started.',
    ],
  };
  let apiProcess;
  let viteProcess;
  let browser;
  let exitCode = 1;

  try {
    evidence.manifest = verifyManifest(sourceRoot, pin);
    const apiPort = args['api-port'] ? parsePort(args['api-port'], 'API port') : await freePort();
    const vitePort = args['vite-port'] ? parsePort(args['vite-port'], 'Vite port') : await freePort();
    const protectedPorts = new Set([5195, 8644, 8787, 8788, 8789, 8795, 9876]);
    assert(apiPort !== vitePort, 'API and Vite ports must be different.');
    assert(!protectedPorts.has(apiPort) && !protectedPorts.has(vitePort), 'Refusing a protected port.');
    await assertPortAvailable(apiPort);
    await assertPortAvailable(vitePort);
    const apiOrigin = 'http://127.0.0.1:' + apiPort;
    const webOrigin = 'http://127.0.0.1:' + vitePort;
    evidence.ports = { api: apiPort, vite: vitePort, protected_ports_used: [] };

    const pythonCode = [
      'import os, uvicorn',
      'from urban_design.api import create_workspace_app',
      'from urban_design.store import ProjectStateStore',
      "app = create_workspace_app(ProjectStateStore(os.environ['PREVIEW_DATABASE']), morphology_preview_root=os.environ['PREVIEW_ROOT'], morphology_preview_manifest_sha256=os.environ['PREVIEW_PIN'])",
      "uvicorn.run(app, host='127.0.0.1', port=int(os.environ['PREVIEW_API_PORT']), log_level='warning')",
    ].join('; ');
    const common = { PATH: process.env.PATH || '', HOME: process.env.HOME || '', LANG: process.env.LANG || 'C.UTF-8' };
    apiProcess = startOwned(
      'preview-api',
      path.join(project, '.venv', 'bin', 'python'),
      ['-c', pythonCode],
      project,
      {
        ...common,
        PYTHONPATH: path.join(project, 'src'),
        PYTHONDONTWRITEBYTECODE: '1',
        PYTHONUNBUFFERED: '1',
        PREVIEW_ROOT: sourceRoot,
        PREVIEW_PIN: pin,
        PREVIEW_DATABASE: database,
        PREVIEW_API_PORT: String(apiPort),
      },
      path.join(output, 'api.log'),
    );
    viteProcess = startOwned(
      'vite',
      'npm',
      ['run', 'dev', '--', '--host', '127.0.0.1', '--port', String(vitePort), '--strictPort'],
      web,
      { ...common, VITE_API_BASE: apiOrigin, CI: '1' },
      path.join(output, 'vite.log'),
    );

    const apiResponse = await waitHttp(apiOrigin + '/api/v1/morphology/previews', apiProcess, 'Preview API');
    const catalog = await apiResponse.json();
    assert(catalog.status === 'AVAILABLE' && catalog.count === 10, 'Actual preview API did not return ten candidates.');
    assert(catalog.manifest_sha256 === pin, 'Actual preview API returned a different manifest pin.');
    assert(typeof catalog.verified_at_utc === 'string' && catalog.verified_at_utc.endsWith('Z'),
      'Actual preview API did not return its startup verification time.');
    assert(catalog.source_reverified === false, 'Actual preview API did not disclose that its source was not reverified.');
    const indexResponse = await waitHttp(webOrigin, viteProcess, 'Vite');
    assert((await indexResponse.text()).includes('<div id="root">'), 'Vite did not serve the React root.');

    const { chromium } = require(playwrightPath);
    browser = await chromium.launch({
      headless: true,
      args: ['--disable-background-networking', '--disable-component-update', '--disable-sync', '--no-first-run'],
    });
    evidence.browser = { engine: 'Chromium', version: browser.version(), headless: true };
    const context = await browser.newContext({
      viewport: { width: 1280, height: 900 },
      acceptDownloads: true,
      serviceWorkers: 'block',
    });
    const page = await context.newPage();
    const requestRows = new Map();
    const assetTasks = [];

    page.on('request', (request) => {
      const row = { method: request.method(), url: request.url(), resource_type: request.resourceType(), status: null, failure: null };
      evidence.requests.push(row);
      requestRows.set(request, row);
    });
    page.on('response', (response) => {
      const row = requestRows.get(response.request());
      if (row) row.status = response.status();
      let url;
      try { url = new URL(response.url()); } catch { return; }
      if (url.origin !== apiOrigin) return;
      const match = url.pathname.match(/^\/api\/v1\/morphology\/previews\/([AB])\/([a-z0-9_]+)\/assets\/(plan|axonometric|geometry)$/);
      if (!match) return;
      assetTasks.push((async () => {
        const body = await response.body();
        const expected = fs.readFileSync(assetPath(sourceRoot, match[1], match[2], match[3]));
        const etag = (await response.allHeaders()).etag || '';
        const digest = hash(body);
        assert(response.status() === 200, 'Asset returned HTTP ' + response.status() + ': ' + url.pathname);
        assert(body.equals(expected), 'Served bytes differ from source: ' + url.pathname);
        assert(etag.replaceAll('"', '') === digest, 'Asset ETag differs from response hash: ' + url.pathname);
        evidence.served_assets.push({
          path: url.pathname,
          status: response.status(),
          bytes: body.length,
          sha256: digest,
          etag_sha256: etag.replaceAll('"', ''),
          exact_source_match: true,
        });
      })().catch((error) => evidence.asset_verification_errors.push(error.message)));
    });
    page.on('requestfailed', (request) => {
      const row = requestRows.get(request);
      if (row) row.failure = request.failure()?.errorText || 'failed';
    });
    page.on('pageerror', (error) => evidence.page_errors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error') evidence.console_errors.push(message.text());
    });

    const siteContext = {
      study_area: null,
      current_workspace: null,
      buildings: [],
      roads: [],
      segments: [],
      syntax_layers: [],
      syntax_layers_source: 'none',
      syntax_layer_plan: [],
      syntax_segments: [],
      syntax_figure_downloads: {},
      evidence_cards: [],
      evidence_cards_status: 'UNKNOWN',
      evidence_gaps: [],
      source_snapshot_ids: [],
      source_attributions: [],
      source_package_revision: null,
    };
    const surroundingContext = {
      metadata: {
        schema_version: 'browser-fixture-v1',
        project_id: 'fixture-only',
        study_area_id: 'fixture-only',
        study_area_version: 'fixture-only',
        study_area_geometry_sha256: '0'.repeat(64),
        crs: 'EPSG:28992',
        units: 'm',
        context_distance_m: 0,
        source: 'Local browser fixture',
        source_data_version: 'FIXTURE_ONLY',
        source_pbf_sha256: '0'.repeat(64),
        license: 'Not applicable',
        attribution: 'Synthetic empty context; no source retrieved',
        tolerance_m: 0,
      },
      layers: {
        water: { type: 'FeatureCollection', features: [] },
        green: { type: 'FeatureCollection', features: [] },
        buildings: { type: 'FeatureCollection', features: [] },
        roads: { type: 'FeatureCollection', features: [] },
      },
    };
    const profileStatus = {
      active_profile_id: null,
      weekly_call_limit: 200,
      weekly_calls_used: 0,
      live_dispatch_enabled: false,
      dispatch_block_reason: 'BLOCKED_MODEL_RUN_ACCOUNTING_UNAVAILABLE',
      profiles: [
        { id: 'browser-fixture-openai', provider: 'openai', model: 'fixture-only', status: 'MISSING_KEY', status_detail: 'UI fixture only; no key lookup performed.', enabled: false, active: false, egress: 'cloud' },
        { id: 'browser-fixture-hermes', provider: 'hermes', model: '', status: 'DISABLED', status_detail: 'UI fixture only; no CLI or dispatch started.', enabled: false, active: false, egress: 'local' },
      ],
    };
    await context.route('**/*', async (route) => {
      const request = route.request();
      let url;
      try { url = new URL(request.url()); }
      catch {
        evidence.blocked_external_requests.push(request.url());
        await route.abort('blockedbyclient');
        return;
      }
      if (url.protocol === 'blob:' && url.hostname === '127.0.0.1') {
        await route.continue();
        return;
      }
      if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(url.hostname)) {
        evidence.blocked_external_requests.push(request.url());
        await route.abort('blockedbyclient');
        return;
      }
      if (url.origin !== apiOrigin) {
        await route.continue();
        return;
      }
      const method = request.method().toUpperCase();
      if (url.pathname.startsWith('/api/v1/morphology/previews')) {
        await route.continue();
        return;
      }
      if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
        evidence.mutating_api_requests.push({ method, path: url.pathname });
        await route.fulfill({ status: 403, contentType: 'application/json', body: JSON.stringify({ detail: 'Mutation blocked by browser verifier.' }) });
        return;
      }
      if (method !== 'GET' && method !== 'HEAD' && method !== 'OPTIONS') {
        await route.abort('blockedbyclient');
        return;
      }
      if (url.pathname.endsWith('/site-context')) {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(siteContext) });
      } else if (url.pathname === '/api/v1/critic/status') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'BLOCKED_NO_LIVE_AUTHORIZATION' }) });
      } else if (url.pathname === '/api/v1/model-profiles/status') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(profileStatus) });
      } else if (url.pathname.endsWith('/surrounding-context')) {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(surroundingContext) });
      } else if (url.pathname === '/api/v1/scenarios') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ scenarios: [] }) });
      } else {
        await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Not part of this local walkthrough.' }) });
      }
    });

    await page.goto(webOrigin, { waitUntil: 'networkidle', timeout: 30000 });
    await page.locator('#sidebar-tab-dispositions').waitFor({ state: 'visible', timeout: 15000 });
    await page.locator('#tab-disp-buildings').waitFor({ state: 'visible', timeout: 10000 });
    const checks = [
      { id: 'sidebar-tab-dispositions', content: '#tab-disp-buildings', name: 'Dispositions' },
      { id: 'sidebar-tab-brief', content: '#input-zone-name', name: 'Spatial Brief' },
      { id: 'sidebar-tab-syntax', content: '#syntax-blocked-status', name: 'Syntax' },
      { id: 'sidebar-tab-constraints', content: '#constraint-set-title', name: 'Constraints' },
      { id: 'sidebar-tab-scenarios', content: '.scenario-studio h1', name: 'Scenarios' },
    ];

    for (const viewport of [
      { width: 1280, height: 900 },
      { width: 1440, height: 900 },
      { width: 1920, height: 1080 },
    ]) {
      await page.setViewportSize(viewport);
      const row = {
        viewport,
        sidebar: null,
        interactions: [],
        preview_candidates: null,
        preview_panel: null,
        preview_panel_overflow: null,
        narrow_preview_layout: null,
        screenshots: [],
        overflow_detected: false,
      };
      evidence.viewports.push(row);
      for (const item of checks) {
        await page.locator('#' + item.id).click({ timeout: 8000 });
        await page.locator(item.content).waitFor({ state: 'visible', timeout: 12000 });
        row.interactions.push({ control: item.name, clicked: true, content_visible: true });
      }
      await page.locator('#sidebar-tab-ai-settings').click({ timeout: 8000 });
      await page.locator('section[aria-label="AI 模型設定"]').waitFor({ state: 'visible', timeout: 10000 });
      await page.getByText(/目前只保存偏好，尚不啟動模型呼叫/).waitFor({ state: 'visible', timeout: 8000 });
      row.interactions.push({ control: 'AI model settings', clicked: true, content_visible: true, provider_dispatch_started: false });

      const bounds = await page.evaluate(() => {
        const ids = [
          'sidebar-tab-dispositions',
          'sidebar-tab-brief',
          'sidebar-tab-syntax',
          'sidebar-tab-constraints',
          'sidebar-tab-scenarios',
          'sidebar-tab-ai-settings',
        ];
        const first = document.getElementById(ids[0]);
        const sidebar = first && first.parentElement && first.parentElement.parentElement;
        if (!sidebar) return null;
        const side = sidebar.getBoundingClientRect();
        const controls = ids.map((id) => {
          const element = document.getElementById(id);
          const rect = element.getBoundingClientRect();
          return {
            id,
            x: rect.x,
            y: rect.y,
            width: rect.width,
            height: rect.height,
            right: rect.right,
            bottom: rect.bottom,
            client_width: element.clientWidth,
            scroll_width: element.scrollWidth,
            text_overflow: element.scrollWidth > element.clientWidth + 1,
            within_sidebar: rect.left >= side.left - 1 && rect.right <= side.right + 1,
          };
        });
        return {
          viewport_width: window.innerWidth,
          document_width: document.documentElement.scrollWidth,
          body_width: document.body.scrollWidth,
          sidebar: { x: side.x, y: side.y, width: side.width, right: side.right, height: side.height },
          controls,
          document_overflow: document.documentElement.scrollWidth > window.innerWidth + 1 || document.body.scrollWidth > window.innerWidth + 1,
          control_overflow: controls.some((control) => control.text_overflow || !control.within_sidebar),
        };
      });
      assert(bounds, 'Could not measure sidebar bounds.');
      assert(Math.abs(bounds.sidebar.width - 330) <= 1, 'Sidebar is not 330px at width ' + viewport.width + '.');
      assert(Math.abs(bounds.sidebar.x) <= 1, 'Sidebar is not aligned to x=0.');
      row.sidebar = bounds;
      row.overflow_detected = bounds.document_overflow || bounds.control_overflow;
      if (phase === 'after') {
        assert(!bounds.document_overflow, 'Document overflow at width ' + viewport.width + '.');
        assert(!bounds.control_overflow, 'Sidebar control overflow at width ' + viewport.width + '.');
      }

      const aiShot = path.join(output, phase + '-' + viewport.width + '-ai-settings.png');
      await page.screenshot({ path: aiShot, fullPage: true });
      row.screenshots.push(aiShot);
      await page.locator('#sidebar-tab-scenarios').click({ timeout: 8000 });
      await page.locator('.scenario-studio h1').waitFor({ state: 'visible', timeout: 12000 });
      await page.getByRole('tab', { name: '既有探索預覽' }).click({ timeout: 8000 });
      await page.getByRole('heading', { name: 'Existing morphology previews' }).waitFor({ state: 'visible', timeout: 20000 });
      const countA = await page.locator('.morphology-preview__group[aria-label="Assumption set A"] .morphology-preview__candidate').count();
      const countB = await page.locator('.morphology-preview__group[aria-label="Assumption set B"] .morphology-preview__candidate').count();
      assert(countA === 5 && countB === 5, 'Actual UI did not show exactly five A and five B candidates.');
      row.preview_candidates = { A: countA, B: countB };
      const candidate = page.locator('.morphology-preview__group[aria-label="Assumption set B"] .morphology-preview__candidate').first();
      const candidateLabel = await candidate.getAttribute('aria-label');
      await candidate.click({ timeout: 8000 });
      await page.locator('.morphology-preview__detail').waitFor({ state: 'visible', timeout: 10000 });
      const previewPanel = await page.evaluate(() => {
        const measure = (selector) => {
          const element = document.querySelector(selector);
          return element ? {
            client_width: element.clientWidth,
            scroll_width: element.scrollWidth,
            overflow: element.scrollWidth > element.clientWidth,
          } : null;
        };
        const badge = document.querySelector('.morphology-preview__badge');
        return {
          wrapper: measure('.scenario-preview-tab-wrapper'),
          panel: measure('.morphology-preview'),
          layout: measure('.morphology-preview__layout'),
          badge: badge ? {
            client_width: badge.clientWidth,
            scroll_width: badge.scrollWidth,
            overflow: badge.scrollWidth > badge.clientWidth,
            white_space: getComputedStyle(badge).whiteSpace,
            overflow_wrap: getComputedStyle(badge).overflowWrap,
          } : null,
        };
      });
      assert(previewPanel.wrapper && previewPanel.panel && previewPanel.layout && previewPanel.badge,
        'Preview panel overflow elements are missing at width ' + viewport.width + '.');
      row.preview_panel = previewPanel;
      row.preview_panel_overflow = [previewPanel.wrapper, previewPanel.panel, previewPanel.layout, previewPanel.badge]
        .some((item) => item.overflow);
      if (phase === 'after') {
        assert(!row.preview_panel_overflow, 'Preview panel scrollWidth exceeds clientWidth at width ' + viewport.width + '.');
        assert(previewPanel.badge.white_space !== 'nowrap', 'UNAPPROVED_PREVIEW badge cannot wrap.');
        if (viewport.width === 1280) {
          row.narrow_preview_layout = await page.evaluate(() => {
            const wrapper = document.querySelector('.scenario-preview-tab-wrapper');
            const layout = document.querySelector('.morphology-preview__layout');
            if (!wrapper || !layout) return null;
            const oldFlex = wrapper.style.flex;
            const oldWidth = wrapper.style.width;
            wrapper.style.flex = '0 0 740px';
            wrapper.style.width = '740px';
            const columns = getComputedStyle(layout).gridTemplateColumns.trim().split(/\s+/).length;
            wrapper.style.flex = oldFlex;
            wrapper.style.width = oldWidth;
            return { container_width: wrapper.clientWidth, column_count: columns };
          });
          assert(row.narrow_preview_layout && row.narrow_preview_layout.column_count === 1,
            'Preview layout must switch to one column when the central panel is under 760px.');
        }
      }
      await page.waitForFunction(() => {
        const image = document.querySelector('.morphology-preview__viewer img');
        return image && image.complete && image.naturalWidth > 0;
      }, null, { timeout: 15000 });

      if (viewport.width === 1440) {
        const metrics = await page.locator('[aria-label="Preview metrics"]').innerText();
        const retained = await page.locator('[aria-label="Retained-building context"]').innerText();
        assert(metrics.includes('Known-part land FAR'), 'Known-part FAR is not visible.');
        assert(retained.includes('Confidence:'), 'Retained-building confidence is not visible.');
        assert(/Floor count: UNKNOWN|Floor estimate: UNKNOWN/.test(retained), 'Unknown retained floors are not visible.');
        assert(await page.getByText('Human decision created: No').count() === 1, 'Unapproved preview status is not visible.');
        await page.locator('.morphology-preview__provenance summary').click();
        const provenance = await page.locator('.morphology-preview__provenance').innerText();
        assert(provenance.includes('Manifest SHA-256'), 'Manifest provenance is missing.');
        assert(provenance.includes('Comparison SHA-256'), 'Comparison provenance is missing.');
        assert(provenance.length > 100, 'Preview limitations are unexpectedly empty.');
        const verificationDisclosure = '來源於 ' + catalog.verified_at_utc + ' 驗證，啟動後未再驗證';
        assert(await page.getByText(verificationDisclosure, { exact: true }).count() === 1,
          'Startup verification time and source-reverification status are not visible.');
        const previewLabels = await page.locator('.morphology-preview button').allTextContents();
        assert(!previewLabels.some((label) => /^\s*(accept|approve|import|generate|edit)(\s|$)/i.test(label)), 'Preview UI exposes an approval or mutation action.');

        const apiCandidate = catalog.previews.find((item) => item.identity.intensity === 'B' && ('Open B: ' + item.strategy_label) === candidateLabel);
        assert(apiCandidate, 'Selected B candidate is missing from actual API catalog.');
        const planSource = assetPath(sourceRoot, 'B', apiCandidate.identity.strategy_id, 'plan');
        const planShot = path.join(output, phase + '-1440-preview-b-plan.png');
        await page.screenshot({ path: planShot, fullPage: true });
        row.screenshots.push(planShot);
        const planImageShot = path.join(output, phase + '-1440-preview-b-plan-image.png');
        await page.locator('.morphology-preview__viewer img').screenshot({ path: planImageShot });
        row.screenshots.push(planImageShot);

        const planFile = path.join(output, 'downloaded-B-plan.png');
        const [planDownload] = await Promise.all([
          page.waitForEvent('download', { timeout: 15000 }),
          page.getByRole('button', { name: 'Download plan image' }).click(),
        ]);
        await planDownload.saveAs(planFile);
        const planBytes = fs.readFileSync(planFile);
        assert(planBytes.equals(fs.readFileSync(planSource)), 'Downloaded plan image differs from pinned source.');
        const planFilename = 'morphology-preview-B-' + apiCandidate.identity.strategy_id + '-' + hash(planBytes).slice(0, 12) + '-plan.png';
        assert(planDownload.suggestedFilename() === planFilename, 'Plan download filename omits its strategy id or hash prefix.');
        evidence.downloads.push({ file: planFile, suggested_filename: planDownload.suggestedFilename(), bytes: planBytes.length, sha256: hash(planBytes), exact_source_match: true });

        await page.getByRole('button', { name: 'Axonometric image', exact: true }).click();
        await page.waitForFunction(() => {
          const image = document.querySelector('.morphology-preview__viewer img');
          return image && image.complete && image.naturalWidth > 0;
        }, null, { timeout: 15000 });
        const axonImageShot = path.join(output, phase + '-1440-preview-b-axonometric-image.png');
        await page.locator('.morphology-preview__viewer img').screenshot({ path: axonImageShot });
        row.screenshots.push(axonImageShot);
        const axonSource = assetPath(sourceRoot, 'B', apiCandidate.identity.strategy_id, 'axonometric');
        const axonFile = path.join(output, 'downloaded-B-axonometric.png');
        const [axonDownload] = await Promise.all([
          page.waitForEvent('download', { timeout: 15000 }),
          page.getByRole('button', { name: 'Download axonometric image' }).click(),
        ]);
        await axonDownload.saveAs(axonFile);
        const axonBytes = fs.readFileSync(axonFile);
        assert(axonBytes.equals(fs.readFileSync(axonSource)), 'Downloaded axonometric image differs from pinned source.');
        const axonFilename = 'morphology-preview-B-' + apiCandidate.identity.strategy_id + '-' + hash(axonBytes).slice(0, 12) + '-axonometric.png';
        assert(axonDownload.suggestedFilename() === axonFilename, 'Axonometric download filename omits its strategy id or hash prefix.');
        evidence.downloads.push({ file: axonFile, suggested_filename: axonDownload.suggestedFilename(), bytes: axonBytes.length, sha256: hash(axonBytes), exact_source_match: true });

        await page.getByRole('button', { name: 'Geometry' }).click();
        await page.locator('svg[aria-label="Preview geometry in EPSG:28992"]').waitFor({ state: 'visible', timeout: 15000 });
        const geometryShot = path.join(output, phase + '-1440-preview-b-geometry.png');
        await page.screenshot({ path: geometryShot, fullPage: true });
        row.screenshots.push(geometryShot);
        evidence.preview_ui = {
          selected_candidate: 'B/' + apiCandidate.identity.strategy_id,
          accessible_name: candidateLabel,
          known_part_far_visible: metrics.includes('Known-part land FAR'),
          retained_confidence_visible: retained.includes('Confidence:'),
          unknown_floor_visible: /Floor count: UNKNOWN|Floor estimate: UNKNOWN/.test(retained),
          status: 'UNAPPROVED_PREVIEW',
          human_decision_created: false,
          provenance_opened: true,
          geometry_view_visible: true,
          mutation_actions: false,
          downloaded_source_hashes: [hash(planBytes), hash(axonBytes)],
        };
      } else {
        const previewShot = path.join(output, phase + '-' + viewport.width + '-preview-b-plan.png');
        await page.screenshot({ path: previewShot, fullPage: true });
        row.screenshots.push(previewShot);
      }
    }

    await Promise.all(assetTasks);
    assert(evidence.asset_verification_errors.length === 0, 'Browser-served bytes or ETags failed source verification.');
    assert(evidence.served_assets.some((item) => item.path.endsWith('/assets/plan')), 'No real plan image was served.');
    assert(evidence.served_assets.some((item) => item.path.endsWith('/assets/axonometric')), 'No real axonometric image was served.');
    assert(evidence.served_assets.some((item) => item.path.endsWith('/assets/geometry')), 'No real geometry was served.');
    assert(evidence.blocked_external_requests.length === 0, 'Browser attempted a non-loopback network request.');
    assert(evidence.mutating_api_requests.length === 0, 'Browser attempted an API mutation.');
    assert(evidence.page_errors.length === 0, 'Chromium reported a page error.');
    if (phase === 'after') assert(evidence.viewports.every((item) => !item.overflow_detected), 'Sidebar overflow remains after P0 patch.');

    for (const row of evidence.viewports) {
      for (const screenshot of row.screenshots) {
        const bytes = fs.readFileSync(screenshot);
        evidence.screenshots.push({ file: screenshot, bytes: bytes.length, sha256: hash(bytes) });
      }
    }
    evidence.status = phase === 'before' ? 'PASS_BEFORE_PATCH_MEASURED' : 'PASS_AFTER_PATCH';
    exitCode = 0;
  } catch (error) {
    evidence.error = { type: error.name || 'Error', message: error.message || String(error) };
    evidence.status = 'FAIL';
  } finally {
    exitCode = await finalizeRun(evidence, output, exitCode, {
      children: [viteProcess, apiProcess].filter(Boolean),
      browser,
    });
  }
  process.exitCode = exitCode;
  return exitCode;
}

if (require.main === module) {
  main().catch((error) => {
    process.stderr.write((error.stack || error.message) + '\n');
    process.exitCode = 1;
  });
}

module.exports = { finalizeRun, stopOwned, processIdentity, isUrbanDesignRuntimePath, assertDisposableDatabase };
