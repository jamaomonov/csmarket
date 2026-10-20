import config from "@csmarket/config-eslint/react";

export default [
  ...config,
  // Served as-is, outside the TS project: the pre-paint theme bootstrap (no inline script
  // under the admin's CSP).
  { ignores: ["public/**"] },
];
