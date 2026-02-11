import js from "@eslint/js";

export default [
  {
    ignores: ["node_modules/", "dist/", ".vite/"],
  },
  {
    files: ["**/*.js"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: {
        window: "readonly",
        document: "readonly",
        navigator: "readonly",
        console: "readonly",
      },
    },
    rules: js.configs.recommended.rules,
  },
];
