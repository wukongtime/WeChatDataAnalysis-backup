/* 便当盒的五张 anatomy 插图：内联 SVG + 各自的动效脚本（「注册送 1 天试用」格的礼物盒直接写在 index.html 里，不经这里）。
   - 插图文件在 assets/img/figs/（viewBox 已裁到「内容 + 动效包络」），动效在 assets/js/figs/*.live.js。
   - 便当盒接近视口、或页面空闲时才取，不拖慢开场；取不到就留白。
   - 五个动效共用一个 rAF 节拍器：同时在跑的超过两个时按「车道」轮流隔帧推进（每个约 30fps），
     各脚本自己负责滚出视口即停、prefers-reduced-motion 时静止。 */

/* ── 共享节拍器（live 脚本里的 requestAnimationFrame 被换成它） ── */
{
  const pend = new Map(), lane = new WeakMap();
  let seq = 0, lanes = 0, beat = 0, raf = 0;
  const pump = (now) => {
    raf = 0; beat++;
    const jobs = [...pend], k = jobs.length > 2 ? 2 : 1;
    for (const [id, cb] of jobs) {
      if (k > 1 && (lane.get(cb) + beat) % k) continue;
      pend.delete(id);
      try { cb(now); } catch (e) { queueMicrotask(() => { throw e; }); }
    }
    if (pend.size && !raf) raf = requestAnimationFrame(pump);
  };
  window.__figRaf = (cb) => {
    if (!lane.has(cb)) lane.set(cb, lanes++);
    pend.set(++seq, cb);
    if (!raf) raf = requestAnimationFrame(pump);
    return seq;
  };
  window.__figCaf = (id) => { pend.delete(id); };
}

/* key → 挂载函数（脚本都带重复挂载保护；脚本先于 SVG 到达时自动挂载落空，这里补挂） */
const FIGS = {
  drawers: (svg) => window.WdaDrawers && window.WdaDrawers.mount(svg),
  plotter: () => window.pfPlotterMount && window.pfPlotterMount(),
  mutoscope: (svg) => window.MutoscopeLive && window.MutoscopeLive.init(svg),
  latency: (svg) => window.wdaLatency && window.wdaLatency(svg),
  switchboard: (svg) => window.SwitchboardFigure && window.SwitchboardFigure.mount(svg),
};

const script = (src) => new Promise((ok, bad) => {
  const s = document.createElement("script");
  s.src = src; s.async = true; s.onload = ok; s.onerror = bad;
  document.head.appendChild(s);
});

async function fill(slot) {
  const k = slot.dataset.fig;
  try {
    const [text] = await Promise.all([
      fetch(`assets/img/figs/${k}.svg`).then((r) => { if (!r.ok) throw new Error(r.status); return r.text(); }),
      script(`assets/js/figs/${k}.live.js`),
    ]);
    slot.innerHTML = text; // 站内自有的静态插图
    const svg = slot.querySelector("svg");
    // 格子外层的按钮已经有完整的读屏标签；插图本身只是画面，不再让读屏把长长的机械说明再念一遍
    svg.setAttribute("focusable", "false");
    svg.setAttribute("aria-hidden", "true");
    svg.removeAttribute("role"); svg.removeAttribute("aria-label"); svg.removeAttribute("aria-labelledby");
    svg.querySelectorAll(":scope > title").forEach((t) => t.remove());
    FIGS[k](svg);
    requestAnimationFrame(() => slot.classList.add("is-in"));
  } catch (e) { /* 取不到就留白 */ }
}

export function loadFigs(onReady) {
  const slots = [...document.querySelectorAll(".tile-art[data-fig]")].filter((el) => FIGS[el.dataset.fig] && !el.firstElementChild);
  if (!slots.length) return;
  let go = false;
  const start = () => {
    if (go) return; go = true; io.disconnect();
    Promise.all(slots.map(fill)).then(() => onReady && onReady());
  };
  const io = new IntersectionObserver((es) => es.some((e) => e.isIntersecting) && start(), { rootMargin: "100% 0px" });
  slots.forEach((el) => io.observe(el));
  const idle = window.requestIdleCallback || ((f) => setTimeout(f, 1200));
  if (document.readyState === "complete") idle(start); else addEventListener("load", () => idle(start), { once: true });
}
