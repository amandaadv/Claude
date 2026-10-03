<?php
// Protegido (X-Api-Secret): lista os pedidos, com os itens de cada um, pro
// programa do computador mostrar e a operadora validar/excluir.
require __DIR__ . '/config.php';
header('Content-Type: application/json; charset=utf-8');
require_api_secret();

$pdo = get_pdo();
try {
    // Mesma coluna que finalizar.php cria -- garantida aqui também, porque
    // esse ALTER lá só roda depois da validação de nome/telefone/itens, e
    // um pedido antigo consultado aqui antes de qualquer pedido novo passar
    // por lá quebraria essa consulta com "coluna não existe".
    $pdo->exec("ALTER TABLE pedido_itens ADD COLUMN medida VARCHAR(50) NULL");
} catch (Exception $e) {
    // coluna ja existe.
}
try {
    // Mesma coluna que finalizar.php cria -- garantida aqui também pelo
    // mesmo motivo do ALTER de "medida" acima.
    $pdo->exec("ALTER TABLE clientes ADD COLUMN representante VARCHAR(255) NULL");
} catch (Exception $e) {
    // coluna ja existe.
}

$status = $_GET['status'] ?? 'pendente';
$stmt = $pdo->prepare("
    SELECT p.id AS pedido_id, p.status, p.criado_em, c.nome, c.telefone, c.representante
    FROM pedidos p JOIN clientes c ON c.id = p.cliente_id
    WHERE p.status = ?
    ORDER BY p.criado_em ASC
");
$stmt->execute([$status]);
$pedidos = $stmt->fetchAll();

// quantidade: pedido_itens ganhou essa coluna quando o carrinho do site
// passou a deixar escolher mais de uma unidade por figura (ver
// finalizar.php) -- COALESCE cobre um pedido antigo feito antes disso, sem
// a coluna ainda existir com valor pra ele.
$itens_stmt = $pdo->prepare("
    SELECT pr.id AS produto_id, pr.referencia, pr.nome, COALESCE(pi.quantidade, 1) AS quantidade, pi.medida
    FROM pedido_itens pi JOIN produtos pr ON pr.id = pi.produto_id
    WHERE pi.pedido_id = ?
");

foreach ($pedidos as &$pedido) {
    $itens_stmt->execute([$pedido['pedido_id']]);
    $pedido['itens'] = $itens_stmt->fetchAll();
}

echo json_encode($pedidos);
