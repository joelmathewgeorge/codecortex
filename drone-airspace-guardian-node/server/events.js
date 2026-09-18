// server/events.js
// A small in-memory event log the dashboard displays, plus a hook for
// broadcasting new events to connected WebSocket clients immediately.

let log = [];
let broadcastFn = null;

function setBroadcaster(fn) {
  broadcastFn = fn;
}

function pushEvent(message, type = 'info') {
  const event = {
    time: new Date().toLocaleTimeString('en-GB'),
    message,
    type, // info | success | warning | alert | critical
  };
  log.unshift(event);
  if (log.length > 50) log.pop();
  if (broadcastFn) broadcastFn({ type: 'event', event });
  return event;
}

function getLog() {
  return log;
}

module.exports = { setBroadcaster, pushEvent, getLog };
