import { prisma } from "@/lib/prisma";
import { PageHeader, Card, Badge, EmptyState, PrimaryButton } from "@/components/ui";
import { Users, Plus } from "lucide-react";

export default async function RepresentantesPage() {
  const representantes = await prisma.representante.findMany({ orderBy: { nome: "asc" } });

  return (
    <div>
      <PageHeader
        title="Representantes"
        description="Representantes que aparecem no site e acessam o painel próprio."
        action={
          <PrimaryButton>
            <Plus className="h-4 w-4" />
            Novo representante
          </PrimaryButton>
        }
      />

      {representantes.length === 0 ? (
        <EmptyState icon={Users} title="Nenhum representante cadastrado" />
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {representantes.map((r) => (
            <Card key={r.id} className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-medium text-ink-900 dark:text-white">{r.nome}</p>
                  <p className="text-xs text-ink-400">@{r.usuario} · {r.regiao ?? "sem região"}</p>
                </div>
                <Badge tone={r.ativo ? "green" : "neutral"}>{r.ativo ? "Ativo" : "Inativo"}</Badge>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
