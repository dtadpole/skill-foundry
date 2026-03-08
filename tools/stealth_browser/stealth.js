// stealth.js — injected into every page to override automation fingerprints
// Covers: webdriver, plugins, languages, chrome object, permissions, WebGL

// 1. Hide navigator.webdriver
Object.defineProperty(navigator, 'webdriver', {
  get: () => undefined,
  configurable: true,
});

// 2. Fake plugins (real Chrome has ~3)
Object.defineProperty(navigator, 'plugins', {
  get: () => {
    const plugins = [
      { name: 'Chrome PDF Plugin',   filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'Chrome PDF Viewer',   filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
      { name: 'Native Client',       filename: 'internal-nacl-plugin', description: '' },
    ];
    plugins.item = (i) => plugins[i];
    plugins.namedItem = (name) => plugins.find(p => p.name === name) || null;
    plugins.refresh = () => {};
    Object.setPrototypeOf(plugins, PluginArray.prototype);
    return plugins;
  },
  configurable: true,
});

// 3. Languages
Object.defineProperty(navigator, 'languages', {
  get: () => ['en-US', 'en'],
  configurable: true,
});

// 4. window.chrome — must exist and look real
if (!window.chrome) {
  window.chrome = {
    app: { isInstalled: false, InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' }, RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' } },
    csi:       () => {},
    loadTimes: () => {},
    runtime:   {},
  };
}

// 5. Notification permissions — not denied (real users have 'default')
const originalQuery = window.Notification
  ? window.Notification.requestPermission
  : undefined;
if (originalQuery) {
  const desc = Object.getOwnPropertyDescriptor(Notification, 'permission');
  if (desc && desc.get) {
    Object.defineProperty(Notification, 'permission', {
      get: () => 'default',
      configurable: true,
    });
  }
}

// 6. WebGL vendor/renderer — mimic real hardware
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
  if (parameter === 37445) return 'Intel Inc.';           // UNMASKED_VENDOR_WEBGL
  if (parameter === 37446) return 'Intel Iris OpenGL Engine'; // UNMASKED_RENDERER_WEBGL
  return getParameter.call(this, parameter);
};

// 7. Remove common headless tells
delete window.__nightmare;
delete window._phantom;
delete window.callPhantom;
delete window.__phantomas;

// 8. iframe contentWindow.navigator.webdriver fix
const origContentWindow = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'contentWindow');
if (origContentWindow) {
  Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
    get: function() {
      const win = origContentWindow.get.call(this);
      if (win) {
        try {
          Object.defineProperty(win.navigator, 'webdriver', { get: () => undefined, configurable: true });
        } catch(e) {}
      }
      return win;
    },
    configurable: true,
  });
}
