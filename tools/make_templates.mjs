// Writes the templates shipped with the engine, other than default, from the
// presets of the designer (designer/designer.js), so that the designer opens
// them as it wrote them (optimize.md 4.11).
//
//     node tools/make_templates.mjs
//
// tests/unit/test_templates.py checks that the files are up to date.
import { createRequire } from "node:module";
import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const D = createRequire(import.meta.url)(join(root, "designer", "designer.js"));

for (const id of Object.keys(D.PRESETS)) {
  const path = join(root, "report-templates", `${id}.html`);
  writeFileSync(path, D.build(D.preset(id)), "utf8");
  console.log(path);
}
