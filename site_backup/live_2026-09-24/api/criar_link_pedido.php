<?php
// Protegido (X-Api-Secret): o programa do computador manda nome + telefone
// (botão "WebPedido") e recebe o código do link "meu pedido" dessa cliente
// (pedido.php?c=codigo). Idempotente: o mesmo nome+telefone(+escopo)
// normalizados -- ver pedido_util.php -- sempre devolvem o MESMO código.
//
// Dois modos:
//  - sem "escopo": link MESCLADO (todos os pedidos da cliente).
//  - com "escopo" (ex. "prod-58") + "itens" [{catalogo_nome, referencia,
//    quantidade, medida?}]: link que mostra EXATAMENTE essa lista (foto de
//    uma produção). Chamar de novo pro mesmo escopo reaproveita o código e
//    atualiza a lista.
require __DIR__ . '/config.php';
require __DIR__ . '/pedido_util.php';
header('Content-Type: application/json; charset=utf-8');
require_api_secret();

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode(['erro' => 'método não permitido']);
    exit;
}

$body = json_body();
$nome = trim((string)($body['nome'] ?? ''));
$telefone = trim((string)($body['telefone'] ?? ''));
$nome_key = pedido_normalizar_nome($nome);
$telefone_key = pedido_normalizar_telefone($telefone);

if ($nome_key === '' || $telefone_key === '') {
    http_response_code(400);
    echo json_encode(['erro' => 'nome e telefone são obrigatórios']);
    exit;
}

$escopo = trim((string)($body['escopo'] ?? ''));
if ($escopo !== '' && !preg_match('/^[A-Za-z0-9_-]{1,32}$/', $escopo)) {
    http_response_code(400);
    echo json_encode(['erro' => 'escopo inválido']);
    exit;
}
$itens_json = null;
if ($escopo !== '') {
    $itens = pedido_sanear_itens($body['itens'] ?? null);
    if (count($itens) === 0) {
        http_response_code(400);
        echo json_encode(['erro' => 'itens são obrigatórios quando há escopo']);
        exit;
    }
    $itens_json = json_encode($itens, JSON_UNESCAPED_UNICODE);
}

$pdo = get_pdo();
pedido_garantir_tabela_links($pdo);

$busca = $pdo->prepare("SELECT codigo FROM pedido_links WHERE nome_key = ? AND telefone_key = ? AND escopo = ?");
$busca->execute([$nome_key, $telefone_key, $escopo]);
$codigo = $busca->fetchColumn();

if ($codigo) {
    if ($escopo !== '') {
        // Mesma produção de novo: mesmo link, lista atualizada.
        $pdo->prepare("UPDATE pedido_links SET itens_json = ?, nome_exibicao = ? WHERE codigo = ?")
            ->execute([$itens_json, mb_substr($nome, 0, 255), $codigo]);
    }
} else {
    // Código = nome sem acento/espaço + 10 hex aleatórios (40 bits): legível
    // no WhatsApp e não dá pra adivinhar o link de outra cliente -- a página
    // mostra o nome e os pedidos dela, então o código é a única proteção.
    $base = trim((string)preg_replace('/[^a-z0-9]+/', '-', $nome_key), '-');
    if ($base === '') {
        $base = 'cliente';
    }
    $base = substr($base, 0, 30);
    $codigo = $base . '-' . bin2hex(random_bytes(5));

    try {
        $ins = $pdo->prepare("
            INSERT INTO pedido_links (codigo, nome_exibicao, nome_key, telefone_key, escopo, itens_json)
            VALUES (?, ?, ?, ?, ?, ?)
        ");
        $ins->execute([$codigo, mb_substr($nome, 0, 255), $nome_key, $telefone_key, $escopo, $itens_json]);
    } catch (PDOException $e) {
        // Duas chamadas ao mesmo tempo pra mesma cliente: a outra ganhou a
        // corrida no índice único -- reusa o código dela.
        $busca->execute([$nome_key, $telefone_key, $escopo]);
        $existente = $busca->fetchColumn();
        if (!$existente) {
            throw $e;
        }
        $codigo = $existente;
    }
}

$resposta = ['ok' => true, 'codigo' => $codigo];
if ($escopo !== '') {
    // Itens que o programa mandou mas que não existem no site (catálogo nunca
    // publicado, REF removida...) -- não aparecem na página; o programa avisa.
    [, $faltando] = pedido_linhas_do_snapshot($pdo, $itens_json);
    $resposta['faltando'] = array_slice($faltando, 0, 50);
    $resposta['total_faltando'] = count($faltando);
}
echo json_encode($resposta, JSON_UNESCAPED_UNICODE);
