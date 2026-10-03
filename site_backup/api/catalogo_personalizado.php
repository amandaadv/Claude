<?php
// Público: catálogo personalizado de um cliente específico, gerado com
// "Catálogo Personalizado" no programa. Pode incluir um ou mais catálogos.
// Retorna lista flat de produtos -- o frontend já agrupa por catalogo_nome
// com montarGrade(), então múltiplos catálogos aparecem em seções separadas
// automaticamente sem precisar de mudança no JS.
require __DIR__ . '/config.php';
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
header('Pragma: no-cache');

$codigo = trim((string)($_GET['c'] ?? ''));
if ($codigo === '') {
    http_response_code(400);
    echo json_encode(['erro' => 'código é obrigatório']);
    exit;
}

$pdo = get_pdo();
$pdo->exec("
    CREATE TABLE IF NOT EXISTS catalogos_personalizados (
        codigo VARCHAR(64) PRIMARY KEY,
        catalogo_nome VARCHAR(255) NOT NULL,
        cliente_nome VARCHAR(255) NOT NULL,
        criado_em DATETIME DEFAULT CURRENT_TIMESTAMP
    )
");
// Migração segura -- ignora se a coluna já existir
try {
    $pdo->exec("ALTER TABLE catalogos_personalizados ADD COLUMN catalogo_nomes TEXT NULL");
} catch (Exception $e) {}
try {
    $pdo->exec("ALTER TABLE produtos ADD COLUMN imagem_grande_arquivo VARCHAR(255) NULL");
} catch (Exception $e) {}
try {
    $pdo->exec("ALTER TABLE produtos ADD COLUMN medidas_disponiveis VARCHAR(255) NULL");
} catch (Exception $e) {}
try {
    $pdo->exec("ALTER TABLE produtos ADD COLUMN categoria VARCHAR(16) NULL");
} catch (Exception $e) {}

$stmt = $pdo->prepare("SELECT catalogo_nome, catalogo_nomes, cliente_nome FROM catalogos_personalizados WHERE codigo = ?");
$stmt->execute([$codigo]);
$link = $stmt->fetch();
if (!$link) {
    http_response_code(404);
    echo json_encode(['erro' => 'link não encontrado']);
    exit;
}

// Suporte a múltiplos catálogos (catalogo_nomes = JSON) com compat para
// links antigos que só têm catalogo_nome (string singular).
$nomes = null;
if (!empty($link['catalogo_nomes'])) {
    $decoded = json_decode($link['catalogo_nomes'], true);
    if (is_array($decoded) && count($decoded) > 0) {
        $nomes = $decoded;
    }
}
if ($nomes === null) {
    $nomes = [$link['catalogo_nome']];
}

// Monta placeholders pra IN (?, ?, ...) -- cada nome é um parâmetro separado
// pra evitar SQL injection.
$placeholders = implode(',', array_fill(0, count($nomes), '?'));
$stmt = $pdo->prepare("
    SELECT id, catalogo_nome, referencia, nome, imagem_arquivo, imagem_grande_arquivo, medidas_disponiveis, categoria
    FROM produtos
    WHERE ativo = 1 AND catalogo_nome IN ($placeholders)
    ORDER BY catalogo_nome, id
");
$stmt->execute($nomes);
$produtos = $stmt->fetchAll();

foreach ($produtos as &$p) {
    $p['imagem_url'] = '/produtos/' . rawurlencode($p['imagem_arquivo']);
    $p['imagem_grande_url'] = $p['imagem_grande_arquivo']
        ? '/produtos/' . rawurlencode($p['imagem_grande_arquivo'])
        : $p['imagem_url'];
    $p['medidas'] = $p['medidas_disponiveis']
        ? array_values(array_filter(array_map('trim', explode(',', $p['medidas_disponiveis']))))
        : [];
    unset($p['imagem_arquivo'], $p['imagem_grande_arquivo'], $p['medidas_disponiveis']);
}

echo json_encode([
    'cliente_nome'   => $link['cliente_nome'],
    'catalogo_nome'  => $nomes[0],           // compat
    'catalogo_nomes' => $nomes,
    'produtos'       => $produtos,
]);
