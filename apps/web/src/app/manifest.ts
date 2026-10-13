import type { MetadataRoute } from "next";

/**
 * `/manifest.webmanifest`: the name and icons a phone uses when the site is added to the home
 * screen, and that Android and some search engines read for the site's icon.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "csmarket — скины КС2 (CS2) в Узбекистане",
    short_name: "csmarket",
    start_url: "/",
    display: "browser",
    background_color: "#0d111b",
    theme_color: "#0d111b",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/favicon.svg", sizes: "any", type: "image/svg+xml" },
    ],
  };
}
