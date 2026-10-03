<?php
// Protegido (X-Api-Secret): o programa do computador manda um catálogo (nome +
// REF + nome da arte + imagem em base64) pra aparecer no site como uma seção
// própria. Só substitui os produtos DESSE catálogo -- outros catálogos já
// publicados continuam intactos, cada um sua própria seção na vitrine.
//
// origem_ip: guarda a identidade de quem publicou (get_caller_identity() em
// config.php -- o id fixo que o programa manda em X-Machine-Id, com o IP
// só como fallback). Usado por catalogo.php pra só mostrar pro cliente
// final o que veio da máquina matriz (config_site.matriz_ip, definida por
// definir_matriz.php), e por excluir_catalogo.php/meus_catalogos.php pra
// cada computador só conseguir gerenciar o que ele mesmo publicou.
//
// MODO EM LOTES (catálogos grandes): mandar centenas de imagens em base64
// numa única requisição estourava tempo/memória do PHP e o catálogo ficava
// só com parte das figuras. Agora o programa pode mandar vários pedidos
// pequenos, todos com "lote": {"sessao": "<token>", "ultimo": false} -- cada
// um só grava as figuras dele (upsert por catálogo+REF, então repetir um
// lote é inofensivo) e NADA some da vitrine enquanto isso; só o pedido final
// ("ultimo": true, pode vir sem produtos) desativa as figuras do catálogo
// que não vieram nessa sessão. Se cair no meio, o site continua com o que
// já tinha (mais o que já chegou), nunca com o catálogo pela metade.
// Sem "lote" no corpo o comportamento é exatamente o antigo (tudo de uma vez).
// GET responde {"lotes": true} -- é como o programa descobre que esse
// servidor já sabe receber em lotes.
@ini_set('memory_limit', '512M');
@set_time_limit(300);
require __DIR__ . '/config.php';
header('Content-Type: application/json; charset=utf-8');
require_api_secret();

if ($_SERVER['REQUEST_METHOD'] === 'GET') {
    echo json_encode(['ok' => true, 'lotes' => true]);
    exit;
}
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode(['erro' => 'método não permitido']);
    exit;
}

$body = json_body();
$catalogo = trim((string)($body['catalogo'] ?? ''));
$produtos = is_array($body['produtos'] ?? null) ? $body['produtos'] : [];
$origem_ip = get_caller_identity();

// Categoria do catálogo inteiro ('aplique' | 'faixa'): decide quais botões de
// tipo/medida o site mostra em cada figura (ver regras_medidas.json). Sem
// categoria (null) o catálogo continua com o "Adicionar" antigo.
$categoria = strtolower(trim((string)($body['categoria'] ?? '')));
if (!in_array($categoria, ['aplique', 'faixa'], true)) {
    $categoria = null;
}

$lote = is_array($body['lote'] ?? null) ? $body['lote'] : null;
$sessao = $lote ? (string)($lote['sessao'] ?? '') : '';
$lote_final = $lote && !empty($lote['ultimo']);
if ($lote && !preg_match('/^[A-Za-z0-9]{8,64}$/', $sessao)) {
    http_response_code(400);
    echo json_encode(['erro' => 'lote.sessao inválida']);
    exit;
}

if ($catalogo === '') {
    http_response_code(400);
    echo json_encode(['erro' => 'catalogo é obrigatório']);
    exit;
}
// O pedido final de uma sessão em lotes pode vir sem produtos (só "fecha" a
// publicação); qualquer outro pedido sem produtos continua sendo erro.
if (count($produtos) === 0 && !$lote_final) {
    http_response_code(400);
    echo json_encode(['erro' => 'lista de produtos vazia']);
    exit;
}

$pasta_imagens = __DIR__ . '/../produtos';
if (!is_dir($pasta_imagens)) {
    mkdir($pasta_imagens, 0755, true);
}

