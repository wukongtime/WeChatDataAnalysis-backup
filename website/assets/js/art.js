/* 便当盒六个小格的插图：简化等轴测几何（方位 45°、仰角 30°）+ 四档平涂明暗 + 墨色细描边。
   与六个大格的 anatomy 插图（assets/img/figs/）共用一套色板；全部原创矢量，不搬任何微信素材。
   扁平约定：无投影、无光晕、无光泽高光；动效只动 transform / opacity，由 main.css 驱动，
   祖先带 .is-off（滚出视口）时暂停，prefers-reduced-motion 时静止。 */

const C = 0.8660254037844386, S = 0.5, RX = 1.2247449, RY = 0.7071068;
/* 深色模式的口子：色板一律写成 var(--k-…, 原色)。--k-* 只在深色下由 main.css 的便当盒一节定义（与五张 anatomy 插图共用一套深色色板），
   浅色下变量都没定义，取到的就是括号里的原色——计算结果与原来写死的一模一样。
   SVG 的 fill / stroke 属性不认 var()，出图时由 Iso.svg() 把这类属性挪进 style（见 styled）。
   表情（黄脸、眼睛、腮红）与键帽小图标是「画里的内容」，深浅同色，不走色板。 */
const k = (name, hex) => `var(--k-${name}, ${hex})`;
export const TONE = {
  ice: [k("ice-t", "#f2f8ff"), k("ice-3", "#e1eefc"), k("ice-2", "#cfe2f8"), k("ice-0", "#b8d4f2")],
  lav: [k("lav-t", "#f5f1ff"), k("lav-3", "#e7defd"), k("lav-2", "#d8cbfa"), k("lav-0", "#c4b2f3")],
  peach: [k("peach-t", "#fff4ea"), k("peach-3", "#ffe5cc"), k("peach-2", "#ffd1a1"), k("peach-0", "#f4b27a")],
  mint: [k("mint-t", "#effff9"), k("mint-3", "#d2f8ea"), k("mint-2", "#a9ffe0"), k("mint-0", "#7fdcbf")],
};
export const BLUE = k("blue", "#2f86f0");
/* 白：盘面 / 卡片这类「纸面」（深色下压成深色面，好让亮描边与刻度看得见）与高光面（深色下仍是全图最亮的那一档）分开写 */
const PAPER = k("face", "#fff"), HL = k("hl", "#fff");
/* 机件上的墨色小件（插针、表针、轴心、放大镜柄）：深色下换成浅墨；表情里的墨色（眼睛、嘴）不走这里 */
const INKP = k("ink", "#2f3350");
const I = TONE.ice, L = TONE.lav, P = TONE.peach, M = TONE.mint;
const styled = (s) => s.replace(/<[^>]+>/g, (tag) => {
  const css = [];
  const t = tag.replace(/\s(fill|stroke)="(var\([^"]+\))"/g, (_, p, v) => { css.push(`${p}:${v}`); return ""; });
  if (!css.length) return tag;
  return /\sstyle="/.test(t) ? t.replace(/\sstyle="/, ` style="${css.join(";")};`) : t.replace(/\s*(\/?)>$/, ` style="${css.join(";")}"$1>`);
});
const r2 = (n) => Math.round(n * 100) / 100;
let uid = 0;
const rad = (d) => (d * Math.PI) / 180;

