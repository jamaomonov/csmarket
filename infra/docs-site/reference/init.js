// The Scalar reference for docs.csmarket.uz. A file of its own so the CSP needs no inline script.
Scalar.createApiReference("#app", {
  url: "/openapi.json",
  theme: "default",
  layout: "modern",
  withDefaultFonts: false,
  telemetry: false,
  showDeveloperTools: "never",
  agent: { disabled: true },
  mcp: { disabled: true },
  persistAuth: false,
  documentDownloadType: "json",
  operationTitleSource: "summary",
  defaultHttpClient: { targetKey: "shell", clientKey: "curl" },
  metaData: { title: "csmarket API" },
});
