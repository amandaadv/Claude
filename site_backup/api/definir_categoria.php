<?php
// Protegido (X-Api-Secret): troca só a CATEGORIA ('aplique' | 'faixa') de um
// catálogo já publicado, sem reenviar nenhuma imagem -- o programa chama isso
// quando o dj muda o "Tipo" do catálogo (ver publicar.php, $categoria).
// Como excluir_catalogo.php, só mexe no que ESTA máquina publicou.
require __DIR__ . '/config.php';
header('Content-Type: application/json; charset=utf-8');
require_api_secret();

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode(['erro' => 'método não permitido']);
    exit;
}

$body = json_body();
$catalogo = trim((string)($body['catalogo'] ?? ''));
$categoria = strtolower(trim((string)($body['categoria'] ?? '')));
if ($catalogo === '' || !in_array($categoria, ['aplique', 'faixa', ''], true)) {
    http_response_code(400);
    echo json_encode(['erro' => "catalogo e categoria ('aplique' | 'faixa' | '' pra limpar) são obrigatórios"]);
    exit;
}

$pdo = get_pdo();
try {
    $pdo->exec("ALTER TABLE produtos ADD COLUMN categoria VARCHAR(16) NULL");
} catch (Exception $e) {
    // coluna já existe.
}

$stmt = $pdo->prepare("UPDATE produtos SET categoria = ? WHERE catalogo_nome = ? AND origem_ip = ?");
$stmt->execute([$categoria === '' ? null : $categoria, $catalogo, get_caller_identity()]);

echo json_encode(['ok' => true, 'atualizados' => $stmt->rowCount()]);
