import { readFile } from "node:fs/promises";
import path from "node:path";

import { ImageResponse } from "next/og";

export const OG_SIZE = { width: 1200, height: 630 };

// Be Vietnam Pro (SIL OFL, assets/fonts/OFL.txt) has every Vietnamese glyph.
// Read once at module scope; it doesn't depend on the request.
const font = readFile(path.join(process.cwd(), "assets", "fonts", "BeVietnamPro-Bold.ttf"));

/** A plain, readable share card: what the page is, plus one key number if any. */
export async function ogImage({
  eyebrow,
  title,
  figure,
  note,
}: {
  eyebrow: string;
  title: string;
  figure?: string;
  note?: string;
}) {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: 72,
          background: "#ffffff",
          borderTop: "24px solid #0b6e4f",
          color: "#10231c",
          fontFamily: "BeVietnamPro",
        }}
      >
        <div style={{ display: "flex", fontSize: 30, letterSpacing: 2, textTransform: "uppercase", color: "#0b6e4f" }}>
          {eyebrow}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ display: "flex", fontSize: 68, lineHeight: 1.1 }}>{title}</div>
          {figure ? <div style={{ display: "flex", fontSize: 96, color: "#0b6e4f" }}>{figure}</div> : null}
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 28, color: "#4b5d56" }}>
          <span style={{ fontSize: 40, color: "#10231c" }}>SoiVí</span>
          <span>{note ?? ""}</span>
        </div>
      </div>
    ),
    { ...OG_SIZE, fonts: [{ name: "BeVietnamPro", data: await font, weight: 700, style: "normal" }] },
  );
}
