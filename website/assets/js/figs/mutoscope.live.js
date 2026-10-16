/* 官网副本：原文件由 anatomy 插图代理产出（mutoscope.live.js）。外面包了一层，把 requestAnimationFrame 换成 figs.js 的共享节拍器
   （同屏多个动效时轮流隔帧推进），节拍器不在时退回浏览器原生实现；IntersectionObserver 的边距从 120px 收到 0（真正滚出视口就停）。 */
/* 另：静止段（约 6 秒）不再逐帧调度节拍，改用一次 setTimeout 睡到起摇。 */
(function (requestAnimationFrame, cancelAnimationFrame) {
/* 手摇翻页观片机 · 动效脚本（由 build.mjs 生成）
   用法：把 mutoscope.svg 的内容内联进页面，再引入本脚本；它会找到所有 svg.fig-muto 并让它们动起来。
   摇柄匀速转一圈翻 8 张卡（小黄脸眨眼、大笑、吐舌），停一会儿再来；卷轴跟着转，计数盘指针每张跳一格。
   滚出视口即停；系统开启「减少动态效果」时保持静态图。手动初始化：window.MutoscopeLive.init(svgElement)。 */
(() => {
  const D = {"P":{"origin":[264.68966367527685,316.00598933761313],"scale":2.820164288868924,"azimuth":47,"elevation":30},"cards":109,"axis":[-1,31],"drum":[24.52,9.9,18.85],"arm":{"s0":36.6,"s1":38.8,"L":15,"poly":[[-3.4,0],[-3.31,-0.76],[-3.06,-1.48],[-2.66,-2.12],[-2.12,-2.66],[-1.48,-3.06],[-0.76,-3.31],[0,-3.4],[15,-2.5],[15.56,-2.44],[16.08,-2.25],[16.56,-1.95],[16.95,-1.56],[17.25,-1.08],[17.44,-0.56],[17.5,0],[17.44,0.56],[17.25,1.08],[16.95,1.56],[16.56,1.95],[16.08,2.25],[15.56,2.44],[15,2.5],[0,3.4],[-0.76,3.31],[-1.48,3.06],[-2.12,2.66],[-2.66,2.12],[-3.06,1.48],[-3.31,0.76]]},"theta0":-40,"perCard":45,"dial":{"x":-14,"y":-8,"face":8.8,"top":73.05,"span":300},"sequence":[1,0,2,3,4,5,4,0]};
  const P = D.P;
  const RAD = Math.PI / 180;
  const a = P.azimuth * RAD, e = P.elevation * RAD;
  const sinA = Math.sin(a), cosA = Math.cos(a), sinE = Math.sin(e), cosE = Math.cos(e), K = P.scale * Math.sqrt(1.6);
  const iso = (p) => [P.origin[0] + (p[0] * sinA - p[1] * cosA) * K, P.origin[1] + ((p[0] * cosA + p[1] * sinA) * sinE - p[2] * cosE) * K];
  const t1 = (v) => (Math.round(v * 10) / 10).toFixed(1).replace(/\.0$/, "");
  const pathOf = (pts, closed) => pts.map((p, i) => (i ? "L" : "M") + t1(p[0]) + " " + t1(p[1])).join("") + (closed ? "Z" : "");
  const VIEW = [cosA * cosE, sinA * cosE, sinE];
  const LL = Math.hypot(sinA, cosA, 1.2), LIGHT = [-sinA / LL, cosA / LL, 1.2 / LL];
  const dot = (p, q) => p[0] * q[0] + p[1] * q[1] + p[2] * q[2];
  const band = (s) => (s < 0 ? 0 : s < 0.2 ? 1 : s < 0.42 ? 2 : s < 0.62 ? 3 : 4);
  const area = (r) => r.reduce((acc, p, i) => { const q = r[(i + 1) % r.length]; return acc + p[0] * q[1] - q[0] * p[1]; }, 0);
  const screenOriented = (r) => (area(r) < 0 ? r.slice().reverse() : r);
  function hull(points) {
    const s = points.slice().sort((p, q) => p[0] - q[0] || p[1] - q[1]);
    const cross = (o, p, q) => (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0]);
    const lo = [], up = [];
    for (const p of s) { while (lo.length > 1 && cross(lo[lo.length - 2], lo[lo.length - 1], p) <= 0) lo.pop(); lo.push(p); }
    for (let i = s.length - 1; i >= 0; i--) { const p = s[i]; while (up.length > 1 && cross(up[up.length - 2], up[up.length - 1], p) <= 0) up.pop(); up.push(p); }
    return lo.slice(0, -1).concat(up.slice(0, -1));
  }
  // 摇臂：沿 x 拉伸的跑道形棱柱（与 kit 的 prismOf 同一套算法）
  function arm(deg) {
    const t = deg * RAD, u = [0, Math.cos(t), Math.sin(t)], v = [0, -Math.sin(t), Math.cos(t)];
    const ring = area(D.arm.poly) > 0 ? D.arm.poly : D.arm.poly.slice().reverse();
    const n = ring.length;
    const w = (s, p) => [s, D.axis[0] + u[1] * p[0] + v[1] * p[1], D.axis[1] + u[2] * p[0] + v[2] * p[1]];
    const low = ring.map((p) => iso(w(D.arm.s0, p))), high = ring.map((p) => iso(w(D.arm.s1, p)));
    const buckets = [[], [], [], [], []], seen = [];
    for (let j = 0; j < n; j++) {
      const p0 = ring[j], p1 = ring[(j + 1) % n];
      const nx = [0, u[1] * (p1[1] - p0[1]) - v[1] * (p1[0] - p0[0]), u[2] * (p1[1] - p0[1]) - v[2] * (p1[0] - p0[0])];
      const l = Math.hypot(nx[1], nx[2]) || 1; nx[1] /= l; nx[2] /= l;
      const vis = dot(nx, VIEW) > 1e-6; seen.push(vis);
      if (vis) buckets[band(dot(nx, LIGHT))].push(pathOf([low[j], low[(j + 1) % n], high[(j + 1) % n], high[j]], true));
    }
    buckets[band(dot([1, 0, 0], LIGHT))].push(pathOf(high, true));
    const creases = [];
    for (let j = 0; j < n; j++) if (seen[j]) creases.push(pathOf([high[j], high[(j + 1) % n]]));
    const h = pathOf(hull(low.concat(high)), true);
    return { fill: h, outline: h, crease: creases.join(""), top: buckets[4].join(""), shades: buckets.slice(0, 4).map((b) => b.join("")) };
  }
  const spokes = (phase) => {
    let d = "";
    for (let i = 0; i < D.cards; i++) {
      const g = phase + (i / D.cards) * Math.PI * 2, c = Math.cos(g), s = Math.sin(g);
      d += pathOf([iso([D.drum[0], D.axis[0] + c * D.drum[1], D.axis[1] + s * D.drum[1]]), iso([D.drum[0], D.axis[0] + c * D.drum[2], D.axis[1] + s * D.drum[2]])]);
    }
    return d;
  };
  const needle = (n) => {
    const g = (-D.dial.span / 2 + (n / D.cards) * D.dial.span) * RAD, dx = Math.sin(g), dy = -Math.cos(g);
    return pathOf([iso([D.dial.x - dx * 2.2, D.dial.y - dy * 2.2, D.dial.top]), iso([D.dial.x + dx * (D.dial.face - 2.3), D.dial.y + dy * (D.dial.face - 2.3), D.dial.top])]);
  };
  const knobAt = (deg) => { const t = deg * RAD; return iso([0, D.axis[0] + D.arm.L * Math.cos(t), D.axis[1] + D.arm.L * Math.sin(t)]); };
  // 一轮：静止 → 3.6 s 内匀速转一圈（首尾各有 0.45 s 缓起缓停）翻 8 张 → 下一轮
  // 官网副本：静止段从 1.4 s 拉长到 6.4 s（便当盒里六台机器同屏，这台不抢戏）；play() 可立刻摇一圈
  const REST = 6.4, RUN = 3.6, RAMP = 0.45, LOOP = REST + RUN, PER_LOOP = 360;
  function turned(t) {
    const x = t % LOOP, loops = Math.floor(t / LOOP);
    if (x < REST) return loops * PER_LOOP;
    const r = x - REST, vmax = PER_LOOP / (RUN - RAMP);
    let d;
    if (r < RAMP) d = (vmax * r * r) / (2 * RAMP);
    else if (r < RUN - RAMP) d = (vmax * RAMP) / 2 + vmax * (r - RAMP);
    else { const q = RUN - r; d = PER_LOOP - (vmax * q * q) / (2 * RAMP); }
    return loops * PER_LOOP + d;
  }
  const FLIP = 0.2;
  function init(svg) {
    if (!svg || svg.__muto) return;
    svg.__muto = true;
    const still = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)");
    const q = (name) => svg.querySelector('[data-part="' + name + '"]');
    const armG = q("arm"), knob = q("knob"), spoke = q("spokes"), needleEl = q("needle");
    const back = q("card-back"), front = q("card-front"), flip = q("card-flip");
    if (!armG || !knob || !spoke || !needleEl || !front) return;
    const armPaths = {
      fill: armG.querySelector(".iso-fill"), top: armG.querySelector(".iso-top"), crease: armG.querySelector(".iso-crease"), outline: armG.querySelector(".iso-edge"),
      shades: [0, 1, 2, 3].map((i) => armG.querySelector('.iso-shade[data-shade="' + i + '"]')),
    };
    // 缺的色阶补上空 path（静态图只画了当时看得见的那几档）
    armPaths.shades = armPaths.shades.map((el, i) => {
      if (el) return el;
      const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
      p.setAttribute("class", "iso-shade"); p.setAttribute("data-shade", String(i));
      armG.insertBefore(p, armPaths.top); return p;
    });
    if (!armPaths.top) { armPaths.top = document.createElementNS("http://www.w3.org/2000/svg", "path"); armPaths.top.setAttribute("class", "iso-top"); armG.insertBefore(armPaths.top, armPaths.crease || armPaths.outline); }
    const pivot = Number(flip.getAttribute("data-pivot"));
    const k0 = knobAt(D.theta0);
    const href = (el, i) => el && el.setAttribute("href", "#mts-f" + i);
    let clock = 0, last = 0, raf = 0, visible = false, shown = -1, flipAt = -1, card = 0;
    function draw() {
      const deg = turned(clock), n = Math.floor(deg / D.perCard + 1e-6);
      const theta = D.theta0 - deg;
      const p = arm(theta);
      armPaths.fill.setAttribute("d", p.fill); armPaths.outline.setAttribute("d", p.outline);
      if (armPaths.crease) armPaths.crease.setAttribute("d", p.crease);
      armPaths.top.setAttribute("d", p.top);
      p.shades.forEach((d, i) => armPaths.shades[i].setAttribute("d", d));
      const kp = knobAt(theta);
      knob.setAttribute("transform", "translate(" + (kp[0] - k0[0]).toFixed(2) + " " + (kp[1] - k0[1]).toFixed(2) + ")");
      // 卷轴与摇柄同转（经内部减速）：每翻一张卡卷轴走 1/109 圈
      spoke.setAttribute("d", spokes((-(deg / D.perCard) * Math.PI * 2) / D.cards));
      if (n !== card) { card = n; flipAt = clock; }
      // 计数盘：每张卡跳一格（短促的缓动）；数满 109 张时扫回 0
      const wrap = card > 0 && card % D.cards === 0;
      const age = flipAt < 0 ? 1 : Math.min(1, (clock - flipAt) / (wrap ? 0.7 : 0.16));
      const ease = wrap ? age * age * (3 - 2 * age) : 1 - Math.pow(1 - age, 3);
      needleEl.setAttribute("d", needle(wrap ? D.cards * (1 - ease) : ((card - 1 + ease) % D.cards + D.cards) % D.cards));
      // 观察窗：当前卡向前下方翻倒，露出后面的下一张。翻过 n 张后窗里是 face(n)。
      const seq = D.sequence, L = seq.length;
      const face = (m) => (m <= 0 ? 0 : seq[(m - 1) % L]);
      const f = flipAt < 0 ? 1 : Math.min(1, (clock - flipAt) / FLIP);
      if (f < 1) {
        if (shown !== -card) { shown = -card; href(front, face(card - 1)); href(back, face(card)); }
        const sy = Math.cos(f * f * Math.PI / 2);
        flip.setAttribute("transform", "translate(0 " + pivot + ") scale(1 " + Math.max(0.001, sy).toFixed(3) + ") translate(0 " + -pivot + ")");
      } else if (shown !== card) {
        shown = card; href(front, face(card)); href(back, face(card + 1)); flip.removeAttribute("transform");
      }
    }
    let sleepT = 0;
    function tick(now) {
      const dt = last ? Math.min((now - last) / 1000, 1 / 30) : 1 / 60;
      last = now; clock += dt;
      // 静止段里画面不变（指针与翻卡在 0.8 s 内收尾）：不再逐帧调度，睡到本轮起摇那一刻再醒
      const x = clock % LOOP;
      if (x > 0.8 && x < REST) {
        raf = 0;
        sleepT = setTimeout(() => { sleepT = 0; clock += REST - (clock % LOOP); run(); }, (REST - x) * 1000);
        return;
      }
      draw();
      raf = visible ? requestAnimationFrame(tick) : 0;
    }
    const run = () => {
      if (sleepT) { clearTimeout(sleepT); sleepT = 0; }
      if (!raf && visible && !(still && still.matches)) { last = 0; raf = requestAnimationFrame(tick); }
    };
    if ("IntersectionObserver" in window) {
      new IntersectionObserver((entries) => { visible = entries[entries.length - 1].isIntersecting; if (visible) run(); }, { rootMargin: "0px" }).observe(svg);
    } else { visible = true; run(); }
    if (still && still.addEventListener) still.addEventListener("change", () => { if (still.matches) { cancelAnimationFrame(raf); raf = 0; clearTimeout(sleepT); sleepT = 0; } else run(); });
    // 立刻摇一圈：静止段里把时钟拨到本轮起摇的那一刻（角度不变，不会跳）；正在摇时不打断
    svg.__mutoPlay = () => {
      if (still && still.matches) return;
      const x = clock % LOOP;
      if (x < REST) clock += REST - x;
      run();
    };
  }
  const boot = () => document.querySelectorAll("svg.fig-muto").forEach(init);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
  window.MutoscopeLive = { init };
})();

})(window.__figRaf || window.requestAnimationFrame.bind(window), window.__figCaf || window.cancelAnimationFrame.bind(window));
