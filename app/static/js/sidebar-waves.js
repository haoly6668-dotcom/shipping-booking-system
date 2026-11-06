/* Vanta Waves: local assets, progressive enhancement, no navigation dependencies. */
'use strict';
(() => {
  const host = document.querySelector('[data-sidebar-sea]');
  if (!host) return;
  const sidebar = host.closest('.sidebar');
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const mobile = window.matchMedia('(max-width: 760px)');
  let effect = null;
  let libraries = null;
  let failed = false;
  const visible = () => !document.hidden && !reduced.matches &&
    (!mobile.matches || document.body.classList.contains('nav-open'));
  const script = source => new Promise((resolve, reject) => {
    const element = document.createElement('script');
    element.src = source;
    element.onload = resolve;
    element.onerror = reject;
    document.head.append(element);
  });
  const stop = () => {
    if (effect) { effect.destroy(); effect = null; }
    host.replaceChildren();
    sidebar.classList.remove('has-sidebar-waves');
  };
  const sync = async () => {
    if (!visible()) { stop(); return; }
    if (effect || failed) return;
    try {
      libraries ||= script('/static/vendor/three-0.134.0.min.js')
        .then(() => script('/static/vendor/vanta-waves-0.5.24.min.js'));
      await libraries;
      // Loading may finish after the panel is hidden or another event starts it.
      if (!visible() || effect) return;
      effect = window.VANTA.WAVES({
        el:host, THREE:window.THREE,
        mouseControls:false, touchControls:false, gyroControls:false,
        minWidth:100, minHeight:100, scale:1, scaleMobile:1,
        color:0x16465a, shininess:22, waveHeight:9, waveSpeed:.4, zoom:.85
      });
      sidebar.classList.add('has-sidebar-waves');
      const canvas = host.querySelector('canvas');
      if (canvas) canvas.addEventListener('webglcontextlost', () => {
        failed = true;
        stop();
      }, {once:true});
    } catch (_) {
      failed = true;
      stop(); // Retain the existing CSS ocean background on unsupported devices.
    }
  };
  reduced.addEventListener('change', sync);
  mobile.addEventListener('change', sync);
  document.addEventListener('visibilitychange', sync);
  new MutationObserver(sync).observe(document.body, {attributes:true, attributeFilter:['class']});
  window.addEventListener('pagehide', stop);
  window.addEventListener('pageshow', sync);
  sync();
})();