/* ───────── 等轴测小引擎 ───────── */
class Iso {
  constructor() { this.s = ""; this.b = [1e9, 1e9, -1e9, -1e9]; }
  t(X, Y) { const b = this.b; if (X < b[0]) b[0] = X; if (X > b[2]) b[2] = X; if (Y < b[1]) b[1] = Y; if (Y > b[3]) b[3] = Y; }
  P(x, y, z = 0, track = true) { const X = (x - y) * C, Y = (x + y) * S - z; if (track) this.t(X, Y); return [X, Y]; }
  pts(a, track = true) { return a.map((p) => this.P(p[0], p[1], p[2] || 0, track).map(r2).join(",")).join(" "); }
  add(s) { this.s += s; return this; }
  open(a = "") { return this.add(`<g ${a}>`); }
  close() { return this.add("</g>"); }
  poly(a, fill, cls = "o") { return this.add(`<polygon points="${this.pts(a)}" fill="${fill}" class="${cls}"/>`); }
  line(a, b, cls = "d") { const [x1, y1] = this.P(...a), [x2, y2] = this.P(...b); return this.add(`<line x1="${r2(x1)}" y1="${r2(y1)}" x2="${r2(x2)}" y2="${r2(y2)}" class="${cls}"/>`); }
  /* 盒子：顶面最浅，+y 面（屏幕左前）次之，+x 面（屏幕右前）再次之；o.seam 在侧面顶沿下画一道倒角线，o.bevel 在顶面内缩一圈 */
  box(x, y, z, w, d, h, T, o = {}) {
    const z1 = z + h;
    this.poly([[x + w, y, z], [x + w, y + d, z], [x + w, y + d, z1], [x + w, y, z1]], o.r || T[2]);
    this.poly([[x, y + d, z], [x + w, y + d, z], [x + w, y + d, z1], [x, y + d, z1]], o.l || T[1]);
    this.poly([[x, y, z1], [x + w, y, z1], [x + w, y + d, z1], [x, y + d, z1]], o.t || T[0]);
    if (o.seam && h > 2.4) { const s = z1 - Math.min(1.3, h * .3); this.add(`<polyline points="${this.pts([[x, y + d, s], [x + w, y + d, s], [x + w, y, s]])}" fill="none" class="f"/>`); }
    if (o.bevel) { const k = o.bevel; this.add(`<polygon points="${this.pts([[x + k, y + k, z1], [x + w - k, y + k, z1], [x + w - k, y + d - k, z1], [x + k, y + d - k, z1]])}" fill="none" class="f"/>`); }
    return this;
  }
  /* 竖直圆柱：左右两半分档，外轮廓一笔描完，顶面椭圆 */
  cyl(x, y, z, r, h, T, o = {}) {
    const [X, Yb] = this.P(x, y, z), [, Yt] = this.P(x, y, z + h), rx = r * RX, ry = r * RY;
    this.t(X - rx, Yt - ry); this.t(X + rx, Yb + ry);
    const f = (n) => r2(n);
    this.add(`<path d="M${f(X - rx)} ${f(Yt)}V${f(Yb)}A${f(rx)} ${f(ry)} 0 0 0 ${f(X)} ${f(Yb + ry)}V${f(Yt + ry)}A${f(rx)} ${f(ry)} 0 0 1 ${f(X - rx)} ${f(Yt)}Z" fill="${o.l || T[1]}" class="n"/>`);
    this.add(`<path d="M${f(X)} ${f(Yt + ry)}V${f(Yb + ry)}A${f(rx)} ${f(ry)} 0 0 0 ${f(X + rx)} ${f(Yb)}V${f(Yt)}A${f(rx)} ${f(ry)} 0 0 1 ${f(X)} ${f(Yt + ry)}Z" fill="${o.r || T[2]}" class="n"/>`);
    this.add(`<path d="M${f(X - rx)} ${f(Yt)}V${f(Yb)}A${f(rx)} ${f(ry)} 0 0 0 ${f(X + rx)} ${f(Yb)}V${f(Yt)}" fill="none" class="o"/>`);
    return this.add(`<ellipse cx="${f(X)}" cy="${f(Yt)}" rx="${f(rx)}" ry="${f(ry)}" fill="${o.t || T[0]}" class="o"/>`);
  }
  /* 水平面上的圆（等轴测下是一只正椭圆） */
  ellZ(x, y, z, r, fill, cls = "o", extra = "") {
    const [X, Y] = this.P(x, y, z); this.t(X - r * RX, Y - r * RY); this.t(X + r * RX, Y + r * RY);
    return this.add(`<ellipse cx="${r2(X)}" cy="${r2(Y)}" rx="${r2(r * RX)}" ry="${r2(r * RY)}" fill="${fill}" class="${cls}"${extra}/>`);
  }
  /* 面坐标系：在零件的某个面上用 2D 坐标作画（u 向右、v 向下）。
     fy：+y 面（原点 = 面的左上角，u 沿 +x）；fx：+x 面（原点 = 面的左上角，u 沿 -y）；fz：顶面（原点 = 后角，u 沿 +x、v 沿 +y） */
  mY(x, y, z) { const [X, Y] = this.P(x, y, z, false); return `matrix(${C} ${S} 0 1 ${r2(X)} ${r2(Y)})`; }
  mX(x, y, z) { const [X, Y] = this.P(x, y, z, false); return `matrix(${C} ${-S} 0 1 ${r2(X)} ${r2(Y)})`; }
  mZ(x, y, z) { const [X, Y] = this.P(x, y, z, false); return `matrix(${C} ${S} ${-C} ${S} ${r2(X)} ${r2(Y)})`; }
  fy(x, y, z, w, h, body, a = "") { this.P(x, y, z); this.P(x + w, y, z - h); return this.add(`<g transform="${this.mY(x, y, z)}"${a}>${body}</g>`); }
  fx(x, y, z, w, h, body, a = "") { this.P(x, y, z); this.P(x, y - w, z - h); return this.add(`<g transform="${this.mX(x, y, z)}"${a}>${body}</g>`); }
  fz(x, y, z, w, d, body, a = "") { this.P(x, y, z); this.P(x + w, y + d, z); this.P(x + w, y, z); this.P(x, y + d, z); return this.add(`<g transform="${this.mZ(x, y, z)}"${a}>${body}</g>`); }
  svg(cls, pad = 4, defs = "") {
    const [x0, y0, x1, y1] = this.b;
    return `<svg class="iso ${cls}" viewBox="${r2(x0 - pad)} ${r2(y0 - pad)} ${r2(x1 - x0 + 2 * pad)} ${r2(y1 - y0 + 2 * pad)}" preserveAspectRatio="xMidYMid meet" aria-hidden="true" focusable="false">${defs ? `<defs>${defs}</defs>` : ""}${styled(this.s)}</svg>`;
  }
}

