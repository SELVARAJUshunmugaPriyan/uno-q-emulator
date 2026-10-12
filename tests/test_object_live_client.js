// Hardware-free scheduling checks for the browser client: node tests/test_object_live_client.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const elements = new Map();
const node = () => ({
  style: {}, value: '0.5', min: '0', max: '1', readyState: 4,
  videoWidth: 640, videoHeight: 480, classList: { add() {}, remove() {} },
  addEventListener() {}, appendChild() {}, replaceChildren() {},
  getContext: () => ({ drawImage() {} }), toDataURL: () => 'data:image/jpeg;base64,FRAME',
});
let requests = [], rendered = 0, stopped = 0;
const context = vm.createContext({
  console, setTimeout, clearTimeout, AbortController,
  HTMLMediaElement: { HAVE_CURRENT_DATA: 2 },
  WebUI: class { on_connect() {} on_message() {} on_disconnect() {} },
  window: { addEventListener() {} },
  document: {
    getElementById(id) { if (!elements.has(id)) elements.set(id, node()); return elements.get(id); },
    querySelector: () => node(), querySelectorAll: () => [], createElement: node,
  },
  fetch(url, options) {
    assert.equal(url, '/api/detect');
    assert.equal(options.method, 'POST');
    assert.equal(JSON.parse(options.body).image, 'FRAME');
    return new Promise((resolve, reject) => requests.push({ resolve, reject }));
  },
  rendered: () => rendered++, stopped: () => stopped++,
});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../app/object-detection/assets/app.js'), 'utf8'), context);
vm.runInContext(`
  cameraStream = {getTracks: () => [{stop: stopped}]};
  handleDetectionResult = rendered;
`, context);

const result = () => ({ ok: true, json: async () => ({ result_image: 'RESULT', detection_count: 1, processing_time: '2 ms' }) });
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
  const first = context.startLiveDetection();
  await context.startLiveDetection();
  assert.equal(requests.length, 1, 'Duplicate start must not enqueue a second frame');
  context.stopLiveDetection();
  requests.shift().resolve(result());
  await first;
  assert.equal(rendered, 0, 'Late result after stop must not update the UI');

  const second = context.startLiveDetection();
  assert.equal(requests.length, 1);
  requests.shift().resolve(result());
  await pause(150);
  assert.equal(rendered, 1);
  assert.equal(requests.length, 1, 'Next frame follows completion of previous inference');
  context.stopCamera();
  requests.shift().resolve(result());
  await second;
  assert.equal(stopped, 1, 'Camera tracks must stop');
  assert.equal(rendered, 1);
  assert.equal(requests.length, 0);

  vm.runInContext('cameraStream = {getTracks: () => []}', context);
  const third = context.startLiveDetection();
  requests.shift().reject(new Error('network offline'));
  await third;
  assert.equal(vm.runInContext('liveDetection', context), false);
  assert.equal(vm.runInContext('detectionPending', context), false);
  console.log('PASS: one frame in flight, stop/restart, late-result suppression, camera release, network failure');
})().catch(error => { console.error(error); process.exitCode = 1; });
