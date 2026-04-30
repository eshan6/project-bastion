#!/usr/bin/env node
/**
 * sync-fsp-data.mjs
 *
 * Copies the locked FSP demo content from data/fsp/*.json (single source of truth
 * at repo root) into app/public/data/ so Vite serves them as static assets.
 *
 * Runs automatically before `npm run dev` and `npm run build` (see package.json
 * pre-hooks). Never edit the files in app/public/data/ directly — they will be
 * overwritten on next build.
 *
 * Why copy rather than symlink: Vercel build environments do not preserve symlinks
 * reliably across all OSes; a copy is the lowest-friction option.
 *
 * Why copy rather than `import` JSON: the demo's provenance story depends on
 * users being able to view the raw data files at e.g. /data/posts.json directly.
 * Bundling them into JS hides them.
 */
import { copyFile, mkdir, readdir, stat } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const APP_ROOT = resolve(__dirname, "..");
const REPO_ROOT = resolve(APP_ROOT, "..");
const SRC_DIR = join(REPO_ROOT, "data", "fsp");
const DST_DIR = join(APP_ROOT, "public", "data");

const FILES_TO_COPY = [
  "posts.json",
  "routes.json",
  "skus.json",
  "vehicles.json",
  "scenarios.json",
  "methodology.md",
];

async function main() {
  // Sanity check: source dir must exist with the expected files.
  try {
    await stat(SRC_DIR);
  } catch {
    console.error(`[sync-fsp-data] FATAL: source directory not found: ${SRC_DIR}`);
    console.error("[sync-fsp-data] Run this script from inside the project-bastion repo.");
    process.exit(1);
  }

  await mkdir(DST_DIR, { recursive: true });

  const present = new Set(await readdir(SRC_DIR));
  const missing = FILES_TO_COPY.filter((f) => !present.has(f));
  if (missing.length > 0) {
    console.error(`[sync-fsp-data] FATAL: missing files in ${SRC_DIR}:`);
    missing.forEach((f) => console.error(`  - ${f}`));
    process.exit(1);
  }

  for (const f of FILES_TO_COPY) {
    const src = join(SRC_DIR, f);
    const dst = join(DST_DIR, f);
    await copyFile(src, dst);
    const s = await stat(dst);
    console.log(`[sync-fsp-data] ${f}  (${s.size.toLocaleString()} B)`);
  }

  console.log(`[sync-fsp-data] copied ${FILES_TO_COPY.length} files -> ${DST_DIR}`);
}

main().catch((e) => {
  console.error("[sync-fsp-data] FATAL:", e);
  process.exit(1);
});
