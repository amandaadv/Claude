import { prisma } from "@/lib/prisma";
import { PageHeader, Card, Badge, EmptyState, PrimaryButton } from "@/components/ui";
import { LibraryBig, Plus, ImageOff } from "lucide-react";
import Link from "next/link";

const MATERIAL_LABEL: Record<string, string> = {
  TEXTIL: "Têxtil",
  UV: "UV",
  TEXTIL_UV: "Têxtil + UV",
};

export default async function CatalogosPage() {
  const catalogos = await prisma.catalog.findMany({
    orderBy: { displayOrder: "asc" },
    include: { _count: { select: { arts: true } } },
  });

  return (
    <div>
      <PageHeader
        title="Catálogos"
        description="Gerencie os catálogos, publique no site e organize por material e categoria."
        action={
          <PrimaryButton>
            <Plus className="h-4 w-4" />
            Importar catálogo
          </PrimaryButton>
        }
      />

      {catalogos.length === 0 ? (
        <EmptyState
          icon={LibraryBig}
          title="Nenhum catálogo cadastrado"
          description='Clique em "Importar catálogo" para trazer um arquivo master — a extração da arte vetorial roda no worker de produção (CorelDRAW).'
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {catalogos.map((c) => (
            <Link key={c.id} href={`/catalogos/${c.id}`}>
              <Card className="group overflow-hidden transition hover:-translate-y-0.5 hover:shadow-card">
                <div className="flex aspect-[4/3] items-center justify-center bg-gradient-to-br from-brand-50 to-ink-50 dark:from-brand-500/10 dark:to-white/5">
                  {c.coverImageUrl ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={c.coverImageUrl} alt={c.name} className="h-full w-full object-cover" />
                  ) : (
                    <ImageOff className="h-8 w-8 text-ink-300 dark:text-white/20" />
                  )}
                </div>
                <div className="p-4">
                  <div className="mb-1.5 flex items-center justify-between gap-2">
                    <p className="truncate font-medium text-ink-900 dark:text-white">{c.name}</p>
                    {c.isPrivate && <Badge tone="amber">Privado</Badge>}
                  </div>
                  <div className="flex items-center gap-1.5 text-xs text-ink-400">
                    <span>{c._count.arts} figuras</span>
                    <span>·</span>
                    <span>{MATERIAL_LABEL[c.material]}</span>
                  </div>
                  <div className="mt-3 flex items-center gap-1.5">
                    <Badge tone={c.status === "PRONTO" ? "green" : c.status === "PROCESSANDO" ? "amber" : "red"}>
                      {c.status === "PRONTO" ? "Pronto" : c.status === "PROCESSANDO" ? "Processando" : "Falhou"}
                    </Badge>
                    {c.publishedAt && <Badge tone="brand">Publicado</Badge>}
                  </div>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
