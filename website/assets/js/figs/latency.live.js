/* 官网副本：原文件由 anatomy 插图代理产出（latency.live.js）。外面包了一层，把 requestAnimationFrame 换成 figs.js 的共享节拍器
   （同屏多个动效时轮流隔帧推进），节拍器不在时退回浏览器原生实现；IntersectionObserver 的边距从 120px 收到 0（真正滚出视口就停）。 */
(function (requestAnimationFrame, cancelAnimationFrame) {
/* latency.live.js —— 「实时消息更低延迟」插图的循环动效（由 build.mjs 生成）
   用法：页面里内联 latency.svg 的内容，再引入本脚本；也可在插入 SVG 后调用 window.wdaLatency(svgElement)。
   胶囊沿三段透明管依次升起、横移、落下，落进收件台的那一刻延迟表指针轻跳，再落回低区。
   滚出视口即停；prefers-reduced-motion 下保持静态画面。 */
(() => {
  const D = {"legs":{"A":{"step":[0,-1.5357],"length":78},"B":{"step":[1.3974,0.5459],"length":77},"C":{"step":[0,1.5357],"length":46}},"cap":13.6,"rest":-100,"readings":[-100,-88,-106,-94,-84,-110,-97],"low":[-125,-58],"staticC":21};
  const still = matchMedia("(prefers-reduced-motion: reduce)");
  const ease = (t) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);
  const fall = (t) => t * t * (1.6 - 0.6 * t);
  const clamp01 = (t) => Math.max(0, Math.min(1, t));
  // 时间表（秒）：A 升起 → 箱内 → B 横移 → 箱内 → C 落下 → 到达 → 停留
  const T = { a0: 0, a1: 0.95, b0: 1.15, b1: 2.15, c0: 2.35, c1: 2.95, end: 4.6 };
  let uid = 0;
  function mount(svg) {
    if (!svg || svg.__wdaLatency) return;
    svg.__wdaLatency = true;
    // 同页多份内联时给 clipPath 改名，避免 id 冲突
    const n = uid++;
    if (n > 0) {
      svg.querySelectorAll("clipPath[id]").forEach((el) => {
        const old = el.id;
        el.id = old + "-" + n;
        svg.querySelectorAll('[clip-path="url(#' + old + ')"]').forEach((g) => g.setAttribute("clip-path", "url(#" + el.id + ")"));
      });
    }
    const legs = { A: svg.querySelectorAll('[data-leg="A"]'), B: svg.querySelectorAll('[data-leg="B"]'), C: svg.querySelectorAll('[data-leg="C"]') };
    const needle = svg.querySelector("[data-needle]");
    const place = (leg, s) => {
      const st = D.legs[leg].step;
      const off = s == null;
      const v = off ? "translate(-999 -999)" : "translate(" + (st[0] * s).toFixed(2) + " " + (st[1] * s).toFixed(2) + ")";
      // 闲置的胶囊不只挪出管外，还设为不可见（裁剪区之外也不留一个可见的包围盒）
      legs[leg].forEach((g) => { if (g.getAttribute("transform") !== v) { g.setAttribute("transform", v); g.setAttribute("visibility", off ? "hidden" : "visible"); } });
    };
    const span = (leg) => [-D.cap - 2, D.legs[leg].length + D.cap + 2];
    let clock = D.staticC ? T.c0 + (T.c1 - T.c0) * 0.62 : 0;
    let angle = D.rest, rate = 0, target = D.rest, reading = 0, arrived = false;
    let frame = 0, last = 0, visible = false;
    function draw() {
      const t = clock;
      const lerp = (leg, u) => { const [s0, s1] = span(leg); return s0 + (s1 - s0) * u; };
      place("A", t >= T.a0 && t <= T.a1 ? lerp("A", ease(clamp01((t - T.a0) / (T.a1 - T.a0)))) : null);
      place("B", t >= T.b0 && t <= T.b1 ? lerp("B", ease(clamp01((t - T.b0) / (T.b1 - T.b0)))) : null);
      place("C", t >= T.c0 && t <= T.c1 ? lerp("C", fall(clamp01((t - T.c0) / (T.c1 - T.c0)))) : null);
      if (needle) needle.setAttribute("transform", "rotate(" + angle.toFixed(2) + ")");
    }
    function tick(now) {
      const dt = last ? Math.min((now - last) / 1000, 1 / 30) : 1 / 60;
      last = now;
      clock += dt;
      if (!arrived && clock >= T.c1) {
        arrived = true;
        reading = (reading + 1) % D.readings.length;
        target = D.readings[reading];
        rate += 190; // 到达时的一次轻跳（朝高延迟方向），随后弹簧落回低区
      }
      if (clock >= T.end) { clock -= T.end; arrived = false; }
      const stiff = 150, drag = 13;
      for (let i = 0; i < 4; i++) { rate += ((target - angle) * stiff - rate * drag) * dt / 4; angle += rate * dt / 4; }
      draw();
      frame = visible && !still.matches ? requestAnimationFrame(tick) : 0;
    }
    const run = () => { if (!frame && visible && !still.matches) { last = 0; frame = requestAnimationFrame(tick); } };
    new IntersectionObserver((entries) => { visible = entries[entries.length - 1].isIntersecting; if (visible) run(); }, { rootMargin: "0px" }).observe(svg);
    still.addEventListener?.("change", run);
  }
  window.wdaLatency = mount;
  const boot = () => document.querySelectorAll("svg.wda-lat").forEach(mount);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();

})(window.__figRaf || window.requestAnimationFrame.bind(window), window.__figCaf || window.cancelAnimationFrame.bind(window));
