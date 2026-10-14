// Generates src/contracts.generated.ts from json/contracts.schema.json.
// Run via `make contracts` (which first exports the schema from Pydantic).
import { readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "json-schema-to-typescript";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const schema = JSON.parse(await readFile(resolve(root, "json/contracts.schema.json"), "utf8"));

const { "x-enums": enums, "x-agent-definitions": agentDefinitions, ...rawSchema } = schema;

// Pydantic emits per-property titles and `$ref` siblings (default/description),
// which json-schema-to-typescript turns into duplicate aliases (Foo1, Title3...).
// Strip them so every contract maps to exactly one named TS type.
function simplify(node, isDefinitionRoot = false) {
  if (Array.isArray(node)) return node.map((n) => simplify(n));
  if (node === null || typeof node !== "object") return node;
  if (typeof node.$ref === "string") return { $ref: node.$ref };
  const out = {};
  for (const [key, value] of Object.entries(node)) {
    if (key === "title" && !isDefinitionRoot) continue;
    if (key === "$defs" || key === "properties") {
      out[key] = Object.fromEntries(
        Object.entries(value).map(([k, v]) => [k, simplify(v, key === "$defs")]),
      );
    } else {
      out[key] = simplify(value);
    }
  }
  return out;
}
const jsonSchema = simplify(rawSchema, true);

const types = await compile(jsonSchema, "CineForgeContracts", {
  bannerComment:
    "/* GENERATED from packages/schemas/json/contracts.schema.json - do not edit. Run `make contracts`. */",
  unreachableDefinitions: true,
  additionalProperties: false,
  strictIndexSignatures: false,
  style: { singleQuote: false, semi: true },
});

const constants = `
export const PRODUCTION_STATES = ${JSON.stringify(enums.ProductionStateOrder)} as const;
export const HAPPY_PATH = ${JSON.stringify(enums.HappyPath)} as const;
export const AGENT_DEFINITIONS: AgentDefinition[] = ${JSON.stringify(agentDefinitions, null, 2)};
`;

await writeFile(resolve(root, "src/contracts.generated.ts"), types + constants);
console.log("wrote packages/schemas/src/contracts.generated.ts");
