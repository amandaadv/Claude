<?php
// Público (só leitura): dados da página "meu pedido" (pedido.php?c=codigo).
// Link mesclado: junta TODOS os pedidos (pendente + validado) da mesma
// cliente. Link de produção: mostra exatamente a lista guardada nele (ver
// pedido_util.php). Nunca devolve o telefone, e nada aqui escreve na base de
// pedidos (só lê).
require __DIR__ . '/config.php';
require __DIR__ . '/pedido_util.php';
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
header('Pragma: no-cache');
header('X-Robots-Tag: noindex, nofollow');

$codigo = trim((string)($_GET['c'] ?? ''));
if ($codigo === '' || strlen($codigo) > 64) {
    http_response_code(400);
    echo json_encode(['erro' => 'código é obrigatório']);
    exit;
}

$pdo = get_pdo();
pedido_garantir_tabela_links($pdo);

$stmt = $pdo->prepare("SELECT nome_exibicao, nome_key, telefone_key, itens_json FROM pedido_links WHERE codigo = ?");
$stmt->execute([$codigo]);
$link = $stmt->fetch();
if (!$link) {
    http_response_code(404);
    echo json_encode(['erro' => 'link não encontrado']);
    exit;
}

echo json_encode(pedido_dados_do_link($pdo, $link), JSON_UNESCAPED_UNICODE);