/* 世界坐标里沿某个轴平移，换算成屏幕位移（给 CSS 动画用） */
const along = (ax, t) => (ax === "x" ? [C * t, S * t] : ax === "y" ? [-C * t, S * t] : [0, -t]);
const mv = (ax, t) => { const [dx, dy] = along(ax, t); return `--tx:${r2(dx)}px;--ty:${r2(dy)}px`; };

/* 2D 小件 */
const ticks = (cx, cy, r0, r1, a0, a1, n, major, cls = "d", r1m) => {
  let s = "";
  for (let i = 0; i <= n; i++) {
    const a = rad(a0 + (a1 - a0) * i / n), m = major && i % major === 0, rr = m ? (r1m ?? r1 - 1.2) : r1;
    s += `<line x1="${r2(cx + r0 * Math.cos(a))}" y1="${r2(cy + r0 * Math.sin(a))}" x2="${r2(cx + rr * Math.cos(a))}" y2="${r2(cy + rr * Math.sin(a))}" class="${m ? "o" : cls}"/>`;
  }
  return s;
};
const rules = (x, y, w, n = 3, gap = 1.4) => Array.from({ length: n }, (_, i) => `<line x1="${x}" y1="${r2(y + i * gap)}" x2="${r2(x + w * (i === n - 1 ? .6 : 1))}" y2="${r2(y + i * gap)}" class="f"/>`).join("");

/* 底板：冰蓝系，顶面倒角、四角螺钉、前沿刻度尺 */
function plate(g, x, y, w, d, h = 5, ruler = true) {
  g.box(x, y, 0, w, d, h, I, { seam: true });
  const k = 2.2;
  g.add(`<polygon points="${g.pts([[x + k, y + k, h], [x + w - k, y + k, h], [x + w - k, y + d - k, h], [x + k, y + d - k, h]])}" fill="none" class="f"/>`);
  for (const [cx, cy] of [[x + 4.6, y + 4.6], [x + w - 4.6, y + 4.6], [x + w - 4.6, y + d - 4.6], [x + 4.6, y + d - 4.6]]) g.ellZ(cx, cy, h, .95, I[2], "d");
  if (ruler) {
    let s = "";
    for (let i = 0, xi = x + 10; xi <= x + w - 10 + .01; xi += 2.5, i++) {
      const a = g.P(xi, y + d - k, h), b = g.P(xi, y + d - k - (i % 5 === 0 ? 2.6 : 1.3), h);
      s += `<line x1="${r2(a[0])}" y1="${r2(a[1])}" x2="${r2(b[0])}" y2="${r2(b[1])}" class="${i % 5 === 0 ? "d" : "f"}"/>`;
    }
    g.add(s);
  }
}

