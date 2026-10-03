<?php
// Protegido (X-Api-Secret): cria um novo representante com credenciais de
// login pro painel deles (painel.html). Retorna o id gerado.
require __DIR__ . '/config.php';
header('Content-Type: application/json; charset=utf-8');
require_api_secret();

$body = json_body();
$nome    = trim($body['nome']    ?? '');
$usuario = trim($body['usuario'] ?? '');
$senha   = $body['senha']  ?? '';
$regiao  = trim($body['regiao']  ?? '');

if (!$nome || !$usuario || !$senha) {
    http_response_code(400);
    echo json_encode(['ok' => false, 'erro' => 'nome, usuario e senha são obrigatórios']);
    exit;
}
if (strlen($senha) < 4) {
    http_response_code(400);
    echo json_encode(['ok' => false, 'erro' => 'senha muito curta (mínimo 4 caracteres)']);
    exit;
}

$pdo = get_pdo();
foreach ([
    "ALTER TABLE representantes ADD COLUMN regiao VARCHAR(100) NULL",
] as $sql) {
    try { $pdo->exec($sql); } catch (Exception $e) { /* coluna ja existe */ }
}

$check = $pdo->prepare("SELECT id FROM representantes WHERE usuario = ?");
$check->execute([$usuario]);
if ($check->fetch()) {
    http_response_code(409);
    echo json_encode(['ok' => false, 'erro' => 'usuário já existe']);
    exit;
}

$hash = password_hash($senha, PASSWORD_DEFAULT);
$stmt = $pdo->prepare("
    INSERT INTO representantes (nome, usuario, senha_hash, ativo, regiao, criado_em)
    VALUES (?, ?, ?, 1, ?, NOW())
");
$stmt->execute([$nome, $usuario, $hash, $regiao]);
echo json_encode(['ok' => true, 'id' => (int)$pdo->lastInsertId()]);
