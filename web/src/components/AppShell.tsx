"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut } from "next-auth/react";
import { Menu, X, Sparkles, LogOut, Bell } from "lucide-react";
import { NAV_ITEMS } from "./nav-items";
import clsx from "clsx";

type Props = {
  children: React.ReactNode;
  user: { name?: string | null; email?: string | null; role?: string; avatarColor?: string };
  pendingQueueCount?: number;
  pendingOrdersCount?: number;
};

export function AppShell({ children, user, pendingQueueCount = 0, pendingOrdersCount = 0 }: Props) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const pathname = usePathname();
  const initials = (user.name ?? user.email ?? "?").slice(0, 1).toUpperCase();

  const badgeFor: Record<string, number> = {
    "/fila": pendingQueueCount,
    "/pedidos": pendingOrdersCount,
  };

  return (
    <div className="flex min-h-screen bg-ink-50 dark:bg-ink-950">
      {/* Sidebar — desktop */}
      <aside className="hidden w-64 shrink-0 flex-col border-r border-ink-200/70 bg-white dark:border-white/5 dark:bg-ink-900/60 lg:flex">
        <SidebarContent pathname={pathname} badgeFor={badgeFor} user={user} initials={initials} />
      </aside>

      {/* Sidebar — mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 bg-white shadow-2xl dark:bg-ink-900">
            <div className="flex justify-end p-3">
              <button
                onClick={() => setMobileOpen(false)}
                className="rounded-lg p-1.5 text-ink-500 hover:bg-ink-100 dark:hover:bg-white/5"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <SidebarContent
              pathname={pathname}
              badgeFor={badgeFor}
              user={user}
              initials={initials}
              onNavigate={() => setMobileOpen(false)}
            />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Topbar */}
        <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-ink-200/70 bg-white/80 px-4 backdrop-blur-xl dark:border-white/5 dark:bg-ink-950/80 sm:px-6">
          <button
            onClick={() => setMobileOpen(true)}
            className="rounded-lg p-2 text-ink-500 hover:bg-ink-100 dark:hover:bg-white/5 lg:hidden"
          >
            <Menu className="h-5 w-5" />
          </button>
          <div className="flex items-center gap-2 lg:hidden">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-brand-400 to-brand-600">
              <Sparkles className="h-4 w-4 text-white" />
            </div>
            <span className="font-semibold text-ink-900 dark:text-white">Baby Luz</span>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <button className="relative rounded-lg p-2 text-ink-500 hover:bg-ink-100 dark:hover:bg-white/5">
              <Bell className="h-5 w-5" />
              {pendingQueueCount + pendingOrdersCount > 0 && (
                <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-brand-500" />
              )}
            </button>
            <button
              onClick={() => signOut({ callbackUrl: "/login" })}
              className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-ink-500 hover:bg-ink-100 dark:hover:bg-white/5"
            >
              <LogOut className="h-4 w-4" />
              <span className="hidden sm:inline">Saír</span>
            </button>
          </div>
        </header>

        <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">{children}</main>
      </div>
    </div>
  );
}

function SidebarContent({
  pathname,
  badgeFor,
  user,
  initials,
  onNavigate,
}: {
  pathname: string;
  badgeFor: Record<string, number>;
  user: Props["user"];
  initials: string;
  onNavigate?: () => void;
}) {
  return (
    <>
      <div className="flex h-16 items-center gap-2.5 px-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-brand-400 to-brand-600 shadow-sm shadow-brand-500/30">
          <Sparkles className="h-4.5 w-4.5 text-white" />
        </div>
        <div className="leading-tight">
          <p className="font-semibold text-ink-900 dark:text-white">Baby Luz</p>
          <p className="text-[11px] text-ink-400">Produção &amp; Catálogos</p>
        </div>
      </div>

      <nav className="flex-1 space-y-0.5 px-3 py-2">
        {NAV_ITEMS.map((item) => {
          const active = pathname === item.href || pathname.startsWith(item.href + "/");
          const badge = badgeFor[item.href];
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onNavigate}
              className={clsx(
                "group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition",
                active
                  ? "bg-gradient-to-r from-brand-500/15 to-brand-500/5 text-brand-700 dark:text-brand-300"
                  : "text-ink-600 hover:bg-ink-100 dark:text-ink-300 dark:hover:bg-white/5"
              )}
            >
              <item.icon
                className={clsx("h-[18px] w-[18px]", active ? "text-brand-600 dark:text-brand-400" : "text-ink-400")}
              />
              <span className="flex-1">{item.label}</span>
              {!!badge && (
                <span className="rounded-full bg-brand-500 px-1.5 py-0.5 text-[10px] font-bold text-white">
                  {badge}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      <div className="m-3 flex items-center gap-3 rounded-xl bg-ink-100/60 p-3 dark:bg-white/5">
        <div
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-bold text-white"
          style={{ backgroundColor: user.avatarColor ?? "#ff6d96" }}
        >
          {initials}
        </div>
        <div className="min-w-0 leading-tight">
          <p className="truncate text-sm font-medium text-ink-800 dark:text-ink-100">{user.name ?? user.email}</p>
          <p className="truncate text-[11px] text-ink-400">{user.role ?? "Operador"}</p>
        </div>
      </div>
    </>
  );
}
