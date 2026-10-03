import { LibraryBig, ListOrdered, ShoppingBag, Wallet } from "lucide-react";
import { prisma } from "@/lib/prisma";
import { PageHeader, StatCard, Card, Badge, EmptyState } from "@/components/ui";
import Link from "next/link";

export default async function DashboardPage() {
  const [catalogCount, pendingQueue, pendingOrders, productionsThisMonth, recentCatalogs] = await Promise.all([
    prisma.catalog.count(),
    prisma.productionQueueItem.count({ where: { status: "PENDENTE" } }),
    prisma.pedido.count({ where: { status: "PENDENTE" } }),
    prisma.production.count({
      where: { createdAt: { gte: new Date(new Date().getFullYear(), new Date().getMonth(), 1) } },
    }),
    prisma.catalog.findMany({ orderBy: { createdAt: "desc" }, take: 5, include: { _count: { select: { arts: true } } } }),
  ]);

  return (
    <div>
      <PageHeader title="Visão geral" description="Resumo da produção e dos catálogos em tempo real." />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Catálogos" value={catalogCount} icon={LibraryBig} tone="brand" />
        <StatCard label="Na fila de produção" value={pendingQueue} icon={ListOrdered} tone="amber" hint="pendentes" />
        <StatCard label="Pedidos do site" value={pendingOrders} icon={ShoppingBag} tone="blue" hint="aguardando validação" />
        <StatCard label="Produções este mês" value={productionsThisMonth} icon={Wallet} tone="green" />
      </div>

      <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card className="col-span-2 p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-semibold text-ink-900 dark:text-white">Catálogos recentes</h2>
            <Link href="/catalogos" className="text-sm font-medium text-brand-600 hover:underline dark:text-brand-400">
              ver todos
            </Link>
          </div>

          {recentCatalogs.length === 0 ? (
            <EmptyState
              icon={LibraryBig}
              title="Nenhum catálogo importado ainda"
              description="Importe um catálogo master para começar — a arte vetorial é processada pelo worker de produção."
            />
          ) : (
            <div className="divide-y divide-ink-100 dark:divide-white/5">
              {recentCatalogs.map((c) => (
                <Link
                  key={c.id}
                  href={`/catalogos/${c.id}`}
                  className="flex items-center justify-between gap-4 py-3 transition hover:bg-ink-50/80 dark:hover:bg-white/[0.03] rounded-lg px-2 -mx-2"
                >
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-100 text-sm font-semibold text-brand-700 dark:bg-brand-500/15 dark:text-brand-300">
                      {c.name.slice(0, 2).toUpperCase()}
                    </div>
                    <div>
                      <p className="text-sm font-medium text-ink-800 dark:text-ink-100">{c.name}</p>
                      <p className="text-xs text-ink-400">{c._count.arts} figuras</p>
                    </div>
                  </div>
                  <Badge tone={c.status === "PRONTO" ? "green" : c.status === "PROCESSANDO" ? "amber" : "red"}>
                    {c.status === "PRONTO" ? "Pronto" : c.status === "PROCESSANDO" ? "Processando" : "Falhou"}
                  </Badge>
                </Link>
              ))}
            </div>
          )}
        </Card>

        <Card className="p-5">
          <h2 className="mb-4 font-semibold text-ink-900 dark:text-white">Atalhos</h2>
          <div className="space-y-2">
            <QuickLink href="/catalogos" label="Importar catálogo" />
            <QuickLink href="/fila" label="Ver fila de produção" />
            <QuickLink href="/pedidos" label="Validar pedidos do site" />
            <QuickLink href="/precos" label="Editar tabela de preços" />
          </div>
        </Card>
      </div>
    </div>
  );
}

function QuickLink({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="flex items-center justify-between rounded-xl border border-ink-200/70 px-4 py-3 text-sm font-medium text-ink-700 transition hover:border-brand-300 hover:bg-brand-50 dark:border-white/10 dark:text-ink-200 dark:hover:bg-white/5"
    >
      {label}
      <span className="text-ink-400">→</span>
    </Link>
  );
}
