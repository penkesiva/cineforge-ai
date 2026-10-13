import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    rules: {
      "no-restricted-properties": [
        "error",
        { object: "window", property: "alert", message: "Use AppNoticeDialog instead." },
        { object: "window", property: "confirm", message: "Use AppConfirmDialog instead." },
      ],
      "no-restricted-globals": [
        "error",
        { name: "alert", message: "Use AppNoticeDialog instead." },
        { name: "confirm", message: "Use AppConfirmDialog instead." },
      ],
    },
  },
  globalIgnores([".next/**", "out/**", "build/**", "coverage/**", "next-env.d.ts"]),
]);
