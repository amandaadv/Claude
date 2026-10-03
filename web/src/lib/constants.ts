// SQLite não suporta enum nativo no Prisma — esses valores são a fonte da
// verdade usada pela UI e validações. Em produção (Postgres) dá pra promover
// pra enum real do banco sem mudar a lógica da aplicação.

export const ROLES = ["ADMIN", "OPERADOR", "REPRESENTANTE"] as const;
export type Role = (typeof ROLES)[number];

export const CATALOG_STATUS = ["PROCESSANDO", "PRONTO", "FALHOU"] as const;
export type CatalogStatus = (typeof CATALOG_STATUS)[number];

export const MATERIALS = ["TEXTIL", "UV", "TEXTIL_UV"] as const;
export type Material = (typeof MATERIALS)[number];
export const MATERIAL_LABEL: Record<Material, string> = {
  TEXTIL: "Têxtil",
  UV: "UV",
  TEXTIL_UV: "Têxtil + UV",
};

export const CATEGORIAS = ["APLIQUE", "FAIXA"] as const;
export type Categoria = (typeof CATEGORIAS)[number];

export const REVIEW_STATUS = ["PENDENTE", "APROVADO"] as const;
export const QUEUE_STATUS = ["PENDENTE", "PRODUZIDO"] as const;
export const PEDIDO_STATUS = ["PENDENTE", "VALIDADO", "EXCLUIDO"] as const;

export const JOB_TYPES = [
  "IMPORTAR_MASTER",
  "GERAR_PRODUCAO",
  "GERAR_CATALOGO_3_MEDIDAS",
  "MONTAR_FOLHA",
  "CORRIGIR_TAMANHO",
  "CONVERTER_VERSAO",
] as const;
export const JOB_STATUS = ["PENDENTE", "EXECUTANDO", "CONCLUIDO", "FALHOU"] as const;
