<?php
// ATENÇÃO: apaga TODOS os representantes. Rode uma vez e delete esse arquivo.
require __DIR__ . '/config.php';
require_api_secret();
$pdo = get_pdo();
$pdo->exec("DELETE FROM representantes");
echo json_encode(['ok' => true, 'mensagem' => 'todos os representantes apagados']);
