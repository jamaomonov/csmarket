/**
 * The API's problem+json answers, as the session client reads them: the error it throws
 * for a non-2xx answer and the one refusal it tells apart (a suspended account).
 */

/** problem+json `type` of the API's `AccountSuspendedError` (403). */
export const ACCOUNT_SUSPENDED_TYPE = "https://csmarket.uz/errors/account-suspended";

/** A non-2xx answer from our API; `body` is the parsed problem+json (or raw text). */
export class SessionApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly statusText: string,
    public readonly body: unknown,
  ) {
    super(`${status.toString()} ${statusText}`);
    this.name = "SessionApiError";
  }

  /** problem+json `code` (e.g. "trade_link_not_yours"), when the API sent one. */
  get code(): string | undefined {
    // Narrowing an unknown JSON body to the problem+json shape we read.
    const b = this.body as { code?: unknown } | null;
    return typeof b?.code === "string" ? b.code : undefined;
  }

  /** problem+json `type` URI. */
  get type(): string | undefined {
    // Narrowing an unknown JSON body to the problem+json shape we read.
    const b = this.body as { type?: unknown } | null;
    return typeof b?.type === "string" ? b.type : undefined;
  }
}

/** The answer body as JSON when it parses, else its text, else `null`. */
export async function readErrorBody(response: Response): Promise<unknown> {
  const text = await response.text().catch(() => "");
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

/** Whether a 403 is the API's `account-suspended` problem (and not any other refusal). */
export async function isSuspendedAnswer(response: Response): Promise<boolean> {
  const body = await readErrorBody(response);
  // Narrowing an unknown JSON body to the problem+json field we read.
  const type = (body as { type?: unknown } | null)?.type;
  return type === ACCOUNT_SUSPENDED_TYPE;
}
