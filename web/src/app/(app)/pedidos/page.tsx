import { prisma } from "@/lib/prisma";
import { PageHeader, Card, Badge, EmptyState, PrimaryButton } from "@/components/ui";
import { ShoppingBag, Check, X } from "lucide-react";

export default async function PedidosPage() {
  const pedidos = await prisma.pedido.findMany({
    where: { status: "PENDENTE" },
    include: { itens: true },
    orderBy: { createdAt: "desc" },
  });

  return (
    <div>
      <PageHeader title="Pedidos do Site" description="Pedidos recebidos pela vitrine pública, aguardando validação." />

      {pedidos.length === 0 ? (
        <EmptyState icon={ShoppingBag} title="Nenhum pedido pendente" description="Quando uma cliente finalizar um pedido no site, ele aparece aqui." />
      ) : (
        <div className="space-y-4">
          {pedidos.map((p) => (
            <Card key={p.id} className="p-5">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="font-medium text-ink-900 dark:text-white">{p.clienteNome}</p>
                  <p className="text-xs text-ink-400">{p.clienteTelefone} · {p.itens.length} itens</p>
                </div>
                <div className="flex gap-2">
                  <button className="flex items-center gap-1.5 rounded-xl border border-ink-200 px-3 py-1.5 text-xs font-medium text-ink-600 hover:bg-ink-50 dark:border-white/10 dark:text-ink-300 dark:hover:bg-white/5">
                    <X className="h-3.5 w-3.5" />
                    Excluir
                  </button>
                  <PrimaryButton className="text-xs">
                    <Check className="h-3.5 w-3.5" />
                    Validar
                  </PrimaryButton>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                {p.itens.map((item) => (
                  <Badge key={item.id} tone="neutral">
                    {item.catalogo} · REF {item.referencia} ×{item.quantidade}
                  </Badge>
                ))}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
