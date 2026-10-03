import { getServerSession } from "next-auth";
import { redirect } from "next/navigation";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { AppShell } from "@/components/AppShell";

export default async function AppGroupLayout({ children }: { children: React.ReactNode }) {
  const session = await getServerSession(authOptions);
  if (!session?.user) redirect("/login");

  const [pendingQueueCount, pendingOrdersCount] = await Promise.all([
    prisma.productionQueueItem.count({ where: { status: "PENDENTE" } }),
    prisma.pedido.count({ where: { status: "PENDENTE" } }),
  ]);

  return (
    <AppShell
      user={session.user as any}
      pendingQueueCount={pendingQueueCount}
      pendingOrdersCount={pendingOrdersCount}
    >
      {children}
    </AppShell>
  );
}
