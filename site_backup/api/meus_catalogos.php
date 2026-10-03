<?php
// Protegido (X-Api-Secret): lista os nomes de catálogo que ESSA MESMA
// máquina (pelo id fixo que ela manda, ou o IP como fallback -- ver
// get_caller_identity em config.php) publicou e ainda estão ativos -- usado
// pela sincronização automática do programa (ver website_sync.sync_catalogs
// no app) pra saber o que ela pode limpar sem nunca arriscar tocar em
// catálogos publicados por outro computador.
require __DIR__ . '/config.php';
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
header('Pragma: no-cache');
require_api_secret();

$origem_ip = get_caller_identity();

$pdo = get_pdo();
$stmt = $pdo->prepare("
    SELECT DISTINCT catalogo_nome FROM produtos WHERE ativo = 1 AND origem_ip = ?
");
$stmt->execute([$origem_ip]);
$nomes = $stmt->fetchAll(PDO::FETCH_COLUMN);

echo json_encode($nomes);
