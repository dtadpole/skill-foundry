/**
 * stealth.js — comprehensive anti-detection for Playwright
 * Covers: webdriver, plugins, languages, chrome object, permissions,
 *         WebGL, canvas noise, Notification, connection, battery,
 *         toString fingerprint, Turnstile/Cloudflare hardening
 */

(function() {
  'use strict';

  // ── 1. navigator.webdriver — must look native, not an own property ─────────
  try {
    // Step 1: remove any own property Playwright placed on navigator instance
    // (our previous patch or Playwright's injection)
    if (Object.getOwnPropertyDescriptor(navigator, 'webdriver')) {
      try { delete navigator.webdriver; } catch(e) {}
      // If non-configurable, redefine with native-looking getter
      if (Object.getOwnPropertyDescriptor(navigator, 'webdriver')) {
        const nativeGetter = function get() { return undefined; };
        nativeGetter.toString = () => 'function get webdriver() { [native code] }';
        Object.defineProperty(navigator, 'webdriver', {
          get: nativeGetter, configurable: true, enumerable: false,
        });
      }
    }

    // Step 2: override Navigator.prototype so prototype chain looks native
    const protoGetter = function get() { return undefined; };
    // Make toString look native
    Object.defineProperty(protoGetter, 'name', { value: 'get webdriver', configurable: true });
    protoGetter.toString = () => 'function get webdriver() { [native code] }';
    Object.defineProperty(Navigator.prototype, 'webdriver', {
      get: protoGetter,
      configurable: true,
      enumerable: false,
    });
  } catch(e) {}

  // ── 2. Plugins — mimic real Chrome ─────────────────────────────────────────
  try {
    const pluginData = [
      { name: 'Chrome PDF Plugin',   filename: 'internal-pdf-viewer',           description: 'Portable Document Format',   suffixes: 'pdf' },
      { name: 'Chrome PDF Viewer',   filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '',                        suffixes: 'pdf' },
      { name: 'Native Client',       filename: 'internal-nacl-plugin',           description: '',                          suffixes: '' },
    ];
    const makePlugin = (d) => {
      const mime = { type: 'application/x-google-chrome-pdf', suffixes: d.suffixes, description: d.description, enabledPlugin: null };
      const plugin = Object.create(Plugin.prototype);
      Object.defineProperties(plugin, {
        name:        { get: () => d.name },
        filename:    { get: () => d.filename },
        description: { get: () => d.description },
        length:      { get: () => 1 },
        0:           { get: () => mime },
        item:        { value: (i) => i === 0 ? mime : null },
        namedItem:   { value: (n) => null },
      });
      mime.enabledPlugin = plugin;
      return plugin;
    };
    const plugins = pluginData.map(makePlugin);
    const fakePluginArray = Object.create(PluginArray.prototype);
    plugins.forEach((p, i) => { fakePluginArray[i] = p; });
    Object.defineProperties(fakePluginArray, {
      length:    { get: () => plugins.length },
      item:      { value: (i) => plugins[i] || null },
      namedItem: { value: (n) => plugins.find(p => p.name === n) || null },
      refresh:   { value: () => {} },
      [Symbol.iterator]: { value: function*() { yield* plugins; } },
    });
    Object.defineProperty(navigator, 'plugins', { get: () => fakePluginArray, configurable: true });
  } catch(e) {}

  // ── 3. Languages ────────────────────────────────────────────────────────────
  try {
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'], configurable: true });
  } catch(e) {}

  // ── 4. window.chrome — full realistic object ────────────────────────────────
  try {
    const chrome = {
      app: {
        isInstalled: false,
        getDetails:  () => null,
        getIsInstalled: () => false,
        runningState: () => 'cannot_run',
        InstallState:  { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
        RunningState:  { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' },
      },
      csi:       () => ({ startE: Date.now(), onloadT: Date.now(), pageT: 1000 + Math.random() * 200, tran: 15 }),
      loadTimes: () => ({
        requestTime:        Date.now() / 1000 - 1,
        startLoadTime:      Date.now() / 1000 - 0.9,
        commitLoadTime:     Date.now() / 1000 - 0.5,
        finishDocumentLoadTime: Date.now() / 1000 - 0.1,
        finishLoadTime:     Date.now() / 1000,
        firstPaintTime:     Date.now() / 1000 - 0.4,
        firstPaintAfterLoadTime: 0,
        navigationType:     'Other',
        wasFetchedViaSpdy:  false,
        wasNpnNegotiated:   false,
        npnNegotiatedProtocol: 'http/1.1',
        wasAlternateProtocolAvailable: false,
        connectionInfo:     'http/1.1',
      }),
      runtime: {
        PlatformOs:   { MAC: 'mac', WIN: 'win', ANDROID: 'android', CROS: 'cros', LINUX: 'linux', OPENBSD: 'openbsd' },
        PlatformArch: { ARM: 'arm', ARM64: 'arm64', X86_32: 'x86-32', X86_64: 'x86-64', MIPS: 'mips', MIPS64: 'mips64' },
        PlatformNaclArch: { ARM: 'arm', X86_32: 'x86-32', X86_64: 'x86-64' },
        RequestUpdateCheckStatus: { THROTTLED: 'throttled', NO_UPDATE: 'no_update', UPDATE_AVAILABLE: 'update_available' },
        OnInstalledReason: { INSTALL: 'install', UPDATE: 'update', CHROME_UPDATE: 'chrome_update', SHARED_MODULE_UPDATE: 'shared_module_update' },
        OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' },
      },
    };
    if (!window.chrome) {
      window.chrome = chrome;
    } else {
      Object.assign(window.chrome, chrome);
    }
  } catch(e) {}

  // ── 5. navigator.permissions — realistic query ──────────────────────────────
  try {
    const originalQuery = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = (params) => {
      if (params && params.name === 'notifications') {
        return Promise.resolve({ state: Notification.permission, onchange: null });
      }
      return originalQuery(params);
    };
  } catch(e) {}

  // ── 6. Notification permission ──────────────────────────────────────────────
  try {
    Object.defineProperty(Notification, 'permission', { get: () => 'default', configurable: true });
  } catch(e) {}

  // ── 7. WebGL — realistic Intel Mac fingerprint ──────────────────────────────
  try {
    const patchWebGL = (ctx) => {
      const getParam = ctx.prototype.getParameter.bind(ctx.prototype);
      ctx.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return 'Intel Inc.';
        if (parameter === 37446) return 'Intel Iris Pro OpenGL Engine';
        return getParam.call(this, parameter);
      };
    };
    patchWebGL(WebGLRenderingContext);
    if (typeof WebGL2RenderingContext !== 'undefined') patchWebGL(WebGL2RenderingContext);
  } catch(e) {}

  // ── 8. Canvas — subtle noise to defeat fingerprinting ──────────────────────
  try {
    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(type, ...args) {
      const ctx = this.getContext('2d');
      if (ctx) {
        const imgData = ctx.getImageData(0, 0, this.width, this.height);
        // Add imperceptible noise
        for (let i = 0; i < imgData.data.length; i += 4096) {
          imgData.data[i] = imgData.data[i] ^ 1;
        }
        ctx.putImageData(imgData, 0, 0);
      }
      return origToDataURL.call(this, type, ...args);
    };
  } catch(e) {}

  // ── 9. navigator.connection ─────────────────────────────────────────────────
  try {
    if (!navigator.connection) {
      Object.defineProperty(navigator, 'connection', {
        get: () => ({
          downlink:          10,
          effectiveType:     '4g',
          rtt:               50,
          saveData:          false,
          type:              'wifi',
          onchange:          null,
          addEventListener:  () => {},
          removeEventListener: () => {},
        }),
        configurable: true,
      });
    }
  } catch(e) {}

  // ── 10. navigator.hardwareConcurrency & deviceMemory ───────────────────────
  try {
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8, configurable: true });
    Object.defineProperty(navigator, 'deviceMemory',        { get: () => 8, configurable: true });
  } catch(e) {}

  // ── 11. screen properties ───────────────────────────────────────────────────
  try {
    Object.defineProperty(screen, 'colorDepth',  { get: () => 24, configurable: true });
    Object.defineProperty(screen, 'pixelDepth',  { get: () => 24, configurable: true });
  } catch(e) {}

  // ── 12. Remove automation artifacts ────────────────────────────────────────
  try {
    // Remove Playwright/CDP markers
    const markers = ['__playwright', '__pw_manual', '__PW_inspect__', '__selenium',
                     '_phantom', 'callPhantom', '__nightmare', '__phantomas',
                     'domAutomation', 'domAutomationController'];
    markers.forEach(m => { try { delete window[m]; } catch(e) {} });

    // Remove cdc_ prefixed keys (Chrome DevTools Protocol artifacts)
    Object.keys(window).forEach(k => {
      if (k.startsWith('cdc_') || k.startsWith('$cdc_')) {
        try { delete window[k]; } catch(e) {}
      }
    });
  } catch(e) {}

  // ── 13. Function.prototype.toString — prevent native code detection ─────────
  try {
    const nativeToString = Function.prototype.toString;
    const patched = new WeakSet();
    Function.prototype.toString = function() {
      if (patched.has(this)) return `function ${this.name || ''}() { [native code] }`;
      return nativeToString.call(this);
    };
    patched.add(Function.prototype.toString);
  } catch(e) {}

  // ── 14. iframe: propagate webdriver fix ────────────────────────────────────
  try {
    const origDescriptor = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'contentWindow');
    if (origDescriptor) {
      Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
        get: function() {
          const win = origDescriptor.get.call(this);
          if (win) {
            try { Object.defineProperty(win.navigator, 'webdriver', { get: () => undefined, configurable: true }); } catch(e) {}
          }
          return win;
        },
        configurable: true,
      });
    }
  } catch(e) {}

  // ── 15. Cloudflare Turnstile — behave like real browser ────────────────────
  // Ensure window.performance looks complete
  try {
    if (!window.performance.memory) {
      Object.defineProperty(window.performance, 'memory', {
        get: () => ({
          jsHeapSizeLimit:  2172649472,
          totalJSHeapSize:  20000000 + Math.floor(Math.random() * 5000000),
          usedJSHeapSize:   15000000 + Math.floor(Math.random() * 3000000),
        }),
        configurable: true,
      });
    }
  } catch(e) {}

  // navigator.maxTouchPoints — desktop = 0
  try {
    Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0, configurable: true });
  } catch(e) {}

  // navigator.vendor
  try {
    Object.defineProperty(navigator, 'vendor', { get: () => 'Google Inc.', configurable: true });
  } catch(e) {}

})();
