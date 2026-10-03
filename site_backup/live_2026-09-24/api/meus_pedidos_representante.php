<?php
// Painel do representante (painel.html): lista só os pedidos atribuídos a
// ele (clientes.representante_id, preenchido no finalizar.php a partir do
// seletor obrigatório de representante) -- protegido por sessão de login,
// não pelo X-Api-Secret (esse endpoint é chamado do navegador da cliente
// final/representante, não do app da loja).
require __DIR__ . '/config.php';
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
iniciar_sessao_representante();

if (empty($_SESSION['representante_id'])) {
    http_response_code(401);
    echo json_encode(['ok' => false, 'erro' => 'não autenticado']);
    exit;
}
$representante_id = (int)$_SESSION['representante_id'];

$pdo = get_pdo();
try {
    $pdo->exec("ALTER TABLE clientes ADD COLUMN representante_id INT NULL");
} catch (Exception $e) {
    // coluna já existe.
}

$status = $_GET['status'] ?? 'pendente';
$stmt = $pdo->prepare("
    SELECT p.id AS pedido_id, p.status, p.criado_em, c.nome, c.telefone
    FROM pedidos p
    JOIN clientes c ON c.id = p.cliente_id
    WHERE c.representante_id = ? AND p.status = ?
    ORDER BY p.criado_em DESC
");
$stmt->execute([$representante_id, $status]);
$pedidos = $stmt->fetchAll();

$itens_stmt = $pdo->prepare("
    SELECT pr.referencia, pr.nome, COALESCE(pi.quantidade, 1) AS quantidade, pi.medida
    FROM pedido_itens pi JOIN produtos pr ON pr.id = pi.produto_id
    WHERE pi.pedido_id = ?
");
foreach ($pedidos as &$pedido) {
    $itens_stmt->execute([$pedido['pedido_id']]);
    $pedido['itens'] = $itens_stmt->fetchAll();
}

echo json_encode(['ok' => true, 'nome' => $_SESSION['representante_nome'], 'pedidos' => $pedidos]);
