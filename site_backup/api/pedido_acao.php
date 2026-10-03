<?php
// Protegido (X-Api-Secret): marca um pedido como validado ou excluído, depois
// que o programa do computador já processou (ou a operadora decidiu excluir).
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
$acao = (string)($body['acao'] ?? '');

if ($pedido_id <= 0 || !in_array($acao, ['validar', 'excluir'], true)) {
    http_response_code(400);
    echo json_encode(['erro' => 'pedido_id e acao (validar|excluir) são obrigatórios']);
    exit;
}

$novo_status = $acao === 'validar' ? 'validado' : 'excluido';

$pdo = get_pdo();
$stmt = $pdo->prepare("UPDATE pedidos SET status = ? WHERE id = ?");
$stmt->execute([$novo_status, $pedido_id]);

echo json_encode(['ok' => true, 'status' => $novo_status]);
