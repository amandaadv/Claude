<?php
// Público (sem X-Api-Secret): lista os representantes ATIVOS pro seletor do
// formulário de pedido no site (index.html). Nunca inclui senha nem inativos.
require __DIR__ . '/config.php';
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');

$pdo = get_pdo();
foreach ([
    "ALTER TABLE representantes ADD COLUMN regiao VARCHAR(100) NULL",
] as $sql) {
    try { $pdo->exec($sql); } catch (Exception $e) { /* coluna ja existe */ }
}

$stmt = $pdo->query("
    SELECT id, nome, regiao
    FROM representantes
    WHERE ativo = 1
    ORDER BY nome
");
echo json_encode($stmt->fetchAll());