/* ───────── 原创扁平表情（100×100 坐标，圆心 50,50）：几何圆脸 + 纯色五官，用在表情键盘的键帽上 ───────── */
const INK = "#2f3350", PINK = "#ff8fa3", CHEEK = "#ffb393", Y0 = "#ffc83d", Y1 = "#ffd866";
const faceBase = `<circle cx="50" cy="50" r="44" fill="${Y0}" class="o"/><circle cx="47.6" cy="47.2" r="40.4" fill="${Y1}" class="n"/>`;
const cheeks = `<ellipse cx="29" cy="61" rx="6.6" ry="4.2" fill="${CHEEK}"/><ellipse cx="71" cy="61" rx="6.6" ry="4.2" fill="${CHEEK}"/>`;
const eyesOpen = `<ellipse cx="37" cy="44" rx="4.4" ry="6.2" fill="${INK}"/><ellipse cx="63" cy="44" rx="4.4" ry="6.2" fill="${INK}"/>`;
const eyesHappy = `<path d="M30.5 47Q37 38 43.5 47M56.5 47Q63 38 69.5 47" fill="none" stroke="${INK}" stroke-width="3.6" stroke-linecap="round"/>`;
const mSmile = `<path d="M37 61Q50 72 63 61" fill="none" stroke="${INK}" stroke-width="3.6" stroke-linecap="round"/>`;
const mLaugh = `<path d="M32 57H68Q66 79 50 79Q34 79 32 57Z" fill="${INK}"/><path d="M36 57.4H64V61.4Q50 63 36 61.4Z" fill="#fff"/><path d="M40 73.5Q50 66 60 73.5Q56 79 50 79Q44 79 40 73.5Z" fill="${PINK}"/>`;
const wink = `<path d="M30.5 44.5Q37 49.5 43.5 44.5" fill="none" stroke="${INK}" stroke-width="3.6" stroke-linecap="round"/><ellipse cx="63" cy="44" rx="4.4" ry="6.2" fill="${INK}"/>`;
const mTongue = `<path d="M37 61Q50 67 63 61" fill="none" stroke="${INK}" stroke-width="3.6" stroke-linecap="round"/><path d="M43 63.6Q43 77.5 50 77.5Q57 77.5 57 63.6Q50 65.6 43 63.6Z" fill="${PINK}" class="o"/><path d="M50 65.2V72" stroke="#e66e86" stroke-width="1.6" stroke-linecap="round"/>`;
const eyesWow = `<circle cx="37" cy="43" r="5.4" fill="${INK}"/><circle cx="63" cy="43" r="5.4" fill="${INK}"/><path d="M29 31Q35 27 41 30M59 30Q65 27 71 31" fill="none" stroke="${INK}" stroke-width="3" stroke-linecap="round"/>`;
const mWow = `<ellipse cx="50" cy="66" rx="6.4" ry="8" fill="${INK}"/>`;

function emoji(mode = "smile") {
  const F = { smile: eyesOpen + mSmile, laugh: eyesHappy + mLaugh, tongue: wink + mTongue, wow: eyesWow + mWow, happy: eyesHappy + mSmile };
  return `<g>${faceBase}${mode === "wow" ? "" : cheeks}${F[mode] || F.smile}</g>`;
}

/* 键帽上的小图（12×12 坐标）：表情与老表情里那类小物件，全部原创几何 */
const KEYICON = {
  smile: () => `<g transform="translate(1 1) scale(.1)">${emoji("smile")}</g>`,
  laugh: () => `<g transform="translate(1 1) scale(.1)">${emoji("laugh")}</g>`,
  tongue: () => `<g transform="translate(1 1) scale(.1)">${emoji("tongue")}</g>`,
  wow: () => `<g transform="translate(1 1) scale(.1)">${emoji("wow")}</g>`,
  happy: () => `<g transform="translate(1 1) scale(.1)">${emoji("happy")}</g>`,
  ball: () => `<circle cx="6" cy="6" r="4.4" fill="#ff9a52" class="o"/><path d="M1.6 6H10.4M6 1.6V10.4M2.9 2.9Q6 6 2.9 9.1M9.1 2.9Q6 6 9.1 9.1" fill="none" stroke="${INK}" stroke-opacity=".55" stroke-width=".55"/>`,
  taiji: () => `<circle cx="6" cy="6" r="4.4" fill="#fff" class="o"/><path d="M6 1.6A4.4 4.4 0 0 1 6 10.4A2.2 2.2 0 0 1 6 6A2.2 2.2 0 0 0 6 1.6Z" fill="${INK}"/><circle cx="6" cy="3.8" r=".7" fill="${INK}"/><circle cx="6" cy="8.2" r=".7" fill="#fff"/>`,
  paddle: () => `<circle cx="5.2" cy="5.2" r="3.6" fill="#ff7a7a" class="o"/><path d="M7.6 7.6L10.4 10.4" stroke="#c98a55" stroke-width="1.6" stroke-linecap="round"/><circle cx="9.6" cy="3" r="1.2" fill="#fff" class="o"/>`,
  bug: () => `<ellipse cx="6" cy="6.6" rx="4" ry="3.8" fill="#ff6b6b" class="o"/><path d="M6 2.8V10.4" stroke="${INK}" stroke-width=".6"/><circle cx="6" cy="2.9" r="1.6" fill="${INK}"/><circle cx="4.2" cy="6" r=".75" fill="${INK}"/><circle cx="7.8" cy="6" r=".75" fill="${INK}"/><circle cx="4.6" cy="8.6" r=".6" fill="${INK}"/><circle cx="7.4" cy="8.6" r=".6" fill="${INK}"/>`,
  heart: () => `<path d="M6 10.2C1.6 7.2 1.4 4.6 2.6 3.3C3.8 2 5.4 2.6 6 3.8C6.6 2.6 8.2 2 9.4 3.3C10.6 4.6 10.4 7.2 6 10.2Z" fill="#ff7d93" class="o"/>`,
};

