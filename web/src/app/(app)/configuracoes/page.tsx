import { prisma } from "@/lib/prisma";
import { PageHeader, Card } from "@/components/ui";
import { Server, Cpu } from "lucide-react";

export default async function ConfiguracoesPage() {
  const corelVersion = await prisma.setting.findUnique({ where: { key: "target_corel_version" } });
  const pendingJobs = await prisma.renderJob.count({ where: { status: "PENDENTE" } });

  return (
    <div>
      <PageHeader title="Configurações" description="Preferências do sistema e status do worker de produção." />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card className="p-5">
          <div className="mb-3 flex items-center gap-2">
            <Cpu className="h-4 w-4 text-brand-500" />
            <h2 className="font-medium text-ink-900 dark:text-white">Versão de destino do CorelDRAW</h2>
          </div>
          <p className="mb-3 text-sm text-ink-500">
            Arquivos de produção são salvos nessa versão para abrir sem erro em máquinas mais antigas.
          </p>
          <select
            defaultValue={corelVersion?.value ?? "current"}
            className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm dark:border-white/10 dark:bg-white/5"
          >
            <option value="current">Versão atual (sem conversão)</option>
            <option value="24">CorelDRAW 2022 (v24)</option>
            <option value="21">CorelDRAW 2019 (v21)</option>
            <option value="18">CorelDRAW 2016 (v18)</option>
          </select>
        </Card>

        <Card className="p-5">
          <div className="mb-3 flex items-center gap-2">
            <Server className="h-4 w-4 text-brand-500" />
            <h2 className="font-medium text-ink-900 dark:text-white">Worker de produção (CorelDRAW)</h2>
          </div>
          <p className="text-sm text-ink-500">
            {pendingJobs > 0
              ? `${pendingJobs} job(s) na fila aguardando o worker Windows.`
              : "Nenhum job pendente — worker ainda não configurado nesta instalação."}
          </p>
        </Card>
      </div>
    </div>
  );
}
