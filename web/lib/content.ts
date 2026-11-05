import "server-only";

import { readFile } from "node:fs/promises";
import path from "node:path";

import { marked } from "marked";
import { cacheLife } from "next/cache";

import type { Lang } from "./format";

/**
 * docs/methodology.md is the single source: `npm run build` copies it to
 * content/methodology.md (scripts/copy-content.mjs) and the site renders it.
 * It holds the Vietnamese text first ("## Tiếng Việt"), then English ("## English"),
 * then a shared changelog.
 */

export async function methodologyHtml(lang: Lang): Promise<string> {
  "use cache";
  cacheLife("max");
  const text = await readFile(path.join(process.cwd(), "content", "methodology.md"), "utf8");
  const vi = text.indexOf("## Tiếng Việt");
  const en = text.indexOf("## English");
  const log = text.indexOf("## Nhật ký thay đổi");
  if (vi < 0 || en < 0 || log < 0) throw new Error("docs/methodology.md: section headings changed");
  const head = text.slice(0, text.indexOf("---", text.indexOf("Version")));
  const body = lang === "vi" ? text.slice(vi, en) : text.slice(en, log);
  // The language heading is dropped, so its subsections move up one level
  // (h1 -> h2, never h1 -> h3).
  const section = body.replace(/^## (Tiếng Việt|English)\n/, "").replace(/^#(#{2,5}) /gm, "$1 ");
  const md = [head, section, text.slice(log)].join("\n\n");
  return marked.parse(md.replace(/^\[Tiếng Việt\].*$/m, ""), { async: false }) as string;
}