/* ═════════════════ 六个小格的扁平等轴测插图（六个大格是 anatomy 插图，见 figs.js） ═════════════════ */

/* 146 个表情：一块表情键盘，键帽顶面是原创小表情与老表情里那类小物件 */
export function keys() {
  const g = new Iso();
  g.box(0, 0, 0, 66, 51, 4.4, L, { seam: true, bevel: 1.4 });
  const icons = [["smile", "ball", "taiji", "laugh"], ["paddle", "tongue", "heart", "wow"], ["happy", "bug", "smile", "laugh"]];
  const cells = [];
  for (let j = 0; j < 3; j++) for (let i = 0; i < 4; i++) cells.push([i, j]);
  cells.sort((a, b) => a[0] + a[1] - (b[0] + b[1]));
  for (const [i, j] of cells) {
    const x = 4 + i * 15, y = 4.5 + j * 15, on = i === 2 && j === 1;
    if (on) g.open(`class="ky-on"`);
    g.box(x, y, 4.4, 12, 12, on ? 2.4 : 4, on ? I : I, on ? { t: HL } : {});
    g.fz(x, y, on ? 6.8 : 8.4, 12, 12, KEYICON[icons[j][i]]() + (on ? `<rect x=".4" y=".4" width="11.2" height="11.2" rx="1.4" fill="none" stroke="${BLUE}" stroke-width="1"/>` : ""));
    if (on) g.close();
  }
  return g.svg("fig-keys", 3);
}

/* MCP 73 个工具：接口座 + 正在插入的插头，指示灯点亮 */
export function plug() {
  const g = new Iso();
  plate(g, 16, 2, 56, 58, 4, false);
  g.box(30, 8, 4, 36, 22, 15, L, { seam: true, bevel: 1.2 });
  g.fy(30, 30, 19, 36, 15, `${[0, 1, 2].map((k) => `<rect x="${4 + k * 10.6}" y="4" width="7.6" height="7" rx="1.2" fill="${L[3]}" class="o"/><rect x="${5.8 + k * 10.6}" y="6.6" width="1.2" height="2.4" fill="${INKP}" fill-opacity=".7"/><rect x="${8.8 + k * 10.6}" y="6.6" width="1.2" height="2.4" fill="${INKP}" fill-opacity=".7"/>`).join("")}`);
  g.ellZ(60, 13, 19, 1.5, BLUE, "d mc-led");
  g.fz(30, 8, 19, 36, 22, rules(4, 4, 16, 3, 2));
  g.open(`class="mc-plug" style="${mv("y", -5)}"`);
  const cx = 45.6;
  const [ax, ay] = g.P(cx + 3.6, 52, 9.5), [bx, by] = g.P(cx - 26, 58, 4.4);
  g.add(`<path d="M${r2(ax)} ${r2(ay)}C${r2(ax - 6)} ${r2(ay + 10)} ${r2(bx + 18)} ${r2(by - 6)} ${r2(bx)} ${r2(by)}" class="cord-o"/><path d="M${r2(ax)} ${r2(ay)}C${r2(ax - 6)} ${r2(ay + 10)} ${r2(bx + 18)} ${r2(by - 6)} ${r2(bx)} ${r2(by)}" stroke="${M[3]}" class="cord"/>`);
  g.box(cx - 1.6, 36, 10.2, 1.2, 4, 2.4, I); g.box(cx + 1.4, 36, 10.2, 1.2, 4, 2.4, I);
  g.box(cx - 4, 40, 6.6, 11.2, 12, 8.6, P, { seam: true });
  g.close();
  return g.svg("fig-plug", 3);
}

