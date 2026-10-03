<?php
// Público: a cliente manda nome + telefone + a lista de itens escolhidos
// (cada um com catálogo + referência + quantidade -- ver index.html, que
// monta isso a partir do carrinho). catalogo_nome entra no match porque a
// mesma referência (ex. "REF 1") existe em vários catálogos diferentes --
// casar só por referencia (como a versão antiga fazia) arriscava pegar o
// produto errado quando duas REFs coincidiam por acaso.
require __DIR__ . '/config.php';
header('Content-Type: application/json; charset=utf-8');

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode(['erro' => 'método não permitido']);
    exit;
}

$body = json_body();
$nome = trim((string)($body['nome'] ?? ''));
$telefone = trim((string)($body['telefone'] ?? ''));
// Obrigatório -- qual representante cadastrado tirou o pedido com a cliente
// (ver index.html, seletor "Representante"). Vem como id, não texto livre,
// pra sempre casar com um representante de verdade cadastrado no app.
$representante_id = (int)($body['representante_id'] ?? 0);
$itens_enviados = is_array($body['itens'] ?? null) ? $body['itens'] : [];

if ($nome === '' || $telefone === '' || $representante_id <= 0 || count($itens_enviados) === 0) {
    http_response_code(400);
    echo json_encode(['erro' => 'nome, telefone, representante e ao menos um item são obrigatórios']);
    exit;
}
if (mb_strlen($nome) > 255 || mb_strlen($telefone) > 32) {
    http_response_code(400);
    echo json_encode(['erro' => 'nome ou telefone muito longos']);
    exit;
}

$pdo = get_pdo();
$pdo->exec("
    CREATE TABLE IF NOT EXISTS representantes (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nome VARCHAR(255) NOT NULL,
        usuario VARCHAR(100) NOT NULL UNIQUE,
        senha_hash VARCHAR(255) NOT NULL,
        ativo TINYINT(1) NOT NULL DEFAULT 1,
        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
");
$rep_stmt = $pdo->prepare("SELECT nome FROM representantes WHERE id = ? AND ativo = 1");
$rep_stmt->execute([$representante_id]);
$representante_nome = $rep_stmt->fetchColumn();
if (!$representante_nome) {
    http_response_code(400);
    echo json_encode(['erro' => 'representante inválido']);
    exit;
}
try {
    $pdo->exec("ALTER TABLE pedido_itens ADD COLUMN quantidade INT NOT NULL DEFAULT 1");
} catch (Exception $e) {
    // coluna já existe -- ok, só a primeira chamada de todas realmente cria.
}
try {
    // "representante" (texto) fica só pra exibição rápida sem precisar de
    // JOIN (ver pedidos.php / gui_page_website.py); "representante_id" é o
    // que de fato liga o pedido ao representante pro painel dele
    // (meus_pedidos_representante.php).
    $pdo->exec("ALTER TABLE clientes ADD COLUMN representante VARCHAR(255) NULL");
} catch (Exception $e) {
    // coluna já existe.
}
try {
    $pdo->exec("ALTER TABLE clientes ADD COLUMN representante_id INT NULL");
} catch (Exception $e) {
    // coluna já existe.
}
try {
    // Medida escolhida pela cliente pra esse item, quando o produto tem
    // medidas cadastradas (ver produtos.medidas_disponiveis/catalogo.php) --
    // NULL pra produto sem escolha de medida ou pedido feito antes disso.
    $pdo->exec("ALTER TABLE pedido_itens ADD COLUMN medida VARCHAR(50) NULL");
} catch (Exception $e) {
    // coluna já existe.
}

$produto_stmt = $pdo->prepare(
    "SELECT id FROM produtos WHERE catalogo_nome = ? AND referencia = ? AND ativo = 1 LIMIT 1"
);

$para_inserir = []; // [produto_id, quantidade, medida]
foreach ($itens_enviados as $item) {
    $catalogo = trim((string)($item['catalogo_nome'] ?? ''));
    $referencia = trim((string)($item['referencia'] ?? ''));
    $quantidade = (int)($item['quantidade'] ?? 1);
    // Texto livre vindo do cliente -- nunca validado contra a lista de
    // medidas cadastradas pro produto, mas o front-end só deixa escolher
    // entre elas; um valor fora disso aqui só significa payload adulterado,
    // sem risco (é só texto exibido na fila de produção).
    $medida = trim((string)($item['medida'] ?? ''));
    if ($medida !== '' && mb_strlen($medida) > 50) {
        $medida = mb_substr($medida, 0, 50);
    }
    if ($catalogo === '' || $referencia === '' || $quantidade < 1) {
        continue;
    }
    $produto_stmt->execute([$catalogo, $referencia]);
    $produto_id = $produto_stmt->fetchColumn();
    if ($produto_id) {
        // Cap alto só pra travar um valor absurdo vindo de um payload
        // adulterado -- longe de qualquer pedido real dessa loja.
        $para_inserir[] = [$produto_id, min($quantidade, 999), $medida !== '' ? $medida : null];
    }
}

if (count($para_inserir) === 0) {
    http_response_code(400);
    echo json_encode(['erro' => 'nenhum produto válido selecionado']);
    exit;
}

$pdo->beginTransaction();

$stmt = $pdo->prepare("INSERT INTO clientes (nome, telefone, representante, representante_id) VALUES (?, ?, ?, ?)");
$stmt->execute([$nome, $telefone, $representante_nome, $representante_id]);
$cliente_id = $pdo->lastInsertId();

$stmt = $pdo->prepare("INSERT INTO pedidos (cliente_id, status) VALUES (?, 'pendente')");
$stmt->execute([$cliente_id]);
$pedido_id = $pdo->lastInsertId();

$stmt = $pdo->prepare("INSERT INTO pedido_itens (pedido_id, produto_id, quantidade, medida) VALUES (?, ?, ?, ?)");
foreach ($para_inserir as [$produto_id, $quantidade, $medida]) {
    $stmt->execute([$pedido_id, $produto_id, $quantidade, $medida]);
}

$pdo->commit();

echo json_encode(['ok' => true, 'pedido_id' => $pedido_id]);
