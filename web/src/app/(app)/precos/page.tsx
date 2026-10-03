import { prisma } from "@/lib/prisma";
import { PageHeader, Card, EmptyState, PrimaryButton } from "@/components/ui";
import { Tags, Plus } from "lucide-react";

const MATERIAL_LABEL: Record<string, string> = { TEXTIL: "Têxtil", UV: "UV", TEXTIL_UV: "Têxtil + UV" };

export default async function PrecosPage() {
  const precos = await prisma.productPrice.findMany({ orderBy: [{ tipo: "asc" }, { larguraCm: "asc" }] });

  return (
    <div>
      <PageHeader
        title="Tabela de Preços"
        description="Preço por tipo de produto, material e medida — usado nos orçamentos de pedido."
        action={
          <PrimaryButton>
            <Plus className="h-4 w-4" />
            Novo preço
          </PrimaryButton>
        }
      />

      {precos.length === 0 ? (
        <EmptyState icon={Tags} title="Nenhum preço cadastrado" description="Cadastre um preço por tipo + material + medida para gerar orçamentos." />
      ) : (
        <Card className="overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-ink-100 text-left text-xs text-ink-400 dark:border-white/5">
                <th className="px-5 py-3 font-medium">Tipo</th>
                <th className="px-5 py-3 font-medium">Material</th>
                <th className="px-5 py-3 font-medium">Medida</th>
                <th className="px-5 py-3 text-right font-medium">Valor</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100 dark:divide-white/5">
              {precos.map((p) => (
                <tr key={p.id} className="transition hover:bg-ink-50/80 dark:hover:bg-white/[0.03]">
                  <td className="px-5 py-3 font-medium text-ink-800 dark:text-ink-100">{p.tipo}</td>
                  <td className="px-5 py-3 text-ink-500">{MATERIAL_LABEL[p.material]}</td>
                  <td className="px-5 py-3 text-ink-500">{p.larguraCm}×{p.alturaCm}cm</td>
                  <td className="px-5 py-3 text-right font-medium text-ink-800 dark:text-ink-100">
                    {p.valor.toLocaleString("pt-BR", { style: "currency", currency: "BRL" })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