/* 七类一起搜：一盒七张分类卡，放大镜沿卡片平移 */
export function search() {
  const g = new Iso();
  plate(g, 4, 2, 62, 54, 4, false);
  g.box(10, 8, 4, 50, 38, 12, L, { t: L[3], seam: true });
  const cols = [I, L, P, M, I, P, M];
  for (let i = 0; i < 7; i++) {
    const y = 11 + i * 4.6, T = cols[i], hi = i === 3;
    g.box(13, y, 6, 44, .5, 15, T, hi ? { l: HL } : {});
    g.box(15 + i * 5.4, y, 21, 8, .5, 3.2, hi ? [BLUE, BLUE, BLUE] : T, hi ? { t: BLUE, l: BLUE, r: BLUE } : { l: T[2] });
  }
  g.poly([[10, 46, 4], [60, 46, 4], [60, 46, 12.5], [10, 46, 12.5]], L[1]);
  g.poly([[60, 8, 4], [60, 46, 4], [60, 46, 16], [60, 8, 16]], L[2]);
  g.poly([[10, 46, 12.5], [60, 46, 12.5], [60, 46.8, 12.5], [10, 46.8, 12.5]], L[0]);
  g.open(`class="se-lens" style="${mv("x", 14)}"`);
  g.fy(24, 50, 40, 30, 30, `<path d="M17.6 18.6L26 27" stroke="${INKP}" stroke-opacity=".6" stroke-width="4.6" stroke-linecap="round"/><path d="M17.6 18.6L26 27" stroke="${P[2]}" stroke-width="3" stroke-linecap="round"/>
    <circle cx="11" cy="12" r="9.4" fill="${L[2]}" class="o"/><circle cx="11" cy="12" r="7.2" fill="${k("glass", "#fff")}" fill-opacity=".72" class="d"/><path d="M6.4 9.6Q8 7 11 6.6" fill="none" stroke="${BLUE}" stroke-width="1.2" stroke-linecap="round"/>`);
  g.close();
  return g.svg("fig-search", 3);
}

/* 全新界面：一副摊开的色卡扇 + 「经典 / 新版」拨杆 */
export function swatch() {
  const g = new Iso();
  plate(g, 0, 0, 76, 56, 4, false);
  const fan = [[-6, I], [12, L], [30, P], [48, M], [66, "new"]];
  let s = "";
  fan.forEach(([a, T], k) => {
    const top = T === "new" ? BLUE : T[2], band = T === "new" ? HL : T[1];
    s += `<g class="ui-card" transform="rotate(${a})" style="--a:${a}deg;--h:${a - (4 - k) * 5}deg"><rect x="-6" y="-44" width="12" height="44" rx="1.2" fill="${PAPER}" class="o"/><rect x="-6" y="-44" width="12" height="15" rx="1.2" fill="${top}" class="d"/><rect x="-6" y="-29" width="12" height="3.2" fill="${band}"/><line x1="-3.6" y1="-21" x2="3.6" y2="-21" class="f"/><line x1="-3.6" y1="-17.6" x2="1.6" y2="-17.6" class="f"/></g>`;
  });
  g.fz(0, 0, 4, 76, 56, `<g transform="translate(13 50)">${s}<circle r="2.4" fill="${L[2]}" class="o"/><circle r=".9" fill="${INKP}" fill-opacity=".6"/></g>`);
  g.box(50, 6, 4, 22, 11, 5, L, { seam: true });
  g.fz(50, 6, 9, 22, 11, `<rect x="2.6" y="3.6" width="16.8" height="3.8" rx="1.9" fill="${L[3]}" class="d"/>`);
  g.open(`class="ui-knob" style="${mv("x", -9)}"`);
  g.box(62, 7.6, 9, 6, 7.8, 4, [BLUE, BLUE, BLUE], { t: k("blue-t", "#7cc9ff"), l: BLUE, r: k("blue-0", "#2a73d0") });
  g.close();
  return g.svg("fig-swatch", 3);
}

