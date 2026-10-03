<?php
// Protegido (X-Api-Secret): o programa do computador manda "catalogos"
// (array de nomes) + "cliente" e recebe de volta um código único -- usado por
// catalogo_personalizado.php pra montar o link que vai pro WhatsApp do
// cliente (ver pa.do_create_personalized_catalog).
// Backwards compat: aceita "catalogo" (string singular) quando "catalogos"
// não for enviado (versões antigas do programa).
require __DIR__ . '/config.php';
header('Content-Type: application/json; charset=utf-8');
require_api_secret();

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode(['erro' => 'método não permitido']);
    exit;
}

$body = json_body();

// Aceita lista OU nome singular
$catalogos = $body['catalogos'] ?? null;
if (!is_array($catalogos) || count($catalogos) === 0) {
    $singular = trim((string)($body['catalogo'] ?? ''));
    $catalogos = $singular !== '' ? [$singular] : [];
}
// Limpa e filtra entradas vazias
$catalogos = array_values(array_filter(array_map('trim', $catalogos), fn($n) => $n !== ''));

$cliente = trim((string)($body['cliente'] ?? ''));

if (count($catalogos) === 0 || $cliente === '') {
    http_response_code(400);
    echo json_encode(['erro' => 'catalogos e cliente são obrigatórios']);
    exit;
}

$pdo = get_pdo();
$pdo->exec("
    CREATE TABLE IF NOT EXISTS catalogos_personalizados (
        codigo VARCHAR(64) PRIMARY KEY,
        catalogo_nome VARCHAR(255) NOT NULL,
        cliente_nome VARCHAR(255) NOT NULL,
        criado_em DATETIME DEFAULT CURRENT_TIMESTAMP
    )
");
// Migração: adiciona coluna catalogo_nomes (JSON array) se não existir.
// catalogo_nome fica preenchido com o primeiro nome pra compat com versões
// antigas de catalogo_personalizado.php que ainda leiam só essa coluna.
try {
    $pdo->exec("ALTER TABLE catalogos_personalizados ADD COLUMN catalogo_nomes TEXT NULL");
} catch (Exception $e) {
    // coluna já existe
}

// Código a partir do nome do cliente (sem acento/espaço) + um sufixo
// aleatório curto -- evita colisão entre dois clientes com nome parecido
// (ex: "Maria" e "Maria Silva" não geram o mesmo código), e fica
// legível/curto pra mandar no link do WhatsApp.
$base = mb_strtolower($cliente, 'UTF-8');
$comAcento  = ['á','à','â','ã','ä','é','è','ê','ë','í','ì','î','ï','ó','ò','ô','õ','ö','ú','ù','û','ü','ç'];
$semAcento  = ['a','a','a','a','a','e','e','e','e','i','i','i','i','o','o','o','o','o','u','u','u','u','c'];
$base = str_replace($comAcento, $semAcento, $base);
$base = preg_replace('/[^a-z0-9]+/', '-', $base);
$base = trim($base, '-');
if ($base === '') {
    $base = 'cliente';
}
$codigo = $base . '-' . substr(bin2hex(random_bytes(3)), 0, 6);

$stmt = $pdo->prepare("
    INSERT INTO catalogos_personalizados (codigo, catalogo_nome, cliente_nome, catalogo_nomes)
    VALUES (:codigo, :catalogo, :cliente, :catalogo_nomes)
");
$stmt->execute([
    'codigo'          => $codigo,
    'catalogo'        => $catalogos[0],
    'cliente'         => $cliente,
    'catalogo_nomes'  => json_encode($catalogos, JSON_UNESCAPED_UNICODE),
]);

echo json_encode(['ok' => true, 'codigo' => $codigo]);
