# Baby Luz — Web

Painel web de produção/catálogos — a Fase 0 + 1 do plano de migração (ver documento de
análise técnica). Stack: Next.js 16 (App Router) + TypeScript + Tailwind + Prisma + NextAuth.

## Rodar localmente

Funciona igual no Windows (cmd/PowerShell), Mac e Linux — não precisa copiar `.env` manualmente,
isso acontece sozinho no primeiro comando:

```bash
npm install
npm run db:push               # cria o banco (SQLite em dev) a partir do schema.prisma
npm run db:seed               # cria o usuário admin + dados de exemplo
npm run dev
```

Login padrão (seed): `admin@babyluzconfeccao.com.br` / `babyluz2026` — **troque depois do primeiro acesso**.

### Resolução de problemas

- **"Cannot find module '.prisma/client/default'"** — o Prisma Client não foi gerado.
  Resolve com `npx prisma generate` (o `npm install` já roda isso sozinho via `postinstall`).
- **"Environment variable not found: DATABASE_URL"** ou `[next-auth][error][NO_SECRET]`
  — o arquivo `.env` não existe. Todo comando (`dev`, `build`, `db:push`, `db:seed`) já cria
  ele sozinho agora; se mesmo assim acontecer, rode `node scripts/ensure-env.js` manualmente.
- **"localhost recusou-se a conectar" no navegador** — o terminal rodando `npm run dev`
  fechou ou travou. Abra um terminal na pasta `web` e rode `npm run dev` de novo; só volte
  pro navegador depois de ver a linha `✓ Ready`.

## O que já está aqui

- Login com usuário/senha (NextAuth + bcrypt), sessão JWT, rotas protegidas por middleware.
- Dashboard com números reais do banco (catálogos, fila, pedidos, produções do mês).
- Catálogos (lista + detalhe com grade de figuras), Fila de Produção (agrupada por cliente),
  Pedidos do Site, Tabela de Preços, Representantes, Configurações.
- Schema Prisma unificando o que hoje são dois bancos separados (SQLite do app desktop +
  MySQL do site PHP) — ver `prisma/schema.prisma`.
- Totalmente responsivo (mobile/tablet/desktop), com menu lateral que vira gaveta no celular.

## O que falta (próximas fases do plano)

- Fila de jobs (`RenderJob` já está no schema) + worker Windows que roda o CorelDRAW de fato
  (Fase 2 do plano de migração) — hoje os botões de "Gerar produção" e "Importar catálogo"
  ainda não disparam esse worker.
- Formulários de criar/editar (catálogo, preço, representante) — hoje as telas mostram os
  dados, as ações de escrita vêm na próxima rodada.
- Página pública (vitrine do cliente) e autenticação de representante — herdada do site PHP,
  ainda não portada.
- Upload de imagens para storage de objetos (hoje `coverImageUrl`/`previewImageUrl` ficam
  vazios até a importação real existir).
