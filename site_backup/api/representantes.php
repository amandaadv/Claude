<?php
// Protegido (X-Api-Secret): lista todos os representantes (ativos e inativos)
// pro programa do computador mostrar na aba de Representantes.
// Nunca inclui a senha.
require __DIR__ . '/config.php';
header('Content-Type: application/json; charset=utf-8');
require_api_secret();

$pdo = get_pdo();
foreach ([
    "ALTER TABLE representantes ADD COLUMN regiao VARCHAR(100) NULL",
] as $sql) {
    try { $pdo->exec($sql); } catch (Exception $e) { /* coluna ja existe */ }
}

$stmt = $pdo->query("
    SELECT id, nome, usuario, ativo, regiao, criado_em
    FROM representantes
    ORDER BY nome
");
echo json_encode($stmt->fetchAll());
