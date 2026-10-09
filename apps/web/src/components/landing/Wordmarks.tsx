/** Click / Payme / Uzum as text wordmarks in their colours (no fetched trademarks). */
import { WalletIcon } from "./Icons";

export function PayMarks({ balance }: { balance?: string }) {
  return (
    <>
      <span className="wm wm-click">
        <i />
        click
      </span>
      <span className="wm wm-payme">
        pay<b>me</b>
      </span>
      <span className="wm wm-uzum">
        <i />
        uzum
      </span>
      {balance !== undefined && (
        <span className="wm wm-bal">
          <WalletIcon />
          {balance}
        </span>
      )}
    </>
  );
}
