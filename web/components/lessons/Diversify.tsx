"use client";

import { useState } from "react";

import type { ClassStat } from "@/lib/classes";
import { pct, type Lang } from "@/lib/format";
import { mix2 } from "@/lib/lessons";

import { Term } from "../Term";
import { Quiz, Step } from "./Parts";

const TEXT = {
  vi: {
    s1: "Trộn hai tài sản",
    p1: "Chọn hai lớp tài sản và kéo tỷ trọng. Đường cong là mọi cách trộn; đường thẳng nét đứt là nếu chúng luôn lên xuống cùng nhau.",
    a: "Tài sản thứ nhất",
    b: "Tài sản thứ hai",
    share: (n: number, a: string) => `${n}% vào ${a}`,
    ret: "Lợi nhuận kỳ vọng",
    vol: "Biến động",
    saved: "Rủi ro giảm nhờ trộn",
    rho: (r: string) => `Tương quan giữa hai lớp (VNCMA): ${r}`,
    s2: "Nếu tương quan khác thì sao?",
    p2: "Kéo tương quan để xem: càng thấp, đường cong càng cong về bên trái, nghĩa là cùng lợi nhuận mà ít rủi ro hơn.",
    what: (r: string) => `Tương quan giả định: ${r}`,
    reset: "Về số thật của VNCMA",
    s3: "Thử một câu",
    q: "Vì sao trộn cổ phiếu với vàng có thể giảm rủi ro mà không giảm lợi nhuận tương ứng?",
    opts: ["Vì vàng luôn tăng", "Vì hai thứ không luôn lên xuống cùng lúc", "Vì cổ phiếu ít rủi ro", "Không thể"],
    why: "Khi tương quan thấp hơn 1, những năm một thứ giảm thường được thứ kia bù một phần. Lợi nhuận là bình quân, còn rủi ro nhỏ hơn bình quân.",
    axisVol: "biến động →",
    axisRet: "lợi nhuận ↑",
    source: "Lợi nhuận kỳ vọng, biến động và tương quan: giả định VNCMA. Lợi nhuận của danh mục là xấp xỉ bình quân có trọng số.",
  },
  en: {
    s1: "Mix two assets",
    p1: "Pick two asset classes and drag the weight. The curve is every mix; the dashed straight line is what you'd get if they always moved together.",
    a: "First asset",
    b: "Second asset",
    share: (n: number, a: string) => `${n}% in ${a}`,
    ret: "Expected return",
    vol: "Volatility",
    saved: "Risk saved by mixing",
    rho: (r: string) => `Correlation between them (VNCMA): ${r}`,
    s2: "What if the correlation were different?",
    p2: "Drag the correlation: the lower it is, the more the curve bends left, meaning the same return for less risk.",
    what: (r: string) => `Assumed correlation: ${r}`,
    reset: "Back to the VNCMA figure",
    s3: "Try one",
    q: "Why can mixing shares with gold cut risk without cutting return as much?",
    opts: ["Gold always rises", "They don't always move together", "Shares are low risk", "It can't"],
    why: "With correlation below 1, years when one falls are often partly offset by the other. Return is the weighted average; risk is less than the average.",
    axisVol: "volatility →",
    axisRet: "return ↑",
    source: "Expected returns, volatilities and correlations: VNCMA assumptions. Portfolio return is approximated as the weighted average.",
  },
};

