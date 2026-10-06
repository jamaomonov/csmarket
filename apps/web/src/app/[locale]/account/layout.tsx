import { AccountSidebar } from "@/components/account/AccountSidebar";

/** Every profile page: the sections on the left (a row of tabs on phones), the page beside. */
export default function AccountLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto flex max-w-[1100px] flex-col gap-6 px-4 py-8 sm:px-6 lg:flex-row lg:gap-10">
      <AccountSidebar />
      {children}
    </div>
  );
}
