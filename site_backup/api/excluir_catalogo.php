<?php
// Protegido (X-Api-Secret): tira todos os produtos de um catálogo da vitrine
// quando ele é excluído no programa do computador. Desativa em vez de
// apagar a linha, pra não quebrar pedidos antigos que referenciam esses
// produtos (mesma lógica de "sumir da vitrine sem perder histórico" do
// publicar.php).
//
// Só desativa produtos cujo origem_ip bate com a identidade de QUEM ESTÁ
// PEDINDO agora (get_caller_identity em config.php) -- cada computador só
// consegue apagar o que ele mesmo publicou, nunca o que outro computador
// publicou, mesmo que os dois usem catalogo_nome iguais por coincidência.
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
$origem_ip = get_caller_identity();

if ($catalogo === '') {
    http_response_code(400);
    echo json_encode(['erro' => 'catalogo é obrigatório']);
    exit;
}

$pdo = get_pdo();
$stmt = $pdo->prepare("UPDATE produtos SET ativo = 0 WHERE catalogo_nome = ? AND origem_ip = ?");
$stmt->execute([$catalogo, $origem_ip]);

echo json_encode(['ok' => true, 'removidos' => $stmt->rowCount()]);
