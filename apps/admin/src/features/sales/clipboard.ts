/**
 * Copying on a phone. iPhone Safari lets a page write the clipboard only inside the tap: a
 * write started after an awaited request is refused. So:
 *
 * - `copyText(text)` — the text is already on the page: the Clipboard API, started in the tap,
 *   with a selected read-only field + `execCommand("copy")` as the fallback.
 * - `copyLater(promise)` — the text comes from a request (the card number): a `ClipboardItem`
 *   whose content is the promise, handed to the clipboard inside the tap (Safari, Chrome);
 *   without one, the text is written when it arrives (desktop browsers allow that).
 *
 * Both resolve to whether the copy worked; on `false` the page shows the text selectable.
 */

/** A hidden read-only textarea, selected, copied with `execCommand` (older and iOS browsers). */
export function execCopy(text: string): boolean {
  const field = document.createElement("textarea");
  field.value = text;
  field.readOnly = true;
  field.setAttribute("aria-hidden", "true");
  field.style.position = "fixed";
  field.style.top = "0";
  field.style.opacity = "0";
  document.body.appendChild(field);
  try {
    field.focus();
    field.select();
    field.setSelectionRange(0, text.length); // iOS ignores select() alone
    // eslint-disable-next-line @typescript-eslint/no-deprecated -- the only copy that works in older iOS Safari
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    field.remove();
  }
}

function clipboard(): Clipboard | undefined {
  // `navigator.clipboard` is missing on insecure origins and old browsers; the DOM types say
  // it is always there.
  return (navigator as Navigator & { clipboard?: Clipboard }).clipboard;
}

/** Copy text already on the page; call it straight from the tap handler. */
export async function copyText(text: string): Promise<boolean> {
  const api = clipboard();
  if (api?.writeText) {
    try {
      await api.writeText(text);
      return true;
    } catch {
      // Refused (permissions, a lost gesture): try the old way.
    }
  }
  return execCopy(text);
}

/** Copy text a request is fetching; call it straight from the tap handler. */
export async function copyLater(text: Promise<string>): Promise<boolean> {
  const api = clipboard();
  if (typeof ClipboardItem !== "undefined" && api?.write) {
    try {
      const blob = text.then((t) => new Blob([t], { type: "text/plain" }));
      await api.write([new ClipboardItem({ "text/plain": blob })]);
      return true;
    } catch {
      // Fall through: the browser refused the deferred item.
    }
  }
  const value = await text;
  if (api?.writeText) {
    try {
      await api.writeText(value);
      return true;
    } catch {
      return execCopy(value);
    }
  }
  return execCopy(value);
}