$pdo = get_pdo();
try {
    $pdo->exec("ALTER TABLE produtos ADD COLUMN origem_ip VARCHAR(64) NULL");
} catch (Exception $e) {
    // coluna ja existe -- ok, so a primeira chamada de todas realmente cria.
}
try {
    // Imagem maior, separada da miniatura da grade (imagem_arquivo) --
    // usada só no zoom/popup do site, pra não sair borrada quando
    // amplia a miniatura pequena (que é feita pequena de propósito, pra
    // carregar rápido na grade local do programa também).
    $pdo->exec("ALTER TABLE produtos ADD COLUMN imagem_grande_arquivo VARCHAR(255) NULL");
} catch (Exception $e) {
    // coluna ja existe.
}
try {
    // Medidas que a cliente pode escolher no site pra esse REF (ex:
    // "29cm,35cm"), cadastradas no programa -- NULL/vazio = sem escolha de
    // medida pra esse REF. Não confundir com o tamanho de impressão/produção
    // (esse nunca aparece pra cliente final).
    $pdo->exec("ALTER TABLE produtos ADD COLUMN medidas_disponiveis VARCHAR(255) NULL");
} catch (Exception $e) {
    // coluna ja existe.
}
try {
    // 'aplique' | 'faixa' | NULL -- ver $categoria acima.
    $pdo->exec("ALTER TABLE produtos ADD COLUMN categoria VARCHAR(16) NULL");
} catch (Exception $e) {
    // coluna ja existe.
}
try {
    // Token da publicação em lotes que gravou a linha por último -- o pedido
    // final usa isso pra saber o que NÃO veio nessa sessão e desativar.
    $pdo->exec("ALTER TABLE produtos ADD COLUMN pub_sessao VARCHAR(64) NULL");
} catch (Exception $e) {
    // coluna ja existe.
}

$pdo->beginTransaction();

// Desativa só os produtos DESSE catálogo primeiro -- o que vier nesse lote
// fica ativo de novo; o que não vier (foi removido no catálogo local) some
// da vitrine sem apagar o histórico de pedidos antigos. Outros catálogos
// (catalogo_nome diferente) nunca são tocados aqui.
// Em lotes NÃO desativa nada aqui (ver o pedido final lá embaixo) -- senão o
// primeiro lote esconderia da vitrine todo o resto do catálogo até o último
// chegar.
if (!$lote) {
    $stmt = $pdo->prepare("UPDATE produtos SET ativo = 0 WHERE catalogo_nome = ?");
    $stmt->execute([$catalogo]);
}

