const HTTP_BASE = (window.__HELMET_API_BASE_URL__ || window.location.origin).replace(/\/+$/, '');

function websocketBase() {
  return HTTP_BASE.replace(/^http/i, 'ws');
}

export function createRealtimeChannel(topic, handlers = {}) {
  let socket = null;
  let reconnectTimer = 0;
  let heartbeatTimer = 0;
  let closed = false;

  const onMessage = handlers.onMessage || (() => {});
  const onOpen = handlers.onOpen || (() => {});
  const onClose = handlers.onClose || (() => {});

  function clearTimers() {
    if (reconnectTimer) window.clearTimeout(reconnectTimer);
    if (heartbeatTimer) window.clearInterval(heartbeatTimer);
    reconnectTimer = 0;
    heartbeatTimer = 0;
  }

  function scheduleReconnect() {
    if (closed) return;
    clearTimers();
    reconnectTimer = window.setTimeout(connect, 1800);
  }

  function connect() {
    if (closed || typeof WebSocket === 'undefined') return;
    try {
      socket = new WebSocket(`${websocketBase()}/ws/${encodeURIComponent(topic)}`);
    } catch {
      scheduleReconnect();
      return;
    }
    socket.addEventListener('open', () => {
      onOpen();
      heartbeatTimer = window.setInterval(() => {
        if (socket?.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: 'ping', topic }));
        }
      }, 20000);
    });
    socket.addEventListener('message', (event) => {
      try {
        onMessage(JSON.parse(event.data));
      } catch {
        // Ignore malformed frames during reconnects.
      }
    });
    socket.addEventListener('close', () => {
      onClose();
      scheduleReconnect();
    });
    socket.addEventListener('error', () => socket?.close());
  }

  connect();

  return {
    close() {
      closed = true;
      clearTimers();
      socket?.close();
      socket = null;
    },
  };
}
