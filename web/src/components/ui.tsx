import clsx from "clsx";
import type { LucideIcon } from "lucide-react";

export function PageHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-ink-900 dark:text-white">{title}</h1>
        {description && <p className="mt-1 text-sm text-ink-500">{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function Card({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div
      className={clsx(
        "rounded-2xl border border-ink-200/70 bg-white shadow-soft dark:border-white/5 dark:bg-ink-900/60",
        className
      )}
    >
      {children}
    </div>
  );
}

export function StatCard({
  label,
  value,
  icon: Icon,
  tone = "brand",
  hint,
}: {
  label: string;
  value: string | number;
  icon: LucideIcon;
  tone?: "brand" | "green" | "amber" | "blue";
  hint?: string;
}) {
  const tones: Record<string, string> = {
    brand: "from-brand-400 to-brand-600",
    green: "from-emerald-400 to-emerald-600",
    amber: "from-amber-400 to-amber-600",
    blue: "from-sky-400 to-sky-600",
  };
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-ink-500">{label}</p>
          <p className="mt-1.5 text-2xl font-semibold text-ink-900 dark:text-white">{value}</p>
          {hint && <p className="mt-1 text-xs text-ink-400">{hint}</p>}
        </div>
        <div className={clsx("flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br", tones[tone])}>
          <Icon className="h-5 w-5 text-white" />
        </div>
      </div>
    </Card>
  );
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "brand" | "green" | "amber" | "red";
}) {
  const tones: Record<string, string> = {
    neutral: "bg-ink-100 text-ink-600 dark:bg-white/10 dark:text-ink-300",
    brand: "bg-brand-100 text-brand-700 dark:bg-brand-500/15 dark:text-brand-300",
    green: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
    amber: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
    red: "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300",
  };
  return (
    <span className={clsx("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", tones[tone])}>
      {children}
    </span>
  );
}

export function EmptyState({ icon: Icon, title, description }: { icon: LucideIcon; title: string; description?: string }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-ink-300 py-16 text-center dark:border-white/10">
      <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-ink-100 dark:bg-white/5">
        <Icon className="h-6 w-6 text-ink-400" />
      </div>
      <p className="font-medium text-ink-700 dark:text-ink-200">{title}</p>
      {description && <p className="mt-1 max-w-sm text-sm text-ink-400">{description}</p>}
    </div>
  );
}

export function PrimaryButton({
  children,
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={clsx(
        "inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-brand-500 to-brand-600 px-4 py-2 text-sm font-medium text-white shadow-sm shadow-brand-500/30 transition hover:brightness-105 active:scale-[0.98] disabled:opacity-50",
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
}
