/* 官网副本：原文件由 anatomy 插图代理产出（drawers.live.js）。外面包了一层，把 requestAnimationFrame 换成 figs.js 的共享节拍器
   （同屏多个动效时轮流隔帧推进），节拍器不在时退回浏览器原生实现；IntersectionObserver 的边距从 120px 收到 0（真正滚出视口就停）。 */
/* 另：停住与间歇阶段不逐帧调度、画面没变时不重复写 transform（原来视口内约每秒上千次属性写入）。 */
(function (requestAnimationFrame, cancelAnimationFrame) {
/* 九屉目录柜的动效：抽屉按 data-seq 的顺序轮流拉开、停住、推回。
   只作用于内联的 <svg class="fig-drawers">（<img> 里的静态图不动）。
   画家顺序：每个绘制项带 data-k（anatomy 的 A.settle 按真实几何解出的键），
   拉开中的那屉键值 = data-k + lift × share；顺序变了才重排 DOM。
   滚出视口即停；prefers-reduced-motion 下保持静态那一帧；带 data-still 的不自动播放。 */
(() => {
  const still = window.matchMedia("(prefers-reduced-motion: reduce)");
  const HOLD = 1.9; // 拉开后停留（秒）
  const REST = 0.35; // 推回后到下一屉开始前的间歇
  const TAU_OPEN = 0.2; // 临界阻尼弹簧的时间常数
  const TAU_CLOSE = 0.15;

  function mount(svg) {
    if (svg.__drawers) return svg.__drawers;
    const nums = (name) => svg.dataset[name].split(",").map(Number);
    const dir = nums("dir");
    const ext = nums("ext");
    const lift = nums("lift");
    const seq = nums("seq");
    const nodes = [...svg.querySelectorAll("g[data-k]")];
    if (!nodes.length) return null;
    const layer = nodes[0].parentNode;
    const items = nodes.map((el, i) => ({ el, i, k: Number(el.dataset.k), d: el.dataset.d === undefined ? -1 : Number(el.dataset.d), key: 0 }));
    const byDrawer = ext.map((_, d) => items.filter((it) => it.d === d));
    const labels = ext.map((_, d) => svg.querySelector(`.lab[data-d="${d}"]`));
    const state = { active: Number(svg.dataset.start), x: 1, v: 0, target: 1, phase: "hold", clock: 0 };
    let current = items.slice();
    let placedA = -1, placedX = NaN;

    function place() {
      const { active, x } = state;
      if (active === placedA && x === placedX) return; // 停住时画面不变：不重复写属性
      placedA = active; placedX = x;
      const dx = dir[0] * ext[active] * x;
      const dy = dir[1] * ext[active] * x;
      const moved = Math.abs(x) > 1e-4;
      for (const it of byDrawer[active]) {
        if (moved) it.el.setAttribute("transform", `translate(${dx.toFixed(2)} ${dy.toFixed(2)})`);
        else it.el.removeAttribute("transform");
      }
      for (const it of items) it.key = it.k + (it.d === active ? lift[active] * x : 0);
      const next = items.slice().sort((a, b) => a.key - b.key || a.i - b.i);
      if (next.some((it, n) => it !== current[n])) {
        const frag = document.createDocumentFragment();
        for (const it of next) frag.appendChild(it.el);
        layer.appendChild(frag);
        current = next;
      }
    }
    function light(d) {
      labels.forEach((lab, n) => lab && (n === d ? lab.setAttribute("data-on", "") : lab.removeAttribute("data-on")));
    }
    function set(active, share) {
      for (const it of byDrawer[state.active]) it.el.removeAttribute("transform");
      Object.assign(state, { active, x: share, v: 0, target: share, phase: share > 0 ? "hold" : "rest", clock: 0 });
      light(share > 0 ? active : -1);
      placedA = -1; // 上面刚清过 transform，强制重画
      place();
    }
    // 临界阻尼：x 跟到 target，速度连续，四个子步
    function spring(dt, tau) {
      const w = 1 / tau;
      for (let n = 0; n < 4; n++) {
        state.v += (w * w * (state.target - state.x) - 2 * w * state.v) * (dt / 4);
        state.x += state.v * (dt / 4);
      }
      if (Math.abs(state.target - state.x) < 1e-3 && Math.abs(state.v) < 1e-3) {
        state.x = state.target;
        state.v = 0;
        return false;
      }
      return true;
    }
    function step(dt) {
      state.clock += dt;
      if (state.phase === "hold" && state.clock > HOLD) Object.assign(state, { phase: "close", target: 0, clock: 0 });
      else if (state.phase === "close" && !spring(dt, TAU_CLOSE)) Object.assign(state, { phase: "rest", clock: 0 });
      else if (state.phase === "rest" && state.clock > REST) {
        for (const it of byDrawer[state.active]) it.el.removeAttribute("transform");
        const at = seq.indexOf(state.active);
        state.active = seq[(at + 1) % seq.length];
        Object.assign(state, { phase: "open", target: 1, x: 0, v: 0, clock: 0 });
        light(state.active);
      } else if (state.phase === "open" && !spring(dt, TAU_OPEN)) Object.assign(state, { phase: "hold", clock: 0 });
      place();
    }

    let frame = 0;
    let last = 0;
    let visible = false;
    const auto = svg.dataset.still === undefined;
    let sleepT = 0;
    function tick(now) {
      const dt = last ? Math.min((now - last) / 1000, 1 / 30) : 1 / 60;
      last = now;
      step(dt);
      // 拉开后停住、推回后的间歇：画面不动，不逐帧调度，睡到该动的那一刻
      if (state.phase === "hold" || state.phase === "rest") {
        const left = (state.phase === "hold" ? HOLD : REST) - state.clock;
        if (left > 0.05) { frame = 0; sleepT = setTimeout(() => { sleepT = 0; state.clock += left; run(); }, left * 1000); return; }
      }
      frame = visible && !still.matches ? requestAnimationFrame(tick) : 0;
    }
    function run() {
      if (!auto || frame || sleepT || !visible || still.matches) return;
      last = 0;
      frame = requestAnimationFrame(tick);
    }
    if (auto && "IntersectionObserver" in window) {
      new IntersectionObserver((entries) => {
        visible = entries[entries.length - 1].isIntersecting;
        if (visible) run();
      }, { rootMargin: "0px" }).observe(svg);
      // 运行中切到「减少动态」：停在一个完整拉开的画面上，不留半截
      still.addEventListener?.("change", () => (still.matches ? set(state.active, 1) : run()));
    }
    svg.__drawers = { set, state };
    return svg.__drawers;
  }

  const api = {
    mount,
    mountAll(root = document) {
      return [...root.querySelectorAll("svg.fig-drawers")].map(mount);
    },
    set(svg, active, share) {
      return mount(svg).set(active, share);
    },
  };
  window.WdaDrawers = api;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => api.mountAll());
  else api.mountAll();
})();

})(window.__figRaf || window.requestAnimationFrame.bind(window), window.__figCaf || window.cancelAnimationFrame.bind(window));
