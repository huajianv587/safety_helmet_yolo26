declare global {
  interface Window {
    __HELMET_API_BASE_URL__?: string;
    __helmetReactLegacyBootPromise__?: Promise<void>;
    __helmetReactCursorCleanup__?: (() => void) | null;
    __helmetReactLegacyScriptLoaded__?: boolean;
  }
}

function resolveApiBase() {
  const configured = process.env.REACT_APP_API_URL?.trim();
  if (configured) {
    return configured.replace(/\/+$/, '');
  }

  const { protocol, hostname, port, origin } = window.location;
  const isLocalDev = (hostname === 'localhost' || hostname === '127.0.0.1') && (port === '3000' || port === '3002');
  if (isLocalDev) {
    return `${protocol}//${hostname}:8112`;
  }

  return origin.replace(/\/+$/, '');
}

function initCursorEffects() {
  if (window.__helmetReactCursorCleanup__) {
    return;
  }

  const dot = document.getElementById('c-dot');
  const ring = document.getElementById('c-ring');
  const pulse = document.getElementById('c-pulse');
  const finePointerQuery = window.matchMedia('(hover: hover) and (pointer: fine)');
  const interactiveSelector = 'a,button,input,select,textarea,[role=button],.nav-item,.btn,.topbar-chip,.status-filter,.chip-button,.camera-selector,.live-camera-card';

  if (!dot || !ring || !pulse) {
    return;
  }

  const listeners: Array<() => void> = [];
  const setCursorDisplay = (visible: boolean) => {
    document.body.classList.toggle('custom-cursor', visible);
    [dot, ring, pulse].forEach((node) => {
      node.style.display = visible ? '' : 'none';
    });
  };

  if (!finePointerQuery.matches) {
    setCursorDisplay(false);
    window.__helmetReactCursorCleanup__ = () => {};
    return;
  }

  setCursorDisplay(true);

  let mx = 0;
  let my = 0;
  let rx = 0;
  let ry = 0;
  let pressTimer = 0;
  let frame = 0;

  const movePulse = (x: number, y: number) => {
    pulse.style.left = `${x}px`;
    pulse.style.top = `${y}px`;
  };

  const burstPulse = (x: number, y: number) => {
    movePulse(x, y);
    pulse.classList.remove('burst');
    void pulse.offsetWidth;
    pulse.classList.add('burst');
  };

  const onMouseMove = (event: MouseEvent) => {
    mx = event.clientX;
    my = event.clientY;
    dot.style.left = `${mx}px`;
    dot.style.top = `${my}px`;
    movePulse(mx, my);
  };

  const onMouseOver = (event: MouseEvent) => {
    const target = event.target as Element | null;
    const interactive = target?.closest(interactiveSelector);
    document.body.classList.toggle('c-hover', Boolean(interactive));
  };

  const onMouseOut = (event: MouseEvent) => {
    if (event.relatedTarget) {
      return;
    }
    document.body.classList.remove('c-hover');
  };

  const onMouseDown = (event: MouseEvent) => {
    if (event.button !== 0) {
      return;
    }
    document.body.classList.add('c-press');
    burstPulse(event.clientX, event.clientY);
    window.clearTimeout(pressTimer);
    pressTimer = window.setTimeout(() => {
      document.body.classList.remove('c-press');
    }, 180);
  };

  const onMouseUp = () => {
    document.body.classList.remove('c-press');
  };

  const onMediaChange = () => {
    if (finePointerQuery.matches) {
      setCursorDisplay(true);
      return;
    }
    setCursorDisplay(false);
    document.body.classList.remove('c-hover', 'c-press');
  };

  const lerp = () => {
    rx += (mx - rx) * 0.1;
    ry += (my - ry) * 0.1;
    ring.style.left = `${rx}px`;
    ring.style.top = `${ry}px`;
    frame = window.requestAnimationFrame(lerp);
  };

  document.addEventListener('mousemove', onMouseMove);
  document.addEventListener('mouseover', onMouseOver);
  document.addEventListener('mouseout', onMouseOut);
  document.addEventListener('mousedown', onMouseDown);
  document.addEventListener('mouseup', onMouseUp);
  finePointerQuery.addEventListener('change', onMediaChange);
  frame = window.requestAnimationFrame(lerp);

  listeners.push(() => document.removeEventListener('mousemove', onMouseMove));
  listeners.push(() => document.removeEventListener('mouseover', onMouseOver));
  listeners.push(() => document.removeEventListener('mouseout', onMouseOut));
  listeners.push(() => document.removeEventListener('mousedown', onMouseDown));
  listeners.push(() => document.removeEventListener('mouseup', onMouseUp));
  listeners.push(() => finePointerQuery.removeEventListener('change', onMediaChange));

  window.__helmetReactCursorCleanup__ = () => {
    listeners.forEach((dispose) => dispose());
    window.cancelAnimationFrame(frame);
    window.clearTimeout(pressTimer);
    document.body.classList.remove('custom-cursor', 'c-hover', 'c-press');
    window.__helmetReactCursorCleanup__ = null;
  };
}

export async function initLegacyConsole() {
  if (window.__helmetReactLegacyBootPromise__) {
    return window.__helmetReactLegacyBootPromise__;
  }

  window.__helmetReactLegacyBootPromise__ = (async () => {
    window.__HELMET_API_BASE_URL__ = window.__HELMET_API_BASE_URL__ || resolveApiBase();
    initCursorEffects();
    if (window.__helmetReactLegacyScriptLoaded__) {
      return;
    }

    await new Promise<void>((resolve, reject) => {
      const existing = document.querySelector('script[data-legacy-console="true"]') as HTMLScriptElement | null;
      if (existing) {
        existing.addEventListener('load', () => resolve(), { once: true });
        existing.addEventListener('error', () => reject(new Error('Failed to load legacy console script.')), { once: true });
        return;
      }

      const script = document.createElement('script');
      const publicUrl = process.env.PUBLIC_URL || '';
      script.type = 'module';
      script.async = true;
      script.dataset.legacyConsole = 'true';
      script.src = `${publicUrl}/js/app.js?v=1`;
      script.addEventListener('load', () => {
        window.__helmetReactLegacyScriptLoaded__ = true;
        resolve();
      }, { once: true });
      script.addEventListener('error', () => reject(new Error('Failed to load legacy console script.')), { once: true });
      document.body.appendChild(script);
    });
  })();

  return window.__helmetReactLegacyBootPromise__;
}
