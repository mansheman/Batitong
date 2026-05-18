/* batitong — front-end glue. Provides:
 *   - liveLog(engagementId): Alpine component that connects to the engagement
 *     WebSocket and appends events into <pre x-ref="body">.
 *   - csrfToken(): helper for HTMX / fetch.
 */

(function () {
  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }
  window.csrfToken = csrfToken;

  // Wire CSRF for HTMX automatically.
  document.addEventListener('htmx:configRequest', function (evt) {
    evt.detail.headers['X-CSRFToken'] = csrfToken();
  });

  function buildWsUrl(engagementId) {
    var proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return proto + '//' + window.location.host + '/ws/engagements/' + engagementId + '/';
  }

  function pad(n) { return n < 10 ? '0' + n : '' + n; }
  function ts() {
    var d = new Date();
    return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  }

  function liveLog(engagementId) {
    return {
      connected: false,
      socket: null,
      reconnectTimer: null,
      retries: 0,

      connect: function () {
        var self = this;
        try { self.socket = new WebSocket(buildWsUrl(engagementId)); }
        catch (err) { self._scheduleReconnect(); return; }

        self.socket.addEventListener('open', function () {
          self.connected = true;
          self.retries = 0;
          self._append('[ok] connected to engagement live stream');
        });

        self.socket.addEventListener('message', function (msg) {
          try {
            var data = JSON.parse(msg.data);
            self._render(data);
          } catch (e) {
            self._append('[warn] non-json frame: ' + msg.data);
          }
        });

        self.socket.addEventListener('close', function () {
          self.connected = false;
          self._append('[warn] disconnected, retrying…');
          self._scheduleReconnect();
        });

        self.socket.addEventListener('error', function () {
          self._append('[err] websocket error');
        });
      },

      _render: function (data) {
        var line = '';
        switch (data.event) {
          case 'connection.established':
            line = '[hello] watching engagement ' + (data.engagement_id || '');
            break;
          case 'execution.started':
            line = '[run] ' + data.tool + ' ' + JSON.stringify(data.arguments || {});
            break;
          case 'execution.output':
            line = data.chunk || '';
            break;
          case 'execution.finished':
            line = '[done] ' + data.execution_id + ' status=' + data.status +
                   ' (' + (data.duration_seconds || 0).toFixed(1) + 's)' +
                   (data.error ? ' err=' + data.error : '');
            break;
          default:
            line = '[' + (data.event || 'msg') + '] ' + JSON.stringify(data);
        }
        this._append(line);
      },

      _append: function (line) {
        var body = this.$refs.body;
        if (!body) return;
        var prefix = ts() + ' · ';
        body.textContent += (body.textContent ? '\n' : '') + prefix + line;
        body.scrollTop = body.scrollHeight;
      },

      _scheduleReconnect: function () {
        var self = this;
        if (self.reconnectTimer) return;
        self.retries += 1;
        var delay = Math.min(15000, 1000 * Math.pow(2, self.retries));
        self.reconnectTimer = setTimeout(function () {
          self.reconnectTimer = null;
          self.connect();
        }, delay);
      },
    };
  }

  window.liveLog = liveLog;

  /* Phase 2D — verb-first grouped sidebar.
   * Persists open/collapsed state per group in localStorage and auto-opens
   * the group that contains the currently active page so the highlighted
   * link is always visible on first paint. */
  var NAV_LS_KEY = 'batitong:nav:groups';
  var NAV_DEFAULT_OPEN = { operate: true, library: false, workflow: false };
  var NAV_GROUP_NAMESPACES = {
    operate: ['llm', 'engagements', 'playbooks'],
    library: ['mitre', 'mcp', 'targets'],
    workflow: ['approvals', 'credentials'],
  };

  function readNavLs() {
    try {
      var raw = localStorage.getItem(NAV_LS_KEY);
      if (!raw) return {};
      var parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch (e) { return {}; }
  }

  function writeNavLs(open) {
    try { localStorage.setItem(NAV_LS_KEY, JSON.stringify(open)); }
    catch (e) { /* private mode / disabled storage: silently ignore */ }
  }

  function readActiveNamespace() {
    var nav = document.querySelector('[data-component="sidebar-nav"]');
    return nav ? (nav.getAttribute('data-active-namespace') || '') : '';
  }

  function navGroups() {
    return {
      open: Object.assign({}, NAV_DEFAULT_OPEN),

      init: function () {
        var persisted = readNavLs();
        for (var k in NAV_DEFAULT_OPEN) {
          if (typeof persisted[k] === 'boolean') this.open[k] = persisted[k];
        }
        var ns = readActiveNamespace();
        for (var g in NAV_GROUP_NAMESPACES) {
          if (NAV_GROUP_NAMESPACES[g].indexOf(ns) !== -1) this.open[g] = true;
        }
      },

      toggle: function (key) {
        this.open[key] = !this.open[key];
        writeNavLs(this.open);
      },
    };
  }

  window.navGroups = navGroups;

  document.addEventListener('alpine:init', function () {
    if (window.Alpine) {
      window.Alpine.data('liveLog', liveLog);
      window.Alpine.data('navGroups', navGroups);
    }
  });
})();
