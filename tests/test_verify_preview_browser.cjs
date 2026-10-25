'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const test = require('node:test');

test('cleanup EPERM writes OUTCOME_UNKNOWN receipt and exits nonzero', () => {
  const scriptPath = path.resolve(__dirname, '../scripts/verify_preview_browser.cjs');
  const outputDir = fs.mkdtempSync(path.join(os.tmpdir(), 'preview-cleanup-eperm-'));
  const bootstrap = `
    const { finalizeRun } = require(${JSON.stringify(scriptPath)});
    const evidence = { status: 'PASS_AFTER_PATCH', screenshots: [], viewports: [] };
    const children = [
      { name: 'api', pid: 21001, pgid: 21001, command: ['python', 'api.py'] },
      { name: 'vite', pid: 21002, pgid: 21002, command: ['node', 'vite.js'] },
    ];
    (async () => {
      process.exitCode = await finalizeRun(evidence, ${JSON.stringify(outputDir)}, 0, {
        children,
        stopChild: async (child) => {
          if (child.name === 'api') {
            const error = new Error('injected permission denial');
            error.code = 'EPERM';
            throw error;
          }
          return { status: 'STOPPED', signal: 'SIGTERM' };
        },
      });
    })().catch((error) => {
      process.stderr.write(error.stack + '\\n');
      process.exitCode = 1;
    });
  `;

  const result = spawnSync(process.execPath, ['-e', bootstrap], { encoding: 'utf8' });

  assert.equal(result.status, 1, result.stderr);
  const receiptPath = path.join(outputDir, 'receipt.json');
  assert.equal(fs.existsSync(receiptPath), true, 'cleanup receipt should be written');
  const receipt = JSON.parse(fs.readFileSync(receiptPath, 'utf8'));
  assert.equal(receipt.status, 'OUTCOME_UNKNOWN');
  assert.equal(receipt.exit_code, 1);
  assert.deepEqual(receipt.processes.map(({ name, pid, pgid, command, cleanup }) => ({
    name, pid, pgid, command, result: cleanup.status,
  })), [
    { name: 'api', pid: 21001, pgid: 21001, command: ['python', 'api.py'], result: 'OUTCOME_UNKNOWN' },
    { name: 'vite', pid: 21002, pgid: 21002, command: ['node', 'vite.js'], result: 'STOPPED' },
  ]);
  assert.equal(receipt.processes[0].cleanup.error_code, 'EPERM');
});
