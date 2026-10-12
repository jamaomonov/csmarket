# Share-card fonts

IBM Plex Sans Medium (500) and Bold (700), TrueType, Latin and Cyrillic. They come from Google
Fonts (`fonts.gstatic.com`, v23) and are licensed under the SIL Open Font License 1.1
(<https://openfontlicense.org>). `src/lib/og-assets.ts` reads them for the item share card. The
renderer (`next/og`) takes TTF, not the woff2 that `next/font` ships. They live in the repo so a
card never depends on Google answering at runtime.
