<?php
// Protegido (X-Api-Secret): lista os pedidos, com os itens de cada um, pro
// programa do computador mostrar e a operadora validar/excluir.
require __DIR__ . '/config.php';
require __DIR__ . '/regras_medidas.php';
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

foreach ([
    "ALTER TABLE pedido_itens ADD COLUMN tipo VARCHAR(20) NULL",
    "ALTER TABLE produtos ADD COLUMN categoria VARCHAR(16) NULL",
] as $sql) {
    try {
        $pdo->exec($sql);
    } catch (Exception $e) {
        // coluna ja existe.
    }
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
    SELECT pi.id AS item_id, pr.id AS produto_id, pr.catalogo_nome, pr.categoria, pr.referencia, pr.nome,
           COALESCE(pi.quantidade, 1) AS quantidade, pi.medida, pi.tipo
    FROM pedido_itens pi JOIN produtos pr ON pr.id = pi.produto_id
    WHERE pi.pedido_id = ?
    ORDER BY pi.id
");

foreach ($pedidos as &$pedido) {
    $itens_stmt->execute([$pedido['pedido_id']]);
    $itens = $itens_stmt->fetchAll();
    foreach ($itens as &$item) {
        // "medida" continua sendo o valor cru (id da regra, ex. '110x100', ou
        // o texto livre antigo); o resto é pra o programa mostrar e produzir:
        //  - tipo / tipo_rotulo: 'termo_colante' / "Termo colante"
        //  - texto: "Termo colante · 110 x 100 mm" (pronto pra exibir)
        //  - regra: {modo: proporcional|fixa, maior, menor, qtd} da medida escolhida
        $regra = regras_achar($item['categoria'], $item['tipo'], $item['medida']);
        $item['tipo_rotulo'] = $item['tipo'] ? regras_rotulo_tipo($item['tipo']) : null;
        $item['texto'] = regras_texto_item($item['categoria'], $item['tipo'], $item['medida']);
        $item['regra'] = $regra ? [
            'modo' => $regra['modo'], 'maior' => $regra['maior'], 'menor' => $regra['menor'], 'qtd' => $regra['qtd'],
        ] : null;
    }
    unset($item);
    $pedido['itens'] = $itens;
}

echo json_encode($pedidos);
