import js from "@eslint/js";

export default [
  {
    ignores: ["node_modules/", "dist/", ".vite/"]
  },
  {
    files: ["**/*.js"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module"
    },
    rules: js.configs.recommended.rules
  }
];
