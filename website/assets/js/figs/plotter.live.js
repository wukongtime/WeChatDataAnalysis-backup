/* 官网副本：原文件由 anatomy 插图代理产出（plotter.live.js）。外面包了一层，把 requestAnimationFrame 换成 figs.js 的共享节拍器
   （同屏多个动效时轮流隔帧推进），节拍器不在时退回浏览器原生实现；IntersectionObserver 的边距从 120px 收到 0（真正滚出视口就停）。 */
(function (requestAnimationFrame, cancelAnimationFrame) {
/* AI 工作台插图的循环小动作：龙门沿导轨在第 1 排与第 10 排之间来回滑行。
   作用于页面里内联的 <svg class="pf-plotter">；滚出视口即停，prefers-reduced-motion 下保持静止。 */
(() => {
  const still = window.matchMedia("(prefers-reduced-motion: reduce)");
  const ease = (t) => t * t * (3 - 2 * t);
  // 一圈 16 秒：从静止位滑到最前排，停一下，退回最后排，停一下，再回到静止位
  function keys(rest) {
    return [[0, rest], [4.6, 1], [6, 1], [12.6, 0], [14, 0], [16, rest]];
  }
  function shareAt(t, rest) {
    const list = keys(rest);
    const cycle = list[list.length - 1][0];
    const u = t % cycle;
    for (let i = 1; i < list.length; i++) {
      const [t0, a] = list[i - 1];
      const [t1, b] = list[i];
      if (u <= t1) return a + (b - a) * ease((u - t0) / (t1 - t0 || 1));
    }
    return rest;
  }
  function mount(svg) {
    const gantry = svg.querySelector('[data-part="gantry"]');
    if (!gantry || svg.__pfPlotter) return;
    svg.__pfPlotter = true;
    const [ax, ay] = gantry.getAttribute("data-axis").split(" ").map(Number);
    const rest = Number(gantry.getAttribute("data-rest"));
    let visible = false, frame = 0, last = 0, clock = 0;
    const place = (share) => gantry.setAttribute("transform", "translate(" + (ax * share).toFixed(2) + " " + (ay * share).toFixed(2) + ")");
    function tick(now) {
      const dt = last ? Math.min((now - last) / 1000, 1 / 30) : 1 / 60;
      last = now;
      clock += dt;
      place(shareAt(clock, rest));
      frame = visible && !still.matches && !document.hidden ? requestAnimationFrame(tick) : 0;
    }
    const run = () => { if (!frame && visible && !still.matches && !document.hidden) { last = 0; frame = requestAnimationFrame(tick); } };
    const stop = () => { if (frame) cancelAnimationFrame(frame); frame = 0; };
    const calm = () => { stop(); clock = 0; place(rest); };
    new IntersectionObserver((entries) => {
      visible = entries[entries.length - 1].isIntersecting;
      visible ? run() : stop();
    }, { rootMargin: "0px" }).observe(svg);
    document.addEventListener("visibilitychange", () => (document.hidden ? stop() : run()));
    still.addEventListener ? still.addEventListener("change", () => (still.matches ? calm() : run())) : null;
    if (still.matches) calm();
  }
  const all = () => document.querySelectorAll("svg.pf-plotter").forEach(mount);
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", all) : all();
  window.pfPlotterMount = all;
})();

})(window.__figRaf || window.requestAnimationFrame.bind(window), window.__figCaf || window.cancelAnimationFrame.bind(window));
