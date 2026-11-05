// Copies docs/methodology.md (the single source) into web/content/ before a build.
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
const from = [join(web, "..", "docs", "methodology.md"), join(web, "docs", "methodology.md")].find(existsSync);
if (!from) {
  if (existsSync(join(web, "content", "methodology.md"))) process.exit(0); // already copied (Docker)
  throw new Error("docs/methodology.md not found");
}
mkdirSync(join(web, "content"), { recursive: true });
copyFileSync(from, join(web, "content", "methodology.md"));
