/* 官网副本：原文件由 anatomy 插图代理产出（switchboard.live.js）。外面包了一层，把 requestAnimationFrame 换成 figs.js 的共享节拍器
   （同屏多个动效时轮流隔帧推进），节拍器不在时退回浏览器原生实现；IntersectionObserver 的边距从 120px 收到 0（真正滚出视口就停）。 */
(function (requestAnimationFrame, cancelAnimationFrame) {
/* 接线台插图的动效（作用于内联的 svg[data-swb]）。
   一个循环约 7.2 s：用户线路灯闪（卡住了）→ 扳下那把键 → 客服席位灯亮蓝、用户灯灭（接到真人）→ 停留 → 键回位、灯灭 → 稍停。
   静态 SVG 停在「已接通」那一刻，挂载时从同一刻开始，不会跳。
   滚出视口即停（IntersectionObserver），prefers-reduced-motion: reduce 下保持静态；带 data-swb-still 的 SVG 不动。
   之后才插入的 SVG 调 SwitchboardFigure.mount(svg)。 */
(function () {
  var still = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : { matches: false };
  var CYCLE = 7.2;
  var START = 3.0; // 已接通的停留段，与静态图一致
  var mounted = [];

  function easeOutBack(x) {
    var c1 = 1.25, c3 = c1 + 1;
    return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2);
  }
  function easeInOut(x) {
    return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
  }
  function clamp01(x) { return x < 0 ? 0 : x > 1 ? 1 : x; }

  // 某一时刻的状态：键的前倾角（度）、用户灯、席位灯
  function stateAt(t, rest) {
    var deg = 0, user = "", agent = "";
    if (t < 2.0) {
      user = (t % 0.5) < 0.28 ? "call" : "";
    } else if (t < 2.45) {
      deg = rest * easeOutBack(clamp01((t - 2.0) / 0.45));
      if (t < 2.28) user = "call";
      else agent = "lit";
    } else if (t < 5.8) {
      deg = rest;
      agent = "lit";
    } else if (t < 6.3) {
      deg = rest * (1 - easeInOut(clamp01((t - 5.8) / 0.5)));
      if (t < 5.92) agent = "lit";
    }
    return { deg: deg, user: user, agent: agent };
  }

  function mount(svg) {
    if (!svg || svg.__swb) return svg && svg.__swb;
    var data;
    try { data = JSON.parse(svg.getAttribute("data-swb")); } catch (e) { return null; }
    var rodOut = svg.querySelector('[data-part="rod"]');
    var rodIn = svg.querySelector('[data-part="rod-in"]');
    var knob = svg.querySelector('[data-part="knob"]');
    var user = svg.querySelector('[data-lamp="user"]');
    var agent = svg.querySelector('[data-lamp="agent"]');
    if (!rodOut || !rodIn || !knob || !user || !agent) return null;

    var reach = function (deg, len) {
      var r = (deg * Math.PI) / 180, s = Math.sin(r), c = Math.cos(r);
      return [data.pivot[0] + len * (s * data.ey[0] + c * data.ez[0]), data.pivot[1] + len * (s * data.ey[1] + c * data.ez[1])];
    };
    var home = reach(data.rest, data.len);
    var last = { deg: data.rest, user: "", agent: "lit" };

    function draw(s) {
      if (Math.abs(s.deg - last.deg) > 0.01) {
        var k = reach(s.deg, data.len);
        knob.setAttribute("transform", "translate(" + (k[0] - home[0]).toFixed(2) + " " + (k[1] - home[1]).toFixed(2) + ")");
        var tip = reach(s.deg, data.rod);
        var d = "M" + data.pivot[0] + " " + data.pivot[1] + "L" + tip[0].toFixed(2) + " " + tip[1].toFixed(2);
        rodOut.setAttribute("d", d);
        rodIn.setAttribute("d", d);
        last.deg = s.deg;
      }
      if (s.user !== last.user) { user.setAttribute("data-on", s.user); last.user = s.user; }
      if (s.agent !== last.agent) { agent.setAttribute("data-on", s.agent); last.agent = s.agent; }
    }

    var clock = START, frame = 0, prev = 0, visible = false, running = true;
    function tick(now) {
      var dt = prev ? Math.min((now - prev) / 1000, 1 / 30) : 1 / 60;
      prev = now;
      clock = (clock + dt) % CYCLE;
      draw(stateAt(clock, data.rest));
      frame = visible && running && !still.matches ? requestAnimationFrame(tick) : 0;
    }
    function start() {
      running = true;
      if (!frame && visible && !still.matches && !svg.hasAttribute("data-swb-still")) { prev = 0; frame = requestAnimationFrame(tick); }
    }
    function stop() {
      running = false;
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
    }
    var io = null;
    if ("IntersectionObserver" in window) {
      io = new IntersectionObserver(function (entries) {
        visible = entries[entries.length - 1].isIntersecting;
        if (visible && running) start(); else if (frame) { cancelAnimationFrame(frame); frame = 0; }
      }, { rootMargin: "0px" });
      io.observe(svg);
    } else {
      visible = true;
      start();
    }
    var onMotion = function () {
      if (still.matches) { if (frame) cancelAnimationFrame(frame); frame = 0; clock = START; draw(stateAt(START, data.rest)); }
      else if (running) start();
    };
    if (still.addEventListener) still.addEventListener("change", onMotion);
    var api = {
      start: start,
      stop: stop,
      destroy: function () {
        stop();
        if (io) io.disconnect();
        if (still.removeEventListener) still.removeEventListener("change", onMotion);
        clock = START;
        draw(stateAt(START, data.rest));
        svg.__swb = null;
      },
    };
    svg.__swb = api;
    mounted.push(api);
    return api;
  }

  function mountAll() {
    var list = document.querySelectorAll("svg[data-swb]");
    for (var i = 0; i < list.length; i++) mount(list[i]);
  }
  window.SwitchboardFigure = {
    mount: mount,
    stopAll: function () { mounted.forEach(function (m) { m.stop(); }); },
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mountAll);
  else mountAll();
})();

})(window.__figRaf || window.requestAnimationFrame.bind(window), window.__figCaf || window.cancelAnimationFrame.bind(window));