/* 直接发、定时发：台钟走针 + 一只纸飞机 */
export function clock() {
  const g = new Iso();
  plate(g, 4, 4, 66, 44, 4, false);
  g.box(10, 10, 4, 34, 26, 36, P, { seam: true });
  g.box(8.6, 8.6, 40, 36.8, 28.8, 2.4, L, { bevel: 1 });
  g.cyl(27, 23, 42.4, 3.2, 3.2, L);
  const cx = 17, cy = 17, R = 12.6;
  g.fy(10, 36, 40, 34, 36, `<circle cx="${cx}" cy="${cy}" r="${R + 1.8}" fill="${L[1]}" class="o"/><circle cx="${cx}" cy="${cy}" r="${R}" fill="${PAPER}" class="d"/>${ticks(cx, cy, R - .6, R - 2.6, -90, 240, 11, 3, "f", R - 3.8)}
    <g transform="translate(${cx} ${cy})"><g class="ck-h"><path d="M-.9 1.6L0 -6.4L.9 1.6Z" fill="${INKP}"/></g><g class="ck-m"><path d="M-.7 2L0 -${R - 2.8}L.7 2Z" fill="${BLUE}"/></g><circle r="1.2" fill="${INKP}"/></g>
    <rect x="6" y="32" width="22" height="1.6" rx=".8" fill="${P[3]}" class="f"/>`);
  g.open(`class="ck-plane"`);
  const n = [66, 30, 30], tl = [50, 22, 34], tr = [56, 40, 28], keel = [55, 31, 26];
  g.poly([n, tl, keel], I[1]);
  g.poly([n, keel, tr], I[2]);
  g.poly([n, tl, [53, 30, 31.5]], HL);
  g.close();
  return g.svg("fig-clock", 3);
}

/* 实况照片能播：相框里是日出风景，左上角是实况圈，太阳缓缓升起 */
export function photo() {
  const g = new Iso();
  plate(g, 4, 4, 60, 30, 4, false);
  g.box(31, 8, 4, 6, 14, 28, L, { l: L[2], r: L[3] });
  g.box(10, 20, 4, 48, 4, 38, L, { seam: true });
  const id = "phc" + (++uid);
  g.fy(10, 24, 42, 48, 38, `<rect x="3" y="3" width="42" height="30" rx=".8" fill="${I[1]}" class="o"/>
    <g clip-path="url(#${id})"><g class="ph-sun"><circle cx="30" cy="20" r="5.4" fill="${P[2]}" class="d"/></g>
    <path d="M3 25Q12 15 21 22Q28 27 34 21Q40 16 45 20V33H3Z" fill="${M[2]}" class="d"/><path d="M3 29Q14 23 24 28Q34 32 45 27V33H3Z" fill="${M[3]}" class="d"/></g>
    <g transform="translate(10 10)"><circle r="1.4" fill="${BLUE}"/><circle r="3" fill="none" stroke="${BLUE}" stroke-width=".8"/><g class="ph-ring"><circle r="4.8" fill="none" stroke="${BLUE}" stroke-width=".8" stroke-dasharray="1 1.4"/></g></g>`);
  return g.svg("fig-photo", 3, `<clipPath id="${id}"><rect x="3" y="3" width="42" height="30" rx=".8"/></clipPath>`);
}

/* macOS 取密钥（便当盒底部通栏）：左边一台笔记本（屏上钥匙图标 + 三段进度条），右边一排三摞数据库（三种颜色 = 不同的微信版本），
   一把钥匙平躺着沿虚线依次滑到每一摞的挂锁前：锁梁弹起、上方亮起对勾，进度条走一段。
   电脑与数据库沿世界 (1, -1) 排开——这条线在屏幕上正好水平，整幅图是一条横向场景 */
