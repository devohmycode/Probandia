// Development check: validate a GEDCOM 7 export with js-gedcom (gedcom7code/js-gedcom).
//
//   node tools/validate_gedcom7.mjs <js-gedcom folder> <g7validation.json> <file.ged|file.gdz>
//
// g7validation.json comes from FamilySearch/GEDCOM-registries (generated_files/).
// A .gdz is read with `unzip -p`. Errors exit with code 1; warnings are printed.
import { execFileSync } from "node:child_process"
import { readFileSync } from "node:fs"
import { pathToFileURL } from "node:url"
import path from "node:path"

const [jsDir, validationPath, file] = process.argv.slice(2)
if (!jsDir || !validationPath || !file) {
  console.error("usage: node validate_gedcom7.mjs <js-gedcom> <g7validation.json> <file>")
  process.exit(2)
}
const load = (name) => import(pathToFileURL(path.join(jsDir, name)).href)
const { GEDCStruct, g7ConfGEDC } = await load("gedcstruct.js")
const { G7Lookups } = await load("g7lookups.js")
const { G7Dataset } = await load("g7structure.js")

let text = file.toLowerCase().endsWith(".gdz")
  ? execFileSync("unzip", ["-p", file, "gedcom.ged"]).toString("utf-8")
  : readFileSync(file, "utf-8")

const errors = []
const warnings = []
const g7v = new G7Lookups(JSON.parse(readFileSync(validationPath, "utf-8")))
g7v.err = (m) => errors.push(String(m))
g7v.warn = (m) => warnings.push(String(m))
try {
  const gedc = GEDCStruct.fromString(text, g7ConfGEDC, g7v.err)
  if (!Array.isArray(gedc) || gedc.length === 0) errors.push("no GEDCOM data")
  if (errors.length === 0) G7Dataset.fromGEDC(gedc, g7v)
} catch (e) {
  errors.push(`unrecoverable: ${e.message}`)
}
for (const w of warnings) console.log(`WARN ${w}`)
for (const e of errors) console.log(`ERROR ${e}`)
console.log(`${errors.length ? "FAIL" : "OK"} ${file}: ${errors.length} errors, ${warnings.length} warnings`)
process.exit(errors.length ? 1 : 0)
