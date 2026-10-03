import { PrismaClient } from "@prisma/client";
import bcrypt from "bcryptjs";

const prisma = new PrismaClient();

async function main() {
  // Usuário admin padrão — TROQUE A SENHA depois do primeiro login.
  const passwordHash = await bcrypt.hash("babyluz2026", 10);
  await prisma.user.upsert({
    where: { email: "admin@babyluzconfeccao.com.br" },
    update: {},
    create: {
      name: "Administrador",
      email: "admin@babyluzconfeccao.com.br",
      passwordHash,
      role: "ADMIN",
      avatarColor: "#f04577",
    },
  });

  const profile = await prisma.productionProfile.upsert({
    where: { id: "default-profile" },
    update: {},
    create: {
      id: "default-profile",
      name: "Padrão Têxtil 100cm",
      widthMm: 1000,
      heightMm: 1500,
      marginLeftMm: 5,
      marginRightMm: 5,
      marginTopMm: 5,
      marginBottomMm: 5,
      spacingHMm: 3,
      spacingVMm: 3,
      isDefault: true,
      material: "TEXTIL",
    },
  });

  const catalogsData = [
    { name: "Catálogo Baby 01", material: "TEXTIL" as const, categoriaSite: "APLIQUE" as const, arts: 12 },
    { name: "Catálogo Faixas Baby Cores 2", material: "TEXTIL" as const, categoriaSite: "FAIXA" as const, arts: 8 },
    { name: "Catálogo Natalinos", material: "UV" as const, categoriaSite: "APLIQUE" as const, arts: 15 },
  ];

  for (const [index, c] of catalogsData.entries()) {
    const catalog = await prisma.catalog.upsert({
      where: { id: `seed-catalog-${index}` },
      update: {},
      create: {
        id: `seed-catalog-${index}`,
        name: c.name,
        material: c.material,
        categoriaSite: c.categoriaSite,
        status: "PRONTO",
        displayOrder: index,
        defaultWidthMm: 80,
        defaultHeightMm: 80,
        publishedAt: new Date(),
      },
    });

    for (let i = 1; i <= c.arts; i++) {
      await prisma.catalogArt.upsert({
        where: { id: `seed-art-${index}-${i}` },
        update: {},
        create: {
          id: `seed-art-${index}-${i}`,
          catalogId: catalog.id,
          reference: String(1000 + index * 100 + i),
          pageNumber: i,
          reviewStatus: "APROVADO",
        },
      });
    }
  }

  const prices = [
    { tipo: "Aplique Termocolante", material: "TEXTIL" as const, larguraCm: 8, alturaCm: 8, valor: 2.5 },
    { tipo: "Aplique Termocolante", material: "TEXTIL" as const, larguraCm: 12, alturaCm: 12, valor: 4.0 },
    { tipo: "Faixa Termocolante", material: "TEXTIL" as const, larguraCm: 30, alturaCm: 5, valor: 6.5 },
    { tipo: "Aplique UV", material: "UV" as const, larguraCm: 8, alturaCm: 8, valor: 3.2 },
  ];
  for (const p of prices) {
    await prisma.productPrice.upsert({
      where: { tipo_material_larguraCm_alturaCm: { tipo: p.tipo, material: p.material, larguraCm: p.larguraCm, alturaCm: p.alturaCm } },
      update: {},
      create: p,
    });
  }

  await prisma.representante.upsert({
    where: { usuario: "maria.vendas" },
    update: {},
    create: {
      nome: "Maria Souza",
      usuario: "maria.vendas",
      senhaHash: await bcrypt.hash("troque-depois", 10),
      regiao: "Sudeste",
      ativo: true,
    },
  });

  await prisma.setting.upsert({
    where: { key: "target_corel_version" },
    update: {},
    create: { key: "target_corel_version", value: "current" },
  });

  console.log("Seed concluído. Login: admin@babyluzconfeccao.com.br / babyluz2026");
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