export function mackey() {
  const g = new Iso();
  // 笔记本：底座台 + 机身（键盘、触控板）+ 立在机身后沿的屏幕
  plate(g, 0, 26, 36, 28, 3, false);
  g.box(4, 30, 3, 28, 19, 2, I, { seam: true });
  g.fz(4, 30, 5, 28, 19, `<rect x="2.2" y="2" width="23.6" height="9" rx=".8" fill="${I[3]}" class="f"/>${rules(4, 4.2, 19.6, 3, 2.1)}<rect x="9" y="12.6" width="10" height="4.8" rx=".8" fill="${I[3]}" class="f"/>`);
  g.box(4, 28.8, 5, 28, 1.2, 19, I);
  g.fy(4, 30, 24, 28, 19, `<rect x="1.3" y="1.3" width="25.4" height="15.2" rx=".8" fill="${PAPER}" class="d"/>
    <g transform="translate(6.4 6.4)"><circle r="2.3" fill="none" stroke="${BLUE}" stroke-width="1.1"/><path d="M2.3 0H9M6.6 0V2M8.4 0V1.6" fill="none" stroke="${BLUE}" stroke-width="1.1" stroke-linecap="round"/></g>
    ${rules(16, 4.6, 8.6, 2, 2)}<rect x="4.2" y="11.4" width="19.6" height="1.9" rx=".95" fill="${L[3]}"/><rect class="mk-bar" x="4.2" y="11.4" width="19.6" height="1.9" rx=".95" fill="${BLUE}"/>
    <path d="M10.73 11.2V13.5M17.27 11.2V13.5" stroke="${PAPER}" stroke-width=".6"/>`);
  // 三摞数据库：中心在 (18 + s, 41 − s)，s = 56 / 86 / 116；底座台 24 见方，三层圆盘，正面（+y 侧）挂一把锁
  const S = [56, 86, 116], COL = [M, L, I];
  const [ax, ay] = g.P(33, 27, 0), [bx, by] = g.P(18 + S[2] - 12, 41 - S[2] + 12, 0);
  g.add(`<line x1="${r2(ax)}" y1="${r2(ay)}" x2="${r2(bx)}" y2="${r2(by)}" class="d" stroke-dasharray="1.4 2.2"/>`);
  S.forEach((sv, i) => {
    const cx = 18 + sv, cy = 41 - sv, T = COL[i];
    plate(g, cx - 12, cy - 12, 24, 24, 3, false);
    [3, 7.6, 12.2].forEach((z) => g.cyl(cx, cy, z, 7.5, 4, T));
    g.open(`class="mk-sh mk-sh${i + 1}"`);
    g.fy(cx - 3.5, cy + 8.2, 12, 7, 0, `<path d="M1.5 .4V-2.2A2 2 0 0 1 5.5 -2.2V.4" fill="none" stroke="${INKP}" stroke-opacity=".55" stroke-width="2.3" stroke-linecap="round"/><path d="M1.5 .4V-2.2A2 2 0 0 1 5.5 -2.2V.4" fill="none" stroke="${I[0]}" stroke-width="1.3" stroke-linecap="round"/>`);
    g.P(cx - 3.5, cy + 8.2, 17);
    g.close();
    g.box(cx - 3.5, cy + 6.9, 6, 7, 2.6, 6, P, { seam: true });
    g.fy(cx - 3.5, cy + 9.5, 12, 7, 6, `<circle cx="3.5" cy="2.5" r="1" fill="${INKP}" fill-opacity=".7"/><path d="M3.5 3V4.7" stroke="${INKP}" stroke-opacity=".7" stroke-width="1" stroke-linecap="round"/>`);
    const [ox, oy] = g.P(cx, cy, 24);
    g.t(ox - 5, oy - 5); g.t(ox + 5, oy + 5);
    g.add(`<g class="mk-ok mk-ok${i + 1}"><circle cx="${r2(ox)}" cy="${r2(oy)}" r="4" fill="${BLUE}" class="o"/><path d="M${r2(ox - 1.8)} ${r2(oy)}L${r2(ox - .45)} ${r2(oy + 1.45)}L${r2(ox + 2)} ${r2(oy - 1.35)}" fill="none" stroke="${HL}" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></g>`);
  });
  // 钥匙：平躺在 z = 10 的水平面上，沿 (1, -1) 方向、放大 1.25 倍；先画一层压深的当厚度，再画顶面。
  // 从电脑旁 (35, 30) 出发，三处停靠点在第 i 把锁的左前角前面一个钥匙长：沿路走 s − 31.3 个单位；--t1/2/3 是这几段在屏幕上的水平位移
  const key = (fill, hole) => `<g transform="rotate(-45) scale(1.25)"><circle r="3.3" fill="${fill}" class="o"/><circle r="1.3" fill="${hole}" class="d"/><rect x="2.8" y="-.85" width="9.4" height="1.7" rx=".4" fill="${fill}" class="o"/><path d="M9 .8V2.6H10.2V1.7H11.2V2.6H12.2V.8Z" fill="${fill}" class="o"/></g>`;
  const tx = (sv) => `${r2(2 * C * (sv - 31.3))}px`;
  g.open(`class="mk-key" style="--t1:${tx(S[0])};--t2:${tx(S[1])};--t3:${tx(S[2])}"`);
  g.fz(35, 30, 9.3, 1, 1, key(P[0], P[0]));
  g.fz(35, 30, 10, 1, 1, key(P[2], PAPER));
  g.close();
  g.P(31, 34.5, 10);
  return g.svg("fig-mackey", 3);
}

export const ART = { keys, plug, search, swatch, clock, photo, mackey };
