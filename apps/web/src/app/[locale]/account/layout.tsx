import { AccountSidebar } from "@/components/account/AccountSidebar";

/** Every profile page: the sections as tabs along the top, the page under them. */
export default function AccountLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto flex max-w-[1100px] flex-col gap-8 px-4 py-8 sm:px-6">
      <AccountSidebar />
      {children}
    </div>
  );
}
