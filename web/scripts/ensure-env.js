// Garante que .env existe antes de qualquer comando (dev/build/db:push/db:seed).
// Evita o erro "Environment variable not found: DATABASE_URL" quando alguém
// esquece (ou não consegue, no cmd.exe do Windows) de rodar `cp .env.example .env`.
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const root = path.join(__dirname, "..");
const envPath = path.join(root, ".env");
const examplePath = path.join(root, ".env.example");

if (!fs.existsSync(envPath)) {
  let content = fs.readFileSync(examplePath, "utf8");
  const secret = crypto.randomBytes(32).toString("hex");
  content = content.replace(
    /NEXTAUTH_SECRET=.*/,
    `NEXTAUTH_SECRET="${secret}"`
  );
  fs.writeFileSync(envPath, content);
  console.log("[ensure-env] .env não existia — criado automaticamente a partir de .env.example.");
}