$stmt = $pdo->prepare("
    INSERT INTO produtos (catalogo_nome, referencia, nome, imagem_arquivo, imagem_grande_arquivo, ativo, origem_ip, medidas_disponiveis, pub_sessao, categoria)
    VALUES (:catalogo, :ref, :nome, :arquivo, :arquivo_grande, 1, :origem_ip, :medidas, :sessao, :categoria)
    ON DUPLICATE KEY UPDATE nome = VALUES(nome), imagem_arquivo = VALUES(imagem_arquivo),
        imagem_grande_arquivo = COALESCE(VALUES(imagem_grande_arquivo), imagem_grande_arquivo),
        ativo = 1, origem_ip = VALUES(origem_ip), medidas_disponiveis = VALUES(medidas_disponiveis),
        pub_sessao = VALUES(pub_sessao),
        categoria = COALESCE(VALUES(categoria), categoria)
");
$old_file_stmt = $pdo->prepare(
    "SELECT imagem_arquivo, imagem_grande_arquivo FROM produtos WHERE catalogo_nome = :catalogo AND referencia = :ref"
);

$publicados = 0;
foreach ($produtos as $produto) {
    $ref = trim((string)($produto['referencia'] ?? ''));
    $nome = trim((string)($produto['nome'] ?? ''));
    $imagem_base64 = (string)($produto['imagem_base64'] ?? '');
    if ($ref === '' || $imagem_base64 === '') {
        continue;
    }

    $medidas_lista = is_array($produto['medidas'] ?? null) ? $produto['medidas'] : [];
    $medidas_lista = array_filter(array_map('trim', array_map('strval', $medidas_lista)), fn($m) => $m !== '');
    $medidas_disponiveis = $medidas_lista ? implode(',', $medidas_lista) : null;

    $bytes = base64_decode($imagem_base64, true);
    if ($bytes === false) {
        continue;
    }

    // The hash makes the filename change whenever the picture's actual
    // content does -- necessary because Hostinger's CDN (and every
    // browser) caches /produtos/*.jpg for a full week (Cache-Control:
    // max-age=604800) keyed by PATH ONLY: overwriting the same filename
    // in place (the old behavior) left everyone -- customers' browsers,
    // the CDN edge, even a "hard refresh" against the CDN -- still
    // showing whatever picture used to be there until that week was up,
    // no matter how many times the real file on disk got corrected. A
    // republish with the exact same picture keeps the exact same
    // filename (same hash), so it doesn't create pointless new files.
    $arquivo = preg_replace('/[^A-Za-z0-9_.-]/', '_', $catalogo . '_' . $ref)
        . '_' . substr(md5($bytes), 0, 10) . '.jpg';

    $old_file_stmt->execute(['catalogo' => $catalogo, 'ref' => $ref]);
    $antigos = $old_file_stmt->fetch();
    $arquivo_antigo = $antigos ? $antigos['imagem_arquivo'] : null;
    $arquivo_grande_antigo = $antigos ? $antigos['imagem_grande_arquivo'] : null;
    if ($arquivo_antigo && $arquivo_antigo !== $arquivo) {
        @unlink($pasta_imagens . '/' . $arquivo_antigo);
    }

    file_put_contents($pasta_imagens . '/' . $arquivo, $bytes);

    // imagem_grande_base64 é opcional -- um catálogo publicado antes dessa
    // função existir simplesmente não manda esse campo, e o produto
    // continua usando a miniatura pequena no zoom até ser republicado.
    $arquivo_grande = null;
    $imagem_grande_base64 = (string)($produto['imagem_grande_base64'] ?? '');
    if ($imagem_grande_base64 !== '') {
        $bytes_grande = base64_decode($imagem_grande_base64, true);
        if ($bytes_grande !== false) {
            $arquivo_grande = preg_replace('/[^A-Za-z0-9_.-]/', '_', $catalogo . '_' . $ref)
                . '_grande_' . substr(md5($bytes_grande), 0, 10) . '.jpg';
            if ($arquivo_grande_antigo && $arquivo_grande_antigo !== $arquivo_grande) {
                @unlink($pasta_imagens . '/' . $arquivo_grande_antigo);
            }
            file_put_contents($pasta_imagens . '/' . $arquivo_grande, $bytes_grande);
        }
    }

    $stmt->execute([
        'catalogo' => $catalogo, 'ref' => $ref, 'nome' => $nome ?: null, 'arquivo' => $arquivo,
        'arquivo_grande' => $arquivo_grande, 'origem_ip' => $origem_ip ?: null,
        'medidas' => $medidas_disponiveis, 'sessao' => $lote ? $sessao : null,
        'categoria' => $categoria,
    ]);
    $publicados++;
}

$pdo->commit();

$resposta = ['ok' => true, 'publicados' => $publicados, 'lotes' => true];

if ($lote_final) {
    // Só agora, com todos os lotes já gravados: some da vitrine o que estava
    // publicado nesse catálogo e NÃO veio em nenhum lote dessa sessão
    // (foi removido no catálogo local). Devolve também quantas figuras ativas
    // o catálogo tem de fato -- o programa confere isso contra o que enviou.
    $stmt = $pdo->prepare(
        "UPDATE produtos SET ativo = 0 WHERE catalogo_nome = ? AND (pub_sessao IS NULL OR pub_sessao <> ?)");
    $stmt->execute([$catalogo, $sessao]);
    $resposta['desativados'] = $stmt->rowCount();

    $stmt = $pdo->prepare("SELECT COUNT(*) FROM produtos WHERE catalogo_nome = ? AND ativo = 1");
    $stmt->execute([$catalogo]);
    $resposta['ativos'] = (int)$stmt->fetchColumn();
}

echo json_encode($resposta);
