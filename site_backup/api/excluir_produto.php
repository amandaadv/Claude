<?php
// Protegido (X-Api-Secret): remove só UM produto (catalogo + referencia) da
// vitrine, sem tocar no resto do catálogo. Desativa em vez de apagar, mesma
// lógica de excluir_catalogo.php -- e mesma proteção por IP: só desativa se
// origem_ip bater com quem está pedindo agora.
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
$referencia = trim((string)($body['referencia'] ?? ''));
$origem_ip = get_caller_identity();

if ($catalogo === '' || $referencia === '') {
    http_response_code(400);
    echo json_encode(['erro' => 'catalogo e referencia são obrigatórios']);
    exit;
}

$pdo = get_pdo();
$stmt = $pdo->prepare(
    "UPDATE produtos SET ativo = 0 WHERE catalogo_nome = ? AND referencia = ? AND origem_ip = ?"
);
$stmt->execute([$catalogo, $referencia, $origem_ip]);

echo json_encode(['ok' => true, 'removidos' => $stmt->rowCount()]);
