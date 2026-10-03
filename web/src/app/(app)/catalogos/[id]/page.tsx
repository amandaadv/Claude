import { prisma } from "@/lib/prisma";
import { PageHeader, Card, Badge, EmptyState, PrimaryButton } from "@/components/ui";
import { ArrowLeft, ImageOff, Upload } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

export default async function CatalogDetailPage({ params }: { params: { id: string } }) {
  const catalog = await prisma.catalog.findUnique({
    where: { id: params.id },
    include: { arts: { orderBy: { pageNumber: "asc" } } },
  });

  if (!catalog) notFound();

  return (
    <div>
      <Link href="/catalogos" className="mb-4 inline-flex items-center gap-1.5 text-sm text-ink-500 hover:text-brand-600">
        <ArrowLeft className="h-4 w-4" />
        Catálogos
      </Link>

      <PageHeader
        title={catalog.name}
        description={`${catalog.arts.length} figuras · ${catalog.material === "TEXTIL" ? "Têxtil" : catalog.material === "UV" ? "UV" : "Têxtil + UV"}`}
        action={
          <PrimaryButton>
            <Upload className="h-4 w-4" />
            Publicar no site
          </PrimaryButton>
        }
      />

      {catalog.arts.length === 0 ? (
        <EmptyState
          icon={ImageOff}
          title="Catálogo sem figuras ainda"
          description="A importação do master pelo worker de produção ainda não gerou as artes individuais deste catálogo."
        />
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
          {catalog.arts.map((art) => (
            <Card key={art.id} className="overflow-hidden">
              <div className="flex aspect-square items-center justify-center bg-ink-50 dark:bg-white/5">
                {art.previewImageUrl ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={art.previewImageUrl} alt={art.reference ?? ""} className="h-full w-full object-contain" />
                ) : (
                  <ImageOff className="h-6 w-6 text-ink-300" />
                )}
              </div>
              <div className="p-2.5">
                <p className="truncate text-xs font-medium text-ink-800 dark:text-ink-100">
                  REF {art.reference ?? "—"}
                </p>
                <div className="mt-1">
                  <Badge tone={art.reviewStatus === "APROVADO" ? "green" : "amber"}>
                    {art.reviewStatus === "APROVADO" ? "Aprovado" : "Pendente"}
                  </Badge>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