export function DiversifyLesson({ lang, classes, correlation }: { lang: Lang; classes: ClassStat[]; correlation: { classes: string[]; matrix: number[][] } }) {
  const x = TEXT[lang];
  const [aId, setA] = useState(classes.find((c) => c.id === "eq_large")?.id ?? classes[0]?.id);
  const [bId, setB] = useState(classes.find((c) => c.id === "gold")?.id ?? classes[1]?.id);
  const [w, setW] = useState(60);
  const a = classes.find((c) => c.id === aId) ?? classes[0];
  const b = classes.find((c) => c.id === bId) ?? classes[1];
  const real = (() => {
    const i = correlation.classes.indexOf(a?.id ?? "");
    const j = correlation.classes.indexOf(b?.id ?? "");
    return i >= 0 && j >= 0 ? correlation.matrix[i][j] : 0;
  })();
  const [rho, setRho] = useState<number | null>(null);
  if (!a || !b) return null;
  const r = rho ?? real;
  const now = mix2(w / 100, a, b, real);
  const p = (v: number) => pct(Math.round(v * 10) / 10, lang);
  const f = (v: number) => v.toLocaleString(lang === "vi" ? "vi-VN" : "en-US", { maximumFractionDigits: 2 });

  const picker = (label: string, value: string, set: (id: string) => void, other: string) => (
    <label className="map-hand block text-[20px]">
      {label}
      <select className="map-input" value={value} onChange={(e) => (set(e.target.value), setRho(null))}>
        {classes
          .filter((c) => c.id !== other)
          .map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
      </select>
    </label>
  );

  return (
    <div className="space-y-10">
      <Step n={1} title={x.s1}>
        <p>
          {x.p1} <Term id="da-dang-hoa" lang={lang} />
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          {picker(x.a, a.id, setA, b.id)}
          {picker(x.b, b.id, setB, a.id)}
        </div>
        <label className="map-hand block text-[20px]">
          {x.share(w, a.name)}
          <input type="range" min={0} max={100} step={5} value={w} onChange={(e) => setW(+e.target.value)} />
        </label>
        <Frontier a={a} b={b} rho={real} w={w / 100} labels={[x.axisVol, x.axisRet]} />
        <div className="grid gap-3 sm:grid-cols-3" aria-live="polite">
          <div>
            <p className="text-sm">{x.ret}</p>
            <p className="map-num text-[30px]">{p(now.ret)}</p>
          </div>
          <div>
            <p className="text-sm">{x.vol}</p>
            <p className="map-num text-[30px]">{p(now.vol)}</p>
          </div>
          <div>
            <p className="text-sm">{x.saved}</p>
            <p className="map-num map-num--warn text-[30px]">−{p(now.saved)}</p>
          </div>
        </div>
        <p className="text-sm">
          {x.rho(f(real))} · <Term id="tuong-quan" lang={lang} />
        </p>
      </Step>

      <Step n={2} title={x.s2}>
        <p>{x.p2}</p>
        <label className="map-hand block text-[20px]">
          {x.what(f(r))}
          <input type="range" min={-1} max={1} step={0.1} value={r} onChange={(e) => setRho(+e.target.value)} />
        </label>
        <Frontier a={a} b={b} rho={r} w={w / 100} labels={[x.axisVol, x.axisRet]} />
        <p>
          {x.saved}: <b>−{p(mix2(w / 100, a, b, r).saved)}</b>
        </p>
        {rho !== null ? (
          <button type="button" className="sv-btn sv-btn--secondary" onClick={() => setRho(null)}>
            {x.reset}
          </button>
        ) : null}
      </Step>

      <Step n={3} title={x.s3}>
        <Quiz lang={lang} question={x.q} options={x.opts} answer={1} why={x.why} />
      </Step>
      <p className="text-xs text-[var(--map-muted)]">{x.source}</p>
    </div>
  );
}

/** Return against volatility for every mix of a and b; dashed line = no diversification; dot = current mix. */
function Frontier({ a, b, rho, w, labels }: { a: ClassStat; b: ClassStat; rho: number; w: number; labels: [string, string] }) {
  const W = 600;
  const H = 240;
  const pad = 30;
  const pts = Array.from({ length: 21 }, (_, i) => mix2(i / 20, a, b, rho));
  const maxV = Math.max(a.vol, b.vol) * 1.1;
  const minR = Math.min(a.ret, b.ret) - 1;
  const maxR = Math.max(a.ret, b.ret) + 1;
  const x = (v: number) => pad + (v / maxV) * (W - 2 * pad);
  const y = (r: number) => H - pad - ((r - minR) / (maxR - minR)) * (H - 2 * pad);
  const cur = mix2(w, a, b, rho);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`${labels[0]} ${cur.vol.toFixed(1)}%, ${labels[1]} ${cur.ret.toFixed(1)}%`}>
      <line x1={pad} x2={W - pad} y1={H - pad} y2={H - pad} stroke="var(--map-line)" />
      <line x1={pad} x2={pad} y1={pad} y2={H - pad} stroke="var(--map-line)" />
      <text x={W - pad} y={H - 8} textAnchor="end" fontSize="11" fill="var(--map-muted)">
        {labels[0]}
      </text>
      <text x={pad + 4} y={pad - 10} fontSize="11" fill="var(--map-muted)">
        {labels[1]}
      </text>
      <line x1={x(b.vol)} y1={y(b.ret)} x2={x(a.vol)} y2={y(a.ret)} stroke="var(--map-ink)" strokeDasharray="5 5" strokeOpacity={0.6} />
      <path d={pts.map((p, i) => `${i ? "L" : "M"}${x(p.vol).toFixed(1)},${y(p.ret).toFixed(1)}`).join("")} fill="none" stroke="var(--series-1)" strokeWidth={2.5} />
      {[a, b].map((c) => (
        <g key={c.id}>
          <circle cx={x(c.vol)} cy={y(c.ret)} r={5} fill="var(--map-ink)" />
          <text x={x(c.vol) + (x(c.vol) > W / 2 ? -8 : 8)} y={y(c.ret) - 8} textAnchor={x(c.vol) > W / 2 ? "end" : "start"} fontSize="12" fill="var(--map-ink)">
            {c.name}
          </text>
        </g>
      ))}
      <circle cx={x(cur.vol)} cy={y(cur.ret)} r={8} fill="var(--series-2)" stroke="var(--map-card)" strokeWidth={2} />
    </svg>
  );
}
