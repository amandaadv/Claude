<?php
// Público: lista os produtos ativos pro site do cliente mostrar na galeria,
// agrupados por catálogo (cada catálogo importado vira sua própria seção).
//
// Só mostra produtos cuja publicação veio do IP marcado como matriz (tabela
// config_site, definido por definir_matriz.php) -- o negócio roda esse
// programa em mais de um computador, cada um com seus próprios catálogos
// locais, mas só UM (a matriz) deve refletir na vitrine pública. Os outros
// continuam funcionando normalmente pra uso local, só não publicam aqui.
require __DIR__ . '/config.php';
header('Content-Type: application/json; charset=utf-8');
// This is the ONE endpoint the storefront reads on every page load -- it
// must never be stuck showing a stale catalog after a publish. Explicit
// no-store beats depending on Hostinger's own cache-clear API (confirmed
// unreliable: it returned a bare 500 "[Hosting:9999] Request failed" when
// tested live) -- browsers and most reverse proxies/CDNs in front of this
// honor Cache-Control over anything a platform-level cache might otherwise
// apply by default to a GET response.
header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
header('Pragma: no-cache');

$pdo = get_pdo();
$pdo->exec("
    CREATE TABLE IF NOT EXISTS catalogos_ordem (
        catalogo_nome VARCHAR(255) PRIMARY KEY,
        ordem INT NOT NULL DEFAULT 0
    )
");
$pdo->exec("
    CREATE TABLE IF NOT EXISTS config_site (
        chave VARCHAR(64) PRIMARY KEY,
        valor VARCHAR(255) NOT NULL
    )
");
try {
    // Mesma coluna que publicar.php cria -- garantida aqui também pra essa
    // consulta nunca quebrar por rodar antes da primeira publicação depois
    // dessa mudança (ordem de deploy entre os dois arquivos não importa).
    $pdo->exec("ALTER TABLE produtos ADD COLUMN imagem_grande_arquivo VARCHAR(255) NULL");
} catch (Exception $e) {
    // coluna ja existe.
}
try {
    $pdo->exec("ALTER TABLE produtos ADD COLUMN medidas_disponiveis VARCHAR(255) NULL");
} catch (Exception $e) {
    // coluna ja existe.
}
try {
    // 'aplique' | 'faixa' | NULL -- decide os botões de tipo/medida no site
    // (ver publicar.php/regras_medidas.json); NULL = "Adicionar" antigo.
    $pdo->exec("ALTER TABLE produtos ADD COLUMN categoria VARCHAR(16) NULL");
} catch (Exception $e) {
    // coluna ja existe.
}

$matriz_stmt = $pdo->query("SELECT valor FROM config_site WHERE chave = 'matriz_ip'");
$matriz_ip = $matriz_stmt->fetchColumn();

if ($matriz_ip === false || $matriz_ip === '') {
    // Sem matriz configurada ainda -- mostra tudo (comportamento antigo)
    // em vez de esvaziar a vitrine por falta de configuração.
    $stmt = $pdo->query("
        SELECT p.id, p.catalogo_nome, p.referencia, p.nome, p.imagem_arquivo, p.imagem_grande_arquivo, p.medidas_disponiveis, p.categoria
        FROM produtos p
        LEFT JOIN catalogos_ordem o ON o.catalogo_nome = p.catalogo_nome
        WHERE p.ativo = 1
        ORDER BY COALESCE(o.ordem, 999999), p.catalogo_nome, p.id
    ");
} else {
    $stmt = $pdo->prepare("
        SELECT p.id, p.catalogo_nome, p.referencia, p.nome, p.imagem_arquivo, p.imagem_grande_arquivo, p.medidas_disponiveis, p.categoria
        FROM produtos p
        LEFT JOIN catalogos_ordem o ON o.catalogo_nome = p.catalogo_nome
        WHERE p.ativo = 1 AND p.origem_ip = ?
        ORDER BY COALESCE(o.ordem, 999999), p.catalogo_nome, p.id
    ");
    $stmt->execute([$matriz_ip]);
}
$produtos = $stmt->fetchAll();

foreach ($produtos as &$p) {
    $p['imagem_url'] = '/produtos/' . rawurlencode($p['imagem_arquivo']);
    // Sem imagem grande própria (catálogo publicado antes dessa função
    // existir, ou original perdido) -- o zoom cai de volta na miniatura
    // pequena, em vez de ficar sem imagem nenhuma.
    $p['imagem_grande_url'] = $p['imagem_grande_arquivo']
        ? '/produtos/' . rawurlencode($p['imagem_grande_arquivo'])
        : $p['imagem_url'];
    $p['medidas'] = $p['medidas_disponiveis']
        ? array_values(array_filter(array_map('trim', explode(',', $p['medidas_disponiveis']))))
        : [];
    unset($p['imagem_arquivo'], $p['imagem_grande_arquivo'], $p['medidas_disponiveis']);
}

echo json_encode($produtos);
