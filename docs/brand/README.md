# csmarket brand

The mark: two slanted trade arrows (⇄), notched around a gem — trading skins. The wordmark
«cs» + «market» in IBM Plex Sans Bold leans with the arrows (14°) and is set tight
(−0.045 em); the mark is 1.3× the font size, 0.3 em from the text.

In code the logo is `Logo` / `LogoMark` from `@csmarket/ui` (`docs/design-system.md`); these
files are for everything outside the apps (socials, stores, print, documents).

## Files (`svg/`, outlined — no font needed)

| File                                                     | Use                                                      |
| -------------------------------------------------------- | -------------------------------------------------------- |
| `logo-on-dark`                                           | Main logo on a dark background (white «cs»)              |
| `logo-on-dark-bg`                                        | The same with the dark background baked in               |
| `logo-on-light`                                          | On white: deep green `#159A35` (the accent is too light) |
| `logo-white` / `logo-black`                              | One colour: photos, print, stamps                        |
| `logo-stacked-on-dark` / `logo-stacked-on-light`         | Mark above the name, for square spots                    |
| `mark-green` / `mark-white` / `mark-dark` / `mark-black` | The mark alone                                           |
| `icon-green` / `icon-dark`                               | Rounded tile: favicons, app icons                        |
| `icon-green-circle` / `icon-dark-circle`                 | Circle: avatars (Telegram, Instagram)                    |

The storefront's favicon is `icon-green` (`apps/web/public/favicon.svg`, and
`apple-touch-icon.png` at 180 px); the admin's is `icon-dark`, so the two tabs differ.

PNGs (16–1024 px for marks and icons, 64–512 px tall for logos) are rendered from these SVGs
and handed out as an archive; they are not kept in the repo.

## Colours

Accent `#4BF364`, background `#0D111B`, white `#FFFFFF`, on light `#159A35`.

## Don'ts

Don't straighten the wordmark or the arrows, recolour the gem alone, add effects (shadows,
gradients, outlines), or set the accent green on white.
