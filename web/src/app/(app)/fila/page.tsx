import { prisma } from "@/lib/prisma";
import { PageHeader, Card, Badge, EmptyState, PrimaryButton } from "@/components/ui";
import { ListOrdered, Play } from "lucide-react";

export default async function FilaPage() {
  const items = await prisma.productionQueueItem.findMany({
    where: { status: "PENDENTE" },
    include: { catalogArt: { include: { catalog: true } } },
    orderBy: { createdAt: "asc" },
  });

  const groups = new Map<string, typeof items>();
  for (const item of items) {
    const key = `${item.clientName ?? "Sem cliente"}__${item.orderBatchId ?? item.id}`;
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }

  return (
    <div>
      <PageHeader
        title="Fila de Produção"
        description="Itens pendentes, agrupados por cliente/pedido. Gere a produção quando estiver pronto."
      />

      {groups.size === 0 ? (
        <EmptyState
          icon={ListOrdered}
          title="Fila vazia"
          description="Monte um pedido ou adicione figuras à fila para começar uma produção."
        />
      ) : (
        <div className="space-y-4">
          {[...groups.entries()].map(([key, groupItems]) => {
            const first = groupItems[0];
            return (
              <Card key={key} className="p-5">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="font-medium text-ink-900 dark:text-white">{first.clientName ?? "Sem cliente"}</p>
                    <p className="text-xs text-ink-400">{first.clientPhone ?? "sem telefone"} · {groupItems.length} itens</p>
                  </div>
                  <PrimaryButton className="text-xs">
                    <Play className="h-3.5 w-3.5" />
                    Gerar produção
                  </PrimaryButton>
                </div>
                <div className="flex flex-wrap gap-2">
                  {groupItems.map((item) => (
                    <Badge key={item.id} tone="neutral">
                      REF {item.catalogArt.reference ?? "—"} · {item.widthMm}×{item.heightMm}mm
                      {item.quantity ? ` ×${item.quantity}` : ""}
                    </Badge>
                  ))}
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
