<?php
// Protegido (X-Api-Secret): remove UM item de um pedido (a operadora tirou
// aquele desenho específico da lista do cliente), sem excluir o pedido inteiro.
require __DIR__ . '/config.php';
header('Content-Type: application/json; charset=utf-8');
require_api_secret();

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode(['erro' => 'método não permitido']);
    exit;
}

$body = json_body();
$pedido_id = (int)($body['pedido_id'] ?? 0);
$produto_id = (int)($body['produto_id'] ?? 0);
// item_id (opcional): remove SÓ aquela linha. A mesma figura pode estar no
// pedido em mais de uma linha (tipos/medidas diferentes) -- sem item_id
// continua removendo todas as linhas da figura, como antes.
$item_id = (int)($body['item_id'] ?? 0);

if ($pedido_id <= 0 || ($produto_id <= 0 && $item_id <= 0)) {
    http_response_code(400);
    echo json_encode(['erro' => 'pedido_id e (item_id ou produto_id) são obrigatórios']);
    exit;
}

$pdo = get_pdo();
if ($item_id > 0) {
    $stmt = $pdo->prepare("DELETE FROM pedido_itens WHERE pedido_id = ? AND id = ?");
    $stmt->execute([$pedido_id, $item_id]);
} else {
    $stmt = $pdo->prepare("DELETE FROM pedido_itens WHERE pedido_id = ? AND produto_id = ?");
    $stmt->execute([$pedido_id, $produto_id]);
}

echo json_encode(['ok' => true, 'removido' => $stmt->rowCount() > 0]);
